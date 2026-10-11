# -*- coding: utf-8 -*-
"""四轨声音方案测试（video_model_capability_watch O4，Phase 2 增量）。

轨道 A：剧本引擎台词长度约束（≤2 句/镜，生成端截断风险；旁白走后期不受限）
轨道 B：T3 预检口型敏感标记（dialogue×特写 → lip_sync 风险提示，不自动改景别）
轨道 C：逐镜四轨声音策略（dialogue/ambience/narration/bgm × native/post 决策）
轨道 D：合成端四轨汇总报告
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _beat(beat_id: str, dialogue: list, **kw) -> dict:
    beat = {
        "beat_id": beat_id, "family": "情绪爆发族", "type": "dialogue",
        "description": "对峙升级", "action": "看", "shot_purpose": "强调情绪",
        "dialogue": dialogue, "visual_anchor": "特写：颤抖的手", "duration_hint_s": 5.0,
    }
    beat.update(kw)
    return beat


def _doc(beats: list) -> dict:
    return {"scenes": [{"scene_id": "S1", "beats": beats}]}


# ================================================================ 轨道 A：台词长度约束
class TestDialogueLineLimit:
    def test_over_two_lines_flags_issue(self):
        from agents.scripter_pkg._schema import dialogue_line_limit_issues
        doc = _doc([_beat("S1-B1", [
            {"speaker": "林晚", "line": "你到底瞒了我什么"},
            {"speaker": "林晚", "line": "三年前那个晚上"},
            {"speaker": "陈默", "line": "别问了"},
        ])])
        issues = dialogue_line_limit_issues(doc)
        assert any("S1-B1" in i and "2" in i for i in issues)

    def test_two_lines_pass(self):
        from agents.scripter_pkg._schema import dialogue_line_limit_issues
        doc = _doc([_beat("S1-B1", [
            {"speaker": "林晚", "line": "你到底瞒了我什么"},
            {"speaker": "陈默", "line": "别问了"},
        ])])
        assert dialogue_line_limit_issues(doc) == []

    def test_narration_not_limited(self):
        from agents.scripter_pkg._schema import dialogue_line_limit_issues
        doc = _doc([_beat("S1-B1", [
            {"speaker": "旁白", "line": "夜色沉下去"},
            {"speaker": "旁白", "line": "急诊室的灯还亮着"},
            {"speaker": "旁白", "line": "没有人说话"},
        ])])
        assert dialogue_line_limit_issues(doc) == []

    def test_collect_issues_includes_line_limit(self):
        from agents.scripter_pkg._ccv import collect_issues
        doc = _doc([_beat("S1-B1", [
            {"speaker": "林晚", "line": "一"},
            {"speaker": "林晚", "line": "二"},
            {"speaker": "林晚", "line": "三"},
        ])])
        issues = collect_issues(doc, ["情绪爆发族"])
        assert any("S1-B1" in i for i in issues)


# ================================================================ 轨道 B：口型敏感标记
def _contract(shot_id: str, dialogue: list, shot_size: str = "MS") -> dict:
    return {
        "shot_id": shot_id, "scene_id": "S1", "beat_id": f"{shot_id}-B1",
        "shot_size": shot_size, "camera_movement": "locked-off 固定机位",
        "lighting": "自然窗光", "lighting_compliance": "高",
        "duration_s": 4.0, "action": "看", "dialogue": dialogue,
        "family": "情绪爆发族",
    }


class TestLipSyncPrecheck:
    def test_character_dialogue_marks_sensitive(self):
        from agents.storyboarder_pkg._precheck import precheck_contracts
        contracts = [_contract("shot_001", [{"speaker": "林晚", "line": "你到底瞒了我什么"}])]
        contracts, report = precheck_contracts(contracts)
        assert contracts[0]["lip_sync_sensitive"] is True

    def test_closeup_dialogue_flags_issue_without_resize(self):
        from agents.storyboarder_pkg._precheck import precheck_contracts
        contracts = [_contract(
            "shot_001", [{"speaker": "林晚", "line": "你到底瞒了我什么"}], shot_size="ECU",
        )]
        contracts, report = precheck_contracts(contracts)
        # 提示不改景别：特写保留（生成端音色参考路线可救），仅报 issue
        assert contracts[0]["shot_size"] == "ECU"
        assert any(i["type"] == "lip_sync_closeup" for i in report["issues"])
        assert report.get("lip_sync_sensitive") == 1

    def test_narration_not_sensitive(self):
        from agents.storyboarder_pkg._precheck import precheck_contracts
        contracts = [_contract("shot_001", [{"speaker": "旁白", "line": "夜色沉下去"}])]
        contracts, report = precheck_contracts(contracts)
        assert contracts[0]["lip_sync_sensitive"] is False
        assert report.get("lip_sync_sensitive") == 0

    def test_no_dialogue_not_sensitive(self):
        from agents.storyboarder_pkg._precheck import precheck_contracts
        contracts = [_contract("shot_001", [])]
        contracts, report = precheck_contracts(contracts)
        assert contracts[0]["lip_sync_sensitive"] is False


# ================================================================ 轨道 C：四轨声音策略
class TestSoundTrack:
    def test_engine_to_family(self):
        from agents.storyboarder_pkg._sound_track import engine_to_family
        assert engine_to_family("kling_omni") == "Kling"
        assert engine_to_family("kling-v3-omni") == "Kling"
        assert engine_to_family("wan-i2v") == "Wan"
        assert engine_to_family("seedance-2.5") == "Seedance"
        assert engine_to_family("vidu-q3") == "Vidu"
        assert engine_to_family("hailuo-h3") == "MiniMax"
        assert engine_to_family("ffmpeg_slideshow") == ""
        assert engine_to_family("") == ""

    def test_dialogue_native_voice_ref_when_supported_and_audio_available(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [
            {"speaker": "林晚", "line": "你到底瞒了我什么"},
        ])]
        report = annotate_sound_tracks(
            contracts, engine="seedance-2.5",
            voice_refs={"林晚": {"asset_id": "vra-1", "storage_uri": "oss://a.mp3"}},
        )
        st = contracts[0]["sound_track"]
        assert st["dialogue_track"] == "native_voice_ref"
        assert st["ambience_track"] == "native"
        assert st["bgm_track"] == "post"
        assert st["narration_track"] is None
        assert report["dialogue_native"] == 1

    def test_dialogue_falls_back_to_post_tts_without_audio(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [{"speaker": "林晚", "line": "为什么"}])]
        annotate_sound_tracks(contracts, engine="seedance-2.5", voice_refs=None)
        assert contracts[0]["sound_track"]["dialogue_track"] == "post_tts"

    def test_dialogue_post_tts_when_family_lacks_voice_reference(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [{"speaker": "林晚", "line": "为什么"}])]
        # Vidu 支持原生音频但无音频参考 → 对白只能后期
        annotate_sound_tracks(
            contracts, engine="vidu-q3",
            voice_refs={"林晚": {"asset_id": "vra-1", "storage_uri": "oss://a.mp3"}},
        )
        st = contracts[0]["sound_track"]
        assert st["dialogue_track"] == "post_tts"
        assert st["ambience_track"] == "native"

    def test_mixed_speakers_need_all_refs(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [
            {"speaker": "林晚", "line": "你来了"},
            {"speaker": "陈默", "line": "嗯"},
        ])]
        # 只有一个角色的参考音频 → 整镜降级后期（禁止同镜混两套人声来源）
        annotate_sound_tracks(
            contracts, engine="seedance-2.5",
            voice_refs={"林晚": {"asset_id": "vra-1", "storage_uri": "oss://a.mp3"}},
        )
        assert contracts[0]["sound_track"]["dialogue_track"] == "post_tts"

    def test_slideshow_all_post(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [{"speaker": "林晚", "line": "为什么"}])]
        annotate_sound_tracks(contracts, engine="ffmpeg_slideshow")
        st = contracts[0]["sound_track"]
        assert st["dialogue_track"] == "post_tts"
        assert st["ambience_track"] == "post_sfx"
        assert st["bgm_track"] == "post"

    def test_narration_always_post(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [{"speaker": "旁白", "line": "夜色沉下去"}])]
        annotate_sound_tracks(
            contracts, engine="seedance-2.5",
            voice_refs={"旁白": {"asset_id": "vra-1", "storage_uri": "oss://a.mp3"}},
        )
        st = contracts[0]["sound_track"]
        assert st["narration_track"] == "post_tts"
        assert st["dialogue_track"] is None

    def test_no_dialogue_only_ambience(self):
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [])]
        annotate_sound_tracks(contracts, engine="seedance-2.5")
        st = contracts[0]["sound_track"]
        assert st["dialogue_track"] is None
        assert st["narration_track"] is None
        assert st["ambience_track"] == "native"

    def test_lip_sync_flag_passthrough(self):
        from agents.storyboarder_pkg._precheck import precheck_contracts
        from agents.storyboarder_pkg._sound_track import annotate_sound_tracks
        contracts = [_contract("shot_001", [{"speaker": "林晚", "line": "为什么"}])]
        contracts, _ = precheck_contracts(contracts)
        annotate_sound_tracks(contracts, engine="seedance-2.5")
        assert contracts[0]["sound_track"]["lip_sync_sensitive"] is True


# ================================================================ 轨道 D：合成端四轨汇总
class TestSoundTrackSummary:
    def test_summary_counts_by_track(self):
        from agents.synthesis_kit import sound_track_summary
        storyboard = [
            {"shot_id": "shot_001", "sound_track": {
                "dialogue_track": "native_voice_ref", "narration_track": None,
                "ambience_track": "native", "bgm_track": "post", "lip_sync_sensitive": True}},
            {"shot_id": "shot_002", "sound_track": {
                "dialogue_track": "post_tts", "narration_track": None,
                "ambience_track": "native", "bgm_track": "post", "lip_sync_sensitive": False}},
            {"shot_id": "shot_003", "sound_track": {
                "dialogue_track": None, "narration_track": "post_tts",
                "ambience_track": "post_sfx", "bgm_track": "post", "lip_sync_sensitive": False}},
        ]
        s = sound_track_summary(storyboard)
        assert s["shots_total"] == 3
        assert s["dialogue_native_voice_ref"] == 1
        assert s["dialogue_post_tts"] == 1
        assert s["narration_post_tts"] == 1
        assert s["ambience_native"] == 2
        assert s["ambience_post_sfx"] == 1
        assert s["lip_sync_sensitive"] == 1

    def test_summary_empty_storyboard(self):
        from agents.synthesis_kit import sound_track_summary
        s = sound_track_summary([])
        assert s["shots_total"] == 0
