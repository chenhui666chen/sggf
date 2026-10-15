# -*- coding: utf-8 -*-
"""素材托管：把本地图/视频素材投递到公共读 OSS，换取供应商可拉取的公网 URL。"""
from .asset_store import AssetError, AssetStore, StagedAsset, build_object_key, validate_job_id
from .oss_client import OssClient, OssConfig, OssError
from .provider_assets import (
    AssetHttpClient,
    AssetInput,
    AssetRegistrationError,
    ProviderAssetRegistrar,
    ProviderEndpoint,
    RawResponse,
    RegisteredAsset,
    UrllibAssetHttpClient,
)

__all__ = [
    "AssetError",
    "AssetStore",
    "StagedAsset",
    "build_object_key",
    "validate_job_id",
    "OssClient",
    "OssConfig",
    "OssError",
    "AssetHttpClient",
    "AssetInput",
    "AssetRegistrationError",
    "ProviderAssetRegistrar",
    "ProviderEndpoint",
    "RawResponse",
    "RegisteredAsset",
    "UrllibAssetHttpClient",
]
