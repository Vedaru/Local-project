"""N-gram hash mapper — maps token sequences to deterministic table addresses.

Core of DeepSeek Engram's O(1) retrieval mechanism:
  - bigram / trigram extraction from token ID sequences
  - XOR-based rolling hash per n-gram type
  - Modular reduction onto prime-sized tables
"""

from __future__ import annotations

import hashlib
from typing import Iterable


class NgramHashMapper:
    """Compute deterministic hash addresses for n-grams over token-ID sequences."""

    def __init__(
        self,
        n_values: tuple[int, ...] = (2, 3),
        primes: tuple[int, ...] = (500003, 499979, 499969, 499957),
    ):
        self.n_values = n_values          # e.g. (2,) for bigrams, (3,) for trigrams, (2,3) for both
        self.primes = primes              # one prime per head

    # ---- public API ----

    def compute_hashes(self, token_ids: list[int]) -> dict[tuple[int, int], int]:
        """Return {(ngram_type_index, head_index): table_address} for all n-grams."""
        result: dict[tuple[int, int], int] = {}
        for ni, n in enumerate(self.n_values):
            ngrams = self._extract_ngrams(token_ids, n)
            for ng in ngrams:
                xor_hash = self._xor_hash(ng)
                for hi, p in enumerate(self.primes):
                    key = (ni, hi)
                    addr = xor_hash % p
                    if key not in result:
                        result[key] = addr
        return result

    # ---- internal helpers ----

    @staticmethod
    def _extract_ngrams(token_ids: list[int], n: int) -> list[tuple[int, ...]]:
        if len(token_ids) < n:
            return [tuple(token_ids)] if token_ids else []
        return [tuple(token_ids[i:i + n]) for i in range(len(token_ids) - n + 1)]

    @staticmethod
    def _xor_hash(values: tuple[int, ...]) -> int:
        h = 0
        for v in values:
            h ^= v + 0x9E3779B97 + (h << 6) + (h >> 2)
        h &= 0xFFFFFFFFFFFFFFFF
        return h
