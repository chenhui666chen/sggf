"""阶段 4 ProviderRecoveryRecord 短期恢复状态机测试（指导文档 §12.2）。

覆盖验收：

- 输出 artifact 损坏/下载失败时进入恢复状态而非直接重调 Seed；
- recovery_method 判别：request_query 必填 provider_request_id；
  temporary_url 必填 encrypted_result_url 与 expires_at；
- 双层幂等键：内部 attempt 键 = generation_input_hash + attempt_number
  （请求提交前可能尚无 provider_request_id）；外部 provider 键 =
  provider_id + provider_account_scope_hash + provider_request_id
  （仅 request ID 存在时建立）；
- 状态迁移白名单与 CAS：pending → downloadable → downloaded；
  pending/downloadable → expired_unverified；
  expired_unverified → downloaded | confirmed_failed | manual_review；
  禁止 downloaded/confirmed_failed → pending，
  禁止 expired_unverified → pending（不得直接新 Seed attempt）；
- 并发 CAS 只有一个 worker 推进成功。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.provider_recovery import (  # noqa: E402
    RecoveryTransitionError,
    ProviderRecoveryRecord,
    advance_status,
    external_provider_key,
    internal_attempt_key,
)


def _record(status="pending", *, method="request_query", request_id="req-1", url="", expires_at=0.0):
    return ProviderRecoveryRecord(
        provider_id="volcengine_seed",
        provider_account_scope_hash="scope-hash",
        provider_request_id=request_id,
        generation_input_hash="input-hash",
        attempt_number=1,
        encrypted_result_url=url,
        expires_at=expires_at,
        status=status,
        last_checked_at=0.0,
        check_attempts=0,
        recovery_method=method,
    )


class TestRecoveryMethodDiscrimination:
    def test_request_query_requires_provider_request_id(self):
        # 提交后（非 pending）的 request_query 记录必填 provider_request_id；
        # pending 态允许尚空（请求提交前可能尚无 request ID）。
        with pytest.raises(ValueError):
            _record(status="downloadable", method="request_query", request_id="")

    def test_pending_request_query_allows_missing_request_id(self):
        record = _record(status="pending", method="request_query", request_id="")
        assert record.provider_request_id == ""

    def test_request_query_allows_empty_url_and_expiry(self):
        record = _record(method="request_query", url="", expires_at=0.0)
        assert record.recovery_method == "request_query"

    def test_temporary_url_requires_url_and_expiry(self):
        with pytest.raises(ValueError):
            _record(method="temporary_url", request_id="", url="", expires_at=0.0)
        with pytest.raises(ValueError):
            _record(method="temporary_url", request_id="", url="enc://x", expires_at=0.0)

    def test_temporary_url_allows_missing_request_id(self):
        record = _record(method="temporary_url", request_id="", url="enc://x", expires_at=99.0)
        assert record.provider_request_id == ""

    def test_unknown_method_rejected(self):
        with pytest.raises(ValueError):
            _record(method="carrier_pigeon")


class TestDualIdempotencyKeys:
    def test_internal_key_exists_before_provider_request_id(self):
        record = _record(request_id="")
        # 请求提交前尚无 provider_request_id，内部键仍然存在。
        assert internal_attempt_key(record) == "input-hash:1"

    def test_internal_key_distinguishes_retries_of_same_input(self):
        from dataclasses import replace

        first = _record(request_id="req-1")
        second = replace(first, attempt_number=2, provider_request_id="req-2")
        assert internal_attempt_key(first) != internal_attempt_key(second)

    def test_external_key_only_when_request_id_present(self):
        assert external_provider_key(_record(request_id="")) is None
        assert external_provider_key(_record(request_id="req-1")) == (
            "volcengine_seed",
            "scope-hash",
            "req-1",
        )


class TestStateMachine:
    def test_happy_path_pending_downloadable_downloaded(self):
        record = _record(method="temporary_url", request_id="", url="enc://x", expires_at=99.0)
        record = advance_status(record, expected="pending", target="downloadable", now=1.0)
        record = advance_status(record, expected="downloadable", target="downloaded", now=2.0)
        assert record.status == "downloaded"
        assert record.last_checked_at == 2.0

    def test_pending_and_downloadable_can_expire(self):
        record = _record()
        expired = advance_status(record, expected="pending", target="expired_unverified", now=1.0)
        assert expired.status == "expired_unverified"
        record2 = advance_status(
            advance_status(record, expected="pending", target="downloadable", now=1.0),
            expected="downloadable",
            target="expired_unverified",
            now=2.0,
        )
        assert record2.status == "expired_unverified"

    @pytest.mark.parametrize("target", ["downloaded", "confirmed_failed", "manual_review"])
    def test_expired_unverified_resolution_paths(self, target):
        record = _record(status="expired_unverified")
        resolved = advance_status(record, expected="expired_unverified", target=target, now=1.0)
        assert resolved.status == target

    @pytest.mark.parametrize(
        "current,target",
        [
            ("downloaded", "pending"),
            ("confirmed_failed", "pending"),
            ("expired_unverified", "pending"),
            ("pending", "downloaded"),
            ("downloadable", "pending"),
            ("manual_review", "pending"),
        ],
    )
    def test_illegal_transitions_rejected(self, current, target):
        record = _record(status=current, method="temporary_url", request_id="", url="enc://x", expires_at=99.0)
        with pytest.raises(RecoveryTransitionError):
            advance_status(record, expected=current, target=target, now=1.0)

    def test_cas_expected_status_mismatch_rejected(self):
        record = _record(status="pending")
        with pytest.raises(RecoveryTransitionError):
            advance_status(record, expected="downloadable", target="downloaded", now=1.0)

    def test_concurrent_cas_only_one_worker_wins(self):
        base = _record(status="downloadable")
        winner = advance_status(base, expected="downloadable", target="downloaded", now=1.0)
        # 第二个 worker 基于权威最新状态推进：已是 downloaded，CAS 拒绝，
        # 只能复用结果。
        with pytest.raises(RecoveryTransitionError):
            advance_status(winner, expected="downloadable", target="downloaded", now=1.1)
        assert winner.status == "downloaded"

    def test_confirmed_failed_allows_new_attempt_record_only(self):
        failed = _record(status="confirmed_failed")
        # confirmed_failed 不能回到 pending；新 attempt 是新记录。
        from dataclasses import replace

        new_attempt = replace(
            failed,
            attempt_number=failed.attempt_number + 1,
            provider_request_id="",
            status="pending",
        )
        assert internal_attempt_key(new_attempt) == "input-hash:2"

    def test_check_attempts_increment_on_status_checks(self):
        record = _record(status="pending")
        checked = advance_status(record, expected="pending", target="expired_unverified", now=5.0)
        assert checked.check_attempts == record.check_attempts + 1
