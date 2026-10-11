"""片段音频签名的运行时产物排除、三态判定与受控迁移测试。

回归目标：历史管线片段的存储签名可能来自旧版代码迭代而无法复现，
这类音频可继续保留和试听，但不得被认证为当前版本或参与整章混音；
只有携带明确生成上下文且精确命中旧投影的签名才允许受控迁移。
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


TEST_CHAPTER_AUDIO_ID = 98765601

# 混音层/运行时产物字段：不参与片段 TTS 音频内容，必须从签名中排除
_VOLATILE_FIELDS = {
    "timeline_pause_after_ms": 320,
    "cadence_profile": "calm",
    "cadence_reason": "test",
    "timeline_boundary_managed": True,
    "delivery_plan": {"provider": "x"},
    "provider_prompt_snapshot": "snapshot",
    "resolved_tts_model": "qwen-audio-3.1-tts-flash",
    "use_instruct_mode": True,
}


def _build_segment():
    return {
        "type": "dialogue",
        "text": "这是一段用于签名自愈的测试台词。",
        "speaker": "林黛玉",
        "voice_params": {"speaker": "voice-a", "rate": 1.0},
    }


@pytest.fixture()
def cleanup_test_assets():
    # 保证分块上限确定性：测试期间忽略环境变量覆盖
    yield
    from app.services.audiobook import chapter_segment_assets

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)


def test_signature_ignores_runtime_delivery_fields():
    """运行时产物/混音层字段回填进 voice_params 后签名必须保持不变。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_segment()
    base_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    segment["voice_params"].update(_VOLATILE_FIELDS)
    assert chapter_segment_assets.compute_segment_audio_cache_key(segment) == base_key


def test_signature_voice_params_excludes_volatile_keys():
    from app.services.audiobook.render_plan import _signature_voice_params

    result = _signature_voice_params(
        {"speaker": "v1", "rate": 1.0, **_VOLATILE_FIELDS}
    )
    assert "speaker" in result
    assert "rate" in result
    for field in _VOLATILE_FIELDS:
        assert field not in result


def test_signature_status_three_states():
    """三态判定：current / stale / unverifiable。"""
    from app.services.audiobook import chapter_segment_assets as assets

    # 无存储签名 → 无法验证
    assert assets.segment_audio_signature_status(_build_segment()) == "unverifiable"

    # 有记录上下文且匹配 → current；文本修改后 → stale（严格判定）
    segment = _build_segment()
    segment["audio_cache_key"] = assets.compute_segment_audio_cache_key(
        segment, render_chunk_max_chars=420
    )
    segment["audio_render_chunk_max_chars"] = 420
    assert assets.segment_audio_signature_status(segment) == "current"
    modified = dict(segment)
    modified["text"] = "文本已被修改，签名必须判定为过期。"
    assert assets.segment_audio_signature_status(modified) == "stale"

    # 无记录上下文且任何策略都无法复现 → unverifiable（旧格式，不误报过期）
    legacy = _build_segment()
    legacy["audio_cache_key"] = "legacy_unreproducible_key"
    assert assets.segment_audio_signature_status(legacy) == "unverifiable"


def test_remix_reports_unverifiable_legacy_signature_without_deleting_audio(
    cleanup_test_assets,
):
    """无法验证来源的音频不得参与混音，但其持久化文件必须保留。"""
    from app.services.audiobook import background_jobs_remix as remix
    from app.services.audiobook import chapter_segment_assets

    segment = _build_segment()
    segment["audio_cache_key"] = "legacy_unreproducible_key"
    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 legacy audio",
    )
    segment["audio_path"] = asset_ref
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    assert remix.collect_chapter_remix_missing_segments(chapter_audio) == [
        {
            "index": 0,
            "speaker": "林黛玉",
            "text_preview": "这是一段用于签名自愈的测试台词。",
            "reason": "stale_audio",
        }
    ]
    assert chapter_segment_assets.persistent_segment_audio_exists(asset_ref)


def test_repair_does_not_certify_unverifiable_legacy_signature(cleanup_test_assets):
    """缺少生成上下文的旧音频不得被重签为当前版本。"""
    from app.services.audiobook import chapter_segment_assets as assets

    segment = _build_segment()
    segment["audio_cache_key"] = "legacy_unreproducible_key"
    segment["audio_chunk_cache_paths"] = {"legacy_unreproducible_key": "ref"}
    asset_ref = assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 legacy audio",
    )
    segment["audio_path"] = asset_ref
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    original_script_json = chapter_audio.script_json
    assert assets.repair_legacy_segment_signatures(chapter_audio) is False

    updated = json.loads(chapter_audio.script_json)[0]
    assert chapter_audio.script_json == original_script_json
    assert updated["audio_cache_key"] == "legacy_unreproducible_key"
    assert "audio_render_chunk_max_chars" not in updated
    assert updated["audio_chunk_cache_paths"] == {
        "legacy_unreproducible_key": "ref"
    }
    assert assets.segment_audio_signature_status(updated) == "unverifiable"
    assert assets.persistent_segment_audio_exists(asset_ref)


