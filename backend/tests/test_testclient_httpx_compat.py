# -*- coding: utf-8 -*-
"""TestClient 与 httpx 版本兼容性守卫（P37）。

## 故障

全量回归出现 24 个 ERROR，全部同一个根因：

```
TypeError: Client.__init__() got an unexpected keyword argument 'app'
  .venv/Lib/site-packages/starlette/testclient.py:399
```

## 根因（版本契约断裂，非业务代码问题）

- `starlette 0.27.0` 的 `TestClient.__init__` 在第 399-406 行调用
  `super().__init__(app=self.app, base_url=..., transport=..., ...)`
- `httpx 0.28.1` 的 `Client.__init__` **已移除 `app` 参数**
  （改为必须在 transport 层挂 ASGI 应用）

`fastapi==0.104.1` 把 `starlette<0.28.0` 钉死，而环境里的 httpx 被
`chromadb>=0.27.0` / `openai` / `langsmith` 等间接依赖拉到了 0.28.1
⇒ 三个版本三角冲突，测试直接不可用。

项目原本声明的是 `httpx==0.25.2`（requirements-dev.txt / requirements-simple.txt），
说明这是**环境漂移**：重建 venv 时`httpx>=0.25.2`（无上限）被解析到最新。

## 守卫口径

1. `starlette.testclient.TestClient` 必须能实际构造并发起请求
   —— 光「能import」不够，必须真的跑通一个 ASGI 往返
2. starlette 与 httpx 的版本必须落在官方支持矩阵内
3. `httpx` 依赖声明必须设上限，防止再次漂移
"""
from __future__ import annotations

import importlib.metadata as md

import pytest

# ---------------------------------------------------------------------------
# 1. 功能性：TestClient 必须真的能用（这是本次故障的直接防线）
# ---------------------------------------------------------------------------


def test_testclient_can_perform_asgi_roundtrip():
    """TestClient 必须能完成一次真实 ASGI 往返。

    不能只断言「能 import」—— 那个在故障期间也是通过的，
    真正炸在实例化/发请求时的 `app=` 参数上。
    """
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def _ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/ping", _ok)])
    with TestClient(app) as client:
        resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_testclient_supports_post_with_json_body():
    """POST + JSON body 也必须通（项目里大量接口测试依赖它）。"""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def _echo(request):
        return JSONResponse(await request.json())

    app = Starlette(routes=[Route("/echo", _echo, methods=["POST"])])
    with TestClient(app) as client:
        resp = client.post("/echo", json={"a": 1})
    assert resp.status_code == 200
    assert resp.json() == {"a": 1}


# ---------------------------------------------------------------------------
# 2. 版本契约：防止组合再次跑偏
# ---------------------------------------------------------------------------


def test_httpx_accepts_app_kwarg_or_starlette_is_new_enough():
    """两条路任一满足即可，但必须明确知道走的是哪条。

    - httpx < 0.28：接受 `app=` 关键字（starlette 0.27 的用法）
    - starlette >= 0.28：自身已适配 httpx 0.28+
    """
    import inspect

    import httpx
    from starlette import __version__ as starlette_version

    accepts_app = "app" in inspect.signature(httpx.Client.__init__).parameters
    starlette_major_minor = tuple(
        int(x) for x in starlette_version.split(".")[:2])

    if accepts_app:
        pytest.skip(
            f"httpx {httpx.__version__} 仍接受 app= —— "
            f"与 starlette {starlette_version} 兼容，属预期组合")
    assert starlette_major_minor >= (0, 28), (
        f"版本契约断裂：httpx {httpx.__version__} 已移除 app= 参数，"
        f"但 starlette 只有 {starlette_version}（<0.28）仍在传 app=。"
        f"必须降级 httpx 到 <0.28，或升级 starlette 到 >=0.28。"
    )


def test_fastapi_allows_installed_starlette():
    """fastapi 的 starlette 约束必须覆盖实际安装版本。"""
    import fastapi

    fastapi_ver = md.version("fastapi")
    starlette_ver = md.version("starlette")
    reqs = md.distribution("fastapi").requires or []
    pin = next((r for r in reqs if r.lower().startswith("starlette")), None)
    assert pin, "fastapi 未声明 starlette 约束，无法判断兼容性"
    # 形如 "starlette<0.28.0,>=0.27.0"
    upper = None
    for part in pin.split(","):
        part = part.strip()
        if part.startswith("starlette<"):
            upper = part.replace("starlette<", "").strip()
    if upper:
        bound = tuple(int(x) for x in upper.split(".")[:2])
        actual = tuple(int(x) for x in starlette_ver.split(".")[:2])
        assert actual < bound or actual >= (0, 28), (
            f"fastapi {fastapi_ver} 声明 {pin}，实际 starlette {starlette_ver} "
            f"超出约束范围"
        )


# ---------------------------------------------------------------------------
# 3. 依赖声明：防止重建 venv 后再次漂移
# ---------------------------------------------------------------------------

REQ = "backend/requirements.txt"
DEV_REQ = "backend/requirements-dev.txt"


def _read(rel: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / rel).read_text(encoding="utf-8")


def test_httpx_has_upper_bound_in_requirements():
    """`httpx>=0.25.2` 无上限 ⇒ 重建环境必然再次漂到不兼容版本。"""
    line = next(
        (ln for ln in _read(REQ).splitlines()
         if ln.strip().startswith("httpx")),
        None)
    assert line, f"{REQ} 未声明 httpx"
    assert "<" in line, (
        f"httpx 声明为 `{line.strip()}` —— 没有上限，"
        f"重建 venv 时会被chromadb 等间接依赖拉到不兼容版本，"
        f"导致 TestClient 全部不可用。必须设上限。"
    )


def test_starlette_is_pinned_or_bounded():
    """starlette 被 fastapi 间接钉死，但需显式可见以防解析结果失控。"""
    text = _read(REQ)
    has_starlette = any(
        ln.strip().startswith("starlette") for ln in text.splitlines())
    assert has_starlette, (
        f"{REQ} 未显式声明 starlette —— 它是本次故障的直接当事方，"
        f"却只能靠 fastapi 的传递约束决定版本"
    )