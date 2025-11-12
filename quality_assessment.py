"""
质量评估模块 - 小说质量评估和评分系统
"""
from typing import Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class QualityDimension(Enum):
    """质量评估维度"""
    STORY = "story"                    # 故事性
    CHARACTER = "character"            # 人物塑造
    LANGUAGE = "language"              # 语言表达
    STRUCTURE = "structure"            # 结构完整性
    INNOVATION = "innovation"          # 创新性


@dataclass
class QualityMetric:
    """质量指标"""
    name: str                          # 指标名称
    dimension: QualityDimension        # 所属维度
    description: str                   # 指标描述
    weight: float = 1.0                # 权重
    score: float = 0.0                 # 评分（1-10）
    feedback: str = ""                 # 反馈意见
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "dimension": self.dimension.value,
            "description": self.description,
            "weight": self.weight,
            "score": self.score,
            "feedback": self.feedback
        }


@dataclass
class DimensionScore:
    """维度评分"""
    dimension: QualityDimension        # 维度
    metrics: List[QualityMetric] = field(default_factory=list)  # 该维度的所有指标
    dimension_score: float = 0.0       # 维度总分
    weight: float = 1.0                # 维度权重
    
    def calculate_score(self) -> float:
        """计算维度评分"""
        if not self.metrics:
            return 0.0
        
        total_weight = sum(m.weight for m in self.metrics)
        if total_weight == 0:
            return 0.0
        
        weighted_sum = sum(m.score * m.weight for m in self.metrics)
        self.dimension_score = weighted_sum / total_weight
        return self.dimension_score
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "dimension": self.dimension.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "dimension_score": self.dimension_score,
            "weight": self.weight
        }


@dataclass
class QualityAssessmentReport:
    """质量评估报告"""
    content_id: str                    # 内容ID（章节ID等）
    content_type: str                  # 内容类型（chapter, section等）
    
    # 各维度评分
    dimension_scores: Dict[QualityDimension, DimensionScore] = field(default_factory=dict)
    
    # 综合评分
    overall_score: float = 0.0         # 综合评分
    is_excellent: bool = False         # 是否优秀（>8分）
    
    # 评估信息
    assessment_date: str = ""          # 评估日期
    reviewer_name: str = ""            # 评审官名称
    
    # 建议
    strengths: List[str] = field(default_factory=list)  # 优点
    weaknesses: List[str] = field(default_factory=list)  # 缺点
    suggestions: List[str] = field(default_factory=list)  # 改进建议
    
    def calculate_overall_score(self) -> float:
        """计算综合评分"""
        if not self.dimension_scores:
            return 0.0
        
        total_weight = sum(ds.weight for ds in self.dimension_scores.values())
        if total_weight == 0:
            return 0.0
        
        weighted_sum = sum(
            ds.dimension_score * ds.weight 
            for ds in self.dimension_scores.values()
        )
        
        self.overall_score = weighted_sum / total_weight
        self.is_excellent = self.overall_score > 8.0
        
        return self.overall_score
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "content_id": self.content_id,
            "content_type": self.content_type,
            "dimension_scores": {
                dim.value: score.to_dict() 
                for dim, score in self.dimension_scores.items()
            },
            "overall_score": self.overall_score,
            "is_excellent": self.is_excellent,
            "assessment_date": self.assessment_date,
            "reviewer_name": self.reviewer_name,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions
        }


class QualityAssessmentFramework:
    """质量评估框架"""
    
    # 维度权重配置
    DIMENSION_WEIGHTS = {
        QualityDimension.STORY: 0.30,        # 故事性 30%
        QualityDimension.CHARACTER: 0.25,    # 人物塑造 25%
        QualityDimension.LANGUAGE: 0.20,     # 语言表达 20%
        QualityDimension.STRUCTURE: 0.15,    # 结构完整性 15%
        QualityDimension.INNOVATION: 0.10    # 创新性 10%
    }
    
    # 评分标准
    SCORE_STANDARDS = {
        "excellent": (8.0, 10.0),    # 优秀
        "good": (6.0, 8.0),          # 良好
        "fair": (4.0, 6.0),          # 一般
        "poor": (1.0, 4.0)           # 较差
    }
    
    @staticmethod
    def create_assessment_report(content_id: str, content_type: str = "chapter") -> QualityAssessmentReport:
        """创建评估报告"""
        report = QualityAssessmentReport(
            content_id=content_id,
            content_type=content_type
        )
        
        # 初始化各维度
        for dimension in QualityDimension:
            report.dimension_scores[dimension] = DimensionScore(
                dimension=dimension,
                weight=QualityAssessmentFramework.DIMENSION_WEIGHTS[dimension]
            )
        
        return report
    
    @staticmethod
    def add_metric_to_report(report: QualityAssessmentReport, metric: QualityMetric):
        """添加指标到报告"""
        if metric.dimension in report.dimension_scores:
            report.dimension_scores[metric.dimension].metrics.append(metric)
    
    @staticmethod
    def calculate_report_scores(report: QualityAssessmentReport) -> QualityAssessmentReport:
        """计算报告评分"""
        # 计算各维度评分
        for dimension_score in report.dimension_scores.values():
            dimension_score.calculate_score()
        
        # 计算综合评分
        report.calculate_overall_score()
        
        return report
    
    @staticmethod
    def get_score_level(score: float) -> str:
        """获取评分等级"""
        for level, (min_score, max_score) in QualityAssessmentFramework.SCORE_STANDARDS.items():
            if min_score <= score <= max_score:
                return level
        return "unknown"


