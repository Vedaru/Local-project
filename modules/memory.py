import os
import chromadb
import time
import uuid
import re
import jieba
import jieba.posseg as pseg
from .config import data_dir

class MemoryManager:
    # 语义差异阈值：越小越严格（0.3-0.4是推荐区间）
    # 当新旧记忆距离小于此值，且内容不同时，触发覆盖删除
    OVERRIDE_THRESHOLD = 0.35

    # 更加严谨的切割符
    PUNCTUATION = ['。', '！', '？', '!', '?', '\n', '；', ';', '：', ':', '，', ',']

    def __init__(self):
        os.makedirs(data_dir, exist_ok=True)
        print("\n" + "="*50)
        print(" [记忆系统] 正在初始化持久化存储...")
        try:
            self.client = chromadb.PersistentClient(path=data_dir)
            self.collection = self.client.get_or_create_collection(name="seeka_memory")
            self.enabled = True
            print(f" [记忆系统] 状态: 运行中 (存储路径: {data_dir})")
        except Exception as e:
            print(f" [错误] 记忆系统初始化失败: {e}")
            self.collection = None
            self.enabled = False
        print("="*50 + "\n")

    def extract_entities(self, text):
        """提取文本中的核心名词"""
        entities = set()
        words = pseg.cut(text)
        for word, flag in words:
            if flag in ['nr', 'ns', 'nt', 'nz', 'n']:
                if len(word) >= 2:
                    entities.add(word)
        
        if entities:
            print(f"  └─ [实体提取] 识别到核心词: {list(entities)}")
        return entities

    def apply_logical_override(self, conversation):
        """
        基于语义相似度的逻辑覆盖 (冲突类型 B)
        """
        if not self.enabled or not self.collection:
            return
        
        print(f" [分析] 开始逻辑冲突检测...")
        current_entities = self.extract_entities(conversation)
        
        if not current_entities:
            print("  └─ [跳过] 对话中未提取到关键实体，不执行覆盖检查。")
            return

        for entity in current_entities:
            try:
                # 检索关于该实体的旧记录
                results = self.collection.query(
                    query_texts=[entity],
                    n_results=3,
                    include=["documents", "metadatas", "distances"]
                )
                
                docs = results.get('documents', [[]])[0]
                distances = results.get('distances', [[]])[0]
                ids = results.get('ids', [[]])[0]

                if not docs:
                    continue

                to_delete = []
                for i in range(len(docs)):
                    old_doc = docs[i]
                    dist = distances[i]
                    doc_id = ids[i]

                    # 核心逻辑判定：语义距离小于阈值，但文本内容不同
                    if dist < self.OVERRIDE_THRESHOLD:
                        if old_doc.strip() != conversation.strip():
                            print(f"  ├─ [覆盖触发] 发现高度相似的旧记忆!")
                            print(f"  │  ├─ 实体: '{entity}'")
                            print(f"  │  ├─ 旧记忆: \"{old_doc}\"")
                            print(f"  │  ├─ 相似度距离: {dist:.4f} (阈值: {self.OVERRIDE_THRESHOLD})")
                            to_delete.append(doc_id)
                        else:
                            print(f"  ├─ [忽略] 记忆完全一致，无需处理。")
                    else:
                        # 距离较大，说明是同一个实体的不同侧面描述，不属于冲突
                        pass

                if to_delete:
                    self.collection.delete(ids=to_delete)
                    print(f"  └─ [清理成功] 已删除 {len(to_delete)} 条陈旧或冲突的记忆。")
                    
            except Exception as e:
                print(f"  └─ [错误] 逻辑覆盖过程出错: {e}")

    def clean_text(self, text):
        """清洗文本"""
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s' + "".join(self.PUNCTUATION) + r']', '', text)
        return re.sub(r'\s+', ' ', text).strip()

    def store_memory(self, conversation):
        """存储新记忆（包含覆盖流程）"""
        if not self.enabled:
            return
        
        clean_conv = self.clean_text(conversation)
        if len(clean_conv) < 3:
            return

        print(f"\n[记忆入库流水线] 处理文本: \"{clean_conv}\"")
        
        try:
            # 1. 冲突检测与覆盖
            self.apply_logical_override(clean_conv)
            
            # 2. 存储新记忆
            self.collection.add(
                documents=[clean_conv],
                metadatas=[{"timestamp": time.time(), "access_count": 0}],
                ids=[str(uuid.uuid4())]
            )
            print(f" └─ [完成] 新记忆已存入向量数据库。")
        except Exception as e:
            print(f" └─ [错误] 存储失败: {e}")

    def retrieve_memories(self, query, n_results=2):
        """检索记忆"""
        if not self.enabled:
            return ""
        
        print(f"\n[记忆检索] 查询内容: \"{query}\"")
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )
            
            memories = results.get('documents', [[]])[0] if results.get('documents') else []
            dists = results.get('distances', [[]])[0] if results.get('distances') else []
            
            if memories:
                for i, m in enumerate(memories):
                    print(f"  ├─ 匹配到记忆: \"{m}\" (距离: {dists[i]:.4f})")
                
                # 更新访问权重
                ids = results.get('ids', [[]])[0]
                for i, doc_id in enumerate(ids):
                    meta = results['metadatas'][0][i] or {}
                    meta['access_count'] = meta.get('access_count', 0) + 1
                    self.collection.update(ids=[doc_id], metadatas=[meta])
            else:
                print("  └─ 未发现相关记忆。")
            
            return "\n".join(memories) if memories else ""
        except Exception as e:
            print(f"  └─ [错误] 检索失败: {e}")
            return ""

    def cleanup_old_memories(self):
        """清理过期记忆"""
        if not self.enabled:
            return
        print(f"\n[系统维护] 正在扫描陈旧记忆...")
        try:
            results = self.collection.get(include=["metadatas"])
            current_time = time.time()
            to_delete = []
            for i, metadata in enumerate(results["metadatas"]):
                if metadata:
                    # 15天且访问量为0
                    if current_time - metadata.get("timestamp", 0) > 15 * 86400:
                        if metadata.get("access_count", 0) < 1:
                            to_delete.append(results["ids"][i])
            
            if to_delete:
                self.collection.delete(ids=to_delete)
                print(f" └─ [维护完成] 删除了 {len(to_delete)} 条无价值记忆。")
            else:
                print(" └─ [维护完成] 库内记忆均处于活跃状态。")
        except Exception as e:
            print(f" └─ [错误] 维护失败: {e}")