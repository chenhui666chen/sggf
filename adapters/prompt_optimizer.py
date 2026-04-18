# -*- coding: utf-8 -*-
"""
Model-specific prompt optimizer.

Transforms generic prompts from IntentParser into model-specific optimized prompts
based on each model's characteristics, constraints, and best practices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.task_spec import TaskSpec

logger = logging.getLogger(__name__)


@dataclass
class PromptRule:
    """A single prompt transformation rule."""
    name: str
    condition: str  # keywords to match (comma-separated)
    prefix: str = ""
    suffix: str = ""
    remove_patterns: List[str] = field(default_factory=list)
    replace_patterns: Dict[str, str] = field(default_factory=dict)
    description: str = ""


# ============================================================================
# Video model prompt rules
# ============================================================================

VIDEO_PROMPT_RULES: List[PromptRule] = [
    PromptRule(
        name="wan27_motion_boost",
        condition="运动,动作,跑,跳,飞,走动,转身",
        suffix=", 自然流畅的运动，物理真实，避免抖动和变形",
        description="增加运动描述的流畅度",
    ),
    PromptRule(
        name="wan27_lighting",
        condition="光,阳光,黄昏,黎明,夜晚,暗,亮,逆光,侧光",
        suffix=", 光线自然，阴影真实",
        description="增强光照描述",
    ),
    PromptRule(
        name="remove_llm_artifacts",
        condition="",
        remove_patterns=[
            r"这是一张.*?(照片|图片|图像|画面)",
            r"图中显示",
            r"这张.*?展示了",
            r"画面中",
            r"描绘了.*?场景",
            r"呈现了.*?画面",
        ],
        description="去除 LLM 生成的冗余描述",
    ),
    PromptRule(
        name="remove_photo_keyword",
        condition="",
        remove_patterns=[r"照片", r"图片", r"图像", r"插画", r"绘画"],
        description="视频提示词中不应该有静态图片关键词",
    ),
]

# ============================================================================
# Image model prompt rules
# ============================================================================

IMAGE_PROMPT_RULES: List[PromptRule] = [
    PromptRule(
        name="quality_boost",
        condition="高清,高质量,清晰",
        suffix=", 4k, 高画质, 精细细节, 锐利",
        description="质量增强描述",
    ),
    PromptRule(
        name="style_boost",
        condition="写实,真实,照片",
        suffix=", 写实风格, 照片质感, 真实光影",
        description="写实风格增强",
    ),
    PromptRule(
        name="remove_video_keywords",
        condition="",
        remove_patterns=[
            r"视频",
            r"动画",
            r"动起来",
            r"镜头.*?(移动|推进|拉远|摇镜)",
        ],
        description="图片提示词中不应该有视频关键词",
    ),
    PromptRule(
        name="remove_llm_artifacts",
        condition="",
        remove_patterns=[
            r"这是一张.*?(照片|图片|图像|画面)",
            r"图中显示",
            r"这张.*?展示了",
            r"画面中",
            r"描绘了.*?场景",
        ],
        description="去除 LLM 生成的冗余描述",
    ),
]

# ============================================================================
# Kling video model prompt rules
# ============================================================================

KLING_VIDEO_RULES: List[PromptRule] = [
    PromptRule(
        name="kling_quality",
        condition="高质量,高清",
        suffix=", 电影级画质, 8k 分辨率, 超高画质",
        description="Kling 画质增强",
    ),
    PromptRule(
        name="kling_remove_photo",
        condition="",
        remove_patterns=[r"照片", r"图片", r"图像"],
        description="Kling 视频提示词去除图片关键词",
    ),
]

# ============================================================================
# Main optimizer
# ============================================================================


class PromptOptimizer:
    """Optimize prompts for specific models."""
    
    def __init__(self):
        self._rules_cache: Dict[str, List[PromptRule]] = {}
    
    def optimize(
        self,
        prompt: str,
        model_id: str,
        modality: str = "text_to_video",
        style: Optional[str] = None,
    ) -> str:
        """Optimize a prompt for a specific model.
        
        Args:
            prompt: Original prompt from IntentParser
            model_id: Target model ID (e.g., wan2.7-t2v)
            modality: Task modality
            style: Style hint
            
        Returns:
            Optimized prompt for the target model
        """
        if not prompt:
            return prompt
        
        rules = self._get_rules(model_id, modality)
        if not rules:
            return prompt
        
        logger.info(
            "Optimizing prompt for model=%s, modality=%s, rules=%d",
            model_id, modality, len(rules)
        )
        
        optimized = prompt
        
        for rule in rules:
            if not self._matches(rule, optimized, style):
                continue
            
            optimized = self._apply_rule(optimized, rule)
        
        # Clean up
        optimized = self._cleanup(optimized)
        
        if optimized != prompt:
            logger.info("Prompt optimized:\n  Before: %s\n  After:  %s", prompt[:80], optimized[:80])
        
        return optimized
    
    def _get_rules(self, model_id: str, modality: str) -> List[PromptRule]:
        """Get applicable rules for a model."""
        cache_key = f"{model_id}:{modality}"
        if cache_key in self._rules_cache:
            return self._rules_cache[cache_key]
        
        rules: List[PromptRule] = []
        
        if "video" in modality:
            rules.extend(VIDEO_PROMPT_RULES)
            if "kling" in model_id.lower():
                rules.extend(KLING_VIDEO_RULES)
        elif "image" in modality:
            rules.extend(IMAGE_PROMPT_RULES)
        
        self._rules_cache[cache_key] = rules
        return rules
    
    def _matches(self, rule: PromptRule, prompt: str, style: Optional[str]) -> bool:
        """Check if a rule applies to this prompt."""
        if not rule.condition:
            return True  # Always apply if no condition
        
        prompt_lower = prompt.lower()
        keywords = [k.strip() for k in rule.condition.split(",") if k.strip()]
        
        for keyword in keywords:
            if keyword.lower() in prompt_lower:
                return True
        
        if style and style.lower() in rule.condition.lower():
            return True
        
        return False
    
    def _apply_rule(self, prompt: str, rule: PromptRule) -> str:
        """Apply a single rule to a prompt."""
        import re
        
        # Remove patterns
        for pattern in rule.remove_patterns:
            prompt = re.sub(pattern, "", prompt, flags=re.IGNORECASE)
        
        # Replace patterns
        for old, new in rule.replace_patterns.items():
            prompt = re.sub(old, new, prompt, flags=re.IGNORECASE)
        
        # Add prefix/suffix
        if rule.prefix:
            prompt = f"{rule.prefix} {prompt}".strip()
        if rule.suffix:
            prompt = f"{prompt} {rule.suffix}".strip()
        
        return prompt
    
    def _cleanup(self, prompt: str) -> str:
        """Clean up the optimized prompt."""
        import re
        
        # Remove duplicate commas
        prompt = re.sub(r",{2,}", ",", prompt)
        
        # Remove leading/trailing commas
        prompt = re.sub(r"^[\s,]+|[\s,]+$", "", prompt)
        
        # Normalize spaces
        prompt = re.sub(r"\s+", " ", prompt)
        
        return prompt.strip()


# Singleton instance
_optimizer: Optional[PromptOptimizer] = None


def get_prompt_optimizer() -> PromptOptimizer:
    """Get global prompt optimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = PromptOptimizer()
    return _optimizer
