# memory.py - 记忆管理模块

import os
import chromadb
import time
import uuid
from .config import data_dir

class MemoryManager:
    def __init__(self):
        os.makedirs(data_dir, exist_ok=True)
        try:
            self.client = chromadb.PersistentClient(path=data_dir)
            self.collection = self.client.get_or_create_collection(name="seeka_memory")
            self.enabled = True
        except Exception as e:
            print(f"[记忆系统初始化失败] {e}")
            self.collection = None
            self.enabled = False

    def store_memory(self, conversation):
        if not self.enabled:
            return
        try:
            self.collection.add(
                documents=[conversation],
                metadatas=[{"timestamp": time.time(), "access_count": 0}],
                ids=[str(uuid.uuid4())]
            )
        except Exception as e:
            print(f"[记忆存储错误] {e}")

    def retrieve_memories(self, query, n_results=2):
        if not self.enabled:
            return "记忆功能未启用。"
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas"]
            )
            memories = results.get('documents', [[]])[0] if results.get('documents') else []
            return "\n".join(memories) if memories else "无相关记忆。"
        except Exception as e:
            print(f"[记忆检索错误] {e}")
            return "无相关记忆。"

    def cleanup_old_memories(self):
        if not self.enabled:
            return
        try:
            results = self.collection.get(include=["metadatas"])
            current_time = time.time()
            to_delete = []
            for i, metadata in enumerate(results["metadatas"]):
                if metadata:
                    timestamp = metadata.get("timestamp", 0)
                    access_count = metadata.get("access_count", 0)
                    if current_time - timestamp > 7 * 24 * 3600 and access_count < 2:
                        to_delete.append(results["ids"][i])
            if to_delete:
                self.collection.delete(ids=to_delete)
                print(f"[记忆清理] 删除了 {len(to_delete)} 条不重要的记忆")
        except Exception as e:
            print(f"[记忆清理错误] {e}")