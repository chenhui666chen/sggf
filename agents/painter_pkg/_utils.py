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
    is_dreamweaver_generated_video_engine,
    normalize_dreamweaver_video_engine,
    ensure_media_payload,
    normalize_frame_ratio,
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


def _resolve_runtime_model_id(
    cfg: Dict[str, Any],
    *,
    key: str,
    env_name: str,
    default: str,
    require_available: bool = False,
) -> Optional[str]:
    candidate = _cfg_str(cfg, key, env_name=env_name, default=default).strip()
    if not candidate:
        return None
    if require_available and not _model_client_available(candidate):
        return None
    return candidate


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

