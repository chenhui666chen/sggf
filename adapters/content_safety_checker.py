"""
内容安全检查与自动修复工具

用于检测和修复可能触发 DashScope 内容安全检查的提示词
"""

import re
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class ContentSafetyIssue:
    """内容安全问题"""
    keyword: str
    category: str
    severity: str  # high, medium, low
    suggestions: List[str]


class ContentSafetyChecker:
    """内容安全检查器"""
    
    # 敏感词库（按类别分类）
    SENSITIVE_KEYWORDS = {
        "violence": {
            "high": ["杀", "死", "血", "伤", "武器", "枪", "刀", "剑", "砍", "刺", "打击", "击打", "打", "击", "攻击", "暴力", "战斗", "战争", "屠杀", "谋杀", "伤害", "流血", "伤口", "尸体", "死亡"],
            "medium": ["击倒", "击败", "制服", "战斗", "交锋", "对峙"],
            "low": ["对抗", "较量", "比武", "切磋"]
        },
        "sexual": {
            "high": ["裸", "胸", "臀", "性感", "诱惑", "色情", "淫秽", "露骨", "身体", "肌肤", "曲线", "丰满", "性感", "诱惑"],
            "medium": ["美丽", "漂亮", "迷人", "动人"],
            "low": ["好看", "可爱", "俊俏"]
        },
        "political": {
            "high": ["领导人", "政党", "选举", "政治", "政府", "政权", "革命", "抗议", "示威", "游行", "政治人物"],
            "medium": ["政策", "法律", "法规"],
            "low": ["社会", "公民", "权利"]
        },
        "illegal": {
            "high": ["毒品", "赌博", "犯罪", "违法", "非法", "走私", "诈骗", "盗窃", "抢劫", "绑架", "勒索"],
            "medium": ["危险", "风险", "警告"],
            "low": ["注意", "小心"]
        }
    }
    
    # 替换建议库
    REPLACEMENT_SUGGESTIONS = {
        "violence": {
            "杀": ["击败", "制服", "战胜"],
            "死": ["倒下", "失去意识", "战败"],
            "血": ["红光", "光芒", "能量"],
            "伤": ["受损", "痕迹", "印记"],
            "武器": ["装备", "器具", "工具"],
            "枪": ["法器", "宝物", "道具"],
            "刀": ["利刃", "兵刃", "法剑"],
            "剑": ["长兵", "法剑", "兵器"],
            "砍": ["挥舞", "施展", "使用"],
            "刺": ["突进", "冲锋", "攻击"],
            "打击": ["冲击", "影响", "触及"],
            "击打": ["照射", "作用", "触及"],
            "打": ["击打", "攻击", "施展"],
            "击": ["攻击", "打击", "施展"],
            "攻击": ["进攻", "出击", "施展"],
            "暴力": ["激烈", "紧张", "激烈"],
            "战斗": ["交锋", "对决", "较量"],
            "战争": ["纷争", "冲突", "争端"],
            "屠杀": ["击败", "制服", "清除"],
            "谋杀": ["击败", "制服", "清除"],
            "伤害": ["影响", "波及", "触及"],
            "流血": ["受伤", "受损", "印记"],
            "伤口": ["伤痕", "印记", "痕迹"],
            "尸体": ["倒地者", "战败者", "失去意识者"],
            "死亡": ["倒下", "失去意识", "战败"]
        },
        "sexual": {
            "裸": ["身着", "穿着", "披着"],
            "胸": ["身躯", "身姿", "体态"],
            "臀": ["身形", "身姿", "体态"],
            "性感": ["美丽", "动人", "迷人"],
            "诱惑": ["吸引", "魅力", "吸引力"],
            "色情": ["美丽", "动人", "迷人"],
            "淫秽": ["美丽", "动人", "迷人"],
            "露骨": ["明显", "清晰", "突出"],
            "身体": ["身姿", "体态", "身形"],
            "肌肤": ["皮肤", "面容", "外表"],
            "曲线": ["身姿", "体态", "轮廓"],
            "丰满": ["匀称", "协调", "优美"]
        },
        "political": {
            "领导人": ["长者", "智者", "领袖"],
            "政党": ["团体", "组织", "阵营"],
            "选举": ["推举", "选拔", "选拔"],
            "政治": ["治理", "管理", "统治"],
            "政府": ["官府", "朝廷", "管理机构"],
            "政权": ["统治", "权力", "权威"],
            "革命": ["变革", "更替", "转变"],
            "抗议": ["反对", "异议", "不满"],
            "示威": ["表达", "诉求", "呼吁"],
            "游行": ["聚集", "集会", "聚会"],
            "政治人物": ["重要人物", "关键人物", "核心人物"]
        },
        "illegal": {
            "毒品": ["药物", "药剂", "丹药"],
            "赌博": ["博彩", "游戏", "娱乐"],
            "犯罪": ["违规", "违法", "不当行为"],
            "违法": ["违规", "不当", "越界"],
            "非法": ["违规", "不当", "越界"],
            "走私": ["运输", "携带", "运送"],
            "诈骗": ["欺骗", "误导", "蒙蔽"],
            "盗窃": ["拿取", "获取", "取得"],
            "抢劫": ["夺取", "获取", "拿取"],
            "绑架": ["带走", "控制", "限制"],
            "勒索": ["要求", "索取", "请求"]
        }
    }
    
    def __init__(self):
        self.issues: List[ContentSafetyIssue] = []
    
    def check(self, prompt: str) -> List[ContentSafetyIssue]:
        """
        检查提示词中的内容安全问题
        
        Args:
            prompt: 待检查的提示词
            
        Returns:
            发现的问题列表
        """
        self.issues = []
        
        for category, severity_levels in self.SENSITIVE_KEYWORDS.items():
            for severity, keywords in severity_levels.items():
                for keyword in keywords:
                    if keyword in prompt:
                        suggestions = self.REPLACEMENT_SUGGESTIONS.get(category, {}).get(keyword, [])
                        self.issues.append(ContentSafetyIssue(
                            keyword=keyword,
                            category=category,
                            severity=severity,
                            suggestions=suggestions
                        ))

        # 处理重叠命中，避免“击打/打击”与单字“击/打”同时命中导致描述和替换噪声
        detected_keywords = {issue.keyword for issue in self.issues}
        if "击打" in detected_keywords or "打击" in detected_keywords:
            self.issues = [issue for issue in self.issues if issue.keyword not in {"击", "打"}]
        
        return self.issues
    
    def auto_fix(self, prompt: str, strategy: str = "conservative") -> str:
        """
        自动修复提示词
        
        Args:
            prompt: 原始提示词
            strategy: 修复策略
                - conservative: 保守策略，只替换高风险词汇
                - moderate: 中等策略，替换高、中风险词汇
                - aggressive: 激进策略，替换所有敏感词汇
                
        Returns:
            修复后的提示词
        """
        issues = self.check(prompt)
        
        # 根据策略筛选需要修复的问题
        if strategy == "conservative":
            issues_to_fix = [i for i in issues if i.severity == "high"]
        elif strategy == "moderate":
            issues_to_fix = [i for i in issues if i.severity in ["high", "medium"]]
        else:  # aggressive
            issues_to_fix = issues
        
        # 按优先级排序（高风险优先）
        issues_to_fix.sort(key=lambda x: {
            "high": 0,
            "medium": 1,
            "low": 2
        }.get(x.severity, 3))
        
        replacement_map: Dict[str, str] = {}
        for issue in issues_to_fix:
            if not issue.suggestions:
                continue
            if issue.keyword not in replacement_map:
                replacement_map[issue.keyword] = issue.suggestions[0]

        if not replacement_map:
            return prompt

        # 单次扫描原始文本，避免把替换结果再次命中并继续替换
        ordered_keywords = sorted(replacement_map.keys(), key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(keyword) for keyword in ordered_keywords))
        fixed_prompt = pattern.sub(lambda m: replacement_map.get(m.group(0), m.group(0)), prompt)
        return fixed_prompt
    
    def get_fix_suggestions(self, prompt: str) -> Dict[str, List[Tuple[str, List[str]]]]:
        """
        获取修复建议
        
        Args:
            prompt: 原始提示词
            
        Returns:
            按类别分组的修复建议
            {
                "violence": [("杀", ["击败", "制服"]), ...],
                "sexual": [...],
                ...
            }
        """
        issues = self.check(prompt)
        suggestions_by_category: Dict[str, List[Tuple[str, List[str]]]] = {}
        
        for issue in issues:
            if issue.category not in suggestions_by_category:
                suggestions_by_category[issue.category] = []
            
            suggestions_by_category[issue.category].append(
                (issue.keyword, issue.suggestions)
            )
        
        return suggestions_by_category
    
    def generate_safe_prompt(self, prompt: str, max_attempts: int = 3) -> Tuple[str, bool]:
        """
        生成安全提示词（多次尝试）
        
        Args:
            prompt: 原始提示词
            max_attempts: 最大尝试次数
            
        Returns:
            (修复后的提示词, 是否成功)
        """
        current_prompt = prompt
        strategies = ["conservative", "moderate", "aggressive"]
        
        for attempt, strategy in enumerate(strategies[:max_attempts]):
            fixed_prompt = self.auto_fix(current_prompt, strategy=strategy)
            
            # 检查是否还有高风险问题
            issues = self.check(fixed_prompt)
            high_risk_issues = [i for i in issues if i.severity == "high"]
            
            if not high_risk_issues:
                return fixed_prompt, True
            
            current_prompt = fixed_prompt
        
        return current_prompt, False


