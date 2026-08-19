"""ProviderRecoveryRecord：Seed 成品短期恢复状态机（指导文档 §12.2）。

下载失败但供应商可能已成功生成时，不得直接重调 Seed，先进入恢复流程。
长期 checkpoint 只保存 provider_request_id 与安全过滤后的恢复状态；
临时 URL 只存在于本短期记录（加密、TTL 受限）。幂等键双层：
内部 attempt 键 generation_input_hash + attempt_number 始终存在；
外部 provider 键 provider_id + provider_account_scope_hash +
provider_request_id 仅在 request ID 存在时建立。状态迁移走白名单 + CAS，
并发下载只有一个 worker 能推进到 downloaded。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Tuple

RECOVERY_METHODS = ("request_query", "temporary_url")

RECOVERY_STATUSES = (
    "pending",
    "downloadable",
    "downloaded",
    "expired_unverified",
    "confirmed_failed",
    "manual_review",
)

# 状态迁移白名单（§12.2）：
# pending → downloadable → downloaded；
# pending/downloadable → expired_unverified；
# expired_unverified → downloaded | confirmed_failed | manual_review。
# 禁止 downloaded/confirmed_failed → pending，
# 禁止 expired_unverified → 直接新 Seed attempt（pending）。
_ALLOWED_TRANSITIONS = {
    "pending": frozenset({"downloadable", "expired_unverified"}),
    "downloadable": frozenset({"downloaded", "expired_unverified"}),
    "expired_unverified": frozenset({"downloaded", "confirmed_failed", "manual_review"}),
    "downloaded": frozenset(),
    "confirmed_failed": frozenset(),
    "manual_review": frozenset(),
}


class RecoveryTransitionError(Exception):
    """状态迁移违反白名单或 CAS 条件（expected 与当前状态不一致）。"""


@dataclass(frozen=True)
class ProviderRecoveryRecord:
    provider_id: str
    provider_account_scope_hash: str
    provider_request_id: str
    generation_input_hash: str
    attempt_number: int
    encrypted_result_url: str
    expires_at: float
    status: str
    last_checked_at: float
    check_attempts: int
    recovery_method: str

    def __post_init__(self) -> None:
        if self.recovery_method not in RECOVERY_METHODS:
            raise ValueError(f"unknown recovery_method: {self.recovery_method}")
        if self.status not in RECOVERY_STATUSES:
            raise ValueError(f"unknown recovery status: {self.status}")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be >= 1")
        if not self.generation_input_hash:
            raise ValueError("generation_input_hash is required")
        # request_query：提交后（非 pending）必须持有 provider_request_id；
        # pending 态请求可能尚未提交，request ID 允许尚空。
        if self.recovery_method == "request_query" and not self.provider_request_id and self.status != "pending":
            raise ValueError("request_query recovery requires provider_request_id")
        # temporary_url：加密 URL 与 TTL 必填；request ID 在供应商返回时保存。
        if self.recovery_method == "temporary_url":
            if not self.encrypted_result_url:
                raise ValueError("temporary_url recovery requires encrypted_result_url")
            if self.expires_at <= 0:
                raise ValueError("temporary_url recovery requires positive expires_at")


def internal_attempt_key(record: ProviderRecoveryRecord) -> str:
    """内部 attempt 幂等键：请求提交前可能尚无 provider_request_id。"""
    return f"{record.generation_input_hash}:{record.attempt_number}"


def external_provider_key(record: ProviderRecoveryRecord) -> Optional[Tuple[str, str, str]]:
    """外部 provider 唯一键：仅在 request ID 存在时建立。"""
    if not record.provider_request_id:
        return None
    return (record.provider_id, record.provider_account_scope_hash, record.provider_request_id)


def advance_status(
    record: ProviderRecoveryRecord, *, expected: str, target: str, now: float
) -> ProviderRecoveryRecord:
    """CAS 状态推进：expected 与当前状态一致且迁移合法才返回新记录。"""
    if record.status != expected:
        raise RecoveryTransitionError(
            f"CAS mismatch: expected {expected}, current {record.status}"
        )
    if target not in _ALLOWED_TRANSITIONS.get(record.status, frozenset()):
        raise RecoveryTransitionError(
            f"illegal transition {record.status} -> {target}"
        )
    return replace(
        record,
        status=target,
        last_checked_at=now,
        check_attempts=record.check_attempts + 1,
    )


__all__ = [
    "RECOVERY_METHODS",
    "RECOVERY_STATUSES",
    "ProviderRecoveryRecord",
    "RecoveryTransitionError",
    "advance_status",
    "external_provider_key",
    "internal_attempt_key",
]