def test_repair_skips_verified_and_text_modified_segments(cleanup_test_assets):
    """自愈只处理不可复现签名：已验证与判定过期的片段保持原签名。"""
    from app.services.audiobook import chapter_segment_assets as assets

    verified = _build_segment()
    verified["audio_cache_key"] = assets.compute_segment_audio_cache_key(
        verified, render_chunk_max_chars=420
    )
    verified["audio_render_chunk_max_chars"] = 420

    stale = _build_segment()
    stale["text"] = "另一段台词，签名与音频不匹配。"
    stale["audio_cache_key"] = verified["audio_cache_key"]
    stale["audio_render_chunk_max_chars"] = 420

    refs = {}
    for index, seg in enumerate((verified, stale)):
        refs[index] = assets.save_persistent_segment_audio(
            chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
            segment_index=index,
            audio_bytes=b"ID3 audio",
        )
        seg["audio_path"] = refs[index]

    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([verified, stale], ensure_ascii=False),
    )

    assert assets.repair_legacy_segment_signatures(chapter_audio) is False
    updated = json.loads(chapter_audio.script_json)
    assert updated[0]["audio_cache_key"] == verified["audio_cache_key"]
    assert updated[1]["audio_cache_key"] == verified["audio_cache_key"]
    assert assets.segment_audio_signature_status(updated[1]) == "stale"


def test_repair_requires_persistent_audio():
    """非持久化音频引用的片段不自愈（缺失检查仍按原原因上报）。"""
    from app.services.audiobook import chapter_segment_assets as assets

    segment = _build_segment()
    segment["audio_cache_key"] = "legacy_unreproducible_key"
    segment["audio_path"] = "temp/some_expired_run/0.mp3"
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    assert assets.repair_legacy_segment_signatures(chapter_audio) is False
    assert (
        json.loads(chapter_audio.script_json)[0]["audio_cache_key"]
        == "legacy_unreproducible_key"
    )


# 管线 _assign_voices 在内存注入、不落库且不影响 TTS 音频内容的风格/档案派生键：
# 旁白风格 legacy 审计输入与停顿应用标记、非 instruct 模型的音色基线语速。
_ENGINE_INJECTED_STYLE_FIELDS = {
    "narration_style": "professional",
    "narration_style_legacy": "professional",
    "narration_style_prompt_legacy": "自定义风格提示",
    "narration_style_pause_applied": True,
    "character_base_speed": 1.0,
}


def _build_narration_segment():
    return {
        "type": "narration",
        "text": "他低下头，瞳孔骤然收缩，锁链上的符文正微微搏动。",
        "speaker": "旁白",
        "emotion": "fearful",
        "performance_notes": "语速缓慢，营造恐惧和绝望。",
        "instruct_emotion": "fearful",
        "instruct_scene": "水牢阴森环境",
        "instruct_role": "有声书旁白",
        "instruct_identity": "故事讲述者",
        "voice_params": {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "volume": 40,
            "pause_before": 0.2,
            "pause_after": 0.45,
            "tts_model": "seed-tts-2.0-expressive",
        },
    }


def test_signature_ignores_engine_injected_narration_style_fields():
    """管线内存注入的旁白风格/档案派生键不得改变片段音频签名。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_narration_segment()
    base_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    segment["voice_params"].update(_ENGINE_INJECTED_STYLE_FIELDS)
    assert (
        chapter_segment_assets.compute_segment_audio_cache_key(segment) == base_key
    )


def test_pipeline_generated_narration_signature_verifiable_after_persist(
    cleanup_test_assets,
):
    """回归线上事故：audio_from_scripts 生成时 _assign_voices 把旁白风格键注入
    内存 voice_params 参与签名，但剧本持久化不含这些键，导致全部旁白片段
    被误判 stale、整章混音报"片段音频不可用"。持久化后必须能精确复现。"""
    import copy

    from app.services.audiobook import background_jobs_remix as remix
    from app.services.audiobook import chapter_segment_assets as assets

    enriched = _build_narration_segment()
    enriched["voice_params"].update(_ENGINE_INJECTED_STYLE_FIELDS)
    gen_time_key = assets.compute_segment_audio_cache_key(
        enriched, render_chunk_max_chars=360
    )

    # 持久化剧本只保留片段级参数（不含引擎注入键）
    persisted = _build_narration_segment()
    persisted["audio_path"] = assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 pipeline audio",
    )
    persisted["audio_cache_key"] = gen_time_key
    persisted["audio_render_chunk_max_chars"] = 360

    assert assets.segment_audio_signature_status(persisted) == "current"

    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([copy.deepcopy(persisted)], ensure_ascii=False),
    )
    assert remix.collect_chapter_remix_missing_segments(chapter_audio) == []


# 音色档案（mimo 设计/克隆、stepaudio 克隆）配方键：档案创建后不可变，
# 合成时音色由 asset id 锁定，配方原文不改变片段 TTS 音频内容。
_ASSET_RECIPE_FIELDS = {
    "voice_design_prompt": "中老年男性，苍老沉稳，声线浑厚沙哑。",
    "voice_clone_data_url": "data:audio/wav;base64,QUJD",
    "voice_sample_path": "clone_samples/mimo_clone_test.wav",
}


def _build_mimo_design_segment():
    return {
        "type": "monologue",
        "text": "衍儿……记住……不要相信……干净的灵气……",
        "speaker": "纪老药",
        "emotion": "sad",
        "performance_notes": "语速极慢，声音虚弱，断断续续。",
        "voice_params": {
            "speaker": "mimo_design:mimo_design_testasset01",
            "mimo_voice_asset_id": "mimo_design_testasset01",
            "volume": 40,
            "tts_model": "mimo-v2.5-tts-voicedesign",
        },
    }


def test_signature_ignores_asset_recipe_fields():
    """音色档案配方键注入不得改变片段音频签名。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_mimo_design_segment()
    base_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    segment["voice_params"].update(_ASSET_RECIPE_FIELDS)
    assert (
        chapter_segment_assets.compute_segment_audio_cache_key(segment) == base_key
    )


