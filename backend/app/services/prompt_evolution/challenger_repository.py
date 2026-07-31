"""
挑战者池持久化（设计文档 §3.2 ⑦ / §6.1）

- FailedVariantStore    失败变体记录落盘：把 engine._failed_variants（内存 {hash: count}）
  转为跨进程持久的 JSON 账本，供离线门槛 ⑦（不在失败变体记录中）判定，阈值默认 3 次；
- ChallengerRepository  挑战者写入 prompt_challengers 表，幂等 on challenger_id
  （重复入库返回既有行，不产生第二条，供离线批次可重跑）。

纯持久化层：不做业务判定（准入逻辑在 challenger_pool.evaluate_offline_gate）。
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptChallenger
from app.services.prompt_evolution.experiment_contract import ServingMode, assert_transition

logger = logging.getLogger(__name__)

# 失败变体拉黑阈值：与 engine._failed_variants 现有行为一致（fail_count >= 3 跳过）
DEFAULT_BLOCK_THRESHOLD = 3


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
        logger.warning("失败变体账本损坏，按空账本处理: %s", path.name)
        return {}


class FailedVariantStore:
    """失败变体记录（{prompt_hash: fail_count}）落盘，实现离线门槛 ⑦ 的持久化"""

    def __init__(self, storage_dir: Optional[str] = None, block_threshold: int = DEFAULT_BLOCK_THRESHOLD):
        if storage_dir is None:
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            storage_dir = str(base_dir / "data" / "prompt_evolution" / "challenger_pool")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.storage_dir / "failed_variants.json"
        self.block_threshold = block_threshold
        self._counts: Dict[str, int] = {
            str(k): int(v) for k, v in _load_json(self.store_file).items()
        }

    def get_fail_count(self, prompt_hash: str) -> int:
        return self._counts.get(prompt_hash, 0)

    def record_failure(self, prompt_hash: str) -> int:
        """记录一次失败，返回累计失败次数"""
        count = self._counts.get(prompt_hash, 0) + 1
        self._counts[prompt_hash] = count
        _atomic_write_json(self.store_file, self._counts)
        return count

    def is_blocked(self, prompt_hash: str) -> bool:
        return self.get_fail_count(prompt_hash) >= self.block_threshold

    def get_blocked_hashes(self) -> set:
        """返回累计失败已达阈值的哈希集合（供 evaluate_offline_gate 的 blocked_hashes 使用）"""
        return {h for h, c in self._counts.items() if c >= self.block_threshold}


class ChallengerRepository:
    """挑战者池仓储（prompt_challengers 表，写入幂等 on challenger_id）"""

    def __init__(self, session: Session):
        self.session = session

    def get_by_challenger_id(self, challenger_id: str) -> Optional[PromptChallenger]:
        return (
            self.session.query(PromptChallenger)
            .filter(PromptChallenger.challenger_id == challenger_id)
            .one_or_none()
        )

    def upsert_challenger(
        self,
        *,
        challenger_id: str,
        genre: str,
        prompt_text: str,
        prompt_hash: str,
        strategy_desc: str,
        strategy_family: str,
        source_batch: str,
        offline_gate_passed: bool,
        offline_scores: dict,
        serving_mode: str = "shadow",
    ) -> PromptChallenger:
        """
        写入挑战者，幂等 on challenger_id：已存在则原样返回既有行，不覆盖、不新增。

        challenger_id 由内容哈希派生（challenger_pool.make_challenger_id），相同提示词
        重复入库会命中既有行，保证离线批次可安全重跑。
        """
        existing = self.get_by_challenger_id(challenger_id)
        if existing is not None:
            return existing

        row = PromptChallenger(
            challenger_id=challenger_id,
            genre=genre,
            prompt_text=prompt_text,
            prompt_hash=prompt_hash,
            strategy_desc=strategy_desc,
            strategy_family=strategy_family,
            source_batch=source_batch,
            offline_gate_passed=offline_gate_passed,
            offline_scores=offline_scores,
            serving_mode=serving_mode,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_serving(self, genre: str, serving_mode: str = "shadow") -> list:
        """
        列出某题材下处于指定服务模式且已通过离线 gate 的挑战者。

        按 challenger_id 排序保证顺序确定性——分流层用
        select_challenger_index 对该列表做确定性索引（§5.1），
        列表顺序不稳定会破坏同用户×题材×统计窗口内的选择恒定。
        """
        return (
            self.session.query(PromptChallenger)
            .filter(
                PromptChallenger.genre == genre,
                PromptChallenger.serving_mode == serving_mode,
                PromptChallenger.offline_gate_passed.is_(True),
            )
            .order_by(PromptChallenger.challenger_id)
            .all()
        )

    def update_serving_mode(
        self, challenger_id: str, new_mode: str, *, now: Optional[datetime] = None
    ) -> Optional[PromptChallenger]:
        """
        推进挑战者 serving_mode 状态机（§3.1）。经 experiment_contract.assert_transition
        校验合法性，非法转换抛 ValueError；同步记录 state_changed_at。
        挑战者不存在返回 None。

        注意：读取-内存断言-盲写模式，无并发防护，仅供单 worker 调度器上下文
        （champion_promotion / layered_calibration）使用；多管理员并发入口
        （人工开闸）须走 transition_serving_mode 条件更新（六轮评审①）。
        """
        row = self.get_by_challenger_id(challenger_id)
        if row is None:
            return None
        assert_transition(ServingMode(row.serving_mode), ServingMode(new_mode))
        row.serving_mode = new_mode
        row.state_changed_at = now or datetime.now(timezone.utc)
        self.session.flush()
        return row

    def transition_serving_mode(
        self,
        challenger_id: str,
        from_mode: str,
        to_mode: str,
        *,
        now: Optional[datetime] = None,
    ) -> bool:
        """
        条件推进 serving_mode（六轮评审①防并发竞态）：
        UPDATE ... WHERE challenger_id=:id AND serving_mode=:from_mode，
        以影响行数判定本事务是否赢得状态转换——并发审批下只有一个事务
        命中条件返回 True，陈旧读方返回 False（含挑战者不存在）。
        经 assert_transition 校验状态机合法性，非法转换抛 ValueError；
        synchronize_session="fetch" 保持本 session 缓存对象与数据库一致。
        """
        assert_transition(ServingMode(from_mode), ServingMode(to_mode))
        updated = (
            self.session.query(PromptChallenger)
            .filter(
                PromptChallenger.challenger_id == challenger_id,
                PromptChallenger.serving_mode == from_mode,
            )
            .update(
                {
                    "serving_mode": to_mode,
                    "state_changed_at": now or datetime.now(timezone.utc),
                },
                synchronize_session="fetch",
            )
        )
        return updated == 1
