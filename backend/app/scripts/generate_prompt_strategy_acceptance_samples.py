"""Generate UTF-8 TTS prompt-strategy acceptance samples.

This script is intentionally small and local-only: it uses the current
audiobook TTS style-control pipeline, calls the configured real providers, and
writes playable samples plus review scaffolding under backend/data/tts_debug.

Run from backend/:
    python -m app.scripts.generate_prompt_strategy_acceptance_samples --run-asr
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


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


from app.services.audiobook.cosyvoice_clone_client import COSYVOICE_V35_PLUS_MODEL_ID  # noqa: E402
from app.services.audiobook.prompt_audio_asr_provider import (  # noqa: E402
    MiMoPromptAudioAsrProvider,
    PromptAudioAsrProviderError,
)
from app.services.audiobook.tts_delivery_plan import build_delivery_plan  # noqa: E402
from app.services.audiobook.tts_engine import RetryConfig, TTSEngine  # noqa: E402
from app.services.audiobook.tts_model_ids import (  # noqa: E402
    MIMO_V25_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
)
from app.services.audiobook.tts_style_control import (  # noqa: E402
    build_model_style_control,
    build_provider_prompt_snapshot,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/prompt_strategy_acceptance_utf8"
DEFAULT_COSYVOICE_VOICE_ID = "cosyvoice-v3.5-plus-vc25dfd3e-d15265b4a4f74c7996ffa3faa097ee21"
DEFAULT_STEP_AUDIO_VOICE_ID = "cixingnansheng"
DEFAULT_MIMO_VOICE_ID = "mimo_default"
DEFAULT_DOUBAO_VOICE_ID = "saturn_zh_female_keainvsheng_tob"


@dataclass(frozen=True)
class AcceptanceCase:
    id: str
    group: str
    provider: str
    model: str
    speaker: str
    case_name: str
    text: str
    segment_type: str
    segment_speaker: str
    emotion: str
    role: str
    scene: str
    performance_notes: str
    voice_description: str = ""
    style_control_method: str = ""
    style_tags: list[str] = field(default_factory=list)
    inline_audio_tags: list[str] = field(default_factory=list)
    delivery_plan_overrides: dict[str, Any] = field(default_factory=dict)


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cosyvoice_voice_id() -> str:
    return (
        os.getenv("AUDIOBOOK_COSYVOICE_SMOKE_VOICE_ID")
        or os.getenv("COSYVOICE_ACCEPTANCE_VOICE_ID")
        or DEFAULT_COSYVOICE_VOICE_ID
    ).strip()


def _stepaudio_voice_id() -> str:
    return (os.getenv("STEPAUDIO_ACCEPTANCE_VOICE_ID") or DEFAULT_STEP_AUDIO_VOICE_ID).strip()


def _mimo_voice_id() -> str:
    return (os.getenv("MIMO_ACCEPTANCE_VOICE_ID") or DEFAULT_MIMO_VOICE_ID).strip()


def _doubao_voice_id() -> str:
    return (os.getenv("DOUBAO_ACCEPTANCE_VOICE_ID") or DEFAULT_DOUBAO_VOICE_ID).strip()


def _p1_cases(*, cosyvoice_voice_id: str, stepaudio_voice_id: str) -> list[AcceptanceCase]:
    base_cases = [
        {
            "case_name": "narration_pause",
            "text": "雾从旧城区的屋檐滑下来，钟楼停了三秒，才把第一声更鼓送进长街。",
            "segment_type": "narration",
            "segment_speaker": "旁白",
            "emotion": "tense",
            "role": "冷静克制的有声书旁白",
            "scene": "雨夜旧城，钟楼声像从很远的地方传来。",
            "performance_notes": "放慢语速，句中留白明显，最后四个字轻轻落下。",
            "delivery_plan_overrides": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "low",
                "pause_strategy": "钟楼停顿后留一段可感知空白",
                "pause_profile": "dramatic",
                "pause_after": 0.8,
            },
        },
        {
            "case_name": "dialogue_whisper",
            "text": "别回头，灯影里站着的那个人，不一定还活着。",
            "segment_type": "dialogue",
            "segment_speaker": "林晚",
            "emotion": "fearful",
            "role": "强作镇定的年轻调查员",
            "scene": "狭窄走廊尽头，灯光忽明忽暗。",
            "performance_notes": "压低声音，近耳低语，紧张但克制，句尾不要上扬。",
            "inline_audio_tags": ["低语"],
            "delivery_plan_overrides": {
                "delivery_mode": "whisper",
                "pace": "slow",
                "intensity": "low",
                "pause_profile": "dramatic",
                "emotion_mix": ["紧张"],
                "micro_tags": ["低语"],
            },
        },
        {
            "case_name": "inner_monologue",
            "text": "她忽然明白，那封没有署名的信，其实早就替她做出了选择。",
            "segment_type": "monologue",
            "segment_speaker": "林晚",
            "emotion": "sad",
            "role": "外表冷静、内心疲惫的年轻女性",
            "scene": "窗边只剩一盏台灯，信纸被风轻轻掀起。",
            "performance_notes": "内心独白，气息轻，前半慢，后半更轻，避免戏剧化哭腔。",
            "delivery_plan_overrides": {
                "delivery_mode": "monologue",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["疲惫", "悲伤"],
            },
        },
        {
            "case_name": "tense_reveal",
            "text": "盒盖打开的一瞬间，所有人的呼吸都停住了。里面没有钥匙，只有一枚新鲜的指纹。",
            "segment_type": "narration",
            "segment_speaker": "旁白",
            "emotion": "surprised",
            "role": "悬疑故事旁白",
            "scene": "密室中央，所有视线都压在那只木盒上。",
            "performance_notes": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
            "delivery_plan_overrides": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "medium",
                "pause_profile": "dramatic",
                "stress_words": ["新鲜的指纹"],
            },
        },
        {
            "case_name": "quiet_resolution",
            "text": "天亮以前，她把伞留在门边，像把这一夜的秘密，也一并还给了雨声。",
            "segment_type": "narration",
            "segment_speaker": "旁白",
            "emotion": "calm",
            "role": "温柔克制的收束旁白",
            "scene": "清晨前的院落，雨势慢慢变小。",
            "performance_notes": "温柔收束，尾句留白，不要煽情，声音逐渐放轻。",
            "delivery_plan_overrides": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "low",
                "pause_after": 0.6,
            },
        },
    ]

    result: list[AcceptanceCase] = []
    for index, item in enumerate(base_cases, start=1):
        result.append(
            AcceptanceCase(
                id=f"p1_cosyvoice_{index:02d}_{item['case_name']}",
                group="P1 CosyVoice pause/template",
                provider="aliyun_dashscope",
                model=COSYVOICE_V35_PLUS_MODEL_ID,
                speaker=cosyvoice_voice_id,
                voice_description="性别：男性，年龄感：青年，音调：偏低，语速：中速，情绪：克制，特点：沙哑、有磁性，用途：有声书旁白或对白。",
                **item,
            )
        )
        result.append(
            AcceptanceCase(
                id=f"p1_stepaudio_{index:02d}_{item['case_name']}",
                group="P1 StepAudio pause/template",
                provider="stepfun",
                model=STEPAUDIO_25_TTS_MODEL,
                speaker=stepaudio_voice_id,
                voice_description="性别：男性，年龄感：青年，音调：偏低，语速：中速，情绪：克制，特点：沙哑、有磁性，用途：有声书旁白或对白。",
                **item,
            )
        )
    return result


def _p2_cases(*, mimo_voice_id: str, doubao_voice_id: str) -> list[AcceptanceCase]:
    tag_cases = [
        {
            "case_name": "tag_whisper",
            "text": "别出声，门外的脚步停在我们身后。",
            "emotion": "fearful",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["低语"],
            "performance_notes": "低语，气声更明显，紧张但不要尖叫。",
            "delivery_plan_overrides": {
                "delivery_mode": "whisper",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["紧张"],
                "micro_tags": ["低语"],
            },
        },
        {
            "case_name": "tag_sob",
            "text": "我不是不想回去，只是那里再也没有人在等我了。",
            "emotion": "sad",
            "style_tags": ["悲伤"],
            "inline_audio_tags": ["哽咽"],
            "performance_notes": "轻微哽咽，保持可懂度，不要拖成长哭。",
            "delivery_plan_overrides": {
                "delivery_mode": "sob",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["悲伤", "委屈"],
                "micro_tags": ["哽咽"],
            },
        },
        {
            "case_name": "tag_laugh",
            "text": "你看，他连谎话都说得这么认真。",
            "emotion": "happy",
            "style_tags": ["轻松"],
            "inline_audio_tags": ["轻笑"],
            "performance_notes": "轻笑带一点讽刺，短促，不要读成大笑。",
            "delivery_plan_overrides": {
                "delivery_mode": "laugh",
                "pace": "medium",
                "intensity": "medium",
                "emotion_mix": ["轻松"],
                "micro_tags": ["轻笑"],
            },
        },
        {
            "case_name": "tag_shout",
            "text": "停下！谁都不许再靠近那扇门。",
            "emotion": "angry",
            "style_tags": ["愤怒"],
            "inline_audio_tags": ["大喊"],
            "performance_notes": "短促大喊，有制止感，后半句保持清晰。",
            "delivery_plan_overrides": {
                "delivery_mode": "shout",
                "pace": "fast",
                "intensity": "high",
                "emotion_mix": ["愤怒"],
                "micro_tags": ["大喊"],
            },
        },
        {
            "case_name": "tag_sigh",
            "text": "算了，等风过去，我们再谈这件事。",
            "emotion": "calm",
            "style_tags": ["疲惫"],
            "inline_audio_tags": ["叹气"],
            "performance_notes": "先轻轻叹气，再平静说完，尾音放低。",
            "delivery_plan_overrides": {
                "delivery_mode": "dialogue",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["疲惫"],
                "micro_tags": ["叹气"],
            },
        },
    ]

    result: list[AcceptanceCase] = []
    for index, item in enumerate(tag_cases, start=1):
        shared = {
            "segment_type": "dialogue",
            "segment_speaker": "林晚",
            "role": "强作镇定但情绪外露的年轻女性",
            "scene": "封闭房间里，门外传来无法确认的声响。",
            "style_control_method": "audio_tags",
            "voice_description": "性别：女性，年龄感：青年，音调：偏高，语速：中速，特点：清晰、细腻，适合有声书角色对白。",
            **item,
        }
        result.append(
            AcceptanceCase(
                id=f"p2_mimo_{index:02d}_{item['case_name']}",
                group="P2 MiMo tag parser",
                provider="mimo",
                model=MIMO_V25_TTS_MODEL,
                speaker=mimo_voice_id,
                **shared,
            )
        )
        result.append(
            AcceptanceCase(
                id=f"p2_doubao_{index:02d}_{item['case_name']}",
                group="P2 Doubao tag parser",
                provider="volcengine",
                model=SEED_TTS_20_EXPRESSIVE_MODEL,
                speaker=doubao_voice_id,
                **shared,
            )
        )
    return result


def build_cases() -> list[AcceptanceCase]:
    return [
        *_p1_cases(
            cosyvoice_voice_id=_cosyvoice_voice_id(),
            stepaudio_voice_id=_stepaudio_voice_id(),
        ),
        *_p2_cases(
            mimo_voice_id=_mimo_voice_id(),
            doubao_voice_id=_doubao_voice_id(),
        ),
    ]


def _build_voice_params(case: AcceptanceCase) -> tuple[dict[str, Any], dict[str, Any], Any]:
    params: dict[str, Any] = {
        "tts_model": case.model,
        "speaker": case.speaker,
        "voice_id": case.speaker,
        "text": case.text,
        "segment_type": case.segment_type,
        "segment_speaker": case.segment_speaker,
        "instruct_role": case.role,
        "instruct_scene": case.scene,
        "performance_notes": case.performance_notes,
        "instruct_emotion": case.emotion,
        "voice_description": case.voice_description,
        "format": "mp3",
        "speed": 1.0,
        "volume": 50,
        "pitch": 50,
    }
    if case.style_control_method:
        params["style_control_method"] = case.style_control_method
    if case.style_tags:
        params["style_tags"] = list(case.style_tags)
    if case.inline_audio_tags:
        params["inline_audio_tags"] = list(case.inline_audio_tags)
    if case.delivery_plan_overrides:
        params["delivery_plan"] = dict(case.delivery_plan_overrides)

    delivery_plan = build_delivery_plan(
        voice_params=params,
        model=case.model,
        emotion=case.emotion,
    )
    params["delivery_plan"] = delivery_plan

    style_control = build_model_style_control(case.model, params, case.emotion)
    if style_control.provider_fields.get("use_tag_parser"):
        params["use_tag_parser"] = True
    snapshot = build_provider_prompt_snapshot(
        model=case.model,
        voice_id=case.speaker,
        style_control=style_control,
        delivery_plan=delivery_plan,
    )
    params["provider_prompt_snapshot"] = snapshot
    return params, snapshot, style_control


async def _synthesize_case(case: AcceptanceCase, output_dir: Path) -> dict[str, Any]:
    params, snapshot, style_control = _build_voice_params(case)
    case_payload: dict[str, Any] = {
        "id": case.id,
        "group": case.group,
        "provider": case.provider,
        "model": case.model,
        "speaker": case.speaker,
        "case": case.case_name,
        "text": case.text,
        "segment_type": case.segment_type,
        "segment_speaker": case.segment_speaker,
        "emotion": case.emotion,
        "expected_tags": list(case.inline_audio_tags or case.style_tags),
        "style_control_mode": style_control.mode,
        "text_prefix": style_control.text_prefix,
        "snapshot": snapshot,
    }

    json_path = output_dir / f"{case.id}.json"
    engine = TTSEngine(
        model=case.model,
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.2,
        retry_config=RetryConfig(max_retries=2, base_delay=1.0, max_delay=4.0),
    )

    try:
        metadata = await engine.synthesize_with_metadata(case.text, params, case.emotion)
        audio_bytes = metadata.pop("audio_bytes", b"")
        if not audio_bytes:
            case_payload.update(
                {
                    "status": "failed",
                    "error_type": "RuntimeError",
                    "error_message": "provider returned empty audio",
                    "provider_metadata": metadata,
                }
            )
            _write_json(json_path, case_payload)
            return case_payload

        audio_format = str(metadata.get("format") or "mp3").lower()
        extension = "wav" if audio_format == "wav" else "mp3"
        audio_path = output_dir / f"{case.id}.{extension}"
        audio_path.write_bytes(audio_bytes)
        case_payload.update(
            {
                "status": "completed",
                "audio_path": _repo_relative(audio_path),
                "audio_bytes": len(audio_bytes),
                "format": extension,
                "provider_metadata": metadata,
            }
        )
    except Exception as exc:  # noqa: BLE001
        case_payload.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "provider_metadata": engine.get_last_synthesis_metadata(),
            }
        )

    _write_json(json_path, case_payload)
    return case_payload


def _detect_tag_residue(transcript: str, tags: list[str]) -> list[str]:
    text = str(transcript or "")
    return [tag for tag in tags if tag and tag in text]


def _run_mimo_asr(results: list[dict[str, Any]], output_dir: Path) -> None:
    provider = MiMoPromptAudioAsrProvider(timeout_seconds=120.0)
    if not provider.configured:
        for result in results:
            if result.get("status") == "completed" and str(result.get("id", "")).startswith("p2_"):
                result["asr"] = {"status": "skipped", "reason": "mimo_asr_not_configured"}
        return

    for result in results:
        sample_id = str(result.get("id") or "")
        if result.get("status") != "completed" or not sample_id.startswith("p2_"):
            continue
        audio_path = PROJECT_ROOT / str(result.get("audio_path") or "")
        try:
            asr_result = provider.transcribe(str(audio_path))
            transcript = asr_result.transcript
            result["asr"] = {
                "status": "completed",
                "provider": asr_result.provider,
                "model": asr_result.model,
                "transcript": transcript,
                "tag_residue_candidates": _detect_tag_residue(
                    transcript,
                    [str(item) for item in result.get("expected_tags") or []],
                ),
                "metadata_keys": sorted(asr_result.metadata.keys()),
            }
        except PromptAudioAsrProviderError as exc:
            result["asr"] = {
                "status": "failed",
                "code": exc.code,
                "message": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            result["asr"] = {
                "status": "failed",
                "code": type(exc).__name__,
                "message": str(exc),
            }

        json_path = output_dir / f"{sample_id}.json"
        if json_path.exists():
            _write_json(json_path, result)


def _render_status_badge(status: str) -> str:
    if status == "completed":
        return '<span class="ok">completed</span>'
    return '<span class="fail">failed</span>'


def _write_index_html(output_dir: Path, manifest: dict[str, Any]) -> None:
    rows: list[str] = []
    for result in manifest["results"]:
        audio_cell = ""
        if result.get("audio_path"):
            audio_name = Path(str(result["audio_path"])).name
            audio_cell = f'<audio controls preload="metadata" src="./{html.escape(audio_name)}"></audio>'
        asr = result.get("asr") if isinstance(result.get("asr"), dict) else {}
        asr_text = html.escape(str(asr.get("transcript") or asr.get("message") or ""))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('id', '')))}</td>"
            f"<td>{html.escape(str(result.get('group', '')))}</td>"
            f"<td>{html.escape(str(result.get('case', '')))}</td>"
            f"<td>{html.escape(str(result.get('model', '')))}</td>"
            f"<td>{_render_status_badge(str(result.get('status', '')))}</td>"
            f"<td>{audio_cell}</td>"
            f"<td>{html.escape(str(result.get('text', '')))}</td>"
            f"<td>{asr_text}</td>"
            "</tr>"
        )

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Audiobook TTS Prompt Strategy Acceptance</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    p {{ margin: 4px 0 18px; color: #4b5563; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; vertical-align: top; font-size: 13px; word-break: break-word; }}
    th {{ background: #f3f4f6; text-align: left; }}
    audio {{ width: 220px; max-width: 100%; }}
    .ok {{ color: #047857; font-weight: 600; }}
    .fail {{ color: #b91c1c; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>Audiobook TTS Prompt Strategy Acceptance</h1>
  <p>生成时间：{html.escape(str(manifest.get("generated_at", "")))}；完成 {manifest.get("completed", 0)}/{manifest.get("total", 0)}。</p>
  <table>
    <thead>
      <tr>
        <th>样本</th>
        <th>分组</th>
        <th>用例</th>
        <th>模型</th>
        <th>状态</th>
        <th>试听</th>
        <th>正文</th>
        <th>ASR 辅助</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html_text, encoding="utf-8")


def _write_review_sheet(output_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# 有声小说 TTS Prompt 策略人工验收表",
        "",
        f"- 生成时间：{manifest.get('generated_at')}",
        f"- 样本目录：`{manifest.get('output_dir')}`",
        f"- 完成情况：{manifest.get('completed')}/{manifest.get('total')}",
        "",
        "## P1：CosyVoice / StepAudio 停顿与模板分流",
        "",
        "| 样本 | 停顿自然度 1-5 | 留白强度 1-5 | 模板贴合度 1-5 | 情绪贴合度 1-5 | 正文污染 | 整体可用 | 备注 |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for result in manifest["results"]:
        if str(result.get("id", "")).startswith("p1_"):
            lines.append(f"| `{result.get('id')}` |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## P2：MiMo / Doubao 标签解析",
            "",
            "| 样本 | 标签被解析 1-5 | 标签未被朗读 1-5 | 微表演明显度 1-5 | 情绪贴合度 1-5 | 正文污染 | 整体可用 | 备注 |",
            "|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for result in manifest["results"]:
        if str(result.get("id", "")).startswith("p2_"):
            lines.append(f"| `{result.get('id')}` |  |  |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "## 验收口径",
            "",
            "- `正文污染`：是否听到提示词、标签、括号、方括号或非正文内容被读出。",
            "- `整体可用`：建议填写 `可用`、`需微调`、`不可用`。",
            "- ASR 辅助只用于定位疑似正文污染，最终以人工听感为准。",
            "",
        ]
    )
    (output_dir / "review_sheet.md").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(output_dir: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = sum(1 for item in results if item.get("status") == "completed")
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": _repo_relative(output_dir),
        "index_html": _repo_relative(output_dir / "index.html"),
        "review_sheet": _repo_relative(output_dir / "review_sheet.md"),
        "cosyvoice_voice_id": _cosyvoice_voice_id(),
        "stepaudio_voice_id": _stepaudio_voice_id(),
        "mimo_voice_id": _mimo_voice_id(),
        "doubao_voice_id": _doubao_voice_id(),
        "total": len(results),
        "completed": completed,
        "failed": len(results) - completed,
        "results": results,
    }
    _write_json(output_dir / "manifest.json", manifest)
    _write_index_html(output_dir, manifest)
    _write_review_sheet(output_dir, manifest)
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


async def generate_samples(output_dir: Path, *, run_asr: bool) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for case in build_cases():
        print(f"[sample] {case.id} -> {case.model}", flush=True)
        result = await _synthesize_case(case, output_dir)
        results.append(result)

    if run_asr:
        print("[asr] MiMo ASR for P2 completed samples", flush=True)
        _run_mimo_asr(results, output_dir)

    manifest = _write_manifest(output_dir, results)
    print(
        f"[done] completed={manifest['completed']}/{manifest['total']} "
        f"output={manifest['output_dir']}",
        flush=True,
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated samples and review files.",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild manifest-derived index.html and review_sheet.md without calling providers.",
    )
    parser.add_argument(
        "--run-asr",
        action="store_true",
        help="Use configured MiMo ASR to transcribe completed P2 samples.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    if args.rebuild_index:
        manifest_path = output_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _write_index_html(output_dir, manifest)
        _write_review_sheet(output_dir, manifest)
        print(f"[done] rebuilt index and review sheet for {manifest.get('output_dir')}", flush=True)
        return
    asyncio.run(generate_samples(output_dir, run_asr=bool(args.run_asr)))


if __name__ == "__main__":
    main()
