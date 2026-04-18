from __future__ import annotations

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
DREAMWEAVER_I2V_ENGINE = "wan2.7-i2v"
DREAMWEAVER_T2V_ENGINE = "wan2.7-t2v"
DREAMWEAVER_AUTO_ENGINE = "wan_auto"
DREAMWEAVER_SLIDESHOW_ENGINE = "ffmpeg_slideshow"

# Wan 2.7 I2V（图生视频）常见输出规格：
# - 分辨率：720P / 1080P（由输入首帧与服务侧约束共同决定）
# - 时长：5s / 10s / 15s
# - 输出：固定 30fps，MP4(H.264)
DREAMWEAVER_VIDEO_SUPPORTED_DURATIONS_S = (5.0, 10.0, 15.0)
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
    将任意输入时长归一化为 Wan I2V 支持的离散集合（5/10/15 秒）。
    """
    try:
        duration = float(value)
    except Exception:  # noqa: BLE001
        duration = float(default)

    if duration <= 0:
        duration = float(default)

    candidates = DREAMWEAVER_VIDEO_SUPPORTED_DURATIONS_S
    picked = min(candidates, key=lambda x: abs(x - duration))
    return float(picked)


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