def test_repair_heals_asset_recipe_injected_signature(
    cleanup_test_assets, monkeypatch
):
    """回归：历史存储签名计入过档案配方键（voice_design_prompt），持久化剧本
    不含该键；自愈必须能按 asset id 从资产库重建配方投影后迁移为当前签名。"""
    from app.services.audiobook import chapter_segment_assets as assets
    from app.services.audiobook import mimo_voice_assets

    design_prompt = _ASSET_RECIPE_FIELDS["voice_design_prompt"]

    def _fake_merge(config, *, owner_user_id=None):
        return {**config, "voice_design_prompt": design_prompt}

    monkeypatch.setattr(
        mimo_voice_assets, "merge_mimo_voice_asset_tts_params", _fake_merge
    )

    segment = _build_mimo_design_segment()
    injected = dict(segment)
    injected["voice_params"] = {**segment["voice_params"], "voice_design_prompt": design_prompt}
    # 旧算法存储键：配方键计入签名（当前规范签名已忽略该键，哈希不同）
    legacy_key = assets._compute_segment_audio_cache_key(
        injected,
        render_chunk_max_chars=360,
        synchronize_semantics=True,
        exclude_engine_style_keys=False,
    )
    current_key = assets.compute_segment_audio_cache_key(
        segment, render_chunk_max_chars=360
    )
    assert legacy_key != current_key

    segment["audio_path"] = assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 pipeline audio",
    )
    segment["audio_cache_key"] = legacy_key
    segment["audio_render_chunk_max_chars"] = 360
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    assert assets.segment_audio_signature_status(segment) == "stale"
    assert assets.repair_legacy_segment_signatures(chapter_audio, owner_user_id=1) is True

    updated = json.loads(chapter_audio.script_json)[0]
    assert updated["audio_cache_key"] == current_key
    assert assets.segment_audio_signature_status(updated) == "current"

    # 档案解析失败（越权/缺失）时不得迁移
    def _fake_merge_denied(config, *, owner_user_id=None):
        raise mimo_voice_assets.MiMoVoiceAssetError("denied")

    segment2 = _build_mimo_design_segment()
    segment2["audio_path"] = updated["audio_path"]
    segment2["audio_cache_key"] = legacy_key
    segment2["audio_render_chunk_max_chars"] = 360
    chapter_audio2 = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment2], ensure_ascii=False),
    )
    monkeypatch.setattr(
        mimo_voice_assets, "merge_mimo_voice_asset_tts_params", _fake_merge_denied
    )
    assert assets.repair_legacy_segment_signatures(chapter_audio2, owner_user_id=1) is False
    assert (
        json.loads(chapter_audio2.script_json)[0]["audio_cache_key"] == legacy_key
    )


def test_infer_chunk_limit_matches_compute_inference(monkeypatch):
    """自愈写入的分块上下文必须与 compute 推断分支使用同一策略。"""
    from app.services.audiobook import chapter_segment_assets as assets
    from app.services.audiobook.render_plan import DEFAULT_RENDER_CHUNK_MAX_CHARS

    monkeypatch.delenv("AUDIOBOOK_RENDER_CHUNK_MAX_CHARS", raising=False)

    plain = _build_segment()
    inferred = assets.infer_segment_render_chunk_max_chars(plain)
    assert inferred > 0
    assert (
        assets.compute_segment_audio_cache_key(plain)
        == assets.compute_segment_audio_cache_key(
            plain, render_chunk_max_chars=inferred
        )
    )

    # 3.1 与其余在架模型一样不再有独立小上限：推断口径统一落在默认分块上限
    qwen_segment = _build_segment()
    qwen_segment["voice_params"]["tts_model"] = "qwen-audio-3.1-tts-flash"
    assert (
        assets.infer_segment_render_chunk_max_chars(qwen_segment)
        == DEFAULT_RENDER_CHUNK_MAX_CHARS
    )
