"""Omni 影子评审真实调用层：SceneAudioSemanticReviewer（指导文档 §10.1/§10.7）。

默认模型 ``qwen3.5-omni-flash``，不替代 ASR，不塞进既有
``_final_audio_review()``。影子阶段语义在调用层闭合：

- policy 关闭/未开放模式 → skipped，零调用；
- 章节预算（场景/接缝次数上限）超限 → budget_exceeded
  recorded_error，零调用；begin_chapter 按章节重置；
- 音频时长超过 policy 上限 → preprocessing_failed，提交前拦截；
- OmniReviewCheckpointSignature 命中缓存 → 零调用复用评审结果；
  音频/期望合同/策略等任一输入变化（签名变化）自动重新评审；
- 超时/provider 异常/schema 非法 → recorded_error：只记录、
  不阻断、不重试、不改账单；
- Prompt 与输出 Schema 版本化冻结，哈希确定性派生并进入签名。

omni_client 鸭子合同：``async review_audio(*, prompt, audio_path,
model) -> str``，返回评审 JSON 文本。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from ..hashing import canonical_hash
from .checkpoint_signature import OmniReviewCheckpointSignature
from .expectation_contract import (
    build_voice_binding_summary,
    omni_expectation_contract_hash,
)
from .semantic_models import (
    RECOMMENDED_ACTIONS,
    REVIEW_DIMENSIONS,
    SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION,
    SemanticFinding,
    SemanticReviewResult,
)
from .semantic_policy import DEFAULT_SEMANTIC_REVIEW_POLICY, SemanticReviewPolicy

logger = logging.getLogger(__name__)

DEFAULT_OMNI_MODEL_ID = "qwen3.5-omni-flash"

OMNI_REVIEW_PROMPT_VERSION = "omni-review-prompt-1.0.0"

_OMNI_REVIEW_PROMPT_TEMPLATE = f"""你是有声书场景音频的语义评审员（{OMNI_REVIEW_PROMPT_VERSION}）。
只依据听到的音频内容与下方期望合同评审，不得猜测合同之外的事实。
对以下十个维度逐一给出 pass / fail / not_assessable：
dialogue_fidelity（台词逐字保真）、speaker_assignment（说话人归属）、
speaker_separation（说话人区分）、performance（表演贴合）、
vocalizations（非语言人声）、sound_events（声音事件）、music（配乐）、
ambient（环境声）、acoustic_space（声学空间）、mix_balance（混音平衡）。
任何失败必须给出 finding：code、severity（minor/major/critical）、
confidence（0 到 1）、start_ms/end_ms 时间区间、expected（期望）、
observed（观察结果）、suggested_action（accept/manual_review/retry_once/not_assessable）。
只输出严格 JSON，字段为：passed（bool）、confidence（0 到 1）、
dimensions（十个维度到状态的映射）、findings（数组）、
recommended_action（{" / ".join(RECOMMENDED_ACTIONS)}）。
schema 版本：{SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION}。

