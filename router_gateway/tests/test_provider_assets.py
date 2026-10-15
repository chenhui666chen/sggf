# -*- coding: utf-8 -*-
"""供应商素材登记层契约测试（第 2 批）。

用假 HTTP 端口精确断言字节，不发真实网络：
- public_url：外链直通零网络；
- 贰春：v2 multipart 单 part(file) 上传换 med_id（约 24h 过期）；
- 三宝：/uploads/raw 裸二进制换本站永久 URL；
- 算力：/v1/assets/review 一次批量转存，三类同序数组映射。
进程内 TTL 缓存只在 (provider, kind, url) 粒度命中，跨供应商不串。
"""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from router_gateway.assets.provider_assets import (
    AssetInput,
    AssetRegistrationError,
    ProviderAssetRegistrar,
    ProviderEndpoint,
    RawResponse,
    RegisteredAsset,
)
from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 13, 2, 0, 0, tzinfo=UTC)


def _cap(asset_access):
    return RouteCapability(
        billing="per_use",
        duration=DurationRange(5, 30),
        resolutions=("480p",),
        aspect_ratios=("16:9",),
        input_modes=frozenset({Mode.MULTI_IMAGE, Mode.VIDEO_REFERENCE}),
        max_images=10, max_videos=3, max_audios=3,
        asset_access=asset_access)


def _route(provider, asset_access):
    return Route(route_id=f"{provider}-i2v", provider=provider,
                 upstream_model="m", quality_group="g",
                 capability=_cap(asset_access), pricing="1")


def _input(kind="image", url=None, filename=None, content_type=None):
    default_fn = {"image": "x.jpg", "video": "x.mp4",
                  "audio": "x.wav"}[kind]
    u = url or f"https://oss/{default_fn}"
    fn = filename or u.rsplit("/", 1)[-1]
    return AssetInput(kind=kind, public_url=u, filename=fn,
                      content_type=content_type)


class FakeHttp:
    """记录调用；GET 按 URL 回字节，POST 按脚本顺序回响应。"""

    def __init__(self, get_map=None, post_responses=None, max_bytes_ok=True):
        self.get_map = get_map or {}
        self.post_responses = list(post_responses or [])
        self.gets = []
        self.posts = []

    def get(self, url, *, timeout=60):
        self.gets.append(url)
        body = self.get_map[url]
        return RawResponse(200, body, "application/octet-stream")

    def post(self, url, *, headers, body, timeout=60):
        self.posts.append({"url": url, "headers": headers, "body": body})
        return self.post_responses.pop(0)


def _json(payload, status=200):
    return RawResponse(status, json.dumps(payload).encode("utf-8"),
                       "application/json")


def _registrar(post_responses=None, get_map=None, *, now=None,
               max_download_bytes=60 * 1024 * 1024):
    clock_box = {"t": now or T0}
    http = FakeHttp(get_map=get_map, post_responses=post_responses)
    reg = ProviderAssetRegistrar(
        endpoints={
            "erchun": ProviderEndpoint("erchun", "https://api.erchun.youkou.cc", "tok-e"),
            "suanliai": ProviderEndpoint("suanliai", "https://suanliai.top", "tok-s"),
            "sanbao": ProviderEndpoint("sanbao", "https://sanbaobeauty.com", "tok-b"),
        },
        http=http, clock=lambda: clock_box["t"],
        max_download_bytes=max_download_bytes)
    return reg, http, clock_box


# ---------- public_url 直通 ----------

def test_public_url直通零网络并保持顺序():
    reg, http, _ = _registrar()
    i1 = _input(url="https://oss/a.jpg")
    i2 = _input("video", url="https://oss/b.mp4")
    out = reg.register_batch(_route("erchun", "public_url"), [i1, i2])
    assert http.gets == [] and http.posts == []
    assert [r.ref for r in out] == ["https://oss/a.jpg", "https://oss/b.mp4"]
    assert all(r.ref_type == "public_url" and r.expires_at is None for r in out)
    assert [r.kind for r in out] == ["image", "video"]


def test_空输入直接返回空():
    reg, http, _ = _registrar()
    assert reg.register_batch(_route("erchun", "provider_upload"), []) == ()
    assert http.posts == []


# ---------- 贰春 multipart ----------

