from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict, Field

from core.model_resolution import normalize_model_id, normalize_task_type
from core.model_runtime import (
    ensure_model_hub_initialized,
    get_model_base_url,
    resolve_model_for_task,
    run_async_compat,
)


def _message_type_to_role(message: BaseMessage) -> str:
    msg_type = getattr(message, "type", "human")
    role_map = {
        "system": "system",
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
        "function": "function",
    }
    return role_map.get(msg_type, msg_type or "user")


def _to_model_hub_messages(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    serialized: List[Dict[str, str]] = []
    for message in messages:
        serialized.append(
            {
                "role": _message_type_to_role(message),
                "content": str(getattr(message, "content", "") or ""),
            }
        )
    return serialized


class ModelHubChatModel(BaseChatModel):
    """LangChain 兼容桥，底层统一走 ModelHub。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_type: Optional[str] = None
    model_name: str = "qwen3-max"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    runtime_options: Dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "model_hub"

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def openai_api_base(self) -> str:
        return get_model_base_url(self.model_name)

    @property
    def base_url(self) -> str:
        return self.openai_api_base

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        from core.model_hub import model_hub

        ensure_model_hub_initialized()

        call_kwargs = {**self.runtime_options, **kwargs}
        if stop:
            call_kwargs["stop"] = stop

        result = await model_hub.call(
            messages=_to_model_hub_messages(messages),
            task_type=self.task_type,
            model=self.model_name,
            temperature=call_kwargs.pop("temperature", self.temperature),
            max_tokens=call_kwargs.pop("max_tokens", self.max_tokens),
            **call_kwargs,
        )

        if not result.success:
            raise RuntimeError(
                f"统一模型调用失败: model={result.model_id or self.model_name} "
                f"task_type={self.task_type or 'default'} "
                f"error={result.error or result.error_code or 'unknown'}"
            )

        ai_message = AIMessage(
            content=result.content,
            additional_kwargs={
                "model_id": result.model_id,
                "usage": result.usage,
                "latency": result.latency,
                "cost": result.cost,
                **result.metadata,
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=ai_message)],
            llm_output={
                "model_id": result.model_id,
                "usage": result.usage,
                "latency": result.latency,
                "cost": result.cost,
            },
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return run_async_compat(lambda: self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs))

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        from core.model_hub import model_hub

        ensure_model_hub_initialized()

        chunks: List[str] = []
        call_kwargs = {**self.runtime_options, **kwargs}
        if stop:
            call_kwargs["stop"] = stop

        def on_chunk(chunk: str) -> None:
            chunks.append(chunk)

        result = run_async_compat(
            lambda: model_hub.call(
                messages=_to_model_hub_messages(messages),
                task_type=self.task_type,
                model=self.model_name,
                temperature=call_kwargs.pop("temperature", self.temperature),
                max_tokens=call_kwargs.pop("max_tokens", self.max_tokens),
                stream=True,
                on_chunk=on_chunk,
                **call_kwargs,
            )
        )

        if not result.success:
            raise RuntimeError(
                f"统一模型流式调用失败: model={result.model_id or self.model_name} "
                f"task_type={self.task_type or 'default'} "
                f"error={result.error or result.error_code or 'unknown'}"
            )

        if not chunks and result.content:
            chunks = [result.content]

        for chunk in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))


def create_task_llm(
    task_type: Optional[Any] = None,
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **kwargs: Any,
) -> ModelHubChatModel:
    ensure_model_hub_initialized()

    normalized_task_type = normalize_task_type(task_type)
    resolved_model = resolve_model_for_task(normalized_task_type, model)
    normalized_model = normalize_model_id(resolved_model) or "qwen3-max"

    return ModelHubChatModel(
        task_type=normalized_task_type,
        model_name=normalized_model,
        temperature=temperature,
        max_tokens=max_tokens,
        runtime_options=kwargs,
    )


def create_model_llm(model: str, temperature: float = 0.7, **kwargs: Any) -> ModelHubChatModel:
    return create_task_llm(model=model, temperature=temperature, **kwargs)


def get_task_llm(task_type: Optional[Any] = None) -> ModelHubChatModel:
    return create_task_llm(task_type=task_type)
