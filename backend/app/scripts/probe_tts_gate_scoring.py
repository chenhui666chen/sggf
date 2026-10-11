"""门槛/写法音频的离线评分调用器（付费；作为档案复测入口长期留存，不随任务清理）。

复用 `scene_quality.omni_audio_scorer.score_audio`（离线、单次、严格 JSON 合同），
组合按 2026-10-10 已裁定口径（docs/TTS_PROMPT_EVIDENCE_20261010.md §9.1）：

- **情绪与表演维度只采信 doubao-seed-2-1-lite**：qwen3.8-omni-flash 被盲评复测证实会把
  提示词里的表演要求复述成"听感"，同文本同音色的无指令基线也被它描述成"哭腔、颤抖"。
- **qwen3.8-omni-flash 只负责 fidelity / contamination** 这类能与 ASR 逐字转写交叉验证的维度。
- 两个都不是真值：与人耳冲突时以人耳为准，评分器正向证据不得单独作为"提示词有效"的结论。

分工由 `audio_score_contract.tts_dimension_authority` 单点定义，本脚本只负责呈现。

留存理由：`docs/MODEL_INTEGRATION_REFERENCE.md` §11.10 的盲评采信分工与
`docs/TTS_PROMPT_EVIDENCE_20261010.md` 的评分批次都以此为复现入口，且评分原始响应不长期留存。

两种模式（默认 **盲评**）：
- `--mode blind`（默认）：不给指令，只要求模型描述实际听到的情绪与韵律，指令仅写进对照表供人工判定。
- `--mode anchored`：把本轮下达的表演要求一起交给评分模型。已证实会让 qwen3.8 把指令复述成听感，
  只用于复现该偏差，不作为结论来源。

用法（backend/ 下，待评清单与产物路径都由 `--probe-dir` 决定，默认 B3 批次）：
    python -m app.scripts.probe_tts_gate_scoring                                  # 盲评干跑，只列将发送的 prompt
    python -m app.scripts.probe_tts_gate_scoring --confirm-paid                   # 真实盲评
    python -m app.scripts.probe_tts_gate_scoring --probe-dir backend/data/tts_debug/b3_qwen31_writing_r2 --confirm-paid
    python -m app.scripts.probe_tts_gate_scoring --key q4_qwen31_baseline,q1_qwen31_director --confirm-paid  # 审计锚
    python -m app.scripts.probe_tts_gate_scoring --mode anchored --confirm-paid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap_environment() -> tuple[Path, Path]:
    backend_root = Path(__file__).resolve().parents[2]
    project_root = backend_root.parent
    for path in (backend_root, project_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from app.core.env_loader import load_project_env

    load_project_env(override=False)
    return project_root, backend_root


PROJECT_ROOT, BACKEND_ROOT = _bootstrap_environment()

from app.services.audiobook.scene_quality.audio_score_contract import (  # noqa: E402
    EMOTION_AUTHORITY_MODEL,
    TTS_DIMENSIONS,
    VERIFIABLE_AUTHORITY_MODEL,
    tts_dimension_authority,
)
from app.services.audiobook.scene_quality.omni_audio_scorer import score_audio  # noqa: E402

PROBE_DIR = PROJECT_ROOT / "backend/data/tts_debug/b3_qwen31_writing"
MANIFEST = PROBE_DIR / "manifest.json"
OUT_JSON = PROBE_DIR / "scores.json"
OUT_SHEET = PROBE_DIR / "listening_sheet.md"
OUT_JSON_BLIND = PROBE_DIR / "scores_blind.json"
OUT_SHEET_BLIND = PROBE_DIR / "blind_sheet.md"


def _apply_paths(probe_dir: Path, manifest_path: Optional[Path] = None) -> None:
    """评分结果与听辨表一律落在批次目录内，`--tag r2` 这类多轮目录天然隔离。"""
    global PROBE_DIR, MANIFEST, OUT_JSON, OUT_SHEET, OUT_JSON_BLIND, OUT_SHEET_BLIND
    PROBE_DIR = probe_dir
    MANIFEST = manifest_path or (probe_dir / "manifest.json")
    OUT_JSON = probe_dir / "scores.json"
    OUT_SHEET = probe_dir / "listening_sheet.md"
    OUT_JSON_BLIND = probe_dir / "scores_blind.json"
    OUT_SHEET_BLIND = probe_dir / "blind_sheet.md"


# 情绪/表演维度采信方，与可验证维度采信方；分工的唯一事实源是 audio_score_contract。
EMOTION_SCORER = EMOTION_AUTHORITY_MODEL
VERIFIABLE_SCORER = VERIFIABLE_AUTHORITY_MODEL
SCORERS = (EMOTION_SCORER, VERIFIABLE_SCORER)

# 用户已作出的人耳裁定，作为盲评结论的对照真值。历史批次目录已丢失，
# 这三条是 G1–G7 仅存的真值锚，重跑同 key 音频时仍用于对照评分器漂移。
HUMAN_RULING = {
    "g1b_qwen3_sad": "语气无低落感、句尾没下沉，等于没实现",
    "g4b_seed_context": "整体轻快平淡，没实现",
    "g6a_mimo_angry": "声音温婉平缓、重音弱",
}


@dataclass(frozen=True)
class Target:
    key: str
    line: str
    asked: str
    gate: str = ""
    channel: str = ""
    duration_ms: Optional[int] = None


def _targets_from_manifest(
    line_override: str = "", wanted: Optional[set] = None
) -> List[Target]:
    """待评清单来自批次 manifest：只送真正出了音频、且能确定逐字台词的条目。

    `spoken_text` 由探测脚本写入（正文带标签的写法必须显式给干净台词，
    否则 fidelity 会把标签当成漏字）。旧批次缺该字段时用 `--line` 补，
    补不上就报错，不猜。
    """
    if not MANIFEST.exists():
        raise SystemExit(f"manifest 不存在：{MANIFEST}（先用 probe_tts_capability_gates 跑批次）")
    targets: List[Target] = []
    all_keys: set = set()
    for row in json.loads(MANIFEST.read_text(encoding="utf-8")):
        key = str(row.get("key") or "")
        if not key:
            continue
        all_keys.add(key)
        if wanted and key not in wanted:
            continue
        line = str(row.get("spoken_text") or line_override or "").strip()
        if not line:
            raise SystemExit(f"{key} 缺 spoken_text，且未传 --line：无法确定逐字台词")
        targets.append(
            Target(
                key=key,
                line=line,
                asked=str(row.get("question") or ""),
                gate=str(row.get("gate") or ""),
                channel=str(row.get("channel") or ""),
                duration_ms=row.get("duration_ms"),
            )
        )
    if wanted:
        unknown = sorted(wanted - all_keys)
        if unknown:
            raise SystemExit(f"--key 不在本批次 manifest 里：{unknown}")
    if not targets:
        raise SystemExit(f"manifest 里没有可评条目：{MANIFEST}")
    return targets


def _rubric_prompt(line: str, asked: str) -> str:
    return (
        "你是有声书配音质检员。下面这一段音频只有一句话，请只依据听到的内容评分。\n"
        f"台词原文（逐字）：{line}\n"
        f"本轮下达的表演要求：{asked}\n\n"
        "评分维度（1=完全不达标，5=完全达标）：\n"
        "emotion_match：是否实现上述表演要求的情绪与语气（这是主指标，表演要求未下达时按字面自然度评）。\n"
        "prosody_pause：语速、停顿、断句、句尾处理是否自然且符合表演要求。\n"
        "fidelity：是否与台词原文逐字一致，无漏字、无加字、无改写。\n"
        "contamination：是否念出了与台词无关的内容（方括号/尖括号标签词、参数名、提示词残留）。分数越高表示污染越少。\n"
        "voice_identity：本次只给单条片段，无法判断跨片段一致性，必须给 null。\n"
        "overall_naturalness：整体听起来是否像真人在表演（类 MOS）。\n\n"
        "每个维度都要给一句不超过 40 字的证据，并给 0 到 1 的置信度。\n"
        '只输出严格 JSON，不要输出任何其他文字，格式：\n'
        '{"dimensions":{'
        '"emotion_match":{"score":1,"evidence":"...","confidence":0.5},'
        '"prosody_pause":{"score":1,"evidence":"...","confidence":0.5},'
        '"fidelity":{"score":1,"evidence":"...","confidence":0.5},'
        '"contamination":{"score":1,"evidence":"...","confidence":0.5},'
        '"voice_identity":{"score":null,"evidence":"单片段无法判断","confidence":1.0},'
        '"overall_naturalness":{"score":1,"evidence":"...","confidence":0.5}}}'
    )


def _blind_prompt(line: str) -> str:
    return (
        "你是有声书配音质检员。下面这一段音频只有一句话。"
        "你不知道、也不要去猜这句话原本的表演要求或提示词，只报告你真实听到的内容。\n"
        f"台词原文（逐字）：{line}\n\n"
        "评分维度（1=最差，5=最好）：\n"
        "emotion_match：先说你听到的具体情绪与其可听线索（情绪种类、音高走向、句尾是下沉还是上扬、有无哭腔或笑意），"
        "分数表示情绪表达的鲜明程度（1=平直几乎无情绪，5=情绪鲜明、细节清楚）。禁止使用\"符合要求\"\"按要求\"这类措辞。\n"
        "prosody_pause：实际语速、停顿位置、断句与句尾处理，分数表示这些韵律线索的丰富与自然程度。\n"
        "fidelity：是否与台词原文逐字一致，无漏字、无加字、无改写。\n"
        "contamination：是否念出了与台词无关的内容（方括号/尖括号标签词、参数名、提示词残留）。分数越高表示污染越少。\n"
        "voice_identity：本次只给单条片段，无法判断跨片段一致性，必须给 null。\n"
        "overall_naturalness：整体听起来是否像真人在表演（类 MOS）。\n\n"
        "每个维度都要给一句不超过 40 字的证据，证据必须是可听描述，不能是推测；并给 0 到 1 的置信度。\n"
        '只输出严格 JSON，不要输出任何其他文字，格式：\n'
        '{"dimensions":{'
        '"emotion_match":{"score":1,"evidence":"...","confidence":0.5},'
        '"prosody_pause":{"score":1,"evidence":"...","confidence":0.5},'
        '"fidelity":{"score":1,"evidence":"...","confidence":0.5},'
        '"contamination":{"score":1,"evidence":"...","confidence":0.5},'
        '"voice_identity":{"score":null,"evidence":"单片段无法判断","confidence":1.0},'
        '"overall_naturalness":{"score":1,"evidence":"...","confidence":0.5}}}'
    )


def _repo_rel(path: Path) -> str:
    """relative_to 对仓库外路径会抛 ValueError，降级为绝对路径而不是中断评分。"""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _audio_for(key: str) -> Path:
    hits = sorted(PROBE_DIR.glob(f"{key}.*"))
    wav = [p for p in hits if p.suffix in {".wav", ".mp3"}]
    if not wav:
        raise FileNotFoundError(key)
    return wav[0]


def _manifest_rows() -> Dict[str, Dict[str, Any]]:
    if not MANIFEST.exists():
        return {}
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {str(r.get("key")): r for r in rows}


def _api_keys() -> Dict[str, str]:
    qwen_key = (os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY") or "").strip()
    doubao_key = (os.getenv("VOLCENGINE_API_KEY") or os.getenv("DOUBAO_API_KEY") or "").strip()
    return {VERIFIABLE_SCORER: qwen_key, EMOTION_SCORER: doubao_key}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid", action="store_true", help="真实发出评分请求（会扣费）")
    parser.add_argument(
        "--mode",
        choices=("blind", "anchored"),
        default="blind",
        help="blind＝不给评分模型看表演要求（默认，也是唯一可作为结论的模式）；"
        "anchored＝把要求一起交出去，仅用于复现 qwen3.8 的指令回声偏差",
    )
    parser.add_argument(
        "--probe-dir",
        default="",
        help="批次目录（内有 manifest.json 与该批音频）；相对路径按仓库根解析，"
        "默认 backend/data/tts_debug/b3_qwen31_writing",
    )
    parser.add_argument("--manifest", default="", help="manifest 路径覆盖，默认 <probe-dir>/manifest.json")
    parser.add_argument(
        "--line",
        default="",
        help="逐字台词覆盖：仅用于 manifest 里没有 spoken_text 的旧批次（整批同一台词时才可用）",
    )
    parser.add_argument(
        "--key", default="", help="只评这些 key（逗号分隔），用于按审计锚协议抽 1–2 条送评"
    )
    args = parser.parse_args()

    probe_dir = Path(args.probe_dir) if args.probe_dir else PROBE_DIR
    if not probe_dir.is_absolute():
        probe_dir = PROJECT_ROOT / probe_dir
    _apply_paths(probe_dir, Path(args.manifest) if args.manifest else None)

    blind = args.mode == "blind"
    out_json = OUT_JSON_BLIND if blind else OUT_JSON
    out_sheet = OUT_SHEET_BLIND if blind else OUT_SHEET

    targets = _targets_from_manifest(args.line, {k.strip() for k in args.key.split(",") if k.strip()} or None)

    keys = _api_keys()
    rows = _manifest_rows()

    print(f"批次目录: {_repo_rel(probe_dir)}")
    print(f"模式: {'盲评（不透露表演要求）' if blind else '锚定（含表演要求）'}")
    print(f"采信分工: 情绪/表演维度 → {EMOTION_SCORER}；fidelity/contamination → {VERIFIABLE_SCORER}")
    print(f"待评音频 {len(targets)} 条 × {len(SCORERS)} 个评分模型 = {len(targets) * len(SCORERS)} 次调用")
    for model in SCORERS:
        print(f"  {model} key: {'ok' if keys.get(model) else 'missing'}")

    if not args.confirm_paid:
        for t in targets:
            prompt = _blind_prompt(t.line) if blind else _rubric_prompt(t.line, t.asked)
            print(f"\n[{t.key}] {_audio_for(t.key).name}\n{prompt[:200]}...")
        return 0

    results: List[Dict[str, Any]] = []
    for t in targets:
        path = _audio_for(t.key)
        prompt = _blind_prompt(t.line) if blind else _rubric_prompt(t.line, t.asked)
        entry: Dict[str, Any] = {
            "key": t.key,
            "gate": t.gate or (rows.get(t.key) or {}).get("gate"),
            "channel": t.channel or (rows.get(t.key) or {}).get("channel"),
            "line": t.line,
            "asked": t.asked,
            "mode": args.mode,
            "audio_file": _repo_rel(path),
            "duration_ms": t.duration_ms if t.duration_ms is not None else (rows.get(t.key) or {}).get("duration_ms"),
            "authority": {name: tts_dimension_authority(name) for name in TTS_DIMENSIONS},
            "scorers": {},
        }
        for model in SCORERS:
            key = keys.get(model, "")
            if not key:
                entry["scorers"][model] = {"status": "skipped", "error_kind": "missing_key"}
                continue
            outcome = score_audio(
                audio_path=path, prompt=prompt, model=model, kind="tts", scope="single_clip", api_key=key
            )
            entry["scorers"][model] = {
                "status": outcome.status,
                "error_kind": outcome.error_kind,
                "usage": dict(outcome.usage) if outcome.usage else None,
                "dimensions": (
                    {
                        name: {
                            "score": dim.score,
                            "evidence": dim.evidence,
                            "confidence": round(dim.confidence, 3),
                        }
                        for name, dim in outcome.score.dimensions.items()
                    }
                    if outcome.score
                    else None
                ),
            }
        results.append(entry)
        print(f"  scored {t.key}")

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if blind:
        _write_blind_sheet(results, rows)
    else:
        _write_sheet(results, rows)
    print(f"\nscores: {out_json}\nsheet:  {out_sheet}")
    return 0


def _role_label(model: str) -> str:
    return "情绪采信" if model == EMOTION_SCORER else "可验证采信"


def _other_scorer(model: str) -> str:
    return next((other for other in SCORERS if other != model), "")


def _write_sheet(results: List[Dict[str, Any]], rows: Dict[str, Dict[str, Any]]) -> None:
    dims = ("emotion_match", "prosody_pause", "fidelity", "contamination", "overall_naturalness")
    lines = [
        f"# {PROBE_DIR.name} 听辨表（锚定模式；仅用于复现指令回声偏差，不作为结论来源）",
        "",
        f"采信分工：情绪/表演维度 → {EMOTION_SCORER}；fidelity/contamination → {VERIFIABLE_SCORER}。",
        "本模式把表演要求一起交给了评分模型，已证实 qwen3.8 会据此编造听感，故\"采信\"列在锚定模式下不可信。",
        "评分只回答\"指令是否被实现\"；两模型给分不一致时以人耳裁定为准，不做合成分。",
        "",
    ]
    for entry in results:
        lines.append(f"## {entry['key']}（{entry['gate']} / {entry['channel']}）")
        lines.append("")
        lines.append(f"- 台词：{entry['line']}")
        lines.append(f"- 表演要求：{entry['asked']}")
        lines.append(
            f"- 音频：{entry['audio_file']}（{entry.get('duration_ms') or '-'} ms，"
            f"request_id={rows.get(entry['key'], {}).get('request_id') or '-'}）"
        )
        lines.append("")
        lines.append("| 维度 | 采信方 | 采信分 | 采信证据 | 参照方 | 参照分 |")
        lines.append("|---|---|---|---|---|---|")
        for dim in dims:
            authority = tts_dimension_authority(dim)
            other = _other_scorer(authority)
            ad = ((entry["scorers"].get(authority) or {}).get("dimensions") or {}).get(dim, {})
            od = ((entry["scorers"].get(other) or {}).get("dimensions") or {}).get(dim, {})
            lines.append(
                f"| {dim} | {authority} | {ad.get('score', '-')} | {str(ad.get('evidence', ''))[:60]} "
                f"| {other} | {od.get('score', '-')} |"
            )
        lines.append("")
    OUT_SHEET.write_text("\n".join(lines), encoding="utf-8")


def _write_blind_sheet(results: List[Dict[str, Any]], rows: Dict[str, Dict[str, Any]]) -> None:
    """盲评表：把"模型听到的情绪描述"与"当初下达的指令"并排，判定留给人工。"""
    anchored: Dict[str, Dict[str, Any]] = {}
    if OUT_JSON.exists():
        for entry in json.loads(OUT_JSON.read_text(encoding="utf-8")):
            anchored[str(entry.get("key"))] = entry

    def _dims(entry: Dict[str, Any], model: str) -> Dict[str, Any]:
        scorers = entry.get("scorers") or {}
        return (scorers.get(model) or {}).get("dimensions") or {}

    lines = [
        f"# {PROBE_DIR.name} 盲评对照表（评分模型看不到表演要求；情绪维度采信 {EMOTION_SCORER}）",
        "",
        "盲评目的：检验主评此前的正向证据是否只是把提示词里的指令复述成听感。",
        "判定方式：比较\"盲评听到的情绪\"与\"当初下达的指令\"，并对照人耳裁定；两列分数不同不代表音频变了。",
        f"采信分工：情绪/表演维度 → {EMOTION_SCORER}；fidelity/contamination → {VERIFIABLE_SCORER}；人耳为最终真值。",
        "",
    ]
    for entry in results:
        key = entry["key"]
        old = anchored.get(key, {})
        lines.append(f"## {key}（{entry['gate']} / {entry['channel']}，{entry.get('duration_ms') or '-'} ms）")
        lines.append("")
        lines.append(f"- 下达指令（模型未见到）：{entry['asked']}")
        lines.append(f"- 人耳裁定：{HUMAN_RULING.get(key, '尚未听辨')}")
        lines.append("")
        lines.append("| 采信角色 | 模型 | 盲评 emotion | 盲评听到的 | 锚定 emotion | 锚定时说的 |")
        lines.append("|---|---|---|---|---|---|")
        for model in SCORERS:
            now = _dims(entry, model).get("emotion_match") or {}
            was = _dims(old, model).get("emotion_match") or {}
            lines.append(
                f"| {_role_label(model)} {model} | {model} | {now.get('score', '-')} "
                f"| {str(now.get('evidence', ''))[:60]} "
                f"| {was.get('score', '-')} | {str(was.get('evidence', ''))[:60]} |"
            )
        lines.append("")
        lines.append(
            "| 采信角色 | 模型 | prosody_pause | fidelity | contamination | naturalness |"
        )
        lines.append("|---|---|---|---|---|---|")
        for model in SCORERS:
            dims = _dims(entry, model)
            cells = [
                str(((dims.get(d) or {}).get("score")) or "-")
                for d in ("prosody_pause", "fidelity", "contamination", "overall_naturalness")
            ]
            lines.append(f"| {_role_label(model)} {model} | {model} | " + " | ".join(cells) + " |")
        lines.append("")
    OUT_SHEET_BLIND.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
