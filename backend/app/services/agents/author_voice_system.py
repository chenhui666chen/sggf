"""
作者腔调系统 - 管理和应用作者的独特风格和价值观
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuthorVoiceProfile:
    """作者腔调档案"""
    project_id: int
    
    # 核心腔调要素
    narrative_style: str = ""           # 叙事风格（讽刺/诗意/克制/激情/冷漠等）
    value_system: Dict[str, str] = field(default_factory=dict)  # 价值观（道德立场、人生观等）
    unique_traits: List[str] = field(default_factory=list)      # 独特特征（口头禅、习惯用语等）
    emotional_depth: str = ""           # 情感深度（表面/中等/深层）
    
    # 禁止事项
    forbidden_patterns: List[str] = field(default_factory=list)  # 禁止使用的套路
    
    # 元数据
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        """初始化时设置时间戳"""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "project_id": self.project_id,
            "narrative_style": self.narrative_style,
            "value_system": self.value_system,
            "unique_traits": self.unique_traits,
            "emotional_depth": self.emotional_depth,
            "forbidden_patterns": self.forbidden_patterns,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    def to_prompt_string(self) -> str:
        """转换为提示词字符串"""
        prompt = "【作者腔调定义】\n"
        
        if self.narrative_style:
            prompt += f"- 叙事风格：{self.narrative_style}\n"
        
        if self.value_system:
            prompt += "- 价值观：\n"
            for key, value in self.value_system.items():
                prompt += f"  • {key}：{value}\n"
        
        if self.unique_traits:
            prompt += "- 独特特征：\n"
            for trait in self.unique_traits:
                prompt += f"  • {trait}\n"
        
        if self.emotional_depth:
            prompt += f"- 情感深度：{self.emotional_depth}\n"
        
        if self.forbidden_patterns:
            prompt += "- 禁止使用的套路：\n"
            for pattern in self.forbidden_patterns:
                prompt += f"  • {pattern}\n"
        
        return prompt


class AuthorVoiceManager:
    """作者腔调管理器"""
    
    def __init__(self):
        """初始化管理器"""
        self.voice_profiles: Dict[int, AuthorVoiceProfile] = {}
        
        # 预定义的腔调模板
        self.voice_templates = {
            "冷静克制": {
                "narrative_style": "冷静克制，带有黑色幽默",
                "value_system": {
                    "人性观": "质疑理想主义，强调现实的残酷",
                    "道德观": "相对主义，没有绝对的对错",
                    "人生观": "强调个人选择的代价"
                },
                "unique_traits": ["常用'或许'、'也许'表达不确定性", "冷静观察而非热烈评判"],
                "emotional_depth": "深层",
                "forbidden_patterns": ["杰出", "优美", "完美", "绝对"]
            },
            "诗意浪漫": {
                "narrative_style": "诗意浪漫，充满意象和隐喻",
                "value_system": {
                    "人性观": "相信人性的美好和可能性",
                    "道德观": "强调道德的力量和救赎",
                    "人生观": "生活充满意义和美"
                },
                "unique_traits": ["运用大量比喻和象征", "关注细微的情感变化"],
                "emotional_depth": "深层",
                "forbidden_patterns": ["生硬", "机械", "冷漠"]
            },
            "激情澎湃": {
                "narrative_style": "激情澎湃，充满能量和冲突",
                "value_system": {
                    "人性观": "相信人的潜能和成长",
                    "道德观": "善恶分明，正义必胜",
                    "人生观": "生活是不断的挑战和超越"
                },
                "unique_traits": ["使用短句制造紧张感", "强调行动和结果"],
                "emotional_depth": "中等",
                "forbidden_patterns": ["犹豫", "消极", "放弃"]
            }
        }
    
    def create_voice_profile(self, project_id: int, template_name: Optional[str] = None,
                            custom_config: Optional[Dict[str, Any]] = None) -> AuthorVoiceProfile:
        """
        创建作者腔调档案
        
        Args:
            project_id: 项目ID
            template_name: 使用的模板名称（可选）
            custom_config: 自定义配置（可选）
            
        Returns:
            作者腔调档案
        """
        profile = AuthorVoiceProfile(project_id=project_id)
        
        # 如果指定了模板，使用模板
        if template_name and template_name in self.voice_templates:
            template = self.voice_templates[template_name]
            profile.narrative_style = template.get("narrative_style", "")
            profile.value_system = template.get("value_system", {})
            profile.unique_traits = template.get("unique_traits", [])
            profile.emotional_depth = template.get("emotional_depth", "")
            profile.forbidden_patterns = template.get("forbidden_patterns", [])
        
        # 应用自定义配置
        if custom_config:
            if "narrative_style" in custom_config:
                profile.narrative_style = custom_config["narrative_style"]
            if "value_system" in custom_config:
                profile.value_system.update(custom_config["value_system"])
            if "unique_traits" in custom_config:
                profile.unique_traits.extend(custom_config["unique_traits"])
            if "emotional_depth" in custom_config:
                profile.emotional_depth = custom_config["emotional_depth"]
            if "forbidden_patterns" in custom_config:
                profile.forbidden_patterns.extend(custom_config["forbidden_patterns"])
        
        # 保存档案
        self.voice_profiles[project_id] = profile
        print(f"✅ 已为项目 {project_id} 创建作者腔调档案")
        
        return profile
    
    def get_voice_profile(self, project_id: int) -> Optional[AuthorVoiceProfile]:
        """获取作者腔调档案"""
        return self.voice_profiles.get(project_id)
    
    def apply_voice_to_prompt(self, prompt: str, profile: AuthorVoiceProfile) -> str:
        """
        将作者腔调应用到提示词
        
        Args:
            prompt: 原始提示词
            profile: 作者腔调档案
            
        Returns:
            应用了腔调的提示词
        """
        voice_string = profile.to_prompt_string()
        
        # 在提示词开头插入腔调定义
        enhanced_prompt = f"""{voice_string}

