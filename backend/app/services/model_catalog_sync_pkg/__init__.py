"""Model catalog sync service package."""

from app.services.model_catalog_sync_pkg._base import ModelCatalogSyncServiceBase
from app.services.model_catalog_sync_pkg._pricing_mixin import PricingMixin
from app.services.model_catalog_sync_pkg._verification_mixin import VerificationMixin
from app.services.model_catalog_sync_pkg._runtime_mixin import RuntimeMixin
from app.services.model_catalog_sync_pkg._source_verify_mixin import SourceVerifyMixin
from app.services.model_catalog_sync_pkg._spec_utils_mixin import SpecUtilsMixin
from app.services.model_catalog_sync_pkg._spec_extraction_mixin import SpecExtractionMixin
from app.services.model_catalog_sync_pkg._llm_verify_mixin import LlmVerifyMixin


class ModelCatalogSyncService(
    ModelCatalogSyncServiceBase,
    PricingMixin,
    VerificationMixin,
    RuntimeMixin,
    SourceVerifyMixin,
    SpecUtilsMixin,
    SpecExtractionMixin,
    LlmVerifyMixin,
):
    pass


from app.services.model_catalog_sync_pkg._constants import (
    CatalogSeed,
    SourceVerification,
    DetailedSpecExtraction,
    _LLM_VERIFICATION_TRIGGER,
    PRICING_VERIFICATION_CONFIG,
    VERIFIED_PRICING_DATA,
)
from app.services.model_catalog_sync_pkg._serialization import (
    serialize_model_catalog_entry,
)

model_catalog_sync_service = ModelCatalogSyncService()


def get_model_catalog_sync_service() -> ModelCatalogSyncService:
    return model_catalog_sync_service


__all__ = [
    "ModelCatalogSyncService",
    "CatalogSeed",
    "SourceVerification",
    "DetailedSpecExtraction",
    "get_model_catalog_sync_service",
    "serialize_model_catalog_entry",
]
