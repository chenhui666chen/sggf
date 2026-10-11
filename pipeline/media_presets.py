from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


DEFAULT_FRAME_RATIO = "16:9"
DEFAULT_IMAGE_RESOLUTION = "720p"
SUPPORTED_FRAME_RATIOS: Dict[str, Tuple[int, int]] = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
}

SUPPORTED_IMAGE_RESOLUTIONS = {"720p", "1080p"}
SUPPORTED_FRAME_SIZES: Dict[str, Dict[str, Tuple[int, int]]] = {
    "16:9": {
        "720p": (1280, 720),
        "1080p": (1920, 1080),
    },
    "9:16": {
        "720p": (720, 1280),
        "1080p": (1080, 1920),
    },
}

DEFAULT_VIDEO_FPS = 24
# 下面两个常量是 DreamWeaver 的"引擎模式标识"，决定提示词分支与是否走首帧桥接，
# 不是实际调用的模型 ID；实际模型由 DREAMWEAVER_WAN_MODEL_ID 与 video_config.adapter 决定。
# 字符串沿用历史模型名是因为它们已被写进项目配置与计费单价表的 key（user_center_task_billing），
# 改值等于改数据契约，收益为零。
DREAMWEAVER_I2V_ENGINE = "wan2.7-i2v"
DREAMWEAVER_T2V_ENGINE = "wan2.7-t2v"
DREAMWEAVER_AUTO_ENGINE = "wan_auto"
DREAMWEAVER_SLIDESHOW_ENGINE = "ffmpeg_slideshow"

# 万相线实际调用的模型。wan3.0-video 是 all-in-one，i2v/t2v 两种模式共用同一个模型 ID。
DREAMWEAVER_WAN_MODEL_ID = "wan3.0-video"
# all-in-one 模型无法从名字推断 i2v/t2v，统一交给 auto 引擎按是否有首帧关键帧决定
WAN_ALL_IN_ONE_MODEL_IDS = {DREAMWEAVER_WAN_MODEL_ID}

# 万相视频常见输出规格：
# - 分辨率：480P / 720P / 1080P（wan3.0 起支持 480P）
# - 时长：官方支持 [2, 30] 整数秒，与 adapters.dashscope.video_wan3.DURATION_MIN/MAX 同源
# - 输出：固定 30fps，MP4(H.264)
DREAMWEAVER_VIDEO_DURATION_MIN_S = 2.0
DREAMWEAVER_VIDEO_DURATION_MAX_S = 30.0
DREAMWEAVER_I2V_OUTPUT_FPS = 30


