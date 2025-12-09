"""
通用题材评审权重模块

供工作流评审 + 内容进化器评审共用
支持8种题材的差异化评审标准
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class Genre(str, Enum):
    """题材类型"""
    XIUXIAN = "修仙"
    XUANHUAN = "玄幻"
    DUSHI = "都市"
    XUANYI = "悬疑"
    YANQING = "言情"
    DANMEI = "耽美"
    KEHUAN = "科幻"
    CHUNWENXUE = "纯文学"
    GENERAL = "通用"


@dataclass
class EvaluationDimension:
    """评估维度定义"""
    name: str                    # 维度名称
    description: str             # 维度描述
    weight: float                # 权重 (0-1)
    key_indicators: List[str]    # 关键指标
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "weight": self.weight,
            "key_indicators": self.key_indicators,
        }


@dataclass
class GenreEvaluationProfile:
    """题材评估配置"""
    genre: str
    genre_name_cn: str
    description: str
    
    # 核心维度权重
    cool_point_weight: float = 0.20       # 爽点效果
    rhythm_weight: float = 0.20           # 节奏把控
    hook_weight: float = 0.15             # 阅读钩子
    immersion_weight: float = 0.15        # 代入感
    writing_weight: float = 0.15          # 文笔流畅度
    consistency_weight: float = 0.15      # 设定一致性
    
    # 题材专属检测项
    special_checks: List[str] = field(default_factory=list)
    
    # 爽点检测重点
    cool_point_focus: List[str] = field(default_factory=list)
    
    # 节奏检测重点
    rhythm_focus: str = ""
    
    # 评审提示词模板
    evaluation_prompt_template: str = ""
    
    def get_weights(self) -> Dict[str, float]:
        """获取权重字典"""
        return {
            "cool_point": self.cool_point_weight,
            "rhythm": self.rhythm_weight,
            "hook": self.hook_weight,
            "immersion": self.immersion_weight,
            "writing": self.writing_weight,
            "consistency": self.consistency_weight,
        }
    
    def calculate_weighted_score(self, scores: Dict[str, float]) -> float:
        """计算加权总分"""
        weights = self.get_weights()
        total = 0.0
        weight_sum = 0.0
        
        for key, weight in weights.items():
            if key in scores:
                total += scores[key] * weight
                weight_sum += weight
        
        return total / weight_sum if weight_sum > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "genre": self.genre,
            "genre_name_cn": self.genre_name_cn,
            "description": self.description,
            "weights": self.get_weights(),
            "special_checks": self.special_checks,
            "cool_point_focus": self.cool_point_focus,
            "rhythm_focus": self.rhythm_focus,
        }


# ==================== 8种题材评审配置 ====================

GENRE_EVALUATION_PROFILES: Dict[str, GenreEvaluationProfile] = {
    
    # 修仙类
    "修仙": GenreEvaluationProfile(
        genre="修仙",
        genre_name_cn="修仙",
        description="以修炼境界为核心，追求突破爽感和资源获取",
        cool_point_weight=0.30,      # 爽点最重要
        rhythm_weight=0.20,
        hook_weight=0.15,
        immersion_weight=0.15,
        writing_weight=0.10,
        consistency_weight=0.10,
        cool_point_focus=[
            "境界突破",
            "越级战斗",
            "获得珍稀资源/功法/法宝",
            "打脸装逼",
            "扮猪吃虎",
        ],
        rhythm_focus="每5-8章小突破，每15-20章大突破，每卷一次境界跨越",
        special_checks=[
            "境界体系是否一致",
            "战力对比是否合理",
            "资源获取是否有铺垫",
        ],
        evaluation_prompt_template="""【修仙类评审重点】
