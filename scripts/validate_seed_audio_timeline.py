#!/usr/bin/env python3
"""阶段 0 时间轴契约验证驱动脚本（multilingual 真实实测）。

用法：

    # 干跑：只打印将要发送的探针与样例，不调用付费 API
    python scripts/validate_seed_audio_timeline.py

    # 真实实测（付费）：需显式 --paid --confirm-paid
    python scripts/validate_seed_audio_timeline.py --paid --confirm-paid --repeats 3

证据落盘在 ``backend/data/timeline_validation/run_<UTC时间戳>/``：
probes.json / compliance_runs.json / eligibility.json / summary.json 与音频文件。

四个合同：
- syntax：同一广告样例按 5 种时间轴写法各生成一次；
- boundary：最小窗、超 120s、越界、重叠窗口；
- compliance：固定广告样例重复生成（默认 3 次），计算四项误差与 P50/P95/最大偏差；
- failure：颠倒窗口、非数值窗口、空事件。

注意：本脚本只调用 seed-audio-1.0-multilingual，每次调用均产生真实计费。
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (BACKEND_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from adapters.registry import registry  # noqa: E402
from app.core.env_loader import load_project_env  # noqa: E402
from app.services.audiobook.timeline_validation.ad_timeline_sample import (  # noqa: E402
    AD_TARGET_EVENTS,
    AD_TOTAL_DURATION_S,
    ad_compliance_target,
    build_boundary_probes,
    build_failure_probes,
    build_syntax_probes,
)
from app.services.audiobook.timeline_validation.baseline_scenarios import (  # noqa: E402
    BASELINE_CATALOG_VERSION,
    build_baseline_catalog,
    catalog_canonical_hash,
)
from app.services.audiobook.timeline_validation.metrics import (  # noqa: E402
    ELIGIBILITY_POLICY_VERSION,
    EligibilityThresholds,
    RunMetrics,
    aggregate_run_metrics,
    compute_run_metrics,
    decide_timeline_eligibility,
    extract_subtitle_events,
)

MODEL_ID = "seed-audio-1.0-multilingual"


def _utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _save_audio(result: Any, target: Path) -> Dict[str, Any]:
    """从 GenerationResult 落盘音频；返回落盘信息。

    逐个尝试 outputs，优先能解出非空字节的那个（供应商可能同时回
    临时 URL 与 base64，任一为空时自动回退到另一个）。
    """
    outputs = list(result.outputs or [])
    for output in outputs:
        if output.startswith("data:") and ";base64," in output:
            _, _, encoded = output.partition(";base64,")
            mime = output[5:output.index(";")] if ";" in output else "audio/mpeg"
            extension = {"audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/flac": ".flac"}.get(mime, ".bin")
            decoded = base64.b64decode(encoded)
            if decoded:
                audio_path = target.with_suffix(extension)
                audio_path.write_bytes(decoded)
                return {"audio_path": str(audio_path), "source": "base64"}
    for output in outputs:
        if output.startswith(("http://", "https://")):
            import requests

            response = requests.get(output, timeout=120)
            response.raise_for_status()
            if response.content:
                audio_path = target.with_suffix(".bin")
                audio_path.write_bytes(response.content)
                return {"audio_path": str(audio_path), "source": "url"}
    return {"audio_path": None, "source": "missing"}


def _observed_duration_ms(metadata: Dict[str, Any]) -> Optional[float]:
    for key in ("duration", "original_duration"):
        value = metadata.get(key)
        if value is not None:
            try:
                return float(value) * 1000.0
            except (TypeError, ValueError):
                continue
    return None


def _run_generation(
    adapter: Any,
    *,
    label: str,
    prompt: str,
    run_root: Path,
    dry_run: bool,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "label": label,
        "model": MODEL_ID,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt": prompt,
        "dry_run": dry_run,
    }
    if dry_run:
        record["skipped_reason"] = "dry_run"
        return record

    started = time.perf_counter()
    result = adapter.generate(prompt=prompt, model=MODEL_ID, audio_config={"format": "wav", "enable_subtitle": True})
    record["latency_s"] = round(time.perf_counter() - started, 3)
    record["success"] = bool(result.success)
    if not result.success:
        record["error"] = result.error
        record["error_code"] = result.error_code
        record["trace"] = dict(result.trace or {})
        return record

    metadata = dict(result.metadata or {})
    subtitles = metadata.get("subtitles")
    audio_info = _save_audio(result, run_root / f"{label}")
    record.update(audio_info)
    record["request_id"] = metadata.get("request_id")
    record["subtitles"] = subtitles
    record["observed_duration_ms"] = _observed_duration_ms(metadata)
    return record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", help="实际调用付费 API")
    parser.add_argument("--confirm-paid", action="store_true", help="二次确认知晓计费")
    parser.add_argument("--repeats", type=int, default=3, help="遵循精度重复次数（>=3）")
    parser.add_argument(
        "--contracts",
        default="syntax,boundary,compliance,failure",
        help="要执行的合同组，逗号分隔",
    )
    parser.add_argument("--output-root", default="", help="证据输出目录（默认 backend/data/timeline_validation）")
    args = parser.parse_args(argv)

    paid = args.paid and args.confirm_paid
    if args.paid and not args.confirm_paid:
        print("错误：--paid 必须与 --confirm-paid 同时给出（真实调用会产生计费）。")
        return 2
    if args.repeats < 3:
        print("错误：--repeats 必须 >= 3（阶段 0 合同要求）。")
        return 2

    contracts = {item.strip() for item in args.contracts.split(",") if item.strip()}
    catalog = build_baseline_catalog()
    plan: Dict[str, Any] = {
        "run_id": f"run_{_utc_stamp()}",
        "model": MODEL_ID,
        "baseline_catalog_version": BASELINE_CATALOG_VERSION,
        "baseline_catalog_sha256": catalog_canonical_hash(catalog),
        "eligibility_policy_version": ELIGIBILITY_POLICY_VERSION,
        "repeats": args.repeats,
        "contracts": sorted(contracts),
        "paid": paid,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    output_root = Path(args.output_root) if args.output_root else BACKEND_ROOT / "data" / "timeline_validation"
    run_root = output_root / plan["run_id"]
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not paid:
        print("\n[dry-run] 以下为将要发送的探针（不产生计费）。加 --paid --confirm-paid 执行真实实测。")

    adapter = None
    if paid:
        load_project_env()
        adapter = registry.get_adapter(MODEL_ID)
        if adapter is None:
            print(f"错误：适配器 {MODEL_ID} 不可用。")
            return 1

    evidence: Dict[str, Any] = {}

    records: List[Dict[str, Any]] = []
    if "syntax" in contracts:
        for probe in build_syntax_probes():
            record = _run_generation(adapter, label=probe["probe_id"], prompt=probe["prompt"], run_root=run_root, dry_run=not paid)
            record["contract"] = probe["contract"]
            record["description"] = probe["description"]
            record["expected_behavior"] = probe["expected_behavior"]
            records.append(record)
    if "boundary" in contracts:
        for probe in build_boundary_probes():
            record = _run_generation(adapter, label=probe["probe_id"], prompt=probe["prompt"], run_root=run_root, dry_run=not paid)
            record["contract"] = probe["contract"]
            record["description"] = probe["description"]
            record["expected_behavior"] = probe["expected_behavior"]
            records.append(record)
    if "failure" in contracts:
        for probe in build_failure_probes():
            record = _run_generation(adapter, label=probe["probe_id"], prompt=probe["prompt"], run_root=run_root, dry_run=not paid)
            record["contract"] = probe["contract"]
            record["description"] = probe["description"]
            record["expected_behavior"] = probe["expected_behavior"]
            records.append(record)
    if records:
        evidence["probes"] = records
        (run_root / "probes.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    compliance_records: List[Dict[str, Any]] = []
    compliance_metrics: List[RunMetrics] = []
    if "compliance" in contracts:
        target = ad_compliance_target()
        for index in range(1, args.repeats + 1):
            label = f"compliance_r{index}"
            record = _run_generation(adapter, label=label, prompt=target["prompt"], run_root=run_root, dry_run=not paid)
            record["contract"] = "compliance"
            record["sample_id"] = target["sample_id"]
            if paid and record.get("success"):
                subtitles = extract_subtitle_events({"subtitles": record.get("subtitles")})
                metrics = compute_run_metrics(
                    label,
                    success=True,
                    events=AD_TARGET_EVENTS,
                    subtitles=subtitles,
                    total_duration_s=AD_TOTAL_DURATION_S,
                    observed_duration_ms=record.get("observed_duration_ms"),
                )
            else:
                metrics = compute_run_metrics(
                    label,
                    success=False,
                    events=AD_TARGET_EVENTS,
                    subtitles=[],
                    total_duration_s=AD_TOTAL_DURATION_S,
                    error=str(record.get("error") or record.get("skipped_reason") or ""),
                )
            record["metrics"] = metrics.to_dict()
            compliance_records.append(record)
            compliance_metrics.append(metrics)
        evidence["compliance"] = compliance_records
        (run_root / "compliance_runs.json").write_text(
            json.dumps(compliance_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if paid and "compliance" in contracts:
        eligibility = decide_timeline_eligibility(compliance_metrics, EligibilityThresholds())
        evidence["eligibility"] = eligibility
        (run_root / "eligibility.json").write_text(
            json.dumps(eligibility, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n=== eligible 结论 ===")
        print(f"strict_timeline_eligible:  {eligibility['strict_timeline_eligible']}")
        for reason in eligibility["strict_reasons"]:
            print(f"  - {reason}")
        print(f"bounded_timeline_eligible: {eligibility['bounded_timeline_eligible']}")
        for reason in eligibility["bounded_reasons"]:
            print(f"  - {reason}")
        print("\n=== 聚合误差（毫秒）===")
        print(json.dumps(aggregate_run_metrics(compliance_metrics), ensure_ascii=False, indent=2))

    summary = {
        "plan": plan,
        "probe_count": len(records),
        "compliance_count": len(compliance_records),
        "evidence_dir": str(run_root),
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n证据目录：{run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
