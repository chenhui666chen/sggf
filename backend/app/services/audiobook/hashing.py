"""统一 hash 基础设施（指导文档 §12.2 Hash API 职责分离）。

两个 helper 职责严格分离，不得混用：

- ``canonical_hash(value, *, contract_name, contract_version)``：结构化对象的
  语义身份。输入包含 contract_name/contract_version，合同版本变化即语义签名变化。
  用于输入签名、语义合同、policy/schema 等结构化身份；拒绝二进制内容。
- ``content_digest(data)``：原始字节 SHA-256，不随任何签名合同版本变化。
  用于音频文件、reference、持久化 artifact 的字节完整性；拒绝文本。

规范化规则（§12.2 最低规则）：UTF-8 + NFC；映射按 key 排序；tuple 与 list
等价；有顺序语义的数组保持顺序；浮点统一量化为固定三位小数（1.2 与 1.200
同 hash）；文本换行 CRLF/LF 归一为 LF。模块不得自行实现"稳定 hash"，
一律通过本模块。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Mapping

__all__ = ["canonical_hash", "content_digest"]


def canonical_hash(value: Any, *, contract_name: str, contract_version: str) -> str:
    """计算结构化对象的版本化语义身份哈希（SHA-256 hex）。

    contract_name/contract_version 参与哈希输入，避免跨合同碰撞。
    二进制内容一律走 ``content_digest``，传入 bytes 抛 TypeError。
    """
    if not isinstance(contract_name, str) or not contract_name.strip():
        raise ValueError("contract_name must be a non-empty string")
    if not isinstance(contract_version, str) or not contract_version.strip():
        raise ValueError("contract_version must be a non-empty string")
    header = f"{contract_name}@{contract_version}\n"
    payload = header + _canonical_form(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_digest(data: bytes) -> str:
    """计算原始字节的 SHA-256 hex；不随签名合同版本变化。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("content_digest only accepts bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def _canonical_form(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"i:{value}"
    if isinstance(value, float):
        return f"f:{round(value, 3):.3f}"
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
        return f"s:{json.dumps(normalized, ensure_ascii=False)}"
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("binary content must use content_digest, not canonical_hash")
    if isinstance(value, Mapping):
        items = sorted(
            (_canonical_key(key), _canonical_form(item)) for key, item in value.items()
        )
        return "{" + ",".join(f"{key}=>{item}" for key, item in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_form(item) for item in value) + "]"
    raise TypeError(f"unsupported type for canonical_hash: {type(value).__name__}")


def _canonical_key(key: Any) -> str:
    if not isinstance(key, str):
        raise TypeError(f"mapping keys must be strings, got: {type(key).__name__}")
    normalized = unicodedata.normalize("NFC", key).replace("\r\n", "\n")
    return json.dumps(normalized, ensure_ascii=False)
