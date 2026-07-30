import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def test_audio_quality_reviewer_flags_audiobook_script_cadence_risks():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    long_action_text = (
        "一股无形吸力自他掌心爆发。守卫整条右臂的浊气如潮水倒灌，经脉中积蓄多年的祟意被强行抽离。"
        "一息之间，那手臂干瘪如朽木，皮肤龟裂，筋肉萎缩，连骨骼都发出脆响。"
        "守卫连惨叫都未及发出，双目翻白，轰然倒地。陆衍跪在地上干呕，眼前发黑。"
        "右手裂隙比平时扩大近一倍，暗金色漩涡在掌心疯狂转动。"
    )

    report = reviewer.review_script(
        [
            {
                "type": "narration",
                "speaker": "旁白",
                "text": long_action_text,
                "emotion": "tense",
                "pause_after": 0.0,
                "performance_notes": "",
                "sound_effects": [],
            },
            {
                "type": "narration",
                "speaker": "旁白",
                "text": "他压低声音问：“你真的要走吗？”屋里静了下来。",
                "emotion": "neutral",
                "pause_after": 0.2,
                "performance_notes": "压低声线，留一点空白。",
                "sound_effects": [],
            },
            {
                "type": "dialogue",
                "speaker": "",
                "text": "别过来！",
                "emotion": "fearful",
                "pause_after": 0.0,
                "performance_notes": "",
            },
        ],
        novel_genre="玄幻",
    )

    descriptions = "\n".join(issue.description for issue in report.issues)
    assert "单段过长" in descriptions
    assert "旁白片段中疑似混入可拆分对白" in descriptions
    assert "对话片段缺少有效说话人" in descriptions
    assert "强情绪片段缺少停顿" in descriptions
    assert "动作或环境片段缺少音效提示" in descriptions

    assert report.script_quality["long_segment_count"] == 1
    assert report.script_quality["quoted_dialogue_in_narration_count"] == 1
    assert report.script_quality["weak_pause_count"] >= 2
    assert report.script_quality["action_without_effect_count"] == 1
    assert report.script_quality["performance_notes_coverage"] < 1.0


def test_audio_quality_reviewer_uses_shared_narration_duration_estimate():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    segments = [
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "甲" * 270,
            "sound_effects": ["sfx"] * 6,
        }
    ]
    issues = []

    audio_balance = reviewer._review_audio_balance(segments, issues)
    pacing = reviewer._review_pacing(segments, issues)

    assert audio_balance["effects_per_minute"] == 6.0
    assert pacing["estimated_duration"] == "1.0分钟"
    assert pacing["average_segment_duration"] == "60.0秒"


def test_audio_quality_reviewer_reports_seed_scene_readiness():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    report = reviewer.review_script(
        [
            {
                "type": "dialogue",
                "speaker": "俘虏",
                "text": "不要啊！",
                "emotion": "fearful",
                "performance_notes": "先颤抖吸气，随后绝望尖叫",
                "instruct_scene": "空旷大殿，远处风声持续，木台阶有轻微回响",
                "sound_effects": [
                    {"name": "金属划过声", "timing": "after", "duration": 1.0}
                ],
                "music_cue": {"style": "低频铜管进入，随后定音鼓渐强"},
            }
        ],
        audio_engine_mode="seed_scene",
    )

    readiness = report.audio_balance["render_readiness"]
    assert readiness["mode"] == "seed_scene"
    assert readiness["scene_context_coverage"] == 1.0
    assert readiness["relative_timing_coverage"] == 1.0
    assert readiness["music_lifecycle_coverage"] == 1.0
    assert readiness["status"] == "ready"


def test_audio_quality_reviewer_flags_seed_scene_without_context():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    report = reviewer.review_script(
        [
            {
                "type": "narration",
                "speaker": "旁白",
                "text": "门外的脚步越来越近。",
                "sound_effects": [{"name": "脚步声"}],
            }
        ],
        audio_engine_mode="seed_scene",
    )

    readiness = report.audio_balance["render_readiness"]
    descriptions = "\n".join(issue.description for issue in report.issues)
    assert readiness["status"] == "needs_attention"
    assert readiness["scene_context_coverage"] == 0.0
    assert readiness["relative_timing_coverage"] == 0.0
    assert "Seed 场景缺少环境与空间状态" in descriptions
    assert "Seed 声音事件缺少相对时序" in descriptions


def test_audio_quality_reviewer_reports_legacy_stems_readiness():
    from app.services.audiobook.agents.audio_quality_reviewer import AudioQualityReviewer

    reviewer = AudioQualityReviewer()
    report = reviewer.review_script(
        [
            {
                "type": "narration",
                "speaker": "旁白",
                "text": "门被猛地关上。",
                "sound_effects": [
                    {
                        "name": "沉重关门声",
                        "timing": "after",
                        "volume": 0.4,
                        "fade_in": 0.0,
                        "fade_out": 0.3,
                    }
                ],
            }
        ],
        audio_engine_mode="legacy_stems",
    )

    readiness = report.audio_balance["render_readiness"]
    assert readiness["mode"] == "legacy_stems"
    assert readiness["executable_effect_coverage"] == 1.0
    assert readiness["status"] == "ready"
