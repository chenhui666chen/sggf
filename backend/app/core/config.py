"""
配置管理模块
"""
from pydantic_settings import BaseSettings
from typing import Optional, List, Union
import json


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基本配置
    APP_NAME: str = "Novel Writing System API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 数据库配置
    DATABASE_URL: str = "sqlite:///../novel_app.db"
    SQLALCHEMY_ECHO: bool = False
    
    # JWT配置
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    
    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # CORS配置
    CORS_ORIGINS: Union[List[str], str] = '["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:3000"]'
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list = ["*"]
    CORS_HEADERS: list = ["*"]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 如果 CORS_ORIGINS 是字符串，尝试解析为 JSON
        if isinstance(self.CORS_ORIGINS, str):
            try:
                self.CORS_ORIGINS = json.loads(self.CORS_ORIGINS)
            except json.JSONDecodeError:
                # 如果解析失败，使用默认值
                self.CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]
    
    # 文件上传配置
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    UPLOAD_DIR: str = "./uploads"
    
    # DeepSeek API配置
    DEEPSEEK_API_KEY: str = "your-deepseek-api-key"
    DEEPSEEK_API_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-reasoner"
    DEEPSEEK_EMBEDDING_MODEL: str = "deepseek-embedding"
    MODEL_NAME: str = "deepseek-reasoner"
    
    # 阿里云百炼 API配置
    DASHSCOPE_API_KEY: str = "your-dashscope-api-key"
    
    # Mureka AI 音乐服务配置
    MUREKA_API_KEY: str = ""
    MUREKA_API_URL: str = "https://api.mureka.ai"
    
    # Embedding模型配置
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 向量数据库配置
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_db"
    # 🆕 Typed-RAG 开关与参数
    ENABLE_TYPED_RAG: bool = True
    TYPED_RAG_K_CHAR: int = 4
    TYPED_RAG_K_WORLD: int = 5
    
    # Agent配置
    TEMPERATURE: float = 0.7
    MAX_CONTEXT_LENGTH: int = 4000
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    # 腾讯云 API 配置（用于 AI 生成检测）
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""
    TENCENT_REGION: str = "ap-guangzhou"
    TENCENT_BIZTYPE: str = ""  # 可选，策略编号

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"  # 允许额外字段


settings = Settings()