"""
结构化记忆存储器

职责:
1. 以项目为粒度持久化结构化记忆
2. 优先从 project_settings 表读取 / 写回结构化记忆
3. 在数据库不可用时回退到项目上下文文件
4. 在多轮调用间合并历史记忆与当前记忆
"""
from __future__ import annotations

import importlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

from ...utils.datetime_utils import parse_datetime_utc, utc_now

logger = logging.getLogger(__name__)


class StructuredMemoryStore:
    """项目级结构化记忆存储器"""

    STORAGE_KEY = "structured_story_memory"
    DB_TABLE = "project_settings"
    DB_COLUMN = "structured_memory"
    DB_UPDATED_AT_COLUMN = "structured_memory_updated_at"
    CATEGORY_ITEM_LIMITS = {
        "global_story_arcs": 10,
        "character_states": 14,
        "relationship_edges": 12,
        "pending_foreshadowings": 12,
        "world_rules_hard_constraints": 10,
    }

    def __init__(
        self,
        persist_directory: str = "memory_data",
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._session_factory = session_factory

    def load(self, project_id: Optional[int]) -> Dict[str, Any]:
        """加载项目级结构化记忆，优先数据库，失败时回退文件缓存。"""
        if project_id is None:
            return {}

        payload = self._load_from_database(project_id)
        if payload:
            return payload

        return self._load_from_file(project_id)

    def save(
        self,
        project_id: Optional[int],
        structured_memory: Dict[str, List[str]],
        memory_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """保存项目级结构化记忆，同时写数据库与文件缓存。"""
        if project_id is None:
            return False

        payload = self._build_payload(
            structured_memory=structured_memory,
            memory_text=memory_text,
            metadata=metadata,
        )

        db_saved = self._save_to_database(project_id, payload)
        file_saved = self._save_to_file(project_id, payload)
        return db_saved or file_saved

    def merge(
        self,
        current_memory: Optional[Dict[str, List[str]]],
        persisted_memory: Optional[Dict[str, List[str]]],
    ) -> Dict[str, List[str]]:
        """合并当前记忆与历史记忆，当前轮优先。"""
        merged: Dict[str, List[str]] = {}
        all_keys = set((current_memory or {}).keys()) | set((persisted_memory or {}).keys())

        for key in all_keys:
            current_values = list((current_memory or {}).get(key) or [])
            persisted_values = list((persisted_memory or {}).get(key) or [])
            combined = self._deduplicate_preserve_order(current_values + persisted_values)
            limit = self.CATEGORY_ITEM_LIMITS.get(key, 12)
            if combined:
                merged[key] = combined[:limit]

        return merged

    def _build_payload(
        self,
        structured_memory: Optional[Dict[str, List[str]]],
        memory_text: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        updated_at = utc_now().isoformat()
        return {
            "structured_memory": self._normalize_structured_memory(structured_memory),
            "memory_text": str(memory_text or ""),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "updated_at": updated_at,
        }

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "structured_memory": self._normalize_structured_memory(payload.get("structured_memory")),
            "memory_text": str(payload.get("memory_text") or ""),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _normalize_structured_memory(self, value: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
        if not isinstance(value, dict):
            return {}

        normalized: Dict[str, List[str]] = {}
        for key, items in value.items():
            if not isinstance(key, str):
                continue

            if isinstance(items, list):
                normalized_items = self._deduplicate_preserve_order([str(item or "") for item in items])
            else:
                normalized_items = self._deduplicate_preserve_order([str(items or "")])

            if normalized_items:
                normalized[key] = normalized_items

        return normalized

    def _deserialize_payload(self, raw_payload: Any) -> Dict[str, Any]:
        if not raw_payload:
            return {}

        payload = raw_payload
        if isinstance(raw_payload, str):
            try:
                payload = json.loads(raw_payload)
            except Exception:
                return {}

        if not isinstance(payload, dict):
            return {}

        if "structured_memory" in payload:
            return self._normalize_payload(payload)

        legacy_payload = payload.get(self.STORAGE_KEY)
        if isinstance(legacy_payload, dict):
            return self._normalize_payload(legacy_payload)

        return {}

    def _context_file(self, project_id: int) -> Path:
        return self.persist_directory / f"context_{project_id}.json"

    def _load_from_file(self, project_id: int) -> Dict[str, Any]:
        context = self._load_context(project_id)
        payload = context.get(self.STORAGE_KEY)
        return self._deserialize_payload(payload)

    def _save_to_file(self, project_id: int, payload: Dict[str, Any]) -> bool:
        context = self._load_context(project_id)
        context[self.STORAGE_KEY] = payload
        return self._save_context(project_id, context)

    def _load_context(self, project_id: int) -> Dict[str, Any]:
        path = self._context_file(project_id)
        if not path.exists():
            return {}

        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_context(self, project_id: int, context: Dict[str, Any]) -> bool:
        path = self._context_file(project_id)
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(context, file, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _load_from_database(self, project_id: int) -> Dict[str, Any]:
        session_factory = self._get_session_factory()
        if session_factory is None:
            return {}

        session = None
        try:
            session = session_factory()
            raw_payload = session.execute(
                text(
                    f"""
                    SELECT {self.DB_COLUMN}
                    FROM {self.DB_TABLE}
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).scalar()
            return self._deserialize_payload(raw_payload)
        except Exception as exc:
            logger.debug("Load structured memory from database failed: %s", exc)
            return {}
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _save_to_database(self, project_id: int, payload: Dict[str, Any]) -> bool:
        session_factory = self._get_session_factory()
        if session_factory is None:
            return False

        updated_at = self._parse_updated_at(payload.get("updated_at"))
        session = None
        try:
            session = session_factory()
            session.execute(
                text(
                    f"""
                    INSERT INTO {self.DB_TABLE} (
                        project_id,
                        {self.DB_COLUMN},
                        {self.DB_UPDATED_AT_COLUMN}
                    )
                    VALUES (
                        :project_id,
                        :structured_memory,
                        :structured_memory_updated_at
                    )
                    ON CONFLICT (project_id) DO UPDATE
                    SET
                        {self.DB_COLUMN} = EXCLUDED.{self.DB_COLUMN},
                        {self.DB_UPDATED_AT_COLUMN} = EXCLUDED.{self.DB_UPDATED_AT_COLUMN},
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "project_id": project_id,
                    "structured_memory": json.dumps(payload, ensure_ascii=False),
                    "structured_memory_updated_at": updated_at,
                },
            )
            session.commit()
            return True
        except Exception as exc:
            logger.debug("Save structured memory to database failed: %s", exc)
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            return False
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _get_session_factory(self) -> Optional[Callable[[], Any]]:
        if self._session_factory is not None:
            return self._session_factory

        for module_name in ("app.db.base", "backend.app.db.base"):
            try:
                module = importlib.import_module(module_name)
                session_factory = getattr(module, "SessionLocal", None)
                if session_factory is not None:
                    self._session_factory = session_factory
                    return self._session_factory
            except Exception as exc:
                logger.debug("Load session factory from %s failed: %s", module_name, exc)

        return None

    def _parse_updated_at(self, value: Any) -> datetime:
        parsed = parse_datetime_utc(value)
        if parsed is not None:
            return parsed

        return utc_now()

    def _deduplicate_preserve_order(self, values: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()

        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)

        return result
