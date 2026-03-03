"""
技能管理器 — 用于记录/检索 AI 学习到的操作流程 (SOP)

使用独立的 ChromaDB 存储（不再依赖旧的 MemoryStorage）
"""

import os
import uuid
from typing import Optional

import chromadb

from ..config import MODEL_NAME, data_dir
from ..logging_config import get_logger

logger = get_logger("Memory.Skills")


class SkillManager:
    def __init__(self, storage=None, db_path: str = None):
        """初始化技能管理器。

        Args:
            storage: (已废弃) 旧的 MemoryStorage 实例，现忽略此参数以保持向后兼容
            db_path: ChromaDB 数据库路径，默认使用 data/chroma_db
        """
        path = db_path or os.path.join(data_dir)
        os.makedirs(path, exist_ok=True)
        try:
            self.client = chromadb.PersistentClient(path=path)
            self.collection = self.client.get_or_create_collection(
                name="agent_skills", metadata={"description": "存放 AI 学习到的标准操作程序 (SOP)"}
            )
        except Exception as e:
            logger.error(f"创建或获取 agent_skills collection 失败: {e}")
            self.client = None
            self.collection = None

    def retrieve_skill(self, task_description: str) -> Optional[str]:
        """根据任务描述检索最相关的一条技能 SOP。

        如果距离低于阈值 (0.5)，返回 SOP 文本；否则返回 None。
        """
        if not self.collection:
            return None
        try:
            results = self.collection.query(
                query_texts=[task_description], n_results=1, include=["documents", "distances"]
            )
            docs = results.get("documents", [[]])[0]
            dists = results.get("distances", [[]])[0]
            if docs and dists:
                dist = dists[0]
                if dist is not None and dist < 0.5:
                    logger.debug(f"技能检索命中（距离={dist:.3f}）: {docs[0][:50]}...")
                    return docs[0]
        except Exception as e:
            logger.error(f"技能检索异常: {e}")
        return None

    def learn_new_skill(self, task_name: str, interaction_logs: list[str]) -> Optional[str]:
        """将交互日志交给 LLM 总结为通用的 SOP，并写入数据库。

        返回生成的 SOP 文本，或在失败时返回 None。
        """
        if not self.collection:
            return None
        # 构造提示词
        logs_text = "\n".join(interaction_logs) if isinstance(interaction_logs, list) else str(interaction_logs)
        prompt = (
            "你是一个流程分析师，负责将用户与 AI 的交互记录总结为通用的标准操作程序（SOP）。\n"
            f"任务名称：{task_name}\n"
            "交互日志如下（包含 Thought/Action/Observation）：\n"
            f"{logs_text}\n"
            "请忽略所有具体的临时 ID 或页面元素，例如“点击 ID 15”、“选择第3个结果”等，"
            "而应转化为语义描述，例如“点击搜索按钮”、“打开设置页面”等。\n"
            "输出应是简洁、步骤化的通用 SOP，每步独立编号。\n"
            "不要输出其他无关说明。只返回 SOP 文本。"
        )
        try:
            # 延迟导入以避免循环依赖
            from ..llm import call_llm

            sop = call_llm("", MODEL_NAME, prompt)
            if sop:
                # 写入数据库
                try:
                    sid = str(uuid.uuid4())
                    self.collection.add(documents=[sop], metadatas=[{"task_name": task_name}], ids=[sid])
                    logger.info(f"新技能已学习并存储，task_name={task_name} id={sid}")
                except Exception as e:
                    logger.error(f"技能存储失败: {e}")
                return sop
        except Exception as e:
            logger.error(f"调用 LLM 生成 SOP 失败: {e}")
        return None
