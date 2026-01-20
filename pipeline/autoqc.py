from __future__ import annotations

import base64
import json
import os
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.vlm_utils import clamp_text_list


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3_vl_plus"
DEFAULT_SEMANTIC_FRAMES = "both"  # head|tail|both
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0  # 0 表示不设上限（保持历史行为）
DEFAULT_SEMANTIC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0  # 0 表示不设上限（与 semantic_max_checks 一致语义）
DEFAULT_STATE_QC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_REQUIRE_I2V = None  # None=auto; True/False=force


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _stable_hash01(*parts: str) -> float:
    payload = "|".join([p for p in parts if p is not None]).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return float(value / 18446744073709551615)  # 2^64-1


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _is_wan_i2v_configured() -> bool:
    api_key = str(os.getenv("WAN_I2V_API_KEY") or "").strip()
    base_url = str(os.getenv("WAN_I2V_BASE_URL") or "").strip()
    model = (
        str(os.getenv("WAN_I2V_MODEL_NAME") or "").strip()
        or str(os.getenv("WAN_I2V_MODEL_ID") or "").strip()
        or str(os.getenv("WAN_I2V_MODEL") or "").strip()
    )
    return bool(api_key and base_url and model)


def _parse_role_from_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()

    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        if stem.endswith("_head"):
            return stem[: -len("_head")], "head"
        if stem.endswith("_tail"):
            return stem[: -len("_tail")], "tail"
        if stem.endswith("_mid"):
            return stem[: -len("_mid")], "mid"
        return None, None

    if suffix in {".mp4", ".mov", ".mkv"}:
        return stem, "clip"

    return None, None


