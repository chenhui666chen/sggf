#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一模型接入自检工具。

本脚本只做本地静态/运行时自检，不会发起真实远程模型调用。

检查项：
1. 配置文件中是否声明了目标模型
2. 运行时 spec 是否能被加载
3. adapter 是否已注册且可实例化
4. 路由层是否至少能给出本地预览结果

示例：
    python scripts/check_model_integration.py --chain llm --model-id qwen3-max
    python scripts/check_model_integration.py --chain media --model-id wan2.6-t2i --strategy quality
    python scripts/check_model_integration.py --chain all
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_CONFIG_PATH = PROJECT_ROOT / "config" / "llm_models.yaml"
MEDIA_CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SUPPORTED_ROUTABLE_MEDIA_MODALITIES = {
    "text_to_image",
    "image_to_image",
    "text_to_video",
    "image_to_video",
    "video_to_video",
    "image_to_image_edit",
}


@dataclass
class IntegrationCheckResult:
    chain: str
    model_id: str
    config_path: str
    in_config: bool = False
    has_spec: bool = False
    has_adapter: bool = False
    adapter_type: Optional[str] = None
    route_preview: Optional[dict[str, Any]] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_passed(self) -> bool:
        return self.in_config and self.has_spec and self.has_adapter and not self.errors

    @property
    def status_label(self) -> str:
        if self.errors:
            return "ERROR"
        if not self.in_config or not self.has_spec:
            return "MISSING"
        if not self.has_adapter:
            return "SPEC_ONLY"
        if self.warnings:
            return "WARN"
        return "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "model_id": self.model_id,
            "config_path": self.config_path,
            "in_config": self.in_config,
            "has_spec": self.has_spec,
            "has_adapter": self.has_adapter,
            "adapter_type": self.adapter_type,
            "route_preview": self.route_preview,
            "warnings": self.warnings,
            "errors": self.errors,
            "status": self.status_label,
            "passed": self.is_passed,
        }


def configure_output_encoding() -> None:
    if sys.platform != "win32":
        return
    if not hasattr(sys.stdout, "buffer") or not hasattr(sys.stderr, "buffer"):
        return

    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_llm_model_ids(path: Path = LLM_CONFIG_PATH) -> list[str]:
    data = load_yaml(path)
    model_ids: list[str] = []
    for model_data in data.get("llm_models", []) or []:
        model_id = str(model_data.get("id", "")).strip()
        if model_id:
            model_ids.append(model_id)
    return model_ids


def load_media_model_ids(path: Path = MEDIA_CONFIG_PATH) -> list[str]:
    data = load_yaml(path)
    model_ids: list[str] = []
    for model_data in data.get("models", []) or []:
        model_id = str(model_data.get("id", "")).strip()
        if model_id:
            model_ids.append(model_id)
    return model_ids


def resolve_requested_chains(
    chain: str,
    model_id: Optional[str],
    llm_model_ids: list[str],
    media_model_ids: list[str],
) -> list[str]:
    if chain != "all":
        return [chain]

    if not model_id:
        return ["llm", "media"]

    resolved: list[str] = []
    if model_id in llm_model_ids:
        resolved.append("llm")
    if model_id in media_model_ids:
        resolved.append("media")

    if not resolved:
        raise ValueError(f"模型 {model_id} 不存在于 llm_models.yaml 或 models.yaml")

    return resolved


def select_model_ids(model_id: Optional[str], configured_model_ids: list[str]) -> list[str]:
    if model_id:
        return [model_id]
    return configured_model_ids


def infer_llm_task_type(spec: Any, preferred_task_type: Optional[str] = None) -> Optional[str]:
    if preferred_task_type:
        return preferred_task_type
    routing = getattr(spec, "routing", None)
    task_types = list(getattr(routing, "task_types", []) or [])
    if not task_types:
        return None
    return str(task_types[0])


def choose_media_probe_dimensions(spec: Any, modality: str) -> tuple[int, int]:
    constraints = getattr(spec, "constraints", None)
    ratios = list(getattr(constraints, "ratios", []) or [])
    preferred_ratio = ratios[0] if ratios else ("16:9" if "video" in modality else "1:1")

    ratio_dimensions = {
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "21:9": (1536, 658),
    }
    width, height = ratio_dimensions.get(preferred_ratio, (1024, 1024))

    min_width = int(getattr(constraints, "min_width", 256) or 256)
    max_width = int(getattr(constraints, "max_width", 4096) or 4096)
    min_height = int(getattr(constraints, "min_height", 256) or 256)
    max_height = int(getattr(constraints, "max_height", 4096) or 4096)

    width = max(min_width, min(width, max_width))
    height = max(min_height, min(height, max_height))
    return width, height


def choose_media_probe_duration(spec: Any, modality: str) -> Optional[float]:
    if "video" not in modality:
        return None

    constraints = getattr(spec, "constraints", None)
    supported = list(getattr(constraints, "duration", []) or [])
    if supported:
        try:
            return float(supported[0])
        except (TypeError, ValueError):
            pass
    return 5.0


