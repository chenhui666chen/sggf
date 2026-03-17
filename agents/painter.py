from __future__ import annotations

import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
import difflib
import json
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from adapters.adapter_helpers import (
    SimpleGenerationResult as GenerationResult,
    chat_messages,
    edit_image,
    generate_image,
    get_model_info,
    match_scene as match_scene_with_model,
    model_supports_capability,
)
from agents.best_image_selector import select_best_candidate as _select_best_candidate
from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_parent_map, build_camera_tree
from agents.reference_image_selector import (
    merge_reference_images as _merge_reference_images,
    selected_ref_images_from_pick as _selected_ref_images_from_pick,
    vlm_prefilter_reference_images_text_only as _vlm_prefilter_reference_images_text_only,
    vlm_build_edit_prompt_from_base_and_refs as _vlm_build_edit_prompt_from_base_and_refs,
    vlm_rewrite_t2i_prompt_from_references as _vlm_rewrite_t2i_prompt_from_references,
)
from agents.prompt_fragments import (
    apply_prompt_fragment as _apply_prompt_fragment,
    build_reference_pack as _build_reference_pack,
    library_assets_from_payload as _library_assets_from_payload,
    match_library_assets_for_shot as _match_library_assets_for_shot,
)
from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)
from pipeline.media_presets import (
    WAN_I2V_OUTPUT_FPS,
    ensure_media_payload,
    normalize_frame_ratio,
    normalize_wan_i2v_duration_s,
    resolve_frame_size,
)
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.style_presets import ensure_style_payload

_PNG_PLACEHOLDER_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGO4o6YGAAMKASng8MlTAAAAAElFTkSuQmCC"
)


def _ensure_run_dir(ctx: Any) -> Path:
    base = Path("runs") / ctx.run_id
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_telemetry_counters(payload: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = payload.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = {}
        payload["telemetry"] = telemetry
    counters = telemetry.get("counters")
    if not isinstance(counters, dict):
        counters = {}
        telemetry["counters"] = counters
    return counters


def _bump_telemetry_counter(payload: Dict[str, Any], name: str, delta: int = 1) -> None:
    if not name:
        return
    counters = _ensure_telemetry_counters(payload)
    counters[name] = int(counters.get(name) or 0) + int(delta)


def _semantic_index_items_from_frames(
    *,
    frames: List[Dict[str, Any]],
    run_id: str,
    max_items: int = 400,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not isinstance(frames, list) or not frames:
        return items

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        path = frame.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        img_path = Path(path)
        if not img_path.exists():
            continue

        meta = frame.get("meta") if isinstance(frame.get("meta"), dict) else {}
        spec = frame.get("spec") if isinstance(frame.get("spec"), dict) else {}

        frame_role = str(meta.get("role") or "").strip()
        shot_id = ""
        stem = img_path.stem
        if frame_role and stem.endswith(f"_{frame_role}"):
            shot_id = stem[: -len(f"_{frame_role}")]
        else:
            for suffix in ("_head", "_tail", "_mid"):
                if stem.endswith(suffix):
                    shot_id = stem[: -len(suffix)]
                    if not frame_role:
                        frame_role = suffix[1:]
                    break

        prompt = ""
        ref_meta = meta.get("ref") if isinstance(meta.get("ref"), dict) else {}
        rewrite = ref_meta.get("rewrite") if isinstance(ref_meta.get("rewrite"), dict) else {}
        if isinstance(rewrite.get("prompt"), str) and str(rewrite.get("prompt") or "").strip():
            prompt = str(rewrite.get("prompt") or "").strip()
        if not prompt:
            prompt = str(spec.get("prompt") or "").strip()
        if not prompt:
            continue

        via = str(meta.get("via") or "").strip()
        if not via:
            decision = meta.get("decision") if isinstance(meta.get("decision"), dict) else {}
            if isinstance(decision, dict):
                via = str(decision.get("mode") or "").strip()

        items.append(
            {
                "kind": "frame",
                "path": img_path,
                "text": prompt,
                "meta": {
                    "run_id": str(run_id),
                    "shot_id": shot_id,
                    "frame_role": frame_role,
                    "via": via,
                },
            }
        )
        if len(items) >= max(1, int(max_items)):
            break
    return items


def _write_image_from_generation_result(result: GenerationResult, out_path: Path) -> None:
    if not result.success:
        raise RuntimeError(result.error or "WAN T2I generate failed")
    data = result.data
    if isinstance(data, dict):
        url = data.get("image_url") or data.get("url")
        if isinstance(url, str) and url:
            _download_url_to_path(url, out_path, timeout_s=120.0, max_retries=2)
            return

        b64 = data.get("b64_json") or data.get("base64") or data.get("image_base64")
        if isinstance(b64, str) and b64:
            out_path.write_bytes(base64.b64decode(b64))
            return

    raise RuntimeError("WAN T2I response unsupported: missing image_url/base64 payload")


def _write_video_from_generation_result(result: GenerationResult, out_path: Path) -> None:
    if not result.success:
        raise RuntimeError(result.error or "WAN I2V generate failed")
    data = result.data
    if isinstance(data, dict):
        url = data.get("video_url") or data.get("url")
        if isinstance(url, str) and url:
            _download_url_to_path(url, out_path, timeout_s=300.0, max_retries=2)
            return

        b64 = data.get("b64_json") or data.get("base64") or data.get("video_base64")
        if isinstance(b64, str) and b64:
            out_path.write_bytes(base64.b64decode(b64))
            return

    raise RuntimeError("WAN I2V response unsupported: missing video_url/base64 payload")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _normalize_safety_strategy(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"off", "none", "disable", "false", "0"}:
        return ""
    if value in {"conservative", "moderate", "aggressive"}:
        return value
    return "moderate"


def _sanitize_prompt_for_safety(prompt: str) -> Tuple[str, Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "strategy": "off",
        "issues": 0,
        "changed": False,
    }
    if not isinstance(prompt, str) or not prompt.strip():
        return prompt, meta

    strategy = _normalize_safety_strategy(os.getenv("DREAMWEAVER_SAFETY_STRATEGY", "moderate"))
    if not strategy:
        return prompt, meta

    from adapters.content_safety_checker import check_and_fix_prompt

    fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy=strategy)
    meta["strategy"] = strategy
    if issues:
        meta["issues"] = len(issues)
        meta["fix_description"] = fix_description
        if fixed_prompt != prompt:
            meta["changed"] = True
            print(f"⚠️ [内容安全] T2I 提示词已自动修复: {fix_description}")
            return fixed_prompt, meta
    return prompt, meta


def _is_safety_block_error(error: str) -> bool:
    text = (error or "").lower()
    return "datainspectionfailed" in text or "inappropriate content" in text or "content check failed" in text


def _write_png_placeholder(
    out_path: Path,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    label: str = "安全拦截 / 可重试",
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w = int(width or 0)
    h = int(height or 0)
    if w <= 0:
        w = 1024
    if h <= 0:
        h = 576

    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        bg = (252, 232, 232)
        fg = (176, 0, 0)
        border = (224, 120, 120)
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w - 1, h - 1], outline=border, width=2)

        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyh.ttf",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        font_size = max(16, min(w, h) // 18)
        font = None
        for path in font_paths:
            try:
                if Path(path).exists():
                    font = ImageFont.truetype(path, font_size)
                    break
            except Exception:  # noqa: BLE001
                continue
        if font is None:
            font = ImageFont.load_default()

        text_lines = [label.strip(), "Safety blocked / Retry"]
        line_heights: List[int] = []
        line_widths: List[int] = []
        for text in text_lines:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                line_widths.append(bbox[2] - bbox[0])
                line_heights.append(bbox[3] - bbox[1])
            except Exception:  # noqa: BLE001
                size = draw.textsize(text, font=font)
                line_widths.append(size[0])
                line_heights.append(size[1])

        spacing = max(6, int(font_size * 0.4))
        total_height = sum(line_heights) + spacing * (len(text_lines) - 1)
        y = max(12, (h - total_height) // 2)

        for idx, text in enumerate(text_lines):
            line_w = line_widths[idx]
            x = max(12, (w - line_w) // 2)
            draw.text((x, y), text, fill=fg, font=font)
            y += line_heights[idx] + spacing

        img.save(out_path, format="PNG")
        return
    except Exception:  # noqa: BLE001
        out_path.write_bytes(base64.b64decode(_PNG_PLACEHOLDER_B64))


def _cfg_flag(cfg: Dict[str, Any], key: str, *, env_name: str, default: bool) -> bool:
    if isinstance(cfg, dict) and key in cfg:
        val = cfg.get(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "y", "on"}
    return _env_flag(env_name, default)


def _cfg_int(cfg: Dict[str, Any], key: str, *, env_name: str, default: int) -> int:
    if isinstance(cfg, dict) and key in cfg:
        val = cfg.get(key)
        try:
            return int(val)
        except Exception:  # noqa: BLE001
            return default
    return _env_int(env_name, default)


def _cfg_float(cfg: Dict[str, Any], key: str, *, env_name: str, default: float) -> float:
    if isinstance(cfg, dict) and key in cfg:
        val = cfg.get(key)
        try:
            return float(val)
        except Exception:  # noqa: BLE001
            return default
    return _env_float(env_name, default)


def _cfg_str(cfg: Dict[str, Any], key: str, *, env_name: str, default: str) -> str:
    if isinstance(cfg, dict) and key in cfg:
        val = cfg.get(key)
        return str(val) if val is not None else default

    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return default
    return raw


def _clone_adapter_instance(adapter: Any) -> Optional[Any]:
    if isinstance(adapter, str):
        return adapter
    cfg = getattr(adapter, "config", None)
    if cfg is None:
        return None
    try:
        return adapter.__class__(cfg)
    except Exception:  # noqa: BLE001
        return None


def _close_adapter_session(adapter: Any) -> None:
    session = getattr(adapter, "session", None)
    try:
        if session is not None:
            session.close()
    except Exception:  # noqa: BLE001
        pass


def _model_client_available(model_id: Any) -> bool:
    if model_id is None:
        return False
    if not isinstance(model_id, str):
        return True
    return isinstance(get_model_info(model_id), dict)


def _supports_multi_image_client(adapter: Any) -> bool:
    if adapter is None:
        return False
    if isinstance(adapter, str):
        return model_supports_capability(adapter, "multi_image")
    return bool(getattr(adapter, "supports_multi_image", False))


def _generate_t2i_result(
    *,
    adapter: Any,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
) -> GenerationResult:
    if isinstance(adapter, str):
        return generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            model_id=adapter,
        )
    return adapter.generate(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        seed=seed,
    )


def _generate_edit_result(
    *,
    adapter: Any,
    image_path: Path,
    edit_prompt: str,
    strength: float,
    guidance_scale: float,
    seed: int,
    reference_images: Optional[List[str]] = None,
) -> GenerationResult:
    if isinstance(adapter, str):
        return edit_image(
            image_path=str(image_path),
            edit_prompt=edit_prompt,
            strength=strength,
            reference_images=reference_images,
            model_id=adapter,
            seed=seed,
            guidance_scale=guidance_scale,
        )

    kwargs: Dict[str, Any] = {
        "image_path": str(image_path),
        "edit_prompt": edit_prompt,
        "strength": strength,
        "guidance_scale": guidance_scale,
        "seed": seed,
    }
    if reference_images:
        kwargs["image_paths"] = reference_images
    return adapter.generate(**kwargs)


def _generate_candidates(
    *,
    candidate_count: int,
    parallelism: int,
    generate_one: Callable[[int], Path],
) -> List[Path]:
    if candidate_count <= 0:
        return []

    workers = 1
    try:
        workers = int(parallelism)
    except Exception:  # noqa: BLE001
        workers = 1
    workers = max(1, min(workers, candidate_count))

    if workers <= 1 or candidate_count == 1:
        return [generate_one(idx) for idx in range(candidate_count)]

    paths: List[Optional[Path]] = [None] * candidate_count
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(generate_one, idx): idx for idx in range(candidate_count)}
        for fut in as_completed(futures):
            idx = futures[fut]
            paths[idx] = fut.result()
    return [p for p in paths if p is not None]


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        text = str(item).strip()
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= 16:
            break
    return out


def _spec_prompt(spec: Optional[Dict[str, Any]]) -> str:
    if not isinstance(spec, dict):
        return ""
    raw = spec.get("prompt")
    return str(raw).strip() if isinstance(raw, str) else ""


def _normalize_prompt_for_similarity(text: str) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    return "".join(ch for ch in s if ch.isalnum())


def _prompt_similarity(a: str, b: str) -> Optional[float]:
    na = _normalize_prompt_for_similarity(a)
    nb = _normalize_prompt_for_similarity(b)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0
    return float(difflib.SequenceMatcher(None, na, nb).ratio())


def _frame_ratio(spec: Optional[Dict[str, Any]], *, default: str) -> str:
    if isinstance(spec, dict):
        raw = spec.get("ratio")
        if isinstance(raw, str) and raw.strip():
            return normalize_frame_ratio(raw.strip(), default=default)
    return normalize_frame_ratio(default, default=default)


