from pathlib import Path

import pytest

from app.services.audiobook.subtitle_generator import SubtitleEntry, SubtitleGenerator


def test_from_segment_timings_splits_long_subtitle_on_readable_boundaries():
    text = "第一句需要单独显示。第二句也需要单独显示。第三句收束。"
    entries = SubtitleGenerator.from_segment_timings(
        [{"text": text, "speaker": "旁白", "emotion": "neutral"}],
        [{"index": 0, "start": 0.0, "end": 6.0, "duration": 6.0}],
        max_chars_per_entry=24,
    )

    assert [entry.index for entry in entries] == [1, 2]
    assert "".join(entry.text for entry in entries) == text
    assert entries[0].start_time == pytest.approx(0.0)
    assert entries[0].end_time < entries[1].end_time
    assert entries[-1].end_time == pytest.approx(6.0)
    assert all(len(entry.text) <= 24 for entry in entries)


def test_generate_vtt_uses_standard_voice_tag_and_escapes_markup(tmp_path: Path):
    output_path = tmp_path / "chapter.vtt"

    SubtitleGenerator.generate_vtt(
        [
            SubtitleEntry(
                index=1,
                start_time=0.0,
                end_time=1.5,
                text="5 < 6 & OK",
                speaker="旁白 <A>",
                emotion="very happy",
            )
        ],
        str(output_path),
    )

    content = output_path.read_text(encoding="utf-8")
    assert "<v 旁白 &lt;A&gt;><c.very-happy>5 &lt; 6 &amp; OK</c></v>" in content


def test_generate_ass_escapes_control_tags_and_sanitizes_speaker_field(tmp_path: Path):
    output_path = tmp_path / "chapter.ass"

    SubtitleGenerator.generate_ass(
        [
            SubtitleEntry(
                index=1,
                start_time=0.0,
                end_time=1.5,
                text="{bad}\n第二行",
                speaker="角色,A",
            )
        ],
        str(output_path),
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Dialogue,角色 A" in content
    assert "｛bad｝\\N第二行" in content
