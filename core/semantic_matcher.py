# -*- coding: utf-8 -*-
"""
Semantic Model Matcher - Style/scenario-based model matching using embeddings.

Provides fuzzy matching between user intent (style descriptions, scenario keywords)
and model capability profiles, enabling "国风" → chinese_ink style → wan2.6-t2i
type semantic routing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from adapters.registry import registry

logger = logging.getLogger(__name__)

STYLE_VOCABULARY = {
    "realistic": ["写实", "照片级", "真实感", "高清照片", "photorealistic", "realistic", "lifelike"],
    "anime": ["二次元", "动漫", "日漫", "anime", "manga", "卡通", "萌系"],
    "chinese_ink": ["国风", "水墨", "国画", "工笔", "写意", "chinese ink", "oriental"],
    "oil_painting": ["油画", "oil painting", "古典油画", "印象派"],
    "watercolor": ["水彩", "watercolor", "淡彩", "水彩画"],
    "cyberpunk": ["赛博朋克", "赛博", "cyberpunk", "霓虹", "未来都市"],
    "fantasy": ["奇幻", "魔幻", "fantasy", "精灵", "魔法"],
    "3d_render": ["3D", "三维", "3d render", "渲染", "blender", "c4d"],
    "pixel_art": ["像素", "pixel art", "8bit", "复古像素"],
    "comic": ["漫画", "美漫", "comic", "分镜"],
    "sketch": ["素描", "线稿", "sketch", "速写", "白描"],
    "cinematic": ["电影感", "影视", "cinematic", "大片", "镜头感"],
    "documentary": ["纪录片", "纪实", "documentary", "真实记录"],
    "ukiyo_e": ["浮世绘", "日式版画", "ukiyo-e"],
    "minimalist": ["极简", "简约", "minimalist", "留白"],
    "steampunk": ["蒸汽朋克", "steampunk", "齿轮", "维多利亚"],
    "gothic": ["哥特", "暗黑", "gothic", "暗黑风"],
    "retro": ["复古", "怀旧", "retro", "vintage", "老照片"],
    "neon": ["霓虹", "荧光", "neon", "发光"],
    "pop_art": ["波普", "pop art", "安迪沃霍尔"],
    "felt_art": ["毛毡", "毛毡风格", "felt", "羊毛毡", "毡绒"],
    "clay_art": ["黏土", "粘土", "clay", "黏土风格", "粘土动画"],
    "puppet_animation": ["木偶", "木偶动画", "puppet", "定格动画", "阿德曼"],
    "3d_cartoon": ["3D卡通", "3d cartoon", "三维卡通", "Q版3D", "卡通3D"],
    "2d_cartoon": ["2D卡通", "2d cartoon", "二维卡通", "复古卡通", "法国动画"],
    "3d_game": ["3D游戏", "3d game", "游戏画面", "游戏风格", "游戏CG"],
    "black_white_animation": ["黑白动画", "黑白", "black white animation", "复古黑白"],
    "impressionist": ["印象派", "impressionist", "水彩质感", "笔触", "莫奈"],
    "tilt_shift": ["移轴", "移轴摄影", "tilt shift", "微缩", "模型感"],
    "time_lapse": ["延时", "延时拍摄", "time lapse", "快进", "时间流逝"],
    "han_comic": ["韩漫", "韩式漫画", "korean comic", "webtoon"],
    "realistic": ["写实", "照片级", "真实感", "photorealistic"],
    "anime": ["二次元", "动漫", "日漫", "anime", "卡通"],
    "chinese_ink": ["国风", "水墨", "国画", "chinese ink"],
    "oil_painting": ["油画", "oil painting", "古典油画"],
    "watercolor": ["水彩", "watercolor", "淡彩"],
    "cyberpunk": ["赛博朋克", "赛博", "cyberpunk", "霓虹"],
    "fantasy": ["奇幻", "魔幻", "fantasy"],
    "3d_render": ["3D", "三维", "3d render", "渲染"],
    "pixel_art": ["像素", "pixel art", "8bit"],
    "comic": ["漫画", "美漫", "comic"],
    "sketch": ["素描", "线稿", "sketch"],
    "ukiyo_e": ["浮世绘", "日式版画"],
    "minimalist": ["极简", "简约", "minimalist"],
    "steampunk": ["蒸汽朋克", "steampunk"],
    "gothic": ["哥特", "暗黑", "gothic"],
    "retro": ["复古", "怀旧", "retro"],
    "neon": ["霓虹", "荧光", "neon"],
    "pop_art": ["波普", "pop art"],
    "cinematic": ["电影感", "影视", "cinematic"],
    "documentary": ["纪录片", "纪实", "documentary"],
    "felt_art": ["毛毡", "毛毡风格", "felt", "羊毛毡"],
    "clay_art": ["黏土", "粘土", "clay", "黏土风格"],
    "puppet_animation": ["木偶", "木偶动画", "puppet", "定格动画"],
    "3d_cartoon": ["3D 卡通", "3d cartoon", "三维卡通", "Q 版 3D"],
    "2d_cartoon": ["2D 卡通", "2d cartoon", "二维卡通"],
    "3d_game": ["3D 游戏", "3d game", "游戏画面"],
    "black_white_animation": ["黑白动画", "黑白", "black white"],
    "impressionist": ["印象派", "impressionist", "水彩质感"],
    "tilt_shift": ["移轴", "移轴摄影", "tilt shift"],
    "time_lapse": ["延时", "延时拍摄", "time lapse"],
    "han_comic": ["韩漫", "韩式漫画", "korean comic"],
    "realistic": ["写实", "照片级", "真实感", "photorealistic"],
    "anime": ["二次元", "动漫", "日漫", "anime", "卡通"],
    "chinese_ink": ["国风", "水墨", "国画", "chinese ink"],
    "oil_painting": ["油画", "oil painting", "古典油画"],
    "watercolor": ["水彩", "watercolor", "淡彩"],
    "cyberpunk": ["赛博朋克", "赛博", "cyberpunk", "霓虹"],
    "fantasy": ["奇幻", "魔幻", "fantasy"],
    "3d_render": ["3D", "三维", "3d render", "渲染"],
    "pixel_art": ["像素", "pixel art", "8bit"],
    "comic": ["漫画", "美漫", "comic"],
    "sketch": ["素描", "线稿", "sketch"],
    "ukiyo_e": ["浮世绘", "日式版画"],
    "minimalist": ["极简", "简约", "minimalist"],
    "steampunk": ["蒸汽朋克", "steampunk"],
    "gothic": ["哥特", "暗黑", "gothic"],
    "retro": ["复古", "怀旧", "retro"],
    "neon": ["霓虹", "荧光", "neon"],
    "pop_art": ["波普", "pop art"],
    "cinematic": ["电影感", "影视", "cinematic"],
    "documentary": ["纪录片", "纪实", "documentary"],
    "felt_art": ["毛毡", "毛毡风格", "felt", "羊毛毡"],
    "clay_art": ["黏土", "粘土", "clay", "黏土风格"],
    "puppet_animation": ["木偶", "木偶动画", "puppet", "定格动画"],
    "3d_cartoon": ["3D 卡通", "3d cartoon", "三维卡通", "Q 版 3D"],
    "2d_cartoon": ["2D 卡通", "2d cartoon", "二维卡通"],
    "3d_game": ["3D 游戏", "3d game", "游戏画面"],
    "black_white_animation": ["黑白动画", "黑白", "black white"],
    "impressionist": ["印象派", "impressionist", "水彩质感"],
    "tilt_shift": ["移轴", "移轴摄影", "tilt shift"],
    "time_lapse": ["延时", "延时拍摄", "time lapse"],
    "han_comic": ["韩漫", "韩式漫画", "korean comic"],
    "tts_whisper": ["低语", "耳语", "小声", "压低声音", "whisper"],
    "tts_sobbing": ["哽咽", "哭腔", "抽泣", "呜咽", "带着哭意", "sobbing"],
    "tts_laughter": ["笑意", "轻笑", "大笑", "苦笑", "冷笑", "laugh"],
    "tts_breathy": ["气声", "吸气", "叹气", "喘息", "深呼吸", "breathy"],
    "tts_voice_break": ["破音", "变调", "颤抖", "声音颤抖", "鼻音"],
    "tts_emotional_mix": ["压抑的愤怒", "温柔但疲惫", "带着哽咽的笑意", "狂躁中的温柔"],
    "tts_director_guidance": ["导演模式", "角色", "场景", "指导", "演绎要领", "重音", "停顿"]
}

SCENARIO_VOCABULARY = {
    "short_video": ["短视频", "抖音", "tiktok", "竖屏视频", "9:16视频"],
    "marketing": ["营销素材", "广告图", "banner", "海报", "宣传图"],
    "animation": ["动画", "动画片", "animation", "卡通动画"],
    "film": ["影视片段", "电影", "短剧", "微电影", "剧情片"],
    "emoji": ["表情包", "贴纸", "emoji", "sticker"],
    "portrait": ["人像", "头像", "肖像", "portrait", "avatar"],
    "landscape": ["风景", "山水", "landscape", "自然风光"],
    "product": ["产品图", "商品图", "白底图", "电商图"],
    "concept_art": ["概念设计", "设定图", "concept art", "原画"],
    "storyboard": ["分镜", "故事板", "storyboard"],
    "book_cover": ["封面", "书封", "book cover", "小说封面"],
    "social_media": ["社交媒体", "朋友圈", "小红书", "ins风"],
    "video_edit": ["视频编辑", "修改视频", "视频修改", "改视频", "换台词"],
    "action_replicate": ["动作复刻", "模仿动作", "复刻动作", "动作参考"],
    "video_continuation": ["续写", "视频续写", "继续", "延续", "后续"],
    "storyboard": ["分镜", "故事板", "storyboard", "多宫格", "分镜图"],
    "audiobook_narration": ["有声书", "旁白", "朗读", "播讲", "小说配音", "audiobook"],
    "character_dialogue": ["角色对白", "对话", "多人对白", "人物台词", "角色配音"],
    "character_monologue": ["独白", "内心独白", "自言自语", "心理活动", "monologue"],
    "emotional_outburst": ["情绪爆发", "嘶吼", "怒吼", "崩溃", "哭喊", "爆发戏"],
    "tts_director_mode": ["导演模式", "角色场景指导", "演员指导", "角色：", "场景：", "指导："],
    "tts_audio_tag_control": ["音频标签", "风格标签", "标签控制", "低语标签", "哽咽标签"],
}


def _tokenize(text: str) -> List[str]:
    import re
    tokens = re.findall(r"[\w一-鿿]+", str(text or "").lower(), flags=re.UNICODE)
    return tokens


def _hash_embed(text: str, dim: int = 128) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for tok in _tokenize(text):
        h = hashlib.md5(tok.encode("utf-8"), usedforsecurity=False).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        vec[idx] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


@dataclass
class SemanticMatchResult:
    model_id: str
    model_name: str
    provider: str
    style_score: float
    scenario_score: float
    combined_score: float
    matched_styles: List[str]
    matched_scenarios: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "provider": self.provider,
            "style_score": round(self.style_score, 4),
            "scenario_score": round(self.scenario_score, 4),
            "combined_score": round(self.combined_score, 4),
            "matched_styles": self.matched_styles,
            "matched_scenarios": self.matched_scenarios,
        }


class SemanticModelMatcher:
    """Semantic matching between user intent and model capabilities."""

    def __init__(self, style_weight: float = 0.6, scenario_weight: float = 0.4):
        self._style_weight = style_weight
        self._scenario_weight = scenario_weight
        self._style_embeddings: Dict[str, np.ndarray] = {}
        self._scenario_embeddings: Dict[str, np.ndarray] = {}
        self._model_style_map: Dict[str, List[str]] = {}
        self._model_scenario_map: Dict[str, List[str]] = {}
        self._model_style_embeddings: Dict[str, np.ndarray] = {}
        self._model_scenario_embeddings: Dict[str, np.ndarray] = {}
        self._built = False
        self._lock = threading.Lock()

    def build_index(self) -> None:
        with self._lock:
            if self._built:
                return
            self._build_style_index()
            self._build_scenario_index()
            self._build_model_index()
            self._built = True
            logger.info(
                "Semantic index built: %d styles, %d scenarios, %d models",
                len(self._style_embeddings),
                len(self._scenario_embeddings),
                len(self._model_style_embeddings),
            )

    def _build_style_index(self) -> None:
        for style_name, keywords in STYLE_VOCABULARY.items():
            combined_text = " ".join(keywords) + " " + style_name
            self._style_embeddings[style_name] = _hash_embed(combined_text)

    def _build_scenario_index(self) -> None:
        for scenario_name, keywords in SCENARIO_VOCABULARY.items():
            combined_text = " ".join(keywords) + " " + scenario_name
            self._scenario_embeddings[scenario_name] = _hash_embed(combined_text)

    def _build_model_index(self) -> None:
        all_specs = registry.get_all_specs()

        modality_display = {
            "text_to_image": "文生图 text to image 图片生成",
            "image_to_image": "图生图 image to image 风格迁移",
            "text_to_video": "文生视频 text to video 视频生成",
            "image_to_video": "图生视频 image to video 图片动画化",
            "video_to_video": "视频转视频 video to video 视频编辑",
            "image_to_image_edit": "图像编辑 image editing 图片编辑",
        }

        for spec in all_specs:
            style_texts = []
            scenario_texts = []

            style_texts.append(spec.name)
            style_texts.append(spec.id)
            scenario_texts.append(spec.name)

            for mod in spec.modality:
                display = modality_display.get(mod, mod)
                style_texts.append(display)
                scenario_texts.append(display)

            for tag in spec.tags:
                style_texts.append(tag)
                scenario_texts.append(tag)
                if tag in STYLE_VOCABULARY:
                    self._model_style_map.setdefault(spec.id, []).append(tag)
                    style_texts.append(" ".join(STYLE_VOCABULARY[tag]))
                if tag in SCENARIO_VOCABULARY:
                    self._model_scenario_map.setdefault(spec.id, []).append(tag)
                    scenario_texts.append(" ".join(SCENARIO_VOCABULARY[tag]))

            for scenario in spec.recommended_scenarios:
                scenario_texts.append(scenario)
                if scenario in SCENARIO_VOCABULARY:
                    self._model_scenario_map.setdefault(spec.id, []).append(scenario)

            for cap in spec.capabilities:
                style_texts.append(cap.description)
                scenario_texts.append(cap.description)

            if spec.summary:
                scenario_texts.append(spec.summary)

            if style_texts:
                self._model_style_embeddings[spec.id] = _hash_embed(" ".join(style_texts))
            if scenario_texts:
                self._model_scenario_embeddings[spec.id] = _hash_embed(" ".join(scenario_texts))

    def match(
        self,
        user_input: str,
        style_hint: Optional[str] = None,
        scenario_hint: Optional[str] = None,
        top_k: int = 5,
    ) -> List[SemanticMatchResult]:
        if not self._built:
            self.build_index()

        query_style_text = user_input
        if style_hint:
            query_style_text += " " + style_hint
            if style_hint in STYLE_VOCABULARY:
                query_style_text += " " + " ".join(STYLE_VOCABULARY[style_hint])

        query_scenario_text = user_input
        if scenario_hint:
            query_scenario_text += " " + scenario_hint
            if scenario_hint in SCENARIO_VOCABULARY:
                query_scenario_text += " " + " ".join(SCENARIO_VOCABULARY[scenario_hint])

        expanded_styles = self._expand_keywords(user_input, STYLE_VOCABULARY)
        for style_name in expanded_styles:
            query_style_text += " " + style_name + " " + " ".join(STYLE_VOCABULARY[style_name])

        expanded_scenarios = self._expand_keywords(user_input, SCENARIO_VOCABULARY)
        for scenario_name in expanded_scenarios:
            query_scenario_text += " " + scenario_name + " " + " ".join(SCENARIO_VOCABULARY[scenario_name])

        query_style_emb = _hash_embed(query_style_text)
        query_scenario_emb = _hash_embed(query_scenario_text)

        matched_styles = self._find_matching_styles(query_style_emb, threshold=0.3)
        matched_scenarios = self._find_matching_scenarios(query_scenario_emb, threshold=0.3)

        results: List[SemanticMatchResult] = []

        all_model_ids = set(self._model_style_embeddings.keys()) | set(self._model_scenario_embeddings.keys())

        for model_id in all_model_ids:
            spec = registry.get_spec(model_id)
            if spec is None or spec.status.value != "active":
                continue

            style_score = 0.0
            if model_id in self._model_style_embeddings:
                style_score = _cosine_similarity(query_style_emb, self._model_style_embeddings[model_id])

            scenario_score = 0.0
            if model_id in self._model_scenario_embeddings:
                scenario_score = _cosine_similarity(query_scenario_emb, self._model_scenario_embeddings[model_id])

            model_matched_styles = [
                s for s in self._model_style_map.get(model_id, [])
                if s in matched_styles
            ]
            model_matched_scenarios = [
                s for s in self._model_scenario_map.get(model_id, [])
                if s in matched_scenarios
            ]

            combined = (
                style_score * self._style_weight +
                scenario_score * self._scenario_weight
            )

            if combined > 0.05:
                results.append(SemanticMatchResult(
                    model_id=model_id,
                    model_name=spec.name,
                    provider=spec.provider,
                    style_score=style_score,
                    scenario_score=scenario_score,
                    combined_score=combined,
                    matched_styles=model_matched_styles,
                    matched_scenarios=model_matched_scenarios,
                ))

        results.sort(key=lambda r: r.combined_score, reverse=True)
        return results[:top_k]

    def _expand_keywords(self, user_input: str, vocabulary: Dict[str, List[str]]) -> List[str]:
        matched = []
        for name, keywords in vocabulary.items():
            for kw in keywords:
                if kw.lower() in user_input.lower():
                    matched.append(name)
                    break
        return matched

    def _find_matching_styles(self, query_emb: np.ndarray, threshold: float = 0.3) -> List[str]:
        matched = []
        for style_name, style_emb in self._style_embeddings.items():
            sim = _cosine_similarity(query_emb, style_emb)
            if sim >= threshold:
                matched.append(style_name)
        return matched

    def _find_matching_scenarios(self, query_emb: np.ndarray, threshold: float = 0.3) -> List[str]:
        matched = []
        for scenario_name, scenario_emb in self._scenario_embeddings.items():
            sim = _cosine_similarity(query_emb, scenario_emb)
            if sim >= threshold:
                matched.append(scenario_name)
        return matched

    def get_style_keywords(self, style: str) -> List[str]:
        return STYLE_VOCABULARY.get(style, [])

    def get_scenario_keywords(self, scenario: str) -> List[str]:
        return SCENARIO_VOCABULARY.get(scenario, [])

    def get_all_styles(self) -> Dict[str, List[str]]:
        return dict(STYLE_VOCABULARY)

    def get_all_scenarios(self) -> Dict[str, List[str]]:
        return dict(SCENARIO_VOCABULARY)


_semantic_matcher: Optional[SemanticModelMatcher] = None


def get_semantic_matcher(force_rebuild: bool = False) -> SemanticModelMatcher:
    global _semantic_matcher
    if _semantic_matcher is None or force_rebuild:
        _semantic_matcher = SemanticModelMatcher()
        _semantic_matcher.build_index()
    return _semantic_matcher
