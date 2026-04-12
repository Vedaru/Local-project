"""Unit tests for memory retrieval formatting and Chinese lexical matching."""

from pathlib import Path
import time

import pytest

from modules.memory.core import HumanMemoryEngine
from modules.memory.episodic import EpisodicMemory
from modules.memory.palace_kg import PalaceKnowledgeGraph
from modules.memory.palace_store import PalaceMemoryStore, detect_room
from modules.memory.working import WorkingMemory


@pytest.mark.unit
def test_format_results_keeps_episodic_section_grouped(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))
    engine.store("用户: 我今天喜欢吃苹果\nAI: 好的，记住了", metadata={"user_id": "u1", "disable_fact_extraction": True})
    engine.store("用户: 最近在学Rust\nAI: 很棒", metadata={"user_id": "u1", "disable_fact_extraction": True})

    hits = engine._collect_hits(query="喜欢 Rust", n_results=5, user_id="u1")
    context = engine._format_hits(hits, n_results=5)

    assert context.count("【历史对话(用户输入)】") == 1
    assert "用户: 我今天喜欢吃苹果" in context
    assert "用户: 最近在学Rust" in context

    episodic_block = context.split("【历史对话(用户输入)】", 1)[1]
    episodic_block = episodic_block.split("\n\n", 1)[0]
    assert "AI:" not in episodic_block
    engine.close()


@pytest.mark.unit
def test_palace_search_supports_chinese_without_spaces(tmp_path: Path):
    store = PalaceMemoryStore(base_dir=str(tmp_path / "palace"))
    store.add_drawer(
        wing="wing_user_a",
        room="preferences",
        content="用户: 我今天喜欢吃苹果\nAI: 收到",
        user_id="user-a",
    )

    hits = store.search("喜欢苹果", n_results=3, user_id="user-a")

    assert hits
    assert "喜欢吃苹果" in hits[0].text
    store.close()


@pytest.mark.unit
def test_knowledge_graph_search_supports_chinese_without_spaces(tmp_path: Path):
    kg = PalaceKnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    kg.add_triple(
        subject="user:user-a",
        predicate="preference",
        obj="我今天喜欢吃苹果",
        user_id="user-a",
        confidence=0.95,
    )

    hits = kg.search("喜欢苹果", top_k=3, user_id="user-a")

    assert hits
    assert hits[0].object == "我今天喜欢吃苹果"
    kg.close()


@pytest.mark.unit
def test_episodic_search_supports_chinese_without_spaces(tmp_path: Path):
    episodic = EpisodicMemory(path=str(tmp_path / "episodes.jsonl"), similarity_threshold=0.2)
    episodic.add_episode("我今天喜欢吃苹果", "好的，记住了")

    hits = episodic.search("喜欢苹果", top_k=3)

    assert hits
    assert hits[0].user_input == "我今天喜欢吃苹果"


@pytest.mark.unit
def test_room_detection_prefers_problem_keywords():
    room = detect_room("这次部署失败了，报错是连接异常")
    assert room == "problems"


@pytest.mark.unit
def test_working_memory_search_falls_back_to_recent_turns():
    working = WorkingMemory(capacity=7)
    working.add_turn("今天中午我吃了苹果", "好的，记住了")
    working.add_turn("今晚打算去散步", "听起来不错")

    hits = working.search("完全不相关的问题", n_results=2)

    assert len(hits) == 2
    assert hits[0].user_text == "今天中午我吃了苹果"
    assert hits[1].user_text == "今晚打算去散步"


@pytest.mark.unit
def test_working_memory_search_handles_whitespace_variation():
    working = WorkingMemory(capacity=7)
    working.add_turn("你还记得我喜欢吃苹果吗", "记得，你喜欢吃苹果")

    hits = working.search("你 还记得我喜欢吃苹果吗", n_results=1)

    assert hits
    assert hits[0].user_text == "你还记得我喜欢吃苹果吗"


