"""Resolve project voice mappings into Seed Audio scene voice profiles."""

from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

from app.services.audiobook.tts_model_ids import (
    SEED_TTS_20_EXPRESSIVE_MODEL,
    normalize_audiobook_tts_model,
)
from .models import SceneVoiceProfile


_AUTHORIZED_AUDIO_REFERENCE_SOURCES = frozenset({"user_private", "public_pool"})


class VoiceReferenceResolver:
    """Keep provider-specific voice IDs isolated from Seed Audio references."""

    def resolve(
        self,
        speaker_names: Sequence[str],
        *,
        voice_mapping: Mapping[str, Mapping[str, Any]] | None = None,
        descriptions: Mapping[str, str] | None = None,
        default_tts_model: str = "",
    ) -> Tuple[SceneVoiceProfile, ...]:
        mapping = voice_mapping or {}
        description_mapping = descriptions or {}
        profiles = []
        seen = set()
        for raw_name in speaker_names:
            name = str(raw_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            config_value = mapping.get(name, {})
            config = config_value if isinstance(config_value, Mapping) else {}
            description = self._description_for(name, config, description_mapping)
            profiles.append(
                SceneVoiceProfile(
                    name=name,
                    description=description,
                    provider_reference=self._provider_reference(
                        config,
                        default_tts_model=default_tts_model,
                    ),
                )
            )
        return tuple(profiles)

    @staticmethod
    def _description_for(
        name: str,
        config: Mapping[str, Any],
        descriptions: Mapping[str, str],
    ) -> str:
        candidates = (
            descriptions.get(name),
            config.get("voice_description"),
            config.get("description"),
            config.get("voice_design_prompt"),
            config.get("personality"),
        )
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                return value
        return "声音清晰自然，与角色身份和当前剧情一致"

    def _provider_reference(
        self,
        config: Mapping[str, Any],
        *,
        default_tts_model: str,
    ) -> dict[str, str] | None:
        model = normalize_audiobook_tts_model(
            config.get("tts_model") or default_tts_model,
            default="",
        )
        voice_id = str(config.get("voice_id") or "").strip()
        if model == SEED_TTS_20_EXPRESSIVE_MODEL and voice_id:
            return {"speaker": voice_id}

        reference_source = str(config.get("reference_source") or "").strip().lower()
        if reference_source not in _AUTHORIZED_AUDIO_REFERENCE_SOURCES:
            if model and voice_id:
                raise ValueError(
                    "Seed Audio 不接受其他供应商官方音色试听；"
                    "请选择豆包音色、当前用户自有设计/复刻音色或公共音色池"
                )
            return None

        explicit = config.get("seed_audio_reference")
        if isinstance(explicit, Mapping):
            return self._validate_explicit_reference(explicit)

        preview_reference = self._preview_reference(config)
        if preview_reference is not None:
            return preview_reference

        audio_url = str(config.get("reference_audio_url") or "").strip()
        if audio_url:
            if not audio_url.startswith(("http://", "https://")):
                raise ValueError("reference_audio_url must be an HTTP(S) URL")
            return {"audio_url": audio_url}

        audio_data = str(config.get("reference_audio_data") or "").strip()
        if audio_data:
            return {"audio_data": self._strip_data_url(audio_data)}

        clone_data = str(config.get("voice_clone_data_url") or "").strip()
        if clone_data:
            if clone_data.startswith(("http://", "https://")):
                return {"audio_url": clone_data}
            return {"audio_data": self._strip_data_url(clone_data)}

        return None

    def _preview_reference(self, config: Mapping[str, Any]) -> dict[str, str] | None:
        preview_value = config.get("preview")
        preview = preview_value if isinstance(preview_value, Mapping) else {}
        audio_url = str(
            config.get("preview_audio_url")
            or preview.get("audio_url")
            or ""
        ).strip()
        if audio_url:
            if not audio_url.startswith(("http://", "https://")):
                raise ValueError("preview audio_url must be an HTTP(S) URL")
            return {"audio_url": audio_url}

        audio_data = str(
            config.get("preview_audio_data")
            or preview.get("audio_data")
            or preview.get("blob")
            or ""
        ).strip()
        if audio_data:
            return {"audio_data": self._strip_data_url(audio_data)}
        return None

    @staticmethod
    def _validate_explicit_reference(value: Mapping[str, Any]) -> dict[str, str]:
        fields = ("speaker", "audio_data", "audio_url")
        populated = [field for field in fields if str(value.get(field) or "").strip()]
        if len(populated) != 1:
            raise ValueError("seed_audio_reference must set exactly one of speaker, audio_data, audio_url")
        field = populated[0]
        reference_value = str(value[field]).strip()
        if field == "audio_url" and not reference_value.startswith(("http://", "https://")):
            raise ValueError("seed_audio_reference.audio_url must be an HTTP(S) URL")
        if field == "audio_data":
            reference_value = VoiceReferenceResolver._strip_data_url(reference_value)
        return {field: reference_value}

    @staticmethod
    def _strip_data_url(value: str) -> str:
        if value.startswith("data:") and ";base64," in value:
            return value.split(";base64,", 1)[1]
        return value
