"""Provider-neutral data models for Seed Audio scene prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .quality_policy import DEFAULT_SCENE_AUDIO_QUALITY_POLICY_HASH


SCENE_AUDIO_EVENT_KINDS = {
    "speech",
    "vocalization",
    "sfx",
    "ambient",
    "music",
    "scene",
    "transition",
}
SCENE_AUDIO_EVENT_ANCHORS = {
    "before",
    "during",
    "after",
    "throughout",
    "until_text",
}
DEFERRED_PREVIEW_REFERENCE_FIELD = "preview_cache"


@dataclass(frozen=True)
class SceneAudioEvent:
    """One ordered, provider-neutral audible event in a scene."""

    kind: str
    anchor: str
    speaker: Optional[str] = None
    exact_text: Optional[str] = None
    performance: Optional[str] = None
    acoustic: Optional[str] = None
    related_text: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in SCENE_AUDIO_EVENT_KINDS:
            raise ValueError(f"unsupported scene audio event kind: {self.kind}")
        if self.anchor not in SCENE_AUDIO_EVENT_ANCHORS:
            raise ValueError(f"unsupported scene audio event anchor: {self.anchor}")
        if self.kind == "speech" and (not self.speaker or self.exact_text is None):
            raise ValueError("speech events require speaker and exact_text")
        if self.anchor == "until_text" and not str(self.related_text or "").strip():
            raise ValueError("until_text events require related_text")


@dataclass(frozen=True)
class SceneVoiceProfile:
    """A scene-local character description with an optional provider reference."""

    name: str
    description: str
    provider_reference: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("scene voice profile name is required")
        if self.provider_reference is not None and not isinstance(self.provider_reference, dict):
            raise ValueError("provider_reference must be an object")


@dataclass(frozen=True)
class ScenePromptCompileResult:
    """Deterministic prompt output and its validation metadata."""

    prompt: str
    events: Tuple[SceneAudioEvent, ...]
    expected_texts: Tuple[str, ...]
    references: Tuple[Dict[str, Any], ...]
    reference_speakers: Tuple[str, ...]
    requires_split: bool
    split_reason: Optional[str]

    @property
    def prompt_chars(self) -> int:
        return len(self.prompt)


@dataclass(frozen=True)
class SceneRenderPlan:
    """Immutable scene plan used as the input to a renderer."""

    scene_id: str
    source_segment_indices: Tuple[int, ...]
    expected_text: str
    expected_duration_s: float
    speaker_names: Tuple[str, ...]
    references: Tuple[Dict[str, Any], ...]
    prompt: str
    prompt_hash: str
    reference_hashes: Tuple[str, ...]
    boundary_before: str
    boundary_after: str
    render_mode: str = "seed_scene"
    fallback_reason: Optional[str] = None
    expected_vocalizations: Tuple[str, ...] = ()
    quality_policy_hash: str = DEFAULT_SCENE_AUDIO_QUALITY_POLICY_HASH
