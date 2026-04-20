from __future__ import annotations

import base64
import json
import os
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.adapter_helpers import analyze_video, chat_messages, get_model_info
from agents.vlm_utils import clamp_text_list
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    is_dreamweaver_auto_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_engine,
)


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3_vl_plus"
DEFAULT_SEMANTIC_FRAMES = "both"  # head|tail|both
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0  # 0 表示不设上限（保持历史行为）
DEFAULT_SEMANTIC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0  # 0 表示不设上限（与 semantic_max_checks 一致语义）
DEFAULT_STATE_QC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_VIDEO_CLIP_QC_THRESHOLD = 6.5
DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE = 1.0
DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS = 0  # 0 表示不设上限，可通过 qc_config/ENV 收紧
DEFAULT_VIDEO_CLIP_QC_CRITERIA = ["clarity", "smoothness", "consistency", "lighting", "color"]

def check_image_quality(
    image_path: str,
    prompt: Optional[str] = None,
    edit_prompt: Optional[str] = None,
    vlm_adapter: str = "qwen3_vl_plus",
) -> ImageQCReport:
    """
    Check image quality using VLM-based analysis.
    
    Args:
        image_path: Path to the image file
        prompt: Original generation prompt (optional)
        edit_prompt: Edit instruction for image editing (optional)
        vlm_adapter: VLM adapter name for analysis
    
    Returns:
        ImageQCReport with scores and recommendations
    """
    from pathlib import Path
    
    image_file = Path(image_path)
    if not image_file.exists():
        return ImageQCReport(
            success=False,
            image_path=image_path,
            scores=ImageQCScores(),
            issues=["Image file not found"],
            metadata={"error": "file_not_found"},
        )
    
    try:
        # Build analysis prompt
        analysis_prompt = "请评估这张图片的质量，从以下几个维度打分 (0-1)：\n"
        analysis_prompt += "1. 清晰度 (sharpness)：图像是否清晰，细节是否丰富\n"
        analysis_prompt += "2. 曝光 (exposure)：明暗是否适中，不过曝或欠曝\n"
        analysis_prompt += "3. 色彩平衡 (color_balance)：色彩是否自然，白平衡是否准确\n"
        analysis_prompt += "4. 构图 (composition)：构图是否美观，主体是否突出\n"
        
        if prompt:
            analysis_prompt += f"\n5. 提示词遵循度 (prompt_adherence)：是否准确体现了提示词'{prompt[:100]}'的要求\n"
        
        if edit_prompt:
            analysis_prompt += f"\n6. 编辑效果 (edit_quality)：是否准确实现了编辑指令'{edit_prompt[:100]}'\n"
        
        analysis_prompt += "\n请以 JSON 格式返回评分，格式如下：\n"
        analysis_prompt += "{\n"
        analysis_prompt += '  "sharpness": 0.85,\n'
        analysis_prompt += '  "exposure": 0.90,\n'
        analysis_prompt += '  "color_balance": 0.88,\n'
        analysis_prompt += '  "composition": 0.82,\n'
        analysis_prompt += '  "prompt_adherence": 0.90,\n'
        analysis_prompt += '  "overall": 0.87,\n'
        analysis_prompt += '  "issues": ["问题 1", "问题 2"],\n'
        analysis_prompt += '  "recommendations": ["建议 1", "建议 2"]\n'
        analysis_prompt += "}"
        
        # Call VLM for analysis
        from adapters.adapter_helpers import analyze_image
        result = analyze_image(
            image_path=str(image_path),
            analysis_type="quality",
            criteria=[analysis_prompt],
            model_id=vlm_adapter,
        )
        
        if not result.success:
            return ImageQCReport(
                success=False,
                image_path=image_path,
                scores=ImageQCScores(),
                issues=[f"VLM analysis failed: {result.error}"],
                metadata={"vlm_error": result.error},
            )
        
        # Parse VLM response
        try:
            vlm_response = json.loads(result.data.get("content", "{}"))
        except Exception:
            vlm_response = {}
        
        scores = ImageQCScores(
            sharpness=float(vlm_response.get("sharpness", 0.5)),
            exposure=float(vlm_response.get("exposure", 0.5)),
            color_balance=float(vlm_response.get("color_balance", 0.5)),
            composition=float(vlm_response.get("composition", 0.5)),
            style_consistency=float(vlm_response.get("style_consistency", 0.5)),
            prompt_adherence=float(vlm_response.get("prompt_adherence", 0.5)),
            overall=float(vlm_response.get("overall", 0.5)),
        )
        
        issues = vlm_response.get("issues", [])
        recommendations = vlm_response.get("recommendations", [])
        
        # Auto-generate recommendations based on scores
        if scores.sharpness < 0.6:
            recommendations.append("考虑使用超分辨率或锐化工具提升清晰度")
        if scores.exposure < 0.6:
            recommendations.append("调整曝光补偿，避免过曝或欠曝")
        if scores.color_balance < 0.6:
            recommendations.append("校正白平衡，使色彩更自然")
        if scores.composition < 0.6:
            recommendations.append("尝试裁剪或重新构图，突出主体")
        if scores.prompt_adherence < 0.6 and prompt:
            recommendations.append("优化提示词，更准确地描述所需内容")
        
        return ImageQCReport(
            success=True,
            image_path=image_path,
            scores=scores,
            issues=issues,
            recommendations=recommendations,
            metadata={
                "vlm_adapter": vlm_adapter,
                "prompt": prompt,
                "edit_prompt": edit_prompt,
            },
        )
        
    except Exception as e:
        return ImageQCReport(
            success=False,
            image_path=image_path,
            scores=ImageQCScores(),
            issues=[f"Analysis error: {str(e)}"],
            metadata={"error": str(e)},
        )