1. 爽点密度：是否有足够的突破/打脸/获宝场景？
2. 境界合理性：战力体系是否自洽？越级战斗是否有合理解释？
3. 节奏感：升级节奏是否张弛有度？有无拖沓？
4. 资源体系：灵石/丹药/功法的获取是否有吸引力？""",
    ),
    
    # 玄幻类
    "玄幻": GenreEvaluationProfile(
        genre="玄幻",
        genre_name_cn="玄幻",
        description="以血脉觉醒和力量体系为核心，追求热血战斗",
        cool_point_weight=0.30,
        rhythm_weight=0.20,
        hook_weight=0.15,
        immersion_weight=0.15,
        writing_weight=0.10,
        consistency_weight=0.10,
        cool_point_focus=[
            "血脉觉醒",
            "力量突破",
            "越级战斗",
            "身世揭秘",
            "命运逆袭",
        ],
        rhythm_focus="每5-10章有战斗高潮，血脉觉醒节点分布均匀",
        special_checks=[
            "力量体系是否清晰",
            "血脉设定是否有吸引力",
            "战斗场面是否有张力",
        ],
        evaluation_prompt_template="""【玄幻类评审重点】
1. 战斗张力：战斗场面是否热血？描写是否有画面感？
2. 力量体系：等级划分是否清晰？突破是否有仪式感？
3. 血脉魅力：血脉设定是否独特？觉醒过程是否有爽感？
4. 节奏把控：打斗与日常是否交替得当？""",
    ),
    
    # 都市类
    "都市": GenreEvaluationProfile(
        genre="都市",
        genre_name_cn="都市",
        description="以商战博弈和人际权谋为核心，追求逆袭打脸",
        cool_point_weight=0.30,
        rhythm_weight=0.20,
        hook_weight=0.15,
        immersion_weight=0.15,
        writing_weight=0.10,
        consistency_weight=0.10,
        cool_point_focus=[
            "打脸逆袭",
            "商战胜利",
            "财富跨越",
            "身份反转",
            "扮猪吃虎",
        ],
        rhythm_focus="每5章小项目/小冲突，每卷大交易/大逆袭",
        special_checks=[
            "商业逻辑是否合理",
            "人物关系是否立体",
            "社会规则是否真实",
        ],
        evaluation_prompt_template="""【都市类评审重点】
1. 逆袭爽感：打脸场景是否解气？反转是否出乎意料？
2. 商业逻辑：商战情节是否有说服力？不能太离谱
3. 人物魅力：主角是否有个人魅力？配角是否鲜活？
4. 现实感：社会规则描写是否有代入感？""",
    ),
    
    # 悬疑类
    "悬疑": GenreEvaluationProfile(
        genre="悬疑",
        genre_name_cn="悬疑",
        description="以线索布局和反转揭秘为核心，追求紧张刺激",
        cool_point_weight=0.15,
        rhythm_weight=0.15,
        hook_weight=0.25,            # 钩子最重要
        immersion_weight=0.20,       # 代入感很重要
        writing_weight=0.10,
        consistency_weight=0.15,     # 逻辑一致性重要
        cool_point_focus=[
            "真相揭露",
            "意外反转",
            "关键线索发现",
            "危机解除",
        ],
        rhythm_focus="线索释放节奏均匀，反转不宜过密，每卷至少一个大反转",
        special_checks=[
            "伏笔是否有回收",
            "逻辑是否严密",
            "线索是否公平呈现",
        ],
        evaluation_prompt_template="""【悬疑类评审重点】
1. 悬念控制：悬念是否足够吸引人？信息释放节奏是否合理？
2. 逻辑严密：推理过程是否经得起推敲？有无逻辑漏洞？
3. 反转质量：反转是否出乎意料又在情理之中？
4. 伏笔回收：前期埋的伏笔是否有呼应？""",
    ),
    
    # 言情类
    "言情": GenreEvaluationProfile(
        genre="言情",
        genre_name_cn="言情",
        description="以情感发展和情感里程碑为核心，追求心动与共情",
        cool_point_weight=0.15,
        rhythm_weight=0.15,
        hook_weight=0.15,
        immersion_weight=0.25,       # 代入感最重要
        writing_weight=0.20,         # 文笔很重要
        consistency_weight=0.10,
        cool_point_focus=[
            "心动时刻",
            "甜蜜互动",
            "表白/在一起",
            "误会解除",
            "虐后甜/虐心高潮",
        ],
        rhythm_focus="甜虐交替，情感里程碑分布合理（相遇→暧昧→确认→考验→HE）",
        special_checks=[
            "情感发展是否自然",
            "人物性格是否一致",
            "感情线是否有张力",
        ],
        evaluation_prompt_template="""【言情类评审重点】
