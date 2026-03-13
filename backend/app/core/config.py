"""
配置管理模块
"""
import json
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow",
    )

    # 应用基本配置
    APP_NAME: str = "拾光工坊"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # 数据库配置（本地开发使用SQLite，生产环境使用PostgreSQL）
    DATABASE_URL: str = "postgresql://novel_user:NovelPostgres0t649OyRUaI@localhost:5432/novel_db"
    SQLALCHEMY_ECHO: bool = False

    # 数据库连接池配置（生产环境优化）
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # JWT配置
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # 邮件发送配置
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "拾光工坊"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 15

    # 找回密码配置
    PASSWORD_RESET_CODE_TTL_SECONDS: int = 600
    PASSWORD_RESET_RESEND_INTERVAL_SECONDS: int = 60
    PASSWORD_RESET_MAX_ATTEMPTS: int = 5
    PASSWORD_RESET_CODE_LENGTH: int = 6

    # CORS配置
    CORS_ORIGINS: list[str] | str = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ]
    )
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = Field(default_factory=lambda: ["*"])
    CORS_HEADERS: list[str] = Field(default_factory=lambda: ["*"])

    @field_validator("DEBUG", mode="before")
    @classmethod
    def validate_debug(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return value

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def validate_cors_origins(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return ["http://localhost:3000", "http://localhost:5173"]

        return parsed if isinstance(parsed, list) else ["http://localhost:3000", "http://localhost:5173"]

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

    # 可灵AI声效服务配置（用于环境音 / 音效生成）
    KLINGAI_ACCESS_KEY: str = ""
    KLINGAI_SECRET_KEY: str = ""
    KLINGAI_API_URL: str = "https://api.klingai.com/v1/audio/text-to-audio"

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

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # 腾讯云 API 配置（用于 AI 生成检测）
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""
    TENCENT_REGION: str = "ap-guangzhou"
    TENCENT_BIZTYPE: str = ""  # 可选，策略编号

    # 支付宝OAuth配置
    ALIPAY_APP_ID: str = ""
    ALIPAY_PRIVATE_KEY: str = ""
    ALIPAY_PUBLIC_KEY: str = ""

    # 微信OAuth配置
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""


settings = Settings()
