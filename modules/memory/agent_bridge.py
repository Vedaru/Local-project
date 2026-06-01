"""Agent Memory Bridge — one-way read from Agent's Markdown memory files.

Provides read-only access to the agent's persistent .md files
stored under data/agent_memory_md/. The LLM can query agent memories
but cannot modify them through this bridge.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AgentMemoryHit:
    content: str = ""
    source_file: str = ""
    scope: str = ""  # user / session / repo / global
    relevance: float = 0.0
    age_hours: float = 0.0
    is_user_preference: bool = False


class AgentMemoryBridge:
    """Scans and searches Agent's .md memory files."""

    # Default scopes to search, in priority order
    DEFAULT_SCOPES = ("user", "session", "repo", "global")

    def __init__(self, agent_memory_root: Optional[str] = None, project_root: Optional[str] = None):
        self.enabled = False
        self.agent_memory_root = ""
        self._notes: dict[str, dict] = {}  # filepath → {scope, mtime, lines}
        self._lock = threading.RLock()

        root = agent_memory_root or ""
        if not root and project_root:
            root = os.path.join(project_root, "data", "agent_memory_md")

        if root and os.path.isdir(root):
            self.agent_memory_root = root
            self._scan()
            self.enabled = bool(self._notes)

    def get_stats(self) -> dict:
        with self._lock:
            scope_counts: dict[str, int] = {}
            for info in self._notes.values():
                s = info.get("scope", "")
                scope_counts[s] = scope_counts.get(s, 0) + 1
            return {
                "total_notes": len(self._notes),
                "scopes": scope_counts,
                "root": self.agent_memory_root,
            }

    def search(self, query: str, top_k: int = 5, scope: Optional[str] = None) -> list[AgentMemoryHit]:
        """Search notes by keyword overlap."""
        query_words = set(re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]{2,}", (query or "").lower()))
        if not query_words:
            return []

        now = time.time()
        hits: list[tuple[float, AgentMemoryHit]] = []
        target_scope = (scope or "").lower().strip() if scope else ""

        with self._lock:
            for fpath, info in self._notes.items():
                note_scope = info.get("scope", "")
                if target_scope and target_scope != note_scope:
                    continue

                lines = info.get("lines", [])
                full_text = "\n".join(lines).lower()
                mtime = info.get("mtime", now)

                matches = sum(1 for w in query_words if w in full_text)
                containment = matches / max(len(query_words), 1)

                if containment < 0.08:
                    continue

                # Build display content (best matching paragraph or first 500 chars)
                best_content = self._extract_relevant_section(lines, query_words)
                age_hours = max(0.0, (now - mtime)) / 3600.0
                is_pref = any(p in fpath.lower() for p in ("preference", "user/", "profile"))

                hit = AgentMemoryHit(
                    content=best_content,
                    source_file=os.path.relpath(fpath, self.agent_memory_root) if self.agent_memory_root else fpath,
                    scope=note_scope,
                    relevance=containment,
                    age_hours=age_hours,
                    is_user_preference=is_pref,
                )
                score = containment * 0.7 + (0.2 if is_pref else 0.05) + (1.0 / (1.0 + age_hours**0.3)) * 0.1
                hits.append((score, hit))

        hits.sort(reverse=True, key=lambda x: x[0])
        return [h for _, h in hits[:top_k]]

    # ---- internal ----

    def _scan(self):
        """Scan all .md files under agent_memory_root."""
        if not self.agent_memory_root or not os.path.isdir(self.agent_memory_root):
            return

        root_path = Path(self.agent_memory_root)
        for md_file in sorted(root_path.rglob("*.md")):
            try:
                rel = md_file.relative_to(root_path)
                parts = rel.parts
                # First directory component is the scope
                scope = parts[0] if len(parts) > 1 else "global"

                stat = md_file.stat()
                text = md_file.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()

                if lines:
                    self._notes[str(md_file)] = {
                        "scope": scope,
                        "mtime": stat.st_mtime,
                        "lines": lines,
                    }
            except Exception:
                pass

    @staticmethod
    def _extract_relevant_section(lines: list[str], query_words: set[str]) -> str:
        best_para = ""
        best_score = 0.0
        current_para: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_para:
                    para_text = " ".join(current_para).lower()
                    score = sum(1 for w in query_words if w in para_text)
                    if score > best_score:
                        best_score = score
                        best_para = " ".join(current_para)
                    current_para = []
                continue
            current_para.append(stripped)

        if current_para:
            para_text = " ".join(current_para).lower()
            score = sum(1 for w in query_words if w in para_text)
            if score > best_score:
                best_para = " ".join(current_para)

        result = best_para.strip()
        if len(result) > 800:
            result = result[:300] + "\n... [截省] ...\n" + result[-400:]
        return result
