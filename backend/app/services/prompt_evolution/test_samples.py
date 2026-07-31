"""
提示词进化系统 - 测试样本管理

管理用于评估提示词效果的测试样本。
支持三层来源：管理员自定义 > 自动生成 > 内置默认。
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Awaitable
from enum import Enum
from datetime import datetime
import hashlib
import json
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 留出集划分比例（§11.1 holdout_score_gap 信号 2，结构参数非质量阈值）：
# 按 sample_id 哈希取固定比例划入留出集，同一样本恒定归属，增删样本不漂移。
HOLDOUT_RATIO = 0.3


def is_holdout_sample_id(sample_id: str) -> bool:
    """按 sample_id 哈希做确定性留出划分（同一 ID 恒定结果，不随机漂移）。"""
    digest = hashlib.sha256(sample_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % 100 < round(HOLDOUT_RATIO * 100)


class GenreType(str, Enum):
    """题材类型"""
    FANTASY = "玄幻"           # 玄幻小说
    URBAN = "都市"             # 都市小说
    ROMANCE = "言情"           # 言情小说
    SUSPENSE = "悬疑"           # 悬疑小说
    SCIFI = "科幻"             # 科幻小说
    HISTORICAL = "历史"        # 历史小说
    MARTIAL_ARTS = "武侠"      # 武侠小说
    OTHER = "其他"             # 其他类型


class SampleSource(str, Enum):
    """样本来源"""
    DEFAULT = "default"   # 内置默认
    CUSTOM = "custom"     # 管理员自定义
    AUTO = "auto"         # LLM 自动生成


@dataclass
class TestSample:
    """测试样本"""
    sample_id: str                      # 样本ID
    text: str                           # 测试文本
    genre: str = "其他"                 # 题材类型
    expected_ai_score: Optional[int] = None  # 预期AI得分（可选）
    description: str = ""               # 样本描述
    source: str = "default"             # 来源: default / custom / auto
    is_holdout: bool = False            # 留出集标记（§11.1 holdout 过拟合探针，旧数据缺省训练）
    created_at: str = ""                # 创建时间 ISO 格式
    ai_detection_score: Optional[int] = None
    ai_detection_label: str = ""
    ai_detection_suggestion: str = ""
    ai_detection_text_hash: str = ""
    ai_detection_policy_version: str = ""
    ai_detected_at: str = ""

    def _detection_text_hash(self) -> str:
        from app.services.tencent_ai_detect import tencent_ai_detect_service

        prepared = tencent_ai_detect_service.prepare_text(self.text)
        return hashlib.sha256(prepared.encode("utf-8")).hexdigest()

    def get_ai_detection(self, policy_version: str) -> Optional[Dict[str, Any]]:
        """返回仍适用于当前文本和检测策略的持久化基线。"""
        if self.ai_detection_score is None:
            return None
        if self.ai_detection_policy_version != policy_version:
            return None
        if self.ai_detection_text_hash != self._detection_text_hash():
            return None
        return {
            "success": True,
            "ai_score": self.ai_detection_score,
            "label": self.ai_detection_label,
            "suggestion": self.ai_detection_suggestion,
        }

    def detection_cache_key(self, policy_version: str) -> str:
        """返回不包含原文、可跨样本复用的内容寻址键。"""
        return f"{policy_version}:{self._detection_text_hash()}"

    def store_ai_detection(self, result: Dict[str, Any], policy_version: str) -> None:
        """保存成功检测的最小结构化结果，不持久化供应商原始响应。"""
        self.ai_detection_score = int(result.get("ai_score", 0))
        self.ai_detection_label = str(result.get("label", ""))
        self.ai_detection_suggestion = str(result.get("suggestion", ""))
        self.ai_detection_text_hash = self._detection_text_hash()
        self.ai_detection_policy_version = policy_version
        self.ai_detected_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sample_id": self.sample_id,
            "text": self.text,
            "genre": self.genre,
            "expected_ai_score": self.expected_ai_score,
            "description": self.description,
            "source": self.source,
            "is_holdout": self.is_holdout,
            "created_at": self.created_at,
            "ai_detection_score": self.ai_detection_score,
            "ai_detection_label": self.ai_detection_label,
            "ai_detection_suggestion": self.ai_detection_suggestion,
            "ai_detection_text_hash": self.ai_detection_text_hash,
            "ai_detection_policy_version": self.ai_detection_policy_version,
            "ai_detected_at": self.ai_detected_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestSample":
        """从字典创建"""
        return cls(
            sample_id=data["sample_id"],
            text=data["text"],
            genre=data.get("genre", "其他"),
            expected_ai_score=data.get("expected_ai_score"),
            description=data.get("description", ""),
            source=data.get("source", "default"),
            is_holdout=bool(data.get("is_holdout", False)),
            created_at=data.get("created_at", ""),
            ai_detection_score=data.get("ai_detection_score"),
            ai_detection_label=data.get("ai_detection_label", ""),
            ai_detection_suggestion=data.get("ai_detection_suggestion", ""),
            ai_detection_text_hash=data.get("ai_detection_text_hash", ""),
            ai_detection_policy_version=data.get("ai_detection_policy_version", ""),
            ai_detected_at=data.get("ai_detected_at", ""),
        )


DEFAULT_TEST_SAMPLES = [
    TestSample(
        sample_id="fantasy_001",
        text="林凡站在悬崖边，望着远处的云海。他的修为已经达到了金丹期巅峰，只差一步就能突破到元婴期。这十年来，他经历了无数生死考验，从一个小小的炼气期修士，一步步走到今天。",
        genre="玄幻",
        description="玄幻小说典型场景，修炼突破"
    ),
    TestSample(
        sample_id="urban_001",
        text="李明推开办公室的门，看到同事们都在忙碌地工作。他刚从国外留学回来，接手了家族企业。虽然压力很大，但他相信凭借自己的能力，一定能把公司经营得更好。",
        genre="都市",
        description="都市职场场景，回国创业"
    ),
    TestSample(
        sample_id="romance_001",
        text="苏晴看着窗外的雨，想起了三年前那个夏天。那天她在图书馆遇到了陈浩，两人因为一本书结缘。从那以后，他们一起度过了许多美好的时光，直到陈浩出国留学。",
        genre="言情",
        description="言情小说场景，回忆初恋"
    ),
    TestSample(
        sample_id="suspense_001",
        text="侦探走进案发现场，仔细观察每一个细节。地上有一滩血迹，墙上有一枚模糊的指纹。他蹲下身，用放大镜仔细查看，发现了一些不寻常的痕迹。",
        genre="悬疑",
        description="悬疑小说场景，侦探破案"
    ),
    TestSample(
        sample_id="scifi_001",
        text="飞船穿越了虫洞，来到了一个未知的星系。船长看着屏幕上的数据，惊讶地发现这里的物理法则与地球完全不同。重力是地球的三倍，时间流速也异常缓慢。",
        genre="科幻",
        description="科幻小说场景，太空探索"
    ),
    TestSample(
        sample_id="historical_001",
        text="将军站在城墙上，看着远处的敌军。这场仗已经打了三个月，双方都损失惨重。他知道，这一战将决定整个王朝的命运。他握紧了手中的剑，准备迎接最后的决战。",
        genre="历史",
        description="历史小说场景，将军守城"
    ),
    TestSample(
        sample_id="martial_arts_001",
        text="剑客拔出长剑，剑光如水，寒气逼人。他练剑三十年，从未遇到对手。今天，他终于遇到了一个值得他全力以赴的对手。两人相对而立，气氛紧张到了极点。",
        genre="武侠",
        description="武侠小说场景，高手对决"
    ),
    TestSample(
        sample_id="fantasy_002",
        text="少女睁开眼睛，发现自己躺在一片花海中。她记得自己明明在实验室里做实验，怎么会突然来到这里？她站起身，看到远处有一座高耸入云的塔楼，塔顶闪烁着奇异的光芒。",
        genre="玄幻",
        description="玄幻小说场景，异界穿越"
    ),
    TestSample(
        sample_id="urban_002",
        text="程序员看着屏幕上的代码，眉头紧锁。这个bug已经困扰了他三天，无论怎么调试都无法解决。他喝了一口咖啡，决定从头开始分析问题。",
        genre="都市",
        description="都市职场场景，程序员工作"
    ),
    TestSample(
        sample_id="romance_002",
        text="婚礼现场，新娘穿着洁白的婚纱，美丽动人。新郎深情地看着她，眼中满是爱意。他们在亲朋好友的见证下，许下了相守一生的誓言。",
        genre="言情",
        description="言情小说场景，婚礼仪式"
    )
]


class TestSampleManager:
    """
    测试样本管理器

    支持持久化存储，三层来源优先级：custom > auto > default。
    进化引擎取样时优先使用 custom，不足部分用 auto/default 补齐。
    """

    _STORAGE_DIR: Optional[Path] = None

    def __init__(self, samples: Optional[List[TestSample]] = None, storage_dir: Optional[str] = None):
        if storage_dir:
            self._storage_path = Path(storage_dir) / "test_samples.json"
        else:
            # 与 EvolutionStorage / ModelConfigStorage 统一使用仓库根 data/prompt_evolution
            base_dir = Path(__file__).resolve().parents[4]
            self._storage_path = base_dir / "data" / "prompt_evolution" / "test_samples.json"
            legacy_path = Path(__file__).resolve().parents[3] / "data" / "prompt_evolution" / "test_samples.json"
            if not self._storage_path.exists() and legacy_path.exists():
                self._storage_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(legacy_path, self._storage_path)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        if samples is not None:
            self.samples = samples
        else:
            self.samples = self._load_or_default()
        self._rebuild_index()

    def _rebuild_index(self):
        self._sample_index = {s.sample_id: s for s in self.samples}

    def _load_or_default(self) -> List[TestSample]:
        """从持久化文件加载，无文件时使用内置默认"""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                loaded = [TestSample.from_dict(d) for d in data]
                if loaded:
                    logger.info(f"从文件加载测试样本: {len(loaded)} 个")
                    return loaded
            except (json.JSONDecodeError, IOError, TypeError) as e:
                logger.warning(f"加载测试样本文件失败: {e}")
        return DEFAULT_TEST_SAMPLES.copy()

    def _persist(self):
        """持久化到文件"""
        data = [s.to_dict() for s in self.samples]
        with open(self._storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ==================== 查询接口 ====================

    def get_sample(self, sample_id: str) -> Optional[TestSample]:
        """根据ID获取样本"""
        return self._sample_index.get(sample_id)

    def get_samples_by_genre(self, genre: str, holdout: Optional[bool] = None) -> List[TestSample]:
        """根据题材获取样本；holdout 非 None 时按留出归属过滤（True=留出，False=训练）。"""
        samples = [s for s in self.samples if s.genre == genre]
        if holdout is None:
            return samples
        return [s for s in samples if s.is_holdout == holdout]

    def get_samples_by_source(self, source: str) -> List[TestSample]:
        """根据来源获取样本"""
        return [s for s in self.samples if s.source == source]

    def get_random_samples(self, count: int) -> List[TestSample]:
        """
        智能随机取样：custom 优先，不足时补 auto/default。
        尽量覆盖不同题材。
        """
        import random
        custom = [s for s in self.samples if s.source == SampleSource.CUSTOM]
        others = [s for s in self.samples if s.source != SampleSource.CUSTOM]

        if len(custom) >= count:
            return random.sample(custom, count)

        # custom 不够，全选 custom + 从 others 补齐
        selected = custom.copy()
        remaining = count - len(selected)
        if remaining > 0 and others:
            selected += random.sample(others, min(remaining, len(others)))
        return selected

    def get_samples(self, count: int) -> List[TestSample]:
        """按数量获取样本，兼容进化引擎的批量取样接口"""
        return self.get_random_samples(count)

    async def prepare_evaluation_samples(
        self,
        count: int,
        detector: Any,
        genre: Optional[str] = None,
        generator: Optional[Callable[..., Awaitable[List[TestSample]]]] = None,
    ) -> List[TestSample]:
        """复用持久基线，仅检测凑足本轮数量所需的未检测样本。"""
        from app.services.tencent_ai_detect import tencent_ai_detect_service

        policy_version = tencent_ai_detect_service.detection_policy_version
        target_samples = self.get_samples_by_genre(genre) if genre else self.samples.copy()
        source_priority = {SampleSource.CUSTOM: 0, SampleSource.AUTO: 1, SampleSource.DEFAULT: 2}
        target_samples.sort(key=lambda sample: source_priority.get(sample.source, 3))
        detections_by_content = {
            sample.detection_cache_key(policy_version): result
            for sample in self.samples
            if (result := sample.get_ai_detection(policy_version)) is not None
        }
        invalid_ids: List[str] = []
        selected: List[TestSample] = []
        persistence_changed = False

        for sample in target_samples:
            if len(selected) >= count:
                break
            result = sample.get_ai_detection(policy_version)
            if result is None:
                cache_key = sample.detection_cache_key(policy_version)
                result = detections_by_content.get(cache_key)
                if result is None:
                    result = await detector.detect_ai_content(sample.text)
                if result.get("success"):
                    detections_by_content[cache_key] = result
                    sample.store_ai_detection(result, policy_version)
                    persistence_changed = True
            if result.get("success") and result.get("ai_score") == 0:
                invalid_ids.append(sample.sample_id)
            elif result.get("success"):
                selected.append(sample)

        removed_genres = [self._sample_index[sample_id].genre for sample_id in invalid_ids]
        if invalid_ids:
            invalid_set = set(invalid_ids)
            self.samples = [sample for sample in self.samples if sample.sample_id not in invalid_set]
            self._rebuild_index()
            logger.warning("已清除 AI 率为 0 的测试样本: %s", ", ".join(invalid_ids))

        if len(selected) < count and generator is not None:
            replacement_genres = removed_genres or ([genre] if genre else []) or ["通用"]
            attempts = 0
            while len(selected) < count and attempts < 3:
                attempts += 1
                missing = count - len(selected)
                generated = await generator(
                    genres=list(dict.fromkeys(replacement_genres)),
                    count_per_genre=max(2, missing * 2),
                )
                for sample in generated:
                    cache_key = sample.detection_cache_key(policy_version)
                    result = sample.get_ai_detection(policy_version)
                    if result is None:
                        result = detections_by_content.get(cache_key)
                        if result is None:
                            result = await detector.detect_ai_content(sample.text)
                    if result.get("success") and result.get("ai_score") != 0:
                        detections_by_content[cache_key] = result
                        sample.store_ai_detection(result, policy_version)
                        sample.source = SampleSource.AUTO
                        if not sample.created_at:
                            sample.created_at = datetime.now().isoformat()
                        if sample.sample_id not in self._sample_index:
                            self.samples.append(sample)
                            self._sample_index[sample.sample_id] = sample
                            selected.append(sample)
                            persistence_changed = True
                            if len(selected) >= count:
                                break
                    else:
                        logger.warning("丢弃 AI 率为 0 或检测失败的替代样本: %s", sample.sample_id)

        if invalid_ids or persistence_changed:
            self._persist()

        if len(selected) < count:
            raise RuntimeError(f"有效测试样本不足: 需要 {count} 个，当前仅 {len(selected)} 个")

        selected.sort(key=lambda sample: source_priority.get(sample.source, 3))
        return selected[:count]

    def get_all_samples(self) -> List[TestSample]:
        """获取所有样本"""
        return self.samples.copy()

    def apply_holdout_split(self) -> Dict[str, int]:
        """
        对全部样本按 sample_id 哈希做确定性留出划分并持久化（§11.1 holdout 探针）。

        幂等：同一样本恒定归属，重复调用结果不变；归属无变化时不写盘。
        返回 {"holdout": 留出数, "training": 训练数} 统计。
        """
        changed = False
        for sample in self.samples:
            flag = is_holdout_sample_id(sample.sample_id)
            if sample.is_holdout != flag:
                sample.is_holdout = flag
                changed = True
        if changed:
            self._persist()
        holdout_count = sum(1 for s in self.samples if s.is_holdout)
        return {"holdout": holdout_count, "training": len(self.samples) - holdout_count}

    def get_sample_count(self) -> int:
        """获取样本数量"""
        return len(self.samples)

    def get_genres(self) -> List[str]:
        """获取所有题材"""
        return list(set(s.genre for s in self.samples))

    # ==================== 增删接口 ====================

    def add_sample(self, sample: TestSample) -> TestSample:
        """添加样本并持久化"""
        if sample.sample_id in self._sample_index:
            raise ValueError(f"样本ID {sample.sample_id} 已存在")
        if not sample.created_at:
            sample.created_at = datetime.now().isoformat()
        self.samples.append(sample)
        self._sample_index[sample.sample_id] = sample
        self._persist()
        return sample

    def remove_sample(self, sample_id: str) -> bool:
        """移除样本并持久化"""
        if sample_id not in self._sample_index:
            return False
        sample = self._sample_index[sample_id]
        self.samples.remove(sample)
        del self._sample_index[sample_id]
        self._persist()
        return True

    def clear_auto_samples(self):
        """清除所有自动生成的样本"""
        self.samples = [s for s in self.samples if s.source != SampleSource.AUTO]
        self._rebuild_index()
        self._persist()

    def add_auto_samples(self, samples: List[TestSample]):
        """批量添加自动生成的样本（替换旧的 auto 样本）"""
        self.clear_auto_samples()
        for s in samples:
            s.source = SampleSource.AUTO
            if not s.created_at:
                s.created_at = datetime.now().isoformat()
            self.samples.append(s)
        self._rebuild_index()
        self._persist()
        logger.info(f"添加自动生成样本: {len(samples)} 个")

    # ==================== 导入导出 ====================

    def save_to_file(self, file_path: Path):
        """保存到指定文件"""
        data = [s.to_dict() for s in self.samples]
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, file_path: Path) -> "TestSampleManager":
        """从文件加载"""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        samples = [TestSample.from_dict(d) for d in data]
        return cls(samples)

    def get_summary(self) -> Dict[str, Any]:
        """获取摘要信息"""
        genre_count: Dict[str, int] = {}
        source_count: Dict[str, int] = {}
        for sample in self.samples:
            genre_count[sample.genre] = genre_count.get(sample.genre, 0) + 1
            source_count[sample.source] = source_count.get(sample.source, 0) + 1

        return {
            "total_samples": len(self.samples),
            "genres": self.get_genres(),
            "genre_distribution": genre_count,
            "source_distribution": source_count,
        }


# ============================================================================
# 自动生成器
# ============================================================================

# LLM 生成提示模板（按题材）
_GENRE_GENERATION_PROMPTS: Dict[str, str] = {
    "玄幻": "请写一段200-350字的玄幻小说片段，包含修炼、法宝、妖兽等元素。要有具体的场景描写和人物动作，不要使用对话格式。",
    "都市": "请写一段200-350字的都市小说片段，包含职场、生活、城市场景。要有细腻的心理描写和日常细节，不要使用对话格式。",
    "言情": "请写一段200-350字的言情小说片段，描写人物间的情感互动或内心独白。要有氛围描写和细腻的情感表达，不要使用对话格式。",
    "悬疑": "请写一段200-350字的悬疑小说片段，包含线索发现、推理思考或紧张氛围。要有环境描写和心理活动，不要使用对话格式。",
    "科幻": "请写一段200-350字的科幻小说片段，包含未来科技、太空或AI等元素。要有想象力和科技感的细节描写，不要使用对话格式。",
    "历史": "请写一段200-350字的历史小说片段，包含古代场景、人物和时代氛围。要有时代特征的细节和人物心理，不要使用对话格式。",
    "武侠": "请写一段200-350字的武侠小说片段，包含江湖、武功、侠义等元素。要有动作描写和江湖氛围，不要使用对话格式。",
}


async def generate_samples_via_llm(
    genres: Optional[List[str]] = None,
    count_per_genre: int = 2,
) -> List[TestSample]:
    """
    使用 LLM 自动生成测试样本

    Args:
        genres: 要生成的题材列表（None=全部7种）
        count_per_genre: 每种题材生成的样本数

    Returns:
        生成的 TestSample 列表
    """
    from core.unified_llm_client import get_llm_client

    llm = get_llm_client()
    target_genres = genres or list(_GENRE_GENERATION_PROMPTS.keys())
    generated: List[TestSample] = []
    now = datetime.now().isoformat()

    for genre in target_genres:
        prompt = _GENRE_GENERATION_PROMPTS.get(genre)
        if not prompt:
            continue

        for i in range(count_per_genre):
            try:
                messages = [
                    {"role": "system", "content": "你是一位网络小说作家，擅长各种题材的创作。请直接输出小说正文内容，不要加标题、解释或格式标记。"},
                    {"role": "user", "content": prompt},
                ]
                result = await llm.chat(
                    messages=messages,
                    temperature=0.95,  # 高温度增加多样性
                    use_cache=False,
                )

                if result and len(result.strip()) >= 100:
                    sample_id = f"auto_{genre}_{uuid.uuid4().hex[:8]}"
                    generated.append(TestSample(
                        sample_id=sample_id,
                        text=result.strip(),
                        genre=genre,
                        description=f"自动生成 - {genre}小说片段",
                        source=SampleSource.AUTO,
                        created_at=now,
                    ))
                    logger.info(f"自动生成样本: {sample_id} ({genre}, {len(result.strip())}字)")
                else:
                    logger.warning(f"自动生成样本过短或为空: {genre} #{i+1}")
            except Exception as e:
                logger.error(f"自动生成样本失败: {genre} #{i+1}: {e}")

    logger.info(f"自动生成完成: {len(generated)}/{len(target_genres) * count_per_genre} 个样本")
    return generated


# ============================================================================
# 全局单例
# ============================================================================

_manager: Optional[TestSampleManager] = None


def get_sample_manager() -> TestSampleManager:
    """获取测试样本管理器单例"""
    global _manager
    if _manager is None:
        _manager = TestSampleManager()
    return _manager