# 预定义的质量指标模板

def create_story_metrics() -> List[QualityMetric]:
    """创建故事性指标"""
    return [
        QualityMetric(
            name="情节紧凑度",
            dimension=QualityDimension.STORY,
            description="情节是否紧凑、跌宕起伏、有起有伏且符合逻辑，能不断吸引读者的兴趣",
            weight=1.0
        ),
        QualityMetric(
            name="冲突设置合理性",
            dimension=QualityDimension.STORY,
            description="冲突是否具有张力和层次感",
            weight=1.0
        ),
        QualityMetric(
            name="节奏把控",
            dimension=QualityDimension.STORY,
            description="章节节奏是否合理，是否有适当的悬念设置",
            weight=1.0
        )
    ]


def create_character_metrics() -> List[QualityMetric]:
    """创建人物塑造指标"""
    return [
        QualityMetric(
            name="人物立体度",
            dimension=QualityDimension.CHARACTER,
            description="人物形象是否丰满立体，具有多面性的性格特点",
            weight=1.0
        ),
        QualityMetric(
            name="性格一致性",
            dimension=QualityDimension.CHARACTER,
            description="人物的行为、语言、思想是否符合其身份和设定的背景",
            weight=1.0
        ),
        QualityMetric(
            name="成长弧光",
            dimension=QualityDimension.CHARACTER,
            description="人物是否有合理的成长或变化轨迹",
            weight=1.0
        )
    ]


def create_language_metrics() -> List[QualityMetric]:
    """创建语言表达指标"""
    return [
        QualityMetric(
            name="语言流畅度",
            dimension=QualityDimension.LANGUAGE,
            description="语言是否优美流畅",
            weight=1.0
        ),
        QualityMetric(
            name="修辞手法运用",
            dimension=QualityDimension.LANGUAGE,
            description="是否能够运用丰富的修辞手法，如比喻、拟人、夸张等",
            weight=1.0
        ),
        QualityMetric(
            name="风格独特性",
            dimension=QualityDimension.LANGUAGE,
            description="语言风格是否独特鲜明",
            weight=1.0
        ),
        QualityMetric(
            name="画面感营造",
            dimension=QualityDimension.LANGUAGE,
            description="是否能让读者产生强烈的画面感",
            weight=1.0
        )
    ]


def create_structure_metrics() -> List[QualityMetric]:
    """创建结构完整性指标"""
    return [
        QualityMetric(
            name="情节连贯性",
            dimension=QualityDimension.STRUCTURE,
            description="各情节之间是否相互关联，形成完整的叙事结构",
            weight=1.0
        ),
        QualityMetric(
            name="逻辑合理性",
            dimension=QualityDimension.STRUCTURE,
            description="情节发展是否符合逻辑，有无明显漏洞",
            weight=1.0
        ),
        QualityMetric(
            name="章节衔接",
            dimension=QualityDimension.STRUCTURE,
            description="章节之间的过渡是否自然流畅",
            weight=1.0
        )
    ]


def create_innovation_metrics() -> List[QualityMetric]:
    """创建创新性指标"""
    return [
        QualityMetric(
            name="设定新颖性",
            dimension=QualityDimension.INNOVATION,
            description="故事设定是否具有创新性和独特性",
            weight=1.0
        ),
        QualityMetric(
            name="情节原创性",
            dimension=QualityDimension.INNOVATION,
            description="情节发展是否有新意，避免套路化",
            weight=1.0
        ),
        QualityMetric(
            name="视角独特性",
            dimension=QualityDimension.INNOVATION,
            description="叙事视角和手法是否有创新",
            weight=1.0
        )
    ]

