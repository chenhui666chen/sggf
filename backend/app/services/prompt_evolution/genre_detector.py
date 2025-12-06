"""
题材检测器 - 自动识别文本题材

支持检测：玄幻、都市、言情、悬疑、通用
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GenreDetector:
    """题材检测器"""
    
    def __init__(self):
        # 题材特征关键词库
        self.genre_keywords = {
            "玄幻": [
                # 修炼相关
                "修炼", "炼体", "炼气", "灵气", "真气", "内力", "功法", "心法",
                # 境界相关
                "境界", "突破", "元婴", "金丹", "筑基", "化神", "渡劫", "飞升",
                # 物品相关
                "丹药", "法宝", "灵石", "灵药", "法器", "符箓", "阵法",
                # 人物相关
                "修士", "仙人", "妖兽", "灵兽", "天才", "废材",
                # 组织地点
                "宗门", "长老", "掌门", "弟子", "洞府", "秘境", "传承",
                # 其他特征
                "神通", "法术", "仙", "妖", "魔", "灵", "道"
            ],
            "都市": [
                # 职场相关
                "公司", "总裁", "总经理", "秘书", "老板", "员工", "办公室", "会议",
                # 商业相关
                "股票", "商场", "投资", "合同", "生意", "项目", "市场",
                # 校园相关
                "大学", "高中", "班级", "同学", "宿舍", "食堂", "老师", "学生",
                # 现代物品
                "手机", "电脑", "汽车", "地铁", "公交", "电梯",
                # 场所
                "咖啡厅", "酒吧", "ktv", "商场", "餐厅", "医院",
                # 其他
                "都市", "城市", "现代"
            ],
            "言情": [
                # 感情动作
                "恋爱", "喜欢", "爱情", "心动", "暗恋", "表白", "约会", "告白",
                # 关系称呼
                "男朋友", "女朋友", "前任", "前男友", "前女友", "老公", "老婆",
                # 情感状态
                "分手", "复合", "思念", "想念", "牵挂",
                # 亲密行为
                "吻", "拥抱", "牵手", "亲吻", "抱",
                # 情感描写
                "心跳", "脸红", "害羞", "甜蜜", "浪漫", "温柔", "心疼", "宠溺",
                # 情感词
                "爱", "情", "恋", "喜", "欢"
            ],
            "悬疑": [
                # 案件相关
                "案件", "凶手", "嫌疑人", "受害者", "目击者",
                # 侦查相关
                "线索", "推理", "侦探", "警察", "调查", "证据", "现场", "破案",
                # 犯罪相关
                "尸体", "谋杀", "杀人", "死亡", "失踪", "绑架",
                # 氛围词
                "真相", "阴谋", "诡异", "恐怖", "神秘", "悬疑", "惊悚",
                # 场景
                "密室", "现场", "血迹", "指纹"
            ]
        }
    
    def detect(self, text: str, threshold: int = 3) -> str:
        """
        基于关键词检测文本题材
        
        Args:
            text: 待检测文本
            threshold: 最小匹配阈值（关键词命中次数）
        
        Returns:
            检测到的题材（玄幻/都市/言情/悬疑/通用）
        """
        if not text or len(text) < 50:
            logger.warning("文本过短，无法准确检测题材")
            return "通用"
        
        # 统计各题材关键词命中数
        genre_scores = {}
        
        for genre, keywords in self.genre_keywords.items():
            score = 0
            matched_keywords = []
            
            for keyword in keywords:
                # 计算关键词出现次数
                count = len(re.findall(re.escape(keyword), text))
                if count > 0:
                    score += count
                    matched_keywords.append(f"{keyword}({count})")
            
            genre_scores[genre] = score
            
            if score > 0:
                logger.debug(f"题材「{genre}」得分: {score}, 匹配: {', '.join(matched_keywords[:5])}")
        
        # 找出得分最高的题材
        max_score = max(genre_scores.values())
        
        if max_score == 0:
            logger.info("未检测到明显题材特征，返回通用")
            return "通用"
        
        if max_score < threshold:
            logger.info(f"最高得分({max_score})低于阈值({threshold})，返回通用")
            return "通用"
        
        # 找出得分最高的题材
        detected_genre = max(genre_scores.items(), key=lambda x: x[1])[0]
        
        # 计算优势度（最高分与第二高分的差距）
        sorted_scores = sorted(genre_scores.values(), reverse=True)
        if len(sorted_scores) > 1:
            advantage = sorted_scores[0] - sorted_scores[1]
            # 如果优势不明显（差距<30%），返回通用
            if advantage < sorted_scores[0] * 0.3:
                logger.info(f"题材优势不明显(差距:{advantage}，最高:{sorted_scores[0]})，返回通用")
                return "通用"
        
        logger.info(f"🎭 检测到题材: {detected_genre} (得分: {genre_scores[detected_genre]})")
        return detected_genre
    
    def detect_from_samples(self, samples: list) -> str:
        """
        从多个样本中检测题材（综合判断）
        
        Args:
            samples: 样本列表，每个样本包含 'original' 字段
        
        Returns:
            检测到的题材
        """
        if not samples:
            return "通用"
        
        # 收集所有样本的检测结果
        genre_votes = {}
        
        # 最多检测前3个样本
        for sample in samples[:3]:
            text = sample.text if hasattr(sample, 'text') else ""
            if text:
                genre = self.detect(text)
                genre_votes[genre] = genre_votes.get(genre, 0) + 1
        
        if not genre_votes:
            return "通用"
        
        # 找出得票最多的题材
        detected_genre = max(genre_votes.items(), key=lambda x: x[1])[0]
        
        logger.info(f"🎭 综合检测结果: {detected_genre} (投票: {genre_votes})")
        return detected_genre


# 全局单例
_detector = None

def get_genre_detector() -> GenreDetector:
    """获取题材检测器单例"""
    global _detector
    if _detector is None:
        _detector = GenreDetector()
    return _detector
