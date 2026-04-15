"""
API v1 路由模块

使用懒加载避免导入单个路由模块时连带触发整个 v1 包的重型依赖，
这样测试收集和局部工具导入都会更稳定。
"""

from __future__ import annotations

from importlib import import_module


__all__ = [
    "auth",
    "projects",
    "chapters",
    "reviews",
    "workflow",
    "settings",
    "characters",
    "book_parser",
    "model_catalog",
    "asset_studio",
    "user_assets",
    "user_center",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