def normalize_dreamweaver_video_engine(value: Any, *, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = str(default or "").strip().lower()
    if not raw:
        return ""

    aliases = {
        "wan_i2v": DREAMWEAVER_I2V_ENGINE,
        "wan26_i2v": DREAMWEAVER_I2V_ENGINE,
        "wan27_i2v": DREAMWEAVER_I2V_ENGINE,
        "i2v": DREAMWEAVER_I2V_ENGINE,
        DREAMWEAVER_I2V_ENGINE: DREAMWEAVER_I2V_ENGINE,
        "wan_t2v": DREAMWEAVER_T2V_ENGINE,
        "wan26_t2v": DREAMWEAVER_T2V_ENGINE,
        "wan27_t2v": DREAMWEAVER_T2V_ENGINE,
        "t2v": DREAMWEAVER_T2V_ENGINE,
        DREAMWEAVER_T2V_ENGINE: DREAMWEAVER_T2V_ENGINE,
        "wan_auto": DREAMWEAVER_AUTO_ENGINE,
        "auto": DREAMWEAVER_AUTO_ENGINE,
        DREAMWEAVER_AUTO_ENGINE: DREAMWEAVER_AUTO_ENGINE,
        "slideshow": DREAMWEAVER_SLIDESHOW_ENGINE,
        DREAMWEAVER_SLIDESHOW_ENGINE: DREAMWEAVER_SLIDESHOW_ENGINE,
    }
    return aliases.get(raw, raw)


def infer_dreamweaver_video_engine_from_model_id(model_id: Any) -> str:
    if str(model_id or "").strip().lower() in WAN_ALL_IN_ONE_MODEL_IDS:
        return DREAMWEAVER_AUTO_ENGINE

    normalized = normalize_dreamweaver_video_engine(model_id)
    if normalized in {DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_T2V_ENGINE}:
        return normalized

    raw = str(model_id or "").strip().lower()
    if not raw:
        return ""
    if any(token in raw for token in ("i2v", "img2video", "image2video", "start-end2video", "start_end2video")):
        return DREAMWEAVER_I2V_ENGINE
    return DREAMWEAVER_T2V_ENGINE


def is_dreamweaver_i2v_engine(value: Any) -> bool:
    return normalize_dreamweaver_video_engine(value) == DREAMWEAVER_I2V_ENGINE


def is_dreamweaver_t2v_engine(value: Any) -> bool:
    return normalize_dreamweaver_video_engine(value) == DREAMWEAVER_T2V_ENGINE


def is_dreamweaver_auto_engine(value: Any) -> bool:
    return normalize_dreamweaver_video_engine(value) == DREAMWEAVER_AUTO_ENGINE


def is_dreamweaver_generated_video_engine(value: Any) -> bool:
    normalized = normalize_dreamweaver_video_engine(value)
    return normalized in {
        DREAMWEAVER_I2V_ENGINE,
        DREAMWEAVER_T2V_ENGINE,
        DREAMWEAVER_AUTO_ENGINE,
    }


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_dreamweaver_video_audio_output() -> bool:
    """决定 wan3.0-video 的 audio_output（模型是否输出自带音轨）。

    只有「音效交给模型生成」且「不额外合成对白轨」时才需要模型出声：
    其余情况下 DreamWeaver 会用 AudioSyncManager 整轨替换音频，模型自带声音会被丢弃，
    置 True 只会白花钱并与自有音效轨冲突。
    """
    if _env_flag("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", default=False):
        return False

    sfx_source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
    return sfx_source in {"model", "video"}


def normalize_frame_ratio(ratio: Optional[str], *, default: str = DEFAULT_FRAME_RATIO) -> str:
    raw_default = str(default or "").strip().replace("：", ":")
    if raw_default not in SUPPORTED_FRAME_RATIOS:
        raw_default = DEFAULT_FRAME_RATIO

    raw = str(ratio or "").strip()
    if not raw:
        return raw_default
    raw = raw.replace("：", ":")
    if raw in SUPPORTED_FRAME_RATIOS:
        return raw
    return raw_default


def normalize_image_resolution(value: Optional[str], *, default: str = DEFAULT_IMAGE_RESOLUTION) -> str:
    def _norm(raw: str) -> str:
        s = str(raw or "").strip().lower().replace(" ", "")
        if s in {"720", "720p"}:
            return "720p"
        if s in {"1080", "1080p", "fhd", "fullhd"}:
            return "1080p"
        return s

    raw_default = _norm(default)
    if raw_default not in SUPPORTED_IMAGE_RESOLUTIONS:
        raw_default = DEFAULT_IMAGE_RESOLUTION

    raw = _norm(value or "")
    if not raw:
        return raw_default
    if raw in SUPPORTED_IMAGE_RESOLUTIONS:
        return raw
    return raw_default


def normalize_video_fps(value: Any, *, default: int = DEFAULT_VIDEO_FPS) -> int:
    try:
        fps = int(value)
    except Exception:  # noqa: BLE001
        return int(default)
    if fps <= 0:
        return int(default)
    # 约束到常见帧率范围，避免误传导致模型/FFmpeg报错
    if fps > 60:
        return int(default)
    return int(fps)


def normalize_dreamweaver_video_duration_s(value: Any, *, default: float = 5.0) -> float:
    """
    将任意输入时长归一化为 wan3.0-video 官方支持的 [2, 30] 整数秒。

    - 区间内小数四舍五入（half-up），越界值夹取到边界，非正/非数字回落到 default。
    """
    try:
        duration = float(value)
    except Exception:  # noqa: BLE001
        duration = float(default)

    if duration <= 0:
        duration = float(default)

    seconds = int(duration + 0.5)
    seconds = int(min(max(seconds, DREAMWEAVER_VIDEO_DURATION_MIN_S), DREAMWEAVER_VIDEO_DURATION_MAX_S))
    return float(seconds)


def _env_duration_bound(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    if value <= 0:
        return float(default)
    return float(min(max(value, DREAMWEAVER_VIDEO_DURATION_MIN_S), DREAMWEAVER_VIDEO_DURATION_MAX_S))


def dreamweaver_beat_duration_bounds_s() -> Tuple[float, float]:
    """beat/镜头时长的规划区间：官方 [2, 30] 之内由 env 收窄，越界或非法值回落官方边界。

    提示词文案与分镜 clamp 共用这一处事实源，避免剧本按 2-15s 写 beat、分镜却规划 25s 容器。
    """
    low = _env_duration_bound("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", DREAMWEAVER_VIDEO_DURATION_MIN_S)
    high = _env_duration_bound("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", DREAMWEAVER_VIDEO_DURATION_MAX_S)
    return (low, high) if low <= high else (high, low)


def resolve_frame_size(image_config: Optional[Dict[str, Any]]) -> Tuple[int, int, str]:
    """
    从 image_config 推导 width/height/ratio。

    约定：
    - 支持 image_config.ratio（字符串，如 16:9 / 9:16）
    - 支持 image_config.resolution（字符串：720p / 1080p）
    - 若显式提供 image_config.width/height 且为正数，则优先使用
    """
    cfg = image_config if isinstance(image_config, dict) else {}
    ratio = normalize_frame_ratio(cfg.get("ratio") if isinstance(cfg.get("ratio"), str) else None)
    resolution = normalize_image_resolution(
        cfg.get("resolution") if isinstance(cfg.get("resolution"), str) else None,
    )

    width = cfg.get("width")
    height = cfg.get("height")
    try:
        width_int = int(width) if width is not None else 0
        height_int = int(height) if height is not None else 0
    except Exception:  # noqa: BLE001
        width_int = 0
        height_int = 0

    if width_int > 0 and height_int > 0:
        return width_int, height_int, ratio

    sizes = SUPPORTED_FRAME_SIZES.get(ratio) or SUPPORTED_FRAME_SIZES[DEFAULT_FRAME_RATIO]
    w, h = sizes.get(resolution) or sizes[DEFAULT_IMAGE_RESOLUTION]
    return int(w), int(h), ratio


def ensure_media_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    为 DreamWeaver payload 补齐 image_config.ratio / image_config.resolution 与 video_config.fps 的默认值。
    """
    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    _w, _h, ratio = resolve_frame_size(image_cfg)
    resolution = normalize_image_resolution(image_cfg.get("resolution") if isinstance(image_cfg.get("resolution"), str) else None)
    if not isinstance(image_cfg.get("ratio"), str) or not str(image_cfg.get("ratio") or "").strip():
        image_cfg["ratio"] = ratio
    else:
        image_cfg["ratio"] = normalize_frame_ratio(str(image_cfg.get("ratio")))
    if not isinstance(image_cfg.get("resolution"), str) or not str(image_cfg.get("resolution") or "").strip():
        image_cfg["resolution"] = resolution
    else:
        image_cfg["resolution"] = normalize_image_resolution(str(image_cfg.get("resolution")))
    payload["image_config"] = image_cfg

    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    video_cfg["fps"] = normalize_video_fps(video_cfg.get("fps"), default=DEFAULT_VIDEO_FPS)
    normalized_engine = normalize_dreamweaver_video_engine(video_cfg.get("engine"))
    if normalized_engine:
        video_cfg["engine"] = normalized_engine
    payload["video_config"] = video_cfg

    return payload