def _subject_pos(spec: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    if not isinstance(spec, dict):
        return None
    raw = spec.get("subject_pos")
    if not isinstance(raw, dict):
        return None
    x = raw.get("x")
    y = raw.get("y")
    try:
        fx = float(x)
        fy = float(y)
    except Exception:  # noqa: BLE001
        return None
    if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
        return None
    return fx, fy


def _subject_pos_delta(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> Optional[float]:
    if a is None or b is None:
        return None
    dx = abs(float(a[0]) - float(b[0]))
    dy = abs(float(a[1]) - float(b[1]))
    return float(max(dx, dy))


def _decide_image_mode(
    *,
    policy: str,
    base_image_path: Optional[Path],
    base_spec: Optional[Dict[str, Any]],
    target_spec: Optional[Dict[str, Any]],
    base_visible_chars: Optional[List[str]] = None,
    target_visible_chars: Optional[List[str]] = None,
    max_subject_pos_delta: float = 0.1,
    min_prompt_similarity: float = 0.0,
    default_ratio: str = "16:9",
) -> Dict[str, Any]:
    """
    决策是否用“图像编辑”基于已有图做编辑，还是“文生图”从头生成。
    - policy: auto/always/never
    - 返回：{"mode": "image_edit"|"t2i", "reason": "..."}
    """
    p = str(policy or "always").strip().lower()
    if p in {"never", "off", "false", "0"}:
        return {"mode": "t2i", "reason": "策略=never"}

    if base_image_path is None or not isinstance(base_image_path, Path) or not base_image_path.exists():
        return {"mode": "t2i", "reason": "无基准图"}

    if p in {"always", "on", "true", "1"}:
        return {"mode": "image_edit", "reason": "策略=always"}

    # auto 策略：先排除“编辑大概率失败/不合适”的情况
    base_ratio = _frame_ratio(base_spec, default=default_ratio)
    target_ratio = _frame_ratio(target_spec, default=default_ratio)
    if base_ratio and target_ratio and base_ratio != target_ratio:
        return {"mode": "t2i", "reason": "画幅不一致"}

    base_chars = set(_as_str_list(base_visible_chars))
    target_chars = set(_as_str_list(target_visible_chars))
    if base_chars and target_chars and base_chars.isdisjoint(target_chars):
        return {"mode": "t2i", "reason": "人物集合变化"}

    threshold = float(max_subject_pos_delta or 0.0)
    if threshold > 0:
        delta = _subject_pos_delta(_subject_pos(base_spec), _subject_pos(target_spec))
        if delta is not None and delta > threshold:
            return {"mode": "t2i", "reason": "主体位置跳变"}

    prompt_threshold = float(min_prompt_similarity or 0.0)
    similarity_meta: Dict[str, Any] = {}
    if prompt_threshold > 0:
        sim = _prompt_similarity(_spec_prompt(base_spec), _spec_prompt(target_spec))
        if sim is not None and sim < prompt_threshold:
            return {
                "mode": "t2i",
                "reason": "提示词差异过大",
                "prompt_similarity": sim,
                "prompt_similarity_threshold": prompt_threshold,
            }
        if sim is not None:
            similarity_meta = {
                "prompt_similarity": sim,
                "prompt_similarity_threshold": prompt_threshold,
            }

    return {"mode": "image_edit", "reason": "自动：优先连续编辑", **similarity_meta}


def _stable_seed(*parts: str) -> int:
    payload = "|".join(parts).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % 2147483647


def _derive_seed(*, base_seed: Any, ctx: Any, shot_id: str, role: str, idx: int) -> int:
    if isinstance(base_seed, int):
        return int(base_seed) + int(idx)
    return _stable_seed(str(getattr(ctx, "run_id", "")), shot_id, role, str(idx))


def _hash_cache_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    raw = str(os.getenv("DREAMWEAVER_HASH_CACHE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _hash_cache_dir() -> Path:
    raw = str(os.getenv("DREAMWEAVER_HASH_CACHE_DIR") or "runs/_hash_cache/images").strip()
    base = Path(raw) if raw else Path("runs") / "_hash_cache" / "images"
    if not base.is_absolute():
        base = Path.cwd() / base
    base.mkdir(parents=True, exist_ok=True)
    return base


def _adapter_fingerprint(adapter: Any) -> Dict[str, Any]:
    if isinstance(adapter, str):
        info = get_model_info(adapter) if isinstance(adapter, str) else None
        return {
            "model_id": str((info or {}).get("id") or adapter),
            "provider": (info or {}).get("provider"),
        }
    cfg = getattr(adapter, "config", None)
    return {
        "class": adapter.__class__.__name__,
        "model_name": getattr(cfg, "model_name", None),
        "base_url": getattr(cfg, "base_url", None),
    }


def _hash_cache_key(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _try_restore_from_hash_cache(*, key: str, out_path: Path) -> bool:
    cache_path = _hash_cache_dir() / f"{key}.png"
    if not cache_path.exists():
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(cache_path.read_bytes())
    return True


def _save_to_hash_cache(*, key: str, src_path: Path) -> None:
    if not src_path.exists():
        return
    cache_path = _hash_cache_dir() / f"{key}.png"
    if cache_path.exists():
        return
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    try:
        tmp.write_bytes(src_path.read_bytes())
        try:
            tmp.replace(cache_path)
        except Exception:  # noqa: BLE001
            if cache_path.exists():
                return
            raise
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:  # noqa: BLE001
            pass


def _extract_score(obj: Any) -> Optional[float]:
    if isinstance(obj, (int, float)):
        return float(obj)
    if not isinstance(obj, dict):
        return None

    for key in ("overall", "overall_score", "score", "quality", "quality_score"):
        val = obj.get(key)
        if isinstance(val, (int, float)):
            return float(val)

    scores = obj.get("scores")
    if isinstance(scores, dict):
        for key in ("overall", "score", "quality"):
            val = scores.get(key)
            if isinstance(val, (int, float)):
                return float(val)

    return None


def _mime_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _file_to_data_url(path: Path) -> str:
    mime = _mime_from_path(path)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _try_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _vlm_chat_json(
    *,
    vlm_adapter: Any,
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 400,
) -> Optional[Dict[str, Any]]:
    if vlm_adapter is None:
        return None

    try:
        if isinstance(vlm_adapter, str):
            result = chat_messages(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                model_id=vlm_adapter,
            )
            if not getattr(result, "success", False):
                result = chat_messages(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model_id=vlm_adapter,
                )
        else:
            if not hasattr(vlm_adapter, "chat"):
                return None
            result = vlm_adapter.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            if not getattr(result, "success", False):
                result = vlm_adapter.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
        if not getattr(result, "success", False):
            return None
        content = ""
        if isinstance(result.data, dict) and isinstance(result.data.get("content"), str):
            content = result.data["content"]
        return _try_parse_json_object(content)
    except Exception:  # noqa: BLE001
        return None


def _vlm_select_best_candidate_semantic(
    *,
    vlm_adapter: Any,
    target_description: str,
    candidate_paths: List[Path],
    reference_images: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not target_description or not candidate_paths:
        return None

    system_prompt = (
        "你是专业的视觉评估专家。\n"
        "任务：基于【参考图】（若有）与【目标描述】，在多张候选图中选择最优的一张。\n"
        "评估维度（按优先级）：\n"
        "1) 角色一致性：性别/年龄/脸型五官/发型/服装/体态是否与参考图一致（若有多角色，需分别一致）。\n"
        "2) 空间一致性：人物相对位置左右/远近、透视、构图关系是否符合参考图与目标描述。\n"
        "3) 描述准确性：动作、场景、道具、光照、氛围、风格是否命中目标描述的关键点。\n"
        "硬约束：尽量避免白边/黑边/额外边框/明显水印。\n"
        "输出：只输出 JSON（不要 Markdown），字段：best_image_index(int)、reason(string)、scores(object,可选)、issues(list,可选)。"
    )

    content: List[Dict[str, Any]] = []
    if reference_images:
        for idx, ref in enumerate(reference_images):
            path = ref.get("path")
            desc = str(ref.get("desc") or "").strip()
            if not isinstance(path, Path) or not path.exists():
                continue
            content.append({"type": "text", "text": f"参考图 {idx}: {desc}"})
            content.append({"type": "image_url", "image_url": {"url": _file_to_data_url(path)}})

    for idx, path in enumerate(candidate_paths):
        content.append({"type": "text", "text": f"候选图 {idx}"})
        content.append({"type": "image_url", "image_url": {"url": _file_to_data_url(path)}})

    content.append(
        {
            "type": "text",
            "text": (
                f"【目标描述】\n{target_description}\n\n"
                "仅输出 JSON 示例："
                "{\"best_image_index\":0,\"reason\":\"...\",\"scores\":"
                "{\"character_consistency\":0.8,\"spatial_consistency\":0.7,\"description_accuracy\":0.9,\"overall\":0.82},"
                "\"issues\":[\"...\"]}"
            ),
        }
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    obj = _vlm_chat_json(vlm_adapter=vlm_adapter, messages=messages, temperature=0.2, max_tokens=700)
    if not isinstance(obj, dict):
        return None

    best_idx = obj.get("best_image_index")
    reason = obj.get("reason")
    if not isinstance(best_idx, int) or best_idx < 0 or best_idx >= len(candidate_paths):
        return None

    scores = obj.get("scores") if isinstance(obj.get("scores"), dict) else None
    issues = obj.get("issues") if isinstance(obj.get("issues"), list) else None
    issues_list = [str(i) for i in issues if isinstance(i, (str, int))][:8] if issues else []
    return {
        "best_index": best_idx,
        "reason": str(reason or "").strip(),
        "scores": scores or {},
        "issues": issues_list,
    }


def _clamp_prompt_text(text: str, limit: int = 900) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip()


def _is_qwen_image_edit_adapter_name(name: str) -> bool:
    raw = str(name or "").strip().lower()
    if not raw:
        return False
    return (
        raw.startswith("qwen_image_edit")
        or raw.startswith("wan_image_edit")
        or "qwen-image-edit" in raw
        or "qwenimageedit" in raw
    )


def _is_qwen_image_edit_adapter(adapter: Any) -> bool:
    if adapter is None:
        return False
    if isinstance(adapter, str):
        return _is_qwen_image_edit_adapter_name(adapter)
    cfg = getattr(adapter, "config", None)
    model_name = str(getattr(cfg, "model_name", "") or "").strip().lower()
    if _is_qwen_image_edit_adapter_name(model_name):
        return True
    class_name = adapter.__class__.__name__.lower()
    return "qwenimageedit" in class_name or "wanimageedit" in class_name


def _apply_image_edit_prompt_constraints(*, prompt: str, adapter: Any, ref_count: int) -> str:
    cleaned = str(prompt or "").strip()
    if not cleaned:
        return ""
    if ref_count > 0 and "image 1" not in cleaned.lower():
        ref_hint = "Image 2"
        if ref_count >= 2:
            ref_hint = "Image 2、Image 3"
        prefix = f"以 Image 1 为基准，参考 {ref_hint} 保持主体一致。"
        cleaned = f"{prefix}\n{cleaned}"
    limit = 800 if _is_qwen_image_edit_adapter(adapter) else 900
    return _clamp_prompt_text(cleaned, limit=limit)


def _finalize_candidates(
    *,
    candidate_paths: List[Path],
    output_path: Path,
    best_index: int,
    keep_candidates: bool,
) -> None:
    selected = candidate_paths[best_index]
    if output_path.exists():
        output_path.unlink()
    if keep_candidates:
        output_path.write_bytes(selected.read_bytes())
        return

    selected.replace(output_path)
    for idx, path in enumerate(candidate_paths):
        if idx == best_index:
            continue
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            pass


def _generate_t2i_with_candidates(
    *,
    adapter: Any,
    prompt: str,
    negative_prompt: str = "",
    width: int,
    height: int,
    base_seed: Any,
    ctx: Any,
    shot_id: str,
    role: str,
    output_path: Path,
    candidate_count: int,
    parallelism: int = 1,
    selector: str,
    vlm_adapter: Any,
    vlm_criteria: List[str],
    reference_images: Optional[List[Dict[str, Any]]] = None,
    keep_candidates: bool,
    enable_hash_cache: Optional[bool] = None,
    bypass_hash_cache: bool = False,
) -> Dict[str, Any]:
    cache_enabled = _hash_cache_enabled(enable_hash_cache) and not bool(bypass_hash_cache)
    payload = ctx.payload if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict) else None
    raw_prompt = prompt
    prompt, safety_meta = _sanitize_prompt_for_safety(prompt)
    aggressive_prompt: Optional[str] = None
    if _env_flag("DREAMWEAVER_SAFETY_AGGRESSIVE_FALLBACK", True):
        try:
            from adapters.content_safety_checker import check_and_fix_prompt
            aggressive_prompt, _, _ = check_and_fix_prompt(raw_prompt, strategy="aggressive")
            if not aggressive_prompt or aggressive_prompt == prompt:
                aggressive_prompt = None
        except Exception:  # noqa: BLE001
            aggressive_prompt = None
    if payload is not None and safety_meta.get("issues"):
        _bump_telemetry_counter(payload, "t2i_safety_fixes", 1)
    if candidate_count <= 1:
        seed_value = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=0)
        cache_key = None
        if cache_enabled:
            cache_key = _hash_cache_key(
                {
                    "kind": "t2i",
                    "adapter": _adapter_fingerprint(adapter),
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": int(width),
                    "height": int(height),
                    "seed": int(seed_value),
                }
            )
            if _try_restore_from_hash_cache(key=cache_key, out_path=output_path):
                if payload is not None:
                    _bump_telemetry_counter(payload, "t2i_cache_hits", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "single",
                    "seed": seed_value,
                    "cache_hit": True,
                    "cache_key": cache_key,
                }
            if payload is not None:
                _bump_telemetry_counter(payload, "t2i_cache_misses", 1)

        if payload is not None:
            _bump_telemetry_counter(payload, "t2i_generate_calls", 1)
        used_fallback = False
        try:
            try:
                result = _generate_t2i_result(
                    adapter=adapter,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    seed=seed_value,
                )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text) and aggressive_prompt:
                    result = _generate_t2i_result(
                        adapter=adapter,
                        prompt=aggressive_prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        seed=seed_value,
                    )
                    used_fallback = True
                    if payload is not None:
                        _bump_telemetry_counter(payload, "t2i_safety_retries", 1)
                else:
                    raise
            _write_image_from_generation_result(result, output_path)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if _is_safety_block_error(error_text):
                _write_png_placeholder(output_path, width=width, height=height)
                if payload is not None:
                    _bump_telemetry_counter(payload, "t2i_safety_blocked", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "safety_placeholder",
                    "seed": seed_value,
                    "cache_hit": False if cache_enabled else None,
                    "cache_key": cache_key,
                    "safety_blocked": True,
                    "safety_error": error_text,
                }
            raise
        if used_fallback:
            cache_key = None
        if cache_enabled and cache_key:
            _save_to_hash_cache(key=cache_key, src_path=output_path)
        return {
            "candidate_count": 1,
            "selected": 0,
            "selector": "single",
            "seed": seed_value,
            "cache_hit": False if cache_enabled else None,
            "cache_key": cache_key,
        }
    cand_dir = output_path.parent / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    cache_hits = 0
    if cache_enabled:
        try:
            cache_dir = _hash_cache_dir()
            for idx in range(int(candidate_count)):
                seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
                key = _hash_cache_key(
                    {
                        "kind": "t2i",
                        "adapter": _adapter_fingerprint(adapter),
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "width": int(width),
                        "height": int(height),
                        "seed": int(seed),
                    }
                )
                if (cache_dir / f"{key}.png").exists():
                    cache_hits += 1
        except Exception:  # noqa: BLE001
            cache_hits = 0

    workers = 1
    try:
        workers = int(parallelism)
    except Exception:  # noqa: BLE001
        workers = 1
    workers = max(1, min(workers, candidate_count))
    if workers > 1:
        probe = _clone_adapter_instance(adapter)
        if probe is None:
            workers = 1
        else:
            _close_adapter_session(probe)

    safety_blocked_any = False
    safety_error_sample: Optional[str] = None

    def _generate_one(idx: int) -> Path:
        nonlocal safety_blocked_any, safety_error_sample
        seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
        cand_path = cand_dir / f"{shot_id}_{role}_c{idx}.png"
        cache_key = None
        if cache_enabled:
            cache_key = _hash_cache_key(
                {
                    "kind": "t2i",
                    "adapter": _adapter_fingerprint(adapter),
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "width": int(width),
                    "height": int(height),
                    "seed": int(seed),
                }
            )
            if _try_restore_from_hash_cache(key=cache_key, out_path=cand_path):
                return cand_path
        local_adapter = adapter
        if workers > 1:
            cloned = _clone_adapter_instance(adapter)
            if cloned is None:
                raise RuntimeError("adapter clone failed for parallel candidate generation")
            local_adapter = cloned
        try:
            try:
                result = _generate_t2i_result(
                    adapter=local_adapter,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    seed=seed,
                )
                _write_image_from_generation_result(result, cand_path)
                if cache_enabled and cache_key:
                    _save_to_hash_cache(key=cache_key, src_path=cand_path)
                return cand_path
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text) and aggressive_prompt:
                    try:
                        result = _generate_t2i_result(
                            adapter=local_adapter,
                            prompt=aggressive_prompt,
                            negative_prompt=negative_prompt,
                            width=width,
                            height=height,
                            seed=seed,
                        )
                        _write_image_from_generation_result(result, cand_path)
                        if payload is not None:
                            _bump_telemetry_counter(payload, "t2i_safety_retries", 1)
                        return cand_path
                    except Exception as retry_exc:  # noqa: BLE001
                        error_text = str(retry_exc)
                        if _is_safety_block_error(error_text):
                            safety_blocked_any = True
                            if safety_error_sample is None:
                                safety_error_sample = error_text
                            _write_png_placeholder(cand_path, width=width, height=height)
                            return cand_path
                        raise
                if _is_safety_block_error(error_text):
                    safety_blocked_any = True
                    if safety_error_sample is None:
                        safety_error_sample = error_text
                    _write_png_placeholder(cand_path, width=width, height=height)
                    return cand_path
                raise
        finally:
            if local_adapter is not adapter:
                _close_adapter_session(local_adapter)

    candidate_paths = _generate_candidates(candidate_count=candidate_count, parallelism=workers, generate_one=_generate_one)

    pick = _select_best_candidate(
        candidate_paths=candidate_paths,
        selector=selector,
        vlm_adapter=vlm_adapter,
        vlm_criteria=vlm_criteria,
        target_description=prompt,
        reference_images=reference_images,
        bump_telemetry=(
            (lambda n, d=1: _bump_telemetry_counter(ctx.payload, str(n), int(d)))
            if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict)
            else None
        ),
    )
    candidate_seeds = [_derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx) for idx in range(candidate_count)]
    _finalize_candidates(
        candidate_paths=candidate_paths,
        output_path=output_path,
        best_index=int(pick["best_index"]),
        keep_candidates=keep_candidates,
    )
    if payload is not None:
        _bump_telemetry_counter(payload, "t2i_generate_calls", int(candidate_count) - int(cache_hits))
        if cache_enabled:
            _bump_telemetry_counter(payload, "t2i_cache_hits", int(cache_hits))
            _bump_telemetry_counter(payload, "t2i_cache_misses", int(candidate_count) - int(cache_hits))
        if safety_blocked_any:
            _bump_telemetry_counter(payload, "t2i_safety_blocked", 1)
    out = {
        "candidate_count": candidate_count,
        "selected": int(pick["best_index"]),
        "selector": pick["reason"],
        "scores": pick.get("scores"),
        "base_seed": base_seed if isinstance(base_seed, int) else None,
        "candidate_seeds": candidate_seeds,
        "selected_seed": candidate_seeds[int(pick["best_index"])] if isinstance(pick.get("best_index"), int) and 0 <= int(pick["best_index"]) < len(candidate_seeds) else None,
    }
    if safety_blocked_any:
        out["safety_blocked"] = True
        if safety_error_sample:
            out["safety_error"] = safety_error_sample
    if keep_candidates:
        out["candidates"] = [str(p) for p in candidate_paths]
    return out


def _collect_reference_image_paths(
    reference_images: Optional[List[Dict[str, Any]]],
    base_path: Path,
    max_images: int,
) -> List[str]:
    if not reference_images or max_images <= 0:
        return []
    base_str = str(base_path)
    seen: set[str] = set()
    out: List[str] = []
    for item in reference_images:
        if not isinstance(item, dict):
            continue
        raw = item.get("path")
        if isinstance(raw, Path):
            path_str = str(raw)
        elif isinstance(raw, str):
            path_str = raw.strip()
        else:
            continue
        if not path_str or path_str == base_str or path_str in seen:
            continue
        if not path_str.startswith(("http://", "https://")) and not Path(path_str).exists():
            continue
        seen.add(path_str)
        out.append(path_str)
        if len(out) >= int(max_images):
            break
    return out


def _generate_edit_with_candidates(
    *,
    adapter: Any,
    image_path: Path,
    edit_prompt: str,
    reference_desc: Optional[str] = None,
    strength: float,
    guidance_scale: float,
    base_seed: Any,
    ctx: Any,
    shot_id: str,
    role: str,
    output_path: Path,
    candidate_count: int,
    parallelism: int = 1,
    selector: str,
    vlm_adapter: Any,
    vlm_criteria: List[str],
    reference_images: Optional[List[Dict[str, Any]]] = None,
    keep_candidates: bool,
    enable_hash_cache: Optional[bool] = None,
    bypass_hash_cache: bool = False,
    use_multi_ref: bool = False,
    max_ref_images: int = 3,
) -> Dict[str, Any]:
    cache_enabled = _hash_cache_enabled(enable_hash_cache) and not bool(bypass_hash_cache)
    payload = ctx.payload if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict) else None
    raw_edit_prompt = edit_prompt
    edit_prompt, safety_meta = _sanitize_prompt_for_safety(edit_prompt)
    aggressive_edit_prompt: Optional[str] = None
    if _env_flag("DREAMWEAVER_SAFETY_AGGRESSIVE_FALLBACK", True):
        try:
            from adapters.content_safety_checker import check_and_fix_prompt

            aggressive_edit_prompt, _, _ = check_and_fix_prompt(raw_edit_prompt, strategy="aggressive")
            if not aggressive_edit_prompt or aggressive_edit_prompt == edit_prompt:
                aggressive_edit_prompt = None
        except Exception:  # noqa: BLE001
            aggressive_edit_prompt = None
    if payload is not None and safety_meta.get("issues"):
        _bump_telemetry_counter(payload, "image_edit_safety_fixes", 1)
    base_image_hash = ""
    if cache_enabled:
        base_image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    supports_multi_ref = _supports_multi_image_client(adapter)
    if _is_qwen_image_edit_adapter(adapter):
        max_ref_images = min(int(max_ref_images), 2)
    ref_paths = (
        _collect_reference_image_paths(reference_images, image_path, max_ref_images)
        if use_multi_ref and supports_multi_ref
        else []
    )
    if not ref_paths:
        use_multi_ref = False
    edit_prompt = _apply_image_edit_prompt_constraints(
        prompt=edit_prompt,
        adapter=adapter,
        ref_count=len(ref_paths),
    )
    ref_hashes: List[str] = []
    if cache_enabled and use_multi_ref:
        for ref_path in ref_paths:
            if ref_path.startswith(("http://", "https://")):
                ref_hashes.append(ref_path)
                continue
            try:
                ref_hashes.append(hashlib.sha256(Path(ref_path).read_bytes()).hexdigest())
            except Exception:  # noqa: BLE001
                continue
    if candidate_count <= 1:
        seed_value = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=0)
        cache_key = None
        if cache_enabled:
            cache_payload = {
                "kind": "image_edit",
                "adapter": _adapter_fingerprint(adapter),
                "image_sha256": base_image_hash,
                "edit_prompt": edit_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed_value),
            }
            if use_multi_ref:
                cache_payload["ref_images"] = ref_hashes
            cache_key = _hash_cache_key(cache_payload)
            if _try_restore_from_hash_cache(key=cache_key, out_path=output_path):
                if payload is not None:
                    _bump_telemetry_counter(payload, "image_edit_cache_hits", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "single",
                    "seed": seed_value,
                    "cache_hit": True,
                    "cache_key": cache_key,
                }
            if payload is not None:
                _bump_telemetry_counter(payload, "image_edit_cache_misses", 1)

        if payload is not None:
            _bump_telemetry_counter(payload, "image_edit_generate_calls", 1)
        used_fallback = False
        try:
            try:
                if use_multi_ref:
                    result = _generate_edit_result(
                        adapter=adapter,
                        image_path=image_path,
                        edit_prompt=edit_prompt,
                        strength=strength,
                        guidance_scale=guidance_scale,
                        seed=seed_value,
                        reference_images=ref_paths,
                    )
                else:
                    result = _generate_edit_result(
                        adapter=adapter,
                        image_path=image_path,
                        edit_prompt=edit_prompt,
                        strength=strength,
                        guidance_scale=guidance_scale,
                        seed=seed_value,
                    )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text) and aggressive_edit_prompt:
                    if use_multi_ref:
                        result = _generate_edit_result(
                            adapter=adapter,
                            image_path=image_path,
                            edit_prompt=aggressive_edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed_value,
                            reference_images=ref_paths,
                        )
                    else:
                        result = _generate_edit_result(
                            adapter=adapter,
                            image_path=image_path,
                            edit_prompt=aggressive_edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed_value,
                        )
                    used_fallback = True
                    if payload is not None:
                        _bump_telemetry_counter(payload, "image_edit_safety_retries", 1)
                else:
                    raise
            _write_image_from_generation_result(result, output_path)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if _is_safety_block_error(error_text):
                _write_png_placeholder(output_path, width=None, height=None)
                if payload is not None:
                    _bump_telemetry_counter(payload, "image_edit_safety_blocked", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "safety_placeholder",
                    "seed": seed_value,
                    "cache_hit": False if cache_enabled else None,
                    "cache_key": cache_key,
                    "safety_blocked": True,
                    "safety_error": error_text,
                }
            raise
        if used_fallback:
            cache_key = None
        if cache_enabled and cache_key:
            _save_to_hash_cache(key=cache_key, src_path=output_path)
        return {
            "candidate_count": 1,
            "selected": 0,
            "selector": "single",
            "seed": seed_value,
            "cache_hit": False if cache_enabled else None,
            "cache_key": cache_key,
        }

    cand_dir = output_path.parent / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    cache_hits = 0
    if cache_enabled:
        try:
            cache_dir = _hash_cache_dir()
            for idx in range(int(candidate_count)):
                seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
                cache_payload = {
                    "kind": "image_edit",
                    "adapter": _adapter_fingerprint(adapter),
                    "image_sha256": base_image_hash,
                    "edit_prompt": edit_prompt,
                    "strength": float(strength),
                    "guidance_scale": float(guidance_scale),
                    "seed": int(seed),
                }
                if use_multi_ref:
                    cache_payload["ref_images"] = ref_hashes
                key = _hash_cache_key(cache_payload)
                if (cache_dir / f"{key}.png").exists():
                    cache_hits += 1
        except Exception:  # noqa: BLE001
            cache_hits = 0

    workers = 1
    try:
        workers = int(parallelism)
    except Exception:  # noqa: BLE001
        workers = 1
    workers = max(1, min(workers, candidate_count))
    if workers > 1:
        probe = _clone_adapter_instance(adapter)
        if probe is None:
            workers = 1
        else:
            _close_adapter_session(probe)

    safety_blocked_any = False
    safety_error_sample: Optional[str] = None

    def _generate_one(idx: int) -> Path:
        nonlocal safety_blocked_any, safety_error_sample
        seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
        cand_path = cand_dir / f"{shot_id}_{role}_c{idx}.png"
        cache_key = None
        if cache_enabled:
            cache_payload = {
                "kind": "image_edit",
                "adapter": _adapter_fingerprint(adapter),
                "image_sha256": base_image_hash,
                "edit_prompt": edit_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed),
            }
            if use_multi_ref:
                cache_payload["ref_images"] = ref_hashes
            cache_key = _hash_cache_key(cache_payload)
            if _try_restore_from_hash_cache(key=cache_key, out_path=cand_path):
                return cand_path
        local_adapter = adapter
        if workers > 1:
            cloned = _clone_adapter_instance(adapter)
            if cloned is None:
                raise RuntimeError("adapter clone failed for parallel candidate generation")
            local_adapter = cloned
        try:
            used_fallback = False
            try:
                try:
                    if use_multi_ref:
                        result = _generate_edit_result(
                            adapter=local_adapter,
                            image_path=image_path,
                            edit_prompt=edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed,
                            reference_images=ref_paths,
                        )
                    else:
                        result = _generate_edit_result(
                            adapter=local_adapter,
                            image_path=image_path,
                            edit_prompt=edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed,
                        )
                except Exception as exc:  # noqa: BLE001
                    error_text = str(exc)
                    if _is_safety_block_error(error_text) and aggressive_edit_prompt:
                        if use_multi_ref:
                            result = _generate_edit_result(
                                adapter=local_adapter,
                                image_path=image_path,
                                edit_prompt=aggressive_edit_prompt,
                                strength=strength,
                                guidance_scale=guidance_scale,
                                seed=seed,
                                reference_images=ref_paths,
                            )
                        else:
                            result = _generate_edit_result(
                                adapter=local_adapter,
                                image_path=image_path,
                                edit_prompt=aggressive_edit_prompt,
                                strength=strength,
                                guidance_scale=guidance_scale,
                                seed=seed,
                            )
                        used_fallback = True
                        if payload is not None:
                            _bump_telemetry_counter(payload, "image_edit_safety_retries", 1)
                    else:
                        raise
                _write_image_from_generation_result(result, cand_path)
                if used_fallback:
                    cache_key = None
                if cache_enabled and cache_key:
                    _save_to_hash_cache(key=cache_key, src_path=cand_path)
                return cand_path
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text):
                    safety_blocked_any = True
                    if safety_error_sample is None:
                        safety_error_sample = error_text
                    _write_png_placeholder(cand_path, width=None, height=None)
                    return cand_path
                raise
        finally:
            if local_adapter is not adapter:
                _close_adapter_session(local_adapter)

    candidate_paths = _generate_candidates(candidate_count=candidate_count, parallelism=workers, generate_one=_generate_one)

    ref_desc = str(reference_desc or f"参考图（{image_path.name}）").strip()
    refs = [{"path": image_path, "desc": ref_desc}]
    if isinstance(reference_images, list) and reference_images:
        refs.extend(reference_images)
    pick = _select_best_candidate(
        candidate_paths=candidate_paths,
        selector=selector,
        vlm_adapter=vlm_adapter,
        vlm_criteria=vlm_criteria,
        target_description=edit_prompt,
        reference_images=refs,
        bump_telemetry=(
            (lambda n, d=1: _bump_telemetry_counter(ctx.payload, str(n), int(d)))
            if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict)
            else None
        ),
    )
    candidate_seeds = [_derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx) for idx in range(candidate_count)]
    _finalize_candidates(
        candidate_paths=candidate_paths,
        output_path=output_path,
        best_index=int(pick["best_index"]),
        keep_candidates=keep_candidates,
    )
    if payload is not None:
        _bump_telemetry_counter(payload, "image_edit_generate_calls", int(candidate_count) - int(cache_hits))
        if cache_enabled:
            _bump_telemetry_counter(payload, "image_edit_cache_hits", int(cache_hits))
            _bump_telemetry_counter(payload, "image_edit_cache_misses", int(candidate_count) - int(cache_hits))
        if safety_blocked_any:
            _bump_telemetry_counter(payload, "image_edit_safety_blocked", 1)
    out = {
        "candidate_count": candidate_count,
        "selected": int(pick["best_index"]),
        "selector": pick["reason"],
        "scores": pick.get("scores"),
        "base_seed": base_seed if isinstance(base_seed, int) else None,
        "candidate_seeds": candidate_seeds,
        "selected_seed": candidate_seeds[int(pick["best_index"])] if isinstance(pick.get("best_index"), int) and 0 <= int(pick["best_index"]) < len(candidate_seeds) else None,
    }
    if safety_blocked_any:
        out["safety_blocked"] = True
        if safety_error_sample:
            out["safety_error"] = safety_error_sample
    if keep_candidates:
        out["candidates"] = [str(p) for p in candidate_paths]
    return out


