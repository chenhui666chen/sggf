"""密码策略纯函数测试（P2-4.6）。

策略收敛为一处：schema（4 处）与前端（2 处本地拦截）共用同一句用户可见文案，
避免各写一遍导致口径漂移（现状 6-50 与 min_length=6 已经不齐）。
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.password_policy import (  # noqa: E402
    PASSWORD_POLICY_ERROR_MESSAGE,
    check_password_strength,
    validate_password_strength,
)
from app.core.config import settings  # noqa: E402


@pytest.mark.parametrize(
    "password",
    [
        "Abcdef1g",  # 恰好 8 位，含大小写与数字
        "Abcdef1gxyz",  # 更长
        "X9y8Z7x2!@#",  # 含符号
    ],
)
def test_accepts_compliant_password(password):
    assert check_password_strength(password) is None


@pytest.mark.parametrize(
    "password",
    [
        "Ab1defg",  # 缺一位（< 8）
        "abcdefg1",  # 无大写字母
        "ABCDEFG1",  # 无小写字母
        "Abcdefgh",  # 无数字
        "Abcdefg1" * 7,  # 超过 50 位
        "",  # 空串
    ],
)
def test_rejects_with_unified_message(password):
    """所有拒绝场景返回同一句文案，且 validate 直接抛该文案的 ValueError。"""
    assert check_password_strength(password) == PASSWORD_POLICY_ERROR_MESSAGE
    with pytest.raises(ValueError) as exc_info:
        validate_password_strength(password)
    assert str(exc_info.value) == PASSWORD_POLICY_ERROR_MESSAGE


def test_min_length_follows_settings(monkeypatch):
    """下限走配置（架构文档 6.2 的 PASSWORD_MIN_LENGTH），便于按环境收紧。"""
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 10)
    assert check_password_strength("Abcdef1g") == PASSWORD_POLICY_ERROR_MESSAGE  # 9 位
    assert check_password_strength("Abcdefg1xz") is None  # 10 位


def test_admin_user_create_password_rejects_with_unified_message():
    """admin 创建用户超长密码也必须返回统一策略文案（评审 #7：去掉 Field 双重拦截）。"""
    from pydantic import ValidationError

    from app.schemas.admin import UserCreateByAdmin

    with pytest.raises(ValidationError) as exc_info:
        UserCreateByAdmin(
            username="admin_u",
            email="admin@example.com",
            password="A1" * 30,  # 60 位，超过上限
            role_ids=[],
        )
    assert PASSWORD_POLICY_ERROR_MESSAGE in str(exc_info.value)


def test_password_history_hash_rejects_empty_pepper(monkeypatch):
    """空 pepper 的 HMAC 退化为已知 key 哈希（评审 #6）：必须显式拒绝。"""
    from app.services.password_history_service import hash_password_for_history

    monkeypatch.setattr(settings, "PASSWORD_HISTORY_PEPPER", "")
    with pytest.raises(ValueError, match="PASSWORD_HISTORY_PEPPER"):
        hash_password_for_history("Anything1")
