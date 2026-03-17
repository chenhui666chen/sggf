from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.vlm_utils import clamp_prompt_text, file_to_data_url, vlm_chat_json


def vlm_select_reference_and_prompt(
    *,
    vlm_adapter: Any,
    frame_description: str,
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not frame_description or not candidates:
        return None

    valid: List[Tuple[int, Dict[str, Any]]] = []
    for idx, cand in enumerate(candidates):
        path = cand.get("path")
        if isinstance(path, Path) and path.exists():
            valid.append((idx, cand))
        if len(valid) >= 120:
            break
    if not valid:
        return None

    subset: List[Tuple[int, Dict[str, Any]]] = valid
    prefilter: Optional[Dict[str, Any]] = None
    if len(valid) > 8:
        pre = vlm_prefilter_reference_images_text_only(
            vlm_adapter=vlm_adapter,
            frame_description=frame_description,
            candidates=[cand for _, cand in valid],
            max_keep=8,
        )
        indices: List[int] = []
        if isinstance(pre, dict):
            raw = pre.get("selected_ref_indices")
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, int) and 0 <= item < len(valid) and item not in indices:
                        indices.append(item)
                    if len(indices) >= 8:
                        break
        if indices:
            subset = [valid[i] for i in indices]
            prefilter = pre
        else:
            subset = valid[:8]

    system_prompt = (
        "你是专业的视觉创作助理。\n"
        "任务：从候选参考图中选择最适合生成【目标帧描述】的那张，并输出用于图片编辑模型的 edit_prompt。\n"
        "要求：只输出 JSON（不要 Markdown），字段为 ref_image_index(int)、edit_prompt(string)、reason(string)。"
    )
    system_prompt += (
        "\nOutput JSON only with keys: ref_image_index(int), edit_prompt(string), reason(string). "
        "Keep reason within 120 chars; do not add extra keys."
    )

    content: List[Dict[str, Any]] = []
    for idx, (_, cand) in enumerate(subset):
        path = cand.get("path")
        desc = str(cand.get("desc") or "").strip()
        if not isinstance(path, Path):
            continue
        content.append({"type": "text", "text": f"参考图 {idx}: {desc}"})
        content.append({"type": "image_url", "image_url": {"url": file_to_data_url(path)}})

    content.append({"type": "text", "text": f"【目标帧描述】\n{frame_description}\n\n仅输出 JSON：{{\"ref_image_index\":0,\"edit_prompt\":\"...\",\"reason\":\"...\"}}"})

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    obj = vlm_chat_json(vlm_adapter=vlm_adapter, messages=messages, temperature=0.2, max_tokens=600)
    if not isinstance(obj, dict):
        return None

    ref_idx = obj.get("ref_image_index")
    edit_prompt = obj.get("edit_prompt")
    reason = obj.get("reason")

    if not isinstance(ref_idx, int) or ref_idx < 0 or ref_idx >= len(subset):
        return None
    if not isinstance(edit_prompt, str) or not edit_prompt.strip():
        return None

    orig_idx = subset[int(ref_idx)][0]
    return {
        "ref_index": int(orig_idx),
        "edit_prompt": clamp_prompt_text(edit_prompt.strip(), limit=900),
        "reason": clamp_prompt_text(str(reason or "").strip(), limit=160),
        "prefilter": prefilter,
    }


def vlm_prefilter_reference_images_text_only(
    *,
    vlm_adapter: Any,
    frame_description: str,
    candidates: List[Dict[str, Any]],
    max_keep: int = 8,
    max_desc_chars: int = 220,
) -> Optional[Dict[str, Any]]:
    """
    两段式参考图选择：先用 text-only 粗筛压缩候选集，再走多模态精筛/改写。
    该函数仅依赖候选描述（不传图片），输出用于保留的候选索引列表。
    """
    if not frame_description or not candidates:
        return None
    if vlm_adapter is None:
        return None

    max_keep = max(1, int(max_keep))
    max_desc_chars = max(0, int(max_desc_chars))

    lines: List[str] = []
    for idx, cand in enumerate(candidates):
        desc = str(cand.get("desc") or "").strip()
        if max_desc_chars and len(desc) > max_desc_chars:
            desc = desc[:max_desc_chars].rstrip()
        if not desc:
            path = cand.get("path")
            desc = str(path) if isinstance(path, Path) else "(no desc)"
        lines.append(f"参考图 {idx}: {desc}")
        if idx >= 120:
            break

    system_prompt = (
        "你是专业的视觉创作助手。\n"
        "任务：仅基于【候选参考图描述】与【目标帧描述】，选择最相关的参考图索引列表，用于后续多模态精筛/提示词改写。\n"
        "要求：只输出 JSON（不要 Markdown），字段：selected_ref_indices(list[int])、reason(string)。\n"
        f"规则：最多选择 {max_keep} 个索引；优先保证角色一致性、场景一致性、风格一致性；尽量避免重复/冗余。\n"
    )
    system_prompt += (
        "\nOutput JSON only with keys: selected_ref_indices(list[int]), reason(string). "
        "Keep reason within 120 chars; no extra keys."
    )

    user_text = (
        "【候选参考图描述】\n"
        + "\n".join(lines)
        + "\n\n【目标帧描述】\n"
        + str(frame_description).strip()
        + "\n\n仅输出 JSON："
        + "{\"selected_ref_indices\":[0,2],\"reason\":\"...\"}"
    )

    obj = vlm_chat_json(
        vlm_adapter=vlm_adapter,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
        temperature=0.2,
        max_tokens=420,
    )
    if not isinstance(obj, dict):
        return None

    indices_raw = obj.get("selected_ref_indices")
    if not isinstance(indices_raw, list):
        indices_raw = obj.get("ref_image_indices")

    selected: List[int] = []
    if isinstance(indices_raw, list):
        for item in indices_raw:
            if not isinstance(item, int):
                continue
            if item < 0 or item >= len(candidates):
                continue
            if item in selected:
                continue
            selected.append(item)
            if len(selected) >= min(max_keep, len(candidates)):
                break

    if not selected:
        return None

    return {
        "selected_ref_indices": selected,
        "reason": clamp_prompt_text(str(obj.get("reason") or "").strip(), limit=160),
    }


