"""
memoripy Memory Manager — modified for local project integration.

Changes from upstream:
- Removed langchain dependency (HumanMessage, SystemMessage).
- Messages are plain dicts with 'role' and 'content' keys.
"""

import os
import time
import uuid
from collections import OrderedDict

import numpy as np
from pydantic import BaseModel, Field

from .in_memory_storage import InMemoryStorage
from .memory_store import MemoryStore
from .model import ChatModel, EmbeddingModel


def _debug_log(message: str) -> None:
    if os.environ.get("MEMORY_MANAGER_DEBUG") == "1":
        print(message)


class ConceptExtractionResponse(BaseModel):
    concepts: list[str] = Field(description="List of key concepts extracted from the text.")


class MemoryManager:
    """
    Manages the memory store, including loading and saving history,
    adding interactions, retrieving relevant interactions, and generating responses.
    """

    def __init__(self, chat_model: ChatModel, embedding_model: EmbeddingModel, storage=None):
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self._embedding_cache_size = max(0, int(os.environ.get("MEMORY_EMBED_CACHE_SIZE", "256")))
        self._embedding_cache: OrderedDict[str, np.ndarray] = OrderedDict()

        # Initialize memory store with the correct dimension
        self.dimension = self.embedding_model.initialize_embedding_dimension()
        self.memory_store = MemoryStore(dimension=self.dimension)

        if storage is None:
            self.storage = InMemoryStorage()
        else:
            self.storage = storage

        self.initialize_memory()

    @staticmethod
    def _normalize_cache_key(text: str) -> str:
        return " ".join((text or "").split())

    def standardize_embedding(self, embedding: np.ndarray) -> np.ndarray:
        """
        Standardize embedding to the target dimension by padding with zeros or truncating.
        """
        current_dim = len(embedding)
        if current_dim == self.dimension:
            return embedding
        elif current_dim < self.dimension:
            return np.pad(embedding, (0, self.dimension - current_dim), "constant")
        else:
            return embedding[: self.dimension]

    def load_history(self):
        return self.storage.load_history()

    def save_memory_to_history(self):
        self.storage.save_memory_to_history(self.memory_store)

    def add_interaction(self, prompt: str, output: str, embedding: np.ndarray, concepts: list[str]):
        timestamp = time.time()
        interaction_id = str(uuid.uuid4())
        interaction = {
            "id": interaction_id,
            "prompt": prompt,
            "output": output,
            "embedding": embedding.tolist(),
            "timestamp": timestamp,
            "access_count": 1,
            "concepts": [str(concept) for concept in concepts],
            "decay_factor": 1.0,
        }
        self.memory_store.add_interaction(interaction)
        self.save_memory_to_history()

    def get_embedding(self, text: str) -> np.ndarray:
        _debug_log("Generating embedding for the provided text...")
        cache_key = self._normalize_cache_key(text)
        if cache_key and self._embedding_cache_size > 0:
            cached = self._embedding_cache.get(cache_key)
            if cached is not None:
                self._embedding_cache.move_to_end(cache_key)
                return np.array(cached, copy=True)

        embedding = self.embedding_model.get_embedding(text)
        if embedding is None:
            raise ValueError("Failed to generate embedding.")
        standardized_embedding = self.standardize_embedding(embedding)
        result = np.asarray(standardized_embedding, dtype=np.float32).reshape(1, -1)

        if cache_key and self._embedding_cache_size > 0:
            self._embedding_cache[cache_key] = result
            self._embedding_cache.move_to_end(cache_key)
            while len(self._embedding_cache) > self._embedding_cache_size:
                self._embedding_cache.popitem(last=False)

        return np.array(result, copy=True)

    def extract_concepts(self, text: str) -> list[str]:
        _debug_log("Extracting key concepts from the provided text...")
        return self.chat_model.extract_concepts(text)

    def initialize_memory(self):
        short_term, long_term = self.load_history()
        for interaction in short_term:
            interaction["embedding"] = self.standardize_embedding(np.array(interaction["embedding"]))
            self.memory_store.add_interaction(interaction)
        self.memory_store.long_term_memory.extend(long_term)

        self.memory_store.cluster_interactions()
        _debug_log(
            f"Memory initialized with {len(self.memory_store.short_term_memory)} interactions in short-term and {len(self.memory_store.long_term_memory)} in long-term."
        )

    def retrieve_relevant_interactions(self, query: str, similarity_threshold=40, exclude_last_n=0) -> list:
        query_embedding = self.get_embedding(query)
        query_concepts = self.extract_concepts(query)
        return self.memory_store.retrieve(
            query_embedding, query_concepts, similarity_threshold, exclude_last_n=exclude_last_n
        )

    def generate_response(self, prompt: str, last_interactions: list, retrievals: list, context_window=3) -> str:
        context = ""
        if last_interactions:
            context_interactions = last_interactions[-context_window:]
            context += "\n".join(
                [f"Previous prompt: {r['prompt']}\nPrevious output: {r['output']}" for r in context_interactions]
            )
            _debug_log(f"Using the following last interactions as context for response generation:\n{context}")
        else:
            context = "No previous interactions available."
            _debug_log(context)

        if retrievals:
            retrieved_context_interactions = retrievals[:context_window]
            retrieved_context = "\n".join(
                [
                    f"Relevant prompt: {r['prompt']}\nRelevant output: {r['output']}"
                    for r in retrieved_context_interactions
                ]
            )
            _debug_log(
                f"Using the following retrieved interactions as context for response generation:\n{retrieved_context}"
            )
            context += "\n" + retrieved_context

        # Use simple dicts instead of langchain message objects
        messages = [
            {"role": "system", "content": "You're a helpful assistant."},
            {"role": "user", "content": f"{context}\nCurrent prompt: {prompt}"},
        ]

        response = self.chat_model.invoke(messages)

        return response
