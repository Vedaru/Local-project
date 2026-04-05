"""Cleanup utility — removes old legacy memory data files.

Runs once on startup (idempotent via sentinel file).
Deletes interaction_history.json, user_facts.json, and old FAISS indices.
"""

from __future__ import annotations

import os
import time


def cleanup_legacy_files(base_dir: Optional[str] = None) -> dict:
    """
    Remove old legacy memory data files from *base_dir*.

    Returns a status dict with 'success', 'deleted_files', and 'deleted_dirs'.
    Idempotent: safe to call multiple times.
    """
    data_dir = base_dir or ""
    if not data_dir:
        return {"success": False, "error": "no_base_dir"}

    sentinel = os.path.join(data_dir, ".engram_cleanup_complete")

    # Check if already done
    if os.path.isfile(sentinel):
        try:
            with open(sentinel, "r") as fh:
                cached = fh.read().strip()
            if cached:
                return {"success": True, "cached": True, "message": cached}
        except Exception:
            pass

    deleted_files: list[str] = []
    deleted_dirs: list[str] = []

    # Files to remove
    targets = [
        "interaction_history.json",
        "interaction_history.json.bak",
        "user_facts.json",
        "user_facts.json.bak",
        "concepts.json",
        "concepts.json.bak",
        "memory_index.faiss",
        "memory_index.faiss.bak",
        "concept_graph.gml",
        "concept_graph.gml.bak",
    ]

    for fname in targets:
        fpath = os.path.join(data_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                deleted_files.append(fname)
            except OSError:
                pass

    # Directories to remove (old FAISS / cache dirs)
    old_dirs = [
        "faiss_cache",
        "faiss_indices",
        "__pycache__",
    ]

    for dname in old_dirs:
        dpath = os.path.join(data_dir, dname)
        if os.path.isdir(dpath):
            try:
                import shutil
                shutil.rmtree(dpath)
                deleted_dirs.append(dname)
            except OSError:
                pass

    # Write sentinel
    ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = (
        f"cleanup completed at {ts_str}: "
        f"files={len(deleted_files)}, dirs={len(deleted_dirs)}"
    )
    try:
        with open(sententiel := sentinel, "w", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    except Exception:
        pass

    return {
        "success": True,
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "timestamp": ts_str,
    }
