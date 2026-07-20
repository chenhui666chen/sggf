"""
新功能集成测试 - 断点续传、叙事风格、字幕同步、浏览器播放器
"""
import pytest
import json
import sys
import os
import importlib.util
from pathlib import Path


@pytest.fixture
def backend_services_dir():
    return Path(__file__).parent.parent / "app" / "services" / "audiobook"


def test_narration_style_presets(backend_services_dir):
    """测试叙事风格预设加载"""
    spec = importlib.util.spec_from_file_location(
        "narration_styles", backend_services_dir / "narration_styles.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    all_styles = module.get_all_narration_styles()
    assert len(all_styles) == 5

    style_ids = [s["id"] for s in all_styles]
    assert "professional" in style_ids
    assert "dramatic" in style_ids
    assert "relaxing" in style_ids
    assert "expressive" in style_ids
    assert "custom" in style_ids

    preset = module.get_narration_style_preset("professional")
    assert preset["id"] == "professional"
    assert "speed_range" in preset
    assert "pitch_range" in preset
    assert "pause_multiplier" in preset

    params = module.apply_narration_style_to_tts_params("professional", {})
    assert params["narration_style_legacy"] == "professional"
    assert "speed" not in params
    assert "emotion" not in params
    assert "system_prompt" not in params
    assert "instructions" not in params

    custom_params = module.apply_narration_style_to_tts_params("custom", {}, "  慢速温柔  ")
    assert custom_params["narration_style_legacy"] == "custom"
    assert custom_params["narration_style_prompt_legacy"] == "慢速温柔"
    assert "system_prompt" not in custom_params
    assert "instructions" not in custom_params


def test_subtitle_generator_srt(backend_services_dir):
    """测试 SRT 字幕生成"""
    spec = importlib.util.spec_from_file_location(
        "subtitle_generator", backend_services_dir / "subtitle_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from dataclasses import dataclass

    entries = [
        module.SubtitleEntry(
            index=1,
            start_time=0.0,
            end_time=3.5,
            text="这是一段测试文本",
            speaker="角色A",
            emotion="calm",
        ),
        module.SubtitleEntry(
            index=2,
            start_time=4.0,
            end_time=7.5,
            text="这是第二段文本",
            speaker="角色B",
            emotion="happy",
        ),
    ]

    output_path = "test_subtitle.srt"
    result = module.SubtitleGenerator.generate_srt(entries, output_path)
    assert result == output_path
    assert os.path.exists(output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "00:00:00,000 --> 00:00:03,500" in content
    assert "[角色A] 这是一段测试文本" in content
    assert "[角色B] 这是第二段文本" in content

    os.remove(output_path)


def test_subtitle_generator_vtt(backend_services_dir):
    """测试 VTT 字幕生成"""
    spec = importlib.util.spec_from_file_location(
        "subtitle_generator", backend_services_dir / "subtitle_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    entries = [
        module.SubtitleEntry(
            index=1,
            start_time=0.0,
            end_time=2.5,
            text="VTT 测试文本",
            speaker="Narrator",
        ),
    ]

    output_path = "test_subtitle.vtt"
    result = module.SubtitleGenerator.generate_vtt(entries, output_path)
    assert result == output_path
    assert os.path.exists(output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "WEBVTT" in content
    assert "00:00:00.000 --> 00:00:02.500" in content
    assert "<v Narrator>VTT 测试文本</v>" in content

    os.remove(output_path)


def test_subtitle_generator_ass(backend_services_dir):
    """测试 ASS 字幕生成"""
    spec = importlib.util.spec_from_file_location(
        "subtitle_generator", backend_services_dir / "subtitle_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    entries = [
        module.SubtitleEntry(
            index=1,
            start_time=0.0,
            end_time=3.0,
            text="ASS 测试文本",
            speaker="角色A",
            emotion="happy",
        ),
    ]

    output_path = "test_subtitle.ass"
    result = module.SubtitleGenerator.generate_ass(entries, output_path)
    assert result == output_path
    assert os.path.exists(output_path)

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "Dialogue: 0,0:00:00.00,0:00:03.00,Dialogue,角色A" in content

    os.remove(output_path)


def test_subtitle_from_script_segments(backend_services_dir):
    """测试从剧本片段生成字幕"""
    spec = importlib.util.spec_from_file_location(
        "subtitle_generator", backend_services_dir / "subtitle_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    segments = [
        {
            "text": "你好，[情感:高兴]世界",
            "character": "主角",
            "type": "dialogue",
            "emotion": "happy",
        },
        {
            "text": "这是一个旁白段落",
            "type": "narration",
        },
    ]

    timings = [
        {"start": 0.0, "end": 2.5, "duration": 2.5},
        {"start": 3.0, "end": 6.0, "duration": 3.0},
    ]

    entries = module.SubtitleGenerator.from_script_segments(segments, timings)
    assert len(entries) == 2

    assert entries[0].text == "你好，世界"  # 情感标签被清理
    assert entries[0].speaker == "主角"
    assert entries[0].emotion == "happy"

    assert entries[1].text == "这是一个旁白段落"
    assert entries[1].speaker is None


def test_time_formatting(backend_services_dir):
    """测试时间格式化"""
    spec = importlib.util.spec_from_file_location(
        "subtitle_generator", backend_services_dir / "subtitle_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.SubtitleGenerator._format_srt_time(0.0) == "00:00:00,000"
    assert module.SubtitleGenerator._format_srt_time(3661.123) == "01:01:01,123"

    assert module.SubtitleGenerator._format_vtt_time(0.0) == "00:00:00.000"
    assert module.SubtitleGenerator._format_vtt_time(3661.123) == "01:01:01.123"

    assert module.SubtitleGenerator._format_ass_time(0.0) == "0:00:00.00"
    assert module.SubtitleGenerator._format_ass_time(3661.123) == "1:01:01.12"


def test_narration_style_api_schema():
    """测试叙事风格 API Schema"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.schemas.audiobook import NarrationStylePreset

    preset = NarrationStylePreset(
        id="test_style",
        name="测试风格",
        description="测试描述",
        emotion_profile={"default": "calm"},
        speed_range={"min": 0.8, "max": 1.2, "default": 1.0},
        pitch_range={"min": -2, "max": 2, "default": 0},
        pause_multiplier=1.0,
        supported_models=["qwen3-tts-instruct-flash"],
    )

    assert preset.id == "test_style"
    assert len(preset.supported_models) == 1


def test_checkpoint_api_schema():
    """测试断点续传 API Schema"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.schemas.audiobook import GenerationCheckpointResponse

    checkpoint = GenerationCheckpointResponse(
        chapter_id=1,
        total_segments=10,
        completed_segments=5,
        completed_segment_indices=[0, 1, 2, 3, 4],
        cached_audio_paths={0: "audio_0.mp3", 1: "audio_1.mp3"},
        can_resume=True,
        estimated_remaining_time=120.5,
    )

    assert checkpoint.chapter_id == 1
    assert checkpoint.completed_segments == 5
    assert checkpoint.can_resume is True
    assert len(checkpoint.cached_audio_paths) == 2


def test_subtitle_api_schema():
    """测试字幕下载 API Schema"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from app.schemas.audiobook import SubtitleDownloadResponse

    subtitle = SubtitleDownloadResponse(
        chapter_id=1,
        subtitle_format="srt",
        subtitle_url="/api/v1/audiobook/projects/1/chapters/1/subtitle",
        subtitle_content="00:00:00,000 --> 00:00:03,000\n测试文本",
    )

    assert subtitle.chapter_id == 1
    assert subtitle.subtitle_format == "srt"
    assert subtitle.subtitle_content is not None


def test_backend_imports():
    """测试后端模块可正常导入"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from app.services.audiobook.narration_styles import (
            get_narration_style_preset,
            get_all_narration_styles,
            apply_narration_style_to_tts_params,
        )
        from app.services.audiobook.subtitle_generator import (
            SubtitleGenerator,
            SubtitleEntry,
        )

        assert callable(get_narration_style_preset)
        assert callable(get_all_narration_styles)
        assert callable(apply_narration_style_to_tts_params)
        assert callable(SubtitleGenerator.generate_srt)
    except ImportError as e:
        pytest.fail(f"后端模块导入失败: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