def _index_assets(payload: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    by_shot: Dict[str, Dict[str, str]] = {}

    def push(path: Any) -> None:
        if not isinstance(path, str):
            return
        shot_key, role = _parse_role_from_path(path)
        if not shot_key or not role:
            return
        by_shot.setdefault(shot_key, {})[role] = path

    for item in payload.get("keyframes") or []:
        if isinstance(item, dict):
            push(item.get("path"))
    for item in payload.get("midframes") or []:
        if isinstance(item, dict):
            push(item.get("path"))
    for item in payload.get("video_clips") or []:
        if isinstance(item, dict):
            push(item.get("path"))

    return by_shot


def _file_exists(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:  # noqa: BLE001
        return False


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


def _semantic_frames_list(semantic_frames: str) -> List[str]:
    frames = str(semantic_frames or "").strip().lower()
    if frames == "head":
        return ["head"]
    if frames == "tail":
        return ["tail"]
    return ["head", "tail"]


def _normalize_state_text(value: Any, *, limit: int = 120) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if limit > 0 and len(text) > int(limit):
        text = text[: int(limit)]
    return text


def _plan_state_checks(
    *,
    run_id: str,
    shot_order: List[str],
    candidate_pairs: List[Dict[str, Any]],
    shot_items_by_key: Dict[str, Dict[str, Any]],
    base_shots: Dict[str, AutoQCShotReport],
    enable_state_qc: bool,
    state_strategy: str,
    state_sample_rate: float,
    state_max_checks: int,
    state_always_first: bool,
    state_always_last: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    状态连续性 QC 成本控制（按“镜头对”计数）。
    返回：计划检查列表（每项包含 prev_shot_key/next_shot_key/kinds/camera?）以及计划检查次数（按 pair 计数）。
    """
    if not enable_state_qc:
        return [], 0
    if not shot_order or len(shot_order) < 2:
        return [], 0

    strategy = str(state_strategy or "").strip().lower()
    if strategy not in {"priority", "sample", "all"}:
        strategy = DEFAULT_STATE_QC_STRATEGY

    budget = int(state_max_checks) if state_max_checks and int(state_max_checks) > 0 else 1_000_000

    planned: List[Dict[str, Any]] = []
    planned_pairs: set[tuple[str, str]] = set()
    checks_done = 0

    def _pair_has_state(prev_key: str, next_key: str) -> bool:
        prev = shot_items_by_key.get(prev_key) if prev_key else None
        next_ = shot_items_by_key.get(next_key) if next_key else None
        if not isinstance(prev, dict) or not isinstance(next_, dict):
            return False
        a = _normalize_state_text(prev.get("state_after"))
        b = _normalize_state_text(next_.get("state_before"))
        return bool(a or b)

    def _alloc(prev_key: str, next_key: str, item: Dict[str, Any]) -> None:
        nonlocal checks_done
        if checks_done >= budget:
            return
        if not prev_key or not next_key:
            return
        key = (prev_key, next_key)
        if key in planned_pairs:
            return
        if not _pair_has_state(prev_key, next_key):
            return
        planned.append(item)
        planned_pairs.add(key)
        checks_done += 1

    first_pair = (shot_order[0], shot_order[1]) if len(shot_order) >= 2 else ("", "")
    last_pair = (shot_order[-2], shot_order[-1]) if len(shot_order) >= 2 else ("", "")

    candidates_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for cand in candidate_pairs:
        if not isinstance(cand, dict):
            continue
        prev_key = str(cand.get("prev_shot_key") or "").strip()
        next_key = str(cand.get("next_shot_key") or "").strip()
        if not prev_key or not next_key:
            continue
        pair_key = (prev_key, next_key)
        existing = candidates_by_pair.get(pair_key)
        if existing is None:
            candidates_by_pair[pair_key] = cand
            continue
        kinds = existing.get("kinds")
        if not isinstance(kinds, list):
            kinds = []
        for k in cand.get("kinds") if isinstance(cand.get("kinds"), list) else []:
            if isinstance(k, str) and k and k not in kinds:
                kinds.append(k)
        if kinds:
            existing["kinds"] = kinds
        if not isinstance(existing.get("camera"), dict) and isinstance(cand.get("camera"), dict):
            existing["camera"] = cand["camera"]

    if state_always_first and first_pair[0] and first_pair[1]:
        item = candidates_by_pair.get(first_pair) or {"prev_shot_key": first_pair[0], "next_shot_key": first_pair[1], "kinds": ["adjacent"]}
        _alloc(first_pair[0], first_pair[1], item)
    if state_always_last and last_pair[0] and last_pair[1] and last_pair != first_pair:
        item = candidates_by_pair.get(last_pair) or {"prev_shot_key": last_pair[0], "next_shot_key": last_pair[1], "kinds": ["adjacent"]}
        _alloc(last_pair[0], last_pair[1], item)

    if strategy == "all":
        for prev_key, next_key in candidates_by_pair.keys():
            item = candidates_by_pair.get((prev_key, next_key))
            if isinstance(item, dict):
                _alloc(prev_key, next_key, item)
        return planned, int(checks_done)

    if strategy == "sample":
        rate = float(state_sample_rate)
        if rate < 0.0:
            rate = 0.0
        if rate > 1.0:
            rate = 1.0
        for prev_key, next_key in candidates_by_pair.keys():
            if checks_done >= budget:
                break
            item = candidates_by_pair.get((prev_key, next_key))
            if not isinstance(item, dict):
                continue
            if (prev_key, next_key) in planned_pairs:
                continue
            if rate >= 1.0:
                _alloc(prev_key, next_key, item)
                continue
            if rate <= 0.0:
                continue
            if _stable_hash01(run_id, prev_key, next_key) < rate:
                _alloc(prev_key, next_key, item)
        return planned, int(checks_done)

    candidates: List[Tuple[float, str, str]] = []
    for prev_key, next_key in candidates_by_pair.keys():
        if (prev_key, next_key) in planned_pairs:
            continue
        if not _pair_has_state(prev_key, next_key):
            continue

        prev_item = shot_items_by_key.get(prev_key, {})
        next_item = shot_items_by_key.get(next_key, {})
        state_after = _normalize_state_text(prev_item.get("state_after"))
        state_before = _normalize_state_text(next_item.get("state_before"))

        if state_after and state_before:
            base = 0.0 if state_after != state_before else 2.0
        else:
            base = 1.0

        report = base_shots.get(next_key)
        overall = float(report.scores.overall) if report and report.scores else 1.0
        candidates.append((base + overall, next_key, prev_key))

    candidates.sort(key=lambda x: x[0])
    for _score, next_key, prev_key in candidates:
        if checks_done >= budget:
            break
        item = candidates_by_pair.get((prev_key, next_key))
        if isinstance(item, dict):
            _alloc(prev_key, next_key, item)

    return planned, int(checks_done)


def _plan_semantic_checks(
    *,
    run_id: str,
    shot_order: List[str],
    base_shots: Dict[str, AutoQCShotReport],
    enable_semantic_qc: bool,
    semantic_frames: str,
    semantic_strategy: str,
    semantic_sample_rate: float,
    semantic_max_checks: int,
    semantic_always_first: bool,
    semantic_always_last: bool,
) -> Tuple[Dict[str, Dict[str, bool]], int]:
    """
    语义 QC 成本控制：
    - priority：优先检查关键镜头（首/尾）与低分但“本来能过”的镜头（base pass_ 为 True 且 overall 较低）
    - sample：兼容历史抽样（stable-hash），仍受 max_checks 限制
    - all：全部检查（仍受 max_checks 限制；max_checks<=0 表示不设上限）

    返回：per-shot 的 frame 选择（head/tail bool），以及计划的检查次数（按 frame 计数）。
    """
    if not enable_semantic_qc:
        return {}, 0
    if not shot_order:
        return {}, 0

    strategy = str(semantic_strategy or "").strip().lower()
    if strategy not in {"priority", "sample", "all"}:
        strategy = DEFAULT_SEMANTIC_STRATEGY

    frames = _semantic_frames_list(semantic_frames)
    budget = int(semantic_max_checks) if semantic_max_checks and int(semantic_max_checks) > 0 else 1_000_000

    planned: Dict[str, Dict[str, bool]] = {}
    checks_done = 0

    def _alloc(shot_key: str, frame_list: List[str]) -> None:
        nonlocal checks_done
        if not shot_key:
            return
        if checks_done >= budget:
            return
        current = planned.setdefault(shot_key, {"head": False, "tail": False})
        for frame in frame_list:
            if checks_done >= budget:
                break
            if frame not in {"head", "tail"}:
                continue
            if bool(current.get(frame)):
                continue
            current[frame] = True
            checks_done += 1

    first_key = shot_order[0] if shot_order else ""
    last_key = shot_order[-1] if shot_order else ""

    if semantic_always_first and first_key:
        _alloc(first_key, frames)
    if semantic_always_last and last_key and last_key != first_key:
        _alloc(last_key, frames)

    if strategy == "all":
        for sk in shot_order:
            _alloc(sk, frames)
        return planned, int(checks_done)

    if strategy == "sample":
        rate = float(semantic_sample_rate)
        if rate < 0.0:
            rate = 0.0
        if rate > 1.0:
            rate = 1.0
        for idx, sk in enumerate(shot_order, 1):
            for frame in frames:
                if checks_done >= budget:
                    break
                if semantic_always_first and idx == 1:
                    _alloc(sk, [frame])
                    continue
                if semantic_always_last and idx == len(shot_order) and len(shot_order) > 0:
                    _alloc(sk, [frame])
                    continue
                if rate >= 1.0:
                    _alloc(sk, [frame])
                    continue
                if rate <= 0.0:
                    continue
                if _stable_hash01(run_id, sk, frame) < rate:
                    _alloc(sk, [frame])
        return planned, int(checks_done)

    # priority：只对“本来能过但分数偏低”的镜头做语义核验（另加首/尾兜底）
    candidates: List[Tuple[float, str]] = []
    for sk in shot_order:
        report = base_shots.get(sk)
        if not report or not isinstance(report, AutoQCShotReport):
            continue
        if not bool(report.pass_):
            continue
        overall = float(report.scores.overall) if report.scores else 1.0
        candidates.append((overall, sk))

    candidates.sort(key=lambda x: x[0])
    for _overall, sk in candidates:
        if sk == first_key or sk == last_key:
            continue
        _alloc(sk, frames)
        if checks_done >= budget:
            break

    return planned, int(checks_done)


def _semantic_match(
    *,
    vlm_adapter: Any,
    image_path: str,
    expected: str,
    max_tokens: int = 400,
) -> Optional[Dict[str, Any]]:
    if not vlm_adapter or not hasattr(vlm_adapter, "chat"):
        return None
    if not image_path or not expected:
        return None
    p = Path(image_path)
    if not p.exists():
        return None

    system_prompt = (
        "你是视频/分镜质检员。\n"
        "任务：判断给定图片是否符合【期望描述】（语义一致性/主要元素/动作/场景）。\n"
        "只输出 JSON（不要 Markdown），字段：match_score(0~1, float)、issues(list[string])。"
    )
    system_prompt += "\nOutput JSON only. Keep issues <= 6 items; each item <= 120 chars."

    user_content = [
        {"type": "image_url", "image_url": {"url": _file_to_data_url(p)}},
        {"type": "text", "text": f"【期望描述】\n{expected}\n\n仅输出 JSON：{{\"match_score\":0.8,\"issues\":[\"...\"]}}"},
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens, response_format={"type": "json_object"})
        if not getattr(res, "success", False):
            res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens)
        if not getattr(res, "success", False):
            return None

        content = ""
        if isinstance(res.data, dict) and isinstance(res.data.get("content"), str):
            content = res.data["content"]
        obj = _try_parse_json_object(content)
        if not isinstance(obj, dict):
            return None

        score = obj.get("match_score")
        issues = obj.get("issues")
        if isinstance(score, (int, float)):
            score_f = float(score)
        else:
            return None
        issues_list = clamp_text_list(issues, max_items=6, max_chars=120)
        return {"match_score": score_f, "issues": issues_list}
    except Exception:  # noqa: BLE001
        return None


def _state_continuity_match(
    *,
    vlm_adapter: Any,
    prev_tail_path: str,
    next_head_path: str,
    prev_state_after: str,
    next_state_before: str,
    max_tokens: int = 500,
) -> Optional[Dict[str, Any]]:
    if not vlm_adapter or not hasattr(vlm_adapter, "chat"):
        return None
    if not prev_tail_path or not next_head_path:
        return None

    prev_p = Path(prev_tail_path)
    next_p = Path(next_head_path)
    if not prev_p.exists() or not next_p.exists():
        return None

    state_after = _normalize_state_text(prev_state_after)
    state_before = _normalize_state_text(next_state_before)
    if not state_after and not state_before:
        return None

    system_prompt = (
        "你是视频/分镜连续性质检员。\n"
        "任务：基于【上一镜头尾帧】与【下一镜头首帧】，核验两帧之间是否在关键状态上连续。\n"
        "请重点检查：门开/关、人物站位/朝向、道具持有、关键物体是否突然消失/出现、场景是否突变。\n"
        "同时参考提供的【状态约束】：若画面与状态约束矛盾，应判为不连续。\n"
        "只输出 JSON（不要 Markdown），字段：match_score(0~1,float)、issues(list[string])、suggestions(list[string],可选)。"
    )
    system_prompt += "\nOutput JSON only. Keep issues/suggestions <= 6 items; each item <= 120 chars."

    constraint_text = (
        "【状态约束】\n"
        f"- 上一镜头结束(state_after)：{state_after or '(未提供)'}\n"
        f"- 下一镜头开始(state_before)：{state_before or '(未提供)'}\n\n"
        "仅输出 JSON 示例："
        "{\"match_score\":0.82,\"issues\":[\"...\"],\"suggestions\":[\"... (可选)\"]}"
    )

    user_content = [
        {"type": "text", "text": "上一镜头尾帧"},
        {"type": "image_url", "image_url": {"url": _file_to_data_url(prev_p)}},
        {"type": "text", "text": "下一镜头首帧"},
        {"type": "image_url", "image_url": {"url": _file_to_data_url(next_p)}},
        {"type": "text", "text": constraint_text},
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens, response_format={"type": "json_object"})
        if not getattr(res, "success", False):
            res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens)
        if not getattr(res, "success", False):
            return None

        content = ""
        if isinstance(res.data, dict) and isinstance(res.data.get("content"), str):
            content = res.data["content"]
        obj = _try_parse_json_object(content)
        if not isinstance(obj, dict):
            return None

        score = obj.get("match_score")
        if not isinstance(score, (int, float)):
            return None
        score_f = float(score)
        if score_f < 0.0:
            score_f = 0.0
        if score_f > 1.0:
            score_f = 1.0

        issues_raw = obj.get("issues") if isinstance(obj.get("issues"), list) else []
        issues = clamp_text_list(issues_raw, max_items=6, max_chars=120)

        suggestions_raw = obj.get("suggestions") if isinstance(obj.get("suggestions"), list) else []
        suggestions = clamp_text_list(suggestions_raw, max_items=6, max_chars=120)

        return {"match_score": score_f, "issues": issues, "suggestions": suggestions}
    except Exception:  # noqa: BLE001
        return None


def _subject_pos(spec: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(spec, dict):
        return None
    pos = spec.get("subject_pos")
    if not isinstance(pos, dict):
        return None
    x = _safe_float(pos.get("x"))
    y = _safe_float(pos.get("y"))
    if x is None or y is None:
        return None
    return x, y


def _pos_delta(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> Optional[float]:
    if not a or not b:
        return None
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class AutoQCFailure:
    failure_type: str
    severity: str
    message: str
    shot_key: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoQCScores:
    identity: float
    structure: float
    style: float
    overall: float
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class AutoQCShotReport:
    shot_key: str
    pass_: bool
    scores: AutoQCScores
    failures: List[AutoQCFailure] = field(default_factory=list)


@dataclass
class AutoQCRoute:
    target_state: str
    action: str
    reason: str
    failure_types: List[str] = field(default_factory=list)
    patch: Dict[str, Any] = field(default_factory=dict)
    reset_policy: str = "downstream"


@dataclass
class AutoQCReport:
    pass_: bool
    overall_score: float
    shots: Dict[str, AutoQCShotReport]
    failures: List[AutoQCFailure] = field(default_factory=list)
    route: Optional[AutoQCRoute] = None
    config: Dict[str, Any] = field(default_factory=dict)


def _weighted_overall(identity: float, structure: float, style: float, weights: Dict[str, float]) -> float:
    total = float(sum(weights.values())) or 1.0
    return float(
        (identity * weights.get("identity", 0.0) + structure * weights.get("structure", 0.0) + style * weights.get("style", 0.0))
        / total
    )


def _score_shot(
    *,
    shot_key: str,
    head_spec: Dict[str, Any],
    tail_spec: Dict[str, Any],
    assets: Dict[str, str],
    prev_tail_spec: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
    vlm_adapter: Any = None,
    semantic_check: Optional[Dict[str, bool]] = None,
) -> AutoQCShotReport:
    similarity_threshold = float(cfg.get("similarity_threshold") or DEFAULT_SIMILARITY_THRESHOLD)
    max_pos_delta = float(cfg.get("max_subject_pos_delta") or DEFAULT_MAX_SUBJECT_POS_DELTA)
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(cfg.get("weights"), dict):
        for k in ("identity", "structure", "style"):
            if k in cfg["weights"]:
                weights[k] = float(cfg["weights"][k])

    failures: List[AutoQCFailure] = []

    head_path = assets.get("head")
    tail_path = assets.get("tail")
    if not _file_exists(head_path):
        failures.append(
            AutoQCFailure(
                failure_type="missing_head_frame",
                severity="hard",
                message="head frame file missing",
                shot_key=shot_key,
                meta={"path": head_path},
            )
        )
    if not _file_exists(tail_path):
        failures.append(
            AutoQCFailure(
                failure_type="missing_tail_frame",
                severity="hard",
                message="tail frame file missing",
                shot_key=shot_key,
                meta={"path": tail_path},
            )
        )

    head_ratio = head_spec.get("ratio")
    tail_ratio = tail_spec.get("ratio")
    ratio_match = bool(head_ratio and tail_ratio and str(head_ratio) == str(tail_ratio))
    if not ratio_match:
        failures.append(
            AutoQCFailure(
                failure_type="ratio_mismatch",
                severity="hard",
                message="head/tail ratio mismatch",
                shot_key=shot_key,
                meta={"head_ratio": head_ratio, "tail_ratio": tail_ratio},
            )
        )

    head_pos = _subject_pos(head_spec)
    tail_pos = _subject_pos(tail_spec)
    within_shot_delta = _pos_delta(head_pos, tail_pos)
    if within_shot_delta is None:
        failures.append(
            AutoQCFailure(
                failure_type="missing_subject_pos",
                severity="hard",
                message="subject_pos missing in head/tail spec",
                shot_key=shot_key,
            )
        )
        within_shot_delta_value = 1.0
    else:
        within_shot_delta_value = within_shot_delta
        if within_shot_delta > max_pos_delta:
            failures.append(
                AutoQCFailure(
                    failure_type="shot_continuity_break",
                    severity="hard",
                    message="subject position delta too large within shot",
                    shot_key=shot_key,
                    meta={"delta": within_shot_delta, "max_delta": max_pos_delta},
                )
            )

    cross_delta_value = 0.0
    if isinstance(prev_tail_spec, dict):
        prev_tail_pos = _subject_pos(prev_tail_spec)
        cross_delta = _pos_delta(prev_tail_pos, head_pos)
        if cross_delta is not None:
            cross_delta_value = cross_delta
            if cross_delta > max_pos_delta:
                failures.append(
                    AutoQCFailure(
                        failure_type="cross_shot_continuity_break",
                        severity="hard",
                        message="subject position delta too large across shots",
                        shot_key=shot_key,
                        meta={"delta": cross_delta, "max_delta": max_pos_delta},
                    )
                )

    # 结构分数是“软惩罚”（硬惩罚由 shot_continuity_break / cross_shot_continuity_break 负责）：
    # - 当 delta 接近 max_pos_delta 时，不应把 structure_score 压到接近 0（否则 overall 会因阈值过高而频繁失败）
    # - 这里把 max_pos_delta 映射到 0.75 左右（搭配默认权重/阈值能保持“接近阈值仍可通过”）
    structure_scale = float(max_pos_delta) * 4.0 if max_pos_delta > 0 else 0.0
    if structure_scale <= 0:
        structure_scale = float(max_pos_delta) if max_pos_delta > 0 else 1.0
    structure_badness = max(
        min(within_shot_delta_value / structure_scale, 1.0) if structure_scale > 0 else 1.0,
        min(cross_delta_value / structure_scale, 1.0) if structure_scale > 0 else 1.0,
    )
    structure_score = float(max(0.0, 1.0 - structure_badness))

    identity_score = 1.0 if _file_exists(head_path) and _file_exists(tail_path) else 0.0
    style_score = 1.0 if ratio_match else 0.0

    enable_semantic_qc = bool(cfg.get("enable_semantic_qc"))
    semantic_check = semantic_check if isinstance(semantic_check, dict) else {}
    semantic_threshold = float(cfg.get("semantic_threshold") or DEFAULT_SEMANTIC_THRESHOLD)
    if enable_semantic_qc and vlm_adapter is not None:
        head_prompt = str(head_spec.get("prompt") or "").strip()
        tail_prompt = str(tail_spec.get("prompt") or "").strip()

        if bool(semantic_check.get("head")) and _file_exists(head_path) and head_prompt:
            semantic = _semantic_match(vlm_adapter=vlm_adapter, image_path=str(head_path), expected=head_prompt)
            if semantic and semantic.get("match_score", 1.0) < semantic_threshold:
                failures.append(
                    AutoQCFailure(
                        failure_type="semantic_mismatch",
                        severity="hard",
                        message="head frame semantic mismatch",
                        shot_key=shot_key,
                        meta={
                            "frame": "head",
                            "match_score": float(semantic.get("match_score") or 0.0),
                            "threshold": semantic_threshold,
                            "issues": semantic.get("issues") or [],
                        },
                    )
                )

        if bool(semantic_check.get("tail")) and _file_exists(tail_path) and tail_prompt:
            semantic = _semantic_match(vlm_adapter=vlm_adapter, image_path=str(tail_path), expected=tail_prompt)
            if semantic and semantic.get("match_score", 1.0) < semantic_threshold:
                failures.append(
                    AutoQCFailure(
                        failure_type="semantic_mismatch",
                        severity="hard",
                        message="tail frame semantic mismatch",
                        shot_key=shot_key,
                        meta={
                            "frame": "tail",
                            "match_score": float(semantic.get("match_score") or 0.0),
                            "threshold": semantic_threshold,
                            "issues": semantic.get("issues") or [],
                        },
                    )
                )

    overall = _weighted_overall(identity_score, structure_score, style_score, weights)
    scores = AutoQCScores(identity=identity_score, structure=structure_score, style=style_score, overall=overall, weights=weights)

    pass_ = not any(f.severity == "hard" for f in failures) and overall >= similarity_threshold
    if overall < similarity_threshold:
        failures.append(
            AutoQCFailure(
                failure_type="overall_score_below_threshold",
                severity="hard",
                message="overall score below threshold",
                shot_key=shot_key,
                meta={"overall": overall, "threshold": similarity_threshold},
            )
        )
        pass_ = False

    return AutoQCShotReport(shot_key=shot_key, pass_=pass_, scores=scores, failures=failures)


def _route_from_failures(*, failures: List[AutoQCFailure], payload: Dict[str, Any]) -> Optional[AutoQCRoute]:
    if not failures:
        return None

    def _normalize_shot_keys(value: Any, *, limit: int = 200) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    regen_shots: List[str] = []
    for f in failures:
        if f.severity != "hard":
            continue
        shot_key = str(getattr(f, "shot_key", "") or "").strip()
        if shot_key and shot_key not in regen_shots:
            regen_shots.append(shot_key)
            if len(regen_shots) >= 200:
                break
        meta = getattr(f, "meta", None)
        if isinstance(meta, dict):
            for s in _normalize_shot_keys(meta.get("shot_keys")):
                if s in regen_shots:
                    continue
                regen_shots.append(s)
                if len(regen_shots) >= 200:
                    break
        if len(regen_shots) >= 200:
            break

    def _maybe_with_regen_shots(*, patch: Optional[Dict[str, Any]], target_state: str) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(patch) if isinstance(patch, dict) else {}
        if not regen_shots:
            return out
        if str(target_state or "").strip().upper() not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
            return out
        out["regenerate_shot_ids"] = regen_shots
        return out

    types: List[str] = []
    seen: set[str] = set()
    for f in failures:
        if f.severity != "hard":
            continue
        t = str(f.failure_type or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        types.append(t)
    if not types:
        return None

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    image_edit_enabled = any(
        bool(image_cfg.get(k))
        for k in (
            "head_use_image_edit",
            "tail_use_image_edit",
            "mid_use_image_edit",
        )
    )

    if any(t in {"ratio_mismatch", "missing_subject_pos"} for t in types):
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="revise_storyboard",
            reason="storyboard spec mismatch",
            failure_types=types,
        )

    if any(t in {"missing_video_clips", "video_engine_not_i2v", "i2v_fallback"} for t in types):
        patch: Dict[str, Any] = {}
        if _is_wan_i2v_configured():
            patch["video_config"] = {"engine": "wan_i2v"}
            if any(t == "i2v_fallback" for t in types):
                if not (isinstance(video_cfg.get("parallelism"), int) and int(video_cfg.get("parallelism")) <= 1):
                    patch["video_config"]["parallelism"] = 1
        patch = _maybe_with_regen_shots(patch=patch, target_state="VIDEO")
        return AutoQCRoute(
            target_state="VIDEO",
            action="switch_to_i2v" if _is_wan_i2v_configured() else "rerun_video",
            reason="video quality route mismatch",
            failure_types=types,
            patch=patch,
        )

    if any(t in {"shot_continuity_break", "cross_shot_continuity_break", "camera_continuity_break"} for t in types):
        if not image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_image_edit",
                reason="continuity constraint violated; prefer image_edit",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={
                        "image_config": {
                            "head_use_image_edit": True,
                            "tail_use_image_edit": True,
                            "image_edit_policy": "auto",
                        }
                    },
                    target_state="KEYFRAMES",
                ),
            )
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="revise_storyboard",
            reason="continuity constraint violated",
            failure_types=types,
        )

    if any(t in {"missing_head_frame", "missing_tail_frame"} for t in types):
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="keyframe assets missing",
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
        )

    if any(t in {"state_continuity_mismatch"} for t in types):
        if not image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_image_edit",
                reason="state continuity mismatch; prefer image_edit",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={
                        "image_config": {
                            "head_use_image_edit": True,
                            "tail_use_image_edit": True,
                            "image_edit_policy": "auto",
                        }
                    },
                    target_state="KEYFRAMES",
                ),
            )
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="state continuity mismatch",
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
        )

    if any(t in {"semantic_mismatch"} for t in types):
        if image_edit_enabled:
            return AutoQCRoute(
                target_state="KEYFRAMES",
                action="switch_to_t2i",
                reason="semantic mismatch under image_edit; prefer t2i",
                failure_types=types,
                patch=_maybe_with_regen_shots(
                    patch={"image_config": {"head_use_image_edit": False, "tail_use_image_edit": False, "mid_use_image_edit": False}},
                    target_state="KEYFRAMES",
                ),
            )
        current = int(image_cfg.get("t2i_candidates") or 1)
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action="regen_keyframes",
            reason="semantic mismatch (vlm)",
            failure_types=types,
            patch=_maybe_with_regen_shots(
                patch={"image_config": {"image_selector": "vlm", "t2i_candidates": min(4, max(current, 2))}},
                target_state="KEYFRAMES",
            ),
        )
    if any(t in {"overall_score_below_threshold"} for t in types):
        patch = {"image_config": {}}
        if image_edit_enabled:
            patch["image_config"].update({"head_use_image_edit": False, "tail_use_image_edit": False, "mid_use_image_edit": False})
            action = "switch_to_t2i"
            reason = "overall score below threshold under image_edit; prefer t2i"
        else:
            current = int(image_cfg.get("t2i_candidates") or 1)
            patch["image_config"].update({"t2i_candidates": min(4, max(current, 3)), "image_selector": "vlm"})
            action = "boost_candidates"
            reason = "overall score below threshold; increase candidates"
        return AutoQCRoute(
            target_state="KEYFRAMES",
            action=action,
            reason=reason,
            failure_types=types,
            patch=_maybe_with_regen_shots(patch=patch, target_state="KEYFRAMES"),
        )

    return AutoQCRoute(
        target_state="KEYFRAMES",
        action="regen_keyframes",
        reason="autoqc failed",
        failure_types=types,
        patch=_maybe_with_regen_shots(patch=None, target_state="KEYFRAMES"),
    )


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}

    enable_semantic_qc_cfg = cfg.get("enable_semantic_qc")
    enable_semantic_qc = (
        bool(enable_semantic_qc_cfg)
        if isinstance(enable_semantic_qc_cfg, bool)
        else _env_flag("DREAMWEAVER_ENABLE_SEMANTIC_QC", False)
    )
    semantic_threshold = float(cfg.get("semantic_threshold") or os.getenv("DREAMWEAVER_SEMANTIC_THRESHOLD") or DEFAULT_SEMANTIC_THRESHOLD)
    semantic_vlm_adapter = str(cfg.get("semantic_vlm_adapter") or os.getenv("DREAMWEAVER_SEMANTIC_VLM_ADAPTER") or DEFAULT_SEMANTIC_VLM_ADAPTER)

    semantic_frames = str(
        cfg.get("semantic_frames")
        or os.getenv("DREAMWEAVER_SEMANTIC_FRAMES")
        or DEFAULT_SEMANTIC_FRAMES
    ).strip().lower()
    if semantic_frames not in {"head", "tail", "both"}:
        semantic_frames = DEFAULT_SEMANTIC_FRAMES

    semantic_strategy = str(
        cfg.get("semantic_strategy")
        or os.getenv("DREAMWEAVER_SEMANTIC_STRATEGY")
        or DEFAULT_SEMANTIC_STRATEGY
    ).strip().lower()
    if semantic_strategy not in {"priority", "sample", "all"}:
        semantic_strategy = DEFAULT_SEMANTIC_STRATEGY

    semantic_sample_rate = float(
        cfg.get("semantic_sample_rate")
        if isinstance(cfg.get("semantic_sample_rate"), (int, float))
        else _env_float("DREAMWEAVER_SEMANTIC_SAMPLE_RATE", DEFAULT_SEMANTIC_SAMPLE_RATE)
    )
    if semantic_sample_rate < 0.0:
        semantic_sample_rate = 0.0
    if semantic_sample_rate > 1.0:
        semantic_sample_rate = 1.0

    semantic_max_checks_explicit = False
    if isinstance(cfg.get("semantic_max_checks"), (int, float, str)) and str(cfg.get("semantic_max_checks")).strip():
        semantic_max_checks_explicit = True
    elif os.getenv("DREAMWEAVER_SEMANTIC_MAX_CHECKS") is not None and str(os.getenv("DREAMWEAVER_SEMANTIC_MAX_CHECKS") or "").strip():
        semantic_max_checks_explicit = True

    semantic_max_checks = (
        int(cfg.get("semantic_max_checks"))
        if semantic_max_checks_explicit and "semantic_max_checks" in cfg
        else _env_int("DREAMWEAVER_SEMANTIC_MAX_CHECKS", DEFAULT_SEMANTIC_MAX_CHECKS)
    )
    if semantic_max_checks < 0:
        semantic_max_checks = 0

    semantic_always_first = (
        bool(cfg.get("semantic_always_first"))
        if isinstance(cfg.get("semantic_always_first"), bool)
        else _env_flag("DREAMWEAVER_SEMANTIC_ALWAYS_FIRST", True)
    )
    semantic_always_last = (
        bool(cfg.get("semantic_always_last"))
        if isinstance(cfg.get("semantic_always_last"), bool)
        else _env_flag("DREAMWEAVER_SEMANTIC_ALWAYS_LAST", True)
    )

    enable_state_qc_cfg = cfg.get("enable_state_qc")
    enable_state_qc = bool(enable_state_qc_cfg) if isinstance(enable_state_qc_cfg, bool) else _env_flag("DREAMWEAVER_ENABLE_STATE_QC", False)
    state_threshold = float(cfg.get("state_threshold") or os.getenv("DREAMWEAVER_STATE_QC_THRESHOLD") or DEFAULT_STATE_QC_THRESHOLD)
    state_vlm_adapter = str(cfg.get("state_vlm_adapter") or os.getenv("DREAMWEAVER_STATE_QC_VLM_ADAPTER") or DEFAULT_STATE_QC_VLM_ADAPTER)

    state_strategy = str(cfg.get("state_strategy") or os.getenv("DREAMWEAVER_STATE_QC_STRATEGY") or DEFAULT_STATE_QC_STRATEGY).strip().lower()
    if state_strategy not in {"priority", "sample", "all"}:
        state_strategy = DEFAULT_STATE_QC_STRATEGY

    state_sample_rate = float(
        cfg.get("state_sample_rate")
        if isinstance(cfg.get("state_sample_rate"), (int, float))
        else _env_float("DREAMWEAVER_STATE_QC_SAMPLE_RATE", DEFAULT_STATE_QC_SAMPLE_RATE)
    )
    if state_sample_rate < 0.0:
        state_sample_rate = 0.0
    if state_sample_rate > 1.0:
        state_sample_rate = 1.0

    state_max_checks_explicit = False
    if isinstance(cfg.get("state_max_checks"), (int, float, str)) and str(cfg.get("state_max_checks")).strip():
        state_max_checks_explicit = True
    elif os.getenv("DREAMWEAVER_STATE_QC_MAX_CHECKS") is not None and str(os.getenv("DREAMWEAVER_STATE_QC_MAX_CHECKS") or "").strip():
        state_max_checks_explicit = True

    state_max_checks = (
        int(cfg.get("state_max_checks"))
        if state_max_checks_explicit and "state_max_checks" in cfg
        else _env_int("DREAMWEAVER_STATE_QC_MAX_CHECKS", DEFAULT_STATE_QC_MAX_CHECKS)
    )
    if state_max_checks < 0:
        state_max_checks = 0

    state_always_first = (
        bool(cfg.get("state_always_first"))
        if isinstance(cfg.get("state_always_first"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_ALWAYS_FIRST", True)
    )
    state_always_last = (
        bool(cfg.get("state_always_last"))
        if isinstance(cfg.get("state_always_last"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_ALWAYS_LAST", True)
    )
    state_include_camera_edges = (
        bool(cfg.get("state_include_camera_edges"))
        if isinstance(cfg.get("state_include_camera_edges"), bool)
        else _env_flag("DREAMWEAVER_STATE_QC_INCLUDE_CAMERA_EDGES", True)
    )
    enable_camera_continuity_qc_cfg = cfg.get("enable_camera_continuity_qc")
    enable_camera_continuity_qc = (
        bool(enable_camera_continuity_qc_cfg)
        if isinstance(enable_camera_continuity_qc_cfg, bool)
        else _env_flag("DREAMWEAVER_ENABLE_CAMERA_CONTINUITY_QC", False)
    )

    quality_mode = str(payload.get("quality_mode") or "").strip().lower()
    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    video_engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "").strip().lower()
    is_t2v_engine = video_engine in {"wan_t2v", "wan26_t2v", "t2v"}
    require_i2v_cfg = cfg.get("require_i2v", DEFAULT_REQUIRE_I2V)
    if isinstance(require_i2v_cfg, bool):
        require_i2v = bool(require_i2v_cfg)
    else:
        # 默认策略：quality_mode=quality 且配置了 I2V 才会强制 require_i2v；当用户显式选择 T2V 引擎时不强制（可手动 override）。
        require_i2v = (quality_mode == "quality" and _is_wan_i2v_configured()) and (not is_t2v_engine)

    cfg_effective = {
        "similarity_threshold": cfg.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        "max_subject_pos_delta": cfg.get("max_subject_pos_delta", DEFAULT_MAX_SUBJECT_POS_DELTA),
        "weights": cfg.get("weights", DEFAULT_WEIGHTS),
        "enable_semantic_qc": enable_semantic_qc,
        "semantic_threshold": semantic_threshold,
        "semantic_vlm_adapter": semantic_vlm_adapter,
        "semantic_frames": semantic_frames,
        "semantic_strategy": semantic_strategy,
        "semantic_sample_rate": semantic_sample_rate,
        "semantic_max_checks": semantic_max_checks,
        "semantic_always_first": semantic_always_first,
        "semantic_always_last": semantic_always_last,
        "enable_state_qc": enable_state_qc,
        "state_threshold": state_threshold,
        "state_vlm_adapter": state_vlm_adapter,
        "state_strategy": state_strategy,
        "state_sample_rate": state_sample_rate,
        "state_max_checks": state_max_checks,
        "state_always_first": state_always_first,
        "state_always_last": state_always_last,
        "state_include_camera_edges": state_include_camera_edges,
        "enable_camera_continuity_qc": enable_camera_continuity_qc,
        "require_i2v": require_i2v,
    }

    semantic_vlm = None
    state_vlm = None
    if enable_semantic_qc or enable_state_qc:
        try:
            from adapters.model_adapters import ModelAdapterFactory

            factory = ModelAdapterFactory()

            if enable_semantic_qc:
                try:
                    semantic_vlm = factory.get_adapter(semantic_vlm_adapter)
                except Exception:  # noqa: BLE001
                    semantic_vlm = None
                    cfg_effective["enable_semantic_qc"] = False

            if enable_state_qc:
                try:
                    if semantic_vlm is not None and str(semantic_vlm_adapter) == str(state_vlm_adapter):
                        state_vlm = semantic_vlm
                    else:
                        state_vlm = factory.get_adapter(state_vlm_adapter)
                except Exception:  # noqa: BLE001
                    state_vlm = None
                    cfg_effective["enable_state_qc"] = False
        except Exception:  # noqa: BLE001
            semantic_vlm = None
            state_vlm = None
            cfg_effective["enable_semantic_qc"] = False
            cfg_effective["enable_state_qc"] = False

    assets_index = _index_assets(payload)
    storyboard = payload.get("storyboard") or []

    shots: Dict[str, AutoQCShotReport] = {}
    all_failures: List[AutoQCFailure] = []
    prev_tail_spec: Optional[Dict[str, Any]] = None
    run_id = str(payload.get("run_id") or "")
    shot_items = [item for item in storyboard if isinstance(item, dict) and str(item.get("shot_id") or "").strip()]
    shot_count = len(shot_items)

    shot_items_by_key: Dict[str, Dict[str, Any]] = {}
    for item in shot_items:
        shot_key = str(item.get("shot_id") or "").strip()
        if shot_key:
            shot_items_by_key[shot_key] = item

    shot_order = [str(item.get("shot_id") or "") for item in shot_items if isinstance(item, dict)]
    shot_order = [s for s in shot_order if s]

    # 默认预算兜底：避免误开 semantic_qc 时对所有镜头全量调用 VLM（越提质越慢/越贵）
    # 仅在未显式配置 semantic_max_checks 且 env 未设置时生效；显式设置为 0 表示不设上限（保持历史行为）。
    if enable_semantic_qc and semantic_vlm is not None and (not semantic_max_checks_explicit) and int(semantic_max_checks) <= 0:
        default_budget = 24 if quality_mode == "quality" else 12
        min_budget = len(_semantic_frames_list(semantic_frames)) * (2 if shot_count >= 2 else 1)
        semantic_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["semantic_max_checks"] = int(semantic_max_checks)

    if enable_state_qc and state_vlm is not None and (not state_max_checks_explicit) and int(state_max_checks) <= 0:
        default_budget = 12 if quality_mode == "quality" else 6
        min_budget = 2 if shot_count >= 3 else (1 if shot_count >= 2 else 0)
        state_max_checks = max(int(min_budget), int(default_budget))
        cfg_effective["state_max_checks"] = int(state_max_checks)

    # first pass：先算“非语义”的 base 分数，用于 priority 分层
    base_shots: Dict[str, AutoQCShotReport] = {}
    base_prev_tail: Dict[str, Optional[Dict[str, Any]]] = {}
    prev_tail_spec = None
    for idx, item in enumerate(shot_items, 1):
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        head_spec = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
        tail_spec = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}
        base_prev_tail[shot_key] = prev_tail_spec
        report = _score_shot(
            shot_key=shot_key,
            head_spec=head_spec,
            tail_spec=tail_spec,
            assets=assets_index.get(shot_key, {}),
            prev_tail_spec=prev_tail_spec,
            cfg=cfg_effective,
            vlm_adapter=semantic_vlm,
            semantic_check={"head": False, "tail": False},
        )
        base_shots[shot_key] = report
        prev_tail_spec = tail_spec

    semantic_plan: Dict[str, Dict[str, bool]] = {}
    semantic_checks_done = 0
    if enable_semantic_qc and semantic_vlm is not None:
        semantic_plan, semantic_checks_done = _plan_semantic_checks(
            run_id=run_id,
            shot_order=shot_order,
            base_shots=base_shots,
            enable_semantic_qc=True,
            semantic_frames=semantic_frames,
            semantic_strategy=semantic_strategy,
            semantic_sample_rate=semantic_sample_rate,
            semantic_max_checks=int(semantic_max_checks),
            semantic_always_first=semantic_always_first,
            semantic_always_last=semantic_always_last,
        )

    state_plan: List[Dict[str, Any]] = []
    state_checks_done = 0
    if enable_state_qc and state_vlm is not None:
        state_candidates: List[Dict[str, Any]] = []
        for i in range(1, len(shot_order)):
            state_candidates.append({"prev_shot_key": shot_order[i - 1], "next_shot_key": shot_order[i], "kinds": ["adjacent"]})

        if state_include_camera_edges:
            camera_states = payload.get("camera_states")
            if isinstance(camera_states, list) and camera_states:
                for track in camera_states:
                    if not isinstance(track, dict):
                        continue
                    cam_idx = track.get("cam_idx")
                    if not isinstance(cam_idx, int):
                        continue
                    states = track.get("states") if isinstance(track.get("states"), list) else []
                    prev_id: Optional[str] = None
                    for st in states:
                        if not isinstance(st, dict):
                            continue
                        sid = str(st.get("shot_id") or st.get("state_id") or "").strip()
                        if not sid:
                            continue
                        if prev_id:
                            state_candidates.append(
                                {
                                    "prev_shot_key": prev_id,
                                    "next_shot_key": sid,
                                    "kinds": ["same_camera"],
                                    "camera": {"cam_idx": int(cam_idx)},
                                }
                            )
                        prev_id = sid

                    parent_shot_id = track.get("parent_shot_id")
                    first_state_id = track.get("first_state_id")
                    if (
                        isinstance(parent_shot_id, str)
                        and parent_shot_id.strip()
                        and isinstance(first_state_id, str)
                        and first_state_id.strip()
                        and parent_shot_id.strip() != first_state_id.strip()
                    ):
                        parent_cam_idx = track.get("parent_cam_idx")
                        camera_meta: Dict[str, Any] = {"cam_idx": int(cam_idx)}
                        if isinstance(parent_cam_idx, int):
                            camera_meta["parent_cam_idx"] = int(parent_cam_idx)
                        state_candidates.append(
                            {
                                "prev_shot_key": parent_shot_id.strip(),
                                "next_shot_key": first_state_id.strip(),
                                "kinds": ["camera_tree_parent"],
                                "camera": camera_meta,
                            }
                        )

        state_plan, state_checks_done = _plan_state_checks(
            run_id=run_id,
            shot_order=shot_order,
            candidate_pairs=state_candidates,
            shot_items_by_key=shot_items_by_key,
            base_shots=base_shots,
            enable_state_qc=True,
            state_strategy=state_strategy,
            state_sample_rate=state_sample_rate,
            state_max_checks=int(state_max_checks),
            state_always_first=state_always_first,
            state_always_last=state_always_last,
        )

    for idx, item in enumerate(shot_items, 1):
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        base_report = base_shots.get(shot_key)
        if base_report is None:
            continue

        need_sem = semantic_plan.get(shot_key) if isinstance(semantic_plan.get(shot_key), dict) else None
        if enable_semantic_qc and semantic_vlm is not None and need_sem and (need_sem.get("head") or need_sem.get("tail")):
            head_spec = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
            tail_spec = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}
            report = _score_shot(
                shot_key=shot_key,
                head_spec=head_spec,
                tail_spec=tail_spec,
                assets=assets_index.get(shot_key, {}),
                prev_tail_spec=base_prev_tail.get(shot_key),
                cfg=cfg_effective,
                vlm_adapter=semantic_vlm,
                semantic_check={"head": bool(need_sem.get("head")), "tail": bool(need_sem.get("tail"))},
            )
        else:
            report = base_report

        shots[shot_key] = report
        all_failures.extend(report.failures)

    if enable_state_qc and state_vlm is not None and state_plan:
        for check in state_plan:
            if not isinstance(check, dict):
                continue
            prev_key = str(check.get("prev_shot_key") or "").strip()
            next_key = str(check.get("next_shot_key") or "").strip()
            if not prev_key or not next_key:
                continue
            prev_assets = assets_index.get(prev_key, {})
            next_assets = assets_index.get(next_key, {})
            prev_tail_path = prev_assets.get("tail")
            next_head_path = next_assets.get("head")
            if not _file_exists(prev_tail_path) or not _file_exists(next_head_path):
                continue

            prev_item = shot_items_by_key.get(prev_key, {})
            next_item = shot_items_by_key.get(next_key, {})
            prev_state_after = _normalize_state_text(prev_item.get("state_after"))
            next_state_before = _normalize_state_text(next_item.get("state_before"))
            if not (prev_state_after or next_state_before):
                continue

            res = _state_continuity_match(
                vlm_adapter=state_vlm,
                prev_tail_path=str(prev_tail_path),
                next_head_path=str(next_head_path),
                prev_state_after=prev_state_after,
                next_state_before=next_state_before,
            )
            if not res:
                continue

            score = float(res.get("match_score") or 0.0)
            if score >= float(state_threshold):
                continue

            failure = AutoQCFailure(
                failure_type="state_continuity_mismatch",
                severity="hard",
                message="state continuity mismatch across shots",
                shot_key=next_key,
                meta={
                    "prev_shot_key": prev_key,
                    "next_shot_key": next_key,
                    "match_score": score,
                    "threshold": float(state_threshold),
                    "state_after": prev_state_after,
                    "state_before": next_state_before,
                    "issues": res.get("issues") or [],
                    "suggestions": res.get("suggestions") or [],
                    "shot_keys": [prev_key, next_key],
                    "kinds": check.get("kinds") if isinstance(check.get("kinds"), list) else [],
                    "camera": check.get("camera") if isinstance(check.get("camera"), dict) else None,
                },
            )
            report = shots.get(next_key)
            if report is not None:
                report.failures.append(failure)
                report.pass_ = False
            all_failures.append(failure)

    camera_continuity_checks_done = 0
    if enable_camera_continuity_qc:
        try:
            max_pos_delta_value = float(cfg_effective.get("max_subject_pos_delta") or DEFAULT_MAX_SUBJECT_POS_DELTA)
        except Exception:  # noqa: BLE001
            max_pos_delta_value = DEFAULT_MAX_SUBJECT_POS_DELTA
        if max_pos_delta_value < 0.0:
            max_pos_delta_value = 0.0

        shot_index_by_key = {k: i for i, k in enumerate(shot_order)}
        seen_pairs: set[tuple[str, str]] = set()
        camera_states = payload.get("camera_states")
        if isinstance(camera_states, list) and camera_states and max_pos_delta_value > 0.0:
            for track in camera_states:
                if not isinstance(track, dict):
                    continue
                cam_idx = track.get("cam_idx")
                if not isinstance(cam_idx, int):
                    continue

                def _check_pair(prev_key: str, next_key: str, *, kinds: List[str], camera_meta: Dict[str, Any]) -> None:
                    nonlocal camera_continuity_checks_done
                    pair = (prev_key, next_key)
                    if pair in seen_pairs:
                        return
                    prev_idx = shot_index_by_key.get(prev_key)
                    next_idx = shot_index_by_key.get(next_key)
                    if isinstance(prev_idx, int) and isinstance(next_idx, int) and next_idx == prev_idx + 1:
                        # storyboard 邻接已由 cross_shot_continuity_break 覆盖，避免重复报错。
                        return

                    prev_item = shot_items_by_key.get(prev_key)
                    next_item = shot_items_by_key.get(next_key)
                    if not isinstance(prev_item, dict) or not isinstance(next_item, dict):
                        return
                    prev_tail_spec = prev_item.get("tail_frame") if isinstance(prev_item.get("tail_frame"), dict) else {}
                    next_head_spec = next_item.get("head_frame") if isinstance(next_item.get("head_frame"), dict) else {}

                    prev_tail_pos = _subject_pos(prev_tail_spec)
                    next_head_pos = _subject_pos(next_head_spec)
                    delta = _pos_delta(prev_tail_pos, next_head_pos)
                    if delta is None:
                        return

                    camera_continuity_checks_done += 1
                    seen_pairs.add(pair)

                    if delta <= float(max_pos_delta_value):
                        return

                    failure = AutoQCFailure(
                        failure_type="camera_continuity_break",
                        severity="hard",
                        message="camera continuity constraint violated",
                        shot_key=next_key,
                        meta={
                            "prev_shot_key": prev_key,
                            "next_shot_key": next_key,
                            "delta": float(delta),
                            "max_delta": float(max_pos_delta_value),
                            "shot_keys": [prev_key, next_key],
                            "kinds": kinds,
                            "camera": camera_meta,
                        },
                    )
                    report = shots.get(next_key)
                    if report is not None:
                        report.failures.append(failure)
                        report.pass_ = False
                    all_failures.append(failure)

                states = track.get("states") if isinstance(track.get("states"), list) else []
                prev_id: Optional[str] = None
                for st in states:
                    if not isinstance(st, dict):
                        continue
                    sid = str(st.get("shot_id") or st.get("state_id") or "").strip()
                    if not sid:
                        continue
                    if prev_id:
                        _check_pair(prev_id, sid, kinds=["same_camera"], camera_meta={"cam_idx": int(cam_idx)})
                    prev_id = sid

                parent_shot_id = track.get("parent_shot_id")
                first_state_id = track.get("first_state_id")
                if (
                    isinstance(parent_shot_id, str)
                    and parent_shot_id.strip()
                    and isinstance(first_state_id, str)
                    and first_state_id.strip()
                    and parent_shot_id.strip() != first_state_id.strip()
                ):
                    parent_cam_idx = track.get("parent_cam_idx")
                    camera_meta: Dict[str, Any] = {"cam_idx": int(cam_idx)}
                    if isinstance(parent_cam_idx, int):
                        camera_meta["parent_cam_idx"] = int(parent_cam_idx)
                    _check_pair(parent_shot_id.strip(), first_state_id.strip(), kinds=["camera_tree_parent"], camera_meta=camera_meta)

    if require_i2v:
        video_clips = payload.get("video_clips") or []
        if not isinstance(video_clips, list) or not any(isinstance(c, dict) for c in video_clips):
            all_failures.append(
                AutoQCFailure(
                    failure_type="missing_video_clips",
                    severity="hard",
                    message="video clips missing for require_i2v",
                )
            )
        else:
            clip_engines: List[str] = []
            fallback_shots: List[str] = []
            for clip in video_clips:
                if not isinstance(clip, dict):
                    continue
                meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
                engine = str(meta.get("engine") or "").strip()
                if engine:
                    clip_engines.append(engine)
                via = str(meta.get("via") or "").strip()
                if via == "ffmpeg_slideshow_fallback":
                    shot_key, _role = _parse_role_from_path(str(clip.get("path") or ""))
                    fallback_shots.append(shot_key or "")

            if clip_engines and any(e != "wan_i2v" for e in clip_engines):
                all_failures.append(
                    AutoQCFailure(
                        failure_type="video_engine_not_i2v",
                        severity="hard",
                        message="video engine is not wan_i2v",
                        meta={"engines": clip_engines[:8]},
                    )
                )
            if any(s for s in fallback_shots):
                all_failures.append(
                    AutoQCFailure(
                        failure_type="i2v_fallback",
                        severity="hard",
                        message="wan_i2v clip fell back to slideshow",
                        meta={"shot_keys": [s for s in fallback_shots if s][:8]},
                    )
                )

    cfg_effective["semantic_checks_done"] = semantic_checks_done
    cfg_effective["state_checks_done"] = state_checks_done
    cfg_effective["camera_continuity_checks_done"] = camera_continuity_checks_done

    overall_score = float(sum(r.scores.overall for r in shots.values()) / (len(shots) or 1))
    pass_ = not any(f.severity == "hard" for f in all_failures)
    route = _route_from_failures(failures=all_failures, payload=payload) if not pass_ else None

    report = AutoQCReport(
        pass_=pass_,
        overall_score=overall_score,
        shots=shots,
        failures=all_failures,
        route=route,
        config=cfg_effective,
    )

    result = asdict(report)
    result["pass"] = result.pop("pass_")
    for shot in result.get("shots", {}).values():
        shot["pass"] = shot.pop("pass_")
    return result
