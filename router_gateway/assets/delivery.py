# -*- coding: utf-8 -*-
"""成片交付转存：上游成片下载后落入自有 OSS，自有域名链接直透。"""
from __future__ import annotations

import shutil
import json
import math
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from .oss_client import OssClient
from .safe_fetch import SafeFetchError, fetch_bytes, fetch_to_file

# 成片在 OSS 的 key 前缀（按任务创建月份分目录）
OBJECT_KEY_PREFIX = "router_gateway/videos"
VIDEO_CONTENT_TYPE = "video/mp4"
VIDEO_CONTENT_TYPES = ("video/mp4", "video/quicktime", "video/webm",
                       "application/octet-stream")
# ffmpeg 剥离 mp4 容器级元数据（厂商可能在 moov/udta、format tags 中
# 写入 encoder/品牌/任务标识，转存时必须抹除；流复制不重编码、几乎零损耗）
_FFMPEG_STRIP_ARGS = [
    "-map", "0",
    "-map_metadata", "-1",          # 全局/容器级 tags
    "-map_metadata:s:v", "-1",      # 视频流级 tags
    "-map_metadata:s:a", "-1",      # 音频流级 tags（成片可能带默认 AAC 音轨）
    "-map_chapters", "-1",
    "-c", "copy", "-bitexact",
]


class DeliveryError(Exception):
    """转存过程中的可重试失败（下载或上传）。"""


def download_bytes(url: str, *, timeout: int = 60,
                   max_bytes: int = 512 * 1024 * 1024) -> bytes:
    """下载上游成片；任何网络/HTTP 失败统一抛 DeliveryError 供调用方补偿重试。"""
    try:
        response = fetch_bytes(
            url, timeout=timeout, max_bytes=max_bytes,
            expected_content_types=VIDEO_CONTENT_TYPES)
        _validate_video_payload(response.body)
        return response.body
    except SafeFetchError as exc:
        raise DeliveryError(str(exc)) from exc


def _validate_video_payload(content: bytes) -> None:
    """校验常见视频容器头，避免把 HTML 错误页或任意大文件归档为成片。"""
    if len(content) < 12:
        raise DeliveryError("成片文件过小或缺少有效视频文件头")
    if content[4:8] == b"ftyp":
        return
    if content[:4] == b"\x1a\x45\xdf\xa3":
        return
    raise DeliveryError("成片文件头不是受支持的视频容器")


def is_mp4(content: bytes) -> bool:
    return len(content) >= 8 and content[4:8] == b"ftyp"


def sanitize_mp4_metadata(content: bytes, *, ffmpeg_bin: str | None = None) -> bytes:
    """流复制重封装剥离 mp4 容器元数据；ffmpeg 缺失或失败一律抛 DeliveryError。

    失败采用 fail-closed：调用方不得把含厂商标签的原片转存到自有 OSS。
    """
    with tempfile.TemporaryDirectory(prefix="rg_delivery_") as tmp:
        src = Path(tmp) / "src.mp4"
        dst = Path(tmp) / "dst.mp4"
        src.write_bytes(content)
        sanitize_mp4_file(src, dst, ffmpeg_bin=ffmpeg_bin)
        return dst.read_bytes()


def sanitize_mp4_file(src: Path, dst: Path, *, ffmpeg_bin: str | None = None) -> None:
    ffmpeg = ffmpeg_bin or shutil.which("ffmpeg")
    if not ffmpeg:
        raise DeliveryError("未找到 ffmpeg，无法剥离成片元数据")
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-y", "-i", str(src), *_FFMPEG_STRIP_ARGS, str(dst)],
            capture_output=True, timeout=180)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "ignore")[-500:]
            raise DeliveryError(f"ffmpeg 元数据剥离失败: {detail}")
        with dst.open("rb") as cleaned:
            valid = is_mp4(cleaned.read(12))
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError(f"ffmpeg 元数据剥离失败: {exc}") from exc
    if not valid:
        raise DeliveryError("元数据剥离后的成片不是有效 mp4")


