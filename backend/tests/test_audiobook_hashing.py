"""阶段 1 统一 hash 基础设施单元测试。

覆盖指导文档 §12.2 Hash API 职责分离与 §13.1 红线：
canonical_hash 稳定性（字段顺序、CRLF/LF、浮点量化、事件顺序敏感、
tuple/list 等价、contract 版本参与输入、拒绝二进制），
content_digest 稳定性（不随 contract version 变化、拒绝文本）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.hashing import (  # noqa: E402
    canonical_hash,
    content_digest,
)

_CONTRACT = {"contract_name": "test_contract", "contract_version": "1.0.0"}


class TestCanonicalHashStability:
    def test_field_order_does_not_change_hash(self) -> None:
        a = canonical_hash({"alpha": 1, "beta": 2}, **_CONTRACT)
        b = canonical_hash({"beta": 2, "alpha": 1}, **_CONTRACT)
        assert a == b

    def test_crlf_and_lf_text_hash_equal(self) -> None:
        a = canonical_hash({"text": "第一行\r\n第二行"}, **_CONTRACT)
        b = canonical_hash({"text": "第一行\n第二行"}, **_CONTRACT)
        assert a == b

    def test_float_quantization_equal(self) -> None:
        a = canonical_hash({"start": 1.2}, **_CONTRACT)
        b = canonical_hash({"start": 1.200}, **_CONTRACT)
        c = canonical_hash({"start": 1.2004}, **_CONTRACT)
        assert a == b == c
        d = canonical_hash({"start": 1.201}, **_CONTRACT)
        assert d != a

    def test_event_order_is_significant(self) -> None:
        events = [{"text": "甲"}, {"text": "乙"}]
        a = canonical_hash({"events": events}, **_CONTRACT)
        b = canonical_hash({"events": list(reversed(events))}, **_CONTRACT)
        assert a != b

    def test_tuple_and_list_equivalent(self) -> None:
        a = canonical_hash({"items": [1, 2, 3]}, **_CONTRACT)
        b = canonical_hash({"items": (1, 2, 3)}, **_CONTRACT)
        assert a == b

    def test_nested_structure_stability(self) -> None:
        payload = {
            "scenes": [
                {"scene_id": "s1", "windows": [{"start_s": 2.0, "end_s": 6.0}]},
            ],
            "meta": None,
            "flags": {"strict": True, "bounded": False},
        }
        a = canonical_hash(payload, **_CONTRACT)
        b = canonical_hash(payload, **_CONTRACT)
        assert a == b
        assert len(a) == 64

    def test_contract_version_participates_in_hash(self) -> None:
        a = canonical_hash({"x": 1}, contract_name="test_contract", contract_version="1.0.0")
        b = canonical_hash({"x": 1}, contract_name="test_contract", contract_version="2.0.0")
        assert a != b

    def test_contract_name_participates_in_hash(self) -> None:
        a = canonical_hash({"x": 1}, contract_name="contract_a", contract_version="1.0.0")
        b = canonical_hash({"x": 1}, contract_name="contract_b", contract_version="1.0.0")
        assert a != b

    def test_rejects_binary_payload(self) -> None:
        with pytest.raises(TypeError):
            canonical_hash({"audio": b"\x00\x01"}, **_CONTRACT)
        with pytest.raises(TypeError):
            canonical_hash(b"raw-bytes", **_CONTRACT)

    def test_requires_contract_arguments(self) -> None:
        with pytest.raises(TypeError):
            canonical_hash({"x": 1})  # type: ignore[call-arg]

    def test_none_bool_int_distinguished(self) -> None:
        values = [
            canonical_hash({"v": None}, **_CONTRACT),
            canonical_hash({"v": True}, **_CONTRACT),
            canonical_hash({"v": 1}, **_CONTRACT),
            canonical_hash({"v": "1"}, **_CONTRACT),
        ]
        assert len(set(values)) == 4


class TestContentDigestStability:
    def test_digest_of_same_bytes_is_stable(self) -> None:
        data = b"\x89PNG\r\n\x1a\nfake-audio-bytes"
        assert content_digest(data) == content_digest(bytes(data))

    def test_digest_is_sha256_hex(self) -> None:
        digest = content_digest(b"hello")
        assert len(digest) == 64
        assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_digest_independent_of_contract_version(self) -> None:
        # content_digest 的签名不接受任何 contract 参数，字节完整性与合同版本无关。
        data = b"audio-bytes"
        assert content_digest(data) == content_digest(data)
        with pytest.raises(TypeError):
            content_digest(data, contract_version="2.0.0")  # type: ignore[call-arg]

    def test_rejects_text_payload(self) -> None:
        with pytest.raises(TypeError):
            content_digest("not-bytes")  # type: ignore[arg-type]
