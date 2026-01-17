from __future__ import annotations

import os
from typing import Any, Dict, Literal, Optional, Tuple

from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model
from pipeline.media_presets import normalize_frame_ratio
from pipeline.style_presets import (
    normalize_style_preset,
    style_negative_prompt_for_preset,
    style_prompt_for_preset,
)

from app.services.dreamweaver.library import build_library_prompt


LibraryPromptMode = Literal["template", "ai"]


def _is_style_line(line: str) -> bool:
    raw = (line or "").strip()
    return raw.startswith(("风格：", "风格:", "风格预设：", "风格预设:"))


def _is_ratio_line(line: str) -> bool:
    raw = (line or "").strip()
    return raw.startswith(("画幅：", "画幅:", "画面比例：", "画面比例:", "比例：", "比例:"))


def normalize_library_prompt(*, prompt: str, style_prompt: str, ratio: str) -> str:
    """
    将任意输入 prompt 规范为“风格/画幅在顶部”，并移除重复行。

    说明：
    - 不试图解析/改变其它字段，避免覆盖用户自定义内容（KISS）。
    - ratio 会做 normalize_frame_ratio 归一化。
    """
    style_text = (style_prompt or "").strip() or style_prompt_for_preset(None)
    ratio_norm = normalize_frame_ratio(ratio)

    style_line = f"风格：{style_text}（严格保持一致，不要混合风格）"
    ratio_line = f"画幅：{ratio_norm}"

    body_lines = []
    for line in str(prompt or "").splitlines():
        if _is_style_line(line) or _is_ratio_line(line):
            continue
        body_lines.append(line.rstrip())
    body = "\n".join(body_lines).strip()

    if body:
        return f"{style_line}\n{ratio_line}\n{body}".strip()
    return f"{style_line}\n{ratio_line}".strip()


def _llm_refine_descriptor(
    *,
    entity_type: str,
    name: str,
    source_text: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    用 LLM 将“人物/场景/道具描述”整理为更适合图片生成的视觉描述片段。
    """
    entity_type_norm = (entity_type or "").strip().lower()
    name = (name or "").strip()
    text = (source_text or "").strip()
    if not entity_type_norm or not name or not text:
        return None

    system = (
        "你是资深影视概念设计提示词工程师。\n"
        "任务：把输入的素材描述整理为适合图片生成模型的“主体视觉描述片段”。\n"
        "规则：\n"
        "1) 只写与画面可见相关的信息（外观/服饰/材质/环境/光影/镜头/构图等），去重、精炼。\n"
        "2) 不要编造输入未提供的具体事实（如明确的发色/衣服颜色/年龄等），除非输入明确给出。\n"
        "3) 不要输出风格/画幅/通用约束（无水印等），这些由系统模板统一提供。\n"
        "4) 只输出严格 JSON（不要 Markdown，不要解释）。\n"
        '输出 schema：{"descriptor": "..." }\n'
    )

    user = (
        f"实体类型：{entity_type_norm}\n"
        f"实体名称：{name}\n"
        "原始描述：\n"
        f"{text[:2000]}\n"
    )

    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=int(timeout_s),
        temperature=0.2,
    )
    obj = extract_json_object(content)
    if not isinstance(obj, dict):
        return None
    descriptor = obj.get("descriptor")
    if not isinstance(descriptor, str) or not descriptor.strip():
        return None

    refined = descriptor.strip()
    if len(refined) > 400:
        refined = refined[:400]
    return refined, {"llm_model": model}


def suggest_library_prompt(
    *,
    mode: LibraryPromptMode,
    entity_type: str,
    name: str,
    descriptor: str,
    raw_prompt: str,
    style_preset: str,
    ratio: str,
    style_prompt: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    返回：(prompt, negative_prompt, meta)。

    - template：仅做风格/画幅注入与规范化（不走 LLM）。
    - ai：用 LLM 整理 descriptor，再用模板构造 prompt。
    """
    preset = normalize_style_preset(style_preset)
    style_text = (style_prompt or "").strip() or style_prompt_for_preset(preset)
    negative_prompt = style_negative_prompt_for_preset(preset)
    ratio_norm = normalize_frame_ratio(ratio)

    meta: Dict[str, Any] = {
        "mode": str(mode),
        "style_preset": preset,
        "style_prompt": style_text,
        "ratio": ratio_norm,
    }

    if mode == "template":
        base = (raw_prompt or "").strip()
        if not base:
            base = build_library_prompt(
                entity_type=str(entity_type or "").strip().lower(),
                name=str(name or "").strip(),
                descriptor=str(descriptor or "").strip(),
                style_prompt=style_text,
                ratio=ratio_norm,
            )
        prompt = normalize_library_prompt(prompt=base, style_prompt=style_text, ratio=ratio_norm)
        return prompt, negative_prompt, meta

    # mode == "ai"
    enable_llm = env_flag("DREAMWEAVER_LIBRARY_PROMPT_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag("DREAMWEAVER_LIBRARY_PROMPT_REQUIRE_LLM", default=False)
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
    model = pick_model(primary_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen-plus")
    timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_PROMPT_TIMEOUT", "120") or "120")

    refined_descriptor = str(descriptor or "").strip()
    if enable_llm and api_key and base_url:
        try:
            source_text = (raw_prompt or "").strip() or refined_descriptor
            out = _llm_refine_descriptor(
                entity_type=str(entity_type or "").strip().lower(),
                name=str(name or "").strip(),
                source_text=source_text,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
            )
            if out:
                refined_descriptor, llm_meta = out
                meta.update({"llm_used": True, **llm_meta})
            else:
                meta.update({"llm_used": False, "llm_reason": "invalid_llm_output"})
        except Exception as exc:  # noqa: BLE001
            meta.update({"llm_used": False, "llm_error": str(exc)})
            if require_llm:
                raise RuntimeError(f"library prompt LLM failed: {exc}") from exc
    else:
        meta.update({"llm_used": False, "llm_reason": "llm_disabled_or_missing_key"})
        if require_llm:
            raise RuntimeError("library prompt require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

    prompt = build_library_prompt(
        entity_type=str(entity_type or "").strip().lower(),
        name=str(name or "").strip(),
        descriptor=refined_descriptor,
        style_prompt=style_text,
        ratio=ratio_norm,
    )
    prompt = normalize_library_prompt(prompt=prompt, style_prompt=style_text, ratio=ratio_norm)
    return prompt, negative_prompt, meta
