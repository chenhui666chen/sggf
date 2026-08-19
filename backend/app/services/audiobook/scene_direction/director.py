"""SeedSceneDirector：窄职责导演服务（指导文档 §4.2/§4.3/§12.2）。

职责与约束：

- 只在 seed_scene 模式运行；消费已审定片段与章节上下文，输出
  ``SeedSceneDirection[]``；不得修改台词事实，不得直接调用 Seed Audio。
- 四级预算作用域：单次调用超时、单章调用次数、单章 token/金额、单任务累计；
  超预算不继续调用，恢复不重新获得预算。
- JSON/Schema/事实校验失败时每批次最多一次纠错重试（max_attempts_per_batch=2）。
- 仍失败时按保真判定分流：V1 可保真 → degrade_v1（director_degraded_to_v1）；
  V1 无法承载 → manual_review / terminal policy。
- DirectorInputSignature 为导演计划 checkpoint 唯一缓存键；命中时零调用。
- attempt ledger 始终保留：输入变化后创建新 checkpoint，历史账本不删除。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.model_resolution import TaskType

from ..hashing import canonical_hash
from ..llm_client import call_audiobook_llm_async
from ..script_adapter_pkg._seed_scene_capability import (
    SEED_SCENE_CAPABILITY_CONTRACT_VERSION,
)
from .models import SeedSceneDirection
from .parser import (
    DirectionParseError,
    parse_seed_scene_directions,
    serialize_seed_scene_directions,
)
from .policy import DEFAULT_SEED_SCENE_DIRECTOR_POLICY, SeedSceneDirectorPolicy
from .prompt import (
    build_seed_director_prompt,
    director_prompt_hash,
    director_schema_hash,
)
from .signature import build_director_input_signature
from .validator import validate_seed_scene_directions

DIRECTOR_CHECKPOINT_TYPE = "seed_scene_director_plan"
DIRECTOR_CHECKPOINT_SCHEMA_VERSION = 1
DIRECTOR_PLAN_HASH_CONTRACT_NAME = "seed_scene_direction_plan"
DIRECTOR_PLAN_HASH_CONTRACT_VERSION = "1.0.0"
_CONTEXT_SOURCE_HASH_CONTRACT = ("seed_scene_context_source", "1.0.0")
_PROFILES_HASH_CONTRACT = ("seed_scene_character_profiles", "1.0.0")
_SEGMENTS_HASH_CONTRACT = ("seed_scene_source_segments", "1.0.0")

# V1 确定性编译无法承载的重叠/插话标注关键词（保真判定）。
_V1_BLOCKING_TERMS = ("插话", "重叠", "抢话", "同时说", "齐声")

STATUS_COMPLETED = "completed"
STATUS_RETRYABLE_FAILED = "retryable_failed"
STATUS_TERMINAL_FAILED = "terminal_failed"

ACTION_REUSE = "reuse"
ACTION_CORRECTIVE_RETRY = "corrective_retry"
ACTION_DEGRADE_V1 = "degrade_v1"
ACTION_MANUAL_REVIEW = "manual_review"


@dataclass
class DirectorBudgetLedger:
    """已消费预算账本（可变）：章节级随单次运行累计，任务级跨章节累计。"""

    calls: int = 0
    tokens: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class DirectorOutcome:
    status: str
    next_action: str
    directions: Tuple[SeedSceneDirection, ...] = ()
    reason_code: str = ""
    attempts: Tuple[Dict[str, Any], ...] = ()


def v1_fidelity_feasible(segments: Sequence[Any]) -> bool:
    """保真判定：审定内容能否被 V1 确定性编译承载（§4.3 分流规则）。"""
    for segment in segments:
        if getattr(segment, "requires_overlap", False):
            return False
        for field_name in ("performance_notes", "instruct_scene"):
            value = str(getattr(segment, field_name, "") or "")
            if any(term in value for term in _V1_BLOCKING_TERMS):
                return False
    return True


class SeedSceneDirector:
    def __init__(
        self,
        llm_client: Any,
        *,
        model: str = "",
        provider: str = "audiobook-llm",
        policy: SeedSceneDirectorPolicy = DEFAULT_SEED_SCENE_DIRECTOR_POLICY,
        cost_per_1k_tokens: float = 0.004,
    ) -> None:
        self.llm = llm_client
        self.model = model
        self.provider = provider
        self.policy = policy
        self.cost_per_1k_tokens = cost_per_1k_tokens

    async def direct(
        self,
        segments: Sequence[Any],
        *,
        chapter_context: str = "",
        character_profiles_text: str = "",
        reviewed_analysis_artifact_hashes: Sequence[str] = (),
        segment_range: Tuple[int, int] | None = None,
        checkpoints: Optional[List[Dict[str, Any]]] = None,
        chapter_consumed: Optional[DirectorBudgetLedger] = None,
        job_consumed: Optional[DirectorBudgetLedger] = None,
    ) -> DirectorOutcome:
        policy = self.policy
        checkpoint_store = checkpoints if checkpoints is not None else []
        signature = self._input_signature(
            segments,
            chapter_context=chapter_context,
            character_profiles_text=character_profiles_text,
            reviewed_analysis_artifact_hashes=reviewed_analysis_artifact_hashes,
            segment_range=segment_range,
        )
        attempts: List[Dict[str, Any]] = []
        attempts_used = 0
        existing = self._find_checkpoint(checkpoint_store, signature)
        if existing is not None:
            self._merge_consumed(existing, chapter_consumed)
            attempts = list(existing.get("attempts") or ())
            attempts_used = int(existing.get("attempts_used_in_batch") or 0)
            outcome = self._outcome_from_checkpoint(existing)
            if outcome is not None:
                return DirectorOutcome(
                    status=outcome["status"],
                    next_action=outcome["next_action"],
                    directions=outcome.get("directions") or (),
                    reason_code=outcome.get("reason_code", ""),
                    attempts=tuple(attempts),
                )

        # 任务级预算优先拦截：超预算不发起任何调用。
        if job_consumed is not None and job_consumed.cost >= policy.max_cost_per_job:
            return self._budget_exceeded_outcome(segments, attempts)

        last_error_code = ""
        while attempts_used < policy.max_attempts_per_batch:
            if not self._chapter_budget_allows(chapter_consumed):
                break
            messages = build_seed_director_prompt(
                self._segments_text(segments),
                chapter_context=chapter_context,
                character_profiles_text=character_profiles_text,
            )
            if attempts_used > 0:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            f"上一轮输出未通过校验（错误码：{last_error_code}）。"
                            "请按 schema 修正后只重新输出严格 JSON。"
                        ),
                    }
                ]
            attempt = await self._attempt_call(messages, attempt_number=attempts_used + 1)
            attempts.append(attempt)
            self._apply_consumption(attempt, chapter_consumed, job_consumed)
            attempts_used += 1
            if attempt["status"] == "success":
                directions, error_code = self._parse_and_validate(attempt["response"], segments)
                if directions is not None:
                    plan_hash = canonical_hash(
                        serialize_seed_scene_directions(directions),
                        contract_name=DIRECTOR_PLAN_HASH_CONTRACT_NAME,
                        contract_version=DIRECTOR_PLAN_HASH_CONTRACT_VERSION,
                    )
                    checkpoint_store.append(
                        self._build_checkpoint(
                            signature,
                            status=STATUS_COMPLETED,
                            next_action=ACTION_REUSE,
                            attempts=attempts,
                            attempts_used=attempts_used,
                            chapter_consumed=chapter_consumed,
                            validated_plan_hash=plan_hash,
                            directions_payload=serialize_seed_scene_directions(directions),
                        )
                    )
                    return DirectorOutcome(
                        status=STATUS_COMPLETED,
                        next_action=ACTION_REUSE,
                        directions=directions,
                        attempts=tuple(attempts),
                    )
                last_error_code = error_code
                attempt["status"] = "validation_failed"
                attempt["error_code"] = error_code
            else:
                last_error_code = str(attempt.get("error_code") or "")
            continue

        return self._failure_outcome(
            segments,
            signature,
            attempts,
            attempts_used,
            chapter_consumed,
            checkpoint_store,
            last_error_code,
        )

    # ---- 内部辅助 -------------------------------------------------------

    def _input_signature(
        self,
        segments: Sequence[Any],
        *,
        chapter_context: str,
        character_profiles_text: str,
        reviewed_analysis_artifact_hashes: Sequence[str],
        segment_range: Tuple[int, int] | None,
    ) -> str:
        facts = [
            {
                "index": index,
                "speaker": str(getattr(segment, "speaker", "") or ""),
                "text": str(getattr(segment, "text", "") or ""),
                "performance_notes": str(getattr(segment, "performance_notes", "") or ""),
                "instruct_scene": str(getattr(segment, "instruct_scene", "") or ""),
            }
            for index, segment in enumerate(segments)
        ]
        source_segments_hash = canonical_hash(
            facts,
            contract_name=_SEGMENTS_HASH_CONTRACT[0],
            contract_version=_SEGMENTS_HASH_CONTRACT[1],
        )
        return build_director_input_signature(
            source_segments_hash=source_segments_hash,
            source_segment_range=segment_range or (0, len(segments)),
            reviewed_analysis_artifact_hashes=tuple(reviewed_analysis_artifact_hashes),
            scene_context_source_hash=canonical_hash(
                chapter_context,
                contract_name=_CONTEXT_SOURCE_HASH_CONTRACT[0],
                contract_version=_CONTEXT_SOURCE_HASH_CONTRACT[1],
            ),
            character_profiles_hash=canonical_hash(
                character_profiles_text,
                contract_name=_PROFILES_HASH_CONTRACT[0],
                contract_version=_PROFILES_HASH_CONTRACT[1],
            ),
            capability_contract_version=SEED_SCENE_CAPABILITY_CONTRACT_VERSION,
            director_model_id=self.model,
            director_prompt_hash=director_prompt_hash(),
            director_schema_hash=director_schema_hash(),
            policy_hash=self.policy.fingerprint(),
            policy_version=self.policy.version,
        )

    @staticmethod
    def _find_checkpoint(
        checkpoints: Sequence[Dict[str, Any]], signature: str
    ) -> Dict[str, Any] | None:
        for checkpoint in reversed(checkpoints):
            if checkpoint.get("input_signature_hash") == signature:
                return checkpoint
        return None

    @staticmethod
    def _merge_consumed(
        checkpoint: Dict[str, Any], ledger: DirectorBudgetLedger | None
    ) -> None:
        if ledger is None:
            return
        consumed = checkpoint.get("consumed") or {}
        # 恢复沿用已消费预算，不重置；取累计较大者避免回退。
        ledger.calls = max(ledger.calls, int(consumed.get("calls", 0)))
        ledger.tokens = max(ledger.tokens, int(consumed.get("tokens", 0)))
        ledger.cost = max(ledger.cost, float(consumed.get("cost", 0.0)))

    def _outcome_from_checkpoint(
        self, checkpoint: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        status = checkpoint.get("status")
        next_action = checkpoint.get("next_action")
        if status == STATUS_COMPLETED and next_action == ACTION_REUSE:
            payload = checkpoint.get("directions_payload")
            if not payload:
                return None  # 缺输出载体不得静默命中
            directions = parse_seed_scene_directions(json.dumps(payload, ensure_ascii=False))
            return {
                "status": STATUS_COMPLETED,
                "next_action": ACTION_REUSE,
                "directions": directions,
                "reason_code": "",
            }
        if status == STATUS_TERMINAL_FAILED:
            return {
                "status": STATUS_TERMINAL_FAILED,
                "next_action": next_action or ACTION_MANUAL_REVIEW,
                "reason_code": checkpoint.get("reason_code", ""),
            }
        if status == STATUS_RETRYABLE_FAILED and next_action == ACTION_DEGRADE_V1:
            return {
                "status": STATUS_RETRYABLE_FAILED,
                "next_action": ACTION_DEGRADE_V1,
                "reason_code": checkpoint.get("reason_code", ""),
            }
        # retryable_failed 且仍有纠错机会：继续执行（预算沿用，不重置）。
        return None

    def _budget_exceeded_outcome(
        self, segments: Sequence[Any], attempts: List[Dict[str, Any]]
    ) -> DirectorOutcome:
        if v1_fidelity_feasible(segments):
            return DirectorOutcome(
                status=STATUS_RETRYABLE_FAILED,
                next_action=ACTION_DEGRADE_V1,
                reason_code="director_budget_exceeded",
                attempts=tuple(attempts),
            )
        return DirectorOutcome(
            status=STATUS_TERMINAL_FAILED,
            next_action=ACTION_MANUAL_REVIEW,
            reason_code="director_budget_exceeded",
            attempts=tuple(attempts),
        )

    def _chapter_budget_allows(self, ledger: DirectorBudgetLedger | None) -> bool:
        if ledger is None:
            return True
        policy = self.policy
        return (
            ledger.calls < policy.max_calls_per_chapter
            and ledger.tokens < policy.max_tokens_per_chapter
            and ledger.cost < policy.max_cost_per_chapter
        )

    async def _attempt_call(self, messages: List[Dict[str, str]], *, attempt_number: int) -> Dict[str, Any]:
        prompt_chars = sum(len(message["content"]) for message in messages)
        attempt: Dict[str, Any] = {
            "attempt_number": attempt_number,
            "provider": self.provider,
            "model": self.model,
            "status": "error",
            "error_code": "",
            "tokens": 0,
            "cost_estimate": 0.0,
            "response": "",
        }
        try:
            response = await call_audiobook_llm_async(
                self.llm,
                messages=messages,
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                model=self.model or None,
                timeout_seconds=self.policy.timeout_seconds,
            )
        except asyncio.TimeoutError:
            attempt["status"] = "timeout"
            attempt["error_code"] = "timeout"
            attempt["tokens"] = prompt_chars // 2
            attempt["cost_estimate"] = round(attempt["tokens"] * self.cost_per_1k_tokens / 1000, 6)
            return attempt
        except DirectionParseError as exc:  # 防御：调用层不应抛出，保留错误码语义
            attempt["status"] = "parse_failed"
            attempt["error_code"] = exc.code
            return attempt
        except Exception as exc:
            attempt["status"] = "error"
            attempt["error_code"] = type(exc).__name__
            attempt["tokens"] = prompt_chars // 2
            attempt["cost_estimate"] = round(attempt["tokens"] * self.cost_per_1k_tokens / 1000, 6)
            return attempt
        response_text = str(response or "")
        tokens = (prompt_chars + len(response_text)) // 2
        attempt.update(
            {
                "status": "success",
                "tokens": tokens,
                "cost_estimate": round(tokens * self.cost_per_1k_tokens / 1000, 6),
                "response": response_text,
            }
        )
        return attempt

    @staticmethod
    def _apply_consumption(
        attempt: Dict[str, Any],
        chapter_consumed: DirectorBudgetLedger | None,
        job_consumed: DirectorBudgetLedger | None,
    ) -> None:
        for ledger in (chapter_consumed, job_consumed):
            if ledger is None:
                continue
            ledger.calls += 1
            ledger.tokens += int(attempt.get("tokens", 0))
            ledger.cost += float(attempt.get("cost_estimate", 0.0))

    def _parse_and_validate(
        self, response_text: str, segments: Sequence[Any]
    ) -> Tuple[Tuple[SeedSceneDirection, ...] | None, str]:
        try:
            directions = parse_seed_scene_directions(response_text)
        except DirectionParseError as exc:
            return None, exc.code
        result = validate_seed_scene_directions(directions, segments, policy=self.policy)
        if not result.ok:
            return None, result.errors[0].code
        return directions, ""

    def _failure_outcome(
        self,
        segments: Sequence[Any],
        signature: str,
        attempts: List[Dict[str, Any]],
        attempts_used: int,
        chapter_consumed: DirectorBudgetLedger | None,
        checkpoint_store: List[Dict[str, Any]],
        last_error_code: str,
    ) -> DirectorOutcome:
        if v1_fidelity_feasible(segments):
            status, next_action, reason_code = (
                STATUS_RETRYABLE_FAILED,
                ACTION_DEGRADE_V1,
                "director_degraded_to_v1",
            )
        else:
            status, next_action, reason_code = (
                STATUS_TERMINAL_FAILED,
                ACTION_MANUAL_REVIEW,
                "director_terminal_policy",
            )
        checkpoint_store.append(
            self._build_checkpoint(
                signature,
                status=status,
                next_action=next_action,
                attempts=attempts,
                attempts_used=attempts_used,
                chapter_consumed=chapter_consumed,
                validated_plan_hash=None,
                directions_payload=None,
                reason_code=reason_code,
                last_error_code=last_error_code,
            )
        )
        return DirectorOutcome(
            status=status,
            next_action=next_action,
            reason_code=reason_code,
            attempts=tuple(attempts),
        )

    def _build_checkpoint(
        self,
        signature: str,
        *,
        status: str,
        next_action: str,
        attempts: List[Dict[str, Any]],
        attempts_used: int,
        chapter_consumed: DirectorBudgetLedger | None,
        validated_plan_hash: str | None,
        directions_payload: dict | None,
        reason_code: str = "",
        last_error_code: str = "",
    ) -> Dict[str, Any]:
        consumed = chapter_consumed or DirectorBudgetLedger()
        return {
            "checkpoint_type": DIRECTOR_CHECKPOINT_TYPE,
            "schema_version": DIRECTOR_CHECKPOINT_SCHEMA_VERSION,
            "input_signature_hash": signature,
            "status": status,
            "next_action": next_action,
            "reason_code": reason_code,
            "last_error_code": last_error_code,
            "validated_plan_hash": validated_plan_hash,
            "attempts_used_in_batch": attempts_used,
            "consumed": {
                "calls": consumed.calls,
                "tokens": consumed.tokens,
                "cost": round(consumed.cost, 6),
            },
            "attempts": [dict(attempt) for attempt in attempts],
            "policy_version": self.policy.version,
            "policy_hash": self.policy.fingerprint(),
            "directions_payload": directions_payload,
        }

    @staticmethod
    def _segments_text(segments: Sequence[Any]) -> str:
        return "\n".join(
            f"{index}|{getattr(segment, 'speaker', '') or '旁白'}|{getattr(segment, 'text', '') or ''}"
            for index, segment in enumerate(segments)
        )
