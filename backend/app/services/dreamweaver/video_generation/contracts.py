from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

from pipeline.media_presets import normalize_dreamweaver_video_engine


ALLOWED_PROVIDER_MODES = frozenset({"wan_only", "auto", "kling_omni"})
ALLOWED_SELECTOR_MODES = frozenset({"off", "shadow", "active"})


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = _normalize_text(value)
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def normalize_provider_mode(value: Any, *, default: str = "wan_only") -> str:
    text = _normalize_text(value)
    if text in ALLOWED_PROVIDER_MODES:
        return text
    return default


def normalize_selector_mode(value: Any, *, default: str = "off") -> str:
    text = _normalize_text(value)
    if text in ALLOWED_SELECTOR_MODES:
        return text
    return default


def resolve_video_generation_controls(video_config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    resolved = dict(video_config or {})
    normalized_engine = normalize_dreamweaver_video_engine(resolved.get("engine"))
    if normalized_engine:
        resolved["engine"] = normalized_engine
    elif "engine" in resolved:
        resolved["engine"] = _normalize_text(resolved.get("engine"))
    resolved["provider_mode"] = normalize_provider_mode(resolved.get("provider_mode"))
    resolved["selector_mode"] = normalize_selector_mode(resolved.get("selector_mode"))
    resolved["allow_kling_omni"] = coerce_bool(resolved.get("allow_kling_omni"), default=False)
    resolved["enable_kling_video_provider"] = coerce_bool(
        resolved.get("enable_kling_video_provider"),
        default=False,
    )
    resolved["allow_subject_bridge"] = coerce_bool(resolved.get("allow_subject_bridge"), default=False)
    resolved["allow_subject_bridge_auto_sync"] = coerce_bool(
        resolved.get("allow_subject_bridge_auto_sync"),
        default=False,
    )
    return resolved


@dataclass(frozen=True)
class PreflightIssue:
    level: str
    code: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ProviderSubjectRef:
    provider: str
    subject_id: str
    role: str = ""
    source_asset_uri: str = ""
    asset_id: Optional[int] = None
    entity_type: str = ""
    entity_id: Optional[int] = None
    entity_name: str = ""
    view: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "provider": self.provider,
            "subject_id": self.subject_id,
        }
        if self.role:
            payload["role"] = self.role
        if self.source_asset_uri:
            payload["source_asset_uri"] = self.source_asset_uri
        if self.asset_id is not None:
            payload["asset_id"] = int(self.asset_id)
        if self.entity_type:
            payload["entity_type"] = self.entity_type
        if self.entity_id is not None:
            payload["entity_id"] = int(self.entity_id)
        if self.entity_name:
            payload["entity_name"] = self.entity_name
        if self.view:
            payload["view"] = self.view
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass
class DreamweaverRunPreflight:
    issues: list[PreflightIssue] = field(default_factory=list)
    resolved_video_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def add_error(self, code: str, message: str) -> None:
        self.issues.append(PreflightIssue(level="error", code=code, message=message))

    def add_warning(self, code: str, message: str) -> None:
        self.issues.append(PreflightIssue(level="warning", code=code, message=message))

    def errors(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.level == "error"]

    def warnings(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "errors": [item.to_dict() for item in self.errors()],
            "warnings": [item.to_dict() for item in self.warnings()],
            "resolved_video_config": dict(self.resolved_video_config),
        }


@dataclass(frozen=True)
class ProviderSelection:
    shot_id: str
    requested_provider_mode: str
    selector_mode: str
    recommended_provider: str
    applied_provider: str
    route: str
    reason: str
    shadowed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "shot_id": self.shot_id,
            "requested_provider_mode": self.requested_provider_mode,
            "selector_mode": self.selector_mode,
            "recommended_provider": self.recommended_provider,
            "applied_provider": self.applied_provider,
            "route": self.route,
            "reason": self.reason,
            "shadowed": self.shadowed,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


def count_truthy(values: Iterable[Any]) -> int:
    total = 0
    for value in values:
        if value:
            total += 1
    return total