def build_media_probe_task(spec: Any):
    from schemas.task_spec import TaskSpecBuilder

    modalities = list(getattr(spec, "modality", []) or [])
    modality = next((item for item in modalities if item in SUPPORTED_ROUTABLE_MEDIA_MODALITIES), None)
    if modality is None:
        return None, None

    width, height = choose_media_probe_dimensions(spec, modality)
    duration = choose_media_probe_duration(spec, modality)

    builder = (
        TaskSpecBuilder()
        .with_task_id(f"integration-check-{getattr(spec, 'id', 'media')}")
        .with_modality(modality)
        .with_prompt("模型接入自检样例：武侠场景，主体清晰，构图稳定")
        .with_dimensions(width, height)
    )
    if duration is not None:
        builder.with_duration(duration)

    return builder.build(), modality


def preview_media_routing(
    model_id: str,
    spec: Any,
    *,
    smart_router: Any,
    strategy: str,
) -> dict[str, Any]:
    task, modality = build_media_probe_task(spec)
    if task is None or modality is None:
        return {
            "preview_available": False,
            "reason": "当前 modality 不走 SmartRouter dry-run",
            "task_modality": None,
            "strategy": strategy,
        }

    routing_result = smart_router.route_with_fallback_by_strategy(
        task,
        strategy,
        max_fallbacks=3,
    )
    candidate_models = [routing_result.selected_model.id] + [model.id for model in routing_result.fallback_models]
    return {
        "preview_available": True,
        "task_modality": modality,
        "strategy": strategy,
        "selected_model": routing_result.selected_model.id,
        "fallback_models": [model.id for model in routing_result.fallback_models],
        "candidate_models": candidate_models,
        "target_in_candidates": model_id in candidate_models,
        "score": routing_result.score,
    }


def collect_llm_checks(
    model_ids: list[str],
    *,
    configured_model_ids: list[str],
    registry: Any,
    hub: Any,
    config_path: Path,
    task_type: Optional[str] = None,
    strategy: Optional[str] = None,
) -> list[IntegrationCheckResult]:
    results: list[IntegrationCheckResult] = []

    for model_id in model_ids:
        result = IntegrationCheckResult(
            chain="llm",
            model_id=model_id,
            config_path=str(config_path.relative_to(PROJECT_ROOT)),
            in_config=model_id in configured_model_ids,
        )
        if not result.in_config:
            result.errors.append("配置文件中不存在该 model_id")

        spec = registry.get_spec(model_id)
        result.has_spec = spec is not None
        if not result.has_spec:
            result.errors.append("运行时未加载到 spec")

        adapter = None
        if spec is not None:
            try:
                adapter = registry.get_adapter(model_id)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"adapter 实例化失败: {exc}")

        result.has_adapter = adapter is not None
        result.adapter_type = type(adapter).__name__ if adapter else None
        if result.has_spec and not result.has_adapter and not any("adapter 实例化失败" in item for item in result.errors):
            result.errors.append("运行时未注册 adapter")

        if spec is not None:
            resolved_task_type = infer_llm_task_type(spec, task_type)
            try:
                explicit_preview = hub.resolve_model_request(
                    task_type=resolved_task_type,
                    model=model_id,
                    strategy=strategy,
                )
                task_router_preview = None
                if resolved_task_type:
                    task_router_preview = hub.resolve_model_request(
                        task_type=resolved_task_type,
                        strategy=strategy,
                    )

                result.route_preview = {
                    "task_type": resolved_task_type,
                    "strategy": strategy or "auto",
                    "explicit_request": explicit_preview,
                    "task_router": task_router_preview,
                    "task_hits_target": (
                        task_router_preview is not None
                        and task_router_preview.get("resolved_model_id") == model_id
                    ),
                }

                if explicit_preview.get("resolved_model_id") != model_id:
                    result.warnings.append(
                        f"显式请求当前会被改写到 {explicit_preview.get('resolved_model_id')}"
                    )
                if task_router_preview and task_router_preview.get("resolved_model_id") != model_id:
                    result.warnings.append(
                        f"按 task_type={resolved_task_type} 的自动路由不会优先命中该模型"
                    )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"路由预览失败: {exc}")

        results.append(result)

    return results


