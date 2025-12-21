from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


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

    structure_badness = max(
        min(within_shot_delta_value / max_pos_delta, 1.0) if max_pos_delta > 0 else 1.0,
        min(cross_delta_value / max_pos_delta, 1.0) if max_pos_delta > 0 else 1.0,
    )
    structure_score = float(max(0.0, 1.0 - structure_badness))

    identity_score = 1.0 if _file_exists(head_path) and _file_exists(tail_path) else 0.0
    style_score = 1.0 if ratio_match else 0.0

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


def _route_from_failures(failures: List[AutoQCFailure]) -> Optional[AutoQCRoute]:
    if not failures:
        return None

    types = [f.failure_type for f in failures if f.severity == "hard"]
    if not types:
        return None

    if any(t in {"missing_head_frame", "missing_tail_frame", "ratio_mismatch"} for t in types):
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="regen_keyframes",
            reason="keyframe assets or basic spec mismatch",
            failure_types=types,
        )
    if any(t in {"shot_continuity_break", "cross_shot_continuity_break"} for t in types):
        return AutoQCRoute(
            target_state="SCRIPT",
            action="revise_storyboard",
            reason="continuity constraint violated",
            failure_types=types,
        )
    if any(t in {"overall_score_below_threshold"} for t in types):
        return AutoQCRoute(
            target_state="STORYBOARD",
            action="regen_keyframes",
            reason="overall score below threshold",
            failure_types=types,
        )

    return AutoQCRoute(target_state="STORYBOARD", action="regen_keyframes", reason="autoqc failed", failure_types=types)


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = payload.get("qc_config") if isinstance(payload.get("qc_config"), dict) else {}
    cfg_effective = {
        "similarity_threshold": cfg.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD),
        "max_subject_pos_delta": cfg.get("max_subject_pos_delta", DEFAULT_MAX_SUBJECT_POS_DELTA),
        "weights": cfg.get("weights", DEFAULT_WEIGHTS),
    }

    assets_index = _index_assets(payload)
    storyboard = payload.get("storyboard") or []

    shots: Dict[str, AutoQCShotReport] = {}
    all_failures: List[AutoQCFailure] = []
    prev_tail_spec: Optional[Dict[str, Any]] = None

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_key = str(item.get("shot_id") or "")
        if not shot_key:
            continue
        head_spec = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
        tail_spec = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}
        report = _score_shot(
            shot_key=shot_key,
            head_spec=head_spec,
            tail_spec=tail_spec,
            assets=assets_index.get(shot_key, {}),
            prev_tail_spec=prev_tail_spec,
            cfg=cfg_effective,
        )
        shots[shot_key] = report
        all_failures.extend(report.failures)
        prev_tail_spec = tail_spec

    overall_score = float(sum(r.scores.overall for r in shots.values()) / (len(shots) or 1))
    pass_ = all(r.pass_ for r in shots.values())
    route = _route_from_failures(all_failures) if not pass_ else None

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
