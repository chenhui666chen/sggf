"""
提示词进化系统 - 测试样本管理

提供典型的AI生成文本样本，用于测试提示词的降低AI率效果
🔧 支持动态加载用户项目中的实际文本
"""
from dataclasses import dataclass, field
from typing import List, Optional, Callable
import uuid
import random
import logging

logger = logging.getLogger(__name__)


@dataclass
class TestSample:
    """测试样本"""
    sample_id: str
    text: str
    genre: str          # 题材类型
    description: str    # 样本描述
    source: str = "default"  # 🔧 来源：default/project/custom


# 默认测试样本集 - 典型的AI生成文本
DEFAULT_TEST_SAMPLES: List[TestSample] = [
    TestSample(
        sample_id="sample_001",
        text="""夜幕降临，城市的霓虹灯开始闪烁。李明站在写字楼的落地窗前，看着窗外车水马龙的街道，陷入了沉思。

作为公司最年轻的部门经理，他深知自己肩负的责任。首先，他需要带领团队完成这个季度的业绩目标；其次，他必须处理好与其他部门的协调关系；最后，他还要为即将到来的年度总结做好准备。

"压力确实很大。"他自言自语道，嘴角却不自觉地上扬。因为他知道，正是这些挑战，让他不断成长、不断进步。他相信，只要坚持不懈，未来一定会更加美好。

窗外的夜色越来越深，但李明的心中却充满了希望。""",
        genre="都市",
        description="典型的AI生成都市文，包含完美的三段式结构和正能量结尾"
    ),
    TestSample(
        sample_id="sample_002",
        text="""剑光如虹，划破长空。萧云一剑刺出，剑意直冲云霄，浩然正气弥漫整个擂台。

对面的黑衣人脸色大变，他没想到这个看似普通的少年，竟然隐藏着如此惊人的实力。他连忙后退，同时运转全身功力，试图抵挡这一剑。

然而，一切都已经太迟了。萧云的剑芒如同天河倒悬，携带着无匹的威势，轰然落下。黑衣人惨叫一声，整个人被剑气震飞出去，重重地摔在地上。

"你……你究竟是什么人？"黑衣人颤抖着问道。

萧云收剑而立，淡淡地说道："我只是一个普通的修行者，但我的剑，从不放过任何邪恶之徒。"

周围的观众爆发出雷鸣般的掌声，他们被这精彩的一战深深震撼。""",
        genre="玄幻",
        description="典型的AI生成玄幻文，包含华丽战斗和完美主角"
    ),
    TestSample(
        sample_id="sample_003",
        text="""苏晴推开咖啡馆的门，一阵咖啡的香气扑面而来。她环顾四周，终于在角落的位置看到了等待已久的陈浩。

"等很久了吗？"她微笑着坐下。

"不久，刚到。"陈浩礼貌地回应，将菜单递给她。

两人相对而坐，气氛略显尴尬。这是他们相亲后的第三次见面，虽然彼此都有些好感，但还是缺少那种心动的感觉。

"其实，"苏晴鼓起勇气开口，"我觉得你是一个很好的人，善良、体贴、有责任心。"

陈浩看着她，眼中闪过一丝期待。

"但是，"苏晴继续说道，"感情这种事，不能强求。我希望我们可以做朋友。"

陈浩沉默了片刻，然后微微点头："我理解。谢谢你的坦诚。"

阳光透过玻璃窗洒进来，照在两人身上，一切都显得那么平和而美好。""",
        genre="言情",
        description="典型的AI生成言情文，对话过于礼貌，缺乏真实的情感冲突"
    ),
    # ========== 新增测试样本 ==========
    TestSample(
        sample_id="sample_004",
        text="""深夜的警局，灯火通明。刑警队长张磊盯着墙上的案情分析板，眉头紧锁。

这已经是第三起连环杀人案了。受害者都是年轻女性，死亡时间都在凌晨两点到四点之间，作案手法如出一辙。然而，凶手却没有留下任何有价值的线索。

"队长，法医报告出来了。"小王推门进来，递上一份文件。

张磊接过报告，仔细阅读。突然，他的眼中闪过一丝精光。他发现了一个之前被忽略的细节——三名受害者的指甲缝里，都残留着同一种特殊的化学物质。

"这就是突破口！"张磊猛地站起身，"立刻调查本市所有使用这种化学物质的工厂和实验室！"

真相，终于要浮出水面了。""",
        genre="悬疑",
        description="典型的AI生成悬疑文，逻辑过于清晰，缺乏真实的调查过程"
    ),
    TestSample(
        sample_id="sample_005",
        text="""林晓站在舞台中央，聚光灯打在她身上，仿佛她就是这个世界的中心。

台下坐满了观众，他们的目光都聚焦在这个年仅十八岁的少女身上。这是全国歌唱大赛的总决赛，而她，是最后一个出场的选手。

音乐响起，林晓深吸一口气，开始演唱。她的声音清澈如泉水，又温暖如阳光，每一个音符都直击人心。

当最后一个音符落下，全场陷入了短暂的寂静。随即，雷鸣般的掌声响彻整个会场。评委们纷纷起立，眼中满是赞赏。

"恭喜你，林晓！"主持人激动地宣布，"你就是本届大赛的冠军！"

林晓的眼眶湿润了。这一刻，她知道，所有的付出都是值得的。梦想，终于照进了现实。""",
        genre="都市",
        description="典型的AI生成励志文，情节过于顺利，情感表达直白"
    ),
    TestSample(
        sample_id="sample_006",
        text="""叶辰盘膝坐在山巅，周身灵气如潮水般涌动。他已经在这里闭关三个月了，今天，终于到了突破的关键时刻。

丹田之中，金色的灵力不断凝聚，形成一颗璀璨的金丹。叶辰感受着体内澎湃的力量，嘴角露出一丝笑意。

"金丹期，终于成了！"

他睁开眼睛，目光如电。此刻的他，已经不是三个月前那个被人欺辱的废物了。他要让所有看不起他的人，都付出代价！

天空中，乌云密布，雷电交加。这是天劫！金丹期的修士，必须渡过天劫，才能真正稳固境界。

叶辰仰天长啸，迎着雷劫冲了上去。他的身影在电光中若隐若现，宛如战神降世。

三道天雷过后，叶辰依然屹立不倒。他成功了！从今天起，他将踏上一条全新的修炼之路！""",
        genre="玄幻",
        description="典型的AI生成修仙文，包含废物逆袭、渡劫等套路"
    ),
]


