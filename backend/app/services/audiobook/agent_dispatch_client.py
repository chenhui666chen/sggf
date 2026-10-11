"""Agent 智能调度客户端 - 专为 Agent 层设计的 TTS 调度封装

核心功能：
1. 为 Agent 提供统一的 TTS 智能调度接口
2. 自动路由选择最优 TTS 模型（基于策略）
3. 自动降级到已注册的备选 TTS 模型
4. 完整的 trace 可观测性

已注册的 TTS 模型：
- MiniMax/speech-2.8-turbo（低延迟，DashScope API）
- MiniMax/speech-2.8-hd（高质量，DashScope API）
- qwen-audio-3.1-tts-flash（快速，可通过 instructions 精细控制，DashScope API）
- cosyvoice-v3.5-plus（高表现力，需先准备复刻/设计音色，WebSocket API）
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from schemas.task_spec import TaskSpec, PriorityProfile
from schemas.common import Priority, Modality
from core.router import router as smart_router, RoutingResult
from core.execution_engine import engine as execution_engine, ExecutionResult
from adapters.registry import registry as model_registry
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.audiobook.segment_synthesis_contract import (
    resolve_server_owned_mimo_design_params,
)
from app.services.audiobook.voice_identity_policy import (
    is_voice_design_creation_request,
    sanitize_fixed_voice_prompt_params,
)
from app.services.audiobook.voice_parameter_policy import (
    stabilize_fixed_voice_pitch,
    stabilize_instruct_model_speed,
)

logger = logging.getLogger(__name__)


_DISPATCH_MODEL_FIELDS = ("resolved_tts_model", "tts_model", "model_id")


def _normalize_dispatch_model(kwargs: Dict[str, Any]) -> str:
    models = {
        normalize_audiobook_tts_model(kwargs.get(field), default="")
        for field in _DISPATCH_MODEL_FIELDS
        if str(kwargs.get(field) or "").strip()
    }
    models.discard("")
    if len(models) > 1:
        raise ValueError("TTS 调度参数包含互相冲突的模型绑定")
    return next(iter(models), "")


def _sanitize_dispatch_kwargs(
    kwargs: Dict[str, Any],
    *,
    tts_model: str,
    voice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply the fixed-voice contract before either routing or direct fallback."""

    sanitized = dict(kwargs or {})
    owner_user_id = sanitized.pop("owner_user_id", None)
    identity_context = dict(sanitized)
    if voice_id:
        identity_context["voice_id"] = voice_id

    def _sanitize_mapping(
        value: Dict[str, Any],
        *,
        identity_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = dict(value or {})
        for field_name in ("voice_id", "speaker", "mimo_voice_asset_id"):
            if not context.get(field_name) and identity_context:
                context[field_name] = identity_context.get(field_name)
        params = stabilize_instruct_model_speed(value, tts_model)
        if is_voice_design_creation_request(tts_model, context):
            return params

        params, _ = sanitize_fixed_voice_prompt_params(params)
        params = stabilize_fixed_voice_pitch(params)
        for field_name in (
            "voice_description",
            "voice_clone_data_url",
            "voice_design_prompt",
            "mimo_voice_asset_id",
            "provider_prompt",
            "provider_prompt_snapshot",
        ):
            params.pop(field_name, None)
        return params

    nested = sanitized.get("voice_params")
    if isinstance(nested, dict):
        for field_name in ("voice_id", "speaker", "mimo_voice_asset_id"):
            if not identity_context.get(field_name) and nested.get(field_name):
                identity_context[field_name] = nested[field_name]
    server_owned_voice_params = resolve_server_owned_mimo_design_params(
        tts_model=tts_model,
        voice_id=str(
            voice_id
            or identity_context.get("voice_id")
            or identity_context.get("speaker")
            or ""
        ),
        mimo_voice_asset_id=str(identity_context.get("mimo_voice_asset_id") or ""),
        owner_user_id=owner_user_id,
    )

    if isinstance(nested, dict):
        sanitized_nested = _sanitize_mapping(
            nested,
            identity_context=identity_context,
        )
        sanitized_nested.update(server_owned_voice_params)
        sanitized["voice_params"] = sanitized_nested

    result = _sanitize_mapping(
        sanitized,
        identity_context=identity_context,
    )
    if not isinstance(nested, dict):
        result.update(server_owned_voice_params)
    return result


@dataclass
class TTSDispatchResult:
    """TTS 调度结果"""
    success: bool
    audio_data: Optional[bytes] = None
    audio_url: Optional[str] = None
    model_used: str = ""
    fallback_chain: List[str] = field(default_factory=list)
    latency: float = 0.0
    error: Optional[str] = None
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "model_used": self.model_used,
            "fallback_chain": self.fallback_chain,
            "latency_seconds": round(self.latency, 3),
            "audio_size_bytes": len(self.audio_data) if self.audio_data else 0,
            "audio_url": self.audio_url,
            "error": self.error,
            "trace": self.trace,
        }