期望合同：
{{expectation_contract}}
"""

OMNI_REVIEW_PROMPT_HASH = hashlib.sha256(
    _OMNI_REVIEW_PROMPT_TEMPLATE.encode("utf-8")
).hexdigest()

_SCHEMA_FINGERPRINT_CONTRACT = "scene_semantic_review_schema"
OMNI_REVIEW_SCHEMA_HASH = canonical_hash(
    {
        "schema_version": SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION,
        "dimensions": list(REVIEW_DIMENSIONS),
        "recommended_actions": list(RECOMMENDED_ACTIONS),
        "prompt_version": OMNI_REVIEW_PROMPT_VERSION,
    },
    contract_name=_SCHEMA_FINGERPRINT_CONTRACT,
    contract_version="1.0.0",
)

_RESULT_KEYS = frozenset(
    {"passed", "confidence", "dimensions", "findings", "recommended_action"}
)
_FINDING_KEYS = frozenset(
    {
        "code",
        "severity",
        "confidence",
        "start_ms",
        "end_ms",
        "expected",
        "observed",
        "suggested_action",
    }
)

_OUTCOME_REVIEWED = "reviewed"
_OUTCOME_RECORDED_ERROR = "recorded_error"
_OUTCOME_SKIPPED = "skipped"


@dataclass(frozen=True)
class OmniReviewOutcome:
    """单次评审处置结果：影子语义下永远不阻断章节生产。"""

    status: str
    signature_hash: str
    result: SemanticReviewResult | None = None
    error_kind: str | None = None
    reused: bool = False


class SceneAudioSemanticReviewer:
    """场景/接缝级 Omni 影子评审编排（预算、缓存、错误分类）。"""

    def __init__(
        self,
        omni_client: Any,
        *,
        model_id: str = DEFAULT_OMNI_MODEL_ID,
        policy: SemanticReviewPolicy = DEFAULT_SEMANTIC_REVIEW_POLICY,
        checkpoints: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        if omni_client is None or not hasattr(omni_client, "review_audio"):
            raise ValueError("omni_client must provide an async review_audio method")
        self.omni_client = omni_client
        self.model_id = str(model_id or DEFAULT_OMNI_MODEL_ID)
        self.policy = policy
        self.checkpoints = checkpoints if checkpoints is not None else {}
        self._chapter_scene_reviews = 0
        self._chapter_seam_reviews = 0

    def begin_chapter(self) -> None:
        """章节边界重置评审预算（跨章节不累计）。"""
        self._chapter_scene_reviews = 0
        self._chapter_seam_reviews = 0

    async def review_scene(
        self,
        *,
        signature: OmniReviewCheckpointSignature,
        audio_path: Union[str, Path],
        audio_duration_s: float,
        expectation_contract_text: str = "",
    ) -> OmniReviewOutcome:
        """场景级影子评审；任何失败都落 recorded_error，不抛异常。"""
        if signature.review_scope != "scene":
            raise ValueError("review_scene requires a scene-scope signature")
        return await self._review(
            signature=signature,
            audio_path=audio_path,
            audio_duration_s=audio_duration_s,
            expectation_contract_text=expectation_contract_text,
            scope="scene",
        )

    async def _review(
        self,
        *,
        signature: OmniReviewCheckpointSignature,
        audio_path: Union[str, Path],
        audio_duration_s: float,
        expectation_contract_text: str,
        scope: str,
    ) -> OmniReviewOutcome:
        signature_hash = signature.signature_hash()
        if not self.policy.should_review_scene:
            return OmniReviewOutcome(status=_OUTCOME_SKIPPED, signature_hash=signature_hash)
        if self._budget_exhausted(scope):
            return self._record_error(signature_hash, "budget_exceeded")
        if float(audio_duration_s or 0.0) > self.policy.max_audio_duration_s:
            return self._record_error(signature_hash, "preprocessing_failed")

        cached = self.checkpoints.get(signature_hash)
        if isinstance(cached, Mapping) and cached.get("result_payload"):
            try:
                result = _parse_review_payload(str(cached["result_payload"]))
            except ValueError:
                result = None
            if result is not None:
                return OmniReviewOutcome(
                    status=_OUTCOME_REVIEWED,
                    signature_hash=signature_hash,
                    result=result,
                    reused=True,
                )

        self._consume_budget(scope)
        prompt = _OMNI_REVIEW_PROMPT_TEMPLATE.replace(
            "{expectation_contract}",
            expectation_contract_text or "（无附加期望合同）",
        )
        try:
            raw = await asyncio.wait_for(
                self.omni_client.review_audio(
                    prompt=prompt,
                    audio_path=str(audio_path),
                    model=self.model_id,
                ),
                timeout=self.policy.request_timeout_s,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return self._record_error(signature_hash, "timeout")
        except Exception as exc:
            logger.warning(
                "Omni 影子评审 provider 异常（只记录不阻断）: scope=%s error=%s",
                scope,
                exc,
            )
            return self._record_error(signature_hash, "provider_error")

        try:
            result = _parse_review_payload(str(raw))
        except ValueError as exc:
            logger.warning(
                "Omni 影子评审输出 schema 非法（只记录不阻断）: scope=%s error=%s",
                scope,
                exc,
            )
            return self._record_error(signature_hash, "schema_invalid")

        self.checkpoints[signature_hash] = {
            "signature_hash": signature_hash,
            "result_payload": json.dumps(
                _serialize_review_result(result), ensure_ascii=False
            ),
            "result_hash": result.result_hash,
            "model_id": self.model_id,
        }
        return OmniReviewOutcome(
            status=_OUTCOME_REVIEWED,
            signature_hash=signature_hash,
            result=result,
        )

    def _budget_exhausted(self, scope: str) -> bool:
        if scope == "seam":
            return self._chapter_seam_reviews >= self.policy.max_seam_reviews_per_chapter
        return self._chapter_scene_reviews >= self.policy.max_scene_reviews_per_chapter

    def _consume_budget(self, scope: str) -> None:
        if scope == "seam":
            self._chapter_seam_reviews += 1
        else:
            self._chapter_scene_reviews += 1

    def _record_error(self, signature_hash: str, error_kind: str) -> OmniReviewOutcome:
        return OmniReviewOutcome(
            status=_OUTCOME_RECORDED_ERROR,
            signature_hash=signature_hash,
            error_kind=error_kind,
        )


def _parse_review_payload(raw: str) -> SemanticReviewResult:
    """严格解析评审 JSON：未知字段拒绝，校验交给合同层模型。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"review payload is not valid json: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("review payload must be a json object")
    unknown = set(payload) - _RESULT_KEYS
    if unknown:
        raise ValueError(f"unknown review payload fields: {sorted(unknown)}")
    missing = _RESULT_KEYS - set(payload)
    if missing:
        raise ValueError(f"missing review payload fields: {sorted(missing)}")
    dimensions = payload["dimensions"]
    if not isinstance(dimensions, Mapping):
        raise ValueError("review dimensions must be a mapping")
    findings_payload = payload["findings"]
    if not isinstance(findings_payload, list):
        raise ValueError("review findings must be a list")
    findings = []
    for item in findings_payload:
        if not isinstance(item, Mapping):
            raise ValueError("finding must be a json object")
        unknown_finding = set(item) - _FINDING_KEYS
        if unknown_finding:
            raise ValueError(
                f"unknown finding fields: {sorted(unknown_finding)}"
            )
        findings.append(SemanticFinding(**dict(item)))
    return SemanticReviewResult(
        passed=bool(payload["passed"]),
        confidence=float(payload["confidence"]),
        dimensions={str(key): str(value) for key, value in dimensions.items()},
        findings=tuple(findings),
        recommended_action=str(payload["recommended_action"]),
    )