【创作指导】
请严格按照上述作者腔调进行创作，确保：
1. 叙事风格与定义一致
2. 体现价值观和道德立场
3. 使用独特特征和表达方式
4. 避免使用禁止的套路

【原始提示词】
{prompt}"""
        
        return enhanced_prompt
    
    def validate_voice_consistency(self, content: str, profile: AuthorVoiceProfile) -> Dict[str, Any]:
        """
        验证内容与腔调的一致性
        
        Args:
            content: 生成的内容
            profile: 作者腔调档案
            
        Returns:
            一致性检查结果
        """
        result = {
            "consistency_score": 0.0,
            "issues": [],
            "suggestions": []
        }
        
        score = 100.0
        
        # 检查禁止模式
        for pattern in profile.forbidden_patterns:
            if pattern in content:
                result["issues"].append(f"发现禁止模式：'{pattern}'")
                score -= 10
        
        # 检查独特特征的使用
        trait_count = 0
        for trait in profile.unique_traits:
            # 简单的关键词检查
            if any(keyword in content for keyword in trait.split()):
                trait_count += 1
        
        if trait_count == 0 and profile.unique_traits:
            result["suggestions"].append("建议增加更多独特特征的使用")
            score -= 5
        
        # 检查情感深度
        if profile.emotional_depth == "深层":
            # 检查是否有足够的心理描写
            psychological_keywords = ["想到", "觉得", "心想", "意识到", "明白"]
            psych_count = sum(1 for keyword in psychological_keywords if keyword in content)
            if psych_count < 3:
                result["suggestions"].append("建议增加更多心理描写以体现深层情感")
                score -= 5
        
        result["consistency_score"] = max(0, score)
        return result
    
    def list_templates(self) -> List[str]:
        """列出所有可用的腔调模板"""
        return list(self.voice_templates.keys())
    
    def get_template_info(self, template_name: str) -> Optional[Dict[str, Any]]:
        """获取模板信息"""
        return self.voice_templates.get(template_name)


# 全局管理器实例
_voice_manager = AuthorVoiceManager()


def get_voice_manager() -> AuthorVoiceManager:
    """获取全局作者腔调管理器"""
    return _voice_manager


def create_voice_profile(project_id: int, template_name: Optional[str] = None,
                        custom_config: Optional[Dict[str, Any]] = None) -> AuthorVoiceProfile:
    """便捷函数：创建作者腔调档案"""
    return _voice_manager.create_voice_profile(project_id, template_name, custom_config)


def get_voice_profile(project_id: int) -> Optional[AuthorVoiceProfile]:
    """便捷函数：获取作者腔调档案"""
    return _voice_manager.get_voice_profile(project_id)

