# -*- coding: utf-8 -*-
"""
Intent Parser Agent - Natural language to structured TaskSpec conversion.

Converts free-form user requests into structured TaskSpec objects
using LLM-based intent extraction.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from schemas.common import Modality, Priority
from schemas.task_spec import (
    AudioSpec,
    PriorityProfile,
    ReferenceSpec,
    TaskSpec,
    TaskSpecBuilder,
)

logger = logging.getLogger(__name__)

INTENT_PARSER_BASE_PROMPT = """\
你是一个多模态生成任务的意图解析器。你的任务是将用户的自然语言请求解析为结构化的任务规格。

## 可用的生成模态
- text_to_image: 文生图（根据文字描述生成图片）
- image_to_image: 图生图（基于参考图修改/风格迁移）
- text_to_video: 文生视频（根据文字描述生成视频）
- image_to_video: 图生视频（将静态图片动画化为视频）
- video_to_video: 视频转视频（视频风格转换/编辑）
- image_to_image_edit: 图像编辑（指令式图像编辑）

## 分辨率映射
- 720p → 1280x720
- 1080p → 1920x1080
- 2k → 2560x1440
- 4k → 3840x2160

## 优先级策略
- quality: 追求最高画质，不计成本和速度
- cost: 追求最低成本，可牺牲画质和速度
- speed: 追求最快速度，可牺牲画质和增加成本
- balanced: 平衡画质、成本和速度

## 解析规则
1. 如果用户提到"视频"/"动画"/"动起来"等词，模态应为 text_to_video 或 image_to_video
2. 如果用户提到"图片"/"画"/"图"等词且无视频意图，模态应为 text_to_image
3. 如果用户提供了参考图/素材图，且要求修改，模态应为 image_to_image 或 image_to_image_edit
4. 如果用户提到"让这张图动起来"/"图片转视频"，模态应为 image_to_video
5. 时长默认 5 秒，除非用户明确指定
6. 分辨率默认 1080p，除非用户明确指定
7. 如果用户没有指定优先级，默认为 balanced
8. 风格需要从用户的描述中推断

## 输出格式
你必须输出一个严格的 JSON 对象，包含以下字段：
{
  "modality": "text_to_image | image_to_image | text_to_video | image_to_video | video_to_video | image_to_image_edit",
  "creative_mode": "创作模式或 null（仅视频任务需要细分）",
  "style": "风格标签或 null",
  "camera_movement": "运镜标签或 null",
  "shot_type": "景别标签或 null",
  "composition": "构图标签或 null",
  "lighting_time": "光线时段标签或 null",
  "emotion": "情绪标签或 null",
  "duration": 时长秒数或 null（仅视频任务）,
  "width": 宽度像素,
  "height": 高度像素,
  "ratio": "宽高比如 16:9",
  "quality": "standard | hd | ultra",
  "priority": "quality | cost | speed | balanced",
  "negative_prompt": "负向提示词或 null",
  "need_reference_images": true/false,
  "need_reference_videos": true/false,
  "need_audio": true/false,
  "need_dialogue": true/false,
  "camera_control": "镜头控制描述或 null",
  "motion_control": "运动控制描述或 null",
  "character_consistency": true/false,
  "num_outputs": 生成数量,
  "extracted_prompt": "优化的完整生成提示词"
}

只输出 JSON，不要输出其他内容。"""

INTENT_PARSER_USER_TEMPLATE = """\
请解析以下用户请求为结构化任务规格：

用户请求：{user_input}

{context_section}