def test_贰春multipart单part契约与med_id解析():
    raw = b"\xff\xd8binary-jpeg-bytes\xff\xd9"
    resp = {"media_id": "med_0123456789abcdef0123456789abcdef",
            "object": "media.asset", "media_type": "image",
            "status": "ready",
            "expires_at": "2026-10-14T02:00:00Z"}
    reg, http, _ = _registrar([_json(resp)],
                              {"https://oss/x.jpg": raw})
    out = reg.register_batch(_route("erchun", "provider_upload"), [_input()])

    assert len(out) == 1
    r = out[0]
    assert r.ref == "med_0123456789abcdef0123456789abcdef"
    assert r.ref_type == "media_id"
    assert r.expires_at == datetime(2026, 10, 14, 2, 0, tzinfo=UTC)

    call = http.posts[0]
    assert call["url"] == "https://api.erchun.youkou.cc/v2/media/uploads"
    assert call["headers"]["Authorization"] == "Bearer tok-e"
    ctype = call["headers"]["Content-Type"]
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1].encode()
    body = call["body"]
    # 唯一 part 名 file、filename 带扩展名、part content-type、原始字节原样在体内
    assert b'name="file"' in body
    assert b'filename="x.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert body.startswith(b"--" + boundary)
    assert body.endswith(b"--" + boundary + b"--\r\n")
    assert raw in body


def test_贰春音视频扩展名与part类型正确():
    reg, http, _ = _registrar(
        [_json({"media_id": "med_v", "media_type": "video",
                "expires_at": "2026-10-14T02:00:00Z"}),
         _json({"media_id": "med_a", "media_type": "audio",
                "expires_at": "2026-10-14T02:00:00Z"})],
        {"https://oss/v.mp4": b"VID", "https://oss/a.wav": b"WAV"})
    reg.register_batch(_route("erchun", "provider_upload"),
                       [_input("video", url="https://oss/v.mp4"),
                        _input("audio", url="https://oss/a.wav")])
    assert b'filename="v.mp4"' in http.posts[0]["body"]
    assert b"Content-Type: video/mp4" in http.posts[0]["body"]
    assert b'filename="a.wav"' in http.posts[1]["body"]
    assert b"Content-Type: audio/wav" in http.posts[1]["body"]


def test_贰春非2xx报错不写缓存():
    reg, http, box = _registrar(
        [_json({"error": "quota"}, status=402),
         _json({"media_id": "med_ok", "media_type": "image",
                "expires_at": "2026-10-14T02:00:00Z"})],
        {"https://oss/x.jpg": b"x"})
    route = _route("erchun", "provider_upload")
    with pytest.raises(AssetRegistrationError) as ei:
        reg.register_batch(route, [_input()])
    assert ei.value.status == 402
    # 失败后重试同一素材必须重新上传（未被缓存）
    out = reg.register_batch(route, [_input()])
    assert out[0].ref == "med_ok"
    assert len(http.posts) == 2


def test_贰春med_id过期后重新上传():
    exp = "2026-10-14T02:00:00Z"
    reg, http, box = _registrar(
        [_json({"media_id": "med_1", "media_type": "image", "expires_at": exp}),
         _json({"media_id": "med_2", "media_type": "image", "expires_at": exp})],
        {"https://oss/x.jpg": b"x"})
    route = _route("erchun", "provider_upload")
    inp = _input()
    assert reg.register_batch(route, [inp])[0].ref == "med_1"
    box["t"] = T0 + timedelta(hours=23)            # 未过期：命中缓存
    assert reg.register_batch(route, [inp])[0].ref == "med_1"
    box["t"] = datetime(2026, 10, 14, 2, 0, 1, tzinfo=UTC)  # 过期：重传
    assert reg.register_batch(route, [inp])[0].ref == "med_2"
    assert len(http.posts) == 2


# ---------- 三宝裸二进制 ----------

def test_三宝raw裸二进制契约与永久URL():
    raw = b"raw-image-bytes"
    resp = {"file": {"url": "https://sanbaobeauty.com/uploads/abc.jpg",
                     "kind": "image", "contentType": "image/jpeg",
                     "size": len(raw)}}
    reg, http, box = _registrar([_json(resp)], {"https://oss/x.jpg": raw})
    out = reg.register_batch(_route("sanbao", "provider_upload"), [_input()])
    r = out[0]
    assert r.ref == "https://sanbaobeauty.com/uploads/abc.jpg"
    assert r.ref_type == "host_url" and r.expires_at is None

    call = http.posts[0]
    assert call["url"].startswith(
        "https://sanbaobeauty.com/openapi/v1/uploads/raw?")
    assert "kind=image" in call["url"]
    assert "fileName=x.jpg" in call["url"]
    assert call["headers"]["Authorization"] == "Bearer tok-b"
    assert call["headers"]["Content-Type"] == "image/jpeg"
    # 裸二进制：不是 multipart，也不是 JSON，字节原样
    assert call["body"] == raw
    assert not call["body"].startswith(b"--")


