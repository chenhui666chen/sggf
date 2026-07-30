from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def get_backend_root() -> Path:
    """返回 backend 根目录。"""
    return Path(__file__).resolve().parents[2]


def get_project_root() -> Path:
    """
    返回运行时可用的项目根目录。

    本地源码运行时返回仓库根目录；
    Docker 容器中如果仓库根目录未完整挂载，则回退为 backend 根目录。
    """
    backend_root = get_backend_root()
    candidate = backend_root.parent
    markers = (
        candidate / "backend" / "app",
        candidate / "pipeline",
        candidate / "agents",
        candidate / "core",
    )

    if any(marker.exists() for marker in markers):
        return candidate

    return backend_root


def get_env_file_candidates() -> tuple[Path, ...]:
    """
    返回按优先级排序的环境文件候选列表。

    优先 backend/.env，其次项目根目录 .env。
    """
    backend_root = get_backend_root()
    project_root = get_project_root()

    ordered_paths = (
        backend_root / ".env",
        project_root / ".env",
    )

    unique_paths: list[Path] = []
    for path in ordered_paths:
        if path not in unique_paths:
            unique_paths.append(path)

    return tuple(unique_paths)


def load_project_env(*, override: bool = False) -> tuple[Path, ...]:
    """
    按统一顺序加载环境变量。

    - backend/.env 优先
    - 根目录 .env 作为兜底
    - 默认不覆盖已有的非空环境变量
    - 空环境变量视为未配置，允许由 .env 补齐
    """
    loaded_files = [
        env_file
        for env_file in get_env_file_candidates()
        if env_file.exists()
    ]

    if not override:
        env_keys = {
            key
            for env_file in loaded_files
            for key in dotenv_values(env_file)
        }
        for key in env_keys:
            if os.environ.get(key) == "":
                os.environ.pop(key, None)

    for env_file in loaded_files:
        load_dotenv(env_file, override=override)

    return tuple(loaded_files)
