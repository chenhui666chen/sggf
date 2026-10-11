# -*- coding: utf-8 -*-
"""共享的 LLM 注册单例重装工具。

放在独立模块而不是 conftest 里，是因为 module 级夹具无法依赖 function 级夹具，
部分用例需要直接调用而不是通过夹具。
"""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
LLM_MODELS_YAML = ROOT_DIR / "config" / "llm_models.yaml"


def reload_llm_registry() -> None:
    """按生产配置重装共享的 LLM 注册单例。

    UnifiedModelRegistry 是进程级单例，任何用例 clear() 之后都必须重装，否则后续模块
    读到的是被桩模型替换过的目录。重装不能只调 model_hub.initialize()：
    _initialized_adapters 一旦为 True，_ensure_adapters_loaded 就直接返回，
    core.llm_adapters 不会重新导入，@register_llm_model 注册点也就不会重跑，
    结果是 YAML 里的 spec 全在、适配器类全无。因此必须显式 reload 一次。
    """
    from core.model_hub import model_hub

    model_hub.registry.clear()
    if LLM_MODELS_YAML.exists():
        model_hub.initialize(str(LLM_MODELS_YAML))
    importlib.reload(importlib.import_module("core.llm_adapters"))
