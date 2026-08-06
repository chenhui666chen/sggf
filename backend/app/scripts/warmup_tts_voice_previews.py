"""批量预热 TTS 系统音色试听到 OSS。

走真实 TTS 合成链路，逐个对所有 TTS 模型的系统音色调用试听合成，
并把音频上传到 OSS，等价于在前端逐个点击试听按钮。
命中 OSS 已缓存的条目会自动跳过，避免重复消耗 TTS 配额。

运行方式（在 backend/ 目录下）：
    python -m app.scripts.warmup_tts_voice_previews
    python -m app.scripts.warmup_tts_voice_previews --models qwen3-tts-instruct-flash --limit-per-model 3
    python -m app.scripts.warmup_tts_voice_previews --dry-run
    python -m app.scripts.warmup_tts_voice_previews --force
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def _bootstrap_environment() -> None:
    """加载 .env 并把项目根目录加入 sys.path，确保 core.* 可导入。"""
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from app.core.env_loader import load_project_env

    load_project_env(override=False)


_bootstrap_environment()


from app.api.v1.audiobook_api import routes_tts  # noqa: E402
from app.schemas.audiobook import TTSPreviewRequest  # noqa: E402
from app.services.audiobook.tts_engine import RetryConfig, TTSUserInputError  # noqa: E402
from app.services.audiobook.tts_model_ids import (  # noqa: E402
    list_supported_audiobook_tts_models,
    get_audiobook_tts_model_metadata,
)
from app.services.audiobook.tts_preview_cache import (  # noqa: E402
    _build_preview_cache_key,
    check_oss_preview_exists,
    upload_preview_to_oss,
)
from app.services.audiobook.audio_asset_cloud_storage import (  # noqa: E402
    is_audio_library_cloud_storage_enabled,
)
from app.services.audiobook.voice_catalog import (  # noqa: E402
    get_preview_quote_for_voice,
    load_voice_catalog_for_model,
)
from core.unified_media_runtime import (  # noqa: E402
    synthesize_speech as runtime_synthesize_speech,
)


DEFAULT_PREVIEW_TEXT = "当你真的喜欢一个人的时候就容易说傻话办蠢事。"
DEFAULT_VOLUME = 50
DEFAULT_SPEED = 1.0


def _get_preview_text(model_name: str, voice_id: str) -> str:
    """根据音色在 catalog 中的索引从名言列表选取试听文本，与 routes_tts 保持一致。"""
    return get_preview_quote_for_voice(model_name, voice_id)


def _iter_system_voice_models() -> list[str]:
    """返回所有提供系统音色目录的 TTS 模型。"""
    result: list[str] = []
    for model in list_supported_audiobook_tts_models():
        meta = get_audiobook_tts_model_metadata(model)
        capabilities = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
        if capabilities.get("has_system_voices", False):
            result.append(model)
    return result


def _resolve_speaker_id(voice_id: str, model_name: str) -> str:
    """复用 routes_tts 中的解析逻辑，保证与线上接口完全一致。"""
    request = TTSPreviewRequest(
        text=_get_preview_text(model_name, voice_id),
        voice_id=voice_id,
        model=model_name,
        volume=DEFAULT_VOLUME,
    )
    return routes_tts._resolve_preview_speaker_id(request, model_name)


def _build_voice_params(voice_id: str, model_name: str, speaker_id: str) -> dict:
    """复用 routes_tts 中的参数构建逻辑，保证缓存键与前端一致。"""
    request = TTSPreviewRequest(
        text=_get_preview_text(model_name, voice_id),
        voice_id=voice_id,
        model=model_name,
        volume=DEFAULT_VOLUME,
    )
    return routes_tts._build_preview_voice_params(request, speaker_id)


def _build_cache_key(model_name: str, speaker_id: str, voice_params: dict, voice_id: str) -> str:
    return _build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=_get_preview_text(model_name, voice_id),
        volume=DEFAULT_VOLUME,
        speed=DEFAULT_SPEED,
        emotion=str(voice_params.get("emotion") or "neutral"),
        voice_type="",
        mimo_voice_asset_id="",
        stepaudio_voice_asset_id="",
        voice_params=voice_params,
    )


async def _warmup_one(
    *,
    model_name: str,
    voice_entry: dict,
    force: bool,
    retry_config: RetryConfig,
) -> dict:
    """对单个 (模型, 音色) 调用真实 TTS 链路并上传 OSS。"""
    voice_id = str(voice_entry.get("id") or voice_entry.get("speaker") or "")
    label = str(voice_entry.get("label") or voice_id)
    if not voice_id:
        return {"status": "skipped", "reason": "no voice id", "label": label}

    try:
        speaker_id = _resolve_speaker_id(voice_id, model_name)
    except Exception as exc:
        return {"status": "skipped", "reason": f"resolve speaker failed: {exc}", "label": label}

    try:
        voice_params = _build_voice_params(voice_id, model_name, speaker_id)
    except Exception as exc:
        return {"status": "skipped", "reason": f"build voice params failed: {exc}", "label": label}

    cache_key = _build_cache_key(model_name, speaker_id, voice_params, voice_id)

    if not force:
        for ext in ("mp3", "wav"):
            cached_url = check_oss_preview_exists(cache_key, ext=ext)
            if cached_url:
                return {
                    "status": "cached",
                    "label": label,
                    "voice_id": voice_id,
                    "speaker_id": speaker_id,
                    "audio_url": cached_url,
                    "format": ext,
                }

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=_get_preview_text(model_name, voice_id),
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=retry_config,
        )
    except TTSUserInputError as exc:
        return {"status": "failed", "label": label, "voice_id": voice_id, "error": f"user_input: {exc}"}
    except Exception as exc:
        return {"status": "failed", "label": label, "voice_id": voice_id, "error": f"synth failed: {exc}"}

    if not audio_bytes:
        return {"status": "failed", "label": label, "voice_id": voice_id, "error": "empty audio"}

    response_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    cloud_url = upload_preview_to_oss(
        audio_bytes=audio_bytes,
        cache_key=cache_key,
        response_format=response_format,
    )

    if not cloud_url:
        return {
            "status": "failed",
            "label": label,
            "voice_id": voice_id,
            "error": "oss upload returned None (cloud storage disabled?)",
            "audio_size": len(audio_bytes),
        }

    return {
        "status": "synthesized",
        "label": label,
        "voice_id": voice_id,
        "speaker_id": speaker_id,
        "audio_url": cloud_url,
        "format": response_format,
        "audio_size": len(audio_bytes),
    }


async def _warmup_model(
    *,
    model_name: str,
    voices: list[dict],
    force: bool,
    limit: int | None,
    retry_config: RetryConfig,
) -> dict:
    total = len(voices)
    effective_voices = voices if (limit is None or limit <= 0) else voices[:limit]
    print(f"\n=== 模型: {model_name} (共 {total} 个系统音色，本次处理 {len(effective_voices)}) ===")

    counters = {"cached": 0, "synthesized": 0, "failed": 0, "skipped": 0}
    sample_url: str | None = None
    failures: list[dict] = []

    for index, voice in enumerate(effective_voices, start=1):
        label = voice.get("label") or voice.get("id") or voice.get("speaker")
        prefix = f"[{index}/{len(effective_voices)}] {label}"
        start_ts = time.perf_counter()
        result = await _warmup_one(
            model_name=model_name,
            voice_entry=voice,
            force=force,
            retry_config=retry_config,
        )
        elapsed = time.perf_counter() - start_ts
        status = result["status"]
        counters[status] = counters.get(status, 0) + 1

        if status == "cached":
            print(f"{prefix} 命中缓存 ({result.get('format')}) {result.get('audio_url')}")
            if sample_url is None:
                sample_url = result.get("audio_url")
        elif status == "synthesized":
            size_kb = (result.get("audio_size") or 0) / 1024
            print(
                f"{prefix} 合成+上传成功 ({result.get('format')}, {size_kb:.1f}KB, {elapsed:.1f}s) "
                f"{result.get('audio_url')}"
            )
            if sample_url is None:
                sample_url = result.get("audio_url")
        else:
            reason = result.get("error") or result.get("reason") or "unknown"
            print(f"{prefix} 跳过/失败: {reason}")
            if status == "failed":
                failures.append({"label": label, "voice_id": result.get("voice_id"), "error": reason})

    print(
        f"--- {model_name} 汇总: 命中缓存 {counters.get('cached', 0)} / "
        f"新合成 {counters.get('synthesized', 0)} / 失败 {counters.get('failed', 0)} / "
        f"跳过 {counters.get('skipped', 0)}"
    )
    return {
        "model": model_name,
        "total": total,
        "processed": len(effective_voices),
        "counters": counters,
        "sample_url": sample_url,
        "failures": failures,
    }


async def _run(args: argparse.Namespace) -> int:
    if not is_audio_library_cloud_storage_enabled():
        print("[警告] AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER 未启用云端存储。")
        print("       合成可继续，但上传会失败。请先在 backend/.env 中配置 aliyun_oss。")
        if not args.force:
            return 2

    target_models = _iter_system_voice_models()
    if args.models:
        requested = [item.strip() for item in args.models.split(",") if item.strip()]
        target_models = [m for m in target_models if m in requested]
        missing = [m for m in requested if m not in target_models]
        if missing:
            print(f"[警告] 以下模型不存在或不提供系统音色，已忽略: {missing}")

    if not target_models:
        print("[错误] 没有可预热的模型。")
        return 1

    print(f"待预热模型: {target_models}")
    print(f"试听文本: {DEFAULT_PREVIEW_TEXT}")
    print(f"参数: volume={DEFAULT_VOLUME} speed={DEFAULT_SPEED}")
    print(f"force={args.force} limit_per_model={args.limit_per_model} dry_run={args.dry_run}")

    retry_config = routes_tts._PREVIEW_RETRY_CONFIG

    if args.dry_run:
        print("\n[dry-run] 仅展示计划，不调用 TTS：")
        for model in target_models:
            try:
                catalog = load_voice_catalog_for_model(model)
            except Exception as exc:
                print(f"  - {model}: 加载音色目录失败: {exc}")
                continue
            voices = list(catalog.get("voices") or [])
            effective = voices if (args.limit_per_model is None or args.limit_per_model <= 0) else voices[:args.limit_per_model]
            print(f"  - {model}: 共 {len(voices)} 个系统音色，将处理 {len(effective)} 个")
            for v in effective:
                print(f"      · {v.get('label') or v.get('id')} (speaker={v.get('speaker')})")
        return 0

    overall_counters = {"cached": 0, "synthesized": 0, "failed": 0, "skipped": 0}
    all_failures: list[dict] = []
    sample_urls: dict[str, str | None] = {}

    for model in target_models:
        try:
            catalog = load_voice_catalog_for_model(model)
        except Exception as exc:
            print(f"\n[跳过] 加载 {model} 音色目录失败: {exc}")
            continue
        voices = list(catalog.get("voices") or [])
        if not voices:
            print(f"\n[跳过] {model} 无系统音色。")
            continue

        summary = await _warmup_model(
            model_name=model,
            voices=voices,
            force=args.force,
            limit=args.limit_per_model,
            retry_config=retry_config,
        )
        for key, value in summary["counters"].items():
            overall_counters[key] = overall_counters.get(key, 0) + value
        all_failures.extend(summary["failures"])
        sample_urls[model] = summary["sample_url"]

    print("\n" + "=" * 60)
    print("全量预热完成")
    print("=" * 60)
    print(
        f"命中缓存: {overall_counters.get('cached', 0)} | "
        f"新合成并上传: {overall_counters.get('synthesized', 0)} | "
        f"失败: {overall_counters.get('failed', 0)} | "
        f"跳过: {overall_counters.get('skipped', 0)}"
    )
    if sample_urls:
        print("\n各模型示例 URL：")
        for model, url in sample_urls.items():
            if url:
                print(f"  - {model}: {url}")
    if all_failures:
        print(f"\n失败明细 ({len(all_failures)} 条)：")
        for item in all_failures:
            print(f"  - {item.get('label')} ({item.get('voice_id')}): {item.get('error')}")

    return 0 if not all_failures else 3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量预热 TTS 系统音色试听到 OSS",
    )
    parser.add_argument(
        "--models",
        default="",
        help="逗号分隔的模型 ID 列表，默认覆盖所有提供系统音色的模型",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_PREVIEW_TEXT,
        help="试听文本（默认前端默认文本，不建议修改，否则前端无法命中缓存）",
    )
    parser.add_argument(
        "--limit-per-model",
        type=int,
        default=0,
        help="每个模型最多预热的音色数，0 表示不限制",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略 OSS 已缓存，强制重新合成并上传",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印预热计划，不调用 TTS",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.text and args.text != DEFAULT_PREVIEW_TEXT:
        print(f"[警告] 自定义试听文本不会与前端默认调用对齐，前端可能无法命中缓存: {args.text}")
    # 脚本内部仍使用 DEFAULT_PREVIEW_TEXT，仅做参数校验/提示，避免缓存键漂移。
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
