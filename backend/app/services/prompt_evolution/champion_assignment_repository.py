"""
冠军指针仓储（设计文档 §8.3 / §6.1 · §14 第 9 步 · 子块 B）

prompt_champion_assignments 表的持久化：effective_until 为空 = 当前指针；
切换 = 关闭旧行（置 effective_until）+ 插入新行（每行即审计记录）。
本表只存指针 + 哈希，提示词内容仍在 EvolutionStorage（不覆盖 best_prompts.json）。

仓储层契约（与 experiment_repository 一致）：只 flush 不 commit，事务边界由
调用方（champion_promotion 服务层）掌控，确保指针切换与 serving_mode 推进同事务原子。
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptChampionAssignment

logger = logging.getLogger(__name__)


class ChampionAssignmentRepository:
    """冠军指针仓储（prompt_champion_assignments 表）"""

    def __init__(self, session: Session):
        self.session = session

    def get_current(self, genre: str) -> Optional[PromptChampionAssignment]:
        """当前指针：该题材下 effective_until 为空的行（至多一条）。"""
        return (
            self.session.query(PromptChampionAssignment)
            .filter(
                PromptChampionAssignment.genre == genre,
                PromptChampionAssignment.effective_until.is_(None),
            )
            .one_or_none()
        )

    def list_history(self, genre: str) -> List[PromptChampionAssignment]:
        """该题材指针历史，按生效时间升序（每行即一条审计记录）。"""
        return (
            self.session.query(PromptChampionAssignment)
            .filter(PromptChampionAssignment.genre == genre)
            .order_by(PromptChampionAssignment.effective_from, PromptChampionAssignment.id)
            .all()
        )

    def switch_champion(
        self,
        genre: str,
        *,
        prompt_version_id: str,
        prompt_hash: str,
        operator: Optional[str] = None,
        reason: Optional[str] = None,
        gate_overridden: bool = False,
        override_reason: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> PromptChampionAssignment:
        """
        原子指针切换（§8.3）：关闭当前指针（effective_until=now）+ 插入新指针
        （effective_until 为空）。新行 previous_version_id 自动取自当前指针。
        只 flush 不 commit——调用方在同事务内一并推进 serving_mode 后统一提交。
        """
        now = now or datetime.now(timezone.utc)
        current = self.get_current(genre)
        previous_version_id = current.prompt_version_id if current is not None else None
        if current is not None:
            current.effective_until = now

        new_row = PromptChampionAssignment(
            genre=genre,
            prompt_version_id=prompt_version_id,
            prompt_hash=prompt_hash,
            previous_version_id=previous_version_id,
            operator=operator,
            reason=reason,
            gate_overridden=gate_overridden,
            override_reason=override_reason,
            effective_from=now,
        )
        self.session.add(new_row)
        self.session.flush()
        return new_row