def test_三宝视频音频query的kind与content_type():
    reg, http, _ = _registrar(
        [_json({"file": {"url": "https://sanbaobeauty.com/uploads/v.mp4"}}),
         _json({"file": {"url": "https://sanbaobeauty.com/uploads/a.mp3"}})],
        {"https://oss/v.mp4": b"v", "https://oss/a.mp3": b"a"})
    reg.register_batch(_route("sanbao", "provider_upload"),
                       [_input("video", url="https://oss/v.mp4"),
                        _input("audio", filename="a.mp3",
                               url="https://oss/a.mp3")])
    assert "kind=video" in http.posts[0]["url"]
    assert http.posts[0]["headers"]["Content-Type"] == "video/mp4"
    assert "kind=audio" in http.posts[1]["url"]
    assert http.posts[1]["headers"]["Content-Type"] == "audio/mpeg"


def test_三宝永久URL不过期缓存():
    resp = {"file": {"url": "https://sanbaobeauty.com/uploads/abc.jpg"}}
    reg, http, box = _registrar([_json(resp)], {"https://oss/x.jpg": b"x"})
    route = _route("sanbao", "provider_upload")
    inp = _input()
    assert reg.register_batch(route, [inp])[0].ref.endswith("/abc.jpg")
    box["t"] = T0 + timedelta(days=400)   # 永久：远期仍命中，不再上传
    assert reg.register_batch(route, [inp])[0].ref.endswith("/abc.jpg")
    assert len(http.posts) == 1


def test_三宝非2xx报错():
    reg, _, _ = _registrar([_json({"error": "bad"}, status=415)],
                           {"https://oss/x.jpg": b"x"})
    with pytest.raises(AssetRegistrationError) as ei:
        reg.register_batch(_route("sanbao", "provider_upload"), [_input()])
    assert ei.value.status == 415


# ---------- 算力 review 批量转存 ----------

def _review_ok():
    return {"success": True, "all_ok": True,
            "images": ["https://suanliai.top/api/media/input/a.jpg",
                       "https://suanliai.top/api/media/input/b.jpg"],
            "videos": [],
            "audios": ["https://suanliai.top/api/media/input/c.wav"],
            "items": [
                {"field": "images[0]", "ok": True,
                 "url": "https://suanliai.top/api/media/input/a.jpg"},
                {"field": "images[1]", "ok": True,
                 "url": "https://suanliai.top/api/media/input/b.jpg"},
                {"field": "audios[0]", "ok": True,
                 "url": "https://suanliai.top/api/media/input/c.wav"}]}


def test_算力批量review一次请求同序映射():
    reg, http, _ = _registrar([_json(_review_ok())])
    inputs = [_input("image", url="https://oss/a.jpg"),
              _input("image", url="https://oss/b.jpg"),
              _input("audio", url="https://oss/c.wav")]
    out = reg.register_batch(_route("suanliai", "review_then_ref"), inputs)

    # 只发一次 review；无需下载（站方拉公网 URL）
    assert len(http.posts) == 1 and http.gets == []
    call = http.posts[0]
    assert call["url"] == "https://suanliai.top/v1/assets/review"
    assert call["headers"]["Authorization"] == "Bearer tok-s"
    body = json.loads(call["body"].decode())
    assert body == {"images": ["https://oss/a.jpg", "https://oss/b.jpg"],
                    "audios": ["https://oss/c.wav"]}  # 无视频不带 videos 键

    assert [r.ref for r in out] == [
        "https://suanliai.top/api/media/input/a.jpg",
        "https://suanliai.top/api/media/input/b.jpg",
        "https://suanliai.top/api/media/input/c.wav"]
    assert all(r.ref_type == "review_url" for r in out)
    assert all(r.expires_at == T0 + timedelta(hours=24) for r in out)


def test_算力review重复URL保留重复并同序回显():
    payload = {"success": True, "all_ok": True,
               "images": [], "videos": [],
               "audios": ["https://suanliai.top/u/a.mp3",
                          "https://suanliai.top/u/a.mp3"],
               "items": [
                   {"field": "audios[0]", "ok": True,
                    "url": "https://suanliai.top/u/a.mp3"},
                   {"field": "audios[1]", "ok": True,
                    "url": "https://suanliai.top/u/a.mp3"}]}
    reg, _, _ = _registrar([_json(payload)])
    inputs = [_input("audio", filename="a.mp3", url="https://oss/a.mp3"),
              _input("audio", filename="a.mp3", url="https://oss/a.mp3")]
    out = reg.register_batch(_route("suanliai", "review_then_ref"), inputs)
    assert len(out) == 2 and out[0].ref == out[1].ref


