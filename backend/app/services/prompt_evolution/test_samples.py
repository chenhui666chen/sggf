"""
提示词进化系统 - 测试样本管理

管理用于评估提示词效果的测试样本
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from enum import Enum
import json
from pathlib import Path


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


@dataclass
class TestSample:
    """测试样本"""
    sample_id: str                      # 样本ID
    text: str                           # 测试文本
    genre: str = "其他"                 # 题材类型
    expected_ai_score: Optional[int] = None  # 预期AI得分（可选）
    description: str = ""               # 样本描述
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sample_id": self.sample_id,
            "text": self.text,
            "genre": self.genre,
            "expected_ai_score": self.expected_ai_score,
            "description": self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestSample":
        """从字典创建"""
        return cls(
            sample_id=data["sample_id"],
            text=data["text"],
            genre=data.get("genre", "其他"),
            expected_ai_score=data.get("expected_ai_score"),
            description=data.get("description", "")
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
    """测试样本管理器"""
    
    def __init__(self, samples: Optional[List[TestSample]] = None):
        self.samples = samples or DEFAULT_TEST_SAMPLES.copy()
        self._sample_index = {s.sample_id: s for s in self.samples}
    
    def get_sample(self, sample_id: str) -> Optional[TestSample]:
        """根据ID获取样本"""
        return self._sample_index.get(sample_id)
    
    def get_samples_by_genre(self, genre: str) -> List[TestSample]:
        """根据题材获取样本"""
        return [s for s in self.samples if s.genre == genre]
    
    def get_random_samples(self, count: int) -> List[TestSample]:
        """随机获取指定数量的样本"""
        import random
        return random.sample(self.samples, min(count, len(self.samples)))

    def get_samples(self, count: int) -> List[TestSample]:
        """按数量获取样本，兼容进化引擎的批量取样接口"""
        return self.get_random_samples(count)
    
    def add_sample(self, sample: TestSample):
        """添加样本"""
        if sample.sample_id in self._sample_index:
            raise ValueError(f"样本ID {sample.sample_id} 已存在")
        self.samples.append(sample)
        self._sample_index[sample.sample_id] = sample
    
    def remove_sample(self, sample_id: str) -> bool:
        """移除样本"""
        if sample_id not in self._sample_index:
            return False
        sample = self._sample_index[sample_id]
        self.samples.remove(sample)
        del self._sample_index[sample_id]
        return True
    
    def get_all_samples(self) -> List[TestSample]:
        """获取所有样本"""
        return self.samples.copy()
    
    def get_sample_count(self) -> int:
        """获取样本数量"""
        return len(self.samples)
    
    def get_genres(self) -> List[str]:
        """获取所有题材"""
        return list(set(s.genre for s in self.samples))
    
    def save_to_file(self, file_path: Path):
        """保存到文件"""
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
        genre_count = {}
        for sample in self.samples:
            genre_count[sample.genre] = genre_count.get(sample.genre, 0) + 1
        
        return {
            "total_samples": len(self.samples),
            "genres": self.get_genres(),
            "genre_distribution": genre_count
        }