def _library_assets(ctx: Any) -> List[Dict[str, Any]]:
    items = ctx.payload.get("project_assets")
    if not isinstance(items, list):
        return []

    current_style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    current_ratio = str(image_cfg.get("ratio") or "").strip()
    if current_ratio:
        current_ratio = normalize_frame_ratio(current_ratio)

    assets: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        uri = item.get("uri")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if not isinstance(role, str) or not role.startswith("lib_"):
            continue
        if not isinstance(uri, str) or not uri:
            continue
        if not bool(meta.get("approved")):
            continue

        # 避免跨风格复用已审核素材导致“写实/动漫混用”。
        asset_style_preset = str(meta.get("style_preset") or "").strip()
        if current_style_preset:
            if not asset_style_preset:
                continue
            if asset_style_preset != current_style_preset:
                continue

        # 避免跨画幅复用素材导致构图/尺寸不一致。
        asset_ratio = str(meta.get("ratio") or "").strip()
        if current_ratio:
            if not asset_ratio:
                continue
            if normalize_frame_ratio(asset_ratio, default=current_ratio) != current_ratio:
                continue

        entity_type = str(meta.get("entity_type") or "")
        if not entity_type:
            if role.startswith("lib_character_portrait"):
                entity_type = "character"
            elif role.startswith("lib_scene_card"):
                entity_type = "scene"
            elif role.startswith("lib_prop_card"):
                entity_type = "prop"
            else:
                entity_type = "unknown"

        name = str(meta.get("entity_name") or meta.get("name") or "").strip()
        descriptor = str(meta.get("descriptor") or "").strip()
        path = Path(uri)
        if not path.exists():
            continue
        assets.append(
            {
                "role": role,
                "entity_type": entity_type,
                "entity_name": name or role,
                "descriptor": descriptor,
                "path": path,
                "desc": f"{entity_type}:{name}" if name else role,
            }
        )
    return assets