def test_算力review部分失败按field报错():
    bad = _review_ok()
    bad["all_ok"] = False
    bad["items"][1]["ok"] = False
    bad["items"][1]["error"] = "fetch timeout"
    reg, _, _ = _registrar([_json(bad)])
    inputs = [_input("image", url="https://oss/a.jpg"),
              _input("image", url="https://oss/b.jpg")]
    with pytest.raises(AssetRegistrationError) as ei:
        reg.register_batch(_route("suanliai", "review_then_ref"), inputs)
    assert "images[1]" in str(ei.value)


def test_算力review顶层success为假报错():
    bad = _review_ok()
    bad["success"] = False
    reg, _, _ = _registrar([_json(bad)])
    with pytest.raises(AssetRegistrationError):
        reg.register_batch(_route("suanliai", "review_then_ref"),
                           [_input("image", url="https://oss/a.jpg")])


def test_算力review非2xx报错():
    reg, _, _ = _registrar([_json({"error": "x"}, status=500)])
    with pytest.raises(AssetRegistrationError) as ei:
        reg.register_batch(_route("suanliai", "review_then_ref"),
                           [_input("image", url="https://oss/a.jpg")])
    assert ei.value.status == 500


# ---------- TTL 缓存：跨批命中与跨供应商隔离 ----------

def test_算力review缓存命中只提交未登记素材且保持原顺序():
    # 第一批：a.jpg
    reg, http, _ = _registrar([_json({
        "success": True, "all_ok": True,
        "images": ["https://suanliai.top/u/a.jpg"], "videos": [], "audios": [],
        "items": [{"field": "images[0]", "ok": True,
                   "url": "https://suanliai.top/u/a.jpg"}]})])
    route = _route("suanliai", "review_then_ref")
    a = _input("image", url="https://oss/a.jpg")
    b = _input("image", url="https://oss/b.jpg")
    reg.register_batch(route, [a])

    # 第二批：a（缓存）+ b（新）。响应只需为 b 占位
    http.post_responses.append(_json({
        "success": True, "all_ok": True,
        "images": ["https://suanliai.top/u/b.jpg"], "videos": [], "audios": [],
        "items": [{"field": "images[0]", "ok": True,
                   "url": "https://suanliai.top/u/b.jpg"}]}))
    out = reg.register_batch(route, [a, b])
    sent = json.loads(http.posts[1]["body"].decode())
    assert sent == {"images": ["https://oss/b.jpg"]}  # 只发未登记的 b
    assert [r.ref for r in out] == [
        "https://suanliai.top/u/a.jpg",
        "https://suanliai.top/u/b.jpg"]                 # 输出仍按原顺序合并


def test_缓存按供应商隔离同一OSS素材两家都要上传():
    # 同一 OSS URL：贰春走 multipart、三宝走 raw，互不串用引用
    reg, http, _ = _registrar(
        [_json({"media_id": "med_x", "media_type": "image",
                "expires_at": "2026-10-14T02:00:00Z"}),
         _json({"file": {"url": "https://sanbaobeauty.com/uploads/x.jpg"}})],
        {"https://oss/x.jpg": b"x"})
    inp = _input()
    e = reg.register_batch(_route("erchun", "provider_upload"), [inp])[0]
    b = reg.register_batch(_route("sanbao", "provider_upload"), [inp])[0]
    assert e.ref == "med_x" and b.ref.endswith("/x.jpg")
    assert len(http.posts) == 2  # 没有因为缓存而漏传第二家


# ---------- 配置与下载防护 ----------

def test_provider_upload缺少该供应商端点报错():
    reg = ProviderAssetRegistrar(endpoints={}, http=FakeHttp(), clock=lambda: T0)
    with pytest.raises(AssetRegistrationError):
        reg.register_batch(_route("erchun", "provider_upload"), [_input()])


def test_下载字节超上限报错():
    reg, _, _ = _registrar(
        [_json({"media_id": "med_big"})],
        {"https://oss/x.jpg": b"x" * 100},
        max_download_bytes=10)
    with pytest.raises(AssetRegistrationError):
        reg.register_batch(_route("erchun", "provider_upload"), [_input()])
