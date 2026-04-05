"""
Engram Config — Configuration constants for the Engram-based memory system.

Based on DeepSeek's Engram architecture (Conditional Memory via Scalable Lookup).
Adapted for standalone long-term memory storage in conversational AI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class EngramConfig:
    """Configuration for the Engram N-gram hash-addressed memory system."""

    # === Tokenization ===
    vocab_size_estimate: int = 50000       # Estimated Chinese+English vocabulary size

    # === N-gram parameters ===
    max_ngram_size: int = 3                # Maximum N for N-gram hashing (2,3)
    n_embed_per_ngram: int = 256           # Embedding dimension per n-gram head
    n_head_per_ngram: int = 4              # Number of hash heads per n-gram size

    # === Memory table sizes ===
    # Each (ngram, head) pair gets its own embedding table sized by a prime modulus
    engram_vocab_sizes: List[int] = field(default_factory=lambda: [500003, 500003])

    # === Embedding output ===
    hidden_size: int = 384                 # Final projected dimension (matches CppHashEmbeddingModel)

    # === Hashing ===
    pad_id: int = 0
    seed: int = 42

    # === Gating / Retrieval ===
    gate_temperature: float = 1.0          # Temperature for sigmoid gating
    min_gate_threshold: float = 0.05       # Minimum gate value to include a memory slot
    retrieval_top_k: int = 8               # Top-k memories to retrieve per query

    # === Persistence ===
    persist_dir: str = ""                  # Set by engine init

    @property
    def total_embed_dim(self) -> int:
        return (self.max_ngram_size - 1) * self.n_embed_per_ngram


def get_engram_config() -> EngramConfig:
    """Create EngramConfig from environment variables or defaults."""
    cfg = EngramConfig()
    cfg.vocab_size_estimate = int(os.environ.get("ENGRAM_VOCAB_SIZE", str(cfg.vocab_size_estimate)))
    cfg.max_ngram_size = int(os.environ.get("ENGRAM_MAX_NGRAM", str(cfg.max_ngram_size)))
    cfg.n_embed_per_ngram = int(os.environ.get("ENGRAM_N_EMBED", str(cfg.n_embed_per_ngram)))
    cfg.n_head_per_ngram = int(os.environ.get("ENGRAM_N_HEAD", str(cfg.n_head_per_ngram)))
    cfg.hidden_size = int(os.environ.get("ENGRAM_HIDDEN_SIZE", str(cfg.hidden_size)))
    cfg.seed = int(os.environ.get("ENGRAM_SEED", str(cfg.seed)))

    raw_sizes = os.environ.get("ENGRAM_VOCAB_SIZES")
    if raw_sizes:
        try:
            parsed = [int(x.strip()) for x in raw_sizes.split(",")]
            if len(parsed) >= cfg.max_ngram_size - 1:
                cfg.engram_vocab_sizes = parsed[:cfg.max_ngram_size - 1]
        except ValueError:
            pass

    return cfg


# Module-level singleton for convenience
ENGRAM_CONFIG = get_engram_config()