def _serialize_review_result(result: SemanticReviewResult) -> Dict[str, Any]:
    return {
        "passed": bool(result.passed),
        "confidence": float(result.confidence),
        "dimensions": dict(result.dimensions),
        "findings": [
            dict(finding.canonical_payload()) for finding in result.findings
        ],
        "recommended_action": result.recommended_action,
    }


_DEFAULT_AUDIO_PREPROCESSING_HASH = hashlib.sha256(
    b"default-audio-preprocessing-v1"
).hexdigest()


def build_omni_scene_signature(
    *,
    audio_artifact_hash: str,
    audio_duration_s: float,
    expected_text: str,
    speaker_names: Sequence[str],
    expected_vocalizations: Sequence[str] = (),
    chapter_facts: Optional[Mapping[str, str]] = None,
    model_id: str = DEFAULT_OMNI_MODEL_ID,
    policy: Optional[SemanticReviewPolicy] = None,
) -> OmniReviewCheckpointSignature:
    """从场景计划数据构造场景级 Omni 评审签名（mixin 集成用）。

    影子阶段构造最简可用期望合同与绑定摘要：所有无输入字段
    使用空向量占位（"(none)"）。此签名只参与评审缓存键，
    不影响输出质量。
    """
    effective_policy = policy or DEFAULT_SEMANTIC_REVIEW_POLICY
    duration_ms = max(0, int(float(audio_duration_s or 0.0) * 1000))

    # 最简期望合同：只使用 mixin 可见的输入。
    summary = expected_text.strip() or "（无台词）"
    bindings = [{"speaker": s} for s in speaker_names]
    expectation = {
        "scene_context": dict(chapter_facts) if chapter_facts else {},
        "speech": [
            {"text": summary, "speakers": list(speaker_names)},
        ],
        "vocalizations": list(expected_vocalizations),
        "sound_events": [],
        "music_ambient": [],
        "acoustic_treatment": [],
        "performance_expectations": [],
        "timeline_windows": [],
        "voice_binding_summary": bindings,
        "carry_state": {},
        "target_duration_s": audio_duration_s,
    }
    expectation_hash = omni_expectation_contract_hash(expectation)
    binding_summary_hash = build_voice_binding_summary(bindings)

    return OmniReviewCheckpointSignature(
        audio_artifact_hash=audio_artifact_hash,
        review_scope="scene",
        audio_window_start_ms=0,
        audio_window_end_ms=duration_ms,
        omni_expectation_contract_hash=expectation_hash,
        voice_binding_summary_hash=binding_summary_hash,
        omni_model_id=model_id,
        omni_prompt_hash=OMNI_REVIEW_PROMPT_HASH,
        omni_schema_hash=OMNI_REVIEW_SCHEMA_HASH,
        audio_preprocessing_hash=_DEFAULT_AUDIO_PREPROCESSING_HASH,
        semantic_policy_hash=effective_policy.fingerprint(),
    )


__all__ = [
    "DEFAULT_OMNI_MODEL_ID",
    "OMNI_REVIEW_PROMPT_HASH",
    "OMNI_REVIEW_PROMPT_VERSION",
    "OMNI_REVIEW_SCHEMA_HASH",
    "OmniReviewOutcome",
    "SceneAudioSemanticReviewer",
    "build_omni_scene_signature",
]
