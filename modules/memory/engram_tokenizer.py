"""Compressed tokenizer for Engram N-gram hashing.

Maps text to integer token IDs using a simple vocabulary.
Supports incremental vocabulary building and optional Chinese word segmentation.
"""

from __future__ import annotations

import os
import re
import json
import threading
from typing import Optional

try:
    import jieba

    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


class CompressedTokenizer:
    """Bidirectional token ↔ compressed-id mapping with persistence."""

    def __init__(self, vocab_path: Optional[str] = None):
        self._token_to_id: dict[str, int] = {}
        self._id_to_token: dict[int, str] = {}
        self._next_id: int = 1
        self._lock = threading.RLock()
        self._vocab_path = vocab_path or ""

        if vocab_path and os.path.isfile(vocab_path):
            self._load(vocab_path)

    @property
    def vocab_size(self) -> int:
        return len(self._token_to_id)

    # ---- public API ----

    def encode(self, text: str) -> list[int]:
        """Tokenize *text* and return list of compressed IDs."""
        tokens = self._split(text)
        ids: list[int] = []
        with self._lock:
            for tok in tokens:
                tid = self._token_to_id.get(tok)
                if tid is None:
                    tid = self._next_id
                    self._next_id += 1
                    self._token_to_id[tok] = tid
                    self._id_to_token[tid] = tok
                ids.append(tid)
        return ids

    def decode(self, ids: list[int]) -> str:
        """Convert IDs back to space-joined tokens (best-effort)."""
        parts: list[str] = []
        for tid in ids:
            parts.append(self._id_to_token.get(tid, f"<unk:{tid}>"))
        return " ".join(parts)

    def save(self, path: Optional[str] = None):
        target = path or self._vocab_path
        if not target:
            return
        with self._lock:
            data = {
                "token_to_id": self._token_to_id,
                "next_id": self._next_id,
            }
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, target)

    # ---- internal helpers ----

    def _load(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._token_to_id = {k: int(v) for k, v in data.get("token_to_id", {}).items()}
            self._next_id = int(data.get("next_id", 1))
            self._id_to_token = {v: k for k, v in self._token_to_id.items()}
        except Exception:
            pass

    @staticmethod
    def _split(text: str) -> list[str]:
        text = (text or "").strip().lower()
        if not text:
            return []

        if _HAS_JIEBA:
            raw = list(jieba.cut(text))
        else:
            raw = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+|[^\s]", text)

        cleaned: list[str] = []
        for t in raw:
            t = t.strip()
            if t:
                cleaned.append(t)

        return cleaned if cleaned else [text]
