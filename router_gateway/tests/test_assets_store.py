# -*- coding: utf-8 -*-
"""AssetStore 契约测试：key 规则、白名单、内容寻址去重；网络层全部注入假客户端。"""
import hashlib
from datetime import datetime, timezone

import pytest

from router_gateway.assets.asset_store import AssetError, AssetStore, build_object_key
from router_gateway.assets.oss_client import OssError


FIXED_NOW = datetime(2026, 10, 12, 3, 4, 5, tzinfo=timezone.utc)
PREFIX = "shared/audio_library/router_refs"


class FakeOssClient:
    def __init__(self, head_result=None, put_error=None):
        # head_result: None=默认404, dict=HEAD 200 元数据
        self.head_result = head_result
        self.put_error = put_error
        self.puts = []
        self.heads = []
        self.deletes = []

    def head(self, object_key):
        self.heads.append(object_key)
        if self.head_result is not None:
            return self.head_result
        return {"exists": False, "status_code": 404}

    def public_url(self, object_key):
        return f"https://audio.sggf.net/{object_key}"

    def put_bytes(self, object_key, content, content_type):
        self.puts.append({"key": object_key, "content": content,
                          "content_type": content_type})
        if self.put_error:
            raise self.put_error
        return f"https://audio.sggf.net/{object_key}"

    def delete(self, object_key):
        self.deletes.append(object_key)


def _store(client, tmp_path, max_bytes=100 * 1024 * 1024):
    return AssetStore(client, prefix=PREFIX, max_bytes=max_bytes,
                      clock=lambda: FIXED_NOW)


def _write(tmp_path, name, data=b"\x89PNG\r\n"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_正常stage上传并返回完整元数据(tmp_path):
    client = FakeOssClient()
    store = _store(client, tmp_path)
    p = _write(tmp_path, "a.png")

    asset = store.stage_path(p, job_id="job-1")

    sha12 = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    assert asset.object_key == f"{PREFIX}/2026-10-12/job-1/{sha12}.png"
    assert asset.public_url == f"https://audio.sggf.net/{asset.object_key}"
    assert asset.sha256 == hashlib.sha256(p.read_bytes()).hexdigest()
    assert asset.size == len(p.read_bytes())
    assert asset.content_type == "image/png"
    assert len(client.puts) == 1
    assert client.puts[0]["content_type"] == "image/png"


def test_key按UTC日期分区且服务端完全生成(tmp_path):
    key = build_object_key(prefix=PREFIX, job_id="j1", sha256="a" * 64,
                           extension=".jpg", now=FIXED_NOW)
    assert key == f"{PREFIX}/2026-10-12/j1/{'a' * 12}.jpg"


@pytest.mark.parametrize("bad_job", ["", "../etc", "a/b", "a b", "x" * 65, "a.b", "中文"])
def test_非法job_id拒绝(tmp_path, bad_job):
    store = _store(FakeOssClient(), tmp_path)
    with pytest.raises(AssetError):
        store.stage_path(_write(tmp_path, "a.png"), job_id=bad_job)


@pytest.mark.parametrize("name", ["a.exe", "a.txt", "a.zip", "a"])
def test_非白名单扩展名拒绝(tmp_path, name):
    store = _store(FakeOssClient(), tmp_path)
    with pytest.raises(AssetError):
        store.stage_path(_write(tmp_path, name), job_id="job-1")


@pytest.mark.parametrize("name,ctype", [
    ("a.jpg", "image/jpeg"), ("a.jpeg", "image/jpeg"), ("a.webp", "image/webp"),
    ("a.mp4", "video/mp4"), ("a.mov", "video/quicktime"),
    ("a.mp3", "audio/mpeg"), ("a.wav", "audio/wav"), ("a.m4a", "audio/mp4"),
])
def test_白名单扩展名的content_type映射(tmp_path, name, ctype):
    client = FakeOssClient()
    asset = _store(client, tmp_path).stage_path(_write(tmp_path, name), job_id="job-1")
    assert asset.content_type == ctype


def test_本地文件不存在抛错(tmp_path):
    store = _store(FakeOssClient(), tmp_path)
    with pytest.raises(AssetError):
        store.stage_path(tmp_path / "missing.png", job_id="job-1")


def test_超过大小上限拒绝上传(tmp_path):
    client = FakeOssClient()
    store = _store(client, tmp_path, max_bytes=4)
    with pytest.raises(AssetError):
        store.stage_path(_write(tmp_path, "a.png", b"12345"), job_id="job-1")
    assert client.puts == []


def test_HEAD命中且字节数一致时跳过上传(tmp_path):
    p = _write(tmp_path, "a.png")
    size = p.stat().st_size
    client = FakeOssClient(head_result={"exists": True, "content_length": size})
    store = _store(client, tmp_path)

    asset = store.stage_path(p, job_id="job-1")

    assert client.heads and client.puts == []
    assert asset.public_url.startswith("https://audio.sggf.net/")


def test_HEAD命中但字节数不一致时重新PUT覆盖(tmp_path):
    p = _write(tmp_path, "a.png")
    client = FakeOssClient(head_result={"exists": True, "content_length": 999})
    store = _store(client, tmp_path)

    store.stage_path(p, job_id="job-1")

    assert len(client.puts) == 1


def test_相同内容不同文件名映射同一对象key(tmp_path):
    client = FakeOssClient()
    store = _store(client, tmp_path)
    p1 = _write(tmp_path, "first.png", b"SAME-BYTES")
    p2 = _write(tmp_path, "second.png", b"SAME-BYTES")

    a1 = store.stage_path(p1, job_id="job-1")
    a2 = store.stage_path(p2, job_id="job-1")

    assert a1.object_key == a2.object_key


def test_release委托删除云端对象(tmp_path):
    client = FakeOssClient()
    store = _store(client, tmp_path)
    store.release("shared/audio_library/router_refs/2026-10-12/j/x.png")
    assert client.deletes == ["shared/audio_library/router_refs/2026-10-12/j/x.png"]


def test_上传失败错误向外传播不降级(tmp_path):
    client = FakeOssClient(put_error=OssError("PUT failed: 403", status=403))
    store = _store(client, tmp_path)
    with pytest.raises(OssError):
        store.stage_path(_write(tmp_path, "a.png"), job_id="job-1")
