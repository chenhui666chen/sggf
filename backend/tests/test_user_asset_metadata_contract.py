import json
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.schemas.user_asset import (
    USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
    USER_ASSET_LOCAL_PERSIST_LEVELS,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
    USER_ASSET_LOCAL_STORAGE_DRIVERS,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
    USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
    UserAssetMetadata,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH
CONTRACT_DOC_PATH = REPO_ROOT / USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH
CONTRACT_GENERATOR_SCRIPT = "scripts/generate_user_asset_local_storage_contract.py"
FRONTEND_GENERATED_CONTRACT_PATH = "frontend/src/contracts/userAssetLocalStorageContract.generated.ts"
BACKEND_GENERATED_CONTRACT_PATH = "backend/app/schemas/user_asset_local_storage_contract_generated.py"


def _load_contract_document() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _extract_string_enum_values(property_schema: dict) -> list[str]:
    raw_values = property_schema.get("enum") if isinstance(property_schema, dict) else None
    if not isinstance(raw_values, list):
        return []
    return [value for value in raw_values if isinstance(value, str)]


def _extract_string_max_length(property_schema: dict) -> int | None:
    if not isinstance(property_schema, dict):
        return None

    direct_max_length = property_schema.get("maxLength")
    if isinstance(direct_max_length, int):
        return direct_max_length

    any_of = property_schema.get("anyOf")
    if not isinstance(any_of, list):
        return None

    for item in any_of:
        if isinstance(item, dict) and item.get("type") == "string" and isinstance(item.get("maxLength"), int):
            return item["maxLength"]

    return None


def test_user_asset_metadata_contract_document_matches_backend_allowed_values():
    contract = _load_contract_document()
    properties = contract.get("properties") if isinstance(contract.get("properties"), dict) else {}

    driver_enum = _extract_string_enum_values(properties.get("local_storage_driver", {}))
    persist_enum = _extract_string_enum_values(properties.get("local_persist_level", {}))

    assert contract.get("$id") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID
    assert contract.get("x-contract-version") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION
    assert contract.get("x-contract-doc") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH
    assert contract.get("x-contract-owner") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER
    assert contract.get("additionalProperties") is True
    assert tuple(driver_enum) == USER_ASSET_LOCAL_STORAGE_DRIVERS
    assert tuple(persist_enum) == USER_ASSET_LOCAL_PERSIST_LEVELS
    assert properties.get("local_storage_path", {}).get("maxLength") == USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH
    assert (
        properties.get("external_relative_path", {}).get("maxLength")
        == USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH
    )


def test_user_asset_metadata_model_schema_exposes_shared_contract_annotations():
    contract = _load_contract_document()
    contract_properties = contract.get("properties") if isinstance(contract.get("properties"), dict) else {}
    schema = UserAssetMetadata.model_json_schema()
    schema_properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}

    assert schema.get("$id") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID
    assert schema.get("x-contract-path") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH
    assert schema.get("x-contract-version") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION
    assert schema.get("x-contract-doc") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH
    assert schema.get("x-contract-owner") == USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER
    assert schema.get("additionalProperties") is True
    driver_schema = schema_properties.get("local_storage_driver", {})
    persist_schema = schema_properties.get("local_persist_level", {})
    driver_model_enum = _extract_string_enum_values(driver_schema) or [
        value
        for item in driver_schema.get("anyOf", [])
        if isinstance(item, dict)
        for value in _extract_string_enum_values(item)
    ]
    persist_model_enum = _extract_string_enum_values(persist_schema) or [
        value
        for item in persist_schema.get("anyOf", [])
        if isinstance(item, dict)
        for value in _extract_string_enum_values(item)
    ]
    contract_driver_reserved = contract_properties.get("local_storage_driver", {}).get(
        "x-reserved-values", []
    )
    contract_persist_reserved = contract_properties.get("local_persist_level", {}).get(
        "x-reserved-values", []
    )
    contract_driver_active = [
        value
        for value in _extract_string_enum_values(contract_properties.get("local_storage_driver", {}))
        if value not in contract_driver_reserved
    ]
    contract_persist_active = [
        value
        for value in _extract_string_enum_values(contract_properties.get("local_persist_level", {}))
        if value not in contract_persist_reserved
    ]
    assert sorted(driver_model_enum) == sorted(contract_driver_active)
    assert sorted(persist_model_enum) == sorted(contract_persist_active)
    assert (
        schema_properties.get("local_storage_driver", {}).get("description")
        == contract_properties.get("local_storage_driver", {}).get("description")
    )
    assert (
        _extract_string_max_length(schema_properties.get("local_storage_path", {}))
        == USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH
    )
    assert (
        _extract_string_max_length(schema_properties.get("external_relative_path", {}))
        == USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH
    )


def test_user_asset_metadata_contract_documentation_exists_and_matches_snapshot():
    content = CONTRACT_DOC_PATH.read_text(encoding="utf-8")

    assert CONTRACT_DOC_PATH.is_file()
    assert USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID in content
    assert USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION in content
    assert USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH in content
    assert USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH in content
    assert CONTRACT_GENERATOR_SCRIPT in content
    assert FRONTEND_GENERATED_CONTRACT_PATH in content
    assert BACKEND_GENERATED_CONTRACT_PATH in content


def test_user_asset_metadata_model_normalizes_known_local_storage_fields_and_preserves_extra_keys():
    metadata = UserAssetMetadata.model_validate(
        {
            "local_storage_driver": "OPFS",
            "local_storage_path": " local_asset_vault/image/demo ",
            "local_persist_level": "PERSISTENT_REQUESTED",
            "external_relative_path": " exports/demo.png ",
            "extra_flag": True,
        }
    )

    dumped = metadata.model_dump(mode="python")

    assert dumped["local_storage_driver"] == "opfs"
    assert dumped["local_storage_path"] == "local_asset_vault/image/demo"
    assert dumped["local_persist_level"] == "persistent_requested"
    assert dumped["external_relative_path"] == "exports/demo.png"
    assert dumped["extra_flag"] is True


def test_user_asset_metadata_model_accepts_external_directory_and_user_directory():
    metadata = UserAssetMetadata.model_validate(
        {
            "local_storage_driver": "EXTERNAL_DIRECTORY",
            "local_persist_level": "USER_DIRECTORY",
            "external_relative_path": " exports/demo.mp3 ",
        }
    )

    dumped = metadata.model_dump(mode="python")

    assert dumped["local_storage_driver"] == "external_directory"
    assert dumped["local_persist_level"] == "user_directory"
    assert dumped["external_relative_path"] == "exports/demo.mp3"


def test_user_asset_metadata_model_rejects_oversize_local_storage_path():
    oversized = "a" * (USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH + 1)
    with pytest.raises(ValueError) as exc_info:
        UserAssetMetadata.model_validate({"local_storage_path": oversized})
    assert "超出上限" in str(exc_info.value)


def test_user_asset_metadata_model_rejects_oversize_external_relative_path():
    oversized = "b" * (USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH + 1)
    with pytest.raises(ValueError) as exc_info:
        UserAssetMetadata.model_validate({"external_relative_path": oversized})
    assert "超出上限" in str(exc_info.value)


def test_contract_generator_check_flag_detects_drift(tmp_path, monkeypatch):
    import subprocess

    generator = REPO_ROOT / CONTRACT_GENERATOR_SCRIPT
    target = REPO_ROOT / BACKEND_GENERATED_CONTRACT_PATH
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + "\n# drift marker\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(generator), "--check"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert "派生产物与 schema 不一致" in completed.stderr
    finally:
        target.write_text(original, encoding="utf-8")
