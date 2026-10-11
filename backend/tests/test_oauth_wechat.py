"""微信 OAuth 授权地址与回调登录测试（与支付宝侧覆盖对等，待开放平台审核通过后可直接联调）。"""
import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 在导入 app.* 之前固定测试环境，避免读取到本机脏环境变量。
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_db"
os.environ["WECHAT_APP_ID"] = ""
os.environ["WECHAT_APP_SECRET"] = ""
# openid 加密存储（P2-4.1）的测试密钥由 tests/conftest.py 统一注入

import app.core.crypto as crypto
import app.core.security as security
from app.core.security import verify_token
from app.models.user import User

# 复用支付宝侧的模块副本与 fake 设施（DRY）：必须与 build_test_client 内部的
# auth 副本是同一个对象，否则对路由端点全局名的 monkeypatch 不生效。
from tests.test_oauth_alipay import (
    FakeCodeGuard,
    FakeStateService,
    auth,
    build_test_client,
    oauth_module,
)

REDIRECT_URI = "https://your-domain.com/login/callback"


class FakeWechatService:
    """测试用微信 OAuth 服务：返回值按用例需要注入。"""

    def __init__(self, app_id, app_secret, **kwargs):
        pass

    def get_auth_url(self, redirect_uri: str, state: str | None = None) -> str:
        return (
            "https://open.weixin.qq.com/connect/qrconnect"
            f"?appid=wx_test_app&redirect_uri={redirect_uri}&state={state}#wechat_redirect"
        )

    async def get_access_token(self, code: str):
        return {
            "access_token": "wx-at-1",
            "openid": "wx-open-1",
            "unionid": "wx-union-1",
        }

    async def get_user_info(self, access_token: str, openid: str):
        return {"openid": "wx-open-1", "nickname": "微信用户", "headimgurl": "https://example.com/a.png"}


def _configure_wechat(monkeypatch, fake_service=FakeWechatService):
    """注入微信配置 + 白名单隔离（不得读取本机 .env 真实白名单，与既有测试同约定）。"""
    saved = {
        "WECHAT_APP_ID": auth.settings.WECHAT_APP_ID,
        "WECHAT_APP_SECRET": auth.settings.WECHAT_APP_SECRET,
        "OAUTH_REDIRECT_URI_WHITELIST": auth.settings.OAUTH_REDIRECT_URI_WHITELIST,
    }
    auth.settings.WECHAT_APP_ID = "wx_test_app"
    auth.settings.WECHAT_APP_SECRET = "wx_test_secret"
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = [REDIRECT_URI]
    monkeypatch.setattr(auth, "WechatOAuthService", fake_service)
    return saved


def _restore_settings(saved):
    for key, value in saved.items():
        setattr(auth.settings, key, value)


def _install_state(monkeypatch, state: str, extra=None):
    state_svc = FakeStateService()
    asyncio.run(state_svc.store(state, "wechat", REDIRECT_URI, extra=extra))
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)


def test_wechat_get_auth_url_contains_required_params():
    """授权地址必须包含 appid/redirect_uri/scope/state 与 #wechat_redirect 片段。"""
    service = oauth_module.WechatOAuthService(app_id="wx_app", app_secret="wx_secret")
    url = service.get_auth_url(REDIRECT_URI, state="st-1")

    assert url.startswith("https://open.weixin.qq.com/connect/qrconnect?")
    assert "appid=wx_app" in url
    assert "scope=snsapi_login" in url
    assert "state=st-1" in url
    assert url.endswith("#wechat_redirect")
    # redirect_uri 必须 URL 编码（含冒号/斜杠的明文不得出现）
    assert "redirect_uri=https%3A%2F%2Fyour-domain.com" in url
    assert f"redirect_uri={REDIRECT_URI}" not in url


def test_wechat_auth_url_endpoint_503_when_not_configured(monkeypatch):
    """AppSecret 未配置（开放平台审核未通过）时 fail-closed 503，不得放行授权。"""
    saved = {
        "WECHAT_APP_ID": auth.settings.WECHAT_APP_ID,
        "WECHAT_APP_SECRET": auth.settings.WECHAT_APP_SECRET,
        "OAUTH_REDIRECT_URI_WHITELIST": auth.settings.OAUTH_REDIRECT_URI_WHITELIST,
    }
    auth.settings.WECHAT_APP_ID = "wx_test_app"
    auth.settings.WECHAT_APP_SECRET = ""
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = [REDIRECT_URI]
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/auth-url", json={"redirect_uri": REDIRECT_URI}
        )
        assert response.status_code == 503
        assert "微信" in response.json()["detail"]
    finally:
        _restore_settings(saved)