@pytest.mark.unit
def test_store_can_skip_fact_extraction(tmp_path: Path):
    calls = {"count": 0}

    def _fake_llm_extract(_text: str) -> dict:
        calls["count"] += 1
        return {
            "facts": [
                {
                    "fact": "用户喜欢苹果",
                    "category": "preference",
                    "confidence": 0.9,
                }
            ]
        }

    engine = HumanMemoryEngine(
        base_dir=str(tmp_path / "memoripy"),
        llm_extract_fn=_fake_llm_extract,
    )

    status = engine.store(
        "用户: 我喜欢苹果\nAI: 记住了",
        metadata={"disable_fact_extraction": True},
    )

    assert status == "stored"
    assert calls["count"] == 0
    engine.close()


@pytest.mark.unit
def test_store_deferred_persist_skips_immediate_full_save(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))

    save_calls = {"engram": 0, "semantic": 0}

    def _engram_save() -> None:
        save_calls["engram"] += 1

    def _semantic_save() -> None:
        save_calls["semantic"] += 1

    engine.engram.save = _engram_save  # type: ignore[assignment]
    engine.semantic.save = _semantic_save  # type: ignore[assignment]
    engine._config.deferred_persist_turns = 999
    engine._config.deferred_persist_interval_sec = 9999.0

    status = engine.store(
        "用户: 我今天吃了苹果\nAI: 好的，我记住了",
        metadata={"deferred_persist": True, "disable_fact_extraction": True},
    )

    assert status == "stored"
    assert save_calls["engram"] == 0
    assert save_calls["semantic"] == 0

    engine.close()


@pytest.mark.unit
def test_retrieve_isolated_by_user_id(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))

    engine.store(
        "用户: 我喜欢吃苹果\nAI: 好的，记住了",
        metadata={"user_id": "user-a", "disable_fact_extraction": True},
    )
    engine.store(
        "用户: 我喜欢吃香蕉\nAI: 好的，记住了",
        metadata={"user_id": "user-b", "disable_fact_extraction": True},
    )

    ctx_a = engine.retrieve("喜欢吃", n_results=4, user_id="user-a")
    ctx_b = engine.retrieve("喜欢吃", n_results=4, user_id="user-b")

    assert "苹果" in ctx_a
    assert "香蕉" not in ctx_a
    assert "香蕉" in ctx_b
    assert "苹果" not in ctx_b

    engine.close()


@pytest.mark.unit
def test_retrieve_low_information_query_keeps_memory_unbound(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))

    engine.store(
        "用户: 我喜欢吃苹果\nAI: 好的，记住了",
        metadata={"user_id": "user-a", "disable_fact_extraction": True},
    )

    ctx = engine.retrieve("你好", n_results=4, user_id="user-a")

    assert ctx == ""

    engine.close()


@pytest.mark.unit
def test_retrieve_context_dependent_query_uses_recent_continuity_fallback(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))

    engine.store(
        "用户: 我刚刚把你的记忆模块升级了\nAI: 好的，我记住了",
        metadata={"user_id": "user-a", "disable_fact_extraction": True},
    )

    ctx = engine.retrieve("我之前不是说了吗", n_results=4, user_id="user-a")

    assert "我刚刚把你的记忆模块升级了" in ctx

    engine.close()


@pytest.mark.unit
def test_working_continuity_fallback_excludes_warmup_turns(tmp_path: Path):
    engine = HumanMemoryEngine(base_dir=str(tmp_path / "memoripy"))

    engine.working.clear()
    engine.working.add_turn(
        "之前提过苹果蘸花生酱",
        "收到",
        metadata={"source": "episodic_warmup", "user_id": "user-a"},
        timestamp=1.0,
    )

    ctx_without_live_turn = engine.retrieve("我之前不是说了吗", n_results=3, user_id="user-a")
    assert ctx_without_live_turn == ""

    engine.working.add_turn(
        "我们刚刚在聊记忆模块测试",
        "是的，我记得",
        metadata={"user_id": "user-a", "source": "live_turn"},
    )
    engine.clear_cache()
    ctx_with_live_turn = engine.retrieve("我之前不是说了吗", n_results=3, user_id="user-a")

    assert "我们刚刚在聊记忆模块测试" in ctx_with_live_turn
    engine.close()
