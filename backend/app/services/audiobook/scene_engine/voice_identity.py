"""VoiceIdentityRegistry：只读声音身份领域视图（指导文档 §7.5）。

由项目运行时配置构造，统一屏蔽前端配置、资产权限和供应商字段差异；
不复制音频数据，只保存可审计的身份元数据。同一角色配置冲突时按
优先级解析（显式绑定 > seed_speaker > user_private > public_pool >
description），不允许系统静默覆盖用户显式选择。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

VALID_IDENTITY_SOURCES = (
    "seed_speaker",
    "user_private",
    "public_pool",
    "description",
)

# 冲突解析优先级：数值越小越优先（§7.5 身份来源选择优先级；
# 用户显式绑定直接记 0，不经此表）。
_SOURCE_PRIORITY = {
    "seed_speaker": 1,
    "user_private": 2,
    "public_pool": 3,
    "description": 4,
}


@dataclass(frozen=True)
class VoiceIdentity:
    speaker: str
    source: str
    source_id: str
    provider_reference: dict | None
    description: str
    explicitly_bound: bool
    strict_stability: bool
    asset_revision: str

    @property
    def has_legal_reference(self) -> bool:
        """是否存在可作为 Seed reference 的合法供应商字段。"""
        reference = self.provider_reference
        if not isinstance(reference, Mapping):
            return False
        return any(str(reference.get(key) or "").strip() for key in ("speaker", "audio_data", "audio_url"))


@dataclass(frozen=True)
class VoiceIdentityRegistry:
    identities: Tuple[VoiceIdentity, ...]
    version: str

    def lookup(self, speaker: str) -> VoiceIdentity | None:
        normalized = str(speaker or "").strip()
        if not normalized:
            return None
        for identity in self.identities:
            if identity.speaker == normalized:
                return identity
        return None


def build_voice_identity_registry(
    configs: Sequence[Mapping[str, Any]], *, version: str
) -> VoiceIdentityRegistry:
    """按 §7.5 优先级把角色配置解析为去重后的只读注册表。"""
    best_by_speaker: dict[str, tuple[int, VoiceIdentity]] = {}
    for config in configs:
        speaker = str(config.get("speaker") or "").strip()
        if not speaker:
            continue
        source = str(config.get("source") or "description")
        if source not in VALID_IDENTITY_SOURCES:
            source = "description"
        explicitly_bound = bool(config.get("explicitly_bound"))
        priority = 0 if explicitly_bound else _SOURCE_PRIORITY[source]
        identity = VoiceIdentity(
            speaker=speaker,
            source=source,
            source_id=str(config.get("source_id") or ""),
            provider_reference=(
                dict(config["provider_reference"])
                if isinstance(config.get("provider_reference"), Mapping)
                else None
            ),
            description=str(config.get("description") or ""),
            explicitly_bound=explicitly_bound,
            strict_stability=bool(config.get("strict_stability")),
            asset_revision=str(config.get("asset_revision") or ""),
        )
        existing = best_by_speaker.get(speaker)
        if existing is None or priority < existing[0]:
            best_by_speaker[speaker] = (priority, identity)
    identities = tuple(
        best_by_speaker[speaker][1] for speaker in sorted(best_by_speaker)
    )
    return VoiceIdentityRegistry(identities=identities, version=str(version))


__all__ = [
    "VALID_IDENTITY_SOURCES",
    "VoiceIdentity",
    "VoiceIdentityRegistry",
    "build_voice_identity_registry",
]