def vlm_rewrite_t2i_prompt_from_references(
    *,
    vlm_adapter: Any,
    frame_description: str,
    reference_images: List[Dict[str, Any]],
    max_refs: int = 8,
) -> Optional[Dict[str, Any]]:
    """
    用 VLM 将“参考图的一致性信息”转写为可直接用于 T2I 的自包含 prompt。
    注意：底层 T2I 不接收图片，本函数的价值在于把参考图中的关键信息（外观/服装/色调/氛围）提炼成文字约束。
    """
    if not frame_description or not reference_images:
        return None
    if vlm_adapter is None:
        return None

    refs = reference_images[: max(1, int(max_refs))]
    valid: List[Tuple[int, Dict[str, Any]]] = []
    for idx, ref in enumerate(refs):
        path = ref.get("path")
        if isinstance(path, Path) and path.exists():
            valid.append((idx, ref))
    if not valid:
        return None

    content: List[Dict[str, Any]] = []
    for idx, (_, ref) in enumerate(valid):
        path = ref.get("path")
        desc = str(ref.get("desc") or "").strip()
        if not isinstance(path, Path):
            continue
        content.append({"type": "text", "text": f"参考图 {idx}: {desc}"})
        content.append({"type": "image_url", "image_url": {"url": file_to_data_url(path)}})

    system_prompt = (
        "你是专业的提示词工程师。\n"
        "任务：基于【参考图】与【目标帧描述】，写出一个可直接用于文生图（T2I）的自包含提示词。\n"
        "要求：\n"
        "1) 把参考图中的人物身份（脸型五官/发型/服装主色/体态）、风格、色调、光照等信息提炼为文字约束；\n"
        "2) 与目标帧描述合并，保证画面内容命中目标描述；\n"
        "3) 避免生成可读文字、水印、字幕、UI。\n"
        "只输出 JSON（不要 Markdown），字段：prompt(string)、selected_ref_indices(list[int])、reason(string)。"
    )
    system_prompt += (
        "\nOutput JSON only with keys: prompt(string), selected_ref_indices(list[int]), reason(string). "
        "Keep reason within 120 chars; no extra keys."
    )

    content.append(
        {
            "type": "text",
            "text": (
                f"【目标帧描述】\n{frame_description}\n\n"
                "仅输出 JSON 示例："
                "{\"prompt\":\"...\",\"selected_ref_indices\":[0,2],\"reason\":\"...\"}"
            ),
        }
    )

    obj = vlm_chat_json(
        vlm_adapter=vlm_adapter,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        temperature=0.2,
        max_tokens=700,
    )
    if not isinstance(obj, dict):
        return None

    prompt = obj.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    indices_raw = obj.get("selected_ref_indices")
    selected: List[int] = []
    if isinstance(indices_raw, list):
        for item in indices_raw:
            if not isinstance(item, int) or item < 0 or item >= len(valid):
                continue
            orig_idx = valid[int(item)][0]
            if orig_idx in selected:
                continue
            selected.append(int(orig_idx))
            if len(selected) >= min(8, len(valid)):
                break
    if not selected:
        selected = [int(orig_idx) for orig_idx, _ in valid[: min(len(valid), 3)]]

    return {
        "prompt": clamp_prompt_text(prompt, limit=900),
        "selected_ref_indices": selected,
        "reason": clamp_prompt_text(str(obj.get("reason") or "").strip(), limit=160),
    }


