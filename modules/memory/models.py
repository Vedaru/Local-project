"""
Model adapters for memoripy integration.

ChatModel: uses the project's Volcengine/Ark OpenAI-compatible API
EmbeddingModel (priority order):
  1. ArkEmbeddingModel: Volcengine/Ark API embeddings (requires EMBEDDING_MODEL_NAME in .env)
  2. LocalEmbeddingModel: sentence-transformers locally (requires HuggingFace download)
  3. HashEmbeddingModel: lightweight sklearn hash-based embedding (no downloads needed)
"""

import json
from typing import Optional

import numpy as np

from ..logging_config import get_logger
from .memoripy.model import ChatModel, EmbeddingModel

logger = get_logger("Memory.Models")


class ArkChatModel(ChatModel):
    """Chat model adapter that uses the project's OpenAI-compatible client (Volcengine/Ark)."""

    def __init__(self, model_name: str = None):
        from ..config import MODEL_NAME
        from ..config import client as ark_client

        self._client = ark_client
        self.model_name = model_name or MODEL_NAME
        logger.info(f"ArkChatModel 初始化: model={self.model_name}")

    def invoke(self, messages: list) -> str:
        """Invoke the chat model with a list of message dicts."""
        openai_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                openai_messages.append(msg)
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                openai_messages.append({"role": msg.role, "content": msg.content})
            elif hasattr(msg, "type") and hasattr(msg, "content"):
                role = "system" if msg.type == "system" else "user"
                openai_messages.append({"role": role, "content": msg.content})

        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=openai_messages,
        )
        return response.choices[0].message.content

    def extract_concepts(self, text: str) -> list[str]:
        """Extract key concepts from text using the LLM."""
        prompt = (
            "从以下文本中提取关键概念。返回一个 JSON 对象，包含 'concepts' 键，"
            "其值为一个字符串列表。只返回 JSON，不要其他内容。\n"
            f"文本: {text}\n"
            "JSON:"
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            content = response.choices[0].message.content.strip()
            # Try to extract JSON from the response
            # Sometimes LLM wraps in markdown code blocks
            if "```" in content:
                import re

                json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
            result = json.loads(content)
            concepts = result.get("concepts", [])
            logger.debug(f"提取到 {len(concepts)} 个概念")
            return [str(c) for c in concepts]
        except Exception as e:
            logger.warning(f"概念提取失败: {e}")
            # Fallback: simple keyword extraction
            return _simple_extract_concepts(text)


class ArkEmbeddingModel(EmbeddingModel):
    """Embedding model adapter that uses the Volcengine/Ark OpenAI-compatible embeddings API.

    Requires an embedding model endpoint configured via EMBEDDING_MODEL_NAME in .env.
    Compatible with doubao-embedding, bge-m3, or any Volcengine embedding endpoint.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        from ..config import EMBEDDING_MODEL_NAME
        from ..config import client as ark_client

        self._client = ark_client
        self.model_name = model_name or EMBEDDING_MODEL_NAME

        if not self.model_name:
            raise ValueError(
                "未配置嵌入模型。请在 .env 中设置 EMBEDDING_MODEL_NAME "
                "（例如 EMBEDDING_MODEL_NAME=doubao-embedding 或对应的 endpoint ID）"
            )

        # Determine embedding dimension via a test call
        logger.info(f"ArkEmbeddingModel 初始化: model={self.model_name}")
        self.dimension = self._probe_dimension()
        logger.info(f"ArkEmbeddingModel 就绪: 维度={self.dimension}")

    def _probe_dimension(self) -> int:
        """Send a small test request to determine the embedding dimension."""
        try:
            resp = self._client.embeddings.create(
                model=self.model_name,
                input="test",
            )
            dim = len(resp.data[0].embedding)
            return dim
        except Exception as e:
            logger.warning(f"探测嵌入维度失败: {e}，使用默认 1024")
            return 1024

    def get_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for the given text via API."""
        resp = self._client.embeddings.create(
            model=self.model_name,
            input=text,
        )
        return np.array(resp.data[0].embedding)

    def initialize_embedding_dimension(self) -> int:
        return self.dimension


class LocalEmbeddingModel(EmbeddingModel):
    """Embedding model using sentence-transformers locally.

    Uses a multilingual model for Chinese text support.
    Falls back to a smaller model if the preferred one is unavailable.
    """

    # Preferred models in order of priority
    _MODEL_CANDIDATES = [
        "paraphrase-multilingual-MiniLM-L12-v2",  # Good for Chinese, 384 dim
        "all-MiniLM-L6-v2",  # English-focused, 384 dim
    ]

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model = None
        self.dimension = 384  # default

        candidates = [model_name] if model_name else self._MODEL_CANDIDATES

        for name in candidates:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(f"正在加载嵌入模型: {name}")
                self.model = SentenceTransformer(name)
                self.dimension = self.model.get_sentence_embedding_dimension()
                logger.info(f"嵌入模型已就绪: {name} (维度={self.dimension})")
                break
            except Exception as e:
                logger.warning(f"加载嵌入模型 {name} 失败: {e}")
                continue

        if self.model is None:
            raise RuntimeError("无法加载任何嵌入模型。请安装 sentence-transformers: pip install sentence-transformers")

    def get_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for the given text."""
        return self.model.encode(text)

    def initialize_embedding_dimension(self) -> int:
        """Return the embedding dimension."""
        return self.dimension


def _simple_extract_concepts(text: str) -> list[str]:
    """Fallback concept extraction using simple heuristics (no LLM needed)."""
    try:
        import jieba.posseg as pseg

        concepts = []
        for word, flag in pseg.cut(text):
            if flag.startswith("n") and len(word) >= 2:
                concepts.append(word)
        return list(set(concepts))[:10]
    except ImportError:
        # If jieba not available, just split into meaningful chunks
        words = text.split()
        return [w for w in words if len(w) >= 2][:10]


class HashEmbeddingModel(EmbeddingModel):
    """Lightweight embedding model using sklearn HashingVectorizer + TruncatedSVD.

    Produces deterministic fixed-dimension dense vectors from text.
    No external model downloads required — works entirely offline.
    Uses character n-grams (2-4) for good Chinese text support.
    """

    def __init__(self, dimension: int = 384):
        from sklearn.feature_extraction.text import HashingVectorizer

        self._dimension = dimension
        # Character n-gram hashing (supports Chinese without word segmentation)
        self._vectorizer = HashingVectorizer(
            n_features=dimension,
            analyzer="char",
            ngram_range=(2, 4),
            alternate_sign=False,
            norm="l2",
        )
        logger.info(f"HashEmbeddingModel 已就绪: 维度={dimension}（本地哈希嵌入，无需下载）")

    def get_embedding(self, text: str) -> np.ndarray:
        """Generate a dense embedding via feature hashing."""
        sparse = self._vectorizer.transform([text])
        return np.asarray(sparse.todense()).flatten().astype(np.float32)

    def initialize_embedding_dimension(self) -> int:
        return self._dimension