1. 情感真实：情感描写是否细腻？能否引起共鸣？
2. 人物魅力：男女主是否有吸引力？CP感是否强？
3. 节奏把控：甜虐比例是否合适？是否有读者期待的糖？
4. 代入感：读者是否能代入主角视角？""",
    ),
    
    # 耽美类
    "耽美": GenreEvaluationProfile(
        genre="耽美",
        genre_name_cn="耽美",
        description="以情感递进和角色魅力为核心，追求暧昧张力",
        cool_point_weight=0.15,
        rhythm_weight=0.15,
        hook_weight=0.15,
        immersion_weight=0.25,
        writing_weight=0.20,
        consistency_weight=0.10,
        cool_point_focus=[
            "暧昧张力",
            "心动时刻",
            "表白/在一起",
            "甜蜜互动",
            "身份揭秘（如有）",
        ],
        rhythm_focus="暧昧期不宜过短，感情递进要有层次感",
        special_checks=[
            "攻受人设是否鲜明",
            "互动是否有化学反应",
            "情感发展是否自然",
        ],
        evaluation_prompt_template="""【耽美类评审重点】
1. 人物魅力：攻受人设是否有吸引力？性格是否立体？
2. 化学反应：两人互动是否有火花？暧昧氛围是否到位？
3. 情感层次：感情发展是否有层次？不能太突兀
4. 文笔质感：描写是否细腻有质感？""",
    ),
    
    # 科幻类
    "科幻": GenreEvaluationProfile(
        genre="科幻",
        genre_name_cn="科幻",
        description="以科技设定和星际探索为核心，追求创新与宏大",
        cool_point_weight=0.20,
        rhythm_weight=0.15,
        hook_weight=0.15,
        immersion_weight=0.20,
        writing_weight=0.15,
        consistency_weight=0.15,     # 科技设定一致性重要
        cool_point_focus=[
            "科技突破",
            "星际探索发现",
            "文明接触",
            "危机解决",
            "真相揭示",
        ],
        rhythm_focus="探索与冲突交替，科技概念不宜过密",
        special_checks=[
            "科技设定是否自洽",
            "世界观是否完整",
            "硬科幻元素是否合理",
        ],
        evaluation_prompt_template="""【科幻类评审重点】
1. 创意新颖：科幻概念是否有创新？世界观是否有吸引力？
2. 设定自洽：科技体系是否经得起推敲？不能前后矛盾
3. 故事性：科幻元素是否服务于故事？不能为科幻而科幻
4. 视觉感：场景描写是否有画面感？""",
    ),
    
    # 纯文学类
    "纯文学": GenreEvaluationProfile(
        genre="纯文学",
        genre_name_cn="纯文学",
        description="以内心挖掘和诗意表达为核心，追求思想深度",
        cool_point_weight=0.10,
        rhythm_weight=0.15,
        hook_weight=0.10,
        immersion_weight=0.20,
        writing_weight=0.30,         # 文笔最重要
        consistency_weight=0.15,
        cool_point_focus=[
            "顿悟时刻",
            "情感高潮",
            "人物成长",
            "诗意片段",
        ],
        rhythm_focus="不追求快节奏，注重情绪流动和思想沉淀",
        special_checks=[
            "主题是否深刻",
            "人物内心是否立体",
            "语言是否有文学性",
        ],
        evaluation_prompt_template="""【纯文学类评审重点】
1. 文笔质量：语言是否有文学性？表达是否精准？
2. 思想深度：是否有值得思考的主题？人性挖掘是否到位？
3. 人物刻画：人物内心是否丰富立体？
4. 诗意表达：是否有打动人心的片段？""",
    ),
    
    # 通用（兜底）
    "通用": GenreEvaluationProfile(
        genre="通用",
        genre_name_cn="通用",
        description="通用评审标准，适用于未明确题材的作品",
        cool_point_weight=0.20,
        rhythm_weight=0.20,
        hook_weight=0.15,
        immersion_weight=0.15,
        writing_weight=0.15,
        consistency_weight=0.15,
        cool_point_focus=[
            "情节高潮",
            "转折反转",
            "悬念揭示",
        ],
        rhythm_focus="叙事节奏均衡，高低起伏交替",
        special_checks=[
            "情节是否连贯",
            "人物是否立体",
            "叙事是否流畅",
        ],
        evaluation_prompt_template="""【通用评审重点】
