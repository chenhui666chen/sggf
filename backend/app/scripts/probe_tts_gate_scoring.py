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

用法（backend/ 下）：
    python -m app.scripts.probe_tts_gate_scoring                      # 盲评干跑，只列将发送的 prompt
    python -m app.scripts.probe_tts_gate_scoring --confirm-paid       # 真实盲评
    python -m app.scripts.probe_tts_gate_scoring --mode anchored --confirm-paid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


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

PROBE_DIR = PROJECT_ROOT / "backend/data/tts_debug/gate_probe_g1_g7"
MANIFEST = PROBE_DIR / "manifest.json"
OUT_JSON = PROBE_DIR / "scores.json"
OUT_SHEET = PROBE_DIR / "listening_sheet.md"
OUT_JSON_BLIND = PROBE_DIR / "scores_blind.json"
OUT_SHEET_BLIND = PROBE_DIR / "blind_sheet.md"

# 情绪/表演维度采信方，与可验证维度采信方；分工的唯一事实源是 audio_score_contract。
EMOTION_SCORER = EMOTION_AUTHORITY_MODEL
VERIFIABLE_SCORER = VERIFIABLE_AUTHORITY_MODEL
SCORERS = (EMOTION_SCORER, VERIFIABLE_SCORER)

# 用户已作出的人耳裁定，作为盲评结论的对照真值。
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


# 只送需要"耳朵判断"的门槛对；纯客观已判定的（时长/转写）不进评分。
TARGETS: List[Target] = [
    Target("g1a_qwen3_none", "我没事。我真的没事，你们都不用管我。", "未下达任何表演指令，按台词字面自然朗读即可。"),
    Target("g1b_qwen3_sad", "我没事。我真的没事，你们都不用管我。", "极其克制压抑的悲伤，语速偏慢，句尾下沉，几乎不带哭腔。"),
    Target("g1c_qwen3_happy", "我没事。我真的没事，你们都不用管我。", "明快雀跃，语速偏快，句尾上扬，带着笑意。"),
    Target("g2a_minimax_calm", "好吧，既然你都这么说了，那就是我多管闲事了。", "emotion=calm：平静、不带情绪的陈述。"),
    Target("g2b_minimax_sad", "好吧，既然你都这么说了，那就是我多管闲事了。", "emotion=sad：低落、委屈、有失落感。"),
    Target("g4a_seed_plain", "所以从一开始，你就在骗我。", "无指令基线：按台词字面自然朗读。"),
    Target("g4b_seed_context", "所以从一开始，你就在骗我。", "她压着怒气，声音很低，一字一句地说（低音量、克制怒火、逐字清晰）。"),
    Target("g5d_seed_plain_control", "你怎么还不走？", "无标签基线：按台词字面自然朗读。"),
    Target("g5b_seed_cot", "你怎么还不走？", "Cot 标签指定焦急难耐：应表现为着急、语速偏快、气息变短。"),
    Target("g6a_mimo_angry", "你到底想怎么样？", "愤怒：外放的火气，重音强，语气冲。"),
    Target("g6b_mimo_suppressed", "你到底想怎么样？", "压抑的愤怒：怒火被压住，音量不高、咬字紧、句尾收住。"),
    Target("g7a_audio_instruction", "我真的没事，你们都不用管我。", "悲伤克制，语速偏慢，句尾下沉。"),
    Target("g7b_audio_tags", "我真的没事，你们都不用管我。", "指令为悲伤克制，但正文带 [excited] 标签；请判断标签是否带来可听的兴奋/明亮变化。"),
]


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
    args = parser.parse_args()

    blind = args.mode == "blind"
    out_json = OUT_JSON_BLIND if blind else OUT_JSON
    out_sheet = OUT_SHEET_BLIND if blind else OUT_SHEET

    keys = _api_keys()
    rows = _manifest_rows()

    print(f"模式: {'盲评（不透露表演要求）' if blind else '锚定（含表演要求）'}")
    print(f"采信分工: 情绪/表演维度 → {EMOTION_SCORER}；fidelity/contamination → {VERIFIABLE_SCORER}")
    print(f"待评音频 {len(TARGETS)} 条 × {len(SCORERS)} 个评分模型 = {len(TARGETS) * len(SCORERS)} 次调用")
    for model in SCORERS:
        print(f"  {model} key: {'ok' if keys.get(model) else 'missing'}")

    if not args.confirm_paid:
        for t in TARGETS:
            prompt = _blind_prompt(t.line) if blind else _rubric_prompt(t.line, t.asked)
            print(f"\n[{t.key}] {_audio_for(t.key).name}\n{prompt[:200]}...")
        return 0

    results: List[Dict[str, Any]] = []
    for t in TARGETS:
        path = _audio_for(t.key)
        prompt = _blind_prompt(t.line) if blind else _rubric_prompt(t.line, t.asked)
        entry: Dict[str, Any] = {
            "key": t.key,
            "gate": (rows.get(t.key) or {}).get("gate"),
            "channel": (rows.get(t.key) or {}).get("channel"),
            "line": t.line,
            "asked": t.asked,
            "mode": args.mode,
            "audio_file": path.relative_to(PROJECT_ROOT).as_posix(),
            "duration_ms": (rows.get(t.key) or {}).get("duration_ms"),
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
        "# G1–G7 门槛听辨表（锚定模式；仅用于复现指令回声偏差，不作为结论来源）",
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
        f"# G1–G7 门槛盲评对照表（评分模型看不到表演要求；情绪维度采信 {EMOTION_SCORER}）",
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
