"""
阿里云百炼 Embeddings 适配器。
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

import requests
from langchain.embeddings.base import Embeddings

from .config import Config

logger = logging.getLogger(__name__)


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
        return [self._get_embedding(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._get_embedding(text)

    def _build_payload(self, text: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions
        return payload

    def _get_embedding(self, text: str) -> List[float]:
        try:
            response = requests.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._build_payload(text),
                timeout=self.request_timeout,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmbeddingRequestError(
                f"Aliyun embedding request failed for model={self.model}: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise EmbeddingRequestError("Aliyun embedding response is not valid JSON.") from exc

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingRequestError(f"Aliyun embedding response has no data field: {payload}")

        embedding = data[0].get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingRequestError(f"Aliyun embedding response has invalid embedding payload: {payload}")

        if self.dimensions > 0 and len(embedding) != self.dimensions:
            logger.warning(
                "Aliyun embedding dimension mismatch: expected=%s actual=%s model=%s",
                self.dimensions,
                len(embedding),
                self.model,
            )

        return embedding


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
