"""
阿里云百炼 Embeddings 适配器
支持 text-embedding-v4 模型
"""
from typing import List, Optional
from langchain.embeddings.base import Embeddings
import requests
import os
import json
import logging

logger = logging.getLogger(__name__)
import numpy as np
from .config import Config

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class AliyunEmbeddings(Embeddings):
    """阿里云百炼 Embeddings 适配器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4"
    ):
        """
        初始化阿里云百炼 Embeddings
        
        Args:
            api_key: 阿里云百炼 API Key
            api_base: API 基础 URL
            model: 使用的模型名称，默认为 text-embedding-v4
        """
        self.api_key = (
            api_key
            or os.getenv("EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or Config.EMBEDDING_API_KEY
            or Config.DASHSCOPE_API_KEY
        )
        self.api_base = api_base
        self.model = model
        
        if not self.api_key:
            raise ValueError("Aliyun API key is required. Please set DASHSCOPE_API_KEY in .env file")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """为文档列表生成 embeddings"""
        embeddings = []
        for text in texts:
            embedding = self._get_embedding(text)
            embeddings.append(embedding)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """为查询文本生成 embedding"""
        return self._get_embedding(text)

    def _get_embedding(self, text: str) -> List[float]:
        """
        调用阿里云百炼 API 获取文本 embedding
        
        Args:
            text: 输入文本
            
        Returns:
            文本的 embedding 向量
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model,
                "input": text,
                "dimensions": 2048  # 指定使用2048维向量
            }

            response = requests.post(
                f"{self.api_base}/embeddings",
                headers=headers,
                json=data,
                timeout=30,
                proxies={'http': None, 'https': None}  # 🛡️ 禁用代理
            )

            if response.status_code == 200:
                result = response.json()
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0]["embedding"]
                else:
                    logger.debug(f"Warning: Aliyun Embedding API returned empty data: {result}")
            else:
                logger.debug(f"Warning: Aliyun Embedding API call failed with status {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.debug(f"Warning: Error getting embedding from Aliyun: {e}")
            
        # Fallback to deterministic random vector
        logger.debug(f"Using fallback vector for text: {text[:50]}...")
        np.random.seed(hash(text) % 2**32)
        return np.random.randn(2048).tolist()  # text-embedding-v4 默认维度是2048


# 兼容性函数，用于替换现有的 DeepSeekEmbeddings
def create_aliyun_embeddings() -> AliyunEmbeddings:
    """
    创建阿里云百炼 embeddings 实例
    
    Returns:
        AliyunEmbeddings 实例
    """
    return AliyunEmbeddings(
        api_key=(
            os.getenv("EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or Config.EMBEDDING_API_KEY
            or Config.DASHSCOPE_API_KEY
        ),
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="text-embedding-v4"
    )
