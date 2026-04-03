# memory_store.py

import hashlib
import os
import time
from collections import OrderedDict, defaultdict

# Workaround for joblib/loky UnicodeDecodeError on Chinese Windows.
# loky executes `wmic` to count physical cores if LOKY_MAX_CPU_COUNT is not set,
# which may produce a UnicodeDecodeError under GBK.  Setting the variable
# early avoids the subprocess call entirely.
if "LOKY_MAX_CPU_COUNT" not in os.environ:
    os.environ["LOKY_MAX_CPU_COUNT"] = str(os.cpu_count() or 4)

import faiss
import networkx as nx
import numpy as np

# sklearn imports are deferred where possible to avoid pulling in joblib on import
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from .rust_accel import compute_adjusted_scores, is_rust_acceleration_available


def _debug_log(message: str) -> None:
    if os.environ.get("MEMORY_STORE_DEBUG") == "1":
        print(message)


class MemoryStore:
    def __init__(self, dimension=1536):
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)
        self.short_term_memory = []  # Short-term memory interactions
        self.long_term_memory = []  # Long-term memory interactions
        self.embeddings = []  # Embeddings for each interaction in short-term memory
        self.normalized_embeddings = []  # Normalized embeddings for fast cosine scoring
        self.timestamps = []  # Timestamps for decay in short-term memory
        self.access_counts = []  # Access counts for reinforcement in short-term memory
        self.concepts_list = []  # Concepts for each interaction in short-term memory
        self.graph = nx.Graph()  # Graph for bidirectional associations
        self.semantic_memory = defaultdict(list)  # Semantic memory clusters
        self.cluster_labels = []  # Labels for each interaction's cluster
        self._rust_acceleration_enabled = is_rust_acceleration_available()
        self._rust_acceleration_logged = False
        self._interaction_index = {}

        # Retrieval layered cache (L1/L2/L3): key = query_signature + concepts + retrieval params.
        self._retrieval_l1_capacity = max(0, int(os.environ.get("MEMORY_RETRIEVE_L1_SIZE", "64")))
        self._retrieval_l2_capacity = max(0, int(os.environ.get("MEMORY_RETRIEVE_L2_SIZE", "256")))
        self._retrieval_l3_capacity = max(0, int(os.environ.get("MEMORY_RETRIEVE_L3_SIZE", "1024")))
        self._retrieval_cache_ttl_sec = max(0.0, float(os.environ.get("MEMORY_RETRIEVE_CACHE_TTL_SEC", "1.5")))
        self._retrieval_cache_epoch = 0
        self._retrieval_l1_cache = OrderedDict()
        self._retrieval_l2_cache = OrderedDict()
        self._retrieval_l3_cache = OrderedDict()
        self._retrieval_cache_stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "l3_hits": 0,
            "misses": 0,
        }

    @staticmethod
    def _normalize_embedding(embedding):
        vector = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(vector)
        if norm <= 0:
            return vector
        return vector / norm

    @staticmethod
    def _normalize_concepts_key(query_concepts):
        concepts = set()
        for concept in query_concepts or []:
            normalized = str(concept).strip().lower()
            if normalized:
                concepts.add(normalized)
        return tuple(sorted(concepts))

    @staticmethod
    def _query_embedding_signature(query_embedding_norm):
        vector = np.asarray(query_embedding_norm, dtype=np.float32).reshape(-1)
        if vector.size == 0:
            return "empty"
        rounded = np.round(vector, decimals=5)
        return hashlib.blake2b(rounded.tobytes(), digest_size=16).hexdigest()

    def _make_retrieval_cache_key(
        self,
        query_embedding_norm,
        query_concepts,
        similarity_threshold,
        exclude_last_n,
        search_limit,
    ):
        return (
            self._retrieval_cache_epoch,
            search_limit,
            round(float(similarity_threshold), 4),
            int(exclude_last_n),
            self._normalize_concepts_key(query_concepts),
            self._query_embedding_signature(query_embedding_norm),
        )

    @staticmethod
    def _touch_cache_layer(layer, key, current_time):
        entry = layer.get(key)
        if entry is None:
            return None

        expires_at, payload = entry
        if expires_at <= current_time:
            layer.pop(key, None)
            return None

        layer.move_to_end(key)
        return entry

    @staticmethod
    def _insert_cache_layer(layer, key, entry, capacity):
        if capacity <= 0:
            return None

        layer[key] = entry
        layer.move_to_end(key)

        if len(layer) > capacity:
            return layer.popitem(last=False)
        return None

    def _promote_cache_entry(self, key, entry):
        evicted_l1 = self._insert_cache_layer(
            self._retrieval_l1_cache,
            key,
            entry,
            self._retrieval_l1_capacity,
        )
        if evicted_l1 is None:
            return

        evicted_l2 = self._insert_cache_layer(
            self._retrieval_l2_cache,
            evicted_l1[0],
            evicted_l1[1],
            self._retrieval_l2_capacity,
        )
        if evicted_l2 is None:
            return

        self._insert_cache_layer(
            self._retrieval_l3_cache,
            evicted_l2[0],
            evicted_l2[1],
            self._retrieval_l3_capacity,
        )

    def _get_cached_retrieval(self, key, current_time):
        if self._retrieval_cache_ttl_sec <= 0:
            return None

        l1_entry = self._touch_cache_layer(self._retrieval_l1_cache, key, current_time)
        if l1_entry is not None:
            self._retrieval_cache_stats["l1_hits"] += 1
            return l1_entry[1]

        l2_entry = self._touch_cache_layer(self._retrieval_l2_cache, key, current_time)
        if l2_entry is not None:
            self._retrieval_cache_stats["l2_hits"] += 1
            self._promote_cache_entry(key, l2_entry)
            return l2_entry[1]

        l3_entry = self._touch_cache_layer(self._retrieval_l3_cache, key, current_time)
        if l3_entry is not None:
            self._retrieval_cache_stats["l3_hits"] += 1
            self._promote_cache_entry(key, l3_entry)
            return l3_entry[1]

        self._retrieval_cache_stats["misses"] += 1
        return None

    def _store_cached_retrieval(self, key, serialized_results, current_time):
        if self._retrieval_cache_ttl_sec <= 0:
            return

        expires_at = current_time + self._retrieval_cache_ttl_sec
        entry = (expires_at, serialized_results)
        self._promote_cache_entry(key, entry)

    def _invalidate_retrieval_cache(self):
        self._retrieval_l1_cache.clear()
        self._retrieval_l2_cache.clear()
        self._retrieval_l3_cache.clear()
        self._retrieval_cache_epoch += 1

    def get_retrieval_cache_stats(self):
        return {
            "l1_hits": int(self._retrieval_cache_stats["l1_hits"]),
            "l2_hits": int(self._retrieval_cache_stats["l2_hits"]),
            "l3_hits": int(self._retrieval_cache_stats["l3_hits"]),
            "misses": int(self._retrieval_cache_stats["misses"]),
            "l1_size": len(self._retrieval_l1_cache),
            "l2_size": len(self._retrieval_l2_cache),
            "l3_size": len(self._retrieval_l3_cache),
            "epoch": self._retrieval_cache_epoch,
            "ttl_sec": float(self._retrieval_cache_ttl_sec),
        }

    @staticmethod
    def _serialize_interactions_for_cache(interactions):
        serialized = []
        for interaction in interactions:
            interaction_id = str(interaction.get("id", "")).strip()
            if not interaction_id:
                continue
            serialized.append((interaction_id, float(interaction.get("total_score", 0.0))))
        return serialized

    def _hydrate_cached_interactions(self, serialized_results):
        hydrated = []
        for interaction_id, total_score in serialized_results:
            idx = self._interaction_index.get(interaction_id)
            if idx is None or idx >= len(self.short_term_memory):
                continue

            interaction = self.short_term_memory[idx]
            interaction["total_score"] = float(total_score)
            hydrated.append(interaction)

        return hydrated

    def _apply_cached_retrieval_feedback(self, interactions, current_time):
        for interaction in interactions:
            interaction_id = str(interaction.get("id", "")).strip()
            idx = self._interaction_index.get(interaction_id)
            if idx is None or idx >= len(self.short_term_memory):
                continue

            self.access_counts[idx] += 1
            self.timestamps[idx] = current_time
            self.short_term_memory[idx]["timestamp"] = current_time
            self.short_term_memory[idx]["access_count"] = self.access_counts[idx]
            self.short_term_memory[idx]["decay_factor"] = float(
                self.short_term_memory[idx].get("decay_factor", 1.0)
            ) * 1.02

            if self.access_counts[idx] > 10:
                self.classify_memory()

    def add_interaction(self, interaction):
        interaction_id = interaction["id"]
        prompt = interaction["prompt"]
        output = interaction["output"]
        embedding = np.array(interaction["embedding"], dtype=np.float32).reshape(1, -1)
        timestamp = interaction.get("timestamp", time.time())
        access_count = interaction.get("access_count", 1)
        concepts = set(interaction.get("concepts", []))
        decay_factor = interaction.get("decay_factor", 1.0)

        _debug_log(f"Adding new interaction to short-term memory: '{prompt[:50]}'")
        # Save the interaction data to short-term memory
        self.short_term_memory.append(
            {
                "id": interaction_id,
                "prompt": prompt,
                "output": output,
                "timestamp": timestamp,
                "access_count": access_count,
                "decay_factor": decay_factor,
            }
        )
        self._interaction_index[interaction_id] = len(self.short_term_memory) - 1
        self.embeddings.append(embedding)
        self.normalized_embeddings.append(self._normalize_embedding(embedding))
        self.index.add(np.ascontiguousarray(embedding, dtype=np.float32))
        self.timestamps.append(timestamp)
        self.access_counts.append(access_count)
        self.concepts_list.append(concepts)

        # Update graph with bidirectional associations
        self.update_graph(concepts)
        self._invalidate_retrieval_cache()

        _debug_log(f"Total interactions stored in short-term memory: {len(self.short_term_memory)}")

    def update_graph(self, concepts):
        for concept in concepts:
            self.graph.add_node(concept)
        for concept1 in concepts:
            for concept2 in concepts:
                if concept1 != concept2:
                    if self.graph.has_edge(concept1, concept2):
                        self.graph[concept1][concept2]["weight"] += 1
                    else:
                        self.graph.add_edge(concept1, concept2, weight=1)

    def classify_memory(self):
        # Move interactions with access count > 10 to long-term memory
        for idx, access_count in enumerate(self.access_counts):
            if access_count > 10 and self.short_term_memory[idx] not in self.long_term_memory:
                self.long_term_memory.append(self.short_term_memory[idx])
                _debug_log(f"Moved interaction {self.short_term_memory[idx]['id']} to long-term memory.")

    def retrieve(self, query_embedding, query_concepts, similarity_threshold=40, exclude_last_n=0):
        if len(self.short_term_memory) == 0:
            _debug_log("No interactions available in short-term memory for retrieval.")
            return []

        if not self._rust_acceleration_enabled:
            raise RuntimeError("Rust memory acceleration backend is unavailable.")

        _debug_log("Retrieving relevant interactions from short-term memory...")
        relevant_interactions = []
        current_time = time.time()
        decay_rate = 0.0001

        search_limit = max(0, len(self.short_term_memory) - exclude_last_n)
        if search_limit == 0:
            _debug_log("No interactions eligible for retrieval due to exclude_last_n.")
            return []

        query_embedding_norm = self._normalize_embedding(query_embedding)
        cache_key = self._make_retrieval_cache_key(
            query_embedding_norm=query_embedding_norm,
            query_concepts=query_concepts,
            similarity_threshold=similarity_threshold,
            exclude_last_n=exclude_last_n,
            search_limit=search_limit,
        )

        cached_serialized = self._get_cached_retrieval(cache_key, current_time)
        if cached_serialized is not None:
            if len(cached_serialized) == 0:
                _debug_log("Retrieval cache hit with empty result set.")
                return []

            cached_interactions = self._hydrate_cached_interactions(cached_serialized)
            if len(cached_interactions) == len(cached_serialized):
                self._apply_cached_retrieval_feedback(cached_interactions, current_time)
                _debug_log("Retrieval cache hit (L1/L2/L3).")
                return cached_interactions

        candidate_embeddings = self.normalized_embeddings[:search_limit]
        candidate_timestamps = self.timestamps[:search_limit]
        candidate_access_counts = self.access_counts[:search_limit]
        candidate_decay_factors = [
            float(self.short_term_memory[idx].get("decay_factor", 1.0)) for idx in range(search_limit)
        ]

        adjusted_scores, decayed_factors = compute_adjusted_scores(
            query_embedding_norm=query_embedding_norm,
            normalized_embeddings=candidate_embeddings,
            timestamps=candidate_timestamps,
            access_counts=candidate_access_counts,
            decay_factors=candidate_decay_factors,
            current_time=current_time,
            decay_rate=decay_rate,
        )

        if len(adjusted_scores) != search_limit or len(decayed_factors) != search_limit:
            raise ValueError(
                "Adjusted score result length mismatch: expected "
                f"{search_limit}, got scores={len(adjusted_scores)}, decays={len(decayed_factors)}"
            )

        # Track indices of relevant interactions
        relevant_indices = set()

        # Calculate adjusted similarity for each interaction
        for idx in range(search_limit):
            self.short_term_memory[idx]["decay_factor"] = float(decayed_factors[idx])
            adjusted_similarity = float(adjusted_scores[idx])
            _debug_log(f"Interaction {idx} - Adjusted similarity score: {adjusted_similarity:.2f}%")

            if adjusted_similarity >= similarity_threshold:
                relevant_indices.add(idx)
                self.access_counts[idx] += 1
                self.timestamps[idx] = current_time
                self.short_term_memory[idx]["timestamp"] = current_time
                self.short_term_memory[idx]["access_count"] = self.access_counts[idx]

                if self.access_counts[idx] > 10:
                    self.classify_memory()

                self.short_term_memory[idx]["decay_factor"] *= 1.1

                relevant_interactions.append(
                    (adjusted_similarity, self.short_term_memory[idx], self.concepts_list[idx])
                )
            else:
                _debug_log(
                    f"[DEBUG] Interaction {self.short_term_memory[idx]['id']} was not relevant (similarity: {adjusted_similarity:.2f}%)."
                )

        # Decrease decay factor for non-relevant interactions
        for idx in range(search_limit):
            if idx not in relevant_indices:
                self.short_term_memory[idx]["decay_factor"] = float(
                    self.short_term_memory[idx].get("decay_factor", 1.0)
                ) * 0.9

        if self._rust_acceleration_enabled and not self._rust_acceleration_logged:
            _debug_log("[MemoryStore] Rust acceleration path active for similarity scoring.")
            self._rust_acceleration_logged = True

        # Spreading activation
        activated_concepts = self.spreading_activation(query_concepts)

        # Integrate spreading activation scores
        final_interactions = []
        for score, interaction, concepts in relevant_interactions:
            activation_score = sum([activated_concepts.get(c, 0) for c in concepts])
            total_score = score + activation_score
            interaction["total_score"] = total_score
            final_interactions.append((total_score, interaction))

        # Sort interactions based on total_score
        final_interactions.sort(key=lambda x: x[0], reverse=True)
        final_interactions = [interaction for _, interaction in final_interactions]

        # Retrieve from semantic memory
        semantic_interactions = self.retrieve_from_semantic_memory(query_embedding_norm)
        final_interactions.extend(semantic_interactions)

        serialized_results = self._serialize_interactions_for_cache(final_interactions)
        self._store_cached_retrieval(cache_key, serialized_results, current_time)

        _debug_log(f"Retrieved {len(final_interactions)} relevant interactions from memory.")
        return final_interactions

    def spreading_activation(self, query_concepts):
        _debug_log("Spreading activation for concept associations...")
        activated_nodes = {}
        initial_activation = 1.0
        decay_factor = 0.5

        for concept in query_concepts:
            activated_nodes[concept] = initial_activation

        for _step in range(2):
            new_activated_nodes = {}
            for node in activated_nodes:
                if node in self.graph:
                    for neighbor in self.graph.neighbors(node):
                        if neighbor not in activated_nodes:
                            weight = self.graph[node][neighbor]["weight"]
                            new_activation = activated_nodes[node] * decay_factor * weight
                            new_activated_nodes[neighbor] = new_activated_nodes.get(neighbor, 0) + new_activation
            activated_nodes.update(new_activated_nodes)

        _debug_log(f"Concepts activated after spreading: {activated_nodes}")
        return activated_nodes

    def cluster_interactions(self):
        # delay sklearn import until clustering is actually needed
        from sklearn.cluster import KMeans

        _debug_log("Clustering interactions to create hierarchical memory...")
        if len(self.embeddings) < 2:
            _debug_log("Not enough interactions to perform clustering.")
            return

        embeddings_matrix = np.vstack(list(self.embeddings))
        num_clusters = min(10, len(self.embeddings))
        kmeans = KMeans(n_clusters=num_clusters, random_state=0).fit(embeddings_matrix)
        self.cluster_labels = kmeans.labels_

        for idx, label in enumerate(self.cluster_labels):
            self.semantic_memory[label].append((self.embeddings[idx], self.short_term_memory[idx]))

        self._invalidate_retrieval_cache()

        _debug_log(f"Clustering completed. Total clusters formed: {num_clusters}")

    def retrieve_from_semantic_memory(self, query_embedding_norm):
        _debug_log("Retrieving interactions from semantic memory...")
        current_time = time.time()
        cluster_similarities = {}
        for label, items in self.semantic_memory.items():
            cluster_embeddings = np.vstack([e for e, _ in items])
            centroid = np.mean(cluster_embeddings, axis=0).reshape(1, -1)
            centroid_norm = normalize(centroid)
            similarity = cosine_similarity(query_embedding_norm, centroid_norm)[0][0]
            cluster_similarities[label] = similarity

        if not cluster_similarities:
            return []
        best_cluster_label = max(cluster_similarities, key=cluster_similarities.get)
        _debug_log(f"Best matching cluster identified: {best_cluster_label}")

        cluster_items = self.semantic_memory[best_cluster_label]
        interactions = [(e, i) for e, i in cluster_items]

        interactions.sort(key=lambda x: cosine_similarity(query_embedding_norm, normalize(x[0]))[0][0], reverse=True)
        semantic_interactions = [interaction for _, interaction in interactions[:5]]

        for interaction in semantic_interactions:
            interaction_id = interaction["id"]
            idx = self._interaction_index.get(interaction_id)
            if idx is not None and idx < len(self.short_term_memory):
                self.access_counts[idx] += 1
                self.timestamps[idx] = current_time
                self.short_term_memory[idx]["timestamp"] = current_time
                self.short_term_memory[idx]["access_count"] = self.access_counts[idx]

        _debug_log(f"Retrieved {len(semantic_interactions)} interactions from the best matching cluster.")
        return semantic_interactions
