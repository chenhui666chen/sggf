"""
Agent configuration helpers.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _resolve_backend_storage_path(raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((BACKEND_ROOT / path).resolve())

class Config:
    """System configuration."""

    # DeepSeek model routing settings (served through DashScope compatible API)
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-reasoner")

    # DashScope settings
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_API_BASE = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Embedding settings
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Vector store persistence directory
    CHROMA_PERSIST_DIRECTORY = _resolve_backend_storage_path(
        os.getenv("CHROMA_PERSIST_DIRECTORY", "./chroma_db")
    )

    # Agent闂備焦婢樼粔鍫曟偪?
    MAX_CONTEXT_LENGTH = int(os.getenv("MAX_CONTEXT_LENGTH", "4000"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

    @classmethod
    def validate(cls):
        """Validate whether required configuration is present."""
        errors = []
        warnings = []

        if not cls.EMBEDDING_API_KEY:
            if cls.DASHSCOPE_API_KEY:
                warnings.append("EMBEDDING_API_KEY is missing, falling back to DASHSCOPE_API_KEY")

        if not cls.DASHSCOPE_API_KEY:
            errors.append("Missing DASHSCOPE_API_KEY")
            errors.append("Please set DASHSCOPE_API_KEY in .env")
        elif cls.DASHSCOPE_API_KEY in {"your-api-key-here", "your-dashscope-api-key-here"}:
            warnings.append("DASHSCOPE_API_KEY is still using a placeholder value")

        if errors or warnings:
            logger.debug("=" * 60)
            logger.debug("Configuration validation result")
            logger.debug("=" * 60)

            for warning in warnings:
                logger.debug("WARNING: %s", warning)

            if errors:
                for error in errors:
                    logger.debug("ERROR: %s", error)
                raise ValueError("Configuration validation failed")

            logger.debug("Configuration validation passed with warnings")
        else:
            logger.debug("Configuration validation passed")

        return True
