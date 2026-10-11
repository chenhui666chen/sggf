# -*- coding: utf-8 -*-
"""tests/ 共享夹具。"""

from __future__ import annotations

import pytest

from model_registry_reset import reload_llm_registry


@pytest.fixture
def restored_llm_registry():
    """用例前后各重装一次 LLM 注册单例，供会 clear() 它的用例声明使用。"""
    reload_llm_registry()
    yield
    reload_llm_registry()