1. 情节吸引力：故事是否引人入胜？
2. 人物塑造：人物是否有特点？
3. 叙事流畅：读起来是否顺畅？
4. 整体质量：有无明显问题？""",
    ),
}


def get_genre_profile(genre: str) -> GenreEvaluationProfile:
    """
    获取题材评估配置
    
    支持模糊匹配，找不到则返回通用配置
    """
    # 精确匹配
    if genre in GENRE_EVALUATION_PROFILES:
        return GENRE_EVALUATION_PROFILES[genre]
    
    # 模糊匹配
    genre_lower = genre.lower()
    for key, profile in GENRE_EVALUATION_PROFILES.items():
        if key.lower() in genre_lower or genre_lower in key.lower():
            return profile
    
    # 关键词匹配
    keyword_map = {
        "修仙": ["修仙", "修真", "仙侠", "飞升", "境界"],
        "玄幻": ["玄幻", "异能", "魔法", "斗气", "血脉"],
        "都市": ["都市", "现代", "商战", "总裁", "职场"],
        "悬疑": ["悬疑", "推理", "探案", "刑侦", "恐怖"],
        "言情": ["言情", "甜宠", "虐恋", "婚恋", "校园"],
        "耽美": ["耽美", "BL", "同人"],
        "科幻": ["科幻", "星际", "机甲", "末日", "赛博"],
        "纯文学": ["文学", "现实主义", "人文"],
    }
    
    for key, keywords in keyword_map.items():
        for kw in keywords:
            if kw in genre:
                return GENRE_EVALUATION_PROFILES[key]
    
    # 返回通用
    return GENRE_EVALUATION_PROFILES["通用"]


def build_evaluation_prompt(
    genre: str,
    content: str,
    context: Dict[str, Any] = None
) -> str:
    """
    构建评审提示词
    
    Args:
        genre: 题材
        content: 待评审内容
        context: 上下文信息（角色设定、前情等）
        
    Returns:
        评审提示词
    """
    profile = get_genre_profile(genre)
    weights = profile.get_weights()
    
    context_str = ""
    if context:
        if context.get("characters"):
            context_str += f"\n【角色设定】\n{context['characters'][:500]}"
        if context.get("world"):
            context_str += f"\n【世界观】\n{context['world'][:500]}"
        if context.get("previous"):
            context_str += f"\n【前情】\n{context['previous'][:500]}"
    
    prompt = f"""你是一位专业的{profile.genre_name_cn}类网文评审专家。请对以下内容进行质量评审。

{profile.evaluation_prompt_template}

【评审维度权重】
- 爽点效果 (cool_point): {weights['cool_point']*100:.0f}%
- 节奏把控 (rhythm): {weights['rhythm']*100:.0f}%
- 阅读钩子 (hook): {weights['hook']*100:.0f}%
- 代入感 (immersion): {weights['immersion']*100:.0f}%
- 文笔流畅 (writing): {weights['writing']*100:.0f}%
- 设定一致 (consistency): {weights['consistency']*100:.0f}%

【题材专属爽点】
{', '.join(profile.cool_point_focus)}

【节奏要求】
{profile.rhythm_focus}

【特殊检查项】
{', '.join(profile.special_checks)}
{context_str}

【待评审内容】
{content[:3000]}

【输出格式】
请以JSON格式输出各维度评分（0-100），以及简短评语：
```json
{{
    "cool_point": 分数,
    "rhythm": 分数,
    "hook": 分数,
    "immersion": 分数,
    "writing": 分数,
    "consistency": 分数,
    "comment": "简短评语（50字内）"
}}
```"""
    
    return prompt


def get_all_genres() -> List[str]:
    """获取所有支持的题材列表"""
    return [g for g in GENRE_EVALUATION_PROFILES.keys() if g != "通用"]


def get_genre_summary() -> Dict[str, Dict[str, Any]]:
    """获取所有题材配置摘要"""
    return {
        genre: profile.to_dict()
        for genre, profile in GENRE_EVALUATION_PROFILES.items()
    }
