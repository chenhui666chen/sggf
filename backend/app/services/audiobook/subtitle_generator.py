"""
字幕生成服务 - 生成 SRT/ASS/VTT 格式的字幕文件
"""
import html
import os
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SUBTITLE_MAX_CHARS = 84
MIN_SUBTITLE_MAX_CHARS = 24
_SENTENCE_BOUNDARIES = set("。！？!?")
_PHRASE_BOUNDARIES = set("，,、；;：:—–")
_CLOSING_PUNCTUATION = set("\"'”’）】》」』")


@dataclass
class SubtitleEntry:
    """单个字幕条目"""
    index: int
    start_time: float  # 秒
    end_time: float  # 秒
    text: str
    speaker: Optional[str] = None  # 说话者
    emotion: Optional[str] = None  # 情感


class SubtitleGenerator:
    """字幕生成器"""

    @staticmethod
    def generate_srt(entries: List[SubtitleEntry], output_path: str) -> str:
        """生成 SRT 格式字幕"""
        lines = []
        for entry in entries:
            # 序号
            lines.append(str(entry.index))
            # 时间范围 (HH:MM:SS,mmm --> HH:MM:SS,mmm)
            start_str = SubtitleGenerator._format_srt_time(entry.start_time)
            end_str = SubtitleGenerator._format_srt_time(entry.end_time)
            lines.append(f"{start_str} --> {end_str}")
            # 文本内容（可选添加说话者标识）
            text = SubtitleGenerator._plain_subtitle_text(entry.text)
            if entry.speaker:
                text = f"[{SubtitleGenerator._plain_subtitle_text(entry.speaker)}] {text}"
            lines.append(text)
            lines.append("")  # 空行分隔

        content = "\n".join(lines)

        # 写入文件
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    @staticmethod
    def generate_vtt(entries: List[SubtitleEntry], output_path: str) -> str:
        """生成 WebVTT 格式字幕"""
        lines = ["WEBVTT\n"]

        for entry in entries:
            start_str = SubtitleGenerator._format_vtt_time(entry.start_time)
            end_str = SubtitleGenerator._format_vtt_time(entry.end_time)
            lines.append(f"{start_str} --> {end_str}")

            # VTT 支持语音标签
            text = SubtitleGenerator._escape_vtt_text(entry.text)
            if entry.emotion:
                emotion_class = SubtitleGenerator._vtt_class_name(entry.emotion)
                text = f"<c.{emotion_class}>{text}</c>"
            if entry.speaker:
                speaker = SubtitleGenerator._escape_vtt_annotation(entry.speaker)
                text = f"<v {speaker}>{text}</v>"

            lines.append(text)
            lines.append("")

        content = "\n".join(lines)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    @staticmethod
    def generate_ass(entries: List[SubtitleEntry], output_path: str, title: str = "Audiobook") -> str:
        """生成 ASS 格式字幕（高级字幕，支持样式）"""
        # ASS 头部
        header = [
            "[Script Info]",
            f"Title: {title}",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "PlayResX: 1280",
            "PlayResY: 720",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Microsoft YaHei,24,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1",
            "Style: Narrator,Microsoft YaHei,22,&H00CCCCCC,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1",
            "Style: Dialogue,Microsoft YaHei,26,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,2,10,10,10,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        lines = []
        for entry in entries:
            start_str = SubtitleGenerator._format_ass_time(entry.start_time)
            end_str = SubtitleGenerator._format_ass_time(entry.end_time)

            # 根据类型选择样式
            style = "Dialogue" if entry.speaker else "Narrator"
            speaker_name = SubtitleGenerator._ass_field_text(entry.speaker or "Narrator")

            # 文本处理（ASS 支持富文本标记）
            text = SubtitleGenerator._escape_ass_text(entry.text)
            if entry.emotion:
                emotion_tags = {
                    "happy": "{\\c&H00FF00&}",  # 绿色
                    "sad": "{\\c&HFF0000&}",  # 红色
                    "angry": "{\\c&H0000FF&}",  # 蓝色
                    "fearful": "{\\c&H8080FF&}",  # 浅蓝色
                }
                emotion_color = emotion_tags.get(entry.emotion, "")
                if emotion_color:
                    text = f"{emotion_color}{text}"

            lines.append(f"Dialogue: 0,{start_str},{end_str},{style},{speaker_name},0,0,0,,{text}")

        content = "\n".join(header + lines)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    @staticmethod
    def generate_audacity_labels(entries: List[SubtitleEntry], output_path: str) -> str:
        """生成 Audacity Label Track 文本，格式为 start<TAB>end<TAB>label。"""
        lines = []
        for entry in entries:
            text = SubtitleGenerator._plain_subtitle_text(entry.text)
            if entry.speaker:
                text = f"[{SubtitleGenerator._plain_subtitle_text(entry.speaker)}] {text}"
            text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
            lines.append(f"{entry.start_time:.6f}\t{entry.end_time:.6f}\t{text}")

        content = "\n".join(lines)
        if content:
            content += "\n"

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    @staticmethod
    def from_script_segments(
        segments: List[Dict[str, Any]],
        timings: List[Dict[str, float]],
        *,
        max_chars_per_entry: Optional[int] = None,
    ) -> List[SubtitleEntry]:
        """从剧本片段和时序信息生成字幕条目

        Args:
            segments: 剧本片段列表
            timings: 时序信息列表，每个包含 {start, end, duration}
        """
        entries = []
        index = 1

        for i, segment in enumerate(segments):
            if i >= len(timings):
                break

            timing = timings[i]
            text = segment.get("text", "")

            # 清理文本中的特殊标记（如情感标签）
            text = re.sub(r'\[([^\]]+)\]', '', text).strip()

            if not text:
                continue

            entry = SubtitleEntry(
                index=index,
                start_time=timing.get("start", 0.0),
                end_time=timing.get("end", 0.0),
                text=text,
                speaker=segment.get("character"),
                emotion=segment.get("emotion"),
            )
            entries.append(entry)
            index += 1

        return SubtitleGenerator._split_and_reindex_entries(
            entries,
            max_chars=SubtitleGenerator._resolve_max_subtitle_chars(max_chars_per_entry),
        )

    @staticmethod
    def from_segment_timings(
        segments: List[Dict[str, Any]],
        timings: List[Dict[str, Any]],
        *,
        max_chars_per_entry: Optional[int] = None,
    ) -> List[SubtitleEntry]:
        """从带 index 的时间轴生成字幕条目，允许跳过未成功合成的片段。"""
        entries = []
        index = 1
        segments_by_index = {
            i: segment
            for i, segment in enumerate(segments or [])
            if isinstance(segment, dict)
        }

        for timing in timings or []:
            try:
                segment_index = int(timing.get("index"))
            except Exception:
                continue
            segment = segments_by_index.get(segment_index)
            if not segment:
                continue

            text = str(segment.get("text", "") or "")
            text = re.sub(r'\[([^\]]+)\]', '', text).strip()
            if not text:
                continue

            start_time = SubtitleGenerator._safe_time_value(timing.get("start"))
            end_time = SubtitleGenerator._safe_time_value(timing.get("end"))
            if end_time <= start_time:
                duration = SubtitleGenerator._safe_time_value(timing.get("duration"))
                end_time = start_time + max(duration, 0.001)

            entry = SubtitleEntry(
                index=index,
                start_time=start_time,
                end_time=end_time,
                text=text,
                speaker=segment.get("speaker") or segment.get("character"),
                emotion=segment.get("emotion"),
            )
            entries.append(entry)
            index += 1

        return SubtitleGenerator._split_and_reindex_entries(
            entries,
            max_chars=SubtitleGenerator._resolve_max_subtitle_chars(max_chars_per_entry),
        )

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """格式化时间为 SRT 格式 (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def _format_vtt_time(seconds: float) -> str:
        """格式化时间为 VTT 格式 (HH:MM:SS.mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        """格式化时间为 ASS 格式 (H:MM:SS.cc)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    @staticmethod
    def _safe_time_value(value: Any) -> float:
        try:
            return max(0.0, float(value))
        except Exception:
            return 0.0

    @staticmethod
    def _split_and_reindex_entries(entries: List[SubtitleEntry], *, max_chars: int) -> List[SubtitleEntry]:
        split_entries: List[SubtitleEntry] = []
        for entry in entries or []:
            split_entries.extend(SubtitleGenerator._split_entry(entry, max_chars=max_chars))

        for index, entry in enumerate(split_entries, start=1):
            entry.index = index
        return split_entries

    @staticmethod
    def _split_entry(entry: SubtitleEntry, *, max_chars: int) -> List[SubtitleEntry]:
        text = str(entry.text or "").strip()
        parts = SubtitleGenerator._split_subtitle_text(text, max_chars=max_chars)
        if len(parts) <= 1:
            entry.text = text
            return [entry]

        duration = max(0.001, float(entry.end_time or 0.0) - float(entry.start_time or 0.0))
        weights = [max(1, len(part)) for part in parts]
        total_weight = sum(weights) or len(parts)
        cursor = float(entry.start_time or 0.0)
        split_entries: List[SubtitleEntry] = []

        for part_index, part in enumerate(parts):
            if part_index == len(parts) - 1:
                end_time = max(cursor + 0.001, float(entry.end_time or cursor + 0.001))
            else:
                end_time = cursor + duration * (weights[part_index] / total_weight)
            split_entries.append(
                SubtitleEntry(
                    index=0,
                    start_time=cursor,
                    end_time=end_time,
                    text=part,
                    speaker=entry.speaker,
                    emotion=entry.emotion,
                )
            )
            cursor = end_time

        return split_entries

    @staticmethod
    def _split_subtitle_text(text: str, *, max_chars: int) -> List[str]:
        source = str(text or "").strip()
        if not source:
            return []
        if max_chars <= 0 or len(source) <= max_chars:
            return [source]

        chunks: List[str] = []
        current = ""
        for unit in SubtitleGenerator._split_text_units(source):
            if not unit:
                continue
            if len(unit) > max_chars:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(SubtitleGenerator._split_long_unit(unit, max_chars))
                continue
            if current and len(current) + len(unit) > max_chars:
                chunks.append(current.strip())
                current = unit.lstrip()
            else:
                current += unit
        if current.strip():
            chunks.append(current.strip())
        return chunks or [source]

    @staticmethod
    def _split_text_units(text: str) -> List[str]:
        units: List[str] = []
        start = 0
        index = 0
        while index < len(text):
            char = text[index]
            is_boundary = (
                char in _SENTENCE_BOUNDARIES
                or char in _PHRASE_BOUNDARIES
                or char in {"\n", "\r"}
            )
            if not is_boundary:
                index += 1
                continue

            end = index + 1
            while end < len(text) and text[end] in _CLOSING_PUNCTUATION:
                end += 1
            while end < len(text) and text[end].isspace():
                end += 1
            units.append(text[start:end])
            start = end
            index = end

        if start < len(text):
            units.append(text[start:])
        return units or [text]

    @staticmethod
    def _split_long_unit(text: str, max_chars: int) -> List[str]:
        remaining = str(text or "").strip()
        if not remaining:
            return []

        chunks: List[str] = []
        while len(remaining) > max_chars:
            cut_index = SubtitleGenerator._find_safe_cut_index(remaining, max_chars)
            chunks.append(remaining[:cut_index].strip())
            remaining = remaining[cut_index:].lstrip()
        if remaining:
            chunks.append(remaining.strip())
        return chunks

    @staticmethod
    def _find_safe_cut_index(text: str, max_chars: int) -> int:
        lower_bound = max(1, min(max_chars // 2, max_chars - 1))
        window = text[:max_chars]
        for pattern in (r"[。！？!?，,、；;：:—–]", r"\s+"):
            matches = list(re.finditer(pattern, window))
            for match in reversed(matches):
                if match.end() >= lower_bound:
                    return match.end()
        return max_chars

    @staticmethod
    def _resolve_max_subtitle_chars(value: Optional[int]) -> int:
        candidate = value
        if candidate is None:
            raw_env = os.getenv("AUDIOBOOK_SUBTITLE_MAX_CHARS")
            if raw_env is not None:
                try:
                    candidate = int(raw_env)
                except (TypeError, ValueError):
                    candidate = None
        if candidate is None:
            candidate = DEFAULT_SUBTITLE_MAX_CHARS
        try:
            resolved = int(candidate)
        except (TypeError, ValueError):
            resolved = DEFAULT_SUBTITLE_MAX_CHARS
        if resolved <= 0:
            return 0
        return max(MIN_SUBTITLE_MAX_CHARS, resolved)

    @staticmethod
    def _plain_subtitle_text(value: Any) -> str:
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _escape_vtt_text(value: Any) -> str:
        return html.escape(SubtitleGenerator._plain_subtitle_text(value), quote=False)

    @staticmethod
    def _escape_vtt_annotation(value: Any) -> str:
        annotation = SubtitleGenerator._plain_subtitle_text(value).replace("\n", " ")
        return html.escape(annotation, quote=True)

    @staticmethod
    def _vtt_class_name(value: Any) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
        return normalized or "emotion"

    @staticmethod
    def _ass_field_text(value: Any) -> str:
        return re.sub(r"[\r\n,]+", " ", str(value or "").strip()) or "Narrator"

    @staticmethod
    def _escape_ass_text(value: Any) -> str:
        text = SubtitleGenerator._plain_subtitle_text(value)
        text = text.replace("{", "｛").replace("}", "｝")
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")
        return text
