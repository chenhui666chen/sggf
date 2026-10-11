from __future__ import annotations

import logging
from collections import Counter
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """统一任务类型枚举。"""

    CONCEPT_WORLD = "concept_world"
    CONCEPT_CHARACTER = "concept_character"
    CONCEPT_STORY = "concept_story"
    STRUCTURE_PLOT = "structure_plot"
    STRUCTURE_EVENTS = "structure_events"
    CONTENT_DRAFT = "content_draft"
    CONTENT_STYLE = "content_style"
    REVIEW_CHECK = "review_check"
    ITERATION_OPTIMIZE = "iteration_optimize"
    REWRITE = "rewrite"
    BOOK_ANALYSIS = "book_analysis"
    BOOK_SYNTHESIS = "book_synthesis"
    AUDIOBOOK_DIRECTOR = "audiobook_director"
    AUDIOBOOK_SCRIPT = "audiobook_script"
    AUDIOBOOK_VOICE = "audiobook_voice"
    AUDIOBOOK_SOUND = "audiobook_sound"
    AUDIOBOOK_MUSIC = "audiobook_music"
    AUDIOBOOK_REVIEW = "audiobook_review"
    ASSET_MUSIC = "asset_music"
    ASSET_SFX = "asset_sfx"
    ASSET_AUDIO = "asset_audio"


TASK_TYPE_ALIASES = {
    "default": "chapter",
    "concept_world": "concept",
    "concept_character": "character",
    "concept_story": "concept",
    "outline": "outline_expand",
    "content_draft": "chapter",
    "content_style": "dialogue",
    "review_check": "review",
    "iteration_optimize": "rewrite",
    "ai_trace": "rewrite",
    "book_analysis": "entity_extract",
    "book_synthesis": "book_synthesis",
    "chapter_summary": "summarize",
}

# 这里只剩「同一模型的不同拼写形态」归一（下划线/短横线、前端短名、上游全名与内部名不一致）。
# 退役与改名产生的旧 ID 别名已于 2026-10-09 随数据库历史改写一并删除：
# 调用方拿到旧 ID 应当直接失败并被发现，而不是被静默改写成一个它没选过的模型。
MODEL_ALIASES = {
    "qwen3_vl_plus": "qwen3-vl-plus",
    "cosyvoice-v3-plus": "cosyvoice-v3.5-plus",
    "cosyvoice_v3_plus": "cosyvoice-v3.5-plus",
    "qwen_image_edit_plus": "qwen-image-edit-plus",
    "qwen_image_edit_max": "qwen-image-edit-max",
    "qwen_multiperson_fusion": "qwen-image-edit-plus",
    "wan_image_edit": "qwen-image-edit-plus",
    # Kling V3 注册中心用斜杠全名，历史配置与早期档案用无斜杠短名（同一模型的不同拼写）
    "kling-v3-image-generation": "kling/kling-v3-image-generation",
    "kling-v3-omni-image-generation": "kling/kling-v3-omni-image-generation",
    "kling-v3-video-generation": "kling/kling-v3-video-generation",
    "kling-v3-omni-video-generation": "kling/kling-v3-omni-video-generation",
    # MiniMax TTS 模型别名（前端使用短横线格式，注册中心使用斜杠格式）
    "minimax-speech-2.8-turbo": "MiniMax/speech-2.8-turbo",
    "minimax-speech-2.8-hd": "MiniMax/speech-2.8-hd",
    "minimax/speech-2.8-turbo": "MiniMax/speech-2.8-turbo",
    "minimax/speech-2.8-hd": "MiniMax/speech-2.8-hd",
}


_ALIAS_HITS: Counter = Counter()


def get_alias_hit_stats() -> Dict[str, int]:
    """返回「旧 ID → 命中次数」，作为退役门槛的取证依据。

    计数是进程内的，重启即清零；多 worker 场景需按进程分别取证。
    """
    return dict(_ALIAS_HITS)


def reset_alias_hit_stats() -> None:
    _ALIAS_HITS.clear()


def _coerce_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    raw = value.value if hasattr(value, "value") else value
    text = str(raw).strip()
    if not text:
        return None
    return text


def normalize_task_type(task_type: Any) -> Optional[str]:
    """将历史任务类型和值对象统一映射到当前中心可识别的任务名。"""

    text = _coerce_value(task_type)
    if text is None:
        return None

    normalized = text.strip().lower().replace("-", "_")
    return TASK_TYPE_ALIASES.get(normalized, normalized)


def normalize_model_id(model_id: Any) -> Optional[str]:
    """将历史模型别名统一映射到当前注册中心中的模型 ID。"""

    text = _coerce_value(model_id)
    if text is None:
        return None

    normalized = text.strip().lower()
    target = MODEL_ALIASES.get(normalized)
    if target is None:
        return normalized

    # 每个旧 ID 只记一条日志，避免热路径刷屏，同时保留"仍有调用方在用旧名"的证据
    if _ALIAS_HITS[normalized] == 0:
        logger.info("模型别名命中: %s -> %s", normalized, target)
    _ALIAS_HITS[normalized] += 1
    return target


# 强制思考模型：上游只接受开启思考，收到任何关思考写法都直接 400。
# 这一集合是"能不能关思考"的唯一事实源，模型换代时必须重新实测。
_FORCED_THINKING_MODEL_IDS = frozenset({"glm"})


def build_thinking_disabled_extra_body(model_id: Optional[str] = None) -> Dict[str, Any]:
    """构造指定模型的"关闭思考" extra_body，按模型族分发互斥参数。

    各 API 厂商的关思考参数互不兼容，不能一股脑全传：
    - 火山 doubao 系：同时收到 reasoning_effort 与 thinking 会报 400
      （InvalidParameter: Invalid combination of reasoning_effort and thinking
      type: low + disabled，2026-08-23 九模型并行验证实测），只传 thinking
    - StepFun 系：认 reasoning_effort（项目 Hard Constraints 要求 low）
    - 强制思考系（glm）：任何关思考写法都 400，只能返回空 extra_body
      （2026-10-09 实测：enable_thinking=false 与 thinking={"type":"disabled"}
      都返回 InternalError.Algo.InvalidParameter: The value of the enable_thinking
      parameter is restricted to True.）
    - 其余（阿里百炼 qwen/kimi、deepseek/minimax/mimo 及未指定模型）：
      thinking + enable_thinking 并存，各 API 取自己认的那一个
    """
    mid = (model_id or "").strip().lower()
    if mid in _FORCED_THINKING_MODEL_IDS:
        return {}
    if mid.startswith("doubao"):
        return {"thinking": {"type": "disabled"}}
    if mid.startswith("step"):
        return {"thinking": {"type": "disabled"}, "reasoning_effort": "low"}
    return {"thinking": {"type": "disabled"}, "enable_thinking": False}


def pick_resolution_label(width: int, height: int) -> str:
    """按短边归一到上游分辨率档（≤480→480P、≤720→720P、否则 1080P）。

    运行时下发 parameters["resolution"] 与积分取价共用本函数，两侧错档才不会漏收。
    """
    short_edge = min(int(width or 0), int(height or 0))
    if short_edge <= 480:
        return "480P"
    if short_edge <= 720:
        return "720P"
    return "1080P"
