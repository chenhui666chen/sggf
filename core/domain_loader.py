# -*- coding: utf-8 -*-
"""
Domain Knowledge Loader for Intent Parser.

Loads model-specific knowledge from YAML configuration files,
enabling multi-model support without code changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SceneRule:
    """Scene-based recommendation rule."""
    name: str
    keywords: List[str]
    recommended: Dict[str, Any]  # Changed from Dict[str, str] to support numeric values
    reason: str
    
    @property
    def is_video_rule(self) -> bool:
        """Check if this is a video-related rule."""
        video_keys = {"lighting_time", "camera_movement", "shot_type", "composition", "emotion"}
        return any(key in self.recommended for key in video_keys)
    
    @property
    def is_image_edit_rule(self) -> bool:
        """Check if this is an image editing rule."""
        edit_keys = {"edit_strength", "skin_smoothing", "saturation_boost", "style_transfer", 
                     "background_removal", "inpainting_quality", "super_resolution"}
        return any(key in self.recommended for key in edit_keys)


@dataclass
class DomainKnowledge:
    """Domain knowledge for a specific model family."""
    
    domain_id: str
    name: str
    provider: str
    description: str
    
    modalities: Dict[str, str]
    creative_modes: Dict[str, str]
    styles: Dict[str, List[str]]
    camera_movements: Dict[str, str]
    shot_types: Dict[str, str]
    compositions: Dict[str, str]
    lighting_times: Dict[str, str]
    emotions: Dict[str, str]
    
    prompt_template: str
    prompt_examples: List[str]
    parsing_rules: List[str]
    scene_rules: List[SceneRule]
    
    constraints: Dict[str, Any]
    
    def get_style_keywords(self, style_name: str) -> List[str]:
        return self.styles.get(style_name, [])
    
    def get_camera_movement_name(self, movement_id: str) -> str:
        return self.camera_movements.get(movement_id, movement_id)
    
    def get_shot_type_name(self, shot_id: str) -> str:
        return self.shot_types.get(shot_id, shot_id)
    
    def get_all_style_names(self) -> List[str]:
        return list(self.styles.keys())
    
    def get_all_creative_modes(self) -> List[str]:
        return list(self.creative_modes.keys())
    
    def match_scene_rules(self, user_input: str) -> List[SceneRule]:
        """Match user input against scene rules."""
        matched = []
        for rule in self.scene_rules:
            if any(keyword in user_input.lower() for keyword in rule.keywords):
                matched.append(rule)
        return matched
    
    def to_system_prompt_section(self) -> str:
        """Convert domain knowledge to a section of system prompt."""
        sections = []
        
        if self.creative_modes:
            modes_text = "\n".join(f"- {k}: {v}" for k, v in self.creative_modes.items())
            sections.append(f"## 创作模式（creative_mode）\n当模态为视频相关时，进一步细分创作模式：\n{modes_text}")
        
        style_groups = {}
        for style_name in self.styles.keys():
            if style_name in ['felt_art', 'clay_art', 'puppet_animation', '3d_cartoon', '2d_cartoon', 
                             '3d_game', 'black_white_animation', 'impressionist', 'tilt_shift', 
                             'time_lapse', 'han_comic']:
                style_groups.setdefault('domain_specific', []).append(style_name)
            else:
                style_groups.setdefault('base', []).append(style_name)
        
        styles_text = ""
        if 'base' in style_groups:
            styles_text += f"- 基础风格：{', '.join(style_groups['base'])}\n"
        if 'domain_specific' in style_groups:
            styles_text += f"- 领域特有风格：{', '.join(style_groups['domain_specific'])}"
        sections.append(f"## 可用的风格标签\n{styles_text}")
        
        if self.camera_movements:
            movements = list(self.camera_movements.keys())
            sections.append(f"## 可用的运镜标签（camera_movement）\n{', '.join(movements)}")
        
        if self.shot_types:
            sections.append(f"## 可用的景别标签（shot_type）\n{', '.join(self.shot_types.keys())}")
        
        if self.compositions:
            sections.append(f"## 可用的构图标签（composition）\n{', '.join(self.compositions.keys())}")
        
        if self.lighting_times:
            sections.append(f"## 可用的光线时段标签（lighting_time）\n{', '.join(self.lighting_times.keys())}")
        
        if self.emotions:
            sections.append(f"## 可用的情绪标签（emotion）\n{', '.join(self.emotions.keys())}")
        
        if self.prompt_template:
            sections.append(f"## {self.name}提示词范式\n{self.prompt_template}")
        
        if self.prompt_examples:
            examples = "\n".join(f"- {ex}" for ex in self.prompt_examples[:3])
            sections.append(f"示例：\n{examples}")
        
        if self.scene_rules:
            rules_text = "\n\n".join(
                f"- **{rule.name}**（关键词：{', '.join(rule.keywords[:5])}）\n"
                f"  推荐：光线={rule.recommended.get('lighting_time', '自动')}, "
                f"运镜={rule.recommended.get('camera_movement', '自动')}, "
                f"景别={rule.recommended.get('shot_type', '自动')}\n"
                f"  理由：{rule.reason}"
                for rule in self.scene_rules[:10]
            )
            sections.append(f"## 场景智能推荐规则\n\n当用户请求包含以下场景关键词时，请主动推荐相应的运镜/光线/景别：\n\n{rules_text}")
        
        return "\n\n".join(sections)


class DomainKnowledgeLoader:
    """Loader for domain knowledge from YAML configuration."""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "intent_domains.yaml"
            )
        self._config_path = Path(config_path)
        self._domains: Dict[str, DomainKnowledge] = {}
        self._common: Dict[str, Any] = {}
        self._loaded = False
    
    def load(self, force_reload: bool = False) -> None:
        """Load domain knowledge from YAML file."""
        if self._loaded and not force_reload:
            return
        
        if not self._config_path.exists():
            logger.warning("Domain knowledge config not found at %s", self._config_path)
            return
        
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error("Failed to load domain knowledge config: %s", e)
            return
        
        domains_config = config.get('domains', {})
        
        for domain_id, domain_data in domains_config.items():
            scene_rules_raw = domain_data.get('scene_rules', [])
            scene_rules = [
                SceneRule(
                    name=rule.get('name', ''),
                    keywords=rule.get('keywords', []),
                    recommended=rule.get('recommended', {}),
                    reason=rule.get('reason', ''),
                )
                for rule in scene_rules_raw
            ]
            
            domain = DomainKnowledge(
                domain_id=domain_id,
                name=domain_data.get('name', domain_id),
                provider=domain_data.get('provider', 'Unknown'),
                description=domain_data.get('description', ''),
                modalities=domain_data.get('modalities', {}),
                creative_modes=domain_data.get('creative_modes', {}),
                styles=domain_data.get('styles', {}),
                camera_movements=domain_data.get('camera_movements', {}),
                shot_types=domain_data.get('shot_types', {}),
                compositions=domain_data.get('compositions', {}),
                lighting_times=domain_data.get('lighting_times', {}),
                emotions=domain_data.get('emotions', {}),
                prompt_template=domain_data.get('prompt_template', ''),
                prompt_examples=domain_data.get('prompt_examples', []),
                parsing_rules=domain_data.get('parsing_rules', []),
                scene_rules=scene_rules,
                constraints=domain_data.get('constraints', {}),
            )
            self._domains[domain_id] = domain
        
        self._common = config.get('common', {})
        self._loaded = True
        
        logger.info(
            "Loaded %d domain knowledge configs: %s",
            len(self._domains),
            list(self._domains.keys())
        )
    
    def get_domain(self, domain_id: str) -> Optional[DomainKnowledge]:
        """Get domain knowledge by ID."""
        if not self._loaded:
            self.load()
        return self._domains.get(domain_id)
    
    def get_all_domains(self) -> List[str]:
        """Get all available domain IDs."""
        if not self._loaded:
            self.load()
        return list(self._domains.keys())
    
    def get_common_config(self) -> Dict[str, Any]:
        """Get common configuration."""
        if not self._loaded:
            self.load()
        return self._common
    
    def get_resolution_map(self) -> Dict[str, List[int]]:
        """Get resolution mapping."""
        return self._common.get('resolution_map', {
            "720p": [1280, 720],
            "1080p": [1920, 1080],
            "2k": [2560, 1440],
            "4k": [3840, 2160],
        })
    
    def get_common_styles(self) -> List[str]:
        """Get common style names that all models support."""
        return self._common.get('common_styles', [
            'realistic', 'anime', 'cinematic', 'fantasy'
        ])


_domain_loader: Optional[DomainKnowledgeLoader] = None


def get_domain_loader() -> DomainKnowledgeLoader:
    """Get global domain knowledge loader instance."""
    global _domain_loader
    if _domain_loader is None:
        _domain_loader = DomainKnowledgeLoader()
    return _domain_loader


def load_domain(domain_id: str) -> Optional[DomainKnowledge]:
    """Convenience function to load a specific domain."""
    loader = get_domain_loader()
    return loader.get_domain(domain_id)
