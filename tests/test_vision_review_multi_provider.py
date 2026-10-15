# -*- coding: utf-8 -*-
"""视觉评审跨供应商接线守卫。

背景：视觉识别入口历史上只有百炼侧两个档位，`adapters/dashscope/chat.py` 里的实现把
"评审结构"与"百炼客户端"绑死，方舟侧无法复用，于是档案里已声明视觉理解能力的豆包
Seed 2.1 两档与 Qwen3.7 Plus 只能停在档案层，页面与白名单也一直是自持名单。

本文件钉住换代后的四件事：
1. 执行层供应商中立：两侧 mixin 都从 `VisionReviewMixin` 派生，各家只出客户端与关思考写法；
2. 新增档位真的能执行，且请求落在各自供应商的正确结构上（方舟 `thinking.type`、
   百炼顶层 `enable_thinking`、Qwen3.8 Omni 顶层 `reasoning_effort`），关思考必须显式带上，
   否则延迟与输出 token 翻倍；
3. 目录与白名单逐字相等：`vision_review` 分组必须等于 `analyze_image` / `analyze_video` 白名单，
   否则前端能选、后端 400 或运行期 adapter_missing 又会重现；反过来白名单多出页面选不到的档位，
   等于把"已退役"变成"退役了一半"。短剧 QC 线的 VLM 与视觉评审共用这份白名单，
   2026-10-12 QC 默认档迁完后，过渡期的子集判据已恢复为相等；
4. 判据带硬约束：页面维度表、执行层默认维度表与扣分约束表三源一致。三档实测都会把
   偏暗素材的 lighting 评到 9.8、把后 4 秒冻结素材的 smoothness 评到 8.5，
   提高抽帧率无效，只有把扣分下限写进提示词才收敛。
"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _import_root in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if _import_root not in sys.path:
        sys.path.insert(0, _import_root)

from adapters._shared_vision_review import VisionReviewMixin  # noqa: E402
from adapters.dashscope.chat import _DashScopeVisionReviewMixin  # noqa: E402
from adapters.volcengine.chat import _VolcengineVisionReviewMixin  # noqa: E402
from adapters.registry import registry  # noqa: E402

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQAAAH/wEBAwAB/8D/gAAAAElFTkSuQmCC"
)
_ANALYSIS_JSON = json.dumps(
    {"scores": {"clarity": {"score": 8, "comment": "主体清楚"}}, "summary": "可用"},
    ensure_ascii=False,
)


class _FakeCompletions:
    def __init__(self, recorder: dict, content: str) -> None:
        self._recorder = recorder
        self._content = content

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self._content))],
            usage=None,
        )


class _FakeChat:
    def __init__(self, recorder: dict, content: str) -> None:
        self.completions = _FakeCompletions(recorder, content)


def _install_fake_openai(monkeypatch, recorder: dict, content: str = _ANALYSIS_JSON) -> None:
    created: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = _FakeChat(recorder, content)

    recorder["__client__"] = created
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))


def _adapter(model_id: str):
    adapter = registry.get_adapter(model_id)
    assert adapter is not None, f"{model_id} 未注册 adapter"
    return adapter


def test_vision_layer_is_provider_neutral() -> None:
    """两侧档位共用同一执行层：任一供应商子类脱离 VisionReviewMixin 都算破坏中立层。"""
    assert issubclass(_DashScopeVisionReviewMixin, VisionReviewMixin)
    assert issubclass(_VolcengineVisionReviewMixin, VisionReviewMixin)


def test_volcengine_vision_review_hits_ark_with_thinking_disabled(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(_PNG_BYTES)
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")

    result = _adapter("doubao-seed-2-1-lite").analyze_image(
        image_path=str(image_path),
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    client_kwargs = recorder["__client__"]
    assert "ark.cn-beijing.volces.com" in client_kwargs["base_url"]
    assert "dashscope" not in client_kwargs["base_url"]
    assert recorder["model"] == "doubao-seed-2-1-lite-260915"
    assert recorder["extra_body"] == {"thinking": {"type": "disabled"}}, "方舟必须显式关闭深度思考"
    parts = recorder["messages"][0]["content"]
    assert next(part for part in parts if part.get("type") == "image_url")["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert result.metadata["result_data"]["scores"]["clarity"]["score"] == 8


def test_volcengine_video_review_sends_video_part(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-mp4-bytes")
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")

    result = _adapter("doubao-seed-2-1-pro").analyze_video(
        video_path=str(video_path),
        analysis_type="quality",
        criteria=["smoothness"],
    )

    assert result.success is True
    parts = recorder["messages"][0]["content"]
    assert next(part for part in parts if part.get("type") == "video_url")["video_url"]["url"].startswith(
        "data:video/mp4;base64,"
    )
    assert "smoothness" in json.dumps(parts, ensure_ascii=False)


def test_qwen_plus_vision_review_disables_thinking_on_compatible_mode(monkeypatch) -> None:
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _adapter("qwen-plus").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    client_kwargs = recorder["__client__"]
    assert client_kwargs["base_url"].endswith("/compatible-mode/v1")
    assert recorder["extra_body"] == {"enable_thinking": False}, "Qwen3.7 开思考实测慢 3~4 倍"


def test_omni_flash_closes_thinking_with_reasoning_effort(monkeypatch) -> None:
    """Qwen3.8 Omni Flash 的关思考写法和同族 Qwen3.7 不同：官方只认 OpenAI 标准参数
    `reasoning_effort`，`enable_thinking` 不在它的适用清单里，混用会静默保留 xhigh 思考。"""
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    assert recorder["reasoning_effort"] == "none"
    assert "extra_body" not in recorder, "本档不应带 enable_thinking，关思考只走 reasoning_effort"


def test_vision_catalog_group_equals_allowlist() -> None:
    """页面可见性（catalog）与可路由性（运行时白名单）必须逐字相等。

    白名单多出的档位在页面上选不到、只在运行期存在，等于把"退役了"变成"退役了一半"；
    分组多出的档位则页面可见但运行期拒单。2026-10-12 短剧 QC 默认档迁完 vl-plus 后，
    过渡期的 ⊆ 判据恢复为相等。
    """
    from app.services.asset_studio_model_catalog import get_asset_studio_model_sets
    from core.unified_media_runtime import _OPERATION_MODEL_IDS

    catalog_group = set(get_asset_studio_model_sets()["vision_review"])
    for operation in ("analyze_image", "analyze_video"):
        allowlist = set(_OPERATION_MODEL_IDS[operation])
        assert catalog_group == allowlist, (
            f"{operation} 分组与白名单不一致: 仅页面 {sorted(catalog_group - allowlist)} / "
            f"仅白名单 {sorted(allowlist - catalog_group)}"
        )


def test_omni_flash_is_routable_in_vision_line() -> None:
    """接线守卫：建档后必须真的进白名单与页面分组，否则档案在、页面在，运行期依旧选不到。"""
    from app.services.asset_studio_model_catalog import get_asset_studio_model_sets
    from core.unified_media_runtime import _OPERATION_MODEL_IDS

    assert "qwen3.8-omni-flash" in get_asset_studio_model_sets()["vision_review"]
    for operation in ("analyze_image", "analyze_video"):
        assert "qwen3.8-omni-flash" in _OPERATION_MODEL_IDS[operation]


def test_every_review_criterion_carries_a_scoring_ceiling() -> None:
    """判据三源一致：页面维度、执行层默认维度、扣分约束互相覆盖。

    缺约束的维度会退回 2026-10-12 三档实测出的共同失效模式：平均亮度 33.5 的偏暗素材
    lighting 给 9.8，后 4 秒完全静止的素材 smoothness 给 8.5，且把抽帧率从默认 2fps
    提到 8fps 判分不变（视频 token 涨 4 倍）——只有把扣分下限写进提示词才收敛。
    """
    from adapters._shared_vision_review import VISION_CRITERION_RUBRICS, VISION_DEFAULT_CRITERIA
    from app.api.v1.asset_studio_api._constants import VISION_REVIEW_CRITERIA

    for asset_type in ("image", "video"):
        adapter_names = set(VISION_DEFAULT_CRITERIA[asset_type])
        assert adapter_names == set(VISION_REVIEW_CRITERIA[asset_type]), asset_type
        missing = adapter_names - set(VISION_CRITERION_RUBRICS)
        assert not missing, f"{asset_type} 维度缺少扣分约束: {sorted(missing)}"


def test_video_review_prompt_sends_exposure_and_freeze_ceilings(tmp_path, monkeypatch) -> None:
    """硬约束必须真的落到发给上游的提示词里，而不是只写在常量表。"""
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-mp4-bytes")
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")

    result = _adapter("doubao-seed-2-1-lite").analyze_video(
        video_path=str(video_path), analysis_type="quality"
    )

    assert result.success is True
    text = next(part for part in recorder["messages"][0]["content"] if part.get("type") == "text")["text"]
    assert "不得因光影有氛围感而给高分" in text, "曝光维度约束缺失，偏暗素材会重新被评成高分"
    assert "冻结" in text and "慢动作" in text, "流畅度约束缺失或口径失衡：真冻结漏检、慢镜头误扣分都会重现"
