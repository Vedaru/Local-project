"""Engram Memory Store — Deterministic hash-addressed N-gram memory tables.

Core of DeepSeek Engram's O(1) memory retrieval:
  - Multiple embedding tables addressed by N-gram hash
  - Gated read: only return stored content above threshold
  - Write-over semantics: last-write-wins at same address
"""

from __future__ import annotations

import json
import os
import time
import threading
from typing import Any, Optional

import numpy as np

from .engram_config import ENGRAM_CONFIG, EngramConfig
from .engram_hashing import NgramHashMapper
from .engram_tokenizer import CompressedTokenizer


class EngramMemoryStore:
    """Multi-head N-gram hash-addressed embedding store with persistence."""

    def __init__(
        self,
        config: Optional[EngramConfig] = None,
        tokenizer: Optional[CompressedTokenizer] = None,
    ):
        self._config = config or ENGRAM_CONFIG
        self.tokenizer = tokenizer or CompressedTokenizer()
        self.hash_mapper = NgramHashMapper(
            n_values=self._config.ngram_n_values,
            primes=self._config.prime_moduli,
        )
        self._lock = threading.RLock()

        # Tables: {(ngram_type_idx, head_idx)} -> dict[int, slot_data]
        self.tables: dict[tuple[int, int], dict[int, dict[str, Any]]] = {}
        # Embedding matrices for each table (lazy init)
        self.embeddings: dict[tuple[int, int], Optional[np.ndarray]] = {}
        self.table_dir = os.path.join(self._config.base_dir, "engram_tables")
        os.makedirs(self.table_dir, exist_ok=True)

        self._init_tables()
        self._load_all_tables()

    @property
    def total_slots_used(self) -> int:
        count = 0
        with self._lock:
            for slots in self.tables.values():
                count += len(slots)
        return count

    # ---- public API ----

    def store(
        self,
        text: str,
        source: str = "conversation",
        confidence: float = 0.7,
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[tuple[int, int, int]]:
        """Store text into all applicable table addresses. Returns list of (n, head, addr)."""
        token_ids = self.tokenizer.encode(text)
        if not token_ids:
            return []

        addresses = self.hash_mapper.compute_hashes(token_ids)
        now = time.time()
        meta = metadata or {}

        results: list[tuple[int, int, int]] = []
        with self._lock:
            for key, addr in addresses.items():
                slot = {
                    "content": text,
                    "source": source,
                    "confidence": min(max(confidence, 0.0), 1.0),
                    "timestamp": now,
                    "token_count": len(token_ids),
                    **meta,
                }
                if key not in self.tables:
                    self.tables[key] = {}
                old_slot = self.tables[key].get(addr)
                # Higher confidence wins at same address
                if old_slot is None or confidence > old_slot.get("confidence", 0.0):
                    self.tables[key][addr] = slot
                    results.append((key[0], key[1], addr))

        return results

    def retrieve(self, query: str, top_k: int = 5, gate_threshold: float = 0.1) -> list[dict]:
        """Retrieve top-k most relevant entries by query hash matching."""
        token_ids = self.tokenizer.encode(query)
        if not token_ids:
            return []

        addresses = self.hash_mapper.compute_hashes(token_ids)
        candidates: list[dict] = []

        with self._lock:
            for key, addr in addresses.items():
                slot = self.tables.get(key, {}).get(addr)
                if slot and slot.get("confidence", 0.0) >= gate_threshold:
                        candidates.append(dict(slot))

        # Deduplicate by content
        seen: set[str] = set()
        unique: list[dict] = []
        for c in candidates:
            content_key = c.get("content", "")
            if content_key not in seen:
                seen.add(content_key)
                unique.append(c)

        # Sort by confidence descending
        unique.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)

        # Time decay penalty
        now = time.time()
        for item in unique[:top_k]:
            age_hours = (now - item.get("timestamp", now)) / 3600.0
            item["relevance"] = item.get("confidence", 0.5) * (1.0 / (1.0 + age_hours ** 0.5))

        unique.sort(key=lambda x: x.get("relevance", 0.0), reverse=True)
        return unique[:top_k]

    def save(self):
        """Persist all tables to disk."""
        with self._lock:
            os.makedirs(self.table_dir, exist_ok=True)
            idx = 0
            for (n_idx, h_idx), slots in self.tables.items():
                fname = f"engram_table_{idx}.json"
                fpath = os.path.join(self.table_dir, fname)
                data = {
                    "ngram_type_index": n_idx,
                    "head_index": h_idx,
                    "total_slots": len(slots),
                    "slots": {
                        str(k): v
                        for k, v in slots.items()
                        if isinstance(v, dict) and "content" in v
                    },
                }
                tmp = fpath + ".tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, ensure_ascii=False, indent=2)
                    os.replace(tmp, fpath)
                except Exception:
                    pass
                idx += 1

            self.tokenizer.save(os.path.join(self._config.base_dir, "engram_vocab.json"))

    # ---- internal ----

    def _init_tables(self):
        for ni in range(len(self._config.ngram_n_values)):
            for hi in range(len(self._config.prime_moduli)):
                self.tables[(ni, hi)] = {}
                self.embeddings[(ni, hi)] = None

    def _load_all_tables(self):
        if not os.path.isdir(self.table_dir):
            return
        for fname in sorted(os.listdir(self.table_dir)):
            if not fname.startswith("engram_table_") or not fname.endswith(".json"):
                continue
            fpath = os.path.join(self.table_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                ni = data.get("ngram_type_index", 0)
                hi = data.get("head_index", 0)
                raw_slots = data.get("slots", {})
                key = (ni, hi)
                if key in self.tables:
                    loaded: dict[int, dict] = {}
                    for k_str, val in raw_slots.items():
                        try:
                            loaded[int(k_str)] = val
                        except ValueError:
                            pass
                    self.tables[key].update(loaded)
            except Exception:
                pass

    @staticmethod
    def _is_contaminated_content(slot: dict) -> bool:
        content = (slot.get("content") or "").strip().lower()
        uncertain_patterns = (
            "不知道", "不确定", "不记得", "没有信息",
            "不清楚", "无法确认", "没有相关信息",
            "i don't know", "not sure", "i'm not sure",
            "no information", "uncertain",
        )
        return any(p in content for p in uncertain_patterns) and len(content) < 80