def _match_library_refs_for_shot(
    *,
    shot: Dict[str, Any],
    library_assets: List[Dict[str, Any]],
    max_refs: int = 8,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    def _norm_names(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if not isinstance(item, (str, int)):
                continue
            name = str(item).strip()
            if not name or name in out:
                continue
            out.append(name)
            if len(out) >= 12:
                break
        return out

    explicit_chars = _norm_names(shot.get("ff_vis_char_ids")) + _norm_names(shot.get("lf_vis_char_ids"))
    explicit_chars = [c for i, c in enumerate(explicit_chars) if c and c not in explicit_chars[:i]]

    text = " ".join(
        [
            str(shot.get("visual_desc") or ""),
            str(shot.get("desc") or ""),
            str(shot.get("ff_desc") or ""),
            str(shot.get("lf_desc") or ""),
        ]
    )

    matches: List[Dict[str, Any]] = []
    # 1) 强约束：若 storyboard 提供了可见人物名单，则优先用人物 AnchorSet
    if explicit_chars:
        for asset in library_assets:
            if str(asset.get("entity_type")) != "character":
                continue
            name = str(asset.get("entity_name") or "").strip()
            if name and name in explicit_chars:
                matches.append(asset)

    # 2) 弱匹配：从文本中命中实体名
    for asset in library_assets:
        name = str(asset.get("entity_name") or "").strip()
        if name and name in text:
            matches.append(asset)

    if not any(str(a.get("entity_type")) == "scene" for a in matches):
        for asset in library_assets:
            if str(asset.get("entity_type")) == "scene":
                matches.append(asset)
                break

    order = {"character": 0, "scene": 1, "prop": 2}
    # 去重：按 role 保留第一个
    seen_roles: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for asset in matches:
        role = str(asset.get("role") or "").strip()
        if not role or role in seen_roles:
            continue
        seen_roles.add(role)
        deduped.append(asset)

    matches = sorted(deduped, key=lambda a: order.get(str(a.get("entity_type")), 99))[: max(0, int(max_refs))]

    ref_images: List[Dict[str, Any]] = []
    constraints: List[str] = []
    for asset in matches:
        path = asset.get("path")
        if isinstance(path, Path) and path.exists():
            ref_images.append({"path": path, "desc": str(asset.get("desc") or "")})
        label = str(asset.get("entity_type") or "")
        name = str(asset.get("entity_name") or "")
        desc = str(asset.get("descriptor") or "")[:80].strip()
        if name:
            constraints.append(f"- {label}：{name}：{desc}")
    return ref_images, constraints


def _append_consistency_constraints(prompt: str, constraints: List[str]) -> str:
    base = (prompt or "").strip()
    if not constraints:
        return base
    return f"{base}\n\n一致性约束（必须遵守）：\n" + "\n".join(constraints)


def _ref_images_meta(ref_images: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for ref in ref_images or []:
        if not isinstance(ref, dict):
            continue
        path = ref.get("path")
        if not isinstance(path, Path):
            continue
        desc = str(ref.get("desc") or "").strip()
        out.append({"uri": str(path), "desc": desc})
    return out


def _normalize_ref_issues(issues: Any, *, require_anchor: bool) -> List[str]:
    out: List[str] = []
    if isinstance(issues, list):
        for item in issues:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= 16:
                break

    if not require_anchor and "missing_anchor_card" in out:
        out = [s for s in out if s != "missing_anchor_card"]
    return out


def _selector_with_ref_issues(selector: str, *, vlm_adapter: Any, ref_issues: List[str]) -> Tuple[str, Optional[str]]:
    sel = (selector or "first").strip().lower() or "first"
    if sel != "semantic":
        return sel, None
    if vlm_adapter is None:
        return "file_size", "no_vlm_adapter"
    if any(i in {"missing_character_card", "missing_scene_card", "missing_anchor_card"} for i in (ref_issues or [])):
        return "vlm", "missing_required_refs"
    return sel, None


def _drop_anchor_from_refs(refs: List[Dict[str, Any]], anchor: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not refs:
        return []
    anchor_path = anchor.get("path") if isinstance(anchor, dict) else None
    if not isinstance(anchor_path, Path):
        return refs
    return [r for r in refs if isinstance(r, dict) and r.get("path") != anchor_path]


def _try_generate_multiperson_fusion_head(
    *,
    shot_id: str,
    output_path: Path,
    head_prompt: str,
    style_negative_prompt: str,
    asset_match: Dict[str, Any],
    head_anchor: Optional[Dict[str, Any]],
    use_anchor_scene: bool,
    max_persons: int,
    keep_candidates: bool,
) -> Tuple[Optional[Path], Dict[str, Any]]:
    max_persons = int(max_persons)
    if max_persons < 2:
        return None, {"status": "skipped", "reason": "max_persons_lt_2"}

    character_assets = asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else []
    scene_assets = asset_match.get("scene_assets") if isinstance(asset_match.get("scene_assets"), list) else []

    person_cards: List[Dict[str, Any]] = []
    for asset in character_assets:
        if not isinstance(asset, dict):
            continue
        path = asset.get("path")
        if not isinstance(path, Path) or not path.exists():
            continue
        person_cards.append(asset)
        if len(person_cards) >= max_persons:
            break

    if len(person_cards) < 2:
        return None, {"status": "skipped", "reason": "insufficient_character_cards", "found": len(person_cards)}

    base_scene_path: Optional[Path] = None
    base_scene_source = "none"
    if use_anchor_scene:
        anchor_path = head_anchor.get("path") if isinstance(head_anchor, dict) else None
        if isinstance(anchor_path, Path) and anchor_path.exists():
            base_scene_path = anchor_path
            base_scene_source = "anchor_tail"

    if base_scene_path is None:
        for asset in scene_assets:
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if not isinstance(path, Path) or not path.exists():
                continue
            base_scene_path = path
            base_scene_source = "scene_card"
            break

    if base_scene_path is None:
        return None, {"status": "skipped", "reason": "missing_scene_base"}

    if not _model_client_available("qwen_multiperson_fusion"):
        return None, {"status": "failed", "reason": "adapter_unavailable", "error": "model_not_registered"}

    cand_dir = output_path.parent / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    fusion_dir = cand_dir / "multiperson_fusion"
    fusion_dir.mkdir(parents=True, exist_ok=True)

    base_prompt = str(head_prompt or "").strip()
    base_prompt = _apply_prompt_fragment(
        base_prompt,
        "任务：将输入的人物自然融合到场景中，保持角色身份、服饰细节一致；保持风格、光照、视角一致；避免新增无关人物与文字水印。",
    )

    current_scene_path = base_scene_path
    steps: List[Dict[str, Any]] = []
    try:
        for idx, asset in enumerate(person_cards):
            person_path = asset.get("path")
            if not isinstance(person_path, Path) or not person_path.exists():
                raise RuntimeError(f"invalid person card path at idx={idx}")
            person_name = str(asset.get("entity_name") or "").strip()
            descriptor = str(asset.get("descriptor") or "").replace("\n", " ").strip()
            if len(descriptor) > 120:
                descriptor = descriptor[:120]
            person_hint = person_name or str(asset.get("role") or f"person_{idx}").strip()
            if descriptor:
                person_hint = f"{person_hint}：{descriptor}"

            step_prompt = _apply_prompt_fragment(base_prompt, f"当前融合人物（必须出现且保持一致）：{person_hint}")
            out_step_path = fusion_dir / f"{shot_id}_head_fuse_{idx+1}.png"

            result = match_scene_with_model(
                person_image_path=str(person_path),
                target_scene_path=str(current_scene_path),
                scene_prompt=step_prompt,
                n=1,
                negative_prompt=style_negative_prompt,
                prompt_extend=True,
                watermark=False,
                model_id="qwen_multiperson_fusion",
            )
            _write_image_from_generation_result(result, out_step_path)

            steps.append(
                {
                    "idx": int(idx),
                    "person": {"uri": str(person_path), "name": person_name, "desc": str(asset.get("desc") or "").strip()},
                    "scene_in": str(current_scene_path),
                    "scene_out": str(out_step_path),
                }
            )
            current_scene_path = out_step_path

        output_path.write_bytes(current_scene_path.read_bytes())

        if not keep_candidates:
            for step in steps:
                try:
                    out_uri = str(step.get("scene_out") or "")
                    if out_uri and Path(out_uri).exists():
                        Path(out_uri).unlink()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "failed", "reason": "fusion_error", "error": str(exc), "steps": steps}
    return (
        output_path,
        {
            "status": "success",
            "scene_base": {"uri": str(base_scene_path), "source": base_scene_source},
            "persons": [{"uri": str(a.get("path")), "name": str(a.get("entity_name") or "").strip(), "desc": str(a.get("desc") or "").strip()} for a in person_cards],
            "steps": steps,
        },
    )


def run_keyframes(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    adapter = "wan_t2i"
    run_dir = _ensure_run_dir(ctx)

    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_width, frame_height, frame_ratio = resolve_frame_size(image_cfg)

    candidate_count = _cfg_int(image_cfg, "t2i_candidates", env_name="DREAMWEAVER_T2I_CANDIDATES", default=1)
    candidate_parallelism = _cfg_int(
        image_cfg,
        "candidate_parallelism",
        env_name="DREAMWEAVER_CANDIDATE_PARALLELISM",
        default=0,
    )
    if candidate_parallelism <= 0:
        candidate_parallelism = 2 if candidate_count > 1 else 1
    candidate_parallelism = max(1, min(int(candidate_parallelism), int(candidate_count)))
    image_edit_policy = _cfg_str(
        image_cfg,
        "image_edit_policy",
        env_name="DREAMWEAVER_IMAGE_EDIT_POLICY",
        default="auto",
    ).strip().lower()
    image_edit_min_prompt_similarity = _cfg_float(
        image_cfg,
        "image_edit_min_prompt_similarity",
        env_name="DREAMWEAVER_IMAGE_EDIT_MIN_PROMPT_SIMILARITY",
        default=0.0,
    )
    image_edit_min_prompt_similarity = max(0.0, min(float(image_edit_min_prompt_similarity), 1.0))
    image_edit_candidates = _cfg_int(
        image_cfg,
        "image_edit_candidates",
        env_name="DREAMWEAVER_IMAGE_EDIT_CANDIDATES",
        default=0,
    )
    if image_edit_candidates <= 0:
        image_edit_candidates = 1 if candidate_count <= 1 else min(2, int(candidate_count))
    image_edit_candidates = max(1, min(int(image_edit_candidates), int(candidate_count)))
    qc_cfg = ctx.payload.get("qc_config") if isinstance(ctx.payload.get("qc_config"), dict) else {}
    try:
        max_subject_pos_delta = float(qc_cfg.get("max_subject_pos_delta") or 0.1)
    except Exception:  # noqa: BLE001
        max_subject_pos_delta = 0.1
    selector = _cfg_str(image_cfg, "image_selector", env_name="DREAMWEAVER_IMAGE_SELECTOR", default="first").strip().lower()
    keep_candidates = _cfg_flag(image_cfg, "keep_candidates", env_name="DREAMWEAVER_KEEP_CANDIDATES", default=False)
    max_refs = _cfg_int(image_cfg, "ref_max_images", env_name="DREAMWEAVER_REF_MAX_IMAGES", default=8)
    ref_history_tails = _cfg_int(image_cfg, "ref_history_tails", env_name="DREAMWEAVER_REF_HISTORY_TAILS", default=0)
    ref_history_tails = max(0, min(int(ref_history_tails), 12))
    ref_text_prefilter = _cfg_flag(image_cfg, "ref_text_prefilter", env_name="DREAMWEAVER_REF_TEXT_PREFILTER", default=True)
    ref_text_prefilter_pool = _cfg_int(image_cfg, "ref_text_prefilter_pool", env_name="DREAMWEAVER_REF_TEXT_PREFILTER_POOL", default=24)
    ref_text_prefilter_pool = max(int(max_refs), min(int(ref_text_prefilter_pool), 60))
    skip_tail_small_variation = _cfg_flag(
        image_cfg,
        "skip_tail_small_variation",
        env_name="DREAMWEAVER_SKIP_TAIL_SMALL_VARIATION",
        default=True,
    )
    variation_driven_image_edit = _cfg_flag(
        image_cfg,
        "variation_driven_image_edit",
        env_name="DREAMWEAVER_VARIATION_DRIVEN_IMAGE_EDIT",
        default=True,
    )

    use_head_image_edit = _cfg_flag(image_cfg, "head_use_image_edit", env_name="DREAMWEAVER_HEAD_USE_IMAGE_EDIT", default=False)
    use_tail_image_edit = _cfg_flag(image_cfg, "tail_use_image_edit", env_name="DREAMWEAVER_TAIL_USE_IMAGE_EDIT", default=False)
    enable_multiperson_fusion = _cfg_flag(
        image_cfg,
        "multiperson_fusion",
        env_name="DREAMWEAVER_ENABLE_MULTIPERSON_FUSION",
        default=False,
    )
    multiperson_fusion_use_anchor_scene = _cfg_flag(
        image_cfg,
        "multiperson_fusion_use_anchor_scene",
        env_name="DREAMWEAVER_MULTIPERSON_FUSION_USE_ANCHOR_SCENE",
        default=True,
    )
    multiperson_fusion_max_persons = _cfg_int(
        image_cfg,
        "multiperson_fusion_max_persons",
        env_name="DREAMWEAVER_MULTIPERSON_FUSION_MAX_PERSONS",
        default=3,
    )
    multiperson_fusion_max_persons = max(0, min(int(multiperson_fusion_max_persons), 6))
    ref_selector = _cfg_str(image_cfg, "ref_selector", env_name="DREAMWEAVER_REF_SELECTOR", default="recent").strip().lower()
    head_ref_rewrite = _cfg_flag(image_cfg, "head_ref_rewrite", env_name="DREAMWEAVER_HEAD_REF_REWRITE", default=True)
    tail_ref_rewrite = _cfg_flag(image_cfg, "tail_ref_rewrite", env_name="DREAMWEAVER_TAIL_REF_REWRITE", default=True)
    image_edit_adapter_name_head = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_head",
        default_adapter="wan_image_edit",
    )
    image_edit_adapter_name_tail = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_tail",
        default_adapter="wan_image_edit",
    )
    image_edit_multi_ref_head = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_head,
    )
    image_edit_multi_ref_tail = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_tail,
    )
    image_edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg)
    max_refs_for_edit = max_refs
    if _is_qwen_image_edit_adapter_name(image_edit_adapter_name_head) or _is_qwen_image_edit_adapter_name(
        image_edit_adapter_name_tail
    ):
        max_refs_for_edit = min(int(max_refs_for_edit), 2)
        image_edit_ref_max_images = min(int(image_edit_ref_max_images), 2)

    vlm_adapter = None
    if selector in {"vlm", "semantic"} or ref_selector == "vlm":
        candidate_vlm = str(os.getenv("DREAMWEAVER_VLM_ADAPTER", "qwen3_vl_plus") or "").strip() or "qwen3_vl_plus"
        vlm_adapter = candidate_vlm if _model_client_available(candidate_vlm) else None
    vlm_criteria = [
        s.strip()
        for s in os.getenv("DREAMWEAVER_VLM_CRITERIA", "clarity,composition,lighting,color,style").split(",")
        if s.strip()
    ]

    lib_assets = _library_assets_from_payload(ctx.payload)

    image_edit_strength = _cfg_float(image_cfg, "image_edit_strength", env_name="DREAMWEAVER_IMAGE_EDIT_STRENGTH", default=0.65)
    image_edit_guidance = _cfg_float(image_cfg, "image_edit_guidance", env_name="DREAMWEAVER_IMAGE_EDIT_GUIDANCE", default=7.5)

    style_negative_prompt = str(ctx.payload.get("style_negative_prompt") or "").strip()

    semantic_index = None
    semantic_cfg: Optional[Dict[str, Any]] = None
    try:
        from agents.semantic_asset_index import SemanticAssetIndex, is_semantic_retrieval_enabled, semantic_retrieval_config

        project_id = int(ctx.payload.get("project_id") or 0)
        if project_id > 0 and is_semantic_retrieval_enabled(image_cfg=image_cfg):
            semantic_cfg = semantic_retrieval_config(image_cfg)
            semantic_index = SemanticAssetIndex(
                project_id=project_id,
                db_path=Path(semantic_cfg["db_path"]),
                dim=int(semantic_cfg.get("dim") or 256),
                max_items_per_project=int(semantic_cfg.get("max_items_per_project") or 5000),
                text_max_chars=int(semantic_cfg.get("text_max_chars") or 800),
            )

            # 预热：把已审核通过的素材库图写入索引（同项目二次生成即可直接命中）
            lib_items: List[Dict[str, Any]] = []
            for asset in lib_assets:
                if not isinstance(asset, dict):
                    continue
                path = asset.get("path")
                if not isinstance(path, Path) or not path.exists():
                    continue
                role = str(asset.get("role") or "").strip()
                entity_type = str(asset.get("entity_type") or "").strip()
                name = str(asset.get("entity_name") or "").strip()
                descriptor = str(asset.get("descriptor") or "").strip()
                text = " ".join([s for s in [entity_type, name, role, descriptor] if s]).strip()
                if not text:
                    continue
                lib_items.append(
                    {
                        "kind": "library_asset",
                        "path": path,
                        "text": text,
                        "meta": {
                            "role": role,
                            "entity_type": entity_type,
                            "entity_name": name,
                            "descriptor": descriptor,
                        },
                    }
                )
                if len(lib_items) >= 200:
                    break
            if lib_items:
                semantic_index.add_many(lib_items)
    except Exception:  # noqa: BLE001
        semantic_index = None
        semantic_cfg = None

    storyboard = ctx.payload.get("storyboard", [])
    camera_tree = ctx.payload.get("camera_tree")
    if not isinstance(camera_tree, list) or not any(isinstance(n, dict) and isinstance(n.get("cam_idx"), int) for n in camera_tree):
        camera_tree = build_camera_tree(storyboard if isinstance(storyboard, list) else [])
    camera_parent_map = build_camera_parent_map(camera_tree)
    if camera_tree:
        ctx.payload["camera_tree"] = camera_tree

    camera_states = ctx.payload.get("camera_states")
    needs_rebuild_camera_states = not isinstance(camera_states, list) or not camera_states
    if not needs_rebuild_camera_states:
        has_dep_fields = False
        for track in camera_states:
            if not isinstance(track, dict):
                continue
            states = track.get("states") if isinstance(track.get("states"), list) else []
            for state in states:
                if not isinstance(state, dict):
                    continue
                if "depends_on_state_ids" in state or "anchor_shot_id" in state or "anchor_source" in state:
                    has_dep_fields = True
                    break
            if has_dep_fields:
                break
        if not has_dep_fields:
            needs_rebuild_camera_states = True

    if needs_rebuild_camera_states:
        camera_states = build_camera_states(
            storyboard if isinstance(storyboard, list) else [],
            camera_tree if isinstance(camera_tree, list) and camera_tree else None,
        )
    if camera_states:
        ctx.payload["camera_states"] = camera_states

    camera_state_by_shot_id: Dict[str, Dict[str, Any]] = {}
    for track in camera_states or []:
        if not isinstance(track, dict):
            continue
        states = track.get("states") if isinstance(track.get("states"), list) else []
        for state in states:
            if not isinstance(state, dict):
                continue
            sid = str(state.get("shot_id") or state.get("state_id") or "").strip()
            if not sid or sid in camera_state_by_shot_id:
                continue
            camera_state_by_shot_id[sid] = state

    regen_shots_raw = ctx.payload.get("regenerate_shot_ids")
    regen_shots: List[str] = []
    if isinstance(regen_shots_raw, list):
        for item in regen_shots_raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in regen_shots:
                continue
            regen_shots.append(s)
            if len(regen_shots) >= 200:
                break
    regen_shot_set = set(regen_shots)

    def _shot_key_and_role(path: str) -> Tuple[Optional[str], Optional[str]]:
        p = Path(path)
        stem = p.stem
        suffix = p.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            return None, None
        if stem.endswith("_head"):
            return stem[: -len("_head")], "head"
        if stem.endswith("_tail"):
            return stem[: -len("_tail")], "tail"
        if stem.endswith("_mid"):
            return stem[: -len("_mid")], "mid"
        return None, None

    existing_keyframes_by_shot: Dict[str, Dict[str, Dict[str, Any]]] = {}
    existing_keyframes_raw = ctx.payload.get("keyframes")
    if not isinstance(existing_keyframes_raw, list):
        existing_keyframes_raw = []
    for f in existing_keyframes_raw:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        shot_key, role = _shot_key_and_role(path)
        if not shot_key or role not in {"head", "tail"}:
            continue
        existing_keyframes_by_shot.setdefault(shot_key, {})[role] = f

    keyframes_parallelism = _cfg_int(
        image_cfg,
        "shot_parallelism",
        env_name="DREAMWEAVER_KEYFRAMES_PARALLELISM",
        default=1,
    )
    if not isinstance(storyboard, list):
        keyframes_parallelism = 1
    keyframes_parallelism = max(1, min(int(keyframes_parallelism), len(storyboard) if isinstance(storyboard, list) else 1))
    if isinstance(storyboard, list) and storyboard:
        plans: List[Dict[str, Any]] = []
        shot_history_by_cam: Dict[int, List[str]] = {}
        prev_tail_prompt_by_shot: Dict[str, str] = {}
        tail_spec_by_shot: Dict[str, Dict[str, Any]] = {}
        lf_vis_by_shot: Dict[str, List[str]] = {}

        for item in storyboard:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "")
            cam_idx = 0
            try:
                cam_idx = int(item.get("cam_idx") or item.get("camera_index") or 0)
            except Exception:  # noqa: BLE001
                cam_idx = 0
            parent_cam_idx = camera_parent_map.get(cam_idx)
            head_spec = item.get("head_frame")
            tail_spec = item.get("tail_frame")
            if not shot_id or not isinstance(head_spec, dict) or not isinstance(tail_spec, dict):
                raise ValueError("invalid storyboard item: missing shot_id/head_frame/tail_frame")

            ff_vis_char_ids = _as_str_list(item.get("ff_vis_char_ids"))
            lf_vis_char_ids = _as_str_list(item.get("lf_vis_char_ids"))

            asset_match = _match_library_assets_for_shot(
                shot=item,
                library_assets=lib_assets,
                max_character_refs=min(4, int(max_refs)),
            )
            prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
            ref_images: List[Dict[str, Any]] = []
            for asset in (
                (asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else [])
                + (asset_match.get("scene_assets") if isinstance(asset_match.get("scene_assets"), list) else [])
                + (asset_match.get("prop_assets") if isinstance(asset_match.get("prop_assets"), list) else [])
            ):
                if not isinstance(asset, dict):
                    continue
                path = asset.get("path")
                if not isinstance(path, Path) or not path.exists():
                    continue
                ref_images.append({"path": path, "desc": str(asset.get("desc") or "").strip()})
                if len(ref_images) >= max(0, int(max_refs)):
                    break

            head_prompt = _apply_prompt_fragment(str(head_spec.get("prompt") or ""), prompt_fragment)
            tail_prompt = _apply_prompt_fragment(str(tail_spec.get("prompt") or ""), prompt_fragment)
            state_before = str(item.get("state_before") or "").strip()
            state_after = str(item.get("state_after") or "").strip()
            if state_before:
                head_prompt = _apply_prompt_fragment(head_prompt, f"状态约束（镜头开始）：{state_before}")
            if state_after:
                tail_prompt = _apply_prompt_fragment(tail_prompt, f"状态约束（镜头结束）：{state_after}")
            tail_prompt_for_state = tail_prompt or head_prompt

            state = camera_state_by_shot_id.get(shot_id)
            anchor_shot_id: Optional[str] = None
            anchor_source = "none"
            depends_on_state_ids: List[str] = []
            if isinstance(state, dict):
                raw_anchor = state.get("anchor_shot_id")
                if isinstance(raw_anchor, str) and raw_anchor.strip():
                    anchor_shot_id = raw_anchor.strip()
                anchor_source = str(state.get("anchor_source") or "none").strip() or "none"
                depends_on_state_ids = _as_str_list(state.get("depends_on_state_ids"))
            if not depends_on_state_ids and isinstance(anchor_shot_id, str) and anchor_shot_id.strip():
                depends_on_state_ids = [anchor_shot_id.strip()]

            head_base_desc = ""
            head_base_spec: Optional[Dict[str, Any]] = None
            head_base_visible_chars: List[str] = []
            if anchor_shot_id:
                base_prompt = str(prev_tail_prompt_by_shot.get(anchor_shot_id) or "").strip()
                head_base_spec = tail_spec_by_shot.get(anchor_shot_id) if isinstance(tail_spec_by_shot.get(anchor_shot_id), dict) else None
                head_base_visible_chars = _as_str_list(lf_vis_by_shot.get(anchor_shot_id))
                if anchor_source == "camera_last_tail":
                    head_base_desc = f"同相机{cam_idx} 上一次镜头{anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "camera_tree_parent_shot":
                    head_base_desc = f"相机树依赖：父相机{parent_cam_idx} 镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "parent_camera_tail":
                    head_base_desc = f"父相机{parent_cam_idx} 镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "previous_shot_tail":
                    head_base_desc = f"上一镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"

            history_refs: List[Dict[str, Any]] = []
            if ref_history_tails > 0:
                def _push_history(cam: Optional[int], *, label: str) -> None:
                    if not isinstance(cam, int):
                        return
                    hist = shot_history_by_cam.get(int(cam))
                    if not isinstance(hist, list) or not hist:
                        return
                    for sid in reversed(hist[-ref_history_tails:]):
                        if not isinstance(sid, str) or not sid.strip():
                            continue
                        base_prompt = str(prev_tail_prompt_by_shot.get(sid) or "").strip()
                        desc = f"{label} 镜头{sid} 的尾帧；prompt={base_prompt[:80]}" if base_prompt else f"{label} 镜头{sid} 的尾帧"
                        history_refs.append({"path": run_dir / f"{sid}_tail.png", "desc": desc})

                _push_history(int(cam_idx), label=f"同相机{cam_idx} 历史")
                if isinstance(parent_cam_idx, int):
                    _push_history(int(parent_cam_idx), label=f"父相机{parent_cam_idx} 历史")

            semantic_retrieval: Optional[Dict[str, Any]] = None
            if semantic_index is not None and isinstance(semantic_cfg, dict):
                try:
                    exclude_paths: List[Path] = []
                    for ref in ref_images + history_refs:
                        p = ref.get("path") if isinstance(ref, dict) else None
                        if isinstance(p, Path):
                            exclude_paths.append(p)

                    hits = semantic_index.query(
                        text=head_prompt or str(head_spec.get("prompt") or ""),
                        top_k=int(semantic_cfg.get("top_k") or 0),
                        min_score=float(semantic_cfg.get("min_score") or 0.0),
                        kinds=["frame", "library_asset"],
                        exclude_paths=exclude_paths,
                    )
                    _bump_telemetry_counter(ctx.payload, "semantic_retrieval_queries", 1)

                    max_add = max(0, int(semantic_cfg.get("max_additional_refs") or 0))
                    added = 0
                    add_library: List[Dict[str, Any]] = []
                    add_history: List[Dict[str, Any]] = []
                    hit_meta: List[Dict[str, Any]] = []
                    existing_roles: set[str] = set()
                    for group_key in ("character_assets", "scene_assets", "prop_assets"):
                        group = asset_match.get(group_key) if isinstance(asset_match.get(group_key), list) else []
                        for item0 in group:
                            if not isinstance(item0, dict):
                                continue
                            r0 = str(item0.get("role") or "").strip()
                            if r0:
                                existing_roles.add(r0)
                    for h in hits:
                        if max_add and added >= max_add:
                            break
                        path = getattr(h, "path", None)
                        if not isinstance(path, Path) or not path.exists():
                            continue
                        kind = str(getattr(h, "kind", "") or "").strip() or "frame"
                        score = float(getattr(h, "score", 0.0))
                        meta = getattr(h, "meta", {}) if isinstance(getattr(h, "meta", None), dict) else {}
                        label = meta.get("role") or meta.get("frame_role") or meta.get("entity_name") or meta.get("entity_type") or kind
                        label = str(label or "").strip()
                        desc = f"[语义检索] score={score:.3f} {label}"
                        cand = {"path": path, "desc": desc}
                        if kind == "library_asset":
                            add_library.append(cand)
                            role = str(meta.get("role") or "").strip()
                            entity_type = str(meta.get("entity_type") or "").strip().lower()
                            entity_name = str(meta.get("entity_name") or "").strip()
                            descriptor = str(meta.get("descriptor") or "").strip()
                            if role and role not in existing_roles and entity_type in {"character", "scene", "prop"}:
                                asset_item = {
                                    "role": role,
                                    "entity_type": entity_type,
                                    "entity_name": entity_name,
                                    "descriptor": descriptor,
                                    "path": path,
                                    "desc": desc,
                                }
                                if entity_type == "character":
                                    asset_match.setdefault("character_assets", [])
                                    if isinstance(asset_match.get("character_assets"), list):
                                        asset_match["character_assets"].append(asset_item)
                                elif entity_type == "scene":
                                    asset_match.setdefault("scene_assets", [])
                                    if isinstance(asset_match.get("scene_assets"), list):
                                        asset_match["scene_assets"].append(asset_item)
                                else:
                                    asset_match.setdefault("prop_assets", [])
                                    if isinstance(asset_match.get("prop_assets"), list):
                                        asset_match["prop_assets"].append(asset_item)
                                existing_roles.add(role)
                        else:
                            add_history.append(cand)
                        hit_meta.append(
                            {
                                "score": score,
                                "kind": kind,
                                "uri": str(path),
                                "label": label,
                                "meta": meta,
                            }
                        )
                        added += 1

                    if hit_meta:
                        _bump_telemetry_counter(ctx.payload, "semantic_retrieval_hits", len(hit_meta))
                    if add_library:
                        ref_images = add_library + ref_images
                    if add_history:
                        history_refs = add_history + history_refs

                    if hit_meta:
                        semantic_retrieval = {
                            "enabled": True,
                            "query": (head_prompt or str(head_spec.get("prompt") or "")).strip()[:240],
                            "top_k": int(semantic_cfg.get("top_k") or 0),
                            "min_score": float(semantic_cfg.get("min_score") or 0.0),
                            "added_refs": int(added),
                            "hits": hit_meta,
                        }
                except Exception as exc:  # noqa: BLE001
                    semantic_retrieval = {"enabled": True, "error": str(exc)}

            library_refs_meta = _ref_images_meta(ref_images)

            variation_type = str(item.get("variation_type") or "").strip().lower()
            if variation_type not in {"small", "medium", "large"}:
                variation_type = ""
            variation_reason = str(item.get("variation_reason") or "").replace("\n", " ").strip()
            if len(variation_reason) > 240:
                variation_reason = variation_reason[:240]

            bypass_hash_cache = bool(regen_shot_set and shot_id in regen_shot_set)
            plans.append(
                {
                    "shot_id": shot_id,
                    "cam_idx": int(cam_idx),
                    "parent_cam_idx": parent_cam_idx,
                    "head_spec": head_spec,
                    "tail_spec": tail_spec,
                    "ff_vis_char_ids": ff_vis_char_ids,
                    "lf_vis_char_ids": lf_vis_char_ids,
                    "ref_images": ref_images,
                    "library_refs_meta": library_refs_meta,
                    "asset_match": asset_match,
                    "prompt_fragment": prompt_fragment,
                    "head_prompt": head_prompt,
                    "tail_prompt": tail_prompt,
                    "variation_type": variation_type,
                    "variation_reason": variation_reason,
                    "anchor_shot_id": anchor_shot_id,
                    "anchor_source": anchor_source,
                    "depends_on_state_ids": depends_on_state_ids,
                    "history_refs": history_refs,
                    "head_base_desc": head_base_desc,
                    "head_base_spec": head_base_spec,
                    "head_base_visible_chars": head_base_visible_chars,
                    "bypass_hash_cache": bypass_hash_cache,
                    "semantic_retrieval": semantic_retrieval,
                }
            )

            prev_tail_prompt_by_shot[shot_id] = tail_prompt_for_state
            tail_spec_by_shot[shot_id] = tail_spec
            lf_vis_by_shot[shot_id] = lf_vis_char_ids
            shot_history_by_cam.setdefault(int(cam_idx), []).append(shot_id)

        results_by_shot: Dict[str, Dict[str, Dict[str, Any]]] = {}
        completed: set[str] = set()
        remaining: Dict[str, Dict[str, Any]] = {}
        for plan in plans:
            shot_id = str(plan.get("shot_id") or "")
            if not shot_id:
                continue
            head_path = run_dir / f"{shot_id}_head.png"
            tail_path = run_dir / f"{shot_id}_tail.png"
            if regen_shot_set and shot_id not in regen_shot_set:
                existing = existing_keyframes_by_shot.get(shot_id) if isinstance(existing_keyframes_by_shot.get(shot_id), dict) else None
                existing_head = existing.get("head") if isinstance(existing, dict) else None
                existing_tail = existing.get("tail") if isinstance(existing, dict) else None
                if isinstance(existing_head, dict) and isinstance(existing_tail, dict) and head_path.exists() and tail_path.exists():
                    results_by_shot[shot_id] = {"head": existing_head, "tail": existing_tail}
                    completed.add(shot_id)
                    continue
            remaining[shot_id] = plan

        def _render_one(shot_plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
            shot_id = str(shot_plan.get("shot_id") or "")
            cam_idx = int(shot_plan.get("cam_idx") or 0)
            parent_cam_idx = shot_plan.get("parent_cam_idx")
            head_spec = shot_plan.get("head_spec")
            tail_spec = shot_plan.get("tail_spec")
            if not shot_id or not isinstance(head_spec, dict) or not isinstance(tail_spec, dict):
                raise ValueError("invalid shot_plan: missing shot_id/head_spec/tail_spec")

            ff_vis_char_ids = _as_str_list(shot_plan.get("ff_vis_char_ids"))
            lf_vis_char_ids = _as_str_list(shot_plan.get("lf_vis_char_ids"))
            ref_images = shot_plan.get("ref_images", [])
            constraints = shot_plan.get("constraints", [])
            library_refs_meta = shot_plan.get("library_refs_meta", [])
            history_refs = shot_plan.get("history_refs", [])
            asset_match = shot_plan.get("asset_match") if isinstance(shot_plan.get("asset_match"), dict) else {}
            semantic_retrieval = (
                shot_plan.get("semantic_retrieval")
                if isinstance(shot_plan.get("semantic_retrieval"), dict)
                else None
            )

            head_prompt = str(shot_plan.get("head_prompt") or "")
            tail_prompt = str(shot_plan.get("tail_prompt") or "")
            variation_type = str(shot_plan.get("variation_type") or "").strip().lower()
            if variation_type not in {"small", "medium", "large"}:
                variation_type = ""
            variation_reason = str(shot_plan.get("variation_reason") or "").replace("\n", " ").strip()

            anchor_shot_id = shot_plan.get("anchor_shot_id")
            anchor_source = str(shot_plan.get("anchor_source") or "none")
            head_base_desc = str(shot_plan.get("head_base_desc") or "").strip()
            head_base_spec = shot_plan.get("head_base_spec") if isinstance(shot_plan.get("head_base_spec"), dict) else None
            head_base_visible_chars = _as_str_list(shot_plan.get("head_base_visible_chars"))
            bypass_hash_cache = bool(shot_plan.get("bypass_hash_cache"))

            head_path = run_dir / f"{shot_id}_head.png"
            tail_path = run_dir / f"{shot_id}_tail.png"

            head_base_path: Optional[Path] = None
            if isinstance(anchor_shot_id, str) and anchor_shot_id.strip():
                head_base_path = run_dir / f"{anchor_shot_id}_tail.png"

            local_t2i = "wan_t2i"

            local_image_edit_adapters: Dict[str, Any] = {}
            if use_head_image_edit:
                local_image_edit_adapters[image_edit_adapter_name_head] = (
                    image_edit_adapter_name_head if _model_client_available(image_edit_adapter_name_head) else None
                )
            if use_tail_image_edit and image_edit_adapter_name_tail not in local_image_edit_adapters:
                local_image_edit_adapters[image_edit_adapter_name_tail] = (
                    image_edit_adapter_name_tail if _model_client_available(image_edit_adapter_name_tail) else None
                )

            local_vlm_adapter = None
            if selector in {"vlm", "semantic"} or ref_selector == "vlm":
                candidate_vlm = str(os.getenv("DREAMWEAVER_VLM_ADAPTER", "qwen3_vl_plus") or "").strip() or "qwen3_vl_plus"
                local_vlm_adapter = candidate_vlm if _model_client_available(candidate_vlm) else None

            def _normalize_ref_list(raw: Any) -> List[Dict[str, Any]]:
                out: List[Dict[str, Any]] = []
                if not isinstance(raw, list):
                    return out
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path")
                    if not isinstance(path, Path):
                        continue
                    desc = str(item.get("desc") or "").strip()
                    out.append({"path": path, "desc": desc})
                    if len(out) >= 200:
                        break
                return out

            ref_images = _normalize_ref_list(ref_images)
            history_refs = _normalize_ref_list(history_refs)
            library_index_by_uri: Dict[str, int] = {}
            for idx, ref in enumerate(ref_images):
                path = ref.get("path")
                if isinstance(path, Path):
                    library_index_by_uri[str(path)] = idx

            def _build_rewrite_pool(
                *,
                anchor: Optional[Dict[str, Any]],
                drop: Optional[Dict[str, Any]] = None,
                selection_refs: Optional[List[Dict[str, Any]]] = None,
            ) -> List[Dict[str, Any]]:
                others: List[Dict[str, Any]] = []
                others.extend(history_refs)
                if selection_refs:
                    others.extend(selection_refs)
                else:
                    others.extend(ref_images)
                if drop is not None:
                    others = _drop_anchor_from_refs(others, drop)
                pool = _merge_reference_images(anchor=anchor, others=others)
                if ref_text_prefilter_pool > 0 and len(pool) > int(ref_text_prefilter_pool):
                    pool = pool[: int(ref_text_prefilter_pool)]
                return pool

            def _select_rewrite_subset(
                pool: List[Dict[str, Any]],
                *,
                frame_description: str,
                enable_prefilter: bool,
            ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[int]]:
                if not pool:
                    return [], None, []
                keep = max(1, int(max_refs))
                if not enable_prefilter or local_vlm_adapter is None or len(pool) <= keep:
                    subset = pool[:keep]
                    return subset, None, list(range(len(subset)))

                pre = _vlm_prefilter_reference_images_text_only(
                    vlm_adapter=local_vlm_adapter,
                    frame_description=frame_description,
                    candidates=pool,
                    max_keep=keep,
                )
                _bump_telemetry_counter(ctx.payload, "vlm_text_prefilter_calls", 1)

                indices: List[int] = []
                if isinstance(pre, dict):
                    raw = pre.get("selected_ref_indices")
                    if isinstance(raw, list):
                        for item in raw:
                            if not isinstance(item, int):
                                continue
                            if item < 0 or item >= len(pool):
                                continue
                            if item in indices:
                                continue
                            indices.append(item)
                            if len(indices) >= min(keep, len(pool)):
                                break

                if indices:
                    return [pool[i] for i in indices], pre, indices

                subset = pool[:keep]
                return subset, None, list(range(len(subset)))

            def _selected_pool_indices_from_pick(pick: Optional[Dict[str, Any]], subset_to_pool: List[int]) -> List[int]:
                if not isinstance(pick, dict):
                    return []
                raw = pick.get("selected_ref_indices")
                if not isinstance(raw, list):
                    return []
                out: List[int] = []
                for item in raw:
                    if not isinstance(item, int):
                        continue
                    if item < 0 or item >= len(subset_to_pool):
                        continue
                    pool_idx = subset_to_pool[item]
                    if pool_idx in out:
                        continue
                    out.append(pool_idx)
                    if len(out) >= min(8, len(subset_to_pool)):
                        break
                return out

            def _selected_library_indices_from_pool(pool: List[Dict[str, Any]], pool_indices: List[int]) -> List[int]:
                out: List[int] = []
                for pidx in pool_indices:
                    if not isinstance(pidx, int) or pidx < 0 or pidx >= len(pool):
                        continue
                    path = pool[pidx].get("path")
                    if not isinstance(path, Path):
                        continue
                    lib_idx = library_index_by_uri.get(str(path))
                    if lib_idx is None or lib_idx in out:
                        continue
                    out.append(lib_idx)
                return out

            try:
                head_via = "t2i"
                head_ref: Optional[Dict[str, Any]] = None
                head_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
                head_anchor: Optional[Dict[str, Any]] = None
                if head_base_path is not None and head_base_desc:
                    head_anchor = {"path": head_base_path, "desc": head_base_desc}
                require_head_anchor = bool(isinstance(anchor_shot_id, str) and anchor_shot_id.strip())
                head_ref_pack, head_ref_issues_raw = _build_reference_pack(anchor=head_anchor, match=asset_match)
                head_ref_issues = _normalize_ref_issues(head_ref_issues_raw, require_anchor=require_head_anchor)
                head_selector, head_selector_degraded_reason = _selector_with_ref_issues(
                    selector,
                    vlm_adapter=local_vlm_adapter,
                    ref_issues=head_ref_issues,
                )
                head_edit_ref_pack = _drop_anchor_from_refs(head_ref_pack, head_anchor)

                head_extra_meta: Dict[str, Any] = {}
                if semantic_retrieval:
                    head_extra_meta["semantic_retrieval"] = semantic_retrieval
                fused_head_path: Optional[Path] = None
                if enable_multiperson_fusion:
                    _bump_telemetry_counter(ctx.payload, "multiperson_fusion_attempts", 1)
                    fused_head_path, fusion_meta = _try_generate_multiperson_fusion_head(
                        shot_id=shot_id,
                        output_path=head_path,
                        head_prompt=head_prompt,
                        style_negative_prompt=style_negative_prompt,
                        asset_match=asset_match,
                        head_anchor=head_anchor,
                        use_anchor_scene=multiperson_fusion_use_anchor_scene,
                        max_persons=multiperson_fusion_max_persons,
                        keep_candidates=keep_candidates,
                    )
                    head_extra_meta["multiperson_fusion"] = fusion_meta
                    if isinstance(fusion_meta, dict):
                        status = str(fusion_meta.get("status") or "").strip().lower()
                        if status == "success":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_success", 1)
                            steps = fusion_meta.get("steps") if isinstance(fusion_meta.get("steps"), list) else []
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_steps", len(steps))
                        elif status == "failed":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_failed", 1)
                        elif status == "skipped":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_skipped", 1)
                    if fused_head_path is not None:
                        head_via = "multiperson_fusion"
                        head_decision = {
                            "mode": "multiperson_fusion",
                            "reason": "多人物融合生成 head",
                            "cam_idx": cam_idx,
                            "parent_cam_idx": parent_cam_idx,
                            "anchor_source": anchor_source,
                        }
                        head_ref = {
                            "base": {"uri": str(head_base_path), "desc": head_base_desc} if head_anchor else None,
                            "library_refs": library_refs_meta,
                            "selection_refs": _ref_images_meta(head_ref_pack),
                            "issues": head_ref_issues,
                        }
                        head_meta = {"candidate_count": 1, "selected": 0, "selector": "single"}

                if fused_head_path is None:
                    head_image_edit_adapter = local_image_edit_adapters.get(image_edit_adapter_name_head)
                    if use_head_image_edit and head_image_edit_adapter is None:
                        head_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
                    elif use_head_image_edit:
                        head_decision = _decide_image_mode(
                            policy=image_edit_policy,
                            base_image_path=head_base_path,
                            base_spec=head_base_spec,
                            target_spec=head_spec,
                            base_visible_chars=head_base_visible_chars,
                            target_visible_chars=ff_vis_char_ids,
                            max_subject_pos_delta=max_subject_pos_delta,
                            min_prompt_similarity=image_edit_min_prompt_similarity,
                            default_ratio=frame_ratio,
                        )
                    head_decision = {**head_decision, "cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}

                    if (
                        head_decision.get("mode") == "image_edit"
                        and head_image_edit_adapter is not None
                        and head_base_path is not None
                        and head_base_path.exists()
                    ):
                        base_desc = head_base_desc or f"基准图：{str(head_base_path)}"
                        edit_prompt = head_prompt
                        ref_pick = None
                        rewrite_pool = _build_rewrite_pool(anchor=None, drop={"path": head_base_path, "desc": base_desc}, selection_refs=head_edit_ref_pack)
                        rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                            rewrite_pool,
                            frame_description=head_prompt,
                            enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None),
                        )
                        if ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_head", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(rewrite_subset) + 1)
                            ref_pick = _vlm_build_edit_prompt_from_base_and_refs(
                                vlm_adapter=local_vlm_adapter,
                                base_image_path=head_base_path,
                                base_image_desc=base_desc,
                                target_description=head_prompt,
                                reference_images=rewrite_subset,
                                max_refs=max_refs_for_edit,
                            )
                            if isinstance(ref_pick, dict) and isinstance(ref_pick.get("edit_prompt"), str):
                                edit_prompt = str(ref_pick.get("edit_prompt") or head_prompt)

                        selected_pool_indices = _selected_pool_indices_from_pick(ref_pick, subset_to_pool)
                        selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                        if selected_library_indices:
                            selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                            selected_ref_indices: Optional[List[int]] = selected_library_indices
                        else:
                            selected_ref_images, selected_ref_indices = ref_images, None
                        selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]
                        selection_refs = head_ref_pack
                        head_ref = {
                            "base": {"uri": str(head_base_path), "desc": base_desc},
                            "library_refs": library_refs_meta,
                            "selected_library_ref_indices": selected_ref_indices,
                            "selected_library_refs": _ref_images_meta(selected_ref_images),
                            "rewrite_candidates": _ref_images_meta(rewrite_pool),
                            "rewrite_prefilter": rewrite_prefilter,
                            "selected_rewrite_ref_indices": selected_pool_indices or None,
                            "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                            "selection_refs": _ref_images_meta(selection_refs),
                            "issues": head_ref_issues,
                            "rewrite": ref_pick,
                        }

                        try:
                            head_meta = _generate_edit_with_candidates(
                                adapter=head_image_edit_adapter,
                                image_path=head_base_path,
                                edit_prompt=edit_prompt,
                                reference_desc=base_desc,
                                strength=image_edit_strength,
                                guidance_scale=image_edit_guidance,
                                base_seed=head_spec.get("seed"),
                                ctx=ctx,
                                shot_id=shot_id,
                                role="head",
                                output_path=head_path,
                                candidate_count=image_edit_candidates,
                                parallelism=candidate_parallelism,
                                selector=head_selector,
                                vlm_adapter=local_vlm_adapter,
                                vlm_criteria=vlm_criteria,
                                reference_images=head_edit_ref_pack,
                                keep_candidates=keep_candidates,
                                bypass_hash_cache=bypass_hash_cache,
                                use_multi_ref=image_edit_multi_ref_head,
                                max_ref_images=image_edit_ref_max_images,
                            )
                            head_via = "image_edit"
                        except Exception as exc:  # noqa: BLE001
                            head_meta = _generate_t2i_with_candidates(
                                adapter=local_t2i,
                                prompt=head_prompt,
                                negative_prompt=style_negative_prompt,
                                width=frame_width,
                                height=frame_height,
                                base_seed=head_spec.get("seed"),
                                ctx=ctx,
                                shot_id=shot_id,
                                role="head",
                                output_path=head_path,
                                candidate_count=candidate_count,
                                parallelism=candidate_parallelism,
                                selector=head_selector,
                                vlm_adapter=local_vlm_adapter,
                                vlm_criteria=vlm_criteria,
                                reference_images=selection_refs,
                                keep_candidates=keep_candidates,
                                bypass_hash_cache=bypass_hash_cache,
                            )
                            head_meta["fallback_error"] = str(exc)
                            head_via = "image_edit_fallback"
                    else:
                        rewritten = None
                        prompt_for_t2i = head_prompt
                        rewrite_anchor = None
                        if head_base_path is not None and head_base_path.exists():
                            rewrite_anchor = {"path": head_base_path, "desc": head_base_desc or f"基准图：{str(head_base_path)}"}
                        rewrite_pool = _build_rewrite_pool(anchor=rewrite_anchor, selection_refs=head_ref_pack)
                        rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                            rewrite_pool,
                            frame_description=head_prompt,
                            enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None),
                        )
                        selected_pool_indices: List[int] = []
                        if ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                            _bump_telemetry_counter(ctx.payload, "vlm_rewrite_t2i_calls", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_rewrite_t2i_ref_images", len(rewrite_subset))
                            rewritten = _vlm_rewrite_t2i_prompt_from_references(
                                vlm_adapter=local_vlm_adapter,
                                frame_description=head_prompt,
                                reference_images=rewrite_subset,
                                max_refs=max_refs,
                            )
                            selected_pool_indices = _selected_pool_indices_from_pick(rewritten, subset_to_pool)
                            if isinstance(rewritten, dict) and isinstance(rewritten.get("prompt"), str):
                                prompt_for_t2i = str(rewritten.get("prompt") or head_prompt)

                        selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                        if selected_library_indices:
                            selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                            selected_ref_indices = selected_library_indices
                        else:
                            selected_ref_images, selected_ref_indices = ref_images, None
                        selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]

                        selection_refs = head_ref_pack
                        if head_anchor or ref_images or history_refs or rewritten:
                            head_ref = {
                                "base": {"uri": str(head_base_path), "desc": head_base_desc} if head_anchor else None,
                                "library_refs": library_refs_meta,
                                "selected_library_ref_indices": selected_ref_indices,
                                "selected_library_refs": _ref_images_meta(selected_ref_images),
                                "rewrite_candidates": _ref_images_meta(rewrite_pool),
                                "rewrite_prefilter": rewrite_prefilter,
                                "selected_rewrite_ref_indices": selected_pool_indices or None,
                                "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                                "selection_refs": _ref_images_meta(selection_refs),
                                "issues": head_ref_issues,
                                "rewrite": rewritten,
                            }

                        head_meta = _generate_t2i_with_candidates(
                            adapter=local_t2i,
                            prompt=prompt_for_t2i,
                            negative_prompt=style_negative_prompt,
                            width=frame_width,
                            height=frame_height,
                            base_seed=head_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="head",
                            output_path=head_path,
                            candidate_count=candidate_count,
                            parallelism=candidate_parallelism,
                            selector=head_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=selection_refs if selection_refs else ref_images,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                        )

                head_meta.update(head_extra_meta)
                head_meta["selector_requested"] = selector
                head_meta["selector_effective"] = "multiperson_fusion" if head_via == "multiperson_fusion" else head_selector
                if head_via != "multiperson_fusion":
                    if head_selector_degraded_reason:
                        head_meta["selector_degraded_reason"] = head_selector_degraded_reason
                else:
                    head_meta["selector_degraded_reason"] = "not_applicable"
                if head_ref_issues:
                    head_meta["ref_issues"] = head_ref_issues
                head_meta["camera"] = {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}
                if variation_type:
                    head_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                head_frame = {
                    "path": str(head_path),
                    "ratio": str(head_spec.get("ratio") or frame_ratio),
                    "spec": head_spec,
                    "meta": {"role": "head", "via": head_via, "ref": head_ref, "decision": head_decision, **head_meta},
                }

                if skip_tail_small_variation and variation_type == "small" and head_path.exists():
                    tail_path.write_bytes(head_path.read_bytes())
                    tail_meta: Dict[str, Any] = {
                        "candidate_count": 0,
                        "selected": None,
                        "selector": "reuse_head",
                        "selector_requested": selector,
                        "selector_effective": "reuse_head",
                        "camera": {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source},
                    }
                    if variation_type:
                        tail_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                    tail_decision = {"mode": "reuse_head", "reason": "variation_type=small"}
                    tail_frame = {
                        "path": str(tail_path),
                        "ratio": str(tail_spec.get("ratio") or frame_ratio),
                        "spec": tail_spec,
                        "meta": {"role": "tail", "via": "reuse_head", "ref": None, "decision": tail_decision, **tail_meta},
                    }
                    return {"head": head_frame, "tail": tail_frame}

                tail_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
                tail_ref: Optional[Dict[str, Any]] = None
                tail_anchor_desc = f"本镜头{shot_id} 的head；prompt={(head_prompt or '')[:80]}"
                tail_anchor = {"path": head_path, "desc": tail_anchor_desc}
                tail_ref_pack, tail_ref_issues_raw = _build_reference_pack(anchor=tail_anchor, match=asset_match)
                tail_ref_issues = _normalize_ref_issues(tail_ref_issues_raw, require_anchor=True)
                tail_selector, tail_selector_degraded_reason = _selector_with_ref_issues(
                    selector,
                    vlm_adapter=local_vlm_adapter,
                    ref_issues=tail_ref_issues,
                )
                tail_edit_ref_pack = _drop_anchor_from_refs(tail_ref_pack, tail_anchor)
                tail_image_edit_adapter = local_image_edit_adapters.get(image_edit_adapter_name_tail)
                if use_tail_image_edit and tail_image_edit_adapter is None:
                    tail_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
                elif use_tail_image_edit:
                    if variation_driven_image_edit and variation_type == "large":
                        tail_decision = {"mode": "t2i", "reason": "variation_type=large"}
                    else:
                        tail_decision = _decide_image_mode(
                            policy=image_edit_policy,
                            base_image_path=head_path,
                            base_spec=head_spec,
                            target_spec=tail_spec,
                            base_visible_chars=ff_vis_char_ids,
                            target_visible_chars=lf_vis_char_ids,
                            max_subject_pos_delta=max_subject_pos_delta,
                            min_prompt_similarity=image_edit_min_prompt_similarity,
                            default_ratio=frame_ratio,
                        )

                if tail_decision.get("mode") == "image_edit" and tail_image_edit_adapter is not None:
                    tail_desc = tail_anchor_desc
                    tail_edit_prompt = tail_prompt or head_prompt
                    tail_rewrite = None
                    rewrite_pool = _build_rewrite_pool(anchor=None, drop={"path": head_path, "desc": tail_desc}, selection_refs=tail_edit_ref_pack)
                    rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                        rewrite_pool,
                        frame_description=tail_edit_prompt,
                        enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and tail_ref_rewrite and local_vlm_adapter is not None),
                    )
                    if ref_selector == "vlm" and tail_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_tail", 1)
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(rewrite_subset) + 1)
                        tail_rewrite = _vlm_build_edit_prompt_from_base_and_refs(
                            vlm_adapter=local_vlm_adapter,
                            base_image_path=head_path,
                            base_image_desc=tail_desc,
                            target_description=tail_edit_prompt,
                            reference_images=rewrite_subset,
                            max_refs=max_refs_for_edit,
                        )
                        if isinstance(tail_rewrite, dict) and isinstance(tail_rewrite.get("edit_prompt"), str):
                            tail_edit_prompt = str(tail_rewrite.get("edit_prompt") or tail_edit_prompt)

                    selected_pool_indices = _selected_pool_indices_from_pick(tail_rewrite, subset_to_pool)
                    selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                    if selected_library_indices:
                        selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                        selected_ref_indices: Optional[List[int]] = selected_library_indices
                    else:
                        selected_ref_images, selected_ref_indices = ref_images, None
                    selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]
                    selection_refs = tail_ref_pack
                    tail_ref = {
                        "base": {"uri": str(head_path), "desc": tail_desc},
                        "library_refs": library_refs_meta,
                        "selected_library_ref_indices": selected_ref_indices,
                        "selected_library_refs": _ref_images_meta(selected_ref_images),
                        "rewrite_candidates": _ref_images_meta(rewrite_pool),
                        "rewrite_prefilter": rewrite_prefilter,
                        "selected_rewrite_ref_indices": selected_pool_indices or None,
                        "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                        "selection_refs": _ref_images_meta(selection_refs),
                        "issues": tail_ref_issues,
                        "rewrite": tail_rewrite,
                    }

                    try:
                        tail_meta = _generate_edit_with_candidates(
                            adapter=tail_image_edit_adapter,
                            image_path=head_path,
                            edit_prompt=tail_edit_prompt,
                            reference_desc=tail_desc,
                            strength=image_edit_strength,
                            guidance_scale=image_edit_guidance,
                            base_seed=tail_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="tail",
                            output_path=tail_path,
                            candidate_count=image_edit_candidates,
                            parallelism=candidate_parallelism,
                            selector=tail_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=tail_edit_ref_pack,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                            use_multi_ref=image_edit_multi_ref_tail,
                            max_ref_images=image_edit_ref_max_images,
                        )
                        tail_via = "image_edit"
                    except Exception as exc:  # noqa: BLE001
                        tail_meta = _generate_t2i_with_candidates(
                            adapter=local_t2i,
                            prompt=tail_prompt,
                            negative_prompt=style_negative_prompt,
                            width=frame_width,
                            height=frame_height,
                            base_seed=tail_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="tail",
                            output_path=tail_path,
                            candidate_count=candidate_count,
                            parallelism=candidate_parallelism,
                            selector=tail_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=selection_refs if selection_refs else ref_images,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                        )
                        tail_meta["fallback_error"] = str(exc)
                        tail_via = "image_edit_fallback"
                else:
                    selection_refs = tail_ref_pack
                    if selection_refs or ref_images:
                        tail_ref = {
                            "base": {"uri": str(head_path), "desc": tail_anchor_desc},
                            "library_refs": library_refs_meta,
                            "selected_library_ref_indices": None,
                            "selected_library_refs": _ref_images_meta(ref_images),
                            "selection_refs": _ref_images_meta(selection_refs),
                            "issues": tail_ref_issues,
                            "rewrite": None,
                        }
                    tail_meta = _generate_t2i_with_candidates(
                        adapter=local_t2i,
                        prompt=tail_prompt,
                        negative_prompt=style_negative_prompt,
                        width=frame_width,
                        height=frame_height,
                        base_seed=tail_spec.get("seed"),
                        ctx=ctx,
                        shot_id=shot_id,
                        role="tail",
                        output_path=tail_path,
                        candidate_count=candidate_count,
                        parallelism=candidate_parallelism,
                        selector=tail_selector,
                        vlm_adapter=local_vlm_adapter,
                        vlm_criteria=vlm_criteria,
                        reference_images=selection_refs if selection_refs else ref_images,
                        keep_candidates=keep_candidates,
                        bypass_hash_cache=bypass_hash_cache,
                    )
                    tail_via = "t2i"

                tail_meta["selector_requested"] = selector
                tail_meta["selector_effective"] = tail_selector
                if tail_selector_degraded_reason:
                    tail_meta["selector_degraded_reason"] = tail_selector_degraded_reason
                if tail_ref_issues:
                    tail_meta["ref_issues"] = tail_ref_issues
                if semantic_retrieval:
                    tail_meta["semantic_retrieval"] = semantic_retrieval
                tail_meta["camera"] = {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}
                if variation_type:
                    tail_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                tail_frame = {
                    "path": str(tail_path),
                    "ratio": str(tail_spec.get("ratio") or frame_ratio),
                    "spec": tail_spec,
                    "meta": {"role": "tail", "via": tail_via, "ref": tail_ref, "decision": tail_decision, **tail_meta},
                }
                return {"head": head_frame, "tail": tail_frame}
            finally:
                _close_adapter_session(local_t2i)
                if local_image_edit_adapters:
                    closed: set[int] = set()
                    for item in local_image_edit_adapters.values():
                        if item is None:
                            continue
                        key = id(item)
                        if key in closed:
                            continue
                        closed.add(key)
                        _close_adapter_session(item)
                if local_vlm_adapter is not None:
                    _close_adapter_session(local_vlm_adapter)

        futures: Dict[Any, str] = {}
        with ThreadPoolExecutor(max_workers=keyframes_parallelism) as pool:
            while remaining or futures:
                submitted = True
                while submitted and len(futures) < keyframes_parallelism:
                    submitted = False
                    for shot_id, plan in list(remaining.items()):
                        deps = _as_str_list(plan.get("depends_on_state_ids"))
                        if any(dep not in completed for dep in deps):
                            continue
                        futures[pool.submit(_render_one, plan)] = shot_id
                        remaining.pop(shot_id, None)
                        submitted = True
                        break

                if not futures:
                    pending = [str(p.get("shot_id") or "") for p in plans if str(p.get("shot_id") or "") in remaining][:5]
                    raise RuntimeError(f"keyframes parallel scheduling stuck (pending={pending})")

                done_futs, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
                for fut in done_futs:
                    shot_id = futures.pop(fut)
                    results_by_shot[shot_id] = fut.result()
                    completed.add(shot_id)

        frames: List[Dict[str, Any]] = []
        for plan in plans:
            shot_id = str(plan.get("shot_id") or "")
            pair = results_by_shot.get(shot_id)
            if not isinstance(pair, dict) or not isinstance(pair.get("head"), dict) or not isinstance(pair.get("tail"), dict):
                raise RuntimeError(f"missing keyframes result for shot {shot_id}")
            frames.append(pair["head"])
            frames.append(pair["tail"])

        if semantic_index is not None:
            try:
                index_items = _semantic_index_items_from_frames(frames=frames, run_id=str(ctx.run_id), max_items=400)
                if index_items:
                    semantic_index.add_many(index_items)
            except Exception:  # noqa: BLE001
                pass

        camera_states = ctx.payload.get("camera_states")
        if not isinstance(camera_states, list) or not camera_states:
            camera_states = build_camera_states(
                storyboard if isinstance(storyboard, list) else [],
                camera_tree if isinstance(camera_tree, list) and camera_tree else None,
            )

        head_by_shot_id: Dict[str, Dict[str, Any]] = {}
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            meta = frame.get("meta") if isinstance(frame.get("meta"), dict) else {}
            if meta.get("role") != "head":
                continue
            path = frame.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            stem = Path(path).stem
            shot_key = stem[: -len("_head")] if stem.endswith("_head") else stem
            if shot_key and shot_key not in head_by_shot_id:
                head_by_shot_id[shot_key] = frame

        camera_scenes: List[Dict[str, Any]] = []
        for track in camera_states:
            if not isinstance(track, dict) or not isinstance(track.get("cam_idx"), int):
                continue
            cam_idx = int(track["cam_idx"])
            shot_id = str(track.get("first_state_id") or "").strip()
            if not shot_id:
                continue
            head = head_by_shot_id.get(shot_id)
            if not isinstance(head, dict):
                continue

            meta = head.get("meta") if isinstance(head.get("meta"), dict) else {}
            camera_meta = meta.get("camera") if isinstance(meta.get("camera"), dict) else {}
            ref_meta = meta.get("ref") if isinstance(meta.get("ref"), dict) else {}
            base_ref = ref_meta.get("base") if isinstance(ref_meta.get("base"), dict) else {}

            states = track.get("states") if isinstance(track.get("states"), list) else []
            shot_pos = None
            if states and isinstance(states[0], dict):
                sp = states[0].get("shot_pos")
                if isinstance(sp, int):
                    shot_pos = int(sp)

            parent_cam_idx = track.get("parent_cam_idx")
            parent_shot_id = track.get("parent_shot_id")
            camera_scenes.append(
                {
                    "cam_idx": cam_idx,
                    "shot_id": shot_id,
                    "shot_pos": shot_pos,
                    "scene_uri": str(head.get("path") or ""),
                    "via": str(meta.get("via") or "").strip() or None,
                    "anchor_source": str(camera_meta.get("anchor_source") or "").strip() or None,
                    "anchor_base_uri": str(base_ref.get("uri") or "").strip() or None,
                    "parent_cam_idx": int(parent_cam_idx) if isinstance(parent_cam_idx, int) else None,
                    "parent_shot_id": str(parent_shot_id).strip() if isinstance(parent_shot_id, str) and parent_shot_id.strip() else None,
                }
            )

        if camera_scenes:
            ctx.payload["camera_scenes"] = camera_scenes

        ctx.payload["keyframes"] = frames
        if semantic_index is not None:
            semantic_index.close()
        return

    ctx.payload["keyframes"] = []
    if semantic_index is not None:
        semantic_index.close()
    return


