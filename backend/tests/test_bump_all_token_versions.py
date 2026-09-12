"""bump_all_token_versions 应急脚本测试（架构 5.5：安全事件批量强制重登）。

- dry-run（默认）：只统计，不写库；
- --apply：全量 tv +1；重复执行幂等递增（应急可多次触发）。

用文件级 sqlite：脚本内部 `create_engine(settings.DATABASE_URL)` 需访问同一库。
"""
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SCRIPT_PATH = ROOT_DIR / "scripts" / "bump_all_token_versions.py"


def _load_script():
    spec = spec_from_file_location("bump_all_token_versions_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 bump_all_token_versions 脚本")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump = _load_script()

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models.password_history import PasswordHistory  # noqa: E402
from app.models.role import Role, user_roles  # noqa: E402,F401  # 注册 user_roles，User mapper 所需
from app.models.user import User  # noqa: E402


@pytest.fixture()
def db_url(tmp_path, monkeypatch):
    """文件级 sqlite：预置 3 个用户（tv=5/6/7），并注入 DATABASE_URL。"""
    url = f"sqlite:///{tmp_path / 'bump.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Role.__table__, user_roles, PasswordHistory.__table__],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        for index in range(3):
            session.add(
                User(
                    username=f"u{index}",
                    email=f"u{index}@example.com",
                    token_version=5 + index,
                )
            )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(settings, "DATABASE_URL", url)
    return url


def _tv_values(url: str) -> list[int]:
    engine = create_engine(url)
    session = sessionmaker(bind=engine)()
    try:
        return sorted(row[0] for row in session.query(User.token_version).all())
    finally:
        session.close()


def test_dry_run_does_not_write(db_url):
    """默认 dry-run：只统计，不动数据。"""
    assert bump.main([]) == 0
    assert _tv_values(db_url) == [5, 6, 7], "dry-run 不得改动数据"


def test_apply_bumps_all_token_versions(db_url):
    assert bump.main(["--apply"]) == 0
    assert _tv_values(db_url) == [6, 7, 8], "全量 tv +1（已签发令牌全部失效）"


def test_apply_is_repeatable(db_url):
    """应急可多次触发：重复执行幂等递增。"""
    assert bump.main(["--apply"]) == 0
    assert bump.main(["--apply"]) == 0
    assert _tv_values(db_url) == [7, 8, 9]