class TestSampleManager:
    """
    测试样本管理器

    🔧 增强功能：
    1. 支持动态加载项目文本作为样本
    2. 支持按题材筛选
    3. 支持随机采样
    4. 支持混合采样（默认+项目）
    """

    def __init__(self, project_sample_loader: Optional[Callable[[], List[dict]]] = None):
        """
        Args:
            project_sample_loader: 可选的项目样本加载器，返回格式：
                [{"text": str, "genre": str, "chapter_title": str}, ...]
        """
        self.default_samples: List[TestSample] = list(DEFAULT_TEST_SAMPLES)
        self.project_samples: List[TestSample] = []
        self.custom_samples: List[TestSample] = []
        self._project_loader = project_sample_loader

    @property
    def samples(self) -> List[TestSample]:
        """获取所有样本（合并默认+项目+自定义）"""
        return self.default_samples + self.project_samples + self.custom_samples

    def load_project_samples(self, max_samples: int = 10, min_text_length: int = 200) -> int:
        """
        🔧 从项目加载样本

        Args:
            max_samples: 最大加载样本数
            min_text_length: 最小文本长度

        Returns:
            加载的样本数量
        """
        if not self._project_loader:
            logger.warning("未配置项目样本加载器")
            return 0

        try:
            raw_samples = self._project_loader()
            loaded_count = 0

            for item in raw_samples:
                text = item.get("text", "")
                if len(text) < min_text_length:
                    continue

                # 截取合适长度的文本片段（300-800字）
                if len(text) > 800:
                    # 随机选择一个起始位置
                    start = random.randint(0, len(text) - 500)
                    # 找到段落边界
                    para_start = text.rfind("\n\n", 0, start)
                    if para_start == -1:
                        para_start = text.rfind("。", 0, start) + 1
                    if para_start <= 0:
                        para_start = start
                    # 截取500-800字
                    text = text[para_start:para_start + random.randint(500, 800)]

                sample = TestSample(
                    sample_id=f"project_{str(uuid.uuid4())[:8]}",
                    text=text.strip(),
                    genre=item.get("genre", "通用"),
                    description=f"项目章节: {item.get('chapter_title', '未知')}",
                    source="project"
                )
                self.project_samples.append(sample)
                loaded_count += 1

                if loaded_count >= max_samples:
                    break

            logger.info(f"📚 从项目加载 {loaded_count} 个样本")
            return loaded_count

        except Exception as e:
            logger.error(f"加载项目样本失败: {e}")
            return 0

    def get_samples(
        self,
        count: Optional[int] = None,
        genre: Optional[str] = None,
        prefer_project: bool = True,
        random_select: bool = True
    ) -> List[TestSample]:
        """
        🔧 获取测试样本（增强版）

        Args:
            count: 需要的样本数量
            genre: 筛选特定题材
            prefer_project: 优先使用项目样本
            random_select: 是否随机选择

        Returns:
            样本列表
        """
        # 筛选可用样本
        available = self.samples
        if genre:
            available = [s for s in available if s.genre == genre]

        if not available:
            available = self.default_samples  # 回退到默认

        # 如果优先项目样本，调整顺序
        if prefer_project and self.project_samples:
            project = [s for s in available if s.source == "project"]
            others = [s for s in available if s.source != "project"]
            available = project + others

        # 随机选择或顺序选择
        if count is None:
            return available

        if random_select and len(available) > count:
            # 🔧 加权随机：项目样本权重更高
            weights = [2.0 if s.source == "project" else 1.0 for s in available]
            selected = []
            temp_available = list(available)
            temp_weights = list(weights)

            for _ in range(min(count, len(available))):
                if not temp_available:
                    break
                idx = random.choices(range(len(temp_available)), weights=temp_weights, k=1)[0]
                selected.append(temp_available.pop(idx))
                temp_weights.pop(idx)

            return selected
        else:
            return available[:count]

    def add_sample(self, text: str, genre: str = "通用", description: str = "") -> TestSample:
        """添加自定义样本"""
        sample = TestSample(
            sample_id=f"custom_{str(uuid.uuid4())[:8]}",
            text=text,
            genre=genre,
            description=description or "用户自定义样本",
            source="custom"
        )
        self.custom_samples.append(sample)
        return sample

    def remove_sample(self, sample_id: str) -> bool:
        """移除样本"""
        for collection in [self.custom_samples, self.project_samples]:
            for i, s in enumerate(collection):
                if s.sample_id == sample_id:
                    collection.pop(i)
                    return True
        return False

    def get_sample_by_id(self, sample_id: str) -> Optional[TestSample]:
        """根据ID获取样本"""
        for s in self.samples:
            if s.sample_id == sample_id:
                return s
        return None

    def get_samples_by_genre(self, genre: str) -> List[TestSample]:
        """根据题材获取样本"""
        return [s for s in self.samples if s.genre == genre]

    def clear_project_samples(self) -> None:
        """清空项目样本"""
        self.project_samples.clear()

    def get_sample_stats(self) -> dict:
        """🔧 获取样本统计信息"""
        genres = {}
        for s in self.samples:
            genres[s.genre] = genres.get(s.genre, 0) + 1

        return {
            "total": len(self.samples),
            "default": len(self.default_samples),
            "project": len(self.project_samples),
            "custom": len(self.custom_samples),
            "by_genre": genres
        }