def test_wechat_auth_url_endpoint_returns_server_state(monkeypatch):
    """配置齐全时返回服务端生成的 state 与授权地址（前端不得自造 state）。"""
    saved = _configure_wechat(monkeypatch)
    # auth-url 会把 state 存 Redis：注入内存实现，不连真实 Redis
    monkeypatch.setattr(auth, "oauth_state_service", FakeStateService())
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/auth-url", json={"redirect_uri": REDIRECT_URI}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["state"]
        assert payload["auth_url"].startswith("https://open.weixin.qq.com/connect/qrconnect?")
        assert f"state={payload['state']}" in payload["auth_url"]
    finally:
        _restore_settings(saved)


def test_wechat_callback_errcode_40163_marks_code_used(monkeypatch):
    """errcode=40163（code 已被使用）：400 + 落 used 标记，重试同 code 直接拒绝。"""

    class ErrService(FakeWechatService):
        async def get_access_token(self, code: str):
            return {"errcode": 40163, "errmsg": "code been used"}

    saved = _configure_wechat(monkeypatch, fake_service=ErrService)
    guard = FakeCodeGuard()
    monkeypatch.setattr(auth, "oauth_code_guard", guard)
    _install_state(monkeypatch, "st-wx-40163")
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback", json={"code": "wx-code-1", "state": "st-wx-40163"}
        )
        assert response.status_code == 400
        code_hash = guard._hash("wx-code-1")
        assert code_hash in guard.used, "errcode=40163 必须落 used 标记，防重复打网关"
        # 同一 code 再来一次：锁层直接 400
        _install_state(monkeypatch, "st-wx-40163-b")
        retry = client.post(
            "/api/v1/auth/wechat/callback", json={"code": "wx-code-1", "state": "st-wx-40163-b"}
        )
        assert retry.status_code == 400
    finally:
        _restore_settings(saved)


def test_wechat_callback_other_errcode_releases_lock(monkeypatch):
    """其他 errcode（如 40029 invalid code）：400 + 释放锁，允许换码重试。"""

    class ErrService(FakeWechatService):
        async def get_access_token(self, code: str):
            return {"errcode": 40029, "errmsg": "invalid code"}

    saved = _configure_wechat(monkeypatch, fake_service=ErrService)
    guard = FakeCodeGuard()
    monkeypatch.setattr(auth, "oauth_code_guard", guard)
    _install_state(monkeypatch, "st-wx-40029")
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback", json={"code": "wx-code-2", "state": "st-wx-40029"}
        )
        assert response.status_code == 400
        code_hash = guard._hash("wx-code-2")
        assert code_hash not in guard.locks, "非 40163 错误必须释放锁"
        assert code_hash not in guard.used
    finally:
        _restore_settings(saved)


def test_wechat_callback_missing_openid_returns_400(monkeypatch):
    """换票成功但缺 openid：400 且释放锁（未拿到 access_token 不算换票成功）。"""

    class NoOpenidService(FakeWechatService):
        async def get_access_token(self, code: str):
            return {"access_token": "wx-at-1"}

    saved = _configure_wechat(monkeypatch, fake_service=NoOpenidService)
    guard = FakeCodeGuard()
    monkeypatch.setattr(auth, "oauth_code_guard", guard)
    _install_state(monkeypatch, "st-wx-no-openid")
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback", json={"code": "wx-code-3", "state": "st-wx-no-openid"}
        )
        assert response.status_code == 400
        code_hash = guard._hash("wx-code-3")
        assert code_hash not in guard.locks and code_hash not in guard.used
    finally:
        _restore_settings(saved)


def test_wechat_callback_userinfo_errcode_returns_400(monkeypatch):
    """userinfo 返回 errcode：400，且 code 已落 used（换票已成功，不得再放同 code 打网关）。"""

    class BadUserinfoService(FakeWechatService):
        async def get_user_info(self, access_token: str, openid: str):
            return {"errcode": 40003, "errmsg": "invalid openid"}

    saved = _configure_wechat(monkeypatch, fake_service=BadUserinfoService)
    guard = FakeCodeGuard()
    monkeypatch.setattr(auth, "oauth_code_guard", guard)
    _install_state(monkeypatch, "st-wx-bad-userinfo")
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback", json={"code": "wx-code-4", "state": "st-wx-bad-userinfo"}
        )
        assert response.status_code == 400
        code_hash = guard._hash("wx-code-4")
        assert code_hash in guard.used, "换票成功后 userinfo 失败也不得释放锁"
    finally:
        _restore_settings(saved)


