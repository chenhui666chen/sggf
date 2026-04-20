# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import base64
import json
from pathlib import Path
from typing import Any, Dict

import requests

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 配置
# ============================================================

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip() or "***REDACTED-DASHSCOPE-KEY***"
VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "").strip() or "8cb15ed7-4471-49ee-ad7e-eece828e1e24"
VIDU_API_KEY = os.getenv("VIDU_API_KEY", "").strip() or "vda_942023019369345024_eDxHYrWsuosFvrIIKzPQhSY384hs9iCv"
MUREKA_API_KEY = os.getenv("MUREKA_API_KEY", "").strip() or "op_mj8g9cd9Sav2RaX2yfTKWeDwfQ1q6G4"
MUREKA_API_URL = os.getenv("MUREKA_API_URL", "https://api.mureka.cn")

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
VOLCENGINE_BASE = "https://ark.cn-beijing.volces.com/api/v3"
VIDU_BASE = "https://api.vidu.cn"


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


def _poll_vidu_task(task_id: str, api_key: str, timeout: int = 300, interval: int = 5) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"https://api.vidu.cn/ent/v2/tasks/{task_id}/creations",
                headers={"Authorization": f"Token {api_key}"},
                timeout=10,
            )
            if r.status_code == 404:
                time.sleep(interval)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Vidu poll HTTP {r.status_code}: {r.text[:100]}")
            data = r.json()
            state = data.get("state", "")
            if state == "success":
                return data
            elif state == "failed":
                raise RuntimeError(f"Vidu task failed: {data}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Vidu task timed out after {timeout}s")

