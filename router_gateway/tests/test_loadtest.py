from collections import Counter

import pytest

from router_gateway.adapters.base import SubmitRequest


def test_latency_summary_counts_errors_and_uses_nearest_rank_percentiles():
    from router_gateway.loadtest import summarize

    result = summarize([(202, 0.01, None), (429, 0.02, "client_rate_limit_exceeded"),
                        (0, 0.10, "ReadTimeout")], elapsed=0.2)
    assert result["requests"] == 3
    assert result["status_counts"] == {"202": 1, "429": 1, "0": 1}
    assert result["error_counts"] == {"client_rate_limit_exceeded": 1, "ReadTimeout": 1}
    assert result["requests_per_second"] == 15
    assert result["p50_ms"] == 20
    assert result["p95_ms"] == result["p99_ms"] == 100


@pytest.mark.parametrize("prompt,phase", [("success", "succeeded"), ("fail", "failed")])
def test_simulated_provider_requires_time_and_never_creates_external_requests(prompt, phase):
    from router_gateway.loadtest import SimulatedProvider

    now = [10.0]
    provider = SimulatedProvider(task_seconds=2, latency_seconds=0, clock=lambda: now[0])
    request = SubmitRequest(model="simulated", prompt=prompt, duration_seconds=5,
                            resolution="720p", aspect_ratio="16:9", idempotency_key="one")
    submitted = provider.submit(request)
    assert provider.submit(request).upstream_task_id == submitted.upstream_task_id
    assert provider.poll(submitted.upstream_task_id).phase == "queued"
    now[0] = 11.0
    assert provider.poll(submitted.upstream_task_id).phase == "running"
    now[0] = 12.0
    result = provider.poll(submitted.upstream_task_id)
    assert result.phase == phase
    if phase == "succeeded":
        assert result.content_url.startswith("https://loadtest.invalid/")
    assert provider.submissions == Counter({"one": 2})


def test_benchmark_cli_has_no_external_target_or_credentials_option():
    from router_gateway.loadtest import argument_parser

    parser = argument_parser()
    assert parser.parse_args([]).output is None
    with pytest.raises(SystemExit):
        parser.parse_args(["--database-url", "postgresql://production/db"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--base-url", "https://api.example.com"])


def test_report_validation_rejects_duplicate_dispatch_and_unfinished_workers():
    from router_gateway.loadtest import report_failures

    report = {"checks": {"active_limit_not_exceeded": True,
              "active_jobs_created": 100,
              "idempotency": {"jobs": 1, "attempts": 2, "submit_calls": 2},
              "outage_preserves_running_jobs": True, "redis_fail_closed": True},
              "phases": {"worker_4": {"status_counts": {"running": 1}, "errors": []}}}
    failures = report_failures(report)
    assert "duplicate_idempotent_dispatch" in failures
    assert "unfinished_worker_4" in failures
