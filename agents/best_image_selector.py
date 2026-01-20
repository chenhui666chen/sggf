from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agents.vlm_utils import clamp_prompt_text, clamp_text_list, file_to_data_url, vlm_chat_json


def _bump(bump_telemetry: Optional[Callable[[str, int], None]], name: str, delta: int = 1) -> None:
    if bump_telemetry is None or not name:
        return
    try:
        bump_telemetry(str(name), int(delta))
    except Exception:  # noqa: BLE001
        return


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:  # noqa: BLE001
        return float(default)


def _clamp_01(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except Exception:  # noqa: BLE001
        return None
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _weighted_total(scores: Dict[str, Any], weights: Dict[str, float]) -> Optional[float]:
    if not isinstance(scores, dict):
        return None
    total = 0.0
    used = 0.0
    for key, w in (weights or {}).items():
        v = _clamp_01(scores.get(key))
        if v is None:
            continue
        wv = float(w)
        if wv <= 0.0:
            continue
        total += v * wv
        used += wv
    if used <= 0.0:
        return None
    return total / used


def _normalize_director_scores(scores: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(scores, dict):
        return {}
    out: Dict[str, Any] = dict(scores)
    overall = out.get("overall")
    if overall is None:
        overall = out.get("overall_score")

    # 向后兼容：旧版语义输出字段（character_consistency/spatial_consistency/description_accuracy/overall）
    if out.get("quality") is None and overall is not None:
        out["quality"] = overall
    if out.get("scene_style_consistency") is None:
        if out.get("style_consistency") is not None:
            out["scene_style_consistency"] = out.get("style_consistency")
        elif out.get("spatial_consistency") is not None:
            out["scene_style_consistency"] = out.get("spatial_consistency")
        elif overall is not None:
            out["scene_style_consistency"] = overall
    if out.get("transition_consistency") is None:
        if out.get("spatial_consistency") is not None:
            out["transition_consistency"] = out.get("spatial_consistency")
        elif overall is not None:
            out["transition_consistency"] = overall
    if out.get("description_accuracy") is None and out.get("accuracy") is not None:
        out["description_accuracy"] = out.get("accuracy")

    return out


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


def _vlm_select_best_candidate_semantic(
    *,
    vlm_adapter: Any,
    target_description: str,
    candidate_paths: List[Path],
    reference_images: Optional[List[Dict[str, Any]]] = None,
    bump_telemetry: Optional[Callable[[str, int], None]] = None,
) -> Optional[Dict[str, Any]]:
    if not target_description or not candidate_paths:
        return None

    weights = {
        "quality": 0.25,
        "character_consistency": 0.30,
        "scene_style_consistency": 0.20,
        "transition_consistency": 0.15,
        "description_accuracy": 0.10,
    }
    pass_threshold = _env_float("DREAMWEAVER_DIRECTOR_PASS_THRESHOLD", 0.72)
    min_quality = _env_float("DREAMWEAVER_DIRECTOR_MIN_QUALITY", 0.55)
    min_character = _env_float("DREAMWEAVER_DIRECTOR_MIN_CHARACTER", 0.60)
    min_scene = _env_float("DREAMWEAVER_DIRECTOR_MIN_SCENE", 0.55)
    min_transition = _env_float("DREAMWEAVER_DIRECTOR_MIN_TRANSITION", 0.50)
    min_desc = _env_float("DREAMWEAVER_DIRECTOR_MIN_DESCRIPTION", 0.60)

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

    system_prompt += (
        "\n额外要求：输出 JSON 时尽量包含 candidate_scores(list) 与 suggestions(list)。"
        "candidate_scores 的每一项包含 index 与 scores，scores 至少给出 "
        "quality/character_consistency/scene_style_consistency/transition_consistency/description_accuracy（0~1）。"
    )
    system_prompt += (
        "\nOutput JSON only. Keep reason <= 120 chars; issues/suggestions <= 6 items; each item <= 120 chars."
    )

    content: List[Dict[str, Any]] = []
    image_count = 0
    if reference_images:
        for idx, ref in enumerate(reference_images):
            path = ref.get("path")
            desc = str(ref.get("desc") or "").strip()
            if not isinstance(path, Path) or not path.exists():
                continue
            content.append({"type": "text", "text": f"参考图 {idx}: {desc}"})
            content.append({"type": "image_url", "image_url": {"url": file_to_data_url(path)}})
            image_count += 1

    for idx, path in enumerate(candidate_paths):
        content.append({"type": "text", "text": f"候选图 {idx}"})
        content.append({"type": "image_url", "image_url": {"url": file_to_data_url(path)}})
        image_count += 1

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

    _bump(bump_telemetry, "vlm_semantic_selector_calls", 1)
    _bump(bump_telemetry, "vlm_semantic_selector_images", image_count)
    obj = vlm_chat_json(vlm_adapter=vlm_adapter, messages=messages, temperature=0.2, max_tokens=700)
    if not isinstance(obj, dict):
        return None

    best_idx = obj.get("best_image_index")
    reason = clamp_prompt_text(str(obj.get("reason") or "").strip(), limit=160)
    if not isinstance(best_idx, int) or best_idx < 0 or best_idx >= len(candidate_paths):
        return None

    issues_raw = obj.get("issues") if isinstance(obj.get("issues"), list) else []
    issues_list = clamp_text_list(issues_raw, max_items=8, max_chars=120)

    suggestions_raw = obj.get("suggestions") if isinstance(obj.get("suggestions"), list) else []
    suggestions = clamp_text_list(suggestions_raw, max_items=6, max_chars=120)

    candidate_scores_raw = obj.get("candidate_scores") if isinstance(obj.get("candidate_scores"), list) else []
    candidate_scores: List[Dict[str, Any]] = []
    for item in candidate_scores_raw:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidate_paths):
            continue
        sc_raw = item.get("scores") if isinstance(item.get("scores"), dict) else {}
        sc = _normalize_director_scores(sc_raw)
        item_issues_raw = item.get("issues") if isinstance(item.get("issues"), list) else []
        item_issues = clamp_text_list(item_issues_raw, max_items=8, max_chars=120)
        total = _weighted_total(sc, weights)
        candidate_scores.append({"index": int(idx), "scores": sc, "issues": item_issues, "total": total})

    scores_raw: Dict[str, Any] = obj.get("scores") if isinstance(obj.get("scores"), dict) else {}
    scores: Dict[str, Any] = _normalize_director_scores(scores_raw)
    if candidate_scores:
        best_by_total = max(
            candidate_scores,
            key=lambda c: float(c.get("total") if isinstance(c.get("total"), (int, float)) else float("-inf")),
        )
        if isinstance(best_by_total.get("index"), int):
            best_idx = int(best_by_total["index"])
            scores = best_by_total.get("scores") if isinstance(best_by_total.get("scores"), dict) else scores

    best_total = _weighted_total(scores, weights)
    fail_reasons: List[str] = []
    pass_ = True
    if best_total is None:
        pass_ = False
        fail_reasons.append("missing_weighted_scores")
    elif float(best_total) < float(pass_threshold):
        pass_ = False
        fail_reasons.append("total_below_threshold")

    q = _clamp_01(scores.get("quality"))
    if q is not None and q < float(min_quality):
        pass_ = False
        fail_reasons.append("quality_below_min")
    cc = _clamp_01(scores.get("character_consistency"))
    if cc is not None and cc < float(min_character):
        pass_ = False
        fail_reasons.append("character_consistency_below_min")
    sc_ = _clamp_01(scores.get("scene_style_consistency"))
    if sc_ is not None and sc_ < float(min_scene):
        pass_ = False
        fail_reasons.append("scene_style_consistency_below_min")
    tc = _clamp_01(scores.get("transition_consistency"))
    if tc is not None and tc < float(min_transition):
        pass_ = False
        fail_reasons.append("transition_consistency_below_min")
    da = _clamp_01(scores.get("description_accuracy"))
    if da is not None and da < float(min_desc):
        pass_ = False
        fail_reasons.append("description_accuracy_below_min")

    director = {
        "pass": bool(pass_),
        "threshold": float(pass_threshold),
        "total": float(best_total) if best_total is not None else None,
        "weights": weights,
        "min": {
            "quality": float(min_quality),
            "character_consistency": float(min_character),
            "scene_style_consistency": float(min_scene),
            "transition_consistency": float(min_transition),
            "description_accuracy": float(min_desc),
        },
        "fail_reasons": fail_reasons,
        "issues": issues_list,
        "suggestions": suggestions,
    }
    return {
        "best_index": best_idx,
        "reason": reason,
        "scores": scores,
        "issues": issues_list,
        "candidate_scores": candidate_scores,
        "director": director,
    }


def select_best_candidate(
    *,
    candidate_paths: List[Path],
    selector: str,
    vlm_adapter: Any,
    vlm_criteria: List[str],
    target_description: Optional[str] = None,
    reference_images: Optional[List[Dict[str, Any]]] = None,
    bump_telemetry: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, Any]:
    selector = (selector or "first").strip().lower()
    if not candidate_paths:
        raise ValueError("candidate_paths empty")

    if selector == "first" or len(candidate_paths) == 1:
        return {"best_index": 0, "reason": "first", "scores": []}

    if selector == "semantic" and vlm_adapter is not None:
        semantic = _vlm_select_best_candidate_semantic(
            vlm_adapter=vlm_adapter,
            target_description=str(target_description or ""),
            candidate_paths=candidate_paths,
            reference_images=reference_images,
            bump_telemetry=bump_telemetry,
        )
        if isinstance(semantic, dict) and isinstance(semantic.get("best_index"), int):
            return {
                "best_index": int(semantic["best_index"]),
                "reason": "semantic",
                "scores": [
                    {
                        "reason": semantic.get("reason"),
                        "scores": semantic.get("scores"),
                        "issues": semantic.get("issues"),
                        "candidate_scores": semantic.get("candidate_scores"),
                        "director": semantic.get("director"),
                    }
                ],
            }
        selector = "vlm"

    if selector == "vlm" and vlm_adapter is not None:
        _bump(bump_telemetry, "vlm_analyze_image_calls", len(candidate_paths))
        _bump(bump_telemetry, "vlm_analyze_image_images", len(candidate_paths))
        scores: List[Dict[str, Any]] = []
        best_index = 0
        best_score = float("-inf")
        for idx, path in enumerate(candidate_paths):
            score_value = float("-inf")
            try:
                result = vlm_adapter.analyze_image(
                    image_path=str(path),
                    analysis_type="quality",
                    criteria=vlm_criteria,
                )
                score = _extract_score(result.data) if getattr(result, "success", False) else None
                score_value = float(score) if score is not None else float("-inf")
                scores.append(
                    {
                        "index": idx,
                        "score": score,
                        "data": result.data if getattr(result, "success", False) else None,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                scores.append({"index": idx, "score": None, "error": str(exc)})

            if score_value > best_score:
                best_score = score_value
                best_index = idx

        if best_score != float("-inf"):
            return {"best_index": best_index, "reason": "vlm", "scores": scores}

        selector = "file_size"

    if selector == "file_size":
        sizes = []
        for idx, path in enumerate(candidate_paths):
            try:
                sizes.append({"index": idx, "bytes": int(path.stat().st_size)})
            except Exception:  # noqa: BLE001
                sizes.append({"index": idx, "bytes": 0})
        best = max(sizes, key=lambda x: x["bytes"])
        return {"best_index": int(best["index"]), "reason": "file_size", "scores": sizes}

    return {"best_index": 0, "reason": "default_first", "scores": []}
