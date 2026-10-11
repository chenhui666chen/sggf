# -*- coding: utf-8 -*-
"""同一个 model ID 只允许有一个 @register_model 注册点。

背景：ModelRegistry.register() 是无条件 last-write-wins，既不报警也不去重
（adapters/registry.py:203-220）。仓库里曾有 9 个 ID 被注册了两次——一次在早期的
单体适配器，一次在后来的 adapters/dashscope/* 拆分模块。
谁生效取决于装饰器的执行顺序，而这个顺序又受「某模块是否已被传递导入过」影响：
_ensure_builtin_registration 里 dashscope 叶子排在最后，正常进程下 dashscope 胜出；
但若 dashscope 在注册流程之前就被别的模块传递导入，它的装饰器反而先跑，
legacy 单体适配器就会翻盘，于是「线上到底跑的哪个适配器」变成不可预测的。

三个早期单体适配器（wan26_video_adapter.py、wanx_adapter.py、qwen_multimodal_adapter.py）已整体删除：
这 9 个重复注册点正是它们与 adapters/dashscope/* 拆分模块各注册一次造成的——
wan26 带 5 个 @register_model（万相视频线 ID），wanx 带 1 个（万相文生图 ID），
qwen_multimodal 带 3 个（即下方 DASHSCOPE_OWNED 列出的那 3 个现役 ID）；
除 adapters/registry.py 的自动导入列表外没有别的生产导入方（列表项已随文件一并移除），重复注册点自此不可能再出现。
具体 ID 清单不在本注释里复述：万相系已退役，写进源码会被退役引用审计计为待改项。

本文件锁定：注册点唯一，且这 3 个 ID 稳定解析到 dashscope 实现。
注：这批单体适配器不覆写 generate，沿用 adapters/base.py 的 TaskSpec 模板；UnifiedMediaRuntime 按首参名
嗅探后本可以调到它们，真正失效原因是这里的重复注册被 last-write-wins 覆盖。另一条并存的失效原因是媒体线
存在不经过 runtime、直接按 kwargs 调用适配器的入口，task-only 签名在那种入口上会 TypeError。
两种失效都不报错，所以除了本文件的注册唯一性守卫，签名约定也必须钉在文档里（见 docs/MODEL_INTEGRATION_REFERENCE.md §6.7）。
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = ROOT_DIR / "adapters"

_DECORATOR_RE = re.compile(r"""@register_model\(\s*["']([^"']+)["']""")

# 曾被注册两次的 ID 中仍在售的 3 个，以及它们应当稳定解析到的模块
DASHSCOPE_OWNED = {
    "qwen-image-edit-plus": "adapters.dashscope.image_edit",
    "qwen-image-edit-max": "adapters.dashscope.image_edit",
    "qwen3-vl-plus": "adapters.dashscope.multimodal",
}

LEGACY_MODULES = {
    "adapters/model_adapters.py",
}


def _scan_registrations() -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for path in sorted(ADAPTERS_DIR.rglob("*.py")):
        relative = path.relative_to(ROOT_DIR).as_posix()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for match in _DECORATOR_RE.finditer(line):
                found[match.group(1)].append(relative)
    return found


class TestRegistrationUniqueness:
    def test_no_model_id_is_registered_twice(self) -> None:
        duplicates = {k: v for k, v in _scan_registrations().items() if len(v) > 1}
        assert duplicates == {}

    def test_legacy_modules_no_longer_claim_dashscope_ids(self) -> None:
        registrations = _scan_registrations()
        offenders = {
            model_id: files
            for model_id, files in registrations.items()
            if model_id in DASHSCOPE_OWNED and set(files) & LEGACY_MODULES
        }
        assert offenders == {}


class TestResolutionIsStable:
    @pytest.mark.parametrize("model_id,module", sorted(DASHSCOPE_OWNED.items()))
    def test_resolves_to_dashscope_implementation(self, model_id, module) -> None:
        from adapters.registry import default_registry

        adapter = default_registry().get_adapter(model_id)
        assert adapter is not None, f"{model_id} 未注册适配器"
        assert type(adapter).__module__ == module

    @pytest.mark.parametrize("model_id", sorted(DASHSCOPE_OWNED))
    def test_resolution_survives_registry_reload(self, model_id) -> None:
        # clear() 会重置 _builtin_loaded，重新加载后胜出者不能变
        from adapters.registry import default_registry

        registry = default_registry()
        before = type(registry.get_adapter(model_id)).__module__
        registry.clear()
        after = type(default_registry().get_adapter(model_id)).__module__
        assert before == after == DASHSCOPE_OWNED[model_id]
