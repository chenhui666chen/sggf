"""scene_quality：Omni 影子评审合同与策略（指导文档 §10）。"""

from .auto_recovery import (
    AutoRecoveryDecision,
    RECOVERY_DECISION_REASONS,
    decide_auto_recovery,
)
from .calibration import (
    AUTO_RETRY_FINDING_CODES,
    CALIBRATION_MIN_NEGATIVE_SAMPLES,
    CALIBRATION_MIN_POSITIVE_SAMPLES,
    CALIBRATION_MIN_PRECISION,
    CALIBRATION_MIN_RECALL,
    CALIBRATION_THRESHOLDS_VERSION,
    FindingCalibration,
    calibration_set_fingerprint,
)
from .checkpoint_signature import OmniReviewCheckpointSignature
from .expectation_contract import (
    EXPECTATION_REQUIRED_PARTS,
    build_voice_binding_summary,
    omni_expectation_contract_hash,
)
from .qwen_omni_reviewer import (
    DEFAULT_OMNI_MODEL_ID,
    OMNI_REVIEW_PROMPT_HASH,
    OMNI_REVIEW_PROMPT_VERSION,
    OMNI_REVIEW_SCHEMA_HASH,
    OmniReviewOutcome,
    SceneAudioSemanticReviewer,
)
from .seam_review import (
    DEFAULT_SEAM_MAX_WINDOW_MS,
    DEFAULT_SEAM_MIN_WINDOW_MS,
    SeamWindows,
    build_seam_review_windows,
)
from .semantic_models import (
    DIMENSION_STATUSES,
    FINDING_SEVERITIES,
    FINDING_SUGGESTED_ACTIONS,
    RECOMMENDED_ACTIONS,
    REVIEW_DIMENSIONS,
    SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION,
    SemanticFinding,
    SemanticReviewResult,
)
from .semantic_policy import (
    DEFAULT_SEMANTIC_REVIEW_POLICY,
    REVIEW_ERROR_KINDS,
    SemanticReviewPolicy,
    classify_review_error,
)
from .semantic_quality_policy import (
    DEFAULT_SEMANTIC_QUALITY_POLICY,
    SemanticQualityPolicy,
)

__all__ = [
    "AUTO_RETRY_FINDING_CODES",
    "AutoRecoveryDecision",
    "CALIBRATION_MIN_NEGATIVE_SAMPLES",
    "CALIBRATION_MIN_POSITIVE_SAMPLES",
    "CALIBRATION_MIN_PRECISION",
    "CALIBRATION_MIN_RECALL",
    "CALIBRATION_THRESHOLDS_VERSION",
    "DEFAULT_OMNI_MODEL_ID",
    "DEFAULT_SEAM_MAX_WINDOW_MS",
    "DEFAULT_SEAM_MIN_WINDOW_MS",
    "DEFAULT_SEMANTIC_QUALITY_POLICY",
    "DEFAULT_SEMANTIC_REVIEW_POLICY",
    "DIMENSION_STATUSES",
    "EXPECTATION_REQUIRED_PARTS",
    "FINDING_SEVERITIES",
    "FINDING_SUGGESTED_ACTIONS",
    "FindingCalibration",
    "OMNI_REVIEW_PROMPT_HASH",
    "OMNI_REVIEW_PROMPT_VERSION",
    "OMNI_REVIEW_SCHEMA_HASH",
    "OmniReviewCheckpointSignature",
    "OmniReviewOutcome",
    "RECOMMENDED_ACTIONS",
    "RECOVERY_DECISION_REASONS",
    "REVIEW_DIMENSIONS",
    "REVIEW_ERROR_KINDS",
    "SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION",
    "SceneAudioSemanticReviewer",
    "SeamWindows",
    "SemanticFinding",
    "SemanticQualityPolicy",
    "SemanticReviewPolicy",
    "SemanticReviewResult",
    "build_seam_review_windows",
    "build_voice_binding_summary",
    "calibration_set_fingerprint",
    "classify_review_error",
    "decide_auto_recovery",
    "omni_expectation_contract_hash",
]
