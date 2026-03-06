# memory_store.py

import os
import time
from collections import defaultdict

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


class MemoryStore:
    def __init__(self, dimension=1536):
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)
        self.short_term_memory = []  # Short-term memory interactions
        self.long_term_memory = []  # Long-term memory interactions
        self.embeddings = []  # Embeddings for each interaction in short-term memory
        self.timestamps = []  # Timestamps for decay in short-term memory
        self.access_counts = []  # Access counts for reinforcement in short-term memory
        self.concepts_list = []  # Concepts for each interaction in short-term memory
        self.graph = nx.Graph()  # Graph for bidirectional associations
        self.semantic_memory = defaultdict(list)  # Semantic memory clusters
        self.cluster_labels = []  # Labels for each interaction's cluster

    def add_interaction(self, interaction):
        interaction_id = interaction["id"]
        prompt = interaction["prompt"]
        output = interaction["output"]
        embedding = np.array(interaction["embedding"]).reshape(1, -1)
        timestamp = interaction.get("timestamp", time.time())
        access_count = interaction.get("access_count", 1)
        concepts = set(interaction.get("concepts", []))
        decay_factor = interaction.get("decay_factor", 1.0)

        print(f"Adding new interaction to short-term memory: '{prompt[:50]}'")
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
        self.embeddings.append(embedding)
        self.index.add(embedding)
        self.timestamps.append(timestamp)
        self.access_counts.append(access_count)
        self.concepts_list.append(concepts)

        # Update graph with bidirectional associations
        self.update_graph(concepts)

        print(f"Total interactions stored in short-term memory: {len(self.short_term_memory)}")

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
                print(f"Moved interaction {self.short_term_memory[idx]['id']} to long-term memory.")

    def retrieve(self, query_embedding, query_concepts, similarity_threshold=40, exclude_last_n=0):
        if len(self.short_term_memory) == 0:
            print("No interactions available in short-term memory for retrieval.")
            return []

        print("Retrieving relevant interactions from short-term memory...")
        relevant_interactions = []
        current_time = time.time()
        decay_rate = 0.0001

        # Normalize embeddings for cosine similarity
        normalized_embeddings = [normalize(e) for e in self.embeddings]
        query_embedding_norm = normalize(query_embedding)

        # Track indices of relevant interactions
        relevant_indices = set()

        # Calculate adjusted similarity for each interaction
        for idx in range(len(self.short_term_memory) - exclude_last_n):
            # Cosine similarity
            similarity = cosine_similarity(query_embedding_norm, normalized_embeddings[idx])[0][0] * 100
            # Time-based decay
            time_diff = current_time - self.timestamps[idx]
            decay_factor = self.short_term_memory[idx].get("decay_factor", 1.0) * np.exp(-decay_rate * time_diff)
            self.short_term_memory[idx]["decay_factor"] = decay_factor
            # Reinforcement
            reinforcement_factor = np.log1p(self.access_counts[idx])
            # Adjusted similarity
            adjusted_similarity = similarity * decay_factor * reinforcement_factor
            print(f"Interaction {idx} - Adjusted similarity score: {adjusted_similarity:.2f}%")

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
                print(
                    f"[DEBUG] Interaction {self.short_term_memory[idx]['id']} was not relevant (similarity: {adjusted_similarity:.2f}%)."
                )

        # Decrease decay factor for non-relevant interactions
        for idx in range(len(self.short_term_memory)):
            if idx not in relevant_indices:
                self.short_term_memory[idx]["decay_factor"] *= 0.9

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

        print(f"Retrieved {len(final_interactions)} relevant interactions from memory.")
        return final_interactions

    def spreading_activation(self, query_concepts):
        print("Spreading activation for concept associations...")
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

        print(f"Concepts activated after spreading: {activated_nodes}")
        return activated_nodes

    def cluster_interactions(self):
        # delay sklearn import until clustering is actually needed
        from sklearn.cluster import KMeans

        print("Clustering interactions to create hierarchical memory...")
        if len(self.embeddings) < 2:
            print("Not enough interactions to perform clustering.")
            return

        embeddings_matrix = np.vstack(list(self.embeddings))
        num_clusters = min(10, len(self.embeddings))
        kmeans = KMeans(n_clusters=num_clusters, random_state=0).fit(embeddings_matrix)
        self.cluster_labels = kmeans.labels_

        for idx, label in enumerate(self.cluster_labels):
            self.semantic_memory[label].append((self.embeddings[idx], self.short_term_memory[idx]))

        print(f"Clustering completed. Total clusters formed: {num_clusters}")

    def retrieve_from_semantic_memory(self, query_embedding_norm):
        print("Retrieving interactions from semantic memory...")
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
        print(f"Best matching cluster identified: {best_cluster_label}")

        cluster_items = self.semantic_memory[best_cluster_label]
        interactions = [(e, i) for e, i in cluster_items]

        interactions.sort(key=lambda x: cosine_similarity(query_embedding_norm, normalize(x[0]))[0][0], reverse=True)
        semantic_interactions = [interaction for _, interaction in interactions[:5]]

        for interaction in semantic_interactions:
            interaction_id = interaction["id"]
            idx = next((i for i, item in enumerate(self.short_term_memory) if item["id"] == interaction_id), None)
            if idx is not None:
                self.access_counts[idx] += 1
                self.timestamps[idx] = current_time
                self.short_term_memory[idx]["timestamp"] = current_time
                self.short_term_memory[idx]["access_count"] = self.access_counts[idx]

        print(f"Retrieved {len(semantic_interactions)} interactions from the best matching cluster.")
        return semantic_interactions