def collect_media_checks(
    model_ids: list[str],
    *,
    configured_model_ids: list[str],
    registry: Any,
    smart_router: Any,
    config_path: Path,
    strategy: str = "balanced",
) -> list[IntegrationCheckResult]:
    results: list[IntegrationCheckResult] = []

    for model_id in model_ids:
        result = IntegrationCheckResult(
            chain="media",
            model_id=model_id,
            config_path=str(config_path.relative_to(PROJECT_ROOT)),
            in_config=model_id in configured_model_ids,
        )
        if not result.in_config:
            result.errors.append("配置文件中不存在该 model_id")

        spec = registry.get_spec(model_id)
        result.has_spec = spec is not None
        if not result.has_spec:
            result.errors.append("运行时未加载到 spec")

        adapter = None
        if spec is not None:
            try:
                adapter = registry.get_adapter(model_id)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"adapter 实例化失败: {exc}")

        result.has_adapter = adapter is not None
        result.adapter_type = type(adapter).__name__ if adapter else None
        if result.has_spec and not result.has_adapter and not any("adapter 实例化失败" in item for item in result.errors):
            result.errors.append("运行时未注册 adapter")

        if spec is not None:
            try:
                preview = preview_media_routing(
                    model_id,
                    spec,
                    smart_router=smart_router,
                    strategy=strategy,
                )
                result.route_preview = preview
                if not preview.get("preview_available"):
                    result.warnings.append(str(preview.get("reason") or "当前模型不支持本地 dry-run"))
                elif not preview.get("target_in_candidates"):
                    result.warnings.append("示例 dry-run 候选中未包含该模型")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"路由预览失败: {exc}")

        results.append(result)

    return results


def format_route_preview(result: IntegrationCheckResult) -> str:
    preview = result.route_preview or {}
    if result.chain == "llm":
        task_type = preview.get("task_type") or "-"
        explicit = (preview.get("explicit_request") or {}).get("resolved_model_id") or "-"
        task_router = (preview.get("task_router") or {}).get("resolved_model_id") or "-"
        return f"task_type={task_type} explicit={explicit} task_router={task_router}"

    if not preview:
        return "-"
    if not preview.get("preview_available"):
        return f"preview_unavailable: {preview.get('reason') or '-'}"

    candidates = ",".join(preview.get("candidate_models", []) or [])
    return (
        f"modality={preview.get('task_modality') or '-'} "
        f"selected={preview.get('selected_model') or '-'} "
        f"candidates={candidates or '-'}"
    )


def print_results(results: list[IntegrationCheckResult]) -> None:
    print("=" * 88)
    print("模型接入自检结果")
    print("=" * 88)

    for result in results:
        adapter_display = result.adapter_type or "-"
        print(
            f"[{result.status_label}] chain={result.chain} model={result.model_id} "
            f"config={result.config_path}"
        )
        print(
            f"  spec={'yes' if result.has_spec else 'no'} "
            f"adapter={'yes' if result.has_adapter else 'no'} "
            f"adapter_type={adapter_display}"
        )
        print(f"  route={format_route_preview(result)}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        for error in result.errors:
            print(f"  error: {error}")
        print()

    passed = sum(1 for item in results if item.is_passed)
    warned = sum(1 for item in results if item.status_label == "WARN")
    failed = sum(1 for item in results if not item.is_passed)

    print("-" * 88)
    print(f"总数: {len(results)} | 通过: {passed} | 警告: {warned} | 未通过: {failed}")
    print("-" * 88)


def run_checks(
    *,
    chain: str,
    model_id: Optional[str],
    task_type: Optional[str],
    strategy: str,
) -> list[IntegrationCheckResult]:
    llm_model_ids = load_llm_model_ids()
    media_model_ids = load_media_model_ids()
    chains = resolve_requested_chains(chain, model_id, llm_model_ids, media_model_ids)

    all_results: list[IntegrationCheckResult] = []

    if "llm" in chains:
        from core.model_hub import model_hub

        model_hub.initialize(str(LLM_CONFIG_PATH))
        llm_results = collect_llm_checks(
            select_model_ids(model_id, llm_model_ids),
            configured_model_ids=llm_model_ids,
            registry=model_hub.registry,
            hub=model_hub,
            config_path=LLM_CONFIG_PATH,
            task_type=task_type,
            strategy=strategy,
        )
        all_results.extend(llm_results)

    if "media" in chains:
        from adapters.registry import registry
        from core.router import router as smart_router

        media_results = collect_media_checks(
            select_model_ids(model_id, media_model_ids),
            configured_model_ids=media_model_ids,
            registry=registry,
            smart_router=smart_router,
            config_path=MEDIA_CONFIG_PATH,
            strategy=strategy,
        )
        all_results.extend(media_results)

    return all_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一模型接入自检工具")
    parser.add_argument(
        "--chain",
        choices=["all", "llm", "media"],
        default="all",
        help="检查链路：llm、media 或 all",
    )
    parser.add_argument(
        "--model-id",
        help="只检查指定模型；当 chain=all 时会自动判断属于哪条链",
    )
    parser.add_argument(
        "--task-type",
        help="LLM 路由预览使用的 task_type；不传则自动取模型配置中的第一个 task_type",
    )
    parser.add_argument(
        "--strategy",
        default="balanced",
        help="路由策略；llm 会映射到 auto/quality/cost/speed，media 使用 quality/cost/speed/balanced",
    )
    return parser


def main() -> int:
    configure_output_encoding()
    args = build_parser().parse_args()

    try:
        results = run_checks(
            chain=args.chain,
            model_id=args.model_id,
            task_type=args.task_type,
            strategy=args.strategy,
        )
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"自检执行失败: {exc}", file=sys.stderr)
        return 1

    print_results(results)
    return 0 if all(item.is_passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
