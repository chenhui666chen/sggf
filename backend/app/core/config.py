"""
配置管理模块
"""
import json
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.env_loader import load_project_env


# 统一环境加载顺序：
# 1. backend/.env
# 2. 仓库根目录 .env（仅作为兜底）
# 3. 已注入到进程的系统环境变量优先级最高
load_project_env(override=False)


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="allow",
    )

    # 应用基本配置
    APP_NAME: str = "拾光工坊"
    APP_VERSION: str = "1.0.0"
    # 运行环境：development | staging | production（生产/staging 启动时会强制安全校验）
    APP_ENV: str = "development"
    DEBUG: bool = False

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
    JWT_SECRET: str = Field(
        default="your-secret-key-change-in-production",
        min_length=32,
        description="JWT 签名密钥，至少 32 字符。生产环境必须通过环境变量注入唯一值。",
    )
    JWT_ALGORITHM: str = "HS256"
    # P1-3.7 短 token 方案：access token 15-30 分钟 + refresh token 7 天
    JWT_ACCESS_EXPIRATION_MINUTES: int = 30
    JWT_REFRESH_EXPIRATION_DAYS: int = 7

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    VIDEO_GATEWAY_INTERNAL_URL: str = ""
    VIDEO_GATEWAY_INTERNAL_TOKEN: str = ""

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

    # 邮箱验证配置（P1-3.8：注册发码与登录态换绑邮箱）
    EMAIL_VERIFY_CODE_TTL_SECONDS: int = 600
    EMAIL_VERIFY_RESEND_INTERVAL_SECONDS: int = 60
    EMAIL_VERIFY_MAX_ATTEMPTS: int = 5
    EMAIL_VERIFY_CODE_LENGTH: int = 6

    # 阿里云短信发送配置（手机号验证码：注册申诉/绑定/找回密码）
    # 签名与模板全部配置化：测试模板审核通过后可直接切换正式签名/模板，零代码改动
    SMS_ACCESS_KEY_ID: str = ""
    SMS_ACCESS_KEY_SECRET: str = ""
    SMS_SIGN_NAME: str = ""
    SMS_TEMPLATE_CODE: str = ""
    SMS_ENDPOINT: str = "dysmsapi.aliyuncs.com"
    SMS_TIMEOUT_SECONDS: int = 10

    # 短信验证码配置（镜像 EMAIL_VERIFY_*；TTL 与测试模板文案"5 分钟内有效"一致）
    SMS_VERIFY_CODE_TTL_SECONDS: int = 300
    SMS_VERIFY_RESEND_INTERVAL_SECONDS: int = 60
    SMS_VERIFY_MAX_ATTEMPTS: int = 5
    SMS_VERIFY_CODE_LENGTH: int = 6

    # 短信防滥用（成本封顶）：号码维/日、IP 维/日、全局日预算熔断（≈500 元/月上限）
    SMS_DAILY_LIMIT_PER_PHONE: int = 5
    SMS_DAILY_LIMIT_PER_IP: int = 20
    SMS_GLOBAL_DAILY_BUDGET: int = 300

    # 认证端点限流（P1-3.1，每分钟次数）
    AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE: int = 20
    AUTH_RATE_LIMIT_LOGIN_ACCOUNT_PER_MINUTE: int = 5
    AUTH_RATE_LIMIT_REGISTER_PER_MINUTE: int = 3
    AUTH_RATE_LIMIT_PASSWORD_RESET_PER_MINUTE: int = 1

    # openid 加密存储（P2-4.1）：查找哈希与加密密文用两把独立密钥，必须分开存储
    # - OPENID_LOOKUP_KEY：HMAC-SHA256 密钥，任意随机串即可（openssl rand -hex 32）
    #   轮换代价极高（需离线重算全表哈希），设计为极低频轮换
    # - OPENID_ENCRYPTION_KEY：Fernet 密钥（32 字节 urlsafe-base64），可按需轮换
    OPENID_LOOKUP_KEY: str = ""
    OPENID_ENCRYPTION_KEY: str = ""

    # 密码策略与锁定（P2-4.6）
    # 密码复杂度下限（架构文档 6.2：≥8，含大小写字母和数字；上限固定 50）
    PASSWORD_MIN_LENGTH: int = 8
    # 连续失败 ACCOUNT_LOCKOUT_ATTEMPTS 次后锁定 ACCOUNT_LOCKOUT_MINUTES 分钟（Redis 计数）
    ACCOUNT_LOCKOUT_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15
    # 密码历史独立 pepper：只用于 password_history 的 HMAC，禁止复用登录 password_hash（bcrypt）
    # 与登录哈希、openid 密钥完全分离；任何环境不得为空，生产/staging 启动强校验
    PASSWORD_HISTORY_PEPPER: str = "your-password-history-pepper-change-in-production"
    # 密码历史保留条数（含当前密码；评审 #9）
    PASSWORD_HISTORY_SIZE: int = 3

    # 审计日志（P2-4.4）：IP / User-Agent 脱敏哈希用独立 pepper（禁止与登录/历史密码复用）；
    # 任何环境不得为空，生产/staging 启动强校验
    AUDIT_LOG_PEPPER: str = ""
    # 审计日志保留天数（5.3：90 天），超期由清理任务/懒清理删除
    AUDIT_LOG_RETENTION_DAYS: int = 90

    # 账户注销（P2-4.3）：注销为软删除，冷静期后由匿名化脚本处理
    # （5.3：用户基本信息/oauth 关联注销后保留 30 天再匿名化；同意记录与账单法定保留）
    ACCOUNT_DELETE_COOLING_DAYS: int = 30

    # Cookie 认证（P2-4.5）：access/refresh/csrf 均入 httpOnly cookie
    # - COOKIE_SECURE：production/staging 必须 True；development（http://localhost）设 False
    # - COOKIE_PREFIX：production/staging 用 __Host-（要求 Secure + Path=/ + 无 Domain）；
    #   development 设为空字符串（http 下 __Host- 前缀不兼容）
    COOKIE_SECURE: bool = True
    COOKIE_PREFIX: str = "__Host-"

    # 初始超管密码（P2-4.6：init_admin_data.py 去硬编码）
    # production/staging 必填；development 未设置时随机生成并打印一次（仅 stdout，不入日志文件）
    INITIAL_ADMIN_PASSWORD: str = ""

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
    CORS_METHODS: list[str] = Field(default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    CORS_HEADERS: list[str] = Field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-Requested-With", "Accept"]
    )

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

    # DeepSeek 官方 API配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-pro"
    MODEL_NAME: str = "deepseek-pro"
    
    # 阿里云百炼 API配置（Qwen / Embedding / TTS / 视频等 DashScope 能力）
    DASHSCOPE_API_KEY: str = "your-dashscope-api-key"
    DASHSCOPE_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Mureka AI 音乐服务配置
    MUREKA_API_KEY: str = ""
    MUREKA_API_URL: str = "https://api.mureka.cn"

    # Vidu 音效服务配置（用于可控时序音效生成）
    VIDU_API_KEY: str = ""
    VIDU_API_URL: str = "https://api.vidu.cn/ent/v2"

    # 公开音效库 API 配置
    FREESOUND_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""

    # 有声书共享音频素材库云存储配置
    AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER: str = "local_fs"
    AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX: str = "shared/audio_library"
    AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_POLICY_MODEL: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET: str = ""
    AUDIOBOOK_AUDIO_LIBRARY_OSS_SECURITY_TOKEN: str = ""

    # 火山引擎 Doubao 服务配置
    DOUBAO_API_KEY: str = ""
    DOUBAO_API_BASE: str = "https://ark.cn-beijing.volces.com/api/v3"

    # Embedding 模型配置
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
    MULTI_MODEL_REVIEW_DEFAULT_PRESET: str = "balanced_3"
    MULTI_MODEL_REVIEW_CHIEF_MODEL: str = "deepseek-pro"
    MULTI_MODEL_REVIEW_CONCURRENCY: int = 5
    MULTI_MODEL_REVIEW_TIMEOUT_SECONDS: int = 120
    MULTI_MODEL_REVIEW_CHIEF_TIMEOUT_SECONDS: int = 120
    MULTI_MODEL_REVIEW_MAX_REVIEWERS: int = 7
    # 主审模型是否可以同时占一个评审席位（默认允许，保持现有面板不变；
    # 关闭后被主审占用的席位改由异厂商、同推理档位的模型接替，避免主审给自己的意见背书）
    MULTI_MODEL_REVIEW_ALLOW_CHIEF_REUSE: bool = True
    MULTI_MODEL_REVIEW_DEFAULT_PROMPT_BUDGET: int = 80000
    MULTI_MODEL_REVIEW_CHAPTER_PLAN_PROMPT_BUDGET: int = 12000
    DOUBAO_REVIEW_PROMPT_BUDGET: int = 64000

    # 迭代优化复评通过线（综合评分 >= 该值即视为达标，无需继续返修）
    ITERATION_PASS_SCORE: float = 8.5
    # 迭代优化最大返修轮次
    ITERATION_MAX_ROUNDS: int = 2

    # 免费生成档位（灵感方舟）配置
    # 强制开关：开启后无标准档角色的用户一律落入免费档（默认关，行为与现状一致）
    FREE_TIER_ENFORCEMENT_ENABLED: bool = False
    # 拥有任一角色码即具备标准档权益（逗号分隔）
    FREE_TIER_STANDARD_ROLE_CODES: str = "super_admin,admin,standard_generation"
    # 免费档每用户每日章数额度
    FREE_TIER_DAILY_CHAPTER_LIMIT: int = 2
    # 全局免费发放量护栏（当日免费章数封顶，注意：章数不等于成本）
    FREE_TIER_GLOBAL_DAILY_LIMIT: int = 500

    # 场景分段生成（P2-1）：默认关闭。
    # 原因：按"关键事件条目"切片保证不了"一段一景"，三个项目先后出现同场复述/整弧重启类结构事故；
    # 单遍生成恢复规划中段可见性。仅当场景互斥切片（一段一场）方案就绪后，经 .env 开启实验。
    SCENE_SEGMENTATION_ENABLED: bool = False

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # 朱雀 AIGC 检测（EdgeOne AI 网关 zhuque-text）
    ZHUQUE_GATEWAY_URL: str = ""  # 创建网关后分配的域名，如 https://xxxx.edgeone.app
    ZHUQUE_API_KEY: str = ""  # 网关 API Key（Bearer 鉴权）
    ZHUQUE_IS_MERGE: bool = False  # 2026-08-28 冒烟定夺：非合并单次调用即得段级真值，全文分与合并模式一致

    # 支付宝OAuth配置
    ALIPAY_APP_ID: str = ""
    ALIPAY_PRIVATE_KEY: str = ""
    ALIPAY_PUBLIC_KEY: str = ""  # 支付宝公钥（用于验签，非应用公钥）
    ALIPAY_SANDBOX: bool = False  # 沙箱环境开关，沙箱网关为 openapi.alipaydev.com
    ALIPAY_SIGN_TYPE: str = "RSA2"

    # 微信OAuth配置
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    # OAuth 安全配置：回调地址精确白名单（按 APP_ENV 组装，生产/staging 仅 HTTPS）
    OAUTH_REDIRECT_URI_WHITELIST: list[str] = Field(
        default_factory=lambda: [
            "https://your-domain.com/login/callback",
        ]
    )

    @model_validator(mode="after")
    def _assemble_oauth_whitelist(self) -> "Settings":
        """开发环境默认追加本地 localhost 回调地址，避免本机 OAuth 直接 400。"""
        if self.APP_ENV == "development":
            local_callback = "http://localhost:5173/login/callback"
            if local_callback not in self.OAUTH_REDIRECT_URI_WHITELIST:
                self.OAUTH_REDIRECT_URI_WHITELIST = [*self.OAUTH_REDIRECT_URI_WHITELIST, local_callback]
        return self


settings = Settings()
