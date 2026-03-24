# -*- coding: utf-8 -*-
"""
统一模型调度中心 (ModelHub) - 单一入口

提供统一的模型调用接口，支持：
- 自动模型选择
- 用户指定模型
- 熔断降级
- 重试机制
- 成本追踪
"""

from __future__ import annotations

import os
import time
import logging
import asyncio
from copy import deepcopy
from typing import Dict, List, Optional, Any, Callable, Union, TYPE_CHECKING
from pathlib import Path

from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id, normalize_task_type

if TYPE_CHECKING:
    from schemas.unified_model_spec import (
        UnifiedModelSpec, LLMTaskSpec, LLMResult, DispatchStrategy
    )

logger = logging.getLogger(__name__)


class ModelHub:
    """
    统一模型调度中心

    单例模式，提供统一的模型调用入口
    """

    _instance: Optional["ModelHub"] = None

    def __new__(cls) -> "ModelHub":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import DispatchStrategy

        self.registry = UnifiedModelRegistry()
        self.default_strategy = DispatchStrategy.AUTO
        self._initialized_adapters = False

    @classmethod
    def get_instance(cls) -> "ModelHub":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, config_path: Optional[str] = None) -> None:
        """
        初始化 ModelHub

        Args:
            config_path: YAML 配置文件路径
        """
        if config_path:
            self.registry.load_from_yaml(config_path)
        else:
            default_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"
            if default_path.exists():
                self.registry.load_from_yaml(str(default_path))

        self._ensure_adapters_loaded()
        self._initialized_adapters = True

        logger.info(f"✅ ModelHub 初始化完成，已注册 {len(self.registry.get_all_specs())} 个模型")

    def _ensure_adapters_loaded(self) -> None:
        """确保适配器已加载"""
        if self._initialized_adapters:
            return

        try:
            import core.llm_adapters
        except ImportError:
            pass

    async def call(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_chunk: Optional[Callable[[str], None]] = None,
        strategy: Optional[str] = None,
        **kwargs
    ) -> "LLMResult":
        """
        统一 LLM 调用入口

        Args:
            messages: 消息列表
            task_type: 任务类型（自动选择模型）
            model: 指定模型（优先级最高）
            temperature: 温度参数
            max_tokens: 最大输出 tokens
            stream: 是否流式输出
            on_chunk: 流式回调函数
            strategy: 调度策略 (auto/quality/cost/speed)
            **kwargs: 其他参数

        Returns:
            LLMResult 对象
        """
        from schemas.unified_model_spec import DispatchStrategy, LLMResult

        selection = self.resolve_model_request(
            task_type=task_type,
            model=model,
            strategy=strategy,
        )
        selected_model_id = selection["resolved_model_id"]

        if selected_model_id is None:
            selected_model_id = self._get_default_model()
            selection["resolved_model_id"] = selected_model_id
            selection["selection_mode"] = "default"

        if selected_model_id is None:
            return self._attach_resolution_metadata(
                LLMResult(
                    success=False,
                    model_id="",
                    error="没有可用的模型",
                    error_code="no_model_available"
                ),
                selection,
            )

        result = await self._execute_call(
            model_id=selected_model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            on_chunk=on_chunk,
            **kwargs
        )
        return self._attach_resolution_metadata(result, selection)

    async def _execute_call(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        stream: bool,
        on_chunk: Optional[Callable[[str], None]],
        **kwargs
    ) -> "LLMResult":
        """执行实际调用"""
        from schemas.unified_model_spec import LLMResult

        spec = self.registry.get_spec(model_id)
        if not spec:
            return LLMResult(
                success=False,
                model_id=model_id,
                error=f"模型 {model_id} 未注册",
                error_code="model_not_registered"
            )

        if not self.registry._is_available(model_id):
            fallback_id = spec.get_fallback_model()
            if fallback_id and self.registry._is_available(fallback_id):
                logger.warning(f"⚠️ 模型 {model_id} 不可用，切换到回退模型 {fallback_id}")
                model_id = fallback_id
                spec = self.registry.get_spec(model_id)
            else:
                return LLMResult(
                    success=False,
                    model_id=model_id,
                    error=f"模型 {model_id} 不可用且无回退模型",
                    error_code="model_unavailable"
                )

        adapter = self.registry.get_adapter(model_id)
        if not adapter:
            return LLMResult(
                success=False,
                model_id=model_id,
                error=f"模型 {model_id} 无适配器",
                error_code="adapter_missing"
            )

        max_retries = self._resolve_max_retries(spec, kwargs)
        last_result = None

        for attempt in range(max_retries):
            try:
                if stream and on_chunk:
                    result = await adapter.generate_stream(
                        messages=messages,
                        on_chunk=on_chunk,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs
                    )
                else:
                    result = await adapter.generate(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=stream,
                        on_chunk=on_chunk,
                        **kwargs
                    )

                if result.success:
                    self.registry.record_success(
                        model_id=model_id,
                        latency=result.latency,
                        cost=result.cost,
                        input_tokens=result.usage.get("prompt_tokens", 0),
                        output_tokens=result.usage.get("completion_tokens", 0)
                    )
                    return result

                last_result = result

                if result.error_code in ["auth_error", "model_not_found"]:
                    break

                if result.error_code == "rate_limit":
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(f"⚠️ 限流，等待 {wait_time}秒后重试")
                    await asyncio.sleep(wait_time)

                self.registry.record_failure(model_id, result.error_code or "unknown")

            except Exception as e:
                logger.error(f"❌ 调用异常: {e}")
                self.registry.record_failure(model_id, "exception")

                last_result = LLMResult(
                    success=False,
                    model_id=model_id,
                    error=str(e),
                    error_code="exception"
                )

        fallback_id = spec.get_fallback_model() if spec else None
        if fallback_id and fallback_id != model_id:
            logger.warning(f"⚠️ 模型 {model_id} 调用失败，尝试回退模型 {fallback_id}")
            return await self._execute_call(
                model_id=fallback_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                on_chunk=on_chunk,
                **{k: v for k, v in kwargs.items() if k != "max_retries"}
            )

        return last_result or LLMResult(
            success=False,
            model_id=model_id,
            error="调用失败",
            error_code="call_failed"
        )

    def resolve_model_request(
        self,
        *,
        task_type: Optional[str] = None,
        model: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.registry.get_all_specs():
            self.initialize()

        self._ensure_adapters_loaded()

        normalized_task_type = normalize_task_type(task_type)
        requested_model_id = normalize_model_id(model)
        dispatch_strategy = self._parse_strategy(strategy)
        resolved_model_id: Optional[str] = None
        selection_mode = "unresolved"
        reason: Optional[str] = None
        requested_signal: Optional[Dict[str, Any]] = None

        if requested_model_id is None and normalized_task_type:
            selected_spec = self.registry.select_best_model(normalized_task_type, dispatch_strategy)
            if selected_spec:
                resolved_model_id = selected_spec.id
                selection_mode = "task_router"
        elif requested_model_id is not None:
            requested_signal = get_model_catalog_runtime_index().get_signal(requested_model_id).to_dict()
            resolved_model_id = self._resolve_catalog_guarded_model(
                requested_model_id,
                task_type=normalized_task_type,
                strategy=dispatch_strategy,
            )
            selection_mode = "explicit_model"
            if resolved_model_id != requested_model_id:
                reason = requested_signal.get("reason") or "catalog_guard_reroute"

        return {
            "task_type": normalized_task_type,
            "strategy": getattr(dispatch_strategy, "value", str(dispatch_strategy)),
            "requested_model_id": requested_model_id,
            "resolved_model_id": resolved_model_id,
            "requested_catalog_routing": requested_signal,
            "rerouted": bool(requested_model_id and resolved_model_id and resolved_model_id != requested_model_id),
            "reason": reason,
            "selection_mode": selection_mode,
        }

    def _resolve_max_retries(
        self,
        spec: "UnifiedModelSpec",
        kwargs: Dict[str, Any],
    ) -> int:
        """解析本次调用的重试次数，优先使用模型配置。"""
        explicit_value = kwargs.get("max_retries")
        if explicit_value is not None:
            try:
                return max(1, int(explicit_value))
            except (TypeError, ValueError):
                logger.warning(f"⚠️ 非法 max_retries={explicit_value!r}，回退到模型默认配置")

        if not spec.constraints.supports_max_retries:
            return 1

        configured_retries = spec.api_config.default_max_retries
        try:
            return max(1, int(configured_retries))
        except (TypeError, ValueError):
            logger.warning(
                f"⚠️ 模型 {spec.id} 的 default_max_retries={configured_retries!r} 非法，使用默认值 1"
            )
            return 1

    def _resolve_catalog_guarded_model(
        self,
        model_id: str,
        *,
        task_type: Optional[str],
        strategy: "DispatchStrategy",
    ) -> str:
        runtime_index = get_model_catalog_runtime_index()
        signal = runtime_index.get_signal(model_id)
        if not signal.blocked:
            return model_id

        if task_type:
            alternative = self.registry.select_best_model(task_type, strategy)
            if alternative and alternative.id != model_id:
                logger.warning(
                    "⚠️ 模型 %s 最近联网校验失败，自动切换到任务 %s 的可路由模型 %s",
                    model_id,
                    task_type,
                    alternative.id,
                )
                return alternative.id

        spec = self.registry.get_spec(model_id)
        fallback_id = spec.get_fallback_model() if spec else None
        if fallback_id and fallback_id != model_id and self.registry._is_available(fallback_id):
            fallback_signal = runtime_index.get_signal(fallback_id)
            if not fallback_signal.blocked:
                logger.warning(
                    "⚠️ 模型 %s 最近联网校验失败，自动切换到回退模型 %s",
                    model_id,
                    fallback_id,
                )
                return fallback_id

        logger.warning(
            "⚠️ 模型 %s 最近联网校验失败，但暂未找到更稳妥的替代模型，保留原始调用",
            model_id,
        )
        return model_id

    def _attach_resolution_metadata(self, result: "LLMResult", selection: Dict[str, Any]) -> "LLMResult":
        metadata = dict(getattr(result, "metadata", {}) or {})
        metadata["selection_mode"] = selection.get("selection_mode")
        metadata["requested_model_id"] = selection.get("requested_model_id")
        metadata["resolved_model_id"] = selection.get("resolved_model_id")
        metadata["rerouted"] = bool(selection.get("rerouted"))
        if selection.get("requested_catalog_routing") is not None:
            metadata["requested_catalog_routing"] = deepcopy(selection["requested_catalog_routing"])
        if selection.get("reason"):
            metadata["routing_reason"] = selection.get("reason")
        result.metadata = metadata
        return result

    def _attach_catalog_signal(self, info: Dict[str, Any], model_id: str) -> Dict[str, Any]:
        payload = dict(info)
        payload["catalog_routing"] = get_model_catalog_runtime_index().get_signal(model_id).to_dict()
        return payload

    def _parse_strategy(self, strategy: Optional[str]) -> "DispatchStrategy":
        """解析调度策略"""
        from schemas.unified_model_spec import DispatchStrategy

        if strategy is None:
            return self.default_strategy

        strategy_map = {
            "auto": DispatchStrategy.AUTO,
            "quality": DispatchStrategy.QUALITY,
            "cost": DispatchStrategy.COST,
            "speed": DispatchStrategy.SPEED,
        }
        return strategy_map.get(strategy.lower(), DispatchStrategy.AUTO)

    def _get_default_model(self) -> Optional[str]:
        """获取默认模型"""
        default_models = ["qwen3-max", "deepseek-chat", "qwen-turbo"]
        for model_id in default_models:
            if self.registry._is_available(model_id):
                return model_id
        return None

    def register_model(
        self,
        model_id: str,
        name: str,
        provider: str,
        capabilities: List[str],
        task_types: List[str],
        **kwargs
    ) -> None:
        """
        动态注册模型

        Args:
            model_id: 模型 ID
            name: 模型名称
            provider: 提供商
            capabilities: 能力列表
            task_types: 支持的任务类型
            **kwargs: 其他配置
        """
        from schemas.unified_model_spec import (
            UnifiedModelSpec, LLMCapability, LLMConstraints,
            APIConfig, PerformanceProfile, RoutingConfig, SupportLevel
        )

        capability_objs = [
            LLMCapability(name=cap, level=SupportLevel.NATIVE, score=0.8)
            for cap in capabilities
        ]

        constraints = LLMConstraints(
            max_context_tokens=kwargs.get("max_context_tokens", 4096),
            max_output_tokens=kwargs.get("max_output_tokens", 4096),
        )

        api_config = APIConfig(
            api_key_env=kwargs.get("api_key_env", f"{provider.upper()}_API_KEY"),
            base_url=kwargs.get("base_url", ""),
        )

        performance = PerformanceProfile(
            quality_score=kwargs.get("quality_score", 7.0),
            avg_latency_seconds=kwargs.get("avg_latency_seconds", 2.0),
            cost_per_1k_input_tokens=kwargs.get("cost_per_1k_input_tokens", 0.0),
            cost_per_1k_output_tokens=kwargs.get("cost_per_1k_output_tokens", 0.0),
        )

        routing = RoutingConfig(
            task_types=task_types,
            priority=kwargs.get("priority", 1),
            fallback_models=kwargs.get("fallback_models", []),
        )

        spec = UnifiedModelSpec(
            id=model_id,
            name=name,
            provider=provider,
            model_type="llm",
            capabilities=capability_objs,
            constraints=constraints,
            api_config=api_config,
            performance=performance,
            routing=routing,
        )

        self.registry.register(spec)

    def list_models(
        self,
        model_type: Optional[str] = None,
        provider: Optional[str] = None,
        task_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出模型

        Args:
            model_type: 模型类型过滤
            provider: 提供商过滤
            task_type: 任务类型过滤

        Returns:
            模型列表
        """
        specs = self.registry.get_all_specs()

        if model_type:
            specs = [s for s in specs if s.model_type.value == model_type]
        if provider:
            specs = [s for s in specs if s.provider == provider]
        if task_type:
            specs = [s for s in specs if s.supports_task_type(task_type)]

        return [self._attach_catalog_signal(s.to_dict(), s.id) for s in specs]

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """获取模型详情"""
        spec = self.registry.get_spec(model_id)
        if spec:
            info = self._attach_catalog_signal(spec.to_dict(), spec.id)
            stats = self.registry.get_performance_stats(model_id)
            if stats:
                info["stats"] = stats.to_dict()
            return info
        return None

    def select_model(
        self,
        task_type: str,
        strategy: Optional[str] = None
    ) -> Optional["UnifiedModelSpec"]:
        """
        为任务选择最佳模型

        Args:
            task_type: 任务类型
            strategy: 调度策略

        Returns:
            最佳模型规格
        """
        if not self.registry.get_all_specs():
            self.initialize()

        dispatch_strategy = self._parse_strategy(strategy)
        return self.registry.select_best_model(normalize_task_type(task_type) or task_type, dispatch_strategy)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "registry": self.registry.get_registry_status(),
            "performance": self.registry.get_all_performance_stats(),
        }


model_hub = ModelHub.get_instance()


def get_model_hub() -> ModelHub:
    """获取 ModelHub 单例"""
    return model_hub


async def call_llm(
    messages: List[Dict[str, str]],
    task_type: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> "LLMResult":
    """
    便捷函数：调用 LLM

    Args:
        messages: 消息列表
        task_type: 任务类型
        model: 指定模型
        **kwargs: 其他参数

    Returns:
        LLMResult
    """
    return await model_hub.call(
        messages=messages,
        task_type=task_type,
        model=model,
        **kwargs
    )
