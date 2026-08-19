"""
阿里云百炼 Embeddings 适配器。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Optional

import requests
from langchain.embeddings.base import Embeddings

from .config import Config

logger = logging.getLogger(__name__)

# DashScope compatible-mode /embeddings 单次批量上限
_BATCH_SIZE = 10
# 失败重试次数（不含首次请求）
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.0


# 禁用代理，避免本地向量检索与 embedding 请求被宿主机代理干扰。
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class EmbeddingRequestError(RuntimeError):
    """Embedding 请求失败。"""


class AliyunEmbeddings(Embeddings):
    """阿里云百炼 text-embedding-v4 适配器。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or Config.EMBEDDING_API_KEY
            or Config.DASHSCOPE_API_KEY
        )
        self.api_base = (api_base or Config.EMBEDDING_API_BASE or Config.DASHSCOPE_API_BASE).rstrip("/")
        self.model = model or Config.EMBEDDING_MODEL or "text-embedding-v4"
        self.dimensions = int(
            dimensions
            or os.getenv("EMBEDDING_DIMENSIONS")
            or 2048
        )
        self.request_timeout = float(request_timeout)

        if not self.api_key:
            raise ValueError("Aliyun embedding API key is required. Please set DASHSCOPE_API_KEY or EMBEDDING_API_KEY.")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """按批请求 embedding，避免逐条 HTTP 往返；批次内失败带重试。"""
        results: List[List[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start:start + _BATCH_SIZE]
            results.extend(self._get_embeddings_batch(batch))
        return results

    def embed_query(self, text: str) -> List[float]:
        return self._get_embeddings_batch([text])[0]

    def _build_payload(self, input_value: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_value,
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions
        return payload

    def _get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量获取 embeddings；按响应 index 还原顺序；带指数退避重试。"""
        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = requests.post(
                    f"{self.api_base}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._build_payload(texts),
                    timeout=self.request_timeout,
                    proxies={"http": None, "https": None},
                )
                response.raise_for_status()
                payload = response.json()
                return self._parse_batch_payload(payload, expected_count=len(texts))
            except (requests.RequestException, ValueError, EmbeddingRequestError) as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Aliyun embedding batch failed (attempt %s/%s, batch_size=%s), retrying in %.1fs: %s",
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        len(texts),
                        delay,
                        exc,
                    )
                    time.sleep(delay)

        raise EmbeddingRequestError(
            f"Aliyun embedding request failed for model={self.model} after {_MAX_RETRIES + 1} attempts: {last_error}"
        ) from last_error

    def _parse_batch_payload(self, payload: Any, *, expected_count: int) -> List[List[float]]:
        if not isinstance(payload, dict):
            raise EmbeddingRequestError("Aliyun embedding response is not valid JSON.")

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingRequestError(f"Aliyun embedding response has no data field: {payload}")

        # 按 index 字段还原请求顺序（批量响应不保证顺序）
        indexed: List[tuple[int, List[float]]] = []
        for entry in data:
            embedding = entry.get("embedding") if isinstance(entry, dict) else None
            if not isinstance(embedding, list) or not embedding:
                raise EmbeddingRequestError(f"Aliyun embedding response has invalid embedding payload: {payload}")
            index = entry.get("index", len(indexed))
            indexed.append((int(index), embedding))

        indexed.sort(key=lambda item: item[0])
        embeddings = [embedding for _, embedding in indexed]

        if len(embeddings) != expected_count:
            logger.warning(
                "Aliyun embedding batch count mismatch: expected=%s actual=%s model=%s",
                expected_count,
                len(embeddings),
                self.model,
            )
        if embeddings and self.dimensions > 0 and len(embeddings[0]) != self.dimensions:
            logger.warning(
                "Aliyun embedding dimension mismatch: expected=%s actual=%s model=%s",
                self.dimensions,
                len(embeddings[0]),
                self.model,
            )
        return embeddings


def create_aliyun_embeddings() -> AliyunEmbeddings:
    """创建默认阿里云 embedding 适配器。"""
    return AliyunEmbeddings(
        api_key=(
            os.getenv("EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or Config.EMBEDDING_API_KEY
            or Config.DASHSCOPE_API_KEY
        ),
        api_base=Config.EMBEDDING_API_BASE or Config.DASHSCOPE_API_BASE,
        model=Config.EMBEDDING_MODEL,
    )
