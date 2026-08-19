"""Deterministic compiler from audiobook script segments to Seed Audio prompts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.services.audiobook.voice_identity_policy import (
    sanitize_fixed_voice_performance_text,
    sanitize_fixed_voice_scene_text,
    stable_prompt_speaker,
)

from .models import (
    DEFERRED_PREVIEW_REFERENCE_FIELD,
    SceneAudioEvent,
    ScenePromptCompileResult,
    SceneVoiceProfile,
)


REFERENCE_FIELDS = (
    "speaker",
    "audio_data",
    "audio_url",
    DEFERRED_PREVIEW_REFERENCE_FIELD,
)
# §9.3 非语言人声兼容词表：显式导演事件优先，词表只服务历史
# performance_notes 兼容路径。多字词按最长匹配；单字项只在引号、
# 标点、空白或显式动作模板边界内命中。
MICRO_VOCALIZATION_TERMS = (
    "轻笑",
    "笑声",
    "冷笑",
    "苦笑",
    "哭泣",
    "抽泣",
    "哭腔",
    "哽咽",
    "呜咽",
    "吸气",
    "倒吸冷气",
    "喘息",
    "呼喝",
    "惊呼",
    "呼喊",
    "尖叫",
    "呻吟",
    "吞咽",
    "咳嗽",
    "叹气",
    "哼",
    "嗯",
    "啊",
    "诶",
    "哎",
)
_SINGLE_CHAR_TERMS = ("哼", "嗯", "啊", "诶", "哎")
_MULTI_CHAR_TERMS = tuple(term for term in MICRO_VOCALIZATION_TERMS if len(term) > 1)
_VOCAL_LEFT_BOUNDARY = set("“”\"‘’'，。！？、：；（） \t")
_VOCAL_RIGHT_BOUNDARY = set("？！。，、：；“”\"‘’' \t")

# §9.2 表演模板：按显式动作选择说白动词，不再统一套用
# “用……的方式说道”；无显式动作时用中性模板（说道）。
_SPEECH_VERB_RULES = (
    (("一字一顿", "一字一句"), "一字一顿地说道"),
    (("喊", "吼", "嚷", "喝道"), "喊道"),
    (("问",), "问道"),
    (("回应", "回答", "答道", "应道"), "回应道"),
    (("低语", "小声", "轻声", "低声"), "低语道"),
)

# Prompt 顶层场景描述的最终兜底文案（指导文档 §7.1 优先级 5）。
# 入口贯通后应只在无上下文可用时出现；与 scene_local_context 共享同一常量。
GENERIC_SCENE_FALLBACK_DESCRIPTION = "按剧情顺序生成自然、连贯的有声小说场景。"


class ScenePromptCompiler:
    """Compile reviewed script facts without asking an LLM to rewrite dialogue."""

    def __init__(self, *, max_prompt_chars: int = 2800) -> None:
        if max_prompt_chars <= 0:
            raise ValueError("max_prompt_chars must be positive")
        self.max_prompt_chars = max_prompt_chars

    def compile_segments(
        self,
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile] = (),
        scene_description: str = "",
        ending_description: str = "",
    ) -> ScenePromptCompileResult:
        events: List[SceneAudioEvent] = []
        previous_scene = ""
        previous_music = ""
        for segment in segments:
            current_scene = str(getattr(segment, "instruct_scene", "") or "").strip()
            if current_scene and current_scene.casefold() != previous_scene.casefold():
                events.append(
                    SceneAudioEvent(
                        kind="scene",
                        anchor="before",
                        acoustic=current_scene,
                    )
                )
                previous_scene = current_scene
            music_signature = self._music_cue_signature(
                getattr(segment, "music_cue", None)
            )
            include_music = bool(music_signature and music_signature != previous_music)
            events.extend(
                self._events_from_segment(
                    segment,
                    include_music=include_music,
                )
            )
            if music_signature:
                previous_music = music_signature
        return self.compile_events(
            events,
            voice_profiles=voice_profiles,
            scene_description=scene_description,
            ending_description=ending_description,
        )

    def compile_events(
        self,
        events: Iterable[SceneAudioEvent],
        *,
        voice_profiles: Sequence[SceneVoiceProfile] = (),
        scene_description: str = "",
        ending_description: str = "",
    ) -> ScenePromptCompileResult:
        ordered_events = tuple(self._sanitize_event_speaker(event) for event in events)
        expected_texts = tuple(
            str(event.exact_text)
            for event in ordered_events
            if event.kind == "speech" and event.exact_text is not None
        )
        appearing_speakers = self._appearing_speakers(ordered_events)
        profiles_by_name = {
            stable_prompt_speaker(str(profile.name).strip()): profile
            for profile in voice_profiles
        }
        references, reference_speakers = self._resolve_references(
            appearing_speakers,
            profiles_by_name,
        )
        reference_index = {
            speaker: index
            for index, speaker in enumerate(reference_speakers, start=1)
        }

        safe_scene_description, _ = sanitize_fixed_voice_scene_text(scene_description)
        lines = [
            f"场景：{safe_scene_description or GENERIC_SCENE_FALLBACK_DESCRIPTION}",
            "",
            "角色与声音：",
        ]
        if appearing_speakers:
            for speaker in appearing_speakers:
                profile = profiles_by_name.get(speaker)
                description = str(getattr(profile, "description", "") or "").strip()
                if not description:
                    description = "声音清晰自然，与角色身份和当前剧情一致"
                if speaker in reference_index:
                    lines.append(
                        f"- {speaker} 的声音参考 @音频{reference_index[speaker]}，"
                        "以参考中的声音身份为准；仅按当前剧情调整情绪、语气、音量、语速和停顿。"
                    )
                else:
                    lines.append(f"- {speaker} 是 {description}。")
        else:
            lines.append("- 本场景没有可辨识角色台词。")

        lines.extend(
            [
                "",
                "生成要求：",
                "对白和旁白始终清晰位于前景；音乐、环境与动作音效不得遮挡人声。",
                "严格朗读说话事件中文引号内的原文，不新增、删减或改写台词，不产生未声明的可辨识人声或歌词。",
                "笑声、哭泣、吸气、喘息、呻吟和吞咽按非语言人声表演，不朗读其舞台说明。",
                "",
                "按顺序生成：",
            ]
        )
        lines.extend(
            self._render_narrative_lines(ordered_events, expected_texts=expected_texts)
        )
        ending, _ = sanitize_fixed_voice_scene_text(ending_description)
        if ending:
            lines.extend(["", f"场景收尾：{ending.rstrip('。')}。"])

        prompt = "\n".join(lines).strip()
        requires_split = len(prompt) > self.max_prompt_chars
        return ScenePromptCompileResult(
            prompt=prompt,
            events=ordered_events,
            expected_texts=expected_texts,
            references=references,
            reference_speakers=reference_speakers,
            requires_split=requires_split,
            split_reason="prompt_exceeds_budget" if requires_split else None,
        )

    def _events_from_segment(
        self,
        segment: Any,
        *,
        include_music: bool = True,
    ) -> List[SceneAudioEvent]:
        events: List[SceneAudioEvent] = []
        speaker = stable_prompt_speaker(
            str(getattr(segment, "speaker", "") or "旁白").strip() or "旁白",
            segment_type=getattr(segment, "type", None),
        )
        text = str(getattr(segment, "text", "") or "")
        performance = self._segment_performance(segment)

        music_cue = getattr(segment, "music_cue", None)
        if (
            include_music
            and music_cue is not None
            and str(getattr(music_cue, "style", "") or "").strip()
        ):
            events.append(
                SceneAudioEvent(
                    kind="music",
                    anchor="before",
                    acoustic=self._describe_music_cue(music_cue),
                )
            )

        effect_events = [
            self._sound_effect_event(effect, related_text=text or None)
            for effect in list(getattr(segment, "sound_effects", None) or [])
        ]
        events.extend(
            event
            for event in effect_events
            if event.anchor in {"before", "throughout"}
        )

        vocalization = self._build_vocalization_event(speaker, performance)
        if vocalization is not None and vocalization.anchor == "before":
            events.append(vocalization)

        pause_before = self._pause_value(segment, "pause_before")
        if pause_before > 0:
            events.append(
                SceneAudioEvent(
                    kind="transition",
                    anchor="before",
                    acoustic=f"停顿约{pause_before:g}秒",
                )
            )

        if text:
            events.append(
                SceneAudioEvent(
                    kind="speech",
                    anchor="during",
                    speaker=speaker,
                    exact_text=text,
                    performance=performance or None,
                    acoustic=str(getattr(segment, "instruct_scene", "") or "").strip() or None,
                )
            )

        if vocalization is not None and vocalization.anchor != "before":
            events.append(vocalization)

        events.extend(
            event
            for event in effect_events
            if event.anchor in {"during", "until_text", "after"}
        )

        pause_after = self._pause_value(segment, "pause_after")
        if pause_after > 0:
            events.append(
                SceneAudioEvent(
                    kind="transition",
                    anchor="after",
                    acoustic=f"停顿约{pause_after:g}秒",
                )
            )
        return events

    @staticmethod
    def _appearing_speakers(events: Sequence[SceneAudioEvent]) -> Tuple[str, ...]:
        speakers: List[str] = []
        for event in events:
            speaker = str(event.speaker or "").strip()
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        return tuple(speakers)

    @staticmethod
    def _sanitize_event_speaker(event: SceneAudioEvent) -> SceneAudioEvent:
        speaker = stable_prompt_speaker(event.speaker)
        if speaker == event.speaker:
            return event
        return replace(event, speaker=speaker)

    def _resolve_references(
        self,
        appearing_speakers: Sequence[str],
        profiles_by_name: Dict[str, SceneVoiceProfile],
    ) -> Tuple[Tuple[Dict[str, Any], ...], Tuple[str, ...]]:
        references: List[Dict[str, Any]] = []
        reference_speakers: List[str] = []
        for speaker in appearing_speakers:
            profile = profiles_by_name.get(speaker)
            if profile is None or profile.provider_reference is None:
                continue
            reference = dict(profile.provider_reference)
            populated = [field for field in REFERENCE_FIELDS if str(reference.get(field) or "").strip()]
            if len(populated) != 1:
                fields = ", ".join(REFERENCE_FIELDS)
                raise ValueError(f"voice profile {speaker} must set exactly one of {fields}")
            references.append(reference)
            reference_speakers.append(speaker)
        if len(references) > 3:
            raise ValueError("a Seed Audio scene supports at most 3 references")
        return tuple(references), tuple(reference_speakers)

    @staticmethod
    def _segment_performance(segment: Any) -> str:
        notes = str(getattr(segment, "performance_notes", "") or "").strip().rstrip("。")
        if notes:
            cleaned, _ = sanitize_fixed_voice_performance_text(notes)
            if cleaned:
                return cleaned
        emotion = str(getattr(segment, "emotion", "") or "").strip()
        return f"以{emotion}情绪自然表达" if emotion and emotion != "neutral" else "自然、清晰"

    @staticmethod
    def _pause_value(segment: Any, name: str) -> float:
        value = getattr(segment, name, 0.0)
        voice_params = getattr(segment, "voice_params", None)
        if isinstance(voice_params, dict) and voice_params.get(name) is not None:
            value = voice_params[name]
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _describe_music_cue(cue: Any) -> str:
        style = str(getattr(cue, "style", "") or "").strip()
        fade_out = float(getattr(cue, "fade_out", 0.0) or 0.0)
        if any(marker in style for marker in ("音乐停止", "停止音乐", "配乐停止", "戛然而止")):
            parts = ["音乐停止"]
            if fade_out > 0 and "戛然而止" not in style:
                parts.append(f"约{fade_out:g}秒淡出")
            return "，".join(parts)
        if any(marker in style for marker in ("切换为", "转为", "变化为")):
            parts = [style]
        else:
            parts = [f"音乐以{style}进入"]
        fade_in = float(getattr(cue, "fade_in", 0.0) or 0.0)
        duration = getattr(cue, "duration", None)
        if fade_in > 0:
            parts.append(f"约{fade_in:g}秒淡入")
        if duration is not None:
            parts.append(f"持续约{float(duration):g}秒")
        if fade_out > 0:
            parts.append(f"末尾约{fade_out:g}秒淡出")
        parts.append("对白出现时降低且不遮挡人声")
        return "，".join(parts)

    @staticmethod
    def _music_cue_signature(cue: Any) -> str:
        if cue is None:
            return ""
        values = (
            getattr(cue, "style", ""),
            getattr(cue, "fade_in", 0.0),
            getattr(cue, "fade_out", 0.0),
            getattr(cue, "duration", None),
        )
        return "|".join(str(value or "").strip().casefold() for value in values)

    @staticmethod
    def _build_vocalization_event(speaker: str, performance: str) -> SceneAudioEvent | None:
        ordered_terms = ScenePromptCompiler._extract_vocalization_terms(performance)
        if not ordered_terms:
            return None
        if any(marker in performance for marker in ("在一声", "先轻", "先吸", "开口前")):
            anchor = "before"
        elif any(marker in performance for marker in ("随后", "句尾", "说完", "结束后")):
            anchor = "after"
        else:
            anchor = "during"
        return SceneAudioEvent(
            kind="vocalization",
            anchor=anchor,
            speaker=speaker,
            performance="、".join(ordered_terms),
        )

    @staticmethod
    def _extract_vocalization_terms(performance: str) -> List[str]:
        """确定性正则与最长匹配抽取，不引入 NLP（§9.3）。"""
        consumed = [False] * len(performance)
        found: List[Tuple[int, str]] = []
        for term in sorted(_MULTI_CHAR_TERMS, key=len, reverse=True):
            start = 0
            while True:
                index = performance.find(term, start)
                if index < 0:
                    break
                if not any(consumed[index : index + len(term)]):
                    found.append((index, term))
                    for position in range(index, index + len(term)):
                        consumed[position] = True
                start = index + 1
        for char in _SINGLE_CHAR_TERMS:
            for index, current in enumerate(performance):
                if current != char or consumed[index]:
                    continue
                if ScenePromptCompiler._single_char_at_boundary(performance, index):
                    found.append((index, char))
                    consumed[index] = True
        return [term for _, term in sorted(found)]

    @staticmethod
    def _single_char_at_boundary(performance: str, index: int) -> bool:
        """单字项只在引号/标点/空白/显式动作模板边界内命中。"""
        left = performance[index - 1] if index > 0 else ""
        right = performance[index + 1] if index + 1 < len(performance) else ""
        left_ok = (
            index == 0
            or left in _VOCAL_LEFT_BOUNDARY
            or performance[max(0, index - 2) : index] in ("发出", "一声")
            or left == "先"
        )
        right_ok = (
            index == len(performance) - 1
            or right in _VOCAL_RIGHT_BOUNDARY
            or performance[index + 1 : index + 4] == "了一声"
        )
        return left_ok and right_ok

    @staticmethod
    def _sound_effect_event(effect: Any, *, related_text: str | None) -> SceneAudioEvent:
        name = str(getattr(effect, "name", "") or "").strip() or "关键动作音效"
        timing = str(getattr(effect, "timing", "") or "trigger").strip().lower()
        layer = str(getattr(effect, "layer", "") or "action").strip().lower()
        continuous = timing in {"continuous", "throughout"}
        kind = "ambient" if continuous and layer in {"bottom", "atmosphere"} else "sfx"
        anchor_map = {
            "before": "before",
            "pre": "before",
            "during": "during",
            "trigger": "during",
            "after": "after",
            "post": "after",
            "continuous": "throughout",
            "throughout": "throughout",
            "until_text": "until_text",
        }
        anchor = anchor_map.get(timing, "during")
        acoustic_parts = [name]
        position = str(getattr(effect, "position_3d", "") or "").strip()
        if position:
            acoustic_parts.append(f"空间位置或移动为{position}")
        duration = getattr(effect, "duration", None)
        if duration is not None:
            acoustic_parts.append(f"持续约{float(duration):g}秒")
        delay = float(getattr(effect, "delay", 0.0) or 0.0)
        if delay > 0:
            acoustic_parts.append(f"延后约{delay:g}秒")
        fade_in = float(getattr(effect, "fade_in", 0.0) or 0.0)
        if fade_in > 0:
            acoustic_parts.append(f"开头约{fade_in:g}秒淡入")
        fade_out = float(getattr(effect, "fade_out", 0.0) or 0.0)
        if fade_out > 0:
            acoustic_parts.append(f"末尾约{fade_out:g}秒淡出")
        return SceneAudioEvent(
            kind=kind,
            anchor=anchor,
            acoustic="，".join(acoustic_parts),
            related_text=related_text,
        )

    @staticmethod
    def _is_stop_music(event: SceneAudioEvent) -> bool:
        """"音乐停止"类动态锚定：挂到所属台词行尾（官方风格“此时音乐停止”）。"""
        return event.kind == "music" and str(event.acoustic or "").strip().startswith("音乐停止")

    def _render_narrative_lines(
        self,
        events: Sequence[SceneAudioEvent],
        *,
        expected_texts: Tuple[str, ...],
    ) -> List[str]:
        """叙事流渲染（P3）：伴随事件按锚点内联进台词行，不再编号清单。

        - before 音效/停顿 → 台词行前导（“伴随着X，{说话人}说道：…”）
        - during/after 音效 → 台词行尾（“，伴随X” / “，随后是X”）
        - “音乐停止” → 台词行尾动态锚定（“；此时，音乐停止”）
        - scene/进场音乐/非语言人声/贯穿音效 → 保持独立句
        """
        lines: List[str] = []
        leads: List[str] = []
        pause_lead: str | None = None
        stop_music: List[str] = []
        speech_parts: List[str] | None = None

        def close_speech() -> None:
            nonlocal speech_parts, stop_music
            if speech_parts is None:
                return
            for description in stop_music:
                speech_parts.append(f"；此时，{description}")
            stop_music = []
            lines.append("".join(speech_parts) + "。")
            speech_parts = None

        def flush_pending() -> None:
            nonlocal leads, pause_lead, stop_music
            for action in [*leads, *([] if pause_lead is None else [pause_lead])]:
                lines.append(f"{action}。")
            leads = []
            pause_lead = None
            for description in stop_music:
                lines.append(f"此时，{description}。")
            stop_music = []

        for event in events:
            if event.kind == "speech":
                close_speech()
                prefix = ""
                if leads:
                    prefix += f"伴随着{'与'.join(leads)}，"
                    leads = []
                if pause_lead is not None:
                    prefix += f"{pause_lead}后，"
                    pause_lead = None
                speech_parts = [
                    f"{prefix}{self._render_event(event, expected_texts=expected_texts)}"
                ]
                continue
            if self._is_stop_music(event):
                stop_music.append(str(event.acoustic or "").strip().rstrip("。"))
                continue
            action = self._event_action(event)
            if event.anchor == "before":
                if event.kind in {"sfx", "ambient"}:
                    close_speech()
                    leads.append(action)
                    continue
                if event.kind == "transition":
                    close_speech()
                    pause_lead = action
                    continue
            if speech_parts is not None and event.anchor == "until_text":
                related_text = str(event.related_text or "").strip()
                if related_text and any(related_text in text for text in expected_texts):
                    speech_parts.append(
                        f"；{action}从此处持续至对应台词中的“{related_text}”说完"
                    )
                else:
                    speech_parts.append(f"；{action}从此处持续至该句说完")
                continue
            if speech_parts is not None and event.kind in {"sfx", "ambient"}:
                if event.anchor == "during":
                    speech_parts.append(f"，伴随{action}")
                    continue
                if event.anchor == "after":
                    speech_parts.append(f"，随后是{action}")
                    continue
            if speech_parts is not None and event.anchor == "after" and event.kind == "transition":
                speech_parts.append(f"，随后{action}")
                continue
            close_speech()
            flush_pending()
            lines.append(self._render_event(event, expected_texts=expected_texts))
        close_speech()
        flush_pending()
        return lines

    def _event_action(self, event: SceneAudioEvent) -> str:
        """事件的叙事描述主体（不含锚点措辞与句读）。"""
        description = str(event.acoustic or event.performance or "自然呈现").strip().rstrip("。")
        if event.kind == "scene":
            description, _ = sanitize_fixed_voice_scene_text(description)
            description = description or "自然呈现"
        speaker = stable_prompt_speaker(event.speaker)
        if event.kind == "vocalization":
            return (
                f"{speaker}发出{description}等非语言声音"
                if speaker
                else f"出现{description}等非语言人声"
            )
        if event.kind == "ambient":
            return f"环境中{description}"
        if event.kind == "scene":
            return f"环境与空间状态切换为：{description}"
        return description

    def _render_event(
        self,
        event: SceneAudioEvent,
        *,
        expected_texts: Tuple[str, ...] = (),
    ) -> str:
        if event.kind == "speech":
            performance, _ = sanitize_fixed_voice_performance_text(
                event.performance or "自然、清晰"
            )
            performance = performance or "自然、清晰"
            speaker = stable_prompt_speaker(event.speaker or "旁白") or "旁白"
            verb = self._speech_verb(speaker, performance)
            return f"{speaker}{verb}：“{event.exact_text}”（{performance}）"

        action = self._event_action(event)

        if event.anchor == "before":
            return f"先是{action}。"
        if event.anchor == "during":
            return f"台词期间伴随{action}。" if event.kind in {"sfx", "ambient"} else f"期间，{action}。"
        if event.anchor == "after":
            return f"随后，{action}。"
        if event.anchor == "throughout":
            return f"{action}，并持续到场景结束。"
        # §9.4：中性措辞；编译前验证 related_text 是目标台词子串，
        # 验证失败时降级为“持续至该句说完”。
        related_text = str(event.related_text or "").strip()
        if related_text and any(related_text in text for text in expected_texts):
            return f"{action}从此处持续至对应台词中的“{related_text}”说完。"
        return f"{action}从此处持续至该句说完。"

    @staticmethod
    def _speech_verb(speaker: str, performance: str) -> str:
        if speaker == "旁白":
            return "讲述"
        for markers, verb in _SPEECH_VERB_RULES:
            if any(marker in performance for marker in markers):
                return verb
        return "说道"
