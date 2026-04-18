"""
字幕生成服务 - 生成 SRT/ASS/VTT 格式的字幕文件
"""
import os
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path


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
            text = entry.text
            if entry.speaker:
                text = f"[{entry.speaker}] {text}"
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
            text = entry.text
            if entry.speaker:
                text = f"<v.{entry.speaker}>{text}</v>"
            if entry.emotion:
                text = f"<i.{entry.emotion}>{text}</i>"

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
            speaker_name = entry.speaker or "Narrator"

            # 文本处理（ASS 支持富文本标记）
            text = entry.text
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
    def from_script_segments(segments: List[Dict[str, Any]], timings: List[Dict[str, float]]) -> List[SubtitleEntry]:
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

        return entries

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
