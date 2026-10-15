# -*- coding: utf-8 -*-
"""成片交付转存器单测：自有域名直透，上游链接下载后落自有 OSS。"""
import json
import shutil
import subprocess

import pytest

from router_gateway.assets.delivery import (
    ContentDeliverer,
    DeliveryError,
    sanitize_mp4_metadata,
)
from router_gateway.assets.oss_client import OssError

# 最小合法 mp4 载荷头（ftyp box），用于单测中触发剥离路径
_MP4_HEADER = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
_WEBM_HEADER = b"\x1a\x45\xdf\xa3" + b"\x01" * 32


class FakeOss:
    def __init__(self, failures=0):
        self.puts = []
        self._failures = failures

    def put_bytes(self, object_key, content, content_type):
        self.puts.append((object_key, content, content_type))
        if self._failures > 0:
            self._failures -= 1
            raise OssError("OSS PUT failed: 500", status=500)
        return f"https://sggf-router-video.oss-cn-shanghai.aliyuncs.com/{object_key}"


def test_成片已是自有域名时直透不下载不转存():
    downloads = []
    deliverer = ContentDeliverer(
        FakeOss(), own_hosts=("video.sggf.net",),
        downloader=lambda url: downloads.append(url) or b"x")
    source = "https://video.sggf.net/router_gateway/videos/2026/09/old.mp4"

    assert deliverer.deliver("job1", _created_at(), source) == source
    assert downloads == []


def test_上游成片下载后按任务月份落盘并返回自有地址():
    downloads = []
    oss = FakeOss()

    def downloader(url):
        downloads.append(url)
        return b"fake-mp4-bytes"

    deliverer = ContentDeliverer(
        oss, own_hosts=("sggf-router-video.oss-cn-shanghai.aliyuncs.com",),
        downloader=downloader, sanitizer=lambda content: content)
    final = deliverer.deliver(
        "abc123", _created_at(), "https://media.youkou.cc/uploads/x.mp4?auth_key=z")

    assert downloads == ["https://media.youkou.cc/uploads/x.mp4?auth_key=z"]
    assert oss.puts == [(
        "router_gateway/videos/2026/10/abc123.mp4",
        b"fake-mp4-bytes", "video/mp4")]
    assert final == ("https://sggf-router-video.oss-cn-shanghai.aliyuncs.com/"
                     "router_gateway/videos/2026/10/abc123.mp4")


def test_下载失败统一抛DeliveryError便于补偿():
    def boom(url):
        raise RuntimeError("connection reset")

    deliverer = ContentDeliverer(
        FakeOss(), own_hosts=("own.example.com",), downloader=boom)
    with pytest.raises(DeliveryError):
        deliverer.deliver("j1", _created_at(), "https://v/x.mp4")


def test_OSS上传失败统一抛DeliveryError便于补偿():
    deliverer = ContentDeliverer(
        FakeOss(failures=1), own_hosts=("own.example.com",),
        downloader=lambda url: b"body")
    with pytest.raises(DeliveryError):
        deliverer.deliver("j1", _created_at(), "https://v/x.mp4")


def test_mp4成片转存前先剥离容器元数据():
    seen = {}
    oss = FakeOss()

    def sanitizer(content):
        seen["input"] = content
        return content + b"::clean"

    deliverer = ContentDeliverer(
        oss, own_hosts=("own.example.com",),
        downloader=lambda url: _MP4_HEADER, sanitizer=sanitizer)
    deliverer.deliver("j1", _created_at(), "https://v/x.mp4")

    assert seen["input"] == _MP4_HEADER
    assert oss.puts[0][1] == _MP4_HEADER + b"::clean"


def test_元数据剥离失败时拒绝把原始成片转存OSS():
    def boom(content):
        raise DeliveryError("ffmpeg missing")

    oss = FakeOss()
    deliverer = ContentDeliverer(
        oss, own_hosts=("own.example.com",),
        downloader=lambda url: _MP4_HEADER, sanitizer=boom)
    with pytest.raises(DeliveryError):
        deliverer.deliver("j1", _created_at(), "https://v/x.mp4")
    assert oss.puts == []


def test_非mp4容器不经过剥离器按原样转存():
    calls = []
    oss = FakeOss()
    deliverer = ContentDeliverer(
        oss, own_hosts=("own.example.com",),
        downloader=lambda url: _WEBM_HEADER,
        sanitizer=lambda content: calls.append(content) or content)
    deliverer.deliver("j1", _created_at(), "https://v/x.webm")
    assert calls == []
    assert oss.puts[0][1] == _WEBM_HEADER


_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(not _FFMPEG or not _FFPROBE,
                    reason="本机无 ffmpeg/ffprobe，跳过元数据剥离实证")
def test_ffmpeg实证剥离上游写入的厂商标签(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [_FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
         "-metadata", "title=UPSTREAM-VENDOR-X",
         "-metadata", "comment=provider-leak-12345",
         "-c:v", "mpeg4", "-q:v", "8", str(source)],
        check=True, timeout=120)
    cleaned = sanitize_mp4_metadata(source.read_bytes())
    assert cleaned[:4] != b"" and cleaned[4:8] == b"ftyp"

    out = tmp_path / "cleaned.mp4"
    out.write_bytes(cleaned)
    probe = json.loads(subprocess.run(
        [_FFPROBE, "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(out)],
        check=True, capture_output=True, timeout=120).stdout)
    tags = (probe.get("format") or {}).get("tags") or {}
    assert "UPSTREAM-VENDOR-X" not in json.dumps(tags, ensure_ascii=False)
    assert "provider-leak-12345" not in json.dumps(tags, ensure_ascii=False)
    assert any(s.get("codec_type") == "video" for s in probe["streams"])


def _created_at():
    from datetime import datetime, timezone
    return datetime(2026, 10, 12, 8, 30, 0, tzinfo=timezone.utc)
