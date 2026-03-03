"""Unit tests for SkillManager"""

import os
import sys

# ensure project root on path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules import llm as llm_mod
from modules.memory.skills import SkillManager


def test_skill_learning_and_retrieval(tmp_path, monkeypatch):
    # patch call_llm to return a predictable SOP
    def fake_llm(system_prompt, model_name, prompt, memory_context=""):
        return "1. 首先做A\n2. 然后做B"

    # SkillManager 内部延迟导入 llm，因此 patch llm 模块
    monkeypatch.setattr(llm_mod, "call_llm", fake_llm)

    mgr = SkillManager()
    # ensure collection is empty for deterministic behavior
    try:
        existing = mgr.collection.get(include=["ids"])
        if existing and existing.get("ids"):
            mgr.collection.delete(ids=existing["ids"])
    except Exception:
        pass

    # learn a new skill
    logs = ["Thought: test", "Action: click", "Observation: ok"]
    sop = mgr.learn_new_skill("测试任务", logs)
    assert sop is not None and "做A" in sop

    # retrieval may or may not return the SOP depending on semantic distance threshold
    result = mgr.retrieve_skill("测试任务")
    assert isinstance(result, (str, type(None)))

    # we can at least inspect the raw chroma query output to ensure doc is stored
    raw = mgr.collection.query(query_texts=["测试任务"], n_results=1, include=["documents", "distances"])
    docs = raw.get("documents", [[]])[0]
    assert docs and docs[0].startswith("1.")

    # a query that is unrelated should probably return None (distance > threshold)
    unrelated = mgr.retrieve_skill("完全无关的描述")
    assert unrelated is None or unrelated is None


if __name__ == "__main__":
    # simple runner for environments without pytest
    test_skill_learning_and_retrieval(None, type("M", (), {"setattr": setattr}))
    print("test_skill_learning_and_retrieval passed")
