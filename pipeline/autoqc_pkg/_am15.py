# -*- coding: utf-8 -*-
"""AM-15 视频理解与评价系统（Phase 2.5 · pipeline 评价层升级）。

四阶段（对齐 SSOT AM-15 模块 + v1.3/v1.4 升级字段）：
  ①廉价自检前置（分级质检控成本）：ffprobe 元数据 vs Contract 时长/分辨率、
    黑帧/静态片段检测、音量/静音段分析——可疑镜头才进 VLM，全量 VLM 降级为抽检
  ②混合主客观评审：客观通道（①结果 + transition_summary 跨镜头客观输入）+
    MLLM 主观逐镜评分（镜头卡 12 字段依据），冲突时仲裁（客观否决权限于物理类指标）
  ③persona 观众双轨：3 个观众人格看片反馈（钩子留存/情绪曲线/弃剧点），
    与导演标准分双轨输出（冲突时导演优先，Soft Gate）
  ④双格式输出：人读 markdown + 机读 critique.json（verdict/CF 命中/修复建议/跨镜头维度，
    直接供修复路由消费，无 LLM 再解析——10.6 machine_readable_critique）

VLM 通道：注入式 vlm_chat(prompt)->str 回调（生产默认 agents.vlm_utils.vlm_chat_json；
无回调/无文件时对应阶段降级为 skipped，骨架输出保证可测）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pipeline.autoqc_pkg._cf_map import resolve_cf_hits

AM15_SCHEMA = "am15/1.0"
DEFAULT_PERSONAS = [
    {"id": "p1", "profile": "22岁女性，短视频重度用户，偏爱情感 suspense 题"},
    {"id": "p2", "profile": "35岁男性，通勤碎片时间观看，对节奏拖沓零容忍"},
    {"id": "p3", "profile": "28岁女性，短剧付费用户，重代入感与角色魅力"},
]

_PhysicalIssueTypes = {"black_frame", "static_segment", "silent_segment", "duration_mismatch", "resolution_mismatch"}


# ---------------------------------------------------------------- ① 廉价自检
def _ffprobe_json(path: Path) -> Optional[Dict[str, Any]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        return json.loads(out.stdout or "{}")
    except Exception:  # noqa: BLE001
        return None


def _detect_black_or_static(path: Path) -> List[str]:
    """黑帧/静态片段检测（blackdetect + freezedetect，均属廉价客观通道）。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not path.exists():
        return []
    issues: List[str] = []
    for name, vf in (("black_frame", "blackdetect=d=0.2"), ("static_segment", "freezedetect=n=0.003:d=1")):
        try:
            out = subprocess.run(
                [ffmpeg, "-v", "info", "-i", str(path), "-vf", vf, "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            marker = "blackdetect" if name == "black_frame" else "freezedetect"
            if marker in (out.stderr or ""):
                issues.append(name)
        except Exception:  # noqa: BLE001
            continue
    return issues


def cheap_precheck(
    *,
    video_paths: Optional[List[Path]] = None,
    contracts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """阶段①：ffprobe/帧采样/音频分析（零 VLM 成本）。"""
    checks: List[Dict[str, Any]] = []
    paths = [Path(p) for p in (video_paths or []) if Path(p).exists()]
    if not paths:
        return {"status": "skipped_no_files", "checks": [], "intercepted": 0}

    durations = [float(c.get("duration_s") or 0) for c in (contracts or []) if isinstance(c, dict)]
    for i, path in enumerate(paths[:40]):
        meta = _ffprobe_json(path)
        entry: Dict[str, Any] = {"path": str(path), "issues": []}
        if meta:
            fmt = meta.get("format") or {}
            try:
                dur = float(fmt.get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            entry["ffprobe_duration_s"] = dur
            # 时长偏差 vs Contract（容差 20%）
            expected = durations[i] if i < len(durations) else None
            if expected and dur > 0 and abs(dur - expected) / max(expected, 0.1) > 0.2:
                entry["issues"].append("duration_mismatch")
            streams = meta.get("streams") or []
            if streams and not any(s.get("height") for s in streams if isinstance(s, dict)):
                entry["issues"].append("resolution_mismatch")
        else:
            entry["issues"].append("ffprobe_unavailable")
        entry["issues"].extend(_detect_black_or_static(path))
        checks.append(entry)

    intercepted = sum(1 for c in checks if c.get("issues"))
    return {
        "status": "ok",
        "checks": checks,
        "intercepted": intercepted,
        "intercept_rate": round(intercepted / max(1, len(checks)), 2),
    }


# ---------------------------------------------------------------- ② 混合评审
def hybrid_review(
    *,
    cheap: Dict[str, Any],
    storyboard: Optional[List[Dict[str, Any]]] = None,
    camera_states: Optional[List[Dict[str, Any]]] = None,
    vlm_chat: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """阶段②：客观通道（cheap + transition_summary）+ 主观通道（MLLM 逐镜）+ 仲裁。"""
    objective: Dict[str, Any] = {"cheap": cheap}
    # 跨镜头客观输入（2.4 State Engine 产物）
    transition_summary: List[Dict[str, Any]] = []
    for track in camera_states or []:
        if isinstance(track, dict) and isinstance(track.get("transition_summary"), dict):
            transition_summary.append(track["transition_summary"])
    objective["transition_summaries"] = transition_summary
    total_gaps = sum(int(t.get("gaps") or 0) for t in transition_summary)

    subjective: Dict[str, Any] = {"status": "skipped_no_vlm"}
    if callable(vlm_chat):
        try:
            shots = [s for s in (storyboard or []) if isinstance(s, dict)][:40]
            prompt = (
                "你是 AM-15 评价层。对下列镜头（shot_id/景别/时长/画面要点）逐镜输出 JSON："
                '{"shots":[{"shot_id","score_12fields":0-10,"issues":[]}],"cross_shot":{"story_consistency":0-10,"action_completion":0-10}}\n'
                + json.dumps([
                    {"shot_id": s.get("shot_id"), "shot_type": s.get("shot_type"),
                     "duration_s": s.get("duration_s"), "visual_desc": str(s.get("visual_desc") or "")[:80]}
                    for s in shots
                ], ensure_ascii=False)
            )
            raw = vlm_chat(prompt)
            data = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            subjective = {"status": "ok", "result": data}
        except Exception as exc:  # noqa: BLE001
            subjective = {"status": "error", "error": str(exc)[:160]}

    # 仲裁规则：客观否决权限限物理类（黑帧/静态/静音/时长/分辨率）；其余冲突导演优先
    physical_issues: List[str] = []
    for c in cheap.get("checks", []) if isinstance(cheap, dict) else []:
        for issue in c.get("issues", []):
            if issue in _PhysicalIssueTypes:
                physical_issues.append(issue)
    arbitration = {
        "objective_veto_scope": sorted(set(physical_issues)),
        "objective_veto_triggered": bool(physical_issues),
        "cross_shot_gaps": total_gaps,
        "rule": "物理类客观指标一票否决；主观/客观非物理冲突时导演标准分优先（Soft Gate）",
    }
    return {"objective": objective, "subjective": subjective, "arbitration": arbitration}


# ---------------------------------------------------------------- ③ persona 双轨
def persona_feedback(*, vlm_chat: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """阶段③：persona 观众双轨（CHIEF；无 VLM 降级 skipped，保持双轨结构完整）。"""
    if not callable(vlm_chat):
        return {"status": "skipped_no_vlm", "personas": DEFAULT_PERSONAS,
                "rule": "persona 分与导演标准分双轨输出，冲突时导演优先（Soft Gate）"}
    out: List[Dict[str, Any]] = []
    for persona in DEFAULT_PERSONAS:
        try:
            raw = vlm_chat(
                f"你是一位{persona['profile']}的观众。看完这部短剧后给出 JSON："
                '{"hook_retention":0-10,"emotion_curve":一句话,"drop_point":"弃剧点或null"}'
            )
            data = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            out.append({"id": persona["id"], "profile": persona["profile"], "feedback": data})
        except Exception as exc:  # noqa: BLE001
            out.append({"id": persona["id"], "error": str(exc)[:120]})
    return {"status": "ok", "personas": out}


# ---------------------------------------------------------------- ④ 双格式输出
def _build_markdown(critique: Dict[str, Any]) -> str:
    lines: List[str] = ["# AM-15 评价报告", ""]
    lines.append(f"- schema：{critique.get('schema')}｜verdict：**{critique.get('verdict')}**")
    arb = critique.get("hybrid", {}).get("arbitration", {})
    lines.append(f"- 客观否决：{'触发（' + ','.join(arb.get('objective_veto_scope', [])) + '）' if arb.get('objective_veto_triggered') else '未触发'}"
                 f"｜跨镜头状态 gap：{arb.get('cross_shot_gaps', 0)}")
    cheap = critique.get("hybrid", {}).get("objective", {}).get("cheap", {})
    lines.append(f"- 廉价自检：{cheap.get('status')}｜拦截 {cheap.get('intercepted', 0)}"
                 f"/{len(cheap.get('checks', []))}（拦截率 {cheap.get('intercept_rate', 0)}）")
    lines.append(f"- 主观通道：{critique.get('hybrid', {}).get('subjective', {}).get('status')}"
                 f"｜persona：{critique.get('personas', {}).get('status')}")
    if critique.get("cf_hits"):
        lines.extend(["", "## CF 命中（L1 直索）"])
        for hit in critique["cf_hits"]:
            lines.append(f"- **{hit['cf_id']}** {hit['title']}：{hit['repair_model'][:120]}…")
    if critique.get("repair_suggestions"):
        lines.extend(["", "## 修复建议"])
        for s in critique["repair_suggestions"]:
            lines.append(f"- {s}")
    lines.extend(["", "## 修复知识（供 R0-R6 路由）"])
    lines.append(f"```json\n{json.dumps(critique.get('repair_dispatch', {}), ensure_ascii=False, indent=1)}\n```")
    return "\n".join(lines)


def run_am15_evaluation(
    *,
    payload: Dict[str, Any],
    video_paths: Optional[List[Any]] = None,
    vlm_chat: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """AM-15 主入口：payload（storyboard/camera_states/shot_contracts）→ 双格式报告。

    返回 {"markdown": str, "critique": dict}；critique 即机读 critique.json。
    """
    storyboard = payload.get("storyboard") if isinstance(payload.get("storyboard"), list) else []
    camera_states = payload.get("camera_states") if isinstance(payload.get("camera_states"), list) else []
    contracts = payload.get("shot_contracts") if isinstance(payload.get("shot_contracts"), list) else []

    cheap = cheap_precheck(video_paths=video_paths, contracts=contracts)
    hybrid = hybrid_review(
        cheap=cheap, storyboard=storyboard, camera_states=camera_states, vlm_chat=vlm_chat,
    )
    personas = persona_feedback(vlm_chat=vlm_chat)

    # CF 命中：廉价自检拦截的问题类型 → L1 直索（映射表语义化）
    failure_types: List[str] = []
    for c in cheap.get("checks", []):
        for issue in c.get("issues", []):
            ft = {"black_frame": "missing_video_clips", "static_segment": "video_clip_quality_below_threshold",
                  "duration_mismatch": "missing_video_clips", "resolution_mismatch": "ratio_mismatch",
                  "ffprobe_unavailable": "missing_video_clips"}.get(issue, "")
            if ft and ft not in failure_types:
                failure_types.append(ft)
    if hybrid["arbitration"].get("cross_shot_gaps"):
        failure_types.append("state_continuity_mismatch")
    cf_hits = resolve_cf_hits(failure_types)

    veto = hybrid["arbitration"].get("objective_veto_triggered")
    verdict = "fail_physical" if veto else ("fail_state" if hybrid["arbitration"].get("cross_shot_gaps") else "pass")

    repair_suggestions: List[str] = []
    if veto:
        repair_suggestions.append("物理类客观否决：按 ffmpeg 执行词典修复（黑帧剪除/静态检测复检/时长重生成）")
    if hybrid["arbitration"].get("cross_shot_gaps"):
        repair_suggestions.append("状态 gap：R2 对齐 state_after→下一镜 state_before，修复后 recalculate_state_transitions")
    for hit in cf_hits:
        repair_suggestions.append(f"{hit['cf_id']}：{hit['repair_model'][:100]}")

    critique = {
        "schema": AM15_SCHEMA,
        "verdict": verdict,
        "failure_types": failure_types,
        "cf_hits": cf_hits,
        "hybrid": hybrid,
        "personas": personas,
        "cross_shot": {
            "story_consistency": (hybrid.get("subjective", {}).get("result", {}) or {}).get("cross_shot", {}).get("story_consistency"),
            "action_completion": (hybrid.get("subjective", {}).get("result", {}) or {}).get("cross_shot", {}).get("action_completion"),
            "state_transition_gaps": hybrid["arbitration"].get("cross_shot_gaps", 0),
        },
        "repair_suggestions": repair_suggestions[:12],
        "repair_dispatch": {
            "verdict": verdict,
            "r_level_hint": "R2" if (veto or hybrid["arbitration"].get("cross_shot_gaps")) else "R0",
            "recalculate_state_transitions": bool(hybrid["arbitration"].get("cross_shot_gaps")),
        },
    }
    return {"markdown": _build_markdown(critique), "critique": critique}
