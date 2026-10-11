"""G1–G7 能力门槛探测脚本（付费；作为档案复测入口长期留存，不随任务清理）。

目的：只用"最小可判定"的真实调用，确认 docs/TTS_PROMPT_EVIDENCE_20261010.md §9
里 7 个门槛到底成不成立，为后续全量 A/B 矩阵决定哪些写法根本不能进设计。

留存理由：`docs/MODEL_INTEGRATION_REFERENCE.md` §11.9 / §11.13 引用的门槛结论
（含 G3：244 字 instruction 返回 HTTP 200，据此把 stepaudio 自设 200 上调为官方 500）
没有保留逐条响应日志，原始日志已按清理条款删除，本脚本是唯一的复现入口。
默认拒绝执行，必须显式 --confirm-paid 才发真实请求，因此不存在被动触发的费用风险。

设计约束（与批准口径一致）：
- 不修改生产提示词装配链：本脚本只**借用**引擎里的 payload 构造器，
  然后按需覆盖单个字段，再把最终 payload 原样写进 manifest。
- 默认拒绝执行；必须显式带 --confirm-paid 才发出网络请求。
- 不打印任何密钥；manifest 只含请求体与供应商响应元数据。

用法（在 backend/ 下）：
    python -m app.scripts.probe_tts_capability_gates            # 干跑，只列 payload
    python -m app.scripts.probe_tts_capability_gates --confirm-paid
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


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

import httpx  # noqa: E402

from app.services.audiobook.tts_engine import TTSEngine  # noqa: E402
from app.services.audiobook.tts_engine_pkg._aliyun_mixin import (  # noqa: E402
    QWEN_AUDIO_31_TTS_ENDPOINT,
    SEED_TTS_DEFAULT_RESOURCE_ID,
    SEED_TTS_API_KEY_ENV_NAMES,
    _get_seed_tts_api_key,
    _parse_seed_tts_json_audio_chunks,
)
from app.services.audiobook.tts_model_ids import (  # noqa: E402
    MIMO_V25_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
)

OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/gate_probe_g1_g7"

DASHSCOPE_MULTIMODAL_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
MINIMAX_HD_ALIAS = "MiniMax/speech-2.8-hd"

MINIMAX_VOICE = "male-qn-qingse"
STEPAUDIO_VOICE = "cixingnansheng"
SEED_VOICE = "ICL_uranus_zh_female_keainvsheng_tob"
MIMO_VOICE = "mimo_default"
# Qwen3-TTS 系列已退役（上游返回 404），本脚本的 Qwen 通道统一走 qwen-audio-3.1-tts-flash。
QWEN_AUDIO_VOICE = "longsanshu_v3.1"

G1_TEXT = "我没事。我真的没事，你们都不用管我。"
G2_TEXT = "好吧，既然你都这么说了，那就是我多管闲事了。"
G2_TEXT_PAUSE = "好吧<#1.5#>，既然你都这么说了<#1.5#>，那就是我多管闲事了。"
G3_TEXT = "东西都在我这儿，你别逼我把它扔了。"
G4_TEXT = "所以从一开始，你就在骗我。"
G5_TEXT_PLAIN = "你怎么还不走？"
G5_TEXT_BRACKET = "[焦急，语速快]你怎么还不走？"
G5_TEXT_COT = "<cot text=焦急难耐>你怎么还不走？</cot>"
G5_TEXT_COT_QUOTED = '<cot text="焦急难耐">你怎么还不走？</cot>'
G6_TEXT = "你到底想怎么样？"
G7_TEXT = "我真的没事，你们都不用管我。"
G7_TEXT_TAGGED = "[excited]我真的没事，你们都不用管我。"

# G3 门槛：官方 3-tts 上限 500 字符，自限 200。构造 >200 且 <=500 的指令。
G3_LONG_INSTRUCTION = (
    "你是一个冷硬的债主，站在别人家门口讨要东西。"
    "整段话的基调是压着的怒火，不是吼叫："
    "声音要低、要稳，字与字之间不要连得太紧；"
    "语速比正常朗读慢一些，重音落在“我这儿”和“别逼我”上；"
    "“你别逼我把它扔了”这半句要有一种随时会失控但还在收着的感觉，"
    "句尾不要上扬，要往下压，最后几个字几乎是从牙缝里挤出来的。"
    "开头两个字之前先有一口很浅的吸气，中间提到东西的时候停顿一下，像在掂量对方敢不敢接；"
    "全程不要出现笑音，不要有播报腔，不要提亮音色。"
    "如果对方没有回应，最后半句要更轻、更慢，像是说给自己听的威胁。"
)

G1_INSTRUCTION_SAD = "极其克制压抑的悲伤，语速偏慢，句尾下沉，几乎不带哭腔。"
G1_INSTRUCTION_HAPPY = "明快雀跃，语速偏快，句尾上扬，带着笑意。"
G2_INSTRUCTION = None  # MiniMax 走 emotion 枚举，无自然语言指令通道
G3_SHORT_INSTRUCTION = "语气冰冷，压迫感强，语速偏慢。"
G4_CONTEXT_TEXT = "她压着怒气，声音很低，一字一句地说"
G6_STYLE_ANGRY = "愤怒"
G6_STYLE_SUPPRESSED = "压抑的愤怒"
G7_INSTRUCTION = "悲伤克制，语速偏慢，句尾下沉。"

ASSERT_LONG = len(G3_LONG_INSTRUCTION)


@dataclass
class GateCall:
    key: str
    gate: str
    channel: str
    question: str
    build: Callable[[], Dict[str, Any]]
    endpoint: str
    headers: Callable[[], Dict[str, str]]
    ext: str = "mp3"
    transport: str = "http"
    # 该条应被逐字朗读的台词（不含标签/舞台提示）。评分脚本用它做 fidelity 对照，
    # 因为 payload 里的 text 可能带正文标签，不能直接当台词用。
    spoken_text: str = ""
    seed_spec: Dict[str, Any] = field(default_factory=dict)
    audio: Optional[bytes] = None
    status: Optional[int] = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    duration_ms: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    response_meta: Dict[str, Any] = field(default_factory=dict)


def _engine(model: str) -> TTSEngine:
    return TTSEngine(enable_cache=False, model=model)


def _dashscope_headers() -> Dict[str, str]:
    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY") or ""
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _step_headers() -> Dict[str, str]:
    key = os.getenv("STEP_API_KEY") or os.getenv("STEPFUN_API_KEY") or ""
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _mimo_headers() -> Dict[str, str]:
    key = os.getenv("MIMO_API_KEY") or ""
    return {"api-key": key, "Content-Type": "application/json"}


def _seed_headers() -> Dict[str, str]:
    key = _get_seed_tts_api_key() or ""
    app_key = (
        str(os.getenv("VOLCENGINE_TTS_APP_KEY") or os.getenv("DOUBAO_TTS_APP_KEY") or "").strip() or key
    )
    return {
        "X-Api-App-Key": app_key,
        "X-Api-Key": key,
        "X-Api-Resource-Id": os.getenv("VOLCENGINE_TTS_RESOURCE_ID") or SEED_TTS_DEFAULT_RESOURCE_ID,
        "Content-Type": "application/json",
    }


def _minimax_payload(*, text: str, emotion: str) -> Dict[str, Any]:
    engine = _engine(MINIMAX_SPEECH_28_HD_MODEL)
    payload = engine._build_minimax_http_payload(
        model=MINIMAX_HD_ALIAS,
        text=text,
        voice=MINIMAX_VOICE,
        voice_params={"emotion": "neutral", "volume": 50},
    )
    payload["input"]["voice_setting"]["emotion"] = emotion
    return payload


def _stepaudio_payload(*, text: str, instruction: str) -> Dict[str, Any]:
    engine = _engine(STEPAUDIO_3_TTS_MODEL)
    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_3_TTS_MODEL,
        text=text,
        voice=STEPAUDIO_VOICE,
        voice_params={"emotion": "neutral", "format": "mp3"},
    )
    payload["instruction"] = instruction  # 探测原始上限，绕过发送层自限截断（当前 500，G3 时 200）
    return payload


def _seed_payload(
    *, text: str, context_texts: Optional[List[str]], use_tag_parser: Optional[bool]
) -> Dict[str, Any]:
    engine = _engine(SEED_TTS_20_EXPRESSIVE_MODEL)
    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text=text,
        voice=SEED_VOICE,
        voice_params={"emotion": "neutral", "format": "mp3"},
    )
    req = payload["req_params"]
    req["text"] = text  # 探针必须逐字控制正文，不接受装配链改写
    req.pop("additions", None)
    if context_texts or use_tag_parser:
        additions: Dict[str, Any] = {}
        if context_texts:
            additions["context_texts"] = context_texts
        if use_tag_parser:
            additions["use_tag_parser"] = True
        req["additions"] = additions
    return payload


def _seed_ws_spec(*, text: str, context_texts: Optional[List[str]], use_tag_parser: Optional[bool]) -> Dict[str, Any]:
    """生产 WS 链路的等价请求体：additions 必须是 JSON 字符串（官方协议）。"""
    additions: Dict[str, Any] = {}
    if context_texts:
        additions["context_texts"] = context_texts
    if use_tag_parser:
        additions["use_tag_parser"] = True
    req_params: Dict[str, Any] = {
        "model": SEED_TTS_20_EXPRESSIVE_MODEL,
        "speaker": SEED_VOICE,
        "text": text,
        "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": 0, "loudness_rate": 0},
    }
    if additions:
        req_params["additions"] = json.dumps(additions, ensure_ascii=False, separators=(",", ":"))
    return {
        "text": text,
        "context_texts": context_texts or [],
        "use_tag_parser": bool(use_tag_parser),
        "wire": {"user": {"uid": "audiobook"}, "req_params": req_params},
    }


def _mimo_payload(*, style: str, text: str) -> Dict[str, Any]:
    engine = _engine(MIMO_V25_TTS_MODEL)
    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text=text,
        voice=MIMO_VOICE,
        voice_params={"emotion": "neutral", "format": "mp3"},
    )
    payload["messages"] = [
        {"role": "user", "content": style},
        {"role": "assistant", "content": text},
    ]
    payload["audio"] = {"format": "mp3"}
    return payload


def _qwen_audio_payload(*, text: str, instruction: Optional[str]) -> Dict[str, Any]:
    return _qwen_audio_payload_voice(text=text, instruction=instruction, voice_id=QWEN_AUDIO_VOICE)


def _qwen_audio_payload_voice(*, text: str, instruction: Optional[str], voice_id: str) -> Dict[str, Any]:
    engine = _engine(QWEN_AUDIO_31_TTS_FLASH_MODEL)
    payload = engine._build_qwen_audio_31_http_payload(
        model=QWEN_AUDIO_31_TTS_FLASH_MODEL,
        text=text,
        voice_id=voice_id,
        voice_params={"emotion": "neutral"},
    )
    payload["input"]["text"] = text
    if instruction is None:
        payload["input"].pop("instruction", None)
    else:
        payload["input"]["instruction"] = instruction
    return payload


def build_calls() -> List[GateCall]:
    step_base_url = (os.getenv("STEPAUDIO_TTS_BASE_URL") or "https://api.stepfun.com/v1").rstrip("/")
    seed_endpoint = (
        os.getenv("SEED_TTS_HTTP_ENDPOINT") or "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    ).strip()

    calls: List[GateCall] = [
        GateCall(
            key="g1a_qwen31_none",
            gate="G1",
            channel=QWEN_AUDIO_31_TTS_FLASH_MODEL,
            question="基线：不传 instruction",
            build=lambda: _qwen_audio_payload(text=G1_TEXT, instruction=None),
            endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g1b_qwen31_sad",
            gate="G1",
            channel=QWEN_AUDIO_31_TTS_FLASH_MODEL,
            question="instruction=克制压抑的悲伤 是否与基线分化",
            build=lambda: _qwen_audio_payload(text=G1_TEXT, instruction=G1_INSTRUCTION_SAD),
            endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g1c_qwen31_happy",
            gate="G1",
            channel=QWEN_AUDIO_31_TTS_FLASH_MODEL,
            question="instruction=明快雀跃 是否与悲伤分化",
            build=lambda: _qwen_audio_payload(text=G1_TEXT, instruction=G1_INSTRUCTION_HAPPY),
            endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g2a_minimax_calm",
            gate="G2",
            channel="MiniMax/speech-2.8-hd",
            question="voice_setting.emotion=calm 是否被接受",
            build=lambda: _minimax_payload(text=G2_TEXT, emotion="calm"),
            endpoint=DASHSCOPE_MULTIMODAL_URL,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g2b_minimax_sad",
            gate="G2",
            channel="MiniMax/speech-2.8-hd",
            question="emotion=sad 与 calm 是否听感分化",
            build=lambda: _minimax_payload(text=G2_TEXT, emotion="sad"),
            endpoint=DASHSCOPE_MULTIMODAL_URL,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g2c_minimax_pause_tag",
            gate="G2",
            channel="MiniMax/speech-2.8-hd",
            question="<#1.5#> 是否被读成停顿（与 g2a 时长对比）",
            build=lambda: _minimax_payload(text=G2_TEXT_PAUSE, emotion="calm"),
            endpoint=DASHSCOPE_MULTIMODAL_URL,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g3a_step_short",
            gate="G3",
            channel="stepaudio-3-tts",
            question="200 字内指令基线",
            build=lambda: _stepaudio_payload(text=G3_TEXT, instruction=G3_SHORT_INSTRUCTION),
            endpoint=f"{step_base_url}/audio/speech",
            headers=_step_headers,
        ),
        GateCall(
            key="g3b_step_260",
            gate="G3",
            channel="stepaudio-3-tts",
            question=f"指令 {ASSERT_LONG} 字是否被 400 拒绝",
            build=lambda: _stepaudio_payload(text=G3_TEXT, instruction=G3_LONG_INSTRUCTION),
            endpoint=f"{step_base_url}/audio/speech",
            headers=_step_headers,
        ),
        GateCall(
            key="g4a_seed_plain",
            gate="G4",
            channel="seed-tts-2.0-expressive",
            question="无 context_texts 基线",
            build=lambda: _seed_ws_spec(text=G4_TEXT, context_texts=None, use_tag_parser=None),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g4b_seed_context",
            gate="G4",
            channel="seed-tts-2.0-expressive",
            question="expressive 模型 + context_texts 是否互斥/被忽略",
            build=lambda: _seed_ws_spec(
                text=G4_TEXT, context_texts=[G4_CONTEXT_TEXT], use_tag_parser=None
            ),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g5a_seed_bracket",
            gate="G5",
            channel="seed-tts-2.0-expressive",
            question="现有 [标签] 方括号前缀是否被朗读出来",
            build=lambda: _seed_ws_spec(text=G5_TEXT_BRACKET, context_texts=None, use_tag_parser=False),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g5d_seed_plain_control",
            gate="G5",
            channel="seed-tts-2.0-expressive",
            question="同句无标签对照（用于判定 [标签] 与 Cot 是否被朗读/是否改变韵律）",
            build=lambda: _seed_ws_spec(text=G5_TEXT_PLAIN, context_texts=None, use_tag_parser=False),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g5b_seed_cot",
            gate="G5",
            channel="seed-tts-2.0-expressive",
            question="官方 Cot 标签（无引号）是否被解析",
            build=lambda: _seed_ws_spec(text=G5_TEXT_COT, context_texts=None, use_tag_parser=True),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g5c_seed_cot_quoted",
            gate="G5",
            channel="seed-tts-2.0-expressive",
            question="官方 Cot 标签（带引号）是否被解析",
            build=lambda: _seed_ws_spec(
                text=G5_TEXT_COT_QUOTED, context_texts=None, use_tag_parser=True
            ),
            endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
            headers=_seed_headers,
            transport="seed_ws",
        ),
        GateCall(
            key="g6a_mimo_angry",
            gate="G6",
            channel="mimo-v2.5-tts",
            question="单一情绪词“愤怒”",
            build=lambda: _mimo_payload(style=G6_STYLE_ANGRY, text=G6_TEXT),
            endpoint="https://api.xiaomimimo.com/v1/chat/completions",
            headers=_mimo_headers,
            ext="mp3",
        ),
        GateCall(
            key="g6b_mimo_suppressed",
            gate="G6",
            channel="mimo-v2.5-tts",
            question="复合情绪“压抑的愤怒”是否可听",
            build=lambda: _mimo_payload(style=G6_STYLE_SUPPRESSED, text=G6_TEXT),
            endpoint="https://api.xiaomimimo.com/v1/chat/completions",
            headers=_mimo_headers,
            ext="mp3",
        ),
        GateCall(
            key="g7a_audio_instruction",
            gate="G7",
            channel="qwen-audio-3.1-tts-flash",
            question="仅 instruction 的自然语言控制",
            build=lambda: _qwen_audio_payload(text=G7_TEXT, instruction=G7_INSTRUCTION),
            endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
            headers=_dashscope_headers,
        ),
        GateCall(
            key="g7b_audio_tags",
            gate="G7",
            channel="qwen-audio-3.1-tts-flash",
            question="instruction + 正文 [excited] 标签能否叠加、标签是否被朗读",
            build=lambda: _qwen_audio_payload(text=G7_TEXT_TAGGED, instruction=G7_INSTRUCTION),
            endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
            headers=_dashscope_headers,
        ),
    ]
    return calls


def _redact(headers: Dict[str, str]) -> Dict[str, str]:
    """按"头名含敏感词"掩码，不枚举具体头名。

    枚举式白名单（原先只列 authorization / x-api-key / api-key）漏掉了
    `X-Api-App-Key`，而豆包分支在该环境变量缺省时会把 API Key 兜底填进这个头，
    导致密钥明文写进 manifest（见 docs/TTS_PROMPT_EVIDENCE_20261010.md §14）。
    """
    sensitive = ("key", "token", "authorization", "secret", "signature")
    out = {}
    for k, v in headers.items():
        out[k] = "***" if any(word in k.lower() for word in sensitive) else v
    return out


def _decode_audio_blob(value: Any) -> Optional[bytes]:
    """供应商可能返回 base64，也可能返回十六进制串（MiniMax 走 hex）。"""
    if not isinstance(value, str) or not value:
        return None
    raw = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    if len(raw) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in raw[:64]):
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


async def _download(client: httpx.AsyncClient, url: str) -> Optional[bytes]:
    try:
        resp = await client.get(url)
    except Exception:
        return None
    return resp.content if resp.status_code == 200 and resp.content else None


def _ext_from_url(url: str) -> str:
    tail = str(url or "").split("?")[0].rsplit(".", 1)
    suffix = tail[1].lower() if len(tail) == 2 else ""
    return suffix if suffix in {"wav", "mp3", "ogg", "flac", "pcm"} else "wav"


async def _extract_audio(
    client: httpx.AsyncClient, data: Any, content_type: str, content: bytes, text: str
) -> tuple[Optional[bytes], str, Dict[str, Any]]:
    meta: Dict[str, Any] = {"content_type": content_type}
    if isinstance(data, dict):
        meta["body_keys"] = sorted(str(k) for k in data)
        if isinstance(data.get("usage"), dict):
            meta["usage"] = data["usage"]

    if content_type.startswith("audio/") and content:
        return content, "audio", meta

    if isinstance(data, dict):
        output = data.get("output")
        if isinstance(output, dict):
            audio = output.get("audio")
            if isinstance(audio, str):
                got = _decode_audio_blob(audio)
                if got:
                    return got, "mp3", meta
            if isinstance(audio, dict):
                got = _decode_audio_blob(audio.get("data"))
                if got:
                    return got, "mp3", meta
                url = str(audio.get("url") or "")
                if url:
                    meta["audio_url_head"] = url[:120]
                    got = await _download(client, url)
                    if got:
                        return got, _ext_from_url(url), meta
            inner = output.get("data")
            if isinstance(inner, dict):
                got = _decode_audio_blob(inner.get("audio") or inner.get("data"))
                if got:
                    return got, "mp3", meta
            if isinstance(inner, str):
                got = _decode_audio_blob(inner)
                if got:
                    return got, "mp3", meta
        got = _decode_audio_blob(data.get("data"))
        if got:
            return got, "mp3", meta
        if isinstance(data.get("data"), dict):
            got = _decode_audio_blob(data["data"].get("audio") or data["data"].get("data"))
            if got:
                return got, "mp3", meta
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                audio = message.get("audio")
                if isinstance(audio, dict):
                    got = _decode_audio_blob(audio.get("data"))
                    if got:
                        return got, "mp3", meta
                elif isinstance(audio, str):
                    got = _decode_audio_blob(audio)
                    if got:
                        return got, "mp3", meta

    # Seed-TTS HTTP：正文是 text/plain 的按行 JSON 分片
    chunked = _parse_seed_tts_json_audio_chunks(text)
    if chunked:
        return chunked, "mp3", meta
    return None, "mp3", meta



async def _probe_seed_ws(call: GateCall, client: httpx.AsyncClient) -> None:
    """走生产同款 WebSocket 通道，正文与 additions 由探针逐字控制。"""
    spec = call.build()
    call.seed_spec = spec
    call.payload = spec["wire"]
    api_key = _get_seed_tts_api_key()
    if not api_key:
        call.error = "missing seed tts credential"
        return

    engine = _engine(SEED_TTS_20_EXPRESSIVE_MODEL)
    engine._build_seed_tts_style_request = lambda **_kw: (
        None,
        spec["text"],
        spec["context_texts"],
        spec["use_tag_parser"],
    )
    try:
        audio = await engine._call_seed_tts_websocket(
            model=SEED_TTS_20_EXPRESSIVE_MODEL,
            api_key=api_key,
            text=spec["text"],
            voice=SEED_VOICE,
            voice_params={"format": "mp3", "emotion": "neutral"},
            resource_id=SEED_TTS_DEFAULT_RESOURCE_ID,
        )
    except Exception as exc:
        call.status = None
        call.error = f"{type(exc).__name__}: {exc}"[:600]
        return

    call.response_meta = {
        "transport": "websocket",
        "engine_metadata": getattr(engine, "_last_synthesis_metadata", {}),
    }
    if audio:
        call.audio = audio
        call.ext = "mp3"
        call.status = 200
    else:
        call.error = "websocket returned no audio"


async def _probe(call: GateCall, client: httpx.AsyncClient) -> None:
    if call.transport == "seed_ws":
        await _probe_seed_ws(call, client)
        return

    payload = call.build()
    call.payload = payload
    headers = call.headers()
    if not any(v for k, v in headers.items() if k.lower() in {"authorization", "x-api-key", "api-key"}):
        call.error = "missing credential"
        return

    response = await client.post(call.endpoint, headers=headers, json=payload)
    call.status = response.status_code
    call.request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("X-Request-Id")
        or response.headers.get("x-tt-logid")
        or ""
    )
    content_type = str(response.headers.get("content-type") or "")
    if response.status_code != 200:
        call.error = response.text[:600]
        return

    data = None
    if "json" in content_type:
        try:
            data = response.json()
        except Exception:
            data = None
    audio, ext, meta = await _extract_audio(
        client, data, content_type, response.content, getattr(response, "text", "") or ""
    )
    call.response_meta = meta
    if isinstance(data, dict) and isinstance(data.get("output"), dict):
        base_resp = data["output"].get("base_resp")
        if isinstance(base_resp, dict):
            call.response_meta["base_resp"] = base_resp
    if audio:
        call.audio = audio
        call.ext = ext
    else:
        call.error = "no audio in response"
        raw_dir = OUTPUT_DIR / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{call.key}.txt").write_text(
            (getattr(response, "text", "") or str(data) or "")[:200000], encoding="utf-8"
        )



def _duration_ms(path: Path) -> Optional[int]:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        value = json.loads(out.stdout or "{}").get("format", {}).get("duration")
        return int(round(float(value) * 1000)) if value else None
    except Exception:
        return None


async def _run(calls: List[GateCall]) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        for call in calls:
            try:
                await _probe(call, client)
            except Exception as exc:  # 单次失败不影响后续门槛判定
                call.error = f"{type(exc).__name__}: {exc}"[:400]
            await asyncio.sleep(1.0)


B1_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/b1_mimo_writing"
B1_TEXT = "我没事。我真的没事，你们都不用管我。"
B1_TEXT_LABELED = "（深呼吸）我没事。（停顿）我真的没事，你们都不用管我。"
# 同一句台词、同一音色，只换 user 消息里的"写法"，用来找 MiMo 的最佳提示词书写形态。
B1_STYLES = {
    "b1a_keyword": ("关键词式", B1_TEXT, "克制悲伤"),
    "b1b_physical": (
        "物理量式",
        B1_TEXT,
        "音量偏低，语速偏慢，句尾下沉，气息轻微发颤，不带哭腔。",
    ),
    "b1c_director": (
        "官方三段式",
        B1_TEXT,
        "【角色】一个刚哭过、但不想让家人担心的妹妹。"
        "【场景】深夜客厅，家人都围着她。"
        "【指导】克制悲伤：语速偏慢，音量偏低，句尾往下沉，几乎不带哭腔，"
        "重复的那两句一次比一次轻。",
    ),
    "b1d_motivation": (
        "动机前置式",
        B1_TEXT,
        "她刚被最亲的人误解，此刻最想做的不是辩解，而是让他们别再为她操心。"
        "所以这句话要说得又轻又慢，句尾往下沉，把哭腔咽回去。",
    ),
    "b1e_labels": (
        "正文内标签通道",
        B1_TEXT_LABELED,
        "克制悲伤，语速偏慢。",
    ),
    "b1f_control": (
        "最小基线",
        B1_TEXT,
        "用普通、自然的语气朗读这句话，不做额外表演。",
    ),
}


def build_b1_calls() -> List[GateCall]:
    calls: List[GateCall] = []
    for key, (label, text, style) in B1_STYLES.items():
        calls.append(
            GateCall(
                key=key,
                gate="B1",
                channel="mimo-v2.5-tts（限时免费）",
                question=label,
                build=lambda style=style, text=text: _mimo_payload(style=style, text=text),
                endpoint="https://api.xiaomimimo.com/v1/chat/completions",
                headers=_mimo_headers,
                ext="mp3",
            )
        )
    return calls


B2_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/b2_paid_writing"
B3_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/b3_qwen31_writing"
HTTP_PROBE_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/seed_http_shape"
TAG_PARSER_OUTPUT_DIR = PROJECT_ROOT / "backend/data/tts_debug/seed_tag_parser_shape"

# 与 B1 逐字同台词，跨模型才能直接对照；B1 由人耳裁定的两种最优写法原样搬到各模型官方通道。
B2_TEXT = B1_TEXT
B2_DIRECTOR = B1_STYLES["b1c_director"][2]
B2_MOTIVATION = B1_STYLES["b1d_motivation"][2]
B2_KEYWORD = B1_STYLES["b1a_keyword"][2]
B2_BASELINE = B1_STYLES["b1f_control"][2]
B2_TEXT_STEP_TAGGED = "（很轻地，几乎耳语）我没事。（停一下）我真的没事，你们都不用管我。"
B2_TEXT_BRACKET = f"[{B2_KEYWORD}，语速偏慢]{B2_TEXT}"
B2_TEXT_COT = (
    "<cot text=克制悲伤，语速偏慢>我没事。</cot>"
    "<cot text=更轻更慢，句尾下沉>我真的没事，你们都不用管我。</cot>"
)

# B3 换用与生产别名 female_young_gentle 一致的年轻女声，贴合 B1/B2 台词里的"妹妹"角色。
B3_VOICE = "yeqinghe_v3.1"

# 官方「情感与富语言标签」控制类取值（qwen-audio-3.1-tts-flash 在支持清单内）。
# 官方原文：控制类标签作用于其后文本，"直到遇到下一个控制类标签或句子被自动切分"，
# 作用域止于句界还是整段未明说，故逐句下标签，两种解释下都能覆盖全文。
B3_TAG_SAD = "[sad]"
B3_TEXT_SAD_TAGGED = (B3_TAG_SAD + B2_TEXT.replace("。", "。" + B3_TAG_SAD)).removesuffix(B3_TAG_SAD)

SEED_OFFICIAL_SPEAKER = "zh_female_vv_uranus_bigtts"
SEED_UNIDIRECTIONAL_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


def _seed_http_official_headers() -> Dict[str, str]:
    """只带官方 cURL 出现过的三个头，排除 X-Api-App-Key 这类我方附加项的干扰。"""
    return {
        "X-Api-Key": _get_seed_tts_api_key() or "",
        "X-Api-Resource-Id": SEED_TTS_DEFAULT_RESOURCE_ID,
        "Content-Type": "application/json",
    }


def _seed_http_official_payload(*, speaker: str) -> Dict[str, Any]:
    """逐字照官方 cURL 的最小形状：只有 req_params.text/speaker/audio_params。"""
    return {
        "req_params": {
            "text": B2_TEXT,
            "speaker": speaker,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
        }
    }


def build_seed_http_probe_calls() -> List[GateCall]:
    seed_endpoint = (os.getenv("SEED_TTS_HTTP_ENDPOINT") or SEED_UNIDIRECTIONAL_ENDPOINT).strip()
    return [
        GateCall(
            key="h1_official_speaker",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="官方 cURL 逐字形状＋官方音色：HTTP 到底能不能出音频",
            build=lambda: _seed_http_official_payload(speaker=SEED_OFFICIAL_SPEAKER),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="h2_production_speaker",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="同形状换成生产音色：是音色/资源位问题还是通道本身",
            build=lambda: _seed_http_official_payload(speaker=SEED_VOICE),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="h3_production_shape",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="生产 payload 形状（req_params.model＋text_type＋with_timestamp）是否就是拿不到音频的原因",
            build=lambda: _seed_payload(text=B2_TEXT, context_texts=None, use_tag_parser=None),
            endpoint=seed_endpoint,
            headers=_seed_headers,
            ext="mp3",
        ),
    ]


def build_seed_http_bisect_calls() -> List[GateCall]:
    """把"生产形状拿不到音频"归因到具体字段：只加 model / 只去掉 model。"""
    seed_endpoint = (os.getenv("SEED_TTS_HTTP_ENDPOINT") or SEED_UNIDIRECTIONAL_ENDPOINT).strip()

    def _with_model() -> Dict[str, Any]:
        payload = _seed_http_official_payload(speaker=SEED_VOICE)
        payload["req_params"]["model"] = SEED_TTS_20_EXPRESSIVE_MODEL
        return payload

    def _without_model() -> Dict[str, Any]:
        payload = _seed_payload(text=B2_TEXT, context_texts=None, use_tag_parser=None)
        payload["req_params"].pop("model", None)
        return payload

    def _production_minus_rates() -> Dict[str, Any]:
        payload = _seed_payload(text=B2_TEXT, context_texts=None, use_tag_parser=None)
        for key in ("speech_rate", "loudness_rate"):
            payload["req_params"]["audio_params"].pop(key, None)
        return payload

    def _official_plus(
        *, req: Optional[Dict[str, Any]] = None, audio: Optional[Dict[str, Any]] = None,
        top: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """在官方最小形状上单独加一个生产字段，逐个归因。"""
        payload = _seed_http_official_payload(speaker=SEED_VOICE)
        for key, value in (req or {}).items():
            payload["req_params"][key] = value
        for key, value in (audio or {}).items():
            payload["req_params"]["audio_params"][key] = value
        for key, value in (top or {}).items():
            payload[key] = value
        return payload

    return [
        GateCall(
            key="i1_official_plus_model",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="官方形状只多加 req_params.model 是否会退化成正字幕帧",
            build=_with_model,
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="i2_production_minus_model",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="生产形状只去掉 model 是否能拿到音频",
            build=_without_model,
            endpoint=seed_endpoint,
            headers=_seed_headers,
            ext="mp3",
        ),
        GateCall(
            key="j1_official_plus_text_type",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="只加 text_type=plain",
            build=lambda: _official_plus(req={"text_type": "plain"}),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="j2_official_plus_with_timestamp",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="只加 with_timestamp=0",
            build=lambda: _official_plus(req={"with_timestamp": 0}),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="j3_official_plus_rates",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="只加 audio_params.speech_rate/loudness_rate=0",
            build=lambda: _official_plus(
                audio={"speech_rate": 0, "loudness_rate": 0}
            ),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="j4_official_plus_user",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="只加顶层 user.uid 包装",
            build=lambda: _official_plus(top={"user": {"uid": "audiobook"}}),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="k1_text_type_plus_timestamp",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="text_type＋with_timestamp 两字段同时加",
            build=lambda: _official_plus(req={"text_type": "plain", "with_timestamp": 0}),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="k2_rates_plus_user",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="audio_params 双 0 速率＋user 包装",
            build=lambda: _official_plus(
                audio={"speech_rate": 0, "loudness_rate": 0}, top={"user": {"uid": "audiobook"}}
            ),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="k3_three_text_type_timestamp_rates",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="text_type＋with_timestamp＋双 0 速率（不加 user）",
            build=lambda: _official_plus(
                req={"text_type": "plain", "with_timestamp": 0},
                audio={"speech_rate": 0, "loudness_rate": 0},
            ),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
        GateCall(
            key="k4_production_minus_rates",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="生产形状只去掉 speech_rate/loudness_rate",
            build=_production_minus_rates,
            endpoint=seed_endpoint,
            headers=_seed_headers,
            ext="mp3",
        ),
        GateCall(
            key="m1_official_plus_appkey_header",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="官方形状＋生产那套请求头（多出 X-Api-App-Key）——归因到头而不是 body",
            build=lambda: _seed_http_official_payload(speaker=SEED_VOICE),
            endpoint=seed_endpoint,
            headers=_seed_headers,
            ext="mp3",
        ),
        GateCall(
            key="m2_production_minus_appkey_header",
            gate="HTTP形状",
            channel="seed-tts-2.0 单向流式 HTTP",
            question="生产形状＋官方那套请求头（去掉 X-Api-App-Key）",
            build=lambda: _seed_payload(text=B2_TEXT, context_texts=None, use_tag_parser=None),
            endpoint=seed_endpoint,
            headers=_seed_http_official_headers,
            ext="mp3",
        ),
    ]


def build_b2_calls() -> List[GateCall]:
    """B2 付费写法批次：stepaudio-3 与豆包 Cot 两通道。

    原先的 Qwen 五条已随 Qwen3-TTS 退役移出（产物与 manifest 存档在
    backend/data/tts_debug/b2_paid_writing），改由 B3 批次在
    qwen-audio-3.1-tts-flash 上按同文本、同音色重做。
    """
    step_base_url = (os.getenv("STEPAUDIO_TTS_BASE_URL") or "https://api.stepfun.com/v1").rstrip("/")
    calls: List[GateCall] = []

    step_specs = [
        ("s1_step_director", "顶层 instruction 三段式（<500 字符）", B2_TEXT, B2_DIRECTOR),
        ("s2_step_motivation", "顶层 instruction 动机前置式", B2_TEXT, B2_MOTIVATION),
        ("s3_step_director_tagged", "三段式＋正文圆括号标签", B2_TEXT_STEP_TAGGED, B2_DIRECTOR),
        ("s4_step_keyword", "关键词式", B2_TEXT, B2_KEYWORD),
        ("s5_step_baseline", "念稿基线", B2_TEXT, B2_BASELINE),
    ]
    for key, label, text, instruction in step_specs:
        calls.append(
            GateCall(
                key=key,
                gate="B2",
                channel="stepaudio-3-tts",
                question=label,
                build=lambda text=text, instruction=instruction: _stepaudio_payload(
                    text=text, instruction=instruction
                ),
                endpoint=f"{step_base_url}/audio/speech",
                headers=_step_headers,
                ext="mp3",
            )
        )

    seed_specs = [
        ("d1_seed_context_director", "context_texts 三段式（只有首值有效）", B2_TEXT, [B2_DIRECTOR], False),
        ("d2_seed_context_motivation", "context_texts 动机前置式", B2_TEXT, [B2_MOTIVATION], False),
        ("d3_seed_cot", "官方 Cot 标签逐句（use_tag_parser=true）", B2_TEXT_COT, None, True),
        ("d4_seed_bracket_prefix", "[标签，标签] 前缀且不带 use_tag_parser（≠生产形状）", B2_TEXT_BRACKET, None, False),
        ("d5_seed_baseline", "念稿基线（无 additions）", B2_TEXT, None, False),
    ]
    for key, label, text, context_texts, use_tag_parser in seed_specs:
        calls.append(
            GateCall(
                key=key,
                gate="B2",
                channel="seed-tts-2.0-expressive（WebSocket）",
                question=label,
                build=lambda text=text, context_texts=context_texts, use_tag_parser=use_tag_parser: _seed_ws_spec(
                    text=text, context_texts=context_texts, use_tag_parser=use_tag_parser
                ),
                endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                headers=_seed_headers,
                ext="mp3",
                transport="seed_ws",
            )
        )
    return calls


def build_b3_calls() -> List[GateCall]:
    """B3：qwen-audio-3.1-tts-flash 最佳提示词写法测评。

    与 B1/B2 逐字同台词、批次内同音色（yeqinghe_v3.1），只改变提示词形状，
    因此可与 B2 存档的 stepaudio/豆包 结果横向对照。q5/q6 验证 3.1 会不会
    把正文里的圆括号舞台提示读出来（豆包 §16 的方括号教训需要在 3.1 上重测）；
    q7/q8 走官方文档化的正文通道（半角方括号控制类标签）：q7 测标签单独能否
    改变表演（G7 同向重做，G7 当时把 [excited] 与悲伤指令对立下、设计失效），
    q8 测 instruction＋标签叠加——官方只说两者是独立参数，未保证可叠加。
    多轮由 `--tag r2`/`--tag r3` 生成独立目录，不改本函数。
    """
    specs = [
        ("q1_qwen31_director", "三段式（B1 人耳最优）", B2_TEXT, B2_DIRECTOR),
        ("q2_qwen31_motivation", "动机前置式（B1 并列最优）", B2_TEXT, B2_MOTIVATION),
        ("q3_qwen31_keyword", "关键词式（B1 最弱）", B2_TEXT, B2_KEYWORD),
        ("q4_qwen31_baseline", "念稿基线（不传 instruction）", B2_TEXT, None),
        ("q5_qwen31_tags_only", "仅正文圆括号舞台提示，无 instruction", B2_TEXT_STEP_TAGGED, None),
        (
            "q6_qwen31_director_plus_tags",
            "三段式 instruction＋正文圆括号舞台提示",
            B2_TEXT_STEP_TAGGED,
            B2_DIRECTOR,
        ),
        (
            "q7_qwen31_sad_tag_only",
            "仅正文官方 [sad] 控制类标签，无 instruction（G7 同向重做）",
            B3_TEXT_SAD_TAGGED,
            None,
        ),
        (
            "q8_qwen31_director_plus_sad_tag",
            "三段式 instruction＋正文官方 [sad] 标签叠加（官方未保证可叠加）",
            B3_TEXT_SAD_TAGGED,
            B2_DIRECTOR,
        ),
    ]
    calls: List[GateCall] = []
    for key, label, text, instruction in specs:
        calls.append(
            GateCall(
                key=key,
                gate="B3",
                channel=QWEN_AUDIO_31_TTS_FLASH_MODEL,
                question=label,
                build=lambda text=text, instruction=instruction: _qwen_audio_payload_voice(
                    text=text, instruction=instruction, voice_id=B3_VOICE
                ),
                endpoint=QWEN_AUDIO_31_TTS_ENDPOINT,
                headers=_dashscope_headers,
                ext="wav",
                spoken_text=B2_TEXT,
            )
        )
    return calls


def build_seed_tag_parser_calls() -> List[GateCall]:
    """§13.2：复刻生产真实出站形状，判定方括号前缀在开了 use_tag_parser 后是否仍被朗读。

    改动前的生产链路：tts_style_control.py 用 _render_doubao_voice_label_prefix() 生成 `[a，b]` 前缀，
    同时在 provider_fields 里带上 use_tag_parser=True 与 context_texts，
    最终由 _aliyun_mixin._build_seed_tts_additions 序列化成 additions JSON 字符串。
    d4 只测了"前缀 + additions 缺省"，因此不能代表生产。
    本批次判定（§16）为"仍被朗读"后，生产渲染已改为官方 `<cot text=…>` 包裹，本函数保留作取证复现用。
    """
    specs = [
        (
            "n1_prefix_plus_parser_only",
            "方括号前缀＋use_tag_parser=true（只开 parser，隔离单一变量）",
            B2_TEXT_BRACKET,
            None,
            True,
        ),
        (
            "n2_production_full_shape",
            "生产完整形状：方括号前缀＋use_tag_parser=true＋context_texts",
            B2_TEXT_BRACKET,
            [B2_DIRECTOR],
            True,
        ),
    ]
    calls: List[GateCall] = []
    for key, label, text, context_texts, use_tag_parser in specs:
        calls.append(
            GateCall(
                key=key,
                gate="§13",
                channel="seed-tts-2.0-expressive（WebSocket）",
                question=label,
                build=lambda text=text, context_texts=context_texts, use_tag_parser=use_tag_parser: _seed_ws_spec(
                    text=text, context_texts=context_texts, use_tag_parser=use_tag_parser
                ),
                endpoint="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                headers=_seed_headers,
                ext="mp3",
                transport="seed_ws",
            )
        )
    return calls


def main() -> int:
    global OUTPUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid", action="store_true", help="真实发出生成请求（会扣费）")
    parser.add_argument(
        "--skip-existing", action="store_true", help="已生成音频的 key 不再重复请求（避免重复扣费）"
    )
    parser.add_argument(
        "--batch",
        choices=("g1_g7", "b1_mimo", "b2_paid", "qwen31_writing", "seed_http", "seed_bisect", "seed_tag_parser"),
        default="g1_g7",
        help="g1_g7=能力门槛批次（付费）；b1_mimo=MiMo 提示词写法批次（限时免费）；"
        "b2_paid=付费模型写法批次；qwen31_writing=Qwen-Audio 3.1 最佳提示词写法批次；"
        "seed_http=豆包单向 HTTP 形状定性探测；seed_bisect=定位致因字段；"
        "seed_tag_parser=复刻生产形状判定 [标签] 前缀是否仍被朗读（§13.2）",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="输出目录后缀，用于对同一批次重跑多轮以观测供应商抖动",
    )
    args = parser.parse_args()

    if args.batch == "b1_mimo":
        OUTPUT_DIR = B1_OUTPUT_DIR
        calls = build_b1_calls()
    elif args.batch == "b2_paid":
        OUTPUT_DIR = B2_OUTPUT_DIR
        calls = build_b2_calls()
    elif args.batch == "qwen31_writing":
        OUTPUT_DIR = B3_OUTPUT_DIR
        calls = build_b3_calls()
    elif args.batch == "seed_http":
        OUTPUT_DIR = HTTP_PROBE_OUTPUT_DIR
        calls = build_seed_http_probe_calls()
    elif args.batch == "seed_bisect":
        OUTPUT_DIR = HTTP_PROBE_OUTPUT_DIR
        calls = build_seed_http_bisect_calls()
    elif args.batch == "seed_tag_parser":
        OUTPUT_DIR = TAG_PARSER_OUTPUT_DIR
        calls = build_seed_tag_parser_calls()
    else:
        calls = build_calls()
    if args.tag:
        OUTPUT_DIR = OUTPUT_DIR.parent / f"{OUTPUT_DIR.name}_{args.tag}"
    if args.skip_existing:
        kept = []
        for call in calls:
            found = list(OUTPUT_DIR.glob(f"{call.key}.*")) if OUTPUT_DIR.exists() else []
            if any(p.stat().st_size > 1000 for p in found):
                continue
            kept.append(call)
        print(f"跳过已生成 {len(calls) - len(kept)} 条，本轮实际请求 {len(kept)} 条")
        calls = kept


    if not args.confirm_paid:
        print("DRY-RUN：未发出任何网络请求。共 %d 次调用，payload 摘要如下：" % len(calls))
        for call in calls:
            payload = call.build()
            print(
                f"\n[{call.gate}] {call.key} -> {call.endpoint}\n"
                + json.dumps(payload, ensure_ascii=False)[:600]
            )
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(calls))

    entries: List[Dict[str, Any]] = []
    for call in calls:
        entry: Dict[str, Any] = {
            "gate": call.gate,
            "key": call.key,
            "channel": call.channel,
            "question": call.question,
            "endpoint": call.endpoint,
            "headers": _redact(call.headers()),
            "payload": call.payload,
            "http_status": call.status,
            "request_id": call.request_id,
            "response_meta": call.response_meta,
            "error": call.error,
        }
        if call.spoken_text:
            entry["spoken_text"] = call.spoken_text
        if call.audio:
            path = OUTPUT_DIR / f"{call.key}.{call.ext}"
            path.write_bytes(call.audio)
            entry["audio_file"] = path.relative_to(PROJECT_ROOT).as_posix()
            entry["bytes"] = len(call.audio)
            entry["duration_ms"] = _duration_ms(path)
            call.duration_ms = entry["duration_ms"]
        entries.append(entry)

    # 合并历史条目：--skip-existing 轮次不覆盖上一轮已成功的记录
    manifest_path = OUTPUT_DIR / "manifest.json"
    merged: Dict[str, Dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            for old in json.loads(manifest_path.read_text(encoding="utf-8")):
                merged[str(old.get("key"))] = old
        except Exception:
            merged = {}
    for entry in entries:
        merged[entry["key"]] = entry
    manifest = list(merged.values())

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n{'gate':<5} {'key':<24} {'status':<8} {'ms':>6}  error")
    for e in manifest:
        print(
            f"{e['gate']:<5} {e['key']:<24} {str(e['http_status'] or '-'):<8} "
            f"{str(e.get('duration_ms') or '-'):>6}  {(e['error'] or '')[:70]}"
        )
    print(f"\nmanifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
