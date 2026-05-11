from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL, normalize_audiobook_tts_model
from .voice_manager_factory import create_voice_manager, list_auto_voice_assignment_models

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoVoiceAssignment:
    model: str
    profile: Any
    reused_voice_id: bool = False
    reused_model_voice: bool = False


class AutoVoiceAssignmentPool:
    """在多个可直接合成的 TTS 模型间为角色分配尽量不重复的声线。"""

    def __init__(
        self,
        *,
        preferred_model: str = DEFAULT_AUDIOBOOK_TTS_MODEL,
        llm_client: Any = None,
        existing_assignments: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> None:
        self.preferred_model = normalize_audiobook_tts_model(preferred_model)
        self.llm_client = llm_client
        self.model_order = list_auto_voice_assignment_models(self.preferred_model) or [self.preferred_model]
        self._managers: Dict[str, Any] = {}
        self._used_voice_ids: set[str] = set()
        self._used_model_voices: set[tuple[str, str]] = set()
        self._used_voice_ids_by_model: Dict[str, set[str]] = {}

        for item in existing_assignments or []:
            if not isinstance(item, dict):
                continue
            self.register_existing(
                voice_id=item.get("voice_id"),
                model=item.get("tts_model") or self.preferred_model,
            )

    def register_existing(self, *, voice_id: Any, model: Any = None) -> None:
        voice_id_str = str(voice_id or "").strip()
        if not voice_id_str:
            return

        normalized_model = normalize_audiobook_tts_model(model or self.preferred_model)
        self._used_voice_ids.add(voice_id_str)
        self._used_model_voices.add((normalized_model, voice_id_str))
        self._used_voice_ids_by_model.setdefault(normalized_model, set()).add(voice_id_str)

        manager = self._managers.get(normalized_model)
        if manager is not None and hasattr(manager, "used_voice_ids"):
            manager.used_voice_ids.add(voice_id_str)

    def assign(self, character_name: str, traits: Optional[Dict[str, Any]] = None) -> AutoVoiceAssignment:
        fallback: Optional[AutoVoiceAssignment] = None

        for accept_duplicate_voice_id in (False, True):
            for model in self.model_order:
                manager = self._get_manager(model)
                snapshot = self._snapshot_manager(manager)
                profile = manager.assign_voice(character_name, character_info=traits or None)
                profile.tts_model = model

                voice_id = str(profile.voice_id or "").strip()
                voice_id_reused = voice_id in self._used_voice_ids
                model_voice_reused = (model, voice_id) in self._used_model_voices

                assignment = AutoVoiceAssignment(
                    model=model,
                    profile=profile,
                    reused_voice_id=voice_id_reused,
                    reused_model_voice=model_voice_reused,
                )

                if fallback is None:
                    fallback = assignment

                if not accept_duplicate_voice_id and not voice_id_reused:
                    self._register_profile(assignment)
                    return assignment

                if accept_duplicate_voice_id and not model_voice_reused:
                    self._register_profile(assignment)
                    return assignment

                self._restore_manager(manager, snapshot)

        if fallback is None:
            manager = self._get_manager(self.preferred_model)
            profile = manager.assign_voice(character_name, character_info=traits or None)
            profile.tts_model = self.preferred_model
            fallback = AutoVoiceAssignment(model=self.preferred_model, profile=profile)
        else:
            manager = self._get_manager(fallback.model)
            profile = manager.assign_voice(character_name, character_info=traits or None)
            profile.tts_model = fallback.model
            fallback = AutoVoiceAssignment(
                model=fallback.model,
                profile=profile,
                reused_voice_id=True,
                reused_model_voice=True,
            )

        self._register_profile(fallback)
        logger.warning(
            "角色 %s 的可用声线已耗尽，仍需复用声线: model=%s voice=%s",
            character_name,
            fallback.model,
            getattr(fallback.profile, "voice_id", ""),
        )
        return fallback

    def _get_manager(self, model: str):
        normalized_model = normalize_audiobook_tts_model(model)
        manager = self._managers.get(normalized_model)
        if manager is None:
            manager = create_voice_manager(tts_model=normalized_model, llm_client=self.llm_client)
            manager.used_voice_ids.update(self._used_voice_ids_by_model.get(normalized_model, set()))
            self._managers[normalized_model] = manager
        return manager

    @staticmethod
    def _snapshot_manager(manager: Any) -> tuple[Dict[str, Any], set[str]]:
        return dict(getattr(manager, "character_voices", {}) or {}), set(getattr(manager, "used_voice_ids", set()))

    @staticmethod
    def _restore_manager(manager: Any, snapshot: tuple[Dict[str, Any], set[str]]) -> None:
        character_voices, used_voice_ids = snapshot
        if hasattr(manager, "character_voices"):
            manager.character_voices.clear()
            manager.character_voices.update(character_voices)
            manager.voice_profiles = manager.character_voices
        manager.used_voice_ids = set(used_voice_ids)

    def _register_profile(self, assignment: AutoVoiceAssignment) -> None:
        self.register_existing(
            voice_id=getattr(assignment.profile, "voice_id", ""),
            model=assignment.model,
        )
