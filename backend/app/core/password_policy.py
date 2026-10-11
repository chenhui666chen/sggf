"""密码策略（P2-4.6）。

收敛为一处：注册 / 改密 / 重置 / 设密 / 管理员创建共用同一套规则与同一句
用户可见文案；前端本地拦截（RegisterPage / UserCenter）镜像同一句文案。

规则：长度 ≥ PASSWORD_MIN_LENGTH 且 ≤ 50，须同时包含大写字母、小写字母、数字。
"""
import re

from app.core.config import settings


PASSWORD_POLICY_ERROR_MESSAGE = "密码需至少 8 位，且包含大写字母、小写字母和数字"

MAX_PASSWORD_LENGTH = 50

_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")


def check_password_strength(password: str) -> str | None:
    """校验密码强度：通过返回 None，否则返回统一的用户可见错误文案。"""
    min_length = max(int(settings.PASSWORD_MIN_LENGTH), 1)
    if (
        not password
        or len(password) < min_length
        or len(password) > MAX_PASSWORD_LENGTH
        or not _UPPER.search(password)
        or not _LOWER.search(password)
        or not _DIGIT.search(password)
    ):
        return PASSWORD_POLICY_ERROR_MESSAGE
    return None


def validate_password_strength(password: str) -> None:
    """Pydantic schema 校验入口：不通过抛 ValueError（文案即用户可见错误）。"""
    message = check_password_strength(password)
    if message is not None:
        raise ValueError(message)
