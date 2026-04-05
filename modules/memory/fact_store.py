"""Lightweight fact store for user profile memory (event-derived semantic facts)."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional


class FactStore:
    """JSON-backed fact store with simple SCD2-style status transitions."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._backup_path = f"{path}.bak"
        self._loaded = False
        self._doc: dict[str, Any] = {"version": 1, "facts": []}

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join((value or "").strip().split())

    @staticmethod
    def _is_valid_payload(payload: Any) -> bool:
        return isinstance(payload, dict) and isinstance(payload.get("facts"), list)

    def _load_payload(self, path: str) -> Optional[dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if self._is_valid_payload(payload):
                return payload
        except Exception:
            return None
        return None

    def _write_payload(self, path: str, payload: dict[str, Any]) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        self._loaded = True
        primary_payload = self._load_payload(self._path) if os.path.exists(self._path) else None
        if primary_payload is not None:
            self._doc = primary_payload
            if not os.path.exists(self._backup_path):
                self._write_payload(self._backup_path, self._doc)
            return

        backup_payload = self._load_payload(self._backup_path) if os.path.exists(self._backup_path) else None
        if backup_payload is not None:
            self._doc = backup_payload
            # Primary missing/corrupted: reconstruct from backup.
            self._save()
            return

        # Missing/corrupted primary+backup: rebuild a clean empty structure.
        self._doc = {"version": 1, "facts": []}
        self._save()

    def _save(self) -> None:
        self._write_payload(self._path, self._doc)
        self._write_payload(self._backup_path, self._doc)

    def _iter_facts(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        facts = self._doc.get("facts")
        if not isinstance(facts, list):
            self._doc["facts"] = []
            return self._doc["facts"]
        return facts

    def get_active_fact(self, user_id: str, namespace: str, slot: str) -> Optional[dict[str, Any]]:
        user_key = self._normalize_text(user_id) or "local-user"
        namespace_key = self._normalize_text(namespace)
        slot_key = self._normalize_text(slot)

        matches: list[dict[str, Any]] = []
        for fact in self._iter_facts():
            if fact.get("status") != "active":
                continue
            if fact.get("user_id") != user_key:
                continue
            if fact.get("namespace") != namespace_key or fact.get("slot") != slot_key:
                continue
            matches.append(fact)

        if not matches:
            return None

        matches.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return dict(matches[0])

    def list_active_facts(self, user_id: str) -> list[dict[str, Any]]:
        user_key = self._normalize_text(user_id) or "local-user"

        facts = [
            dict(fact)
            for fact in self._iter_facts()
            if fact.get("status") == "active" and fact.get("user_id") == user_key
        ]
        facts.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return facts

    def count_active_facts(self, user_id: str) -> int:
        return len(self.list_active_facts(user_id))

    def upsert_fact(
        self,
        user_id: str,
        namespace: str,
        slot: str,
        value_raw: str,
        confidence: float,
        source_event_id: str,
    ) -> dict[str, Any]:
        user_key = self._normalize_text(user_id) or "local-user"
        namespace_key = self._normalize_text(namespace)
        slot_key = self._normalize_text(slot)
        value_key = self._normalize_text(value_raw)
        if not namespace_key or not slot_key or not value_key:
            raise ValueError("invalid fact key/value")

        now = float(time.time())
        facts = self._iter_facts()

        active_matches = [
            fact
            for fact in facts
            if fact.get("status") == "active"
            and fact.get("user_id") == user_key
            and fact.get("namespace") == namespace_key
            and fact.get("slot") == slot_key
        ]
        active_matches.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        current = active_matches[0] if active_matches else None

        if current and self._normalize_text(str(current.get("value_norm", ""))) == value_key:
            current["confidence"] = max(float(current.get("confidence", 0.0)), float(confidence))
            current["updated_at"] = now
            current["source_event_id"] = source_event_id
            self._save()
            return dict(current)

        if current:
            current["status"] = "superseded"
            current["valid_to"] = now
            current["updated_at"] = now

        new_fact = {
            "fact_id": str(uuid.uuid4()),
            "user_id": user_key,
            "namespace": namespace_key,
            "slot": slot_key,
            "value_raw": value_raw.strip(),
            "value_norm": value_key,
            "confidence": float(confidence),
            "status": "active",
            "valid_from": now,
            "valid_to": None,
            "source_event_id": source_event_id,
            "updated_at": now,
        }
        facts.append(new_fact)
        self._save()
        return dict(new_fact)
