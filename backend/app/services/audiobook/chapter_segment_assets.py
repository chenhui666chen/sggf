"""章节片段音频持久化存储。

工作台保存/管线生成的片段音频统一持久化到稳定的存储前缀
（temp_segment_store 的 ``chapter_segments_persistent`` run 命名空间下，
按 chapter_audio_id 划分目录），供以下链路复用：

- 工作台分段试听：``load_cached_segment_audio`` 按 asset ref 直接读取；
- 管线断点复用：按 render chunk cache_key 注入 resume checkpoint；
- 整章重新混合：按 script_json 中的 audio_path 读取最新片段音频。

持久化前缀不归属任何 ChapterAudioRun 的 temp_asset_prefix，
因此不会被 run 完成/过期清理逻辑删除；删除章节产物时需显式调用
``delete_chapter_persistent_segment_assets`` 清理。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from app.services.audiobook.render_plan import build_render_plan
from app.services.audiobook.temp_segment_store import (
    TempSegmentStoreError,
    build_temp_segment_prefix,
    delete_temp_segment_prefix,
    load_cached_segment_audio,
    normalize_audio_extension,
    save_segment_audio_map,
    temp_segment_asset_exists,
)

logger = logging.getLogger(__name__)

PERSISTENT_SEGMENT_RUN_ID_PREFIX = "chapter_segments_persistent"
_PERSISTENT_PREVIEW_TYPES = ("voice", "sfx", "bgm", "mix")

# 片段音频资产字段由服务端管理（生成/候选应用时写入），
# 客户端提交的剧本/片段覆盖不得携带，防止注入任意音频路径。
SERVER_MANAGED_SEGMENT_ASSET_FIELDS = (
    "audio_path",
    "sfx_audio_path",
    "bgm_audio_path",
    "mix_audio_path",
    "audio_cache_key",
    "audio_chunk_cache_paths",
    "audio_render_chunk_max_chars",
    # 工作台直接生成并固化的是完整片段；该模式由服务端写入，
    # 让后续管线按完整片段复用，而不是把同一音频误当成某个子 chunk。
    "audio_render_mode",
)

# compute_segment_audio_cache_key 的 render_chunk_max_chars 未提供哨兵：
# 区分“未提供（按模型推断）”与显式传入 None/数值
_UNSET_CHUNK_LIMIT = object()

# 语义同步前的 v1 签名只从 voice_params 读取这些导演字段。
# 兼容旧签名前必须确认顶层值仍与旧副本一致，避免掩盖真实编辑。
_PRE_SEMANTIC_SYNC_DIRECTION_FIELDS = (
    "instruct_scene",
    "instruct_role",
    "instruct_identity",
)

# 多 chunk 片段的单块音频持久化命名空间（供管线按 render chunk 签名复用）
_PERSISTENT_CHUNK_RUN_ID = "chapter_segments_persistent_chunks"
# 虚拟索引步长：chunk 存储索引 = segment_index * 步长 + chunk 序号
_CHUNK_INDEX_STRIDE = 10000

# 数组索引会随片段插入和重排变化。带稳定 segment_key 的片段使用独立的高位槽，
# 避免重新生成时按新数组索引清理到其他片段仍在引用的历史文件。
_STABLE_SEGMENT_STORAGE_INDEX_OFFSET = 1_000_000_000

# 候选片段音频的存储前缀（删除章节产物时一并回收）
_CANDIDATE_RUN_ID_PREFIXES = (
    "segment_regen_candidate_voice",
    "segment_regen_candidate_sfx",
    "segment_regen_candidate_bgm",
    "segment_regen_candidate_mix",
    "segment_voice_recording_candidate",
)


def _persistent_run_id(preview_type: str) -> str:
    normalized = str(preview_type or "voice").strip().lower() or "voice"
    if normalized not in _PERSISTENT_PREVIEW_TYPES:
        normalized = "voice"
    return f"{PERSISTENT_SEGMENT_RUN_ID_PREFIX}_{normalized}"


def is_persistent_segment_asset_ref(asset_ref: Optional[str]) -> bool:
    """判断 asset ref 是否属于持久化片段前缀（用于识别可安全清理的旧片段）。"""
    raw = str(asset_ref or "").strip().lower()
    if not raw:
        return False
    return PERSISTENT_SEGMENT_RUN_ID_PREFIX in raw


def resolve_segment_asset_storage_index(segment: Any, fallback_index: int) -> int:
    """把稳定片段身份映射为物理存储槽；旧数据没有 key 时回退数组索引。"""
    if isinstance(segment, dict):
        raw_key = segment.get("segment_key")
    else:
        raw_key = getattr(segment, "segment_key", None)
    segment_key = str(raw_key or "").strip()
    if not segment_key:
        return int(fallback_index)
    digest_prefix = hashlib.sha1(segment_key.encode("utf-8")).hexdigest()[:12]
    return _STABLE_SEGMENT_STORAGE_INDEX_OFFSET + int(digest_prefix, 16)


def save_persistent_segment_audio(
    *,
    chapter_audio_id: int,
    segment_index: int,
    segment_key: Optional[str] = None,
    audio_bytes: bytes,
    preview_type: str = "voice",
    output_format: Optional[str] = None,
) -> str:
    """把片段音频写入持久化前缀并返回 asset ref。

    同一 (chapter_audio_id, preview_type, stable segment identity) 的旧版本文件会被自动清除。
    """
    extension = normalize_audio_extension(output_format)
    storage_index = resolve_segment_asset_storage_index(
        {"segment_key": segment_key},
        segment_index,
    )
    result = save_segment_audio_map(
        run_id=_persistent_run_id(preview_type),
        chapter_id=chapter_audio_id,
        audio_map={storage_index: audio_bytes},
        format=extension,
    )
    asset_ref = str((result.get("cached_audio_paths") or {}).get(storage_index) or "")
    if not asset_ref:
        raise RuntimeError("持久化片段音频失败: cached_audio_paths 缺失")
    return asset_ref


def load_persistent_segment_audio(asset_ref: Optional[str]) -> Optional[bytes]:
    raw = str(asset_ref or "").strip()
    if not raw:
        return None
    audio_by_index = load_cached_segment_audio({"cached_audio_paths": {0: raw}})
    return audio_by_index.get(0)


def save_persistent_segment_chunk_audio(
    *,
    chapter_audio_id: int,
    segment_index: int,
    segment_key: Optional[str] = None,
    chunk_position: int,
    audio_bytes: bytes,
    output_format: Optional[str] = None,
) -> str:
    """把多 chunk 片段的单个 render chunk 音频写入持久化 chunk 命名空间。

    与片段级合并音频（``save_persistent_segment_audio``）分开存放，
    供管线断点复用时按 chunk 签名精确注入 resume checkpoint。
    """
    extension = normalize_audio_extension(output_format)
    storage_index = resolve_segment_asset_storage_index(
        {"segment_key": segment_key},
        segment_index,
    )
    virtual_index = storage_index * _CHUNK_INDEX_STRIDE + int(chunk_position)
    result = save_segment_audio_map(
        run_id=_PERSISTENT_CHUNK_RUN_ID,
        chapter_id=chapter_audio_id,
        audio_map={virtual_index: audio_bytes},
        format=extension,
    )
    asset_ref = str((result.get("cached_audio_paths") or {}).get(virtual_index) or "")
    if not asset_ref:
        raise RuntimeError("持久化片段 chunk 音频失败: cached_audio_paths 缺失")
    return asset_ref


def persistent_segment_audio_exists(asset_ref: Optional[str]) -> bool:
    return temp_segment_asset_exists(asset_ref)


def collect_segment_asset_refs(segment: Any) -> set[str]:
    """收集单个片段登记的四类轨道和多 chunk 资产引用。"""
    refs: set[str] = set()
    if not isinstance(segment, dict):
        return refs
    for field in ("audio_path", "sfx_audio_path", "bgm_audio_path", "mix_audio_path"):
        ref = str(segment.get(field) or "").strip()
        if ref:
            refs.add(ref)
    chunk_refs = segment.get("audio_chunk_cache_paths")
    if isinstance(chunk_refs, dict):
        for raw_ref in chunk_refs.values():
            ref = str(raw_ref or "").strip()
            if ref:
                refs.add(ref)
    return refs


def collect_chapter_segment_asset_refs(chapter_audio: Any) -> set[str]:
    """收集章节脚本登记的完整片段资产清单，包括多 chunk 引用。"""
    refs: set[str] = set()
    script_json = getattr(chapter_audio, "script_json", None)
    if not script_json:
        return refs
    try:
        segments = json.loads(script_json)
    except (TypeError, ValueError):
        return refs
    if not isinstance(segments, list):
        return refs
    for segment in segments:
        refs.update(collect_segment_asset_refs(segment))
    return refs


def delete_segment_asset_refs(asset_refs: Iterable[str]) -> int:
    """按显式 ref 清单删除资产，兼容无法按前缀枚举对象的 OSS 驱动。"""
    normalized_refs = sorted(
        {
            str(asset_ref or "").strip()
            for asset_ref in asset_refs
            if str(asset_ref or "").strip()
        }
    )
    if not normalized_refs:
        return 0
    return int(
        max(
            delete_temp_segment_prefix(
                None,
                {
                    "cached_audio_paths": {
                        str(index): ref for index, ref in enumerate(normalized_refs)
                    }
                },
            ),
            0,
        )
    )


def delete_replaced_segment_asset_refs(
    previous_refs: Iterable[str],
    current_refs: Iterable[str],
) -> int:
    """删除替换后不再被引用的服务端持久片段资产。"""
    active_refs = {
        str(asset_ref or "").strip()
        for asset_ref in current_refs
        if str(asset_ref or "").strip()
    }
    normalized_previous_refs = {
        str(asset_ref or "").strip()
        for asset_ref in previous_refs
        if str(asset_ref or "").strip()
    }
    obsolete_refs = {
        asset_ref
        for asset_ref in normalized_previous_refs - active_refs
        if is_persistent_segment_asset_ref(asset_ref)
    }
    return delete_segment_asset_refs(obsolete_refs)


def delete_chapter_persistent_segment_assets(chapter_audio: Any) -> Dict[str, Any]:
    """删除章节的全部持久化片段音频（删除章节产物时调用）。

    同时处理剧本中记录的 asset ref（兼容 OSS 驱动）与
    各 preview_type 前缀目录（兜底清理未被剧本引用的残留文件）。
    """
    chapter_audio_id = getattr(chapter_audio, "id", None)
    if chapter_audio_id is None:
        return {"removed_files": 0, "deleted_refs": 0}

    removed_files = 0
    refs = collect_chapter_segment_asset_refs(chapter_audio)
    if refs:
        persistent_refs = {ref for ref in refs if is_persistent_segment_asset_ref(ref)}
        if persistent_refs:
            removed_files += delete_segment_asset_refs(persistent_refs)

    for preview_type in _PERSISTENT_PREVIEW_TYPES:
        prefix = build_temp_segment_prefix(
            run_id=_persistent_run_id(preview_type),
            chapter_id=chapter_audio_id,
        )
        try:
            removed_files += int(
                max(delete_temp_segment_prefix(prefix, None), 0)
            )
        except Exception as exc:
            logger.warning(
                "删除章节持久化片段前缀失败: chapter_audio_id=%s prefix=%s error=%s",
                chapter_audio_id,
                prefix,
                exc,
            )

    # 同步回收多 chunk 片段的单块持久化音频
    chunk_prefix = build_temp_segment_prefix(
        run_id=_PERSISTENT_CHUNK_RUN_ID,
        chapter_id=chapter_audio_id,
    )
    try:
        removed_files += int(max(delete_temp_segment_prefix(chunk_prefix, None), 0))
    except Exception as exc:
        logger.warning(
            "删除章节持久化 chunk 前缀失败: chapter_audio_id=%s prefix=%s error=%s",
            chapter_audio_id,
            chunk_prefix,
            exc,
        )

    # 同步回收片段重生成/配音候选资产，避免孤儿文件
    for candidate_prefix_name in _CANDIDATE_RUN_ID_PREFIXES:
        prefix = build_temp_segment_prefix(
            run_id=f"{candidate_prefix_name}_{chapter_audio_id}",
            chapter_id=getattr(chapter_audio, "chapter_id", None) or 0,
        )
        try:
            removed_files += int(
                max(delete_temp_segment_prefix(prefix, None), 0)
            )
        except Exception as exc:
            logger.warning(
                "删除章节候选片段前缀失败: chapter_audio_id=%s prefix=%s error=%s",
                chapter_audio_id,
                prefix,
                exc,
            )

    return {"removed_files": removed_files, "deleted_refs": len(refs)}


def _normalize_segment_for_render_plan(segment: Any) -> Any:
    if isinstance(segment, dict):
        try:
            return SimpleNamespace(**segment)
        except TypeError:
            return segment
    return segment


def combine_chunk_cache_keys(chunk_keys: List[str]) -> str:
    """把同一片段全部 render chunk 的签名合并为片段级签名。

    单 chunk 片段直接使用 chunk 签名（与管线 cache_key 一致，可按块复用）；
    多 chunk 片段使用全部 chunk 签名的组合哈希（不可按块复用，但可做过期判定）。
    """
    keys = [str(key or "").strip() for key in chunk_keys]
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    digest = hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()
    return f"multi:{digest}"


def resolve_chapter_render_chunk_max_chars(
    segments: Any,
    *,
    default_tts_model: Optional[str] = None,
) -> int:
    """与引擎 ``_build_render_chunks`` 一致的分块决策，返回最终生效的分块上限。

    任一片段声明 Qwen 模型或默认模型为 Qwen 时使用更小分块上限，
    否则使用默认策略（环境变量或内置默认值）的最终生效值。
    """
    from app.services.audiobook.engine_pkg._tts_mixin import (
        QWEN_RENDER_CHUNK_MAX_CHARS,
        _is_qwen_tts_model,
        _item_tts_model,
    )
    from app.services.audiobook.render_plan import _resolve_chunk_char_limit

    has_qwen_model = _is_qwen_tts_model(default_tts_model) or any(
        _is_qwen_tts_model(_item_tts_model(item))
        for item in list(segments or [])
        if _item_tts_model(item)
    )
    if has_qwen_model:
        return int(QWEN_RENDER_CHUNK_MAX_CHARS)
    return int(_resolve_chunk_char_limit(None))


def _compute_segment_audio_cache_key(
    segment: Any,
    *,
    default_tts_model: Optional[str] = None,
    render_chunk_max_chars: Any = _UNSET_CHUNK_LIMIT,
    synchronize_semantics: bool,
) -> str:
    from app.services.audiobook.engine_pkg._tts_mixin import (
        QWEN_RENDER_CHUNK_MAX_CHARS,
        _is_qwen_tts_model,
    )
    from app.services.audiobook.tts_delivery_plan import resolve_segment_tts_model

    normalized = _normalize_segment_for_render_plan(segment)
    raw_voice_params = getattr(normalized, "voice_params", None)
    voice_params = raw_voice_params if isinstance(raw_voice_params, dict) else {}
    if render_chunk_max_chars is _UNSET_CHUNK_LIMIT:
        resolved_model = resolve_segment_tts_model(voice_params, default_tts_model)
        max_chunk_chars = (
            QWEN_RENDER_CHUNK_MAX_CHARS if _is_qwen_tts_model(resolved_model) else None
        )
    else:
        max_chunk_chars = render_chunk_max_chars
    chunks = build_render_plan(
        [normalized],
        max_chunk_chars=max_chunk_chars,
        _synchronize_semantics=synchronize_semantics,
    )
    if not chunks:
        return ""
    return combine_chunk_cache_keys([str(chunk.cache_key or "") for chunk in chunks])


def compute_segment_audio_cache_key(
    segment: Any,
    *,
    default_tts_model: Optional[str] = None,
    render_chunk_max_chars: Any = _UNSET_CHUNK_LIMIT,
) -> str:
    """计算片段音频签名（全部 render chunk 签名的合并）。

    用于判断“片段文本/音色参数已修改、已保存音频过期”。
    与管线 ``build_render_plan`` 使用同一签名算法，保证按签名复用时的一致性。
    显式传入 ``render_chunk_max_chars`` 时按该分块上限复现签名
    （应使用片段记录的生成上下文），未提供时按片段 TTS 模型推断
    （Qwen 模型使用更小的分块上限）。
    """
    return _compute_segment_audio_cache_key(
        segment,
        default_tts_model=default_tts_model,
        render_chunk_max_chars=render_chunk_max_chars,
        synchronize_semantics=True,
    )


def _compute_pre_semantic_sync_audio_cache_key(
    segment: Any,
    *,
    default_tts_model: Optional[str] = None,
    render_chunk_max_chars: Any = _UNSET_CHUNK_LIMIT,
) -> str:
    """冻结语义同步前的 v1 签名投影，仅用于验证并迁移历史资产。"""
    return _compute_segment_audio_cache_key(
        segment,
        default_tts_model=default_tts_model,
        render_chunk_max_chars=render_chunk_max_chars,
        synchronize_semantics=False,
    )


def _pre_semantic_sync_direction_is_coherent(segment: Dict[str, Any]) -> bool:
    voice_params = segment.get("voice_params")
    nested = voice_params if isinstance(voice_params, dict) else {}
    for field_name in _PRE_SEMANTIC_SYNC_DIRECTION_FIELDS:
        if field_name not in segment:
            continue
        top_level_value = str(segment.get(field_name) or "").strip()
        nested_value = str(nested.get(field_name) or "").strip()
        if top_level_value != nested_value:
            return False
    return True


def _pre_semantic_sync_signature_matches(
    segment: Dict[str, Any],
    stored_key: str,
    *,
    default_tts_model: Optional[str] = None,
    render_chunk_max_chars: Any = _UNSET_CHUNK_LIMIT,
) -> bool:
    if not _pre_semantic_sync_direction_is_coherent(segment):
        return False
    legacy_key = _compute_pre_semantic_sync_audio_cache_key(
        segment,
        default_tts_model=default_tts_model,
        render_chunk_max_chars=render_chunk_max_chars,
    )
    return bool(legacy_key and stored_key == legacy_key)


def _recorded_render_chunk_max_chars(segment: Dict[str, Any]) -> Optional[int]:
    """读取片段记录的生成时分块上限（非法值视为未记录）。"""
    recorded = segment.get("audio_render_chunk_max_chars")
    if isinstance(recorded, bool) or not isinstance(recorded, int) or recorded <= 0:
        return None
    return recorded


def infer_segment_render_chunk_max_chars(
    segment: Any,
    *,
    default_tts_model: Optional[str] = None,
) -> int:
    """按片段 TTS 模型推断生成分块上限（与 compute 推断分支同策略）。

    与 ``compute_segment_audio_cache_key`` 未显式传入上限时的推断路径
    保持一致（同一 resolve_segment_tts_model 回退链），避免自愈重写
    签名时记录的上下文与验签推断不匹配。
    """
    from app.services.audiobook.engine_pkg._tts_mixin import (
        QWEN_RENDER_CHUNK_MAX_CHARS,
        _is_qwen_tts_model,
    )
    from app.services.audiobook.render_plan import _resolve_chunk_char_limit
    from app.services.audiobook.tts_delivery_plan import resolve_segment_tts_model

    normalized = _normalize_segment_for_render_plan(segment)
    raw_voice_params = getattr(normalized, "voice_params", None)
    voice_params = raw_voice_params if isinstance(raw_voice_params, dict) else {}
    resolved_model = resolve_segment_tts_model(voice_params, default_tts_model)
    if _is_qwen_tts_model(resolved_model):
        return int(QWEN_RENDER_CHUNK_MAX_CHARS)
    return int(_resolve_chunk_char_limit(None))


def segment_audio_signature_status(
    segment: Dict[str, Any],
    *,
    default_tts_model: Optional[str] = None,
) -> str:
    """片段已保存音频签名的三态判定。

    - ``current``：签名与当前片段参数一致；
    - ``stale``：有记录的生成分块上下文且重算不匹配（文本/音色已修改）；
    - ``unverifiable``：未记录签名，或旧格式签名无法用现有策略复现，
      无法判定是否过期（不得误报过期）。

    优先使用片段记录的生成时分块上下文精确复现签名；历史数据无上下文时，
    按模型推断与默认分块策略各重算一次，任一匹配即视为 current。
    """
    if not isinstance(segment, dict):
        return "unverifiable"
    stored_key = str(segment.get("audio_cache_key") or "").strip()
    if not stored_key:
        return "unverifiable"
    recorded_limit = _recorded_render_chunk_max_chars(segment)
    if recorded_limit is not None:
        current_key = compute_segment_audio_cache_key(
            segment,
            render_chunk_max_chars=recorded_limit,
        )
        if current_key and stored_key == current_key:
            return "current"
        if _pre_semantic_sync_signature_matches(
            segment,
            stored_key,
            default_tts_model=default_tts_model,
            render_chunk_max_chars=recorded_limit,
        ):
            return "current"
        return "stale"
    current_key = compute_segment_audio_cache_key(
        segment,
        default_tts_model=default_tts_model,
    )
    if current_key and stored_key == current_key:
        return "current"
    from app.services.audiobook.render_plan import _resolve_chunk_char_limit

    fallback_key = compute_segment_audio_cache_key(
        segment,
        render_chunk_max_chars=_resolve_chunk_char_limit(None),
    )
    if fallback_key and stored_key == fallback_key:
        return "current"
    return "unverifiable"


def segment_audio_cache_key_is_current(
    segment: Dict[str, Any],
    *,
    default_tts_model: Optional[str] = None,
) -> bool:
    """片段已保存音频的签名是否与当前片段参数严格一致。

    严格布尔判定（仅 ``current`` 为 True），用于固化时跳过覆盖检查；
    缺失上报等需要区分“过期”与“无法验证”的场景应使用
    ``segment_audio_signature_status``。
    """
    return (
        segment_audio_signature_status(segment, default_tts_model=default_tts_model)
        == "current"
    )


def _concatenate_chunk_audio(chunk_audio_list: List[bytes]) -> Optional[bytes]:
    """把同一片段的多个 chunk 音频按序拼接为完整片段音频。

    单 chunk 直接返回；多 chunk 使用 pydub 解码后拼接，
    避免 wav 直接字节拼接破坏文件头。失败时返回 None（放弃固化，不产生残缺音频）。
    """
    valid_chunks = [audio for audio in chunk_audio_list if audio]
    if not valid_chunks:
        return None
    if len(valid_chunks) == 1:
        return valid_chunks[0]
    try:
        from pydub import AudioSegment

        combined = AudioSegment.empty()
        for audio_bytes in valid_chunks:
            combined += AudioSegment.from_file(io.BytesIO(audio_bytes))
        output_format = "wav" if valid_chunks[0].startswith(b"RIFF") else "mp3"
        buffer = io.BytesIO()
        combined.export(buffer, format=output_format)
        return buffer.getvalue()
    except Exception as exc:
        logger.warning("合并多 chunk 片段音频失败，跳过固化: %s", exc)
        return None


def persist_generated_chapter_segment_audio(
    *,
    chapter_audio: Any,
    result: Dict[str, Any],
    tts_model: Optional[str] = None,
) -> Dict[int, str]:
    """在 run 临时资产被清理前，把管线合成的片段音频固化并写回 script_json。

    从 ``result["temp_segment_cache"]`` 读取片段音频与 render_plan：
    对归属单个片段的 chunk，按片段归组合并同源多 chunk 音频（仅当该片段
    全部 chunk 音频均已合成时固化），把完整片段音频写入持久化前缀，
    并把片段级合并签名写入 ``audio_path`` / ``audio_cache_key``。
    同时记录生成分块上下文 ``audio_render_chunk_max_chars``（按 ``tts_model``
    与引擎一致的分块决策），供验签时精确复现签名。
    已持有有效持久化音频且签名未过期的片段（如工作台生成）不会被覆盖。
    返回 {segment_index: persistent_ref}。
    """
    chapter_audio_id = getattr(chapter_audio, "id", None)
    temp_cache = result.get("temp_segment_cache") if isinstance(result, dict) else None
    if chapter_audio_id is None or not isinstance(temp_cache, dict):
        return {}

    try:
        segments = json.loads(getattr(chapter_audio, "script_json", None) or "[]")
    except (TypeError, ValueError):
        return {}
    if not isinstance(segments, list) or not segments:
        return {}

    render_plan = temp_cache.get("render_plan")
    if not isinstance(render_plan, list):
        return {}
    chunk_payload_by_index: Dict[int, Dict[str, Any]] = {}
    for item in render_plan:
        if not isinstance(item, dict):
            continue
        try:
            chunk_index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        chunk_payload_by_index[chunk_index] = item

    audio_by_index = load_cached_segment_audio(temp_cache)
    if not audio_by_index:
        return {}

    # 与运行时引擎一致的分块决策：记录最终生效的分块上限，
    # 验签时按该上下文精确复现签名，避免不同模型的误判
    effective_chunk_limit = resolve_chapter_render_chunk_max_chars(
        segments,
        default_tts_model=tts_model,
    )

    persisted: Dict[int, str] = {}
    changed = False

    # 按片段归组：仅处理“单片段独占”的 chunk，统计计划内全部 chunk
    planned_chunks_by_segment: Dict[int, List[int]] = {}
    for chunk_index, chunk_payload in chunk_payload_by_index.items():
        source_indices = list(chunk_payload.get("source_segment_indices") or [])
        if len(source_indices) != 1:
            continue
        segment_index = source_indices[0]
        if not isinstance(segment_index, int) or not 0 <= segment_index < len(segments):
            continue
        planned_chunks_by_segment.setdefault(segment_index, []).append(chunk_index)

    for segment_index in sorted(planned_chunks_by_segment):
        chunk_indices = sorted(planned_chunks_by_segment[segment_index])
        segment = segments[segment_index]
        if not isinstance(segment, dict):
            continue

        # 工作台已固化且签名未过期的片段保持原音频，不被管线音频覆盖
        existing_ref = str(segment.get("audio_path") or "").strip()
        if is_persistent_segment_asset_ref(existing_ref) and segment_audio_cache_key_is_current(segment):
            continue

        # 片段全部 chunk 均已合成才固化，避免只保留部分内容
        chunk_audio_list = [audio_by_index.get(chunk_index) for chunk_index in chunk_indices]
        if any(not audio for audio in chunk_audio_list):
            logger.info(
                "片段部分 chunk 未合成，跳过固化: chapter_audio_id=%s segment_index=%s chunks=%s",
                chapter_audio_id,
                segment_index,
                chunk_indices,
            )
            continue
        merged_audio = _concatenate_chunk_audio(list(chunk_audio_list))
        if not merged_audio:
            continue

        extension = "wav" if merged_audio.startswith(b"RIFF") else "mp3"
        try:
            asset_ref = save_persistent_segment_audio(
                chapter_audio_id=chapter_audio_id,
                segment_index=segment_index,
                segment_key=str(segment.get("segment_key") or "").strip() or None,
                audio_bytes=merged_audio,
                preview_type="voice",
                output_format=extension,
            )
        except (OSError, RuntimeError, TempSegmentStoreError) as exc:
            logger.warning(
                "固化管线片段音频失败: chapter_audio_id=%s segment_index=%s error=%s",
                chapter_audio_id,
                segment_index,
                exc,
            )
            continue

        # 多 chunk 片段同步固化单块音频，供管线按 chunk 签名断点复用
        chunk_cache_paths: Dict[str, str] = {}
        if len(chunk_indices) > 1:
            for chunk_position, chunk_index in enumerate(chunk_indices):
                chunk_audio = chunk_audio_list[chunk_position]
                chunk_extension = "wav" if chunk_audio.startswith(b"RIFF") else "mp3"
                try:
                    chunk_ref = save_persistent_segment_chunk_audio(
                        chapter_audio_id=chapter_audio_id,
                        segment_index=segment_index,
                        segment_key=str(segment.get("segment_key") or "").strip() or None,
                        chunk_position=chunk_position,
                        audio_bytes=chunk_audio,
                        output_format=chunk_extension,
                    )
                except (OSError, RuntimeError, TempSegmentStoreError) as exc:
                    logger.warning(
                        "固化片段 chunk 音频失败，放弃该片段断点复用: "
                        "chapter_audio_id=%s segment_index=%s chunk=%s error=%s",
                        chapter_audio_id,
                        segment_index,
                        chunk_index,
                        exc,
                    )
                    chunk_cache_paths = {}
                    break
                chunk_key = str(
                    chunk_payload_by_index[chunk_index].get("cache_key") or ""
                ).strip()
                if chunk_key:
                    chunk_cache_paths[chunk_key] = chunk_ref

        segment["audio_path"] = asset_ref
        chunk_keys = [
            str(chunk_payload_by_index[chunk_index].get("cache_key") or "")
            for chunk_index in chunk_indices
        ]
        cache_key = combine_chunk_cache_keys(chunk_keys)
        if cache_key:
            segment["audio_cache_key"] = cache_key
            segment["audio_render_chunk_max_chars"] = effective_chunk_limit
        if chunk_cache_paths:
            segment["audio_chunk_cache_paths"] = chunk_cache_paths
        elif "audio_chunk_cache_paths" in segment:
            # 单 chunk 固化或 chunk 固化失败时清理旧映射，避免错绑
            del segment["audio_chunk_cache_paths"]
        persisted[segment_index] = asset_ref
        changed = True

    if changed:
        chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    return persisted


def repair_legacy_segment_signatures(chapter_audio: Any) -> bool:
    """惰性迁移可精确验证的旧版片段签名。

    仅当片段记录了生成分块上下文、保存签名精确命中语义同步前投影，
    且导演字段与历史 voice_params 副本一致时，迁移为当前签名。
    缺少生成上下文或无法验证的历史资产保持原样，避免把未知音频认证为
    当前文本、音色和表演指令的产物；实际音频文件不会被删除。
    返回是否有变更（调用方需 commit）。
    """
    try:
        segments = json.loads(getattr(chapter_audio, "script_json", None) or "[]")
    except (TypeError, ValueError):
        return False
    if not isinstance(segments, list) or not segments:
        return False

    changed = False
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        audio_ref = str(segment.get("audio_path") or "").strip()
        if not is_persistent_segment_asset_ref(audio_ref):
            continue
        if not str(segment.get("audio_cache_key") or "").strip():
            continue
        recorded_limit = _recorded_render_chunk_max_chars(segment)
        if recorded_limit is not None:
            stored_key = str(segment.get("audio_cache_key") or "").strip()
            current_key = compute_segment_audio_cache_key(
                segment,
                render_chunk_max_chars=recorded_limit,
            )
            if current_key and stored_key == current_key:
                continue
            if not current_key or not _pre_semantic_sync_signature_matches(
                segment,
                stored_key,
                render_chunk_max_chars=recorded_limit,
            ):
                continue
            segment["audio_cache_key"] = current_key
            segment.pop("audio_chunk_cache_paths", None)
            changed = True

    if changed:
        chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    return changed


__all__ = [
    "PERSISTENT_SEGMENT_RUN_ID_PREFIX",
    "SERVER_MANAGED_SEGMENT_ASSET_FIELDS",
    "combine_chunk_cache_keys",
    "collect_chapter_segment_asset_refs",
    "collect_segment_asset_refs",
    "compute_segment_audio_cache_key",
    "delete_chapter_persistent_segment_assets",
    "delete_replaced_segment_asset_refs",
    "delete_segment_asset_refs",
    "infer_segment_render_chunk_max_chars",
    "is_persistent_segment_asset_ref",
    "load_persistent_segment_audio",
    "persist_generated_chapter_segment_audio",
    "persistent_segment_audio_exists",
    "repair_legacy_segment_signatures",
    "resolve_chapter_render_chunk_max_chars",
    "resolve_segment_asset_storage_index",
    "save_persistent_segment_audio",
    "save_persistent_segment_chunk_audio",
    "segment_audio_cache_key_is_current",
    "segment_audio_signature_status",
]