class AgentSmartDispatchClient:
    """Agent 专用的智能调度客户端

    将 Agent 层与智能调度系统（SmartRouter + ExecutionEngine）桥接，
    使 Agent 能够使用智能路由和自动降级进行 TTS 生成。

    调度策略映射：
    - quality: 优先选择高质量模型（MiniMax/speech-2.8-hd > cosyvoice-v3.5-plus）
    - fast: 优先选择快速模型（qwen-audio-3.1-tts-flash ≈ cosyvoice-v3.5-plus）
    - balanced: 平衡质量和速度（默认策略）
    - cost_saving: 优先选择低成本模型（qwen-audio-3.1-tts-flash > MiniMax/speech-2.8-turbo）

    降级链：主模型失败后自动切换到备选模型，最多尝试 3 次。
    """

    AVAILABLE_TTS_MODELS = [
        "MiniMax/speech-2.8-turbo",
        "MiniMax/speech-2.8-hd",
        "qwen-audio-3.1-tts-flash",
        "cosyvoice-v3.5-plus",
    ]

    STRATEGY_MAP = {
        "quality": "quality",
        "fast": "speed",
        "balanced": "balanced",
        "cost_saving": "cost",
    }

    AGENT_STRATEGY_DEFAULTS = {
        "content_creator": "quality",
        "character_designer": "quality",
        "plot_architect": "balanced",
        "voice_manager": "balanced",
        "default": "balanced",
    }

    def __init__(self, default_strategy: str = "balanced"):
        self._default_strategy = default_strategy
        self._router = smart_router
        self._engine = execution_engine
        self._route_history: List[Dict[str, Any]] = []

    def synthesize(
        self,
        text: str,
        strategy: Optional[str] = None,
        voice_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        **kwargs,
    ) -> TTSDispatchResult:
        """合成语音 - 使用智能路由选择最优 TTS 模型

        Args:
            text: 要合成的文本
            strategy: 调度策略 (quality/fast/balanced/cost_saving)
            voice_id: 指定音色 ID（可选）
            agent_type: Agent 类型（用于自动选择策略）
            **kwargs: 其他 TTS 参数

        Returns:
            TTSDispatchResult: 合成结果
        """
        try:
            requested_model = _normalize_dispatch_model(kwargs)
        except ValueError as exc:
            return TTSDispatchResult(success=False, error=str(exc))
        if voice_id and not requested_model:
            return TTSDispatchResult(
                success=False,
                error="固定音色必须绑定所属 TTS 模型，禁止跨模型路由或降级",
            )
        try:
            safe_kwargs = _sanitize_dispatch_kwargs(
                kwargs,
                tts_model=requested_model,
                voice_id=voice_id,
            )
        except ValueError as exc:
            return TTSDispatchResult(success=False, error=str(exc))
        if requested_model:
            safe_kwargs["tts_model"] = requested_model
            safe_kwargs.pop("resolved_tts_model", None)
            safe_kwargs.pop("model_id", None)

        if not strategy:
            if agent_type and agent_type in self.AGENT_STRATEGY_DEFAULTS:
                strategy = self.AGENT_STRATEGY_DEFAULTS[agent_type]
            else:
                strategy = self._default_strategy

        mapped_strategy = self.STRATEGY_MAP.get(strategy, "balanced")

        task = TaskSpec(
            task_id=f"tts_{int(time.time() * 1000)}",
            prompt=text,
            modality=Modality.TEXT_TO_SPEECH,
            priority_profile=PriorityProfile(
                quality=0.40,
                cost=0.30,
                latency=0.30,
            ),
            extra={
                "voice_id": voice_id,
                "strategy": strategy,
                "agent_type": agent_type,
                **safe_kwargs,
            },
        )

        routing_result: Optional[RoutingResult] = None
        try:
            if requested_model:
                selected_model = model_registry.get_spec(requested_model)
                if selected_model is None:
                    raise ValueError(f"固定音色所属 TTS 模型未注册: {requested_model}")
                routing_result = RoutingResult(
                    selected_model=selected_model,
                    fallback_models=[],
                    score=1.0,
                    base_score=1.0,
                    reasons=["固定音色绑定模型，禁用跨模型降级"],
                    strategy=mapped_strategy,
                )
            else:
                routing_result = self._router.route_with_fallback_by_strategy(
                    task=task,
                    strategy=mapped_strategy,
                    max_fallbacks=2,
                )
            logger.info(
                "TTS 路由决策: 主模型=%s, 降级模型=%s, 策略=%s",
                routing_result.selected_model.id,
                [m.id for m in routing_result.fallback_models],
                strategy,
            )
            self._route_history.append({
                "timestamp": time.time(),
                "strategy": strategy,
                "selected_model": routing_result.selected_model.id,
                "fallback_models": [m.id for m in routing_result.fallback_models],
            })
        except Exception as e:
            if requested_model:
                logger.warning("固定音色模型绑定失败，禁止跨模型降级: %s", e)
                return TTSDispatchResult(
                    success=False,
                    error=str(e),
                    trace={"strategy": strategy, "fixed_voice_model": requested_model},
                )
            logger.warning("TTS 路由失败，使用默认模型: %s", e)
            return self._synthesize_fallback(text, voice_id, strategy, safe_kwargs)

        try:
            exec_result: ExecutionResult = self._engine.execute(
                task=task,
                strategy=mapped_strategy,
                use_fallback=not bool(requested_model),
                max_attempts=1 if requested_model else 3,
                timeout=120.0,
                routing_result=routing_result,
            )
            return self._convert_exec_result(exec_result, strategy)
        except Exception as e:
            logger.error("TTS 执行失败: %s", e)
            return TTSDispatchResult(
                success=False,
                error=str(e),
                latency=0.0,
                trace={"strategy": strategy, "routing": routing_result.to_dict() if routing_result else {}},
            )

    def synthesize_batch(
        self,
        texts: List[str],
        strategy: Optional[str] = None,
        voice_ids: Optional[List[str]] = None,
        tts_models: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        max_concurrent: int = 5,
        **kwargs,
    ) -> List[TTSDispatchResult]:
        """批量合成语音 - 使用智能路由

        Args:
            texts: 要合成的文本列表
            strategy: 调度策略
            voice_ids: 音色 ID 列表（与 texts 对应）
            tts_models: 音色所属 TTS 模型列表（与 texts 对应）
            agent_type: Agent 类型
            max_concurrent: 最大并发数
            **kwargs: 其他 TTS 参数

        Returns:
            List[TTSDispatchResult]: 合成结果列表
        """
        if not texts:
            return []

        voice_ids = voice_ids or [None] * len(texts)
        tts_models = tts_models or [None] * len(texts)
        if len(voice_ids) != len(texts) or len(tts_models) != len(texts):
            raise ValueError("texts、voice_ids 与 tts_models 长度必须一致")

        import concurrent.futures

        results: List[TTSDispatchResult] = [None] * len(texts)

        def _synthesize_with_index(
            idx: int,
            text: str,
            vid: Optional[str],
            tts_model: Optional[str],
        ):
            item_kwargs = dict(kwargs)
            if tts_model:
                item_kwargs["tts_model"] = tts_model
            result = self.synthesize(
                text=text,
                strategy=strategy,
                voice_id=vid,
                agent_type=agent_type,
                **item_kwargs,
            )
            return idx, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = [
                executor.submit(
                    _synthesize_with_index,
                    i,
                    text,
                    voice_ids[i],
                    tts_models[i],
                )
                for i, text in enumerate(texts)
            ]

            for future in concurrent.futures.as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results

    def _synthesize_fallback(
        self,
        text: str,
        voice_id: Optional[str],
        strategy: str,
        kwargs: Dict[str, Any],
    ) -> TTSDispatchResult:
        """路由失败时的兜底合成方案"""
        for model_id in self.AVAILABLE_TTS_MODELS:
            try:
                adapter = model_registry.get_adapter(model_id)
                if adapter is None:
                    continue

                result = adapter.generate(prompt=text, voice_id=voice_id, **kwargs)
                if result.success:
                    audio_bytes = result.metadata.get("audio_bytes")
                    return TTSDispatchResult(
                        success=True,
                        audio_data=audio_bytes,
                        model_used=model_id,
                        latency=result.latency,
                        trace={"strategy": strategy, "fallback_direct": True},
                    )
            except Exception as e:
                logger.debug("兜底模型 %s 失败: %s", model_id, e)
                continue

        return TTSDispatchResult(
            success=False,
            error="所有已注册 TTS 模型均失败",
            latency=0.0,
            trace={"strategy": strategy, "fallback_direct": True},
        )

    def _convert_exec_result(
        self, exec_result: ExecutionResult, strategy: str
    ) -> TTSDispatchResult:
        """将 ExecutionResult 转换为 TTSDispatchResult"""
        fallback_chain = []
        if exec_result.fallback_chain:
            for attempt in exec_result.fallback_chain.attempts:
                model_id = getattr(attempt, "model_id", "")
                if model_id and model_id != "none":
                    fallback_chain.append(model_id)

        audio_data = exec_result.metadata.get("audio_bytes")
        audio_url = None
        if exec_result.outputs:
            first_output = exec_result.outputs[0]
            if first_output.startswith("http"):
                audio_url = first_output

        trace = exec_result.trace or {}
        trace["strategy"] = strategy
        trace["routing_history_count"] = len(self._route_history)

        return TTSDispatchResult(
            success=exec_result.success,
            audio_data=audio_data,
            audio_url=audio_url,
            model_used=exec_result.model_id,
            fallback_chain=fallback_chain,
            latency=exec_result.latency,
            error=exec_result.error,
            trace=trace,
        )

    def get_available_models(self) -> List[Dict[str, Any]]:
        """获取所有已注册的 TTS 模型信息"""
        specs = model_registry.get_specs_by_modality("text_to_speech")
        return [
            {
                "id": spec.id,
                "name": spec.name,
                "provider": spec.provider,
                "latency_seconds": spec.avg_latency_seconds,
                "status": spec.status.value,
            }
            for spec in specs
            if spec.id in self.AVAILABLE_TTS_MODELS
        ]

    def get_route_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取路由历史记录（用于调试和可观测性）"""
        return self._route_history[-limit:]


client = AgentSmartDispatchClient()
