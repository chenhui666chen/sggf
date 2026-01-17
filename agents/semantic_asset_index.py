from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


_TOKEN_RE = re.compile(r"[\w一-鿿]+", flags=re.UNICODE)


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float(default)


def _clamp_text(text: str, *, max_chars: int) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    if max_chars > 0 and len(s) > int(max_chars):
        return s[: int(max_chars)].rstrip()
    return s


def _tokenize(text: str) -> List[str]:
    s = str(text or "").lower()
    if not s:
        return []
    return [t for t in _TOKEN_RE.findall(s) if t]


def embed_text_local_hash(text: str, *, dim: int) -> np.ndarray:
    """
    本地“哈希 embedding”（无网络依赖）：
    - 用 token hashing trick 构造稀疏向量，再做 L2 归一化
    - 语义质量不如真实 embedding，但足以支撑“同项目二次生成”的粗粒度复用/锚点检索
    """
    dim = max(16, int(dim))
    vec = np.zeros(dim, dtype=np.float32)
    for tok in _tokenize(text):
        h = hashlib.md5(tok.encode("utf-8"), usedforsecurity=False).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        vec[idx] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class SemanticHit:
    score: float
    path: Path
    kind: str
    meta: Dict[str, Any]


class SemanticAssetIndex:
    """
    DreamWeaver 语义检索索引（SQLite + 本地 embedding）：
    - 输入：一组（图像路径 + 文本描述/Prompt + meta）
    - 查询：给定文本，返回最相似的历史帧/素材库图，用于锚点/参考图候选

    设计原则（KISS/YAGNI）：
    - 默认无网络依赖（local_hash embedding）
    - 持久化用 SQLite，避免 JSON 文件并发写入问题
    - 仅提供必要的 add/query/trim 能力
    """

    def __init__(
        self,
        *,
        project_id: int,
        db_path: Path,
        dim: int = 256,
        max_items_per_project: int = 5000,
        text_max_chars: int = 800,
    ) -> None:
        self.project_id = int(project_id)
        self.db_path = Path(db_path)
        self.dim = max(16, int(dim))
        self.max_items_per_project = max(0, int(max_items_per_project))
        self.text_max_chars = max(0, int(text_max_chars))

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit，避免调用方忘记 commit 导致索引不落盘
        self._conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_assets (
              id TEXT PRIMARY KEY,
              project_id INTEGER NOT NULL,
              kind TEXT NOT NULL,
              path TEXT NOT NULL,
              text TEXT NOT NULL,
              embedding BLOB NOT NULL,
              meta_json TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            """
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_assets_project_path ON semantic_assets(project_id, path);"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_assets_project_created ON semantic_assets(project_id, created_at);"
        )

    def _embed(self, text: str) -> np.ndarray:
        return embed_text_local_hash(text, dim=self.dim)

    def add(
        self,
        *,
        kind: str,
        path: Path,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
        created_at: Optional[float] = None,
    ) -> bool:
        kind = str(kind or "").strip() or "unknown"
        if self.project_id <= 0:
            return False

        p = Path(path)
        if not p.exists():
            return False

        text_norm = _clamp_text(text, max_chars=self.text_max_chars)
        if not text_norm:
            return False

        now = float(time.time()) if created_at is None else float(created_at)
        meta_obj = meta if isinstance(meta, dict) else {}
        meta_json = json.dumps(meta_obj, ensure_ascii=False, separators=(",", ":"))

        item_id = hashlib.sha1(
            f"{self.project_id}|{kind}|{str(p)}".encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        emb = self._embed(text_norm).astype(np.float32, copy=False).tobytes()

        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO semantic_assets
            (id, project_id, kind, path, text, embedding, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (item_id, self.project_id, kind, str(p), text_norm, sqlite3.Binary(emb), meta_json, now),
        )
        inserted = bool(cur.rowcount and cur.rowcount > 0)
        if inserted:
            self._trim_if_needed()
        return inserted

    def add_many(self, items: Iterable[Dict[str, Any]]) -> int:
        inserted = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip() or "unknown"
            path = item.get("path")
            text = str(item.get("text") or "")
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            created_at = item.get("created_at")
            if not isinstance(path, Path):
                try:
                    path = Path(str(path))
                except Exception:  # noqa: BLE001
                    continue
            try:
                inserted += 1 if self.add(kind=kind, path=path, text=text, meta=meta, created_at=created_at) else 0
            except Exception:  # noqa: BLE001
                continue
        return inserted

    def query(
        self,
        *,
        text: str,
        top_k: int = 6,
        min_score: float = 0.25,
        kinds: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[Path]] = None,
    ) -> List[SemanticHit]:
        if self.project_id <= 0:
            return []
        query_text = _clamp_text(text, max_chars=self.text_max_chars)
        if not query_text:
            return []

        top_k = max(0, int(top_k))
        if top_k <= 0:
            return []

        min_score = float(min(1.0, max(-1.0, float(min_score))))
        exclude = {str(p) for p in (exclude_paths or []) if isinstance(p, Path)}

        where = "project_id = ?"
        params: List[Any] = [self.project_id]
        if kinds:
            picked = [str(k).strip() for k in kinds if isinstance(k, str) and str(k).strip()]
            if picked:
                where += f" AND kind IN ({','.join(['?'] * len(picked))})"
                params.extend(picked)

        rows = self._conn.execute(
            f"SELECT path, kind, meta_json, embedding FROM semantic_assets WHERE {where};",
            params,
        ).fetchall()
        if not rows:
            return []

        q = self._embed(query_text).astype(np.float32, copy=False)
        hits: List[SemanticHit] = []
        for path_str, kind, meta_json, emb_blob in rows:
            if not isinstance(path_str, str) or not path_str:
                continue
            if path_str in exclude:
                continue
            p = Path(path_str)
            if not p.exists():
                continue
            if not isinstance(emb_blob, (bytes, bytearray, memoryview)):
                continue
            vec = np.frombuffer(emb_blob, dtype=np.float32)
            if vec.size != self.dim:
                continue
            score = float(np.dot(q, vec))
            if score < min_score:
                continue
            meta: Dict[str, Any] = {}
            if isinstance(meta_json, str) and meta_json:
                try:
                    obj = json.loads(meta_json)
                    if isinstance(obj, dict):
                        meta = obj
                except Exception:  # noqa: BLE001
                    meta = {}
            hits.append(SemanticHit(score=score, path=p, kind=str(kind or ""), meta=meta))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def _trim_if_needed(self) -> None:
        if self.max_items_per_project <= 0:
            return
        row = self._conn.execute(
            "SELECT COUNT(1) FROM semantic_assets WHERE project_id = ?;",
            (self.project_id,),
        ).fetchone()
        count = _safe_int(row[0] if row else 0, 0)
        overflow = count - int(self.max_items_per_project)
        if overflow <= 0:
            return
        # 删除最早的 N 条
        self._conn.execute(
            """
            DELETE FROM semantic_assets
            WHERE id IN (
              SELECT id FROM semantic_assets
              WHERE project_id = ?
              ORDER BY created_at ASC
              LIMIT ?
            );
            """,
            (self.project_id, int(overflow)),
        )


def is_semantic_retrieval_enabled(*, image_cfg: Dict[str, Any]) -> bool:
    """
    统一入口：支持 image_config 与 env 双通道开关，默认关闭（避免影响现有行为）。
    """
    if isinstance(image_cfg.get("semantic_retrieval"), bool):
        return bool(image_cfg.get("semantic_retrieval"))
    return _env_flag("DREAMWEAVER_ENABLE_SEMANTIC_RETRIEVAL", default=False)


def semantic_retrieval_config(image_cfg: Dict[str, Any]) -> Dict[str, Any]:
    top_k = _safe_int(image_cfg.get("semantic_retrieval_top_k"), _safe_int(os.getenv("DREAMWEAVER_SEMANTIC_RETRIEVAL_TOP_K"), 6))
    min_score = _safe_float(image_cfg.get("semantic_retrieval_min_score"), _safe_float(os.getenv("DREAMWEAVER_SEMANTIC_RETRIEVAL_MIN_SCORE"), 0.25))
    max_additional = _safe_int(
        image_cfg.get("semantic_retrieval_max_additional_refs"),
        _safe_int(os.getenv("DREAMWEAVER_SEMANTIC_RETRIEVAL_MAX_ADDITIONAL_REFS"), 4),
    )
    return {
        "top_k": max(0, int(top_k)),
        "min_score": float(min_score),
        "max_additional_refs": max(0, int(max_additional)),
        "db_path": Path(str(os.getenv("DREAMWEAVER_SEMANTIC_INDEX_DB") or "runs/_semantic_cache/semantic_assets.sqlite3")),
        "dim": _safe_int(os.getenv("DREAMWEAVER_SEMANTIC_INDEX_DIM"), 256),
        "max_items_per_project": _safe_int(os.getenv("DREAMWEAVER_SEMANTIC_INDEX_MAX_ITEMS_PER_PROJECT"), 5000),
        "text_max_chars": _safe_int(os.getenv("DREAMWEAVER_SEMANTIC_INDEX_TEXT_MAX_CHARS"), 800),
    }
