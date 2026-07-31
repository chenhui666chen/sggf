"""
实验隐私模块（设计文档 §10）

在线实验中用户原文的全生命周期管控，包含两部分：
1. ExperimentConsentRegistry —— 授权位：默认拒绝，仅 opt-in 用户可进入 shadow 实验；
   匿名化用户标识 ≠ 取得"用于产品优化"的授权，授权位独立存储
2. PayloadVault —— 原文短期载荷保险库：
   - 队列/任务表只传 opaque payload reference，不直接携带原文
   - 载荷 Fernet 加密落盘，索引不含文本
   - 严格 TTL（payload_expires_at），过期即清；处理完成调用方立即 delete
   - 撤回授权时按主体批量删除（delete_by_subject）
   - 日志纪律：本模块任何日志不输出文本内容

安全约束：加密密钥缺失时失败关闭（拒绝构造），禁止明文兜底落盘。
"""
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: dict) -> None:
    """临时文件 + os.replace 原子写，避免写一半进程退出留下损坏文件"""
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("隐私存储索引损坏，按空索引处理: %s", path.name)
        return {}


class ExperimentConsentRegistry:
    """实验授权位注册表（opt-in，默认拒绝）"""

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution" / "experiment_privacy")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.consent_file = self.storage_dir / "experiment_consent.json"

    def has_consent(self, subject_id: str) -> bool:
        """默认拒绝：未记录或已撤回均视为无授权"""
        return _load_json(self.consent_file).get(subject_id, {}).get("granted", False)

    def grant(self, subject_id: str) -> None:
        data = _load_json(self.consent_file)
        data[subject_id] = {"granted": True, "updated_at": time.time()}
        _atomic_write_json(self.consent_file, data)

    def revoke(self, subject_id: str) -> None:
        data = _load_json(self.consent_file)
        data[subject_id] = {"granted": False, "updated_at": time.time()}
        _atomic_write_json(self.consent_file, data)


class PayloadVault:
    """原文短期载荷保险库（加密落盘 + TTL + opaque reference）"""

    DEFAULT_TTL_SECONDS = 24 * 3600

    def __init__(
        self,
        encryption_key: str,
        storage_dir: Optional[str] = None,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        if not encryption_key:
            raise ValueError("PayloadVault 需要非空加密密钥（失败关闭，禁止明文落盘）")
        # 任意字符串密钥 → SHA-256 派生 32 字节 → Fernet key
        derived = hashlib.sha256(encryption_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution" / "experiment_payloads")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "payload_index.json"
        self.default_ttl_seconds = default_ttl_seconds

    # ---------- 内部 ----------

    def _payload_path(self, ref: str) -> Path:
        return self.storage_dir / f"{ref}.bin"

    def _load_index(self) -> Dict[str, dict]:
        return _load_json(self.index_file)

    def _save_index(self, index: Dict[str, dict]) -> None:
        _atomic_write_json(self.index_file, index)

    def _remove(self, ref: str, index: Dict[str, dict]) -> None:
        """从磁盘与索引中移除载荷（索引由调用方保存）"""
        self._payload_path(ref).unlink(missing_ok=True)
        index.pop(ref, None)

    # ---------- 对外接口 ----------

    def put(self, subject_id: str, text: str, ttl_seconds: Optional[int] = None) -> str:
        """
        存入原文，返回 opaque reference（不含原文与主体信息）。

        队列/任务表只允许携带该引用，不允许携带原文。
        """
        ref = uuid.uuid4().hex
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        encrypted = self._fernet.encrypt(text.encode("utf-8"))
        self._payload_path(ref).write_bytes(encrypted)

        index = self._load_index()
        index[ref] = {"subject_id": subject_id, "expires_at": time.time() + ttl}
        self._save_index(index)
        logger.debug("载荷已存入: ref=%s, 长度=%d 字符", ref, len(text))
        return ref

    def get(self, ref: str) -> Optional[str]:
        """读取原文；引用不存在或已过期返回 None（过期即清除）"""
        index = self._load_index()
        meta = index.get(ref)
        if meta is None:
            return None
        if time.time() >= meta["expires_at"]:
            self._remove(ref, index)
            self._save_index(index)
            logger.debug("载荷已过期并清除: ref=%s", ref)
            return None

        path = self._payload_path(ref)
        if not path.exists():
            self._remove(ref, index)
            self._save_index(index)
            return None
        try:
            return self._fernet.decrypt(path.read_bytes()).decode("utf-8")
        except InvalidToken:
            logger.warning("载荷解密失败（密钥不匹配或数据损坏）: ref=%s", ref)
            return None

    def delete(self, ref: str) -> bool:
        """处理完成后立即删除；返回是否实际删除"""
        index = self._load_index()
        if ref not in index:
            return False
        self._remove(ref, index)
        self._save_index(index)
        logger.debug("载荷已删除: ref=%s", ref)
        return True

    def purge_expired(self) -> int:
        """清理所有过期载荷（worker 失败后的 TTL 兜底），返回清理数量"""
        index = self._load_index()
        now = time.time()
        expired = [ref for ref, meta in index.items() if now >= meta["expires_at"]]
        for ref in expired:
            self._remove(ref, index)
        if expired:
            self._save_index(index)
            logger.info("TTL 兜底清理过期载荷: %d 个", len(expired))
        return len(expired)

    def delete_by_subject(self, subject_id: str) -> int:
        """用户撤回授权时按主体批量删除，返回删除数量"""
        index = self._load_index()
        targets = [ref for ref, meta in index.items() if meta.get("subject_id") == subject_id]
        for ref in targets:
            self._remove(ref, index)
        if targets:
            self._save_index(index)
            logger.info("按主体删除载荷: %d 个", len(targets))
        return len(targets)

