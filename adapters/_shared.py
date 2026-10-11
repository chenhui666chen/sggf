# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import base64
import json
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 配置
# ============================================================

_REPO_ROOT = Path(__file__).resolve().parents[1]

# 适配器模块可能在 backend 的 env_loader 之前被导入（脚本、单测、直接 import），
# 此时进程环境里没有任何 key，因此这里按 backend/.env -> 根 .env 的顺序兜底加载一次。
# override=False 保证已经存在的非空环境变量优先。
for _env_file in (_REPO_ROOT / "backend" / ".env", _REPO_ROOT / ".env"):
    if _env_file.exists():
        load_dotenv(_env_file, override=False)


class MissingAPIKeyError(RuntimeError):
    """供应商 API key 未配置。"""


def _api_key(env_name: str) -> str:
    return os.getenv(env_name, "").strip()


def require_api_key(env_name: str) -> str:
    """读取供应商 API key，未配置时立即报错，避免带着空凭证发起请求。"""
    value = _api_key(env_name)
    if not value:
        raise MissingAPIKeyError(
            f"缺少环境变量 {env_name}，请在 backend/.env 或项目根目录 .env 中配置后重试。"
        )
    return value


DASHSCOPE_API_KEY = _api_key("DASHSCOPE_API_KEY")
VOLCENGINE_API_KEY = _api_key("VOLCENGINE_API_KEY")
MUREKA_API_KEY = _api_key("MUREKA_API_KEY")
MUREKA_API_URL = os.getenv("MUREKA_API_URL", "https://api.mureka.cn")

# Mureka 纯音乐端点口径，2026-10-11 官方文档 + 真实调用确证，两处调用点共用本常量：
# - instrumental 的 model 枚举只有 auto/mureka-7.6/mureka-8/mureka-9/mureka-9.5，
#   mureka-o1 与 mureka-v8 实测 400（mureka-o2 只挂在 /v1/song/generate）；auto 当时解析为 mureka-9.5，
#   固定写死代际是为了让产出可复现，上游再发新版必须重测后再改。
# - n 缺省为 2 且按数量计费，实测不发 n 时返回 2 首、扣费翻倍，而我们只取 choices[0]。
MUREKA_INSTRUMENTAL_MODEL = "mureka-9.5"
MUREKA_INSTRUMENTAL_N = 1
# 上游实测的终态集合（preparing/queued/running/streaming/reviewing 为非终态）
MUREKA_PENDING_STATUSES = ("preparing", "queued", "running", "streaming", "reviewing", "processing", "pending")
MUREKA_FAILED_STATUSES = ("failed", "error", "timeouted", "cancelled")

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
VOLCENGINE_BASE = "https://ark.cn-beijing.volces.com/api/v3"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _encode_image(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        return value
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        return value
    suffix = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"


def _poll_dashscope_task(task_id: str, api_key: str, timeout: int = 600, interval: int = 3) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"{DASHSCOPE_BASE}/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            data = r.json()
            status = data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                return data
            elif status in {"FAILED", "CANCELED"}:
                raise RuntimeError(f"Task failed: {data.get('output', {}).get('message', 'Unknown')}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Task timed out after {timeout}s")


def _poll_volcengine_task(task_id: str, api_key: str, timeout: int = 600, interval: int = 5) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"{VOLCENGINE_BASE}/contents/generations/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=10,
            )
            data = r.json()
            status = data.get("status", "")
            if status == "succeeded":
                return data
            elif status in {"failed", "cancelled"}:
                raise RuntimeError(f"Task failed: {data.get('last_error', {}).get('message', 'Unknown')}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Task timed out after {timeout}s")
