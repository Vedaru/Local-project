"""Semantic Memory — structured fact storage with SCD2 versioning and confidence tracking.

Facts are extracted from user statements and stored as structured records.
Each fact has a confidence score that decays over time (Ebbinghaus-style).
Conflicting facts on the same topic use Snapshot-isolated Concurrency Control (SCD2).
"""

from __future__ import annotations

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Fact:
    fact_id: str = ""
    content: str = ""
    category: str = "extracted_from_interaction"
    confidence: float = 0.7
    source: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    active: bool = True
    access_count: int = 0
    decay_factor: float = 1.02
    superseded_by: Optional[str] = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if not self.fact_id:
            self.fact_id = str(uuid.uuid4())[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.metadata is None:
            self.metadata = {}


class SemanticMemory:
    """Thread-safe semantic fact store with JSON persistence."""

    def __init__(self, path: str, min_confidence: float = 0.15, decay_rate: float = 1.02, max_facts_per_slot: int = 5):
        self.path = path
        self.min_confidence = min_confidence
        self.decay_rate = decay_rate
        self.max_facts_per_slot = max_facts_per_slot
        self._facts: list[Fact] = []
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        self._load()

    @property
    def _facts_count(self) -> int:
        return sum(1 for f in self._facts if f.active)

    def count(self) -> int:
        return self._facts_count

    def upsert(
        self,
        content: str,
        category: str = "extracted_from_interaction",
        confidence: float = 0.75,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> Fact:
        """Insert or update a fact. Uses SCD2: new version supersedes old."""
        fact = Fact(
            content=content,
            category=category,
            confidence=min(max(confidence, 0.0), 1.0),
            source=source or "manual",
            metadata=metadata,
        )

        with self._lock:
            # Check for conflicting active facts (same normalized content prefix)
            norm_new = (content or "").strip()[:60].lower()
            superseded_ids: list[str] = []
            for existing in self._facts:
                if not existing.active:
                    continue
                norm_ex = (existing.content or "").strip()[:60].lower()
                if norm_new == norm_ex or norm_ex in norm_new or norm_new in norm_ex:
                    existing.superseded_by = fact.fact_id
                    existing.active = False
                    superseded_ids.append(existing.fact_id)

            self._facts.append(fact)

            # Trim inactive facts periodically
            if len(self._facts) > 5000:
                self._prune_inactive()

        return fact

    def search(self, query: str, top_k: int = 5) -> list[Fact]:
        """Search facts by keyword overlap and relevance scoring."""
        query_words = set((query or "").lower().split())
        if not query_words:
            return []

        scored: list[tuple[float, Fact]] = []
        now = time.time()

        with self._lock:
            for f in self._facts:
                if not f.active or f.confidence < self.min_confidence:
                    continue

                content_lower = f.content.lower()
                # Keyword match
                matches = sum(1 for w in query_words if len(w) > 1 and w in content_lower)
                containment = matches / max(len(query_words), 1)

                # Confidence decay over time
                age_days = (now - f.updated_at) / 86400.0
                decayed_conf = f.confidence / (self.decay_factor ** age_days)

                score = containment * 0.6 + decayed_conf * 0.4
                if score > 0.05:
                    scored.append((score, f))
                    f.access_count += 1

        scored.sort(reverse=True, key=lambda x: x[0])
        return [f for _, f in scored[:top_k]]

    def get_all_active(self) -> list[Fact]:
        with self._lock:
            return [f for f in self._facts if f.active]

    def save(self):
        target = self.path
        if not target:
            return
        backup = target + ".bak"
        tmp = target + ".tmp"

        data = {"version": 2, "facts": []}
        with self._lock:
            for f in self._facts:
                data["facts"].append({
                    "fact_id": f.fact_id,
                    "content": f.content,
                    "category": f.category,
                    "confidence": f.confidence,
                    "source": f.source,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                    "active": f.active,
                    "access_count": f.access_count,
                    "decay_factor": f.decay_factor,
                    "superseded_by": f.superseded_by,
                    "metadata": f.metadata or {},
                })

        try:
            if os.path.isfile(target):
                try:
                    import shutil
                    shutil.copy2(target, backup)
                except Exception:
                    pass
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except Exception:
            pass

    # ---- internal ----

    def _load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for raw in data.get("facts", []):
                f = Fact(**{k: v for k, v in raw.items() if hasattr(Fact, k)})
                self._facts.append(f)
        except Exception:
            pass

    def _prune_inactive(self):
        cutoff = time.time() - 86400 * 30  # 30 days
        self._facts = [
            f for f in self._facts
            if f.active or f.updated_at >= cutoff
        ]
