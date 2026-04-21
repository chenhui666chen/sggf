"""Agent 智能调度客户端 - 专为 Agent 层设计的 TTS 调度封装

核心功能：
1. 为 Agent 提供统一的 TTS 智能调度接口
2. 自动路由选择最优 TTS 模型（基于策略）
3. 自动降级到已注册的备选 TTS 模型
4. 完整的 trace 可观测性

已注册的 TTS 模型：
- MiniMax/speech-2.8-turbo（低延迟，DashScope API）
- MiniMax/speech-2.8-hd（高质量，DashScope API）
- qwen3-tts-instruct-flash（快速，可通过 instructions 精细控制，DashScope API）
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

logger = logging.getLogger(__name__)


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
    - fast: 优先选择快速模型（qwen3-tts-instruct-flash ≈ cosyvoice-v3.5-plus）
    - balanced: 平衡质量和速度（默认策略）
    - cost_saving: 优先选择低成本模型（qwen3-tts-instruct-flash > MiniMax/speech-2.8-turbo）

    降级链：主模型失败后自动切换到备选模型，最多尝试 3 次。
    """

    AVAILABLE_TTS_MODELS = [
        "MiniMax/speech-2.8-turbo",
        "MiniMax/speech-2.8-hd",
        "qwen3-tts-instruct-flash",
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
                **kwargs,
            },
        )

        routing_result: Optional[RoutingResult] = None
        try:
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
            logger.warning("TTS 路由失败，使用默认模型: %s", e)
            return self._synthesize_fallback(text, voice_id, strategy, kwargs)

        try:
            exec_result: ExecutionResult = self._engine.execute(
                task=task,
                strategy=mapped_strategy,
                use_fallback=True,
                max_attempts=3,
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
        agent_type: Optional[str] = None,
        max_concurrent: int = 5,
        **kwargs,
    ) -> List[TTSDispatchResult]:
        """批量合成语音 - 使用智能路由

        Args:
            texts: 要合成的文本列表
            strategy: 调度策略
            voice_ids: 音色 ID 列表（与 texts 对应）
            agent_type: Agent 类型
            max_concurrent: 最大并发数
            **kwargs: 其他 TTS 参数

        Returns:
            List[TTSDispatchResult]: 合成结果列表
        """
        if not texts:
            return []

        voice_ids = voice_ids or [None] * len(texts)

        import concurrent.futures

        results: List[TTSDispatchResult] = [None] * len(texts)

        def _synthesize_with_index(idx: int, text: str, vid: Optional[str]):
            result = self.synthesize(
                text=text,
                strategy=strategy,
                voice_id=vid,
                agent_type=agent_type,
                **kwargs,
            )
            return idx, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = [
                executor.submit(_synthesize_with_index, i, text, voice_ids[i])
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