class ContentDeliverer:
    def __init__(self, oss, *, own_hosts, downloader=download_bytes,
                 sanitizer=sanitize_mp4_metadata):
        self._oss = oss
        self._own_hosts = tuple(own_hosts)
        self._downloader = downloader
        self._sanitizer = sanitizer

    def deliver(self, job_id: str, created_at, source_url: str) -> str:
        host = (urllib.parse.urlsplit(source_url).hostname or "").lower()
        if host in self._own_hosts:
            return source_url
        try:
            content = self._downloader(source_url)
        except DeliveryError:
            raise
        except Exception as exc:
            raise DeliveryError(f"下载上游成片失败: {exc}") from exc
        # mp4 统一抹除容器元数据防厂商侧信道；其余容器维持原行为
        if is_mp4(content):
            content = self._sanitizer(content)
        object_key = (f"{OBJECT_KEY_PREFIX}/{created_at:%Y/%m}/"
                      f"{job_id}.mp4")
        try:
            return self._oss.put_bytes(object_key, content, VIDEO_CONTENT_TYPE)
        except DeliveryError:
            raise
        except Exception as exc:
            raise DeliveryError(f"成片转存 OSS 失败: {exc}") from exc


def probe_video_file(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise DeliveryError("未找到 ffprobe，无法验证成片结构")
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
            capture_output=True, timeout=30)
        if result.returncode != 0:
            raise DeliveryError("成片结构校验失败")
        metadata = json.loads(result.stdout)
        duration = float(metadata.get("format", {}).get("duration", 0))
        videos = [stream for stream in metadata.get("streams", [])
                  if stream.get("codec_type") == "video"]
        if not math.isfinite(duration) or duration <= 0 or not videos:
            raise DeliveryError("成片缺少有效的视频流或时长")
        if any(int(stream.get("width", 0)) <= 0 or int(stream.get("height", 0)) <= 0
               for stream in videos):
            raise DeliveryError("成片分辨率无效")
        return metadata
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError("成片结构校验失败") from exc


class FileContentDeliverer:
    def __init__(self, oss, *, own_hosts, downloader=fetch_to_file,
                 sanitizer=sanitize_mp4_file, probe=probe_video_file):
        self._oss = oss
        self._own_hosts = tuple(own_hosts)
        self._downloader = downloader
        self._sanitizer = sanitizer
        self._probe = probe

    def deliver(self, job_id: str, created_at, source_url: str) -> str:
        host = (urllib.parse.urlsplit(source_url).hostname or "").lower()
        if host in self._own_hosts:
            return source_url
        try:
            with tempfile.TemporaryDirectory(prefix="rg_delivery_") as tmp:
                source = Path(tmp) / "source.video"
                target = Path(tmp) / "delivered.mp4"
                self._downloader(source_url, source, expected_content_types=VIDEO_CONTENT_TYPES)
                with source.open("rb") as content:
                    _validate_video_payload(content.read(12))
                self._sanitizer(source, target)
                self._probe(target)
                key = f"{OBJECT_KEY_PREFIX}/{created_at:%Y/%m}/{job_id}.mp4"
                return self._oss.put_file(key, target, VIDEO_CONTENT_TYPE)
        except DeliveryError:
            raise
        except Exception as exc:
            raise DeliveryError(f"成片转存失败: {exc}") from exc


def build_deliverer(config) -> "FileContentDeliverer":
    """从 OSS 配置构造转存器：自有域名=桶默认域 + 配置的公共访问域（去重保序）。"""
    hosts = [urllib.parse.urlsplit(config.object_url("probe")).hostname]
    if config.public_host:
        hosts.append(urllib.parse.urlsplit(config.public_host).hostname)
    own_hosts = tuple(dict.fromkeys(h for h in hosts if h))
    return FileContentDeliverer(OssClient(config), own_hosts=own_hosts)
