"""Greedy semantic-unit planner for Seed Audio audiobook scenes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, List, Sequence, Tuple

from app.services.audiobook.duration_estimator import estimate_narration_duration_seconds

from .models import ScenePromptCompileResult, SceneRenderPlan, SceneVoiceProfile
from .prompt_compiler import ScenePromptCompiler
from .quality_policy import (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY,
    SceneAudioQualityPolicy,
)


class ScenePlanner:
    """Group complete script segments without splitting their spoken text."""

    def __init__(
        self,
        *,
        target_min_duration_s: float = 45.0,
        target_max_duration_s: float = 75.0,
        soft_max_duration_s: float = 90.0,
        hard_max_duration_s: float = 105.0,
        prompt_max_chars: int = 2800,
        quality_policy: SceneAudioQualityPolicy = DEFAULT_SCENE_AUDIO_QUALITY_POLICY,
    ) -> None:
        if not (0 < target_min_duration_s <= target_max_duration_s <= soft_max_duration_s <= hard_max_duration_s):
            raise ValueError("scene duration limits must be positive and ordered")
        self.target_min_duration_s = target_min_duration_s
        self.target_max_duration_s = target_max_duration_s
        self.soft_max_duration_s = soft_max_duration_s
        self.hard_max_duration_s = hard_max_duration_s
        self.prompt_max_chars = int(prompt_max_chars)
        self.quality_policy_hash = quality_policy.fingerprint()
        self.compiler = ScenePromptCompiler(max_prompt_chars=prompt_max_chars)

    def plan(
        self,
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile] = (),
        scene_description: str = "",
    ) -> Tuple[SceneRenderPlan, ...]:
        if not segments:
            return ()

        grouped_indices: List[Tuple[int, ...]] = []
        current: List[int] = []
        base_prompt_estimate = self._base_prompt_char_estimate(
            voice_profiles,
            scene_description,
        )
        current_prompt_estimate = base_prompt_estimate
        for index in range(len(segments)):
            candidate = [*current, index]
            candidate_prompt_estimate = (
                current_prompt_estimate
                + self._segment_prompt_char_estimate(segments[index])
            )
            if current and self._must_split_before_candidate(
                candidate,
                current,
                segments,
                voice_profiles=voice_profiles,
                scene_description=scene_description,
                candidate_prompt_estimate=candidate_prompt_estimate,
            ):
                grouped_indices.append(tuple(current))
                current = [index]
                current_prompt_estimate = (
                    base_prompt_estimate
                    + self._segment_prompt_char_estimate(segments[index])
                )
            else:
                current = candidate
                current_prompt_estimate = candidate_prompt_estimate
        if current:
            grouped_indices.append(tuple(current))

        plans = [
            self._build_plan(
                scene_id=f"scene_{scene_number:04d}",
                indices=indices,
                segments=segments,
                voice_profiles=voice_profiles,
                scene_description=scene_description,
            )
            for scene_number, indices in enumerate(grouped_indices, start=1)
        ]
        return tuple(plans)

    def recompile_plan(
        self,
        plan: SceneRenderPlan,
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile] = (),
        scene_description: str = "",
    ) -> SceneRenderPlan:
        """Recompile one existing scene topology after references are materialized."""
        return self._build_plan(
            scene_id=plan.scene_id,
            indices=plan.source_segment_indices,
            segments=segments,
            voice_profiles=voice_profiles,
            scene_description=scene_description,
        )

    def split_plan_once(
        self,
        plan: SceneRenderPlan,
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile] = (),
        scene_description: str = "",
    ) -> Tuple[SceneRenderPlan, ...]:
        """Split a failed multi-segment scene once at the best complete boundary."""
        indices = tuple(plan.source_segment_indices)
        if len(indices) < 2:
            return ()

        candidate_positions = tuple(range(1, len(indices)))
        semantic_positions = tuple(
            position
            for position in candidate_positions
            if self._has_semantic_boundary(
                indices[:position],
                indices[position],
                segments,
            )
        )
        positions = semantic_positions or candidate_positions
        half_duration = plan.expected_duration_s / 2
        split_position = min(
            positions,
            key=lambda position: (
                abs(
                    self._estimate_duration(indices[:position], segments)
                    - half_duration
                ),
                position,
            ),
        )
        parts = (indices[:split_position], indices[split_position:])
        return tuple(
            self._build_plan(
                scene_id=f"{plan.scene_id}_split_{part_number:02d}",
                indices=part_indices,
                segments=segments,
                voice_profiles=voice_profiles,
                scene_description=scene_description,
            )
            for part_number, part_indices in enumerate(parts, start=1)
        )

    def _must_split_before_candidate(
        self,
        candidate: Sequence[int],
        current: Sequence[int],
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile],
        scene_description: str,
        candidate_prompt_estimate: int,
    ) -> bool:
        candidate_duration = self._estimate_duration(candidate, segments)
        current_duration = self._estimate_duration(current, segments)
        if candidate_duration > self.hard_max_duration_s:
            return True
        if candidate_duration > self.soft_max_duration_s:
            return True
        if (
            candidate_duration > self.target_max_duration_s
            and current_duration >= self.target_min_duration_s
        ):
            return True
        if (
            current_duration >= self.target_min_duration_s
            and self._has_semantic_boundary(current, candidate[-1], segments)
        ):
            return True
        if self._stable_reference_count(candidate, segments, voice_profiles) > 3:
            return True
        if candidate_prompt_estimate < int(self.prompt_max_chars * 0.5):
            return False
        try:
            compiled = self._compile_indices(
                candidate,
                segments,
                voice_profiles=voice_profiles,
                scene_description=scene_description,
            )
        except ValueError as exc:
            if "at most 3 references" in str(exc):
                return True
            raise
        return compiled.requires_split

    @classmethod
    def _stable_reference_count(
        cls,
        indices: Sequence[int],
        segments: Sequence[Any],
        voice_profiles: Sequence[SceneVoiceProfile],
    ) -> int:
        references_by_name = {
            profile.name: profile.provider_reference
            for profile in voice_profiles
            if profile.provider_reference
        }
        return len(
            {
                speaker
                for index in indices
                if (speaker := cls._speaker_name(segments[index])) in references_by_name
            }
        )

    @staticmethod
    def _base_prompt_char_estimate(
        voice_profiles: Sequence[SceneVoiceProfile],
        scene_description: str,
    ) -> int:
        voice_chars = sum(
            len(str(profile.name or "")) + len(str(profile.description or ""))
            for profile in voice_profiles
        )
        return 480 + len(str(scene_description or "")) * 2 + voice_chars * 2

    @staticmethod
    def _segment_prompt_char_estimate(segment: Any) -> int:
        text_fields = (
            getattr(segment, "text", ""),
            getattr(segment, "speaker", ""),
            getattr(segment, "performance_notes", ""),
            getattr(segment, "instruct_scene", ""),
            getattr(segment, "instruct_emotion", ""),
            getattr(segment, "emotion", ""),
        )
        sound_effects = getattr(segment, "sound_effects", ()) or ()
        effect_chars = sum(len(str(effect)) for effect in sound_effects)
        music_chars = len(str(getattr(segment, "music_cue", "") or ""))
        content_chars = sum(len(str(value or "")) for value in text_fields)
        return 120 + (content_chars + effect_chars + music_chars) * 2

    @classmethod
    def _has_semantic_boundary(
        cls,
        current: Sequence[int],
        next_index: int,
        segments: Sequence[Any],
    ) -> bool:
        previous = segments[current[-1]]
        following = segments[next_index]

        previous_scene = cls._normalized_field(previous, "instruct_scene")
        following_scene = cls._normalized_field(following, "instruct_scene")
        if previous_scene and following_scene and previous_scene != following_scene:
            return True

        if cls._music_signature(previous) != cls._music_signature(following):
            return True

        following_speaker = cls._speaker_name(following)
        current_speakers = {cls._speaker_name(segments[index]) for index in current}
        return (
            following_speaker not in current_speakers
            and cls._emotion_signature(previous) != cls._emotion_signature(following)
        )

    @staticmethod
    def _normalized_field(segment: Any, field: str) -> str:
        return str(getattr(segment, field, "") or "").strip().casefold()

    @classmethod
    def _emotion_signature(cls, segment: Any) -> str:
        return (
            cls._normalized_field(segment, "instruct_emotion")
            or cls._normalized_field(segment, "emotion")
            or "neutral"
        )

    @classmethod
    def _music_signature(cls, segment: Any) -> str:
        simple = cls._normalized_field(segment, "music_cue_simple")
        if simple:
            return simple
        cue = getattr(segment, "music_cue", None)
        return str(getattr(cue, "style", "") or "").strip().casefold()

    @staticmethod
    def _speaker_name(segment: Any) -> str:
        return str(getattr(segment, "speaker", "") or "旁白").strip() or "旁白"

    def _build_plan(
        self,
        *,
        scene_id: str,
        indices: Sequence[int],
        segments: Sequence[Any],
        voice_profiles: Sequence[SceneVoiceProfile],
        scene_description: str,
    ) -> SceneRenderPlan:
        compiled = self._compile_indices(
            indices,
            segments,
            voice_profiles=voice_profiles,
            scene_description=scene_description,
        )
        duration = self._estimate_duration(indices, segments)
        fallback_reason = None
        if compiled.requires_split:
            fallback_reason = compiled.split_reason
        elif duration > self.hard_max_duration_s:
            fallback_reason = "estimated_duration_exceeds_hard_limit"
        render_mode = "legacy_stems" if fallback_reason else "seed_scene"
        speaker_names = self._speaker_names(indices, segments)
        first_segment = segments[indices[0]]
        last_segment = segments[indices[-1]]
        return SceneRenderPlan(
            scene_id=scene_id,
            source_segment_indices=tuple(indices),
            expected_text="\n".join(compiled.expected_texts),
            expected_duration_s=duration,
            speaker_names=speaker_names,
            references=compiled.references,
            prompt=compiled.prompt,
            prompt_hash=hashlib.sha256(compiled.prompt.encode("utf-8")).hexdigest(),
            reference_hashes=tuple(self._reference_hash(reference) for reference in compiled.references),
            boundary_before=self._boundary_description(first_segment, prefix="开始"),
            boundary_after=self._boundary_description(last_segment, prefix="结束"),
            render_mode=render_mode,
            fallback_reason=fallback_reason,
            expected_vocalizations=self._expected_vocalizations(compiled),
            quality_policy_hash=self.quality_policy_hash,
        )

    @staticmethod
    def _expected_vocalizations(
        compiled: ScenePromptCompileResult,
    ) -> Tuple[str, ...]:
        values: List[str] = []
        for event in compiled.events:
            if event.kind != "vocalization":
                continue
            for value in str(event.exact_text or event.performance or "").split("、"):
                normalized = value.strip()
                if normalized and normalized not in values:
                    values.append(normalized)
        return tuple(values)

    def _compile_indices(
        self,
        indices: Sequence[int],
        segments: Sequence[Any],
        *,
        voice_profiles: Sequence[SceneVoiceProfile],
        scene_description: str,
    ) -> ScenePromptCompileResult:
        selected = [segments[index] for index in indices]
        ending = self._boundary_description(selected[-1], prefix="场景结束时保持")
        return self.compiler.compile_segments(
            selected,
            voice_profiles=voice_profiles,
            scene_description=scene_description,
            ending_description=ending,
        )

    @classmethod
    def _estimate_duration(cls, indices: Sequence[int], segments: Sequence[Any]) -> float:
        duration = 0.0
        for index in indices:
            segment = segments[index]
            duration += estimate_narration_duration_seconds(
                str(getattr(segment, "text", "") or ""),
                min_duration=0.0,
            )
            duration += cls._pause_seconds(segment, "pause_before")
            duration += cls._pause_seconds(segment, "pause_after")
        return round(duration, 3)

    @staticmethod
    def _pause_seconds(segment: Any, field: str) -> float:
        value = getattr(segment, field, 0.0)
        voice_params = getattr(segment, "voice_params", None)
        if isinstance(voice_params, dict) and voice_params.get(field) is not None:
            value = voice_params[field]
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _speaker_names(indices: Sequence[int], segments: Sequence[Any]) -> Tuple[str, ...]:
        names: List[str] = []
        for index in indices:
            name = str(getattr(segments[index], "speaker", "") or "旁白").strip() or "旁白"
            if name not in names:
                names.append(name)
        return tuple(names)

    @staticmethod
    def _boundary_description(segment: Any, *, prefix: str) -> str:
        emotion = str(getattr(segment, "emotion", "") or "neutral").strip() or "neutral"
        scene = str(getattr(segment, "instruct_scene", "") or "").strip()
        details = f"{emotion}情绪"
        if scene:
            details += f"，{scene}"
        return f"{prefix}{details}"

    @staticmethod
    def _reference_hash(reference: dict[str, Any]) -> str:
        payload = json.dumps(reference, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