def test_wechat_callback_existing_user_returns_token(monkeypatch):
    """已有用户（openid 命中）回调返回 status=ok，token 入 httpOnly cookie 且带 tv。"""
    from app.core.security import make_unusable_password_hash

    saved = _configure_wechat(monkeypatch)
    _install_state(monkeypatch, "st-wx-existing")
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        db = session_factory()
        try:
            crypto_obj = crypto.get_openid_crypto()
            db.add(
                User(
                    username="wechat_existing",
                    email=None,
                    password_hash=make_unusable_password_hash(),
                    # _sync_external_user 会用网关昵称覆盖旧 full_name（预期行为），
                    # 种子值与 FakeWechatService 的 nickname 保持一致
                    full_name="微信用户",
                    wechat_openid_hash=crypto_obj.lookup_hash("wx-open-1"),
                    wechat_openid_encrypted=crypto_obj.encrypt("wx-open-1"),
                    wechat_unionid_hash=crypto_obj.lookup_hash("wx-union-1"),
                    wechat_unionid_encrypted=crypto_obj.encrypt("wx-union-1"),
                )
            )
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/v1/auth/wechat/callback",
            json={"code": "wx-code-ok", "state": "st-wx-existing"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload.get("registration_ticket") is None
        assert response.cookies.get(security.access_cookie_name()), "OAuth 登录必须写 access cookie"
        token_payload = verify_token(response.cookies.get(security.access_cookie_name()))
        assert token_payload.get("tv") == 1
        assert payload["user"]["full_name"] == "微信用户"
    finally:
        _restore_settings(saved)


def test_wechat_callback_new_user_returns_ticket_without_creating_user(monkeypatch):
    """首次登录不自动建号：返回建号票据，库中无新用户行（与支付宝侧一致）。"""
    saved = _configure_wechat(monkeypatch)
    _install_state(monkeypatch, "st-wx-new")
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback",
            json={"code": "wx-code-new", "state": "st-wx-new"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "new_user"
        assert payload["registration_ticket"]
        # openid 不得回传客户端（反模式警示：openid 不进浏览器）
        assert "wx-open-1" not in response.text
        db = session_factory()
        try:
            assert db.query(User).count() == 0
        finally:
            db.close()
    finally:
        _restore_settings(saved)


def test_wechat_callback_ticket_keeps_openid_and_unionid_encrypted(monkeypatch):
    """待建号票据内 openid/unionid 必须是密文：Redis 泄露不得直接拿到明文（P2-4.1）。"""
    saved = _configure_wechat(monkeypatch)
    _install_state(monkeypatch, "st-wx-ticket-crypto")
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback",
            json={"code": "wx-code-crypto", "state": "st-wx-ticket-crypto"},
        )
        assert response.status_code == 200
        ticket = response.json()["registration_ticket"]

        pending = auth.oauth_pending_registration.pending[ticket]
        assert pending["provider"] == "wechat"
        assert pending["openid"] != "wx-open-1", "票据内不得出现明文 openid"
        assert pending["unionid"] != "wx-union-1", "票据内不得出现明文 unionid"
        crypto_obj = crypto.get_openid_crypto()
        assert crypto_obj.decrypt(pending["openid"]) == "wx-open-1"
        assert crypto_obj.decrypt(pending["unionid"]) == "wx-union-1"
    finally:
        _restore_settings(saved)


def test_wechat_callback_bind_intent_returns_bind_pending(monkeypatch):
    """intent=bind：callback 不建号、不发 token，只回 bind_pending + 票据（P2-4.2）。"""
    saved = _configure_wechat(monkeypatch)
    _install_state(monkeypatch, "st-wx-bind", extra={"intent": "bind", "user_id": 7})
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        response = client.post(
            "/api/v1/auth/wechat/callback",
            json={"code": "wx-code-bind", "state": "st-wx-bind"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "bind_pending"
        assert payload["bind_ticket"]
        assert not response.cookies.get(security.access_cookie_name())

        pending = auth.oauth_pending_registration.pending[payload["bind_ticket"]]
        assert pending["intent"] == "bind"
        assert pending["user_id"] == 7
        db = session_factory()
        try:
            assert db.query(User).count() == 0, "bind 意图不得建号"
        finally:
            db.close()
    finally:
        _restore_settings(saved)
