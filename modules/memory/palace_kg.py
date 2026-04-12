"""Temporal knowledge graph for MemPalace-style memory facts.

Stores lightweight triples with validity windows using local SQLite.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from .text_search import tokenize_for_search


@dataclass
class KgHit:
    triple_id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    score: float
    valid_from: float
    metadata: dict[str, Any]


def _compact_text(text: str) -> str:
    return "".join((text or "").lower().split())


class PalaceKnowledgeGraph:
    """SQLite temporal triples with lexical query support."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=20)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS triples (
                    triple_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    valid_from REAL NOT NULL,
                    valid_to REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_triples_active
                    ON triples(active, valid_from DESC);
                CREATE INDEX IF NOT EXISTS idx_triples_user_active
                    ON triples(user_id, active, valid_from DESC);
                CREATE INDEX IF NOT EXISTS idx_triples_subject
                    ON triples(subject, active);
                CREATE INDEX IF NOT EXISTS idx_triples_object
                    ON triples(object, active);
                """
            )
            self._conn.commit()

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        return (user_id or "").strip()

    def add_triple(
        self,
        *,
        subject: str,
        predicate: str,
        obj: str,
        user_id: Optional[str] = None,
        confidence: float = 1.0,
        valid_from: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        sub = (subject or "").strip()
        pred = (predicate or "general").strip().lower()
        object_text = (obj or "").strip()
        if not sub or not object_text:
            return ""

        uid = self._normalize_user_id(user_id)
        now = float(valid_from if valid_from is not None else time.time())

        with self._lock:
            existing = self._conn.execute(
                """
                SELECT triple_id FROM triples
                WHERE active=1 AND subject=? AND predicate=? AND object=? AND user_id=?
                LIMIT 1
                """,
                (sub, pred, object_text, uid),
            ).fetchone()

            if existing:
                triple_id = str(existing["triple_id"])
                self._conn.execute(
                    "UPDATE triples SET confidence=MAX(confidence, ?) WHERE triple_id=?",
                    (max(0.0, min(1.0, float(confidence))), triple_id),
                )
                return triple_id

            raw_key = f"{uid}|{sub}|{pred}|{object_text}|{now}"
            digest = hashlib.md5(raw_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
            triple_id = f"triple_{digest}"

            payload = dict(metadata or {})
            payload.setdefault("user_id", uid)

            self._conn.execute(
                """
                INSERT INTO triples(triple_id, subject, predicate, object, user_id, confidence, valid_from, valid_to, metadata, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 1)
                """,
                (
                    triple_id,
                    sub,
                    pred,
                    object_text,
                    uid,
                    max(0.0, min(1.0, float(confidence))),
                    now,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

        return triple_id

    def invalidate(
        self,
        *,
        subject: str,
        predicate: str,
        obj: str,
        user_id: Optional[str] = None,
        ended: Optional[float] = None,
    ) -> int:
        sub = (subject or "").strip()
        pred = (predicate or "").strip().lower()
        object_text = (obj or "").strip()
        if not sub or not pred or not object_text:
            return 0

        uid = self._normalize_user_id(user_id)
        end_at = float(ended if ended is not None else time.time())

        with self._lock:
            if uid:
                cursor = self._conn.execute(
                    """
                    UPDATE triples
                    SET active=0, valid_to=?
                    WHERE active=1 AND subject=? AND predicate=? AND object=? AND user_id=?
                    """,
                    (end_at, sub, pred, object_text, uid),
                )
            else:
                cursor = self._conn.execute(
                    """
                    UPDATE triples
                    SET active=0, valid_to=?
                    WHERE active=1 AND subject=? AND predicate=? AND object=?
                    """,
                    (end_at, sub, pred, object_text),
                )
            return int(cursor.rowcount or 0)

    def invalidate_matching(self, keyword: str, *, user_id: Optional[str] = None) -> int:
        query = (keyword or "").strip()
        if not query:
            return 0

        uid = self._normalize_user_id(user_id)
        with self._lock:
            if uid:
                rows = list(
                    self._conn.execute(
                        "SELECT triple_id, subject, predicate, object FROM triples WHERE active=1 AND user_id=?",
                        (uid,),
                    ).fetchall()
                )
            else:
                rows = list(
                    self._conn.execute(
                        "SELECT triple_id, subject, predicate, object FROM triples WHERE active=1"
                    ).fetchall()
                )

            compact_query = _compact_text(query)
            query_tokens = tokenize_for_search(query)
            matched_ids: list[str] = []

            for row in rows:
                text = f"{row['subject']} {row['predicate']} {row['object']}"
                if compact_query and compact_query in _compact_text(text):
                    matched_ids.append(str(row["triple_id"]))
                    continue

                overlap = len(query_tokens & tokenize_for_search(text))
                if overlap > 0:
                    matched_ids.append(str(row["triple_id"]))

            if not matched_ids:
                return 0

            end_at = time.time()
            for triple_id in matched_ids:
                self._conn.execute(
                    "UPDATE triples SET active=0, valid_to=? WHERE triple_id=?",
                    (end_at, triple_id),
                )

            return len(matched_ids)

    def search(self, query: str, *, top_k: int = 5, user_id: Optional[str] = None) -> list[KgHit]:
        query_text = (query or "").strip()
        query_tokens = tokenize_for_search(query_text)
        if not query_tokens:
            return []

        uid = self._normalize_user_id(user_id)
        params: list[Any] = []
        where = ["active=1"]
        if uid:
            where.append("user_id=?")
            params.append(uid)

        candidate_limit = max(60, int(top_k) * 25)
        sql = (
            "SELECT triple_id, subject, predicate, object, confidence, valid_from, metadata "
            "FROM triples "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY valid_from DESC LIMIT ?"
        )
        params.append(candidate_limit)

        with self._lock:
            rows = list(self._conn.execute(sql, params).fetchall())

        ranked: list[tuple[float, KgHit]] = []
        now = time.time()
        compact_query = _compact_text(query_text)

        for row in rows:
            text = f"{row['subject']} {row['predicate']} {row['object']}"
            candidate_tokens = tokenize_for_search(text)
            overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
            if compact_query and compact_query in _compact_text(text):
                overlap = max(overlap, 0.88)
            if overlap <= 0:
                continue

            conf = max(0.0, min(1.0, float(row["confidence"] or 0.0)))
            age_hours = max(0.0, (now - float(row["valid_from"] or now)) / 3600.0)
            recency = 1.0 / (1.0 + age_hours**0.5)
            score = overlap * 0.65 + conf * 0.25 + recency * 0.10

            if score < 0.08:
                continue

            try:
                metadata = json.loads(row["metadata"] or "{}")
            except Exception:
                metadata = {}

            ranked.append(
                (
                    score,
                    KgHit(
                        triple_id=row["triple_id"],
                        subject=row["subject"],
                        predicate=row["predicate"],
                        object=row["object"],
                        confidence=conf,
                        score=round(float(score), 4),
                        valid_from=float(row["valid_from"] or now),
                        metadata=metadata,
                    ),
                )
            )

        ranked.sort(key=lambda item: (item[0], item[1].valid_from), reverse=True)
        return [hit for _, hit in ranked[: max(1, int(top_k))]]

    def count_current(self, *, user_id: Optional[str] = None) -> int:
        uid = self._normalize_user_id(user_id)
        with self._lock:
            if uid:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS c FROM triples WHERE active=1 AND user_id=?",
                    (uid,),
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) AS c FROM triples WHERE active=1").fetchone()
        return int((row["c"] if row else 0) or 0)

    def timeline(self, *, subject: Optional[str] = None, user_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        uid = self._normalize_user_id(user_id)
        params: list[Any] = []
        where = ["1=1"]

        if uid:
            where.append("user_id=?")
            params.append(uid)
        if subject:
            where.append("subject=?")
            params.append(subject)

        sql = (
            "SELECT triple_id, subject, predicate, object, confidence, valid_from, valid_to, active "
            "FROM triples "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY valid_from DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))

        with self._lock:
            rows = list(self._conn.execute(sql, params).fetchall())

        return [
            {
                "triple_id": row["triple_id"],
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": row["object"],
                "confidence": float(row["confidence"] or 0.0),
                "valid_from": float(row["valid_from"] or 0.0),
                "valid_to": float(row["valid_to"] or 0.0) if row["valid_to"] is not None else None,
                "active": bool(row["active"]),
            }
            for row in rows
        ]

    def save(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()
