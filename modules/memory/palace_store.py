"""Palace drawer store for long-term memory.

Implements a MemPalace-like storage model:
  - Wing: project/person domain bucket
  - Room: topic bucket inside wing
  - Drawer: verbatim memory chunk

Storage uses local SQLite for deterministic offline behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..logging_config import get_logger
from .text_search import tokenize_for_search

logger = get_logger("Memory.PalaceStore")


_SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")


def _compact_text(text: str) -> str:
    return "".join((text or "").lower().split())


def normalize_slug(text: str, default: str) -> str:
    raw = (text or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return default
    cleaned = _SLUG_PATTERN.sub("_", raw).strip("_")
    return cleaned or default


def wing_for_user(user_id: Optional[str], default_wing: str = "wing_general") -> str:
    uid = (user_id or "").strip()
    if not uid:
        return normalize_slug(default_wing, "wing_general")
    return f"wing_{normalize_slug(uid, 'local_user')}"


_ROOM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "preferences": (
        "喜欢",
        "不喜欢",
        "偏好",
        "习惯",
        "希望",
        "prefer",
        "favorite",
        "like",
        "dislike",
    ),
    "decisions": (
        "决定",
        "改成",
        "改为",
        "采用",
        "切换",
        "选用",
        "decide",
        "decided",
        "choose",
        "switch",
        "migrate",
    ),
    "problems": (
        "报错",
        "错误",
        "失败",
        "崩溃",
        "异常",
        "问题",
        "error",
        "failed",
        "fail",
        "crash",
        "bug",
    ),
    "planning": (
        "计划",
        "里程碑",
        "排期",
        "需求",
        "roadmap",
        "milestone",
        "plan",
        "todo",
        "requirement",
    ),
    "architecture": (
        "架构",
        "模块",
        "服务",
        "接口",
        "design",
        "architecture",
        "component",
        "service",
        "schema",
    ),
    "technical": (
        "代码",
        "测试",
        "部署",
        "数据库",
        "python",
        "api",
        "code",
        "test",
        "debug",
        "deploy",
    ),
}


def detect_room(text: str) -> str:
    normalized = (text or "").lower()
    if not normalized:
        return "general"

    scores: dict[str, int] = {}
    for room, keywords in _ROOM_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in normalized)
        if score > 0:
            scores[room] = score

    if not scores:
        return "general"
    return max(scores.items(), key=lambda item: item[1])[0]


@dataclass
class DrawerHit:
    drawer_id: str
    text: str
    wing: str
    room: str
    similarity: float
    created_at: float
    metadata: dict[str, Any]


class PalaceMemoryStore:
    """SQLite-backed drawer storage and lexical retrieval."""

    def __init__(self, base_dir: str, collection_name: str = "mempalace_drawers"):
        self.base_dir = base_dir
        self.collection_name = normalize_slug(collection_name, "mempalace_drawers")
        os.makedirs(self.base_dir, exist_ok=True)

        self.db_path = os.path.join(self.base_dir, f"{self.collection_name}.sqlite3")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=20)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS drawers (
                    drawer_id TEXT PRIMARY KEY,
                    wing TEXT NOT NULL,
                    room TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_drawers_active_time
                    ON drawers(active, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_drawers_wing_room
                    ON drawers(wing, room, active, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_drawers_user
                    ON drawers(user_id, active, created_at DESC);
                """
            )
            self._conn.commit()

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    def add_drawer(
        self,
        *,
        wing: str,
        room: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        text = (content or "").strip()
        if not text:
            return ""

        wing_name = normalize_slug(wing, "wing_general")
        room_name = normalize_slug(room, "general")
        uid = self._normalize_user_id(user_id)
        now = time.time()

        stable_key = f"{wing_name}|{room_name}|{uid}|{_compact_text(text)}"
        digest = hashlib.md5(stable_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        drawer_id = f"drawer_{wing_name}_{room_name}_{digest}"

        token_blob = " ".join(sorted(tokenize_for_search(text)))
        payload = dict(metadata or {})
        payload.setdefault("filed_at", now)
        payload.setdefault("wing", wing_name)
        payload.setdefault("room", room_name)
        payload.setdefault("user_id", uid)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO drawers(drawer_id, wing, room, user_id, content, tokens, created_at, metadata, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(drawer_id) DO UPDATE SET
                    created_at=excluded.created_at,
                    metadata=excluded.metadata,
                    active=1
                """,
                (
                    drawer_id,
                    wing_name,
                    room_name,
                    uid,
                    text,
                    token_blob,
                    now,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return drawer_id

    def search(
        self,
        query: str,
        *,
        n_results: int = 5,
        wing: Optional[str] = None,
        room: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[DrawerHit]:
        query_text = (query or "").strip()
        query_tokens = tokenize_for_search(query_text)
        if not query_tokens:
            return []

        uid = self._normalize_user_id(user_id)
        params: list[Any] = []
        where = ["active = 1"]

        if uid:
            where.append("user_id = ?")
            params.append(uid)
        if wing:
            where.append("wing = ?")
            params.append(normalize_slug(wing, "wing_general"))
        if room:
            where.append("room = ?")
            params.append(normalize_slug(room, "general"))

        candidate_limit = max(50, int(n_results) * 30)
        sql = (
            "SELECT drawer_id, wing, room, content, tokens, created_at, metadata "
            "FROM drawers "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT ?"
        )
        params.append(candidate_limit)

        with self._lock:
            rows = list(self._conn.execute(sql, params).fetchall())

        ranked: list[tuple[float, DrawerHit]] = []
        now = time.time()
        compact_query = _compact_text(query_text)

        for row in rows:
            token_blob = (row["tokens"] or "").strip()
            candidate_tokens = set(token_blob.split()) if token_blob else set()
            overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))

            content = row["content"] or ""
            if compact_query and compact_query in _compact_text(content):
                overlap = max(overlap, 0.9)

            if overlap <= 0:
                continue

            coverage = len(query_tokens & candidate_tokens) / max(1, len(candidate_tokens))
            age_hours = max(0.0, (now - float(row["created_at"] or now)) / 3600.0)
            recency = 1.0 / (1.0 + age_hours**0.5)
            score = overlap * 0.75 + coverage * 0.15 + recency * 0.10

            if score < 0.05:
                continue

            metadata_raw = row["metadata"] or "{}"
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}

            ranked.append(
                (
                    score,
                    DrawerHit(
                        drawer_id=row["drawer_id"],
                        text=content,
                        wing=row["wing"],
                        room=row["room"],
                        similarity=round(float(score), 4),
                        created_at=float(row["created_at"] or now),
                        metadata=metadata,
                    ),
                )
            )

        ranked.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [hit for _, hit in ranked[: max(1, int(n_results))]]

    def get_recent(
        self,
        *,
        n: int = 10,
        user_id: Optional[str] = None,
        wing: Optional[str] = None,
    ) -> list[DrawerHit]:
        uid = self._normalize_user_id(user_id)
        params: list[Any] = []
        where = ["active = 1"]

        if uid:
            where.append("user_id = ?")
            params.append(uid)
        if wing:
            where.append("wing = ?")
            params.append(normalize_slug(wing, "wing_general"))

        sql = (
            "SELECT drawer_id, wing, room, content, created_at, metadata "
            "FROM drawers "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT ?"
        )
        params.append(max(1, int(n)))

        with self._lock:
            rows = list(self._conn.execute(sql, params).fetchall())

        hits: list[DrawerHit] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except Exception:
                metadata = {}
            hits.append(
                DrawerHit(
                    drawer_id=row["drawer_id"],
                    text=row["content"] or "",
                    wing=row["wing"],
                    room=row["room"],
                    similarity=0.0,
                    created_at=float(row["created_at"] or 0.0),
                    metadata=metadata,
                )
            )
        return hits

    def delete_matching(self, keyword: str, *, user_id: Optional[str] = None) -> int:
        query = (keyword or "").strip()
        if not query:
            return 0

        uid = self._normalize_user_id(user_id)
        with self._lock:
            if uid:
                rows = list(
                    self._conn.execute(
                        "SELECT drawer_id, content FROM drawers WHERE active=1 AND user_id=?",
                        (uid,),
                    ).fetchall()
                )
            else:
                rows = list(self._conn.execute("SELECT drawer_id, content FROM drawers WHERE active=1").fetchall())

            compact_query = _compact_text(query)
            query_tokens = tokenize_for_search(query)
            matched_ids: list[str] = []

            for row in rows:
                content = row["content"] or ""
                compact_content = _compact_text(content)
                if compact_query and compact_query in compact_content:
                    matched_ids.append(row["drawer_id"])
                    continue

                content_tokens = tokenize_for_search(content)
                overlap = len(query_tokens & content_tokens)
                if overlap > 0:
                    matched_ids.append(row["drawer_id"])

            for drawer_id in matched_ids:
                self._conn.execute("UPDATE drawers SET active=0 WHERE drawer_id=?", (drawer_id,))

            return len(matched_ids)

    def count(self, *, user_id: Optional[str] = None) -> int:
        uid = self._normalize_user_id(user_id)
        with self._lock:
            if uid:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS c FROM drawers WHERE active=1 AND user_id=?",
                    (uid,),
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) AS c FROM drawers WHERE active=1").fetchone()
        return int((row["c"] if row else 0) or 0)

    def save(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()