请输出JSON格式的解析结果。"""

CONTEXT_SECTION_TEMPLATE = """\
附加上下文信息：
- 当前项目类型：{project_type}
- 已有素材：{available_assets}
- 用户偏好：{user_preferences}"""


@dataclass
class IntentParseResult:
    raw_text: str
    parsed_json: Dict[str, Any]
    task_spec: TaskSpec
    confidence: float = 1.0
    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "parsed_json": self.parsed_json,
            "task_spec": self.task_spec.to_dict(),
            "confidence": self.confidence,
            "parse_errors": self.parse_errors,
        }


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    candidates = []

    fence_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
    for match in fence_pattern.finditer(text):
        candidates.append(match.group(1).strip())

    decoder = json.JSONDecoder()
    for pos in range(len(text)):
        if text[pos] == '{':
            try:
                obj, end = decoder.raw_decode(text, pos)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                continue

    for candidate in candidates:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            continue

    try:
        result = json.loads(text.strip())
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _resolve_modality(modality_str: str) -> Modality:
    mapping = {
        "text_to_image": Modality.TEXT_TO_IMAGE,
        "image_to_image": Modality.IMAGE_TO_IMAGE,
        "text_to_video": Modality.TEXT_TO_VIDEO,
        "image_to_video": Modality.IMAGE_TO_VIDEO,
        "video_to_video": Modality.VIDEO_TO_VIDEO,
        "image_to_image_edit": Modality.IMAGE_TO_IMAGE_EDIT,
    }
    result = mapping.get(modality_str)
    if result is None:
        logger.warning("Unknown modality '%s', falling back to TEXT_TO_IMAGE", modality_str)
        return Modality.TEXT_TO_IMAGE
    return result


def _resolve_priority(priority_str: str) -> Priority:
    mapping = {
        "quality": Priority.QUALITY,
        "cost": Priority.COST,
        "speed": Priority.LATENCY,
        "balanced": Priority.BALANCED,
    }
    return mapping.get(priority_str, Priority.BALANCED)


def _resolve_resolution(parsed: Dict[str, Any]) -> tuple:
    resolution_map = {
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "2k": (2560, 1440),
        "4k": (3840, 2160),
    }

    if "resolution" in parsed and parsed["resolution"]:
        res = str(parsed["resolution"]).lower().strip()
        if res in resolution_map:
            return resolution_map[res]

    width = parsed.get("width")
    height = parsed.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return (width, height)

    return (1920, 1080)


def _build_task_spec(parsed: Dict[str, Any], user_input: str) -> TaskSpec:
    modality_raw = parsed.get("modality") or "text_to_image"
    modality = _resolve_modality(modality_raw)
    width, height = _resolve_resolution(parsed)

    builder = TaskSpecBuilder()
    builder.with_task_id(str(uuid.uuid4()))
    builder.with_modality(modality.value)

    prompt_text = parsed.get("extracted_prompt") or user_input
    builder.with_prompt(prompt_text)
    builder.with_dimensions(width, height)

    if parsed.get("negative_prompt"):
        builder.with_negative_prompt(parsed["negative_prompt"])

    if parsed.get("style"):
        builder.with_style(parsed["style"])

    quality = parsed.get("quality", "standard")
    if quality in ("standard", "hd", "ultra"):
        builder.with_quality(quality)

    if modality in (Modality.TEXT_TO_VIDEO, Modality.IMAGE_TO_VIDEO, Modality.VIDEO_TO_VIDEO):
        duration = parsed.get("duration")
        if duration and isinstance(duration, (int, float)) and duration > 0:
            builder.with_duration(float(duration))
        else:
            builder.with_duration(5.0)

    priority = _resolve_priority(parsed.get("priority", "balanced"))
    priority_profile = PriorityProfile.from_priority(priority)
    builder.with_priority(
        quality=priority_profile.quality,
        cost=priority_profile.cost,
        latency=priority_profile.latency,
    )

    reference_images = []
    reference_videos = []
    if parsed.get("need_reference_images"):
        reference_images = ["__placeholder__"]
    if parsed.get("need_reference_videos"):
        reference_videos = ["__placeholder__"]
    if reference_images or reference_videos:
        builder.with_references(
            images=reference_images,
            videos=reference_videos,
            style=parsed.get("style"),
        )

    need_audio = parsed.get("need_audio", False)
    need_dialogue = parsed.get("need_dialogue", False)
    if need_audio or need_dialogue:
        builder.with_audio(
            need_dialogue=need_dialogue,
            need_sfx=need_audio,
            need_music=need_audio,
        )

    if parsed.get("camera_control"):
        builder.with_camera_control(parsed["camera_control"])

    if parsed.get("motion_control"):
        builder.with_motion_control(parsed["motion_control"])

    camera_movement = parsed.get("camera_movement")
    if camera_movement:
        existing_camera = parsed.get("camera_control") or ""
        builder.with_camera_control(f"{existing_camera} {camera_movement}".strip())

    if parsed.get("character_consistency"):
        builder.with_character_consistency(True)

    num_outputs = parsed.get("num_outputs", 1)
    if isinstance(num_outputs, (int, float)) and 1 <= num_outputs <= 10:
        builder.with_num_outputs(int(num_outputs))

    return builder.build()


class IntentParserAgent:
    """Agent that parses natural language requests into structured TaskSpec objects.
    
    Supports multi-model domains through dynamic knowledge loading.
    """

    def __init__(self, domain_id: str = "wan", llm_client=None):
        self._domain_id = domain_id
        self._llm_client = llm_client
        self._domain_knowledge = None
        self._load_domain_knowledge()
    
    def _load_domain_knowledge(self) -> None:
        """Load domain-specific knowledge for intent parsing."""
        try:
            from core.domain_loader import load_domain
            self._domain_knowledge = load_domain(self._domain_id)
            if self._domain_knowledge:
                logger.info("Loaded domain knowledge for: %s", self._domain_knowledge.name)
        except Exception as e:
            logger.warning("Failed to load domain knowledge for %s: %s", self._domain_id, e)
            self._domain_knowledge = None

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client
        from core.unified_llm_client import get_llm_client
        self._llm_client = get_llm_client(strategy="conservative")
        return self._llm_client
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with domain-specific knowledge."""
        base_prompt = INTENT_PARSER_BASE_PROMPT
        
        if self._domain_knowledge:
            domain_section = self._domain_knowledge.to_system_prompt_section()
            return f"{base_prompt}\n\n{domain_section}"
        
        return base_prompt

    async def parse(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
        db_session=None,
    ) -> IntentParseResult:
        messages = self._build_messages(user_input, context)

        try:
            llm = self._get_llm_client()
            raw_response = await llm.chat(
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("IntentParser LLM call failed: %s", e)
            fallback_spec = self._build_fallback_spec(user_input)
            return IntentParseResult(
                raw_text=user_input,
                parsed_json={"modality": "text_to_image", "extracted_prompt": user_input},
                task_spec=fallback_spec,
                confidence=0.0,
                parse_errors=[f"LLM call failed: {str(e)}"],
            )

        parsed = _extract_json_from_text(raw_response)

        if parsed is None:
            logger.warning("IntentParser failed to extract JSON from LLM response")
            fallback_spec = self._build_fallback_spec(user_input)
            return IntentParseResult(
                raw_text=user_input,
                parsed_json={"modality": "text_to_image", "extracted_prompt": user_input},
                task_spec=fallback_spec,
                confidence=0.0,
                parse_errors=["Failed to extract JSON from LLM response"],
            )

        parsed = self._rule_enhance(user_input, parsed)
        parsed = self._stats_enhance(user_input, parsed, db_session)

        parse_errors = []
        task_spec = None
        try:
            task_spec = _build_task_spec(parsed, user_input)
        except Exception as e:
            parse_errors.append(f"TaskSpec build error: {str(e)}")
            task_spec = self._build_fallback_spec(user_input)

        confidence = self._estimate_confidence(parsed, parse_errors)

        return IntentParseResult(
            raw_text=user_input,
            parsed_json=parsed,
            task_spec=task_spec,
            confidence=confidence,
            parse_errors=parse_errors,
        )

    def _build_messages(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        context_section = ""
        if context:
            context_section = CONTEXT_SECTION_TEMPLATE.format(
                project_type=context.get("project_type", "未指定"),
                available_assets=context.get("available_assets", "无"),
                user_preferences=context.get("user_preferences", "无"),
            )

        user_message = INTENT_PARSER_USER_TEMPLATE.format(
            user_input=user_input,
            context_section=context_section,
        )

        system_prompt = self._build_system_prompt()

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
    
    def _rule_enhance(self, user_input: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance parsed JSON with scene rule recommendations.
        
        This method applies domain-specific scene rules to fill in missing fields
        (camera_movement, lighting_time, shot_type, etc.) when the user didn't
        explicitly specify them.
        
        Supports both video rules (lighting/camera/shot) and image editing rules
        (edit_strength, skin_smoothing, etc.).
        """
        if not self._domain_knowledge or not self._domain_knowledge.scene_rules:
            return parsed
        
        matched_rules = self._domain_knowledge.match_scene_rules(user_input.lower())
        
        if not matched_rules:
            return parsed
        
        best_rule = matched_rules[0]
        logger.info("Matched scene rule: %s for input: %s", best_rule.name, user_input[:50])
        
        recommended = best_rule.recommended
        
        # Video-related recommendations
        if not parsed.get("lighting_time") and recommended.get("lighting_time"):
            parsed["lighting_time"] = recommended["lighting_time"]
        
        if not parsed.get("camera_movement") and recommended.get("camera_movement"):
            parsed["camera_movement"] = recommended["camera_movement"]
        
        if not parsed.get("shot_type") and recommended.get("shot_type"):
            parsed["shot_type"] = recommended["shot_type"]
        
        if not parsed.get("composition") and recommended.get("composition"):
            parsed["composition"] = recommended["composition"]
        
        if not parsed.get("emotion") and recommended.get("emotion"):
            parsed["emotion"] = recommended["emotion"]
        
        # Image editing recommendations
        if not parsed.get("edit_strength") and recommended.get("edit_strength"):
            parsed["edit_strength"] = recommended["edit_strength"]
        
        if not parsed.get("skin_smoothing") and recommended.get("skin_smoothing"):
            parsed["skin_smoothing"] = recommended["skin_smoothing"]
        
        if not parsed.get("saturation_boost") and recommended.get("saturation_boost"):
            parsed["saturation_boost"] = recommended["saturation_boost"]
        
        if not parsed.get("style_transfer") and recommended.get("style_transfer"):
            parsed["style_transfer"] = recommended["style_transfer"]
        
        if not parsed.get("background_removal") and recommended.get("background_removal"):
            parsed["background_removal"] = recommended["background_removal"]
        
        if not parsed.get("inpainting_quality") and recommended.get("inpainting_quality"):
            parsed["inpainting_quality"] = recommended["inpainting_quality"]
        
        if not parsed.get("super_resolution") and recommended.get("super_resolution"):
            parsed["super_resolution"] = recommended["super_resolution"]
        
        # Add other image editing parameters as needed
        for key, value in recommended.items():
            if key not in parsed and key not in {
                "lighting_time", "camera_movement", "shot_type", "composition", "emotion",
                "edit_strength", "skin_smoothing", "saturation_boost", "style_transfer",
                "background_removal", "inpainting_quality", "super_resolution"
            }:
                parsed[key] = value
        
        return parsed
    
    def _stats_enhance(
        self,
        user_input: str,
        parsed: Dict[str, Any],
        db_session=None,
    ) -> Dict[str, Any]:
        """Enhance parsed JSON with statistical recommendations from historical feedback.
        
        This method queries historical feedback data to find the best-performing
        recommendations for each field (lighting_time, camera_movement, etc.)
        and overrides rule-based recommendations when statistical confidence is higher.
        
        Args:
            user_input: Original user input text
            parsed: Parsed JSON from LLM
            db_session: Database session for querying feedback
        
        Returns:
            Enhanced parsed JSON with statistical recommendations
        """
        if not self._domain_knowledge or not self._domain_knowledge.scene_rules:
            return parsed
        
        if db_session is None:
            logger.debug("No DB session provided, skipping stats enhancement")
            return parsed
        
        matched_rules = self._domain_knowledge.match_scene_rules(user_input.lower())
        
        if not matched_rules:
            return parsed
        
        try:
            from app.services.feedback_loop import get_feedback_loop_service
            service = get_feedback_loop_service()
        except Exception as e:
            logger.warning("Failed to get feedback service: %s", e)
            return parsed
        
        best_rule = matched_rules[0]
        fields_to_enhance = ["lighting_time", "camera_movement", "shot_type", "composition", "emotion"]
        
        for field in fields_to_enhance:
            if parsed.get(field):
                continue
            
            stats = service.get_scene_recommendation_stats(
                db_session,
                best_rule.keywords,
                field=field,
                days=30,
                min_samples=3,
            )
            
            if not stats:
                continue
            
            top_stat = stats[0]
            
            if top_stat["count"] >= 5:
                logger.info(
                    "Using statistical recommendation for %s: %s (count=%d, score=%.3f)",
                    field, top_stat["value"], top_stat["count"], top_stat["weighted_score"]
                )
                parsed[field] = top_stat["value"]
            elif top_stat["count"] >= 3:
                rule_value = best_rule.recommended.get(field)
                if rule_value and top_stat["weighted_score"] < 7.0:
                    logger.debug(
                        "Keeping rule recommendation for %s: %s (stats count=%d too low)",
                        field, rule_value, top_stat["count"]
                    )
                else:
                    logger.info(
                        "Using statistical recommendation for %s: %s (count=%d, score=%.3f)",
                        field, top_stat["value"], top_stat["count"], top_stat["weighted_score"]
                    )
                    parsed[field] = top_stat["value"]
        
        return parsed

    def _build_fallback_spec(self, user_input: str) -> TaskSpec:
        try:
            builder = TaskSpecBuilder()
            builder.with_task_id(str(uuid.uuid4()))
            builder.with_modality("text_to_image")
            builder.with_prompt(user_input)
            builder.with_dimensions(1920, 1080)
            return builder.build()
        except Exception:
            return TaskSpec(
                task_id=str(uuid.uuid4()),
                modality=Modality.TEXT_TO_IMAGE,
                prompt=user_input,
                width=1920,
                height=1080,
            )

    def _estimate_confidence(
        self,
        parsed: Dict[str, Any],
        errors: List[str],
    ) -> float:
        score = 1.0

        if errors:
            score -= 0.3 * len(errors)

        if not parsed.get("modality"):
            score -= 0.3

        if not parsed.get("extracted_prompt"):
            score -= 0.2

        if not parsed.get("priority"):
            score -= 0.1

        return max(0.0, min(1.0, score))

    async def parse_batch(
        self,
        inputs: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[IntentParseResult]:
        results = []
        for user_input in inputs:
            result = await self.parse(user_input, context)
            results.append(result)
        return results


_intent_parser: Optional[IntentParserAgent] = None


def get_intent_parser(domain_id: str = "wan") -> IntentParserAgent:
    """Get global intent parser instance.
    
    Args:
        domain_id: The domain to use for intent parsing (e.g., "wan", "runway", "kling")
    
    Returns:
        Global IntentParserAgent instance
    """
    global _intent_parser
    if _intent_parser is None or _intent_parser._domain_id != domain_id:
        _intent_parser = IntentParserAgent(domain_id=domain_id)
    return _intent_parser
    return _intent_parser