def run_midframes(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    adapter = "wan_t2i"
    run_dir = _ensure_run_dir(ctx)

    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    video_engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "").strip().lower()
    if video_engine in {"wan_i2v", "i2v", "wan_t2v", "wan26_t2v", "t2v", "wan_auto", "auto"}:
        # Wan2.6 视频生成（I2V/T2V）不会用到 midframes；跳过以减少成本与耗时。
        ctx.payload["midframes"] = []
        return

    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_width, frame_height, frame_ratio = resolve_frame_size(image_cfg)

    t2i_candidates = _cfg_int(image_cfg, "t2i_candidates", env_name="DREAMWEAVER_T2I_CANDIDATES", default=1)
    candidate_count = _cfg_int(image_cfg, "mid_candidates", env_name="DREAMWEAVER_MID_CANDIDATES", default=t2i_candidates)
    candidate_parallelism = _cfg_int(
        image_cfg,
        "candidate_parallelism",
        env_name="DREAMWEAVER_CANDIDATE_PARALLELISM",
        default=0,
    )
    if candidate_parallelism <= 0:
        candidate_parallelism = 2 if candidate_count > 1 else 1
    candidate_parallelism = max(1, min(int(candidate_parallelism), int(candidate_count)))
    image_edit_policy = _cfg_str(
        image_cfg,
        "image_edit_policy",
        env_name="DREAMWEAVER_IMAGE_EDIT_POLICY",
        default="auto",
    ).strip().lower()
    image_edit_min_prompt_similarity = _cfg_float(
        image_cfg,
        "image_edit_min_prompt_similarity",
        env_name="DREAMWEAVER_IMAGE_EDIT_MIN_PROMPT_SIMILARITY",
        default=0.0,
    )
    image_edit_min_prompt_similarity = max(0.0, min(float(image_edit_min_prompt_similarity), 1.0))
    image_edit_candidates = _cfg_int(
        image_cfg,
        "image_edit_candidates",
        env_name="DREAMWEAVER_IMAGE_EDIT_CANDIDATES",
        default=0,
    )
    if image_edit_candidates <= 0:
        image_edit_candidates = 1 if candidate_count <= 1 else min(2, int(candidate_count))
    image_edit_candidates = max(1, min(int(image_edit_candidates), int(candidate_count)))
    selector = _cfg_str(image_cfg, "image_selector", env_name="DREAMWEAVER_IMAGE_SELECTOR", default="first").strip().lower()
    keep_candidates = _cfg_flag(image_cfg, "keep_candidates", env_name="DREAMWEAVER_KEEP_CANDIDATES", default=False)
    max_refs = _cfg_int(image_cfg, "ref_max_images", env_name="DREAMWEAVER_REF_MAX_IMAGES", default=8)
    ref_selector = _cfg_str(image_cfg, "ref_selector", env_name="DREAMWEAVER_REF_SELECTOR", default="recent").strip().lower()
    mid_ref_rewrite = _cfg_flag(image_cfg, "mid_ref_rewrite", env_name="DREAMWEAVER_MID_REF_REWRITE", default=True)
    mid_min_variation = _cfg_str(image_cfg, "mid_min_variation", env_name="DREAMWEAVER_MID_MIN_VARIATION", default="medium").strip().lower()
    if mid_min_variation not in {"small", "medium", "large"}:
        mid_min_variation = "small"
    mid_min_variation_rank = {"small": 0, "medium": 1, "large": 2}.get(mid_min_variation, 0)

    use_mid_image_edit = _cfg_flag(image_cfg, "mid_use_image_edit", env_name="DREAMWEAVER_MID_USE_IMAGE_EDIT", default=False)
    image_edit_adapter_name_mid = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_mid",
        default_adapter="wan_image_edit",
    )
    image_edit_multi_ref_mid = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_mid,
    )
    image_edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg)
    max_refs_for_edit = max_refs
    if _is_qwen_image_edit_adapter_name(image_edit_adapter_name_mid):
        max_refs_for_edit = min(int(max_refs_for_edit), 2)
        image_edit_ref_max_images = min(int(image_edit_ref_max_images), 2)
    image_edit_adapter = None
    if use_mid_image_edit:
        image_edit_adapter = image_edit_adapter_name_mid if _model_client_available(image_edit_adapter_name_mid) else None

    vlm_adapter = None
    if selector in {"vlm", "semantic"} or ref_selector == "vlm":
        candidate_vlm = str(os.getenv("DREAMWEAVER_VLM_ADAPTER", "qwen3_vl_plus") or "").strip() or "qwen3_vl_plus"
        vlm_adapter = candidate_vlm if _model_client_available(candidate_vlm) else None
    vlm_criteria = [
        s.strip()
        for s in os.getenv("DREAMWEAVER_VLM_CRITERIA", "clarity,composition,lighting,color,style").split(",")
        if s.strip()
    ]

    image_edit_strength = _cfg_float(image_cfg, "image_edit_strength", env_name="DREAMWEAVER_IMAGE_EDIT_STRENGTH", default=0.65)
    image_edit_guidance = _cfg_float(image_cfg, "image_edit_guidance", env_name="DREAMWEAVER_IMAGE_EDIT_GUIDANCE", default=7.5)

    style_prompt = str(ctx.payload.get("style_prompt") or "").strip() or "写实风格，电影质感，光影真实，高清细节，统一风格"
    style_negative_prompt = str(ctx.payload.get("style_negative_prompt") or "").strip()
    lib_assets = _library_assets_from_payload(ctx.payload)

    regen_shots_raw = ctx.payload.get("regenerate_shot_ids")
    regen_shots: List[str] = []
    if isinstance(regen_shots_raw, list):
        for item in regen_shots_raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in regen_shots:
                continue
            regen_shots.append(s)
            if len(regen_shots) >= 200:
                break
    regen_shot_set = set(regen_shots)

    existing_mid_by_shot: Dict[str, Dict[str, Any]] = {}
    existing_mid_raw = ctx.payload.get("midframes")
    if not isinstance(existing_mid_raw, list):
        existing_mid_raw = []
    for f in existing_mid_raw:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        p = Path(path)
        stem = p.stem
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not stem.endswith("_mid"):
            continue
        shot_key = stem[: -len("_mid")]
        if shot_key:
            existing_mid_by_shot[shot_key] = f

    mids: List[Dict[str, Any]] = []
    for item in ctx.payload.get("storyboard", []):
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id:
            continue
        shot_variation = str(item.get("variation_type") or "").strip().lower()
        shot_variation_rank = {"small": 0, "medium": 1, "large": 2}.get(shot_variation, 99)
        if shot_variation_rank < mid_min_variation_rank:
            continue
        ff_vis_char_ids = _as_str_list(item.get("ff_vis_char_ids"))
        mid_path = run_dir / f"{shot_id}_mid.png"
        if regen_shot_set and shot_id not in regen_shot_set:
            existing_mid = existing_mid_by_shot.get(shot_id)
            if isinstance(existing_mid, dict) and mid_path.exists():
                mids.append(existing_mid)
                continue
        bypass_hash_cache = bool(regen_shot_set and shot_id in regen_shot_set)
        prompt = str(item.get("desc") or "")
        asset_match = _match_library_assets_for_shot(
            shot=item,
            library_assets=lib_assets,
            max_character_refs=min(4, int(max_refs)),
        )
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        ref_images: List[Dict[str, Any]] = []
        for asset in (
            (asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else [])
            + (asset_match.get("scene_assets") if isinstance(asset_match.get("scene_assets"), list) else [])
            + (asset_match.get("prop_assets") if isinstance(asset_match.get("prop_assets"), list) else [])
        ):
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if not isinstance(path, Path) or not path.exists():
                continue
            ref_images.append({"path": path, "desc": str(asset.get("desc") or "").strip()})
            if len(ref_images) >= max(0, int(max_refs)):
                break
        library_refs_meta = _ref_images_meta(ref_images)
        mid_spec: Dict[str, Any] = {
            "prompt": f"{prompt}，过渡帧，{style_prompt}，{frame_ratio}",
            "ratio": frame_ratio,
            "subject_pos": {"x": 0.5, "y": 0.5},
        }
        base_prompt = prompt
        head_frame = item.get("head_frame")
        if isinstance(head_frame, dict) and head_frame.get("prompt"):
            base_prompt = str(head_frame.get("prompt") or prompt)
        mid_spec["prompt"] = _apply_prompt_fragment(
            f"{base_prompt}，中间过渡帧，{style_prompt}，{frame_ratio}",
            prompt_fragment,
        )
        head_path = run_dir / f"{shot_id}_head.png"
        mid_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
        mid_ref: Optional[Dict[str, Any]] = None
        mid_anchor_desc = f"本镜头 {shot_id} 的 head；prompt={base_prompt[:80]}"
        mid_anchor = {"path": head_path, "desc": mid_anchor_desc}
        mid_anchor_for_pack = mid_anchor if head_path.exists() else None
        mid_ref_pack, mid_ref_issues_raw = _build_reference_pack(anchor=mid_anchor_for_pack, match=asset_match)
        mid_ref_issues = _normalize_ref_issues(mid_ref_issues_raw, require_anchor=bool(mid_anchor_for_pack))
        mid_selector, mid_selector_degraded_reason = _selector_with_ref_issues(
            selector,
            vlm_adapter=vlm_adapter,
            ref_issues=mid_ref_issues,
        )
        mid_edit_ref_pack = _drop_anchor_from_refs(mid_ref_pack, mid_anchor_for_pack)
        if use_mid_image_edit and image_edit_adapter is None:
            mid_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
        elif use_mid_image_edit:
            mid_decision = _decide_image_mode(
                policy=image_edit_policy,
                base_image_path=head_path,
                base_spec=head_frame if isinstance(head_frame, dict) else None,
                target_spec=mid_spec,
                base_visible_chars=ff_vis_char_ids,
                target_visible_chars=ff_vis_char_ids,
                max_subject_pos_delta=0.0,
                min_prompt_similarity=image_edit_min_prompt_similarity,
                default_ratio=frame_ratio,
            )

        if mid_decision.get("mode") == "image_edit" and image_edit_adapter is not None and head_path.exists():
            mid_desc = mid_anchor_desc
            mid_edit_prompt = str(mid_spec["prompt"])
            mid_rewrite = None
            if ref_selector == "vlm" and mid_ref_rewrite and vlm_adapter is not None and ref_images:
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_mid", 1)
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(ref_images) + 1)
                mid_rewrite = _vlm_build_edit_prompt_from_base_and_refs(
                    vlm_adapter=vlm_adapter,
                    base_image_path=head_path,
                    base_image_desc=mid_desc,
                    target_description=mid_edit_prompt,
                    reference_images=ref_images,
                    max_refs=max_refs_for_edit,
                )
                if isinstance(mid_rewrite, dict) and isinstance(mid_rewrite.get("edit_prompt"), str):
                    mid_edit_prompt = str(mid_rewrite.get("edit_prompt") or mid_edit_prompt)

            selected_ref_images, selected_ref_indices = _selected_ref_images_from_pick(ref_images, mid_rewrite)
            selection_refs = mid_ref_pack
            mid_ref = {
                "base": {"uri": str(head_path), "desc": mid_desc},
                "library_refs": library_refs_meta,
                "selected_library_ref_indices": selected_ref_indices,
                "selected_library_refs": _ref_images_meta(selected_ref_images),
                "selection_refs": _ref_images_meta(selection_refs),
                "issues": mid_ref_issues,
                "rewrite": mid_rewrite,
            }
            try:
                mid_meta = _generate_edit_with_candidates(
                    adapter=image_edit_adapter,
                    image_path=head_path,
                    edit_prompt=mid_edit_prompt,
                    reference_desc=mid_desc,
                    strength=image_edit_strength,
                    guidance_scale=image_edit_guidance,
                    base_seed=None,
                    ctx=ctx,
                    shot_id=shot_id,
                    role="mid",
                    output_path=mid_path,
                    candidate_count=image_edit_candidates,
                    parallelism=candidate_parallelism,
                    selector=mid_selector,
                    vlm_adapter=vlm_adapter,
                    vlm_criteria=vlm_criteria,
                    reference_images=mid_edit_ref_pack,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                    use_multi_ref=image_edit_multi_ref_mid,
                    max_ref_images=image_edit_ref_max_images,
                )
            except Exception as exc:  # noqa: BLE001
                mid_meta = _generate_t2i_with_candidates(
                    adapter=adapter,
                    prompt=str(mid_spec["prompt"]),
                    negative_prompt=style_negative_prompt,
                    width=frame_width,
                    height=frame_height,
                    base_seed=None,
                    ctx=ctx,
                    shot_id=shot_id,
                    role="mid",
                    output_path=mid_path,
                    candidate_count=candidate_count,
                    parallelism=candidate_parallelism,
                    selector=mid_selector,
                    vlm_adapter=vlm_adapter,
                    vlm_criteria=vlm_criteria,
                    reference_images=selection_refs if selection_refs else ref_images,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                )
                mid_meta["fallback_error"] = str(exc)
        else:
            selection_refs = mid_ref_pack
            if selection_refs or ref_images:
                mid_ref = {
                    "base": {"uri": str(head_path), "desc": mid_anchor_desc} if head_path.exists() else None,
                    "library_refs": library_refs_meta,
                    "selected_library_ref_indices": None,
                    "selected_library_refs": _ref_images_meta(ref_images),
                    "selection_refs": _ref_images_meta(selection_refs),
                    "issues": mid_ref_issues,
                    "rewrite": None,
                }
            mid_meta = _generate_t2i_with_candidates(
                adapter=adapter,
                prompt=str(mid_spec["prompt"]),
                negative_prompt=style_negative_prompt,
                width=frame_width,
                height=frame_height,
                base_seed=None,
                ctx=ctx,
                shot_id=shot_id,
                role="mid",
                output_path=mid_path,
                candidate_count=candidate_count,
                parallelism=candidate_parallelism,
                selector=mid_selector,
                vlm_adapter=vlm_adapter,
                vlm_criteria=vlm_criteria,
                reference_images=selection_refs if selection_refs else ref_images,
                keep_candidates=keep_candidates,
                bypass_hash_cache=bypass_hash_cache,
            )

        mid_meta["selector_requested"] = selector
        mid_meta["selector_effective"] = mid_selector
        if mid_selector_degraded_reason:
            mid_meta["selector_degraded_reason"] = mid_selector_degraded_reason
        if mid_ref_issues:
            mid_meta["ref_issues"] = mid_ref_issues
        if shot_variation in {"small", "medium", "large"}:
            mid_meta["variation"] = {
                "type": shot_variation,
                "reason": str(item.get("variation_reason") or "").replace("\n", " ").strip(),
            }
        mids.append(
            {
                "path": str(mid_path),
                "ratio": frame_ratio,
                "spec": mid_spec,
                "meta": {"role": "mid", "ref": mid_ref, "decision": mid_decision, **mid_meta},
            }
        )
    ctx.payload["midframes"] = mids

    semantic_index = None
    try:
        from agents.semantic_asset_index import SemanticAssetIndex, is_semantic_retrieval_enabled, semantic_retrieval_config

        project_id = int(ctx.payload.get("project_id") or 0)
        if project_id > 0 and mids and is_semantic_retrieval_enabled(image_cfg=image_cfg):
            semantic_cfg = semantic_retrieval_config(image_cfg)
            semantic_index = SemanticAssetIndex(
                project_id=project_id,
                db_path=Path(semantic_cfg["db_path"]),
                dim=int(semantic_cfg.get("dim") or 256),
                max_items_per_project=int(semantic_cfg.get("max_items_per_project") or 5000),
                text_max_chars=int(semantic_cfg.get("text_max_chars") or 800),
            )
            index_items = _semantic_index_items_from_frames(frames=mids, run_id=str(ctx.run_id), max_items=400)
            if index_items:
                semantic_index.add_many(index_items)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if semantic_index is not None:
            semantic_index.close()