def check_and_fix_prompt(prompt: str, strategy: str = "conservative") -> Tuple[str, List[ContentSafetyIssue], str]:
    """
    检查并修复提示词（便捷函数）
    
    Args:
        prompt: 原始提示词
        strategy: 修复策略
        
    Returns:
        (修复后的提示词, 发现的问题, 修复说明)
    """
    checker = ContentSafetyChecker()
    issues = checker.check(prompt)
    
    if not issues:
        return prompt, [], "提示词未检测到敏感内容"
    
    # 生成修复后的提示词
    fixed_prompt = checker.auto_fix(prompt, strategy=strategy)
    
    # 生成修复说明
    fix_description = f"检测到 {len(issues)} 个敏感词，已自动修复"
    
    # 按类别统计
    category_count = {}
    for issue in issues:
        category_count[issue.category] = category_count.get(issue.category, 0) + 1
    
    category_desc = ", ".join([f"{cat}({count})" for cat, count in category_count.items()])
    fix_description += f"：{category_desc}"
    
    return fixed_prompt, issues, fix_description


if __name__ == "__main__":
    # 测试示例
    test_prompts = [
        "一个手持武器的战士，背景是战场",
        "一个受伤流血的人躺在地上",
        "一个性感的女子，身材丰满",
        "政治人物在选举中发表演讲",
    ]
    
    checker = ContentSafetyChecker()
    
    for prompt in test_prompts:
        print(f"\n原始提示词: {prompt}")
        print("-" * 50)
        
        issues = checker.check(prompt)
        print(f"检测到 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  - [{issue.severity}] {issue.keyword} ({issue.category})")
            if issue.suggestions:
                print(f"    建议: {', '.join(issue.suggestions)}")
        
        fixed_prompt, success = checker.generate_safe_prompt(prompt)
        print(f"\n修复后: {fixed_prompt}")
        print(f"状态: {'✅ 成功' if success else '⚠️ 仍有风险'}")