def vlm_build_edit_prompt_from_base_and_refs(
    *,
    vlm_adapter: Any,
    base_image_path: Path,
    base_image_desc: str,
    target_description: str,
    reference_images: List[Dict[str, Any]],
    max_refs: int = 8,
) -> Optional[Dict[str, Any]]:
    """
    基于“基准图 + 多参考图 + 目标描述”生成 edit_prompt，输出适配单图输入的 image_edit API。
    """
    if not target_description:
        return None
    if vlm_adapter is None:
        return None
    if not isinstance(base_image_path, Path) or not base_image_path.exists():
        return None

    refs = reference_images[: max(1, int(max_refs))]
    valid: List[Tuple[int, Dict[str, Any]]] = []
    for idx, ref in enumerate(refs):
        path = ref.get("path")
        if isinstance(path, Path) and path.exists():
            valid.append((idx, ref))
    content: List[Dict[str, Any]] = []
    content.append({"type": "text", "text": f"Image 1（基准图，待编辑）：{str(base_image_desc or '').strip()}"})
    content.append({"type": "image_url", "image_url": {"url": file_to_data_url(base_image_path)}})

    for idx, (_, ref) in enumerate(valid):
        path = ref.get("path")
        desc = str(ref.get("desc") or "").strip()
        if not isinstance(path, Path):
            continue
        content.append({"type": "text", "text": f"Image {idx + 2}（参考图）: {desc}"})
        content.append({"type": "image_url", "image_url": {"url": file_to_data_url(path)}})

    system_prompt = (
        "你是专业的图像编辑提示词工程师。\n"
        "任务：基于【基准图】与【参考图】（用于提炼一致性信息）以及【目标帧描述】，生成一个可直接用于图片编辑模型的 edit_prompt。\n"
        "要求：以基准图为基础，尽量保持人物身份一致（脸型五官/发型/服装主色/体态），再将画面调整为目标描述。\n"
        "多图输入时，edit_prompt 必须使用“Image 1/2/3”指代输入图片（Image 1 为基准图，Image 2/3 为参考图）。\n"
        "避免镜头术语；不要要求生成可读文字、水印、字幕、UI。\n"
        "只输出 JSON（不要 Markdown），字段：edit_prompt(string)、selected_ref_indices(list[int])、reason(string)。"
    )
    system_prompt += (
        "\nOutput JSON only with keys: edit_prompt(string), selected_ref_indices(list[int]), reason(string). "
        "Keep reason within 120 chars; no extra keys."
    )

    content.append(
        {
            "type": "text",
            "text": (
                f"【目标帧描述】\n{target_description}\n\n"
                "仅输出 JSON 示例："
                "{\"edit_prompt\":\"...\",\"selected_ref_indices\":[0,2],\"reason\":\"...\"}"
            ),
        }
    )

    obj = vlm_chat_json(
        vlm_adapter=vlm_adapter,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        temperature=0.2,
        max_tokens=700,
    )
    if not isinstance(obj, dict):
        return None

    edit_prompt = obj.get("edit_prompt")
    if not isinstance(edit_prompt, str) or not edit_prompt.strip():
        return None

    indices_raw = obj.get("selected_ref_indices")
    selected: List[int] = []
    if isinstance(indices_raw, list):
        for item in indices_raw:
            if not isinstance(item, int) or item < 0 or item >= len(valid):
                continue
            orig_idx = valid[int(item)][0]
            if orig_idx in selected:
                continue
            selected.append(int(orig_idx))
            if len(selected) >= min(8, len(valid)):
                break
    if not selected and valid:
        selected = [int(orig_idx) for orig_idx, _ in valid[: min(len(valid), 3)]]

    return {
        "edit_prompt": clamp_prompt_text(edit_prompt, limit=900),
        "selected_ref_indices": selected,
        "reason": clamp_prompt_text(str(obj.get("reason") or "").strip(), limit=160),
    }


def selected_ref_images_from_pick(
    ref_images: List[Dict[str, Any]],
    pick: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[List[int]]]:
    if not ref_images:
        return [], None
    if not isinstance(pick, dict):
        return ref_images, None
    raw = pick.get("selected_ref_indices")
    if not isinstance(raw, list) or not raw:
        return ref_images, None
    selected: List[Dict[str, Any]] = []
    indices: List[int] = []
    for item in raw:
        if not isinstance(item, int):
            continue
        if item < 0 or item >= len(ref_images):
            continue
        if item in indices:
            continue
        indices.append(item)
        selected.append(ref_images[item])
        if len(selected) >= min(8, len(ref_images)):
            break
    if not selected:
        return ref_images, None
    return selected, indices


def merge_reference_images(
    *,
    anchor: Optional[Dict[str, Any]],
    others: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _push(ref: Optional[Dict[str, Any]]) -> None:
        if not isinstance(ref, dict):
            return
        path = ref.get("path")
        if not isinstance(path, Path) or not path.exists():
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        out.append({"path": path, "desc": str(ref.get("desc") or "").strip()})

    _push(anchor)
    for ref in others or []:
        _push(ref)
    return out
