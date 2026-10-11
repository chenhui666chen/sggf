from __future__ import annotations

import os
import re
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

from app.services.dreamweaver.library_prompt_pkg._constants import *
from app.services.dreamweaver.library_prompt_pkg._utils import *
from app.services.dreamweaver.library_prompt_pkg._character_utils import *
from app.services.dreamweaver.library_prompt_pkg._llm_enrich import *

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
    role: Optional[str] = None,
    enable_anchor_analysis: bool = True,
    enable_descriptor_enrichment: bool = True,
    force_template_rebuild: bool = False,
) -> Tuple[str, str, Dict[str, Any]]:
    preset = normalize_style_preset(style_preset)
    style_text = (style_prompt or "").strip() or style_prompt_for_preset(preset)
    negative_prompt = style_negative_prompt_for_preset(preset)
    ratio_norm = normalize_frame_ratio(ratio)
    entity_type_norm = str(entity_type or "").strip().lower()
    name_norm = str(name or "").strip()
    role_text = str(role or "").strip()
    raw_prompt_text = str(raw_prompt or "").strip()
    raw_prompt_for_merge = "" if bool(force_template_rebuild) else raw_prompt_text

    meta: Dict[str, Any] = {
        "mode": str(mode),
        "style_preset": preset,
        "style_prompt": style_text,
        "ratio": ratio_norm,
        "role": role_text,
        "character_view": _character_view_from_role(role_text),
        "llm_used": False,
        "force_template_rebuild": bool(force_template_rebuild),
    }

    descriptor_source = str(descriptor or "").strip()
    if entity_type_norm == "character" and bool(enable_descriptor_enrichment):
        sparse_input = _is_sparse_character_descriptor(descriptor_source)
        meta["descriptor_sparse_input"] = bool(sparse_input)
        meta["descriptor_enrich_llm_used"] = False
        if sparse_input:
            enable_desc_llm = env_flag("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_ENABLE_LLM", default=True)
            require_desc_llm = env_flag("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_REQUIRE_LLM", default=False)
            desc_api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
            desc_base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
            desc_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL",
                default="qwen-plus",
            )
            desc_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_DESCRIPTOR_ENRICH_TIMEOUT", "90") or "90")

            if enable_desc_llm and desc_api_key and desc_base_url:
                try:
                    enriched_out = _llm_enrich_sparse_character_descriptor(
                        name=name_norm,
                        role=role_text,
                        descriptor=descriptor_source,
                        style_preset=preset,
                        api_key=desc_api_key,
                        base_url=desc_base_url,
                        model=desc_model,
                        timeout_s=desc_timeout_s,
                    )
                    if enriched_out:
                        descriptor_source, desc_meta = enriched_out
                        meta.update({"descriptor_enrich_llm_used": True, **desc_meta})
                    else:
                        meta["descriptor_enrich_reason"] = "invalid_llm_output"
                        if require_desc_llm:
                            raise RuntimeError("character descriptor enrich LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["descriptor_enrich_llm_error"] = str(exc)
                    if require_desc_llm:
                        raise RuntimeError(f"character descriptor enrich LLM failed: {exc}") from exc
            else:
                if not enable_desc_llm:
                    meta["descriptor_enrich_reason"] = "descriptor_enrich_llm_disabled"
                else:
                    meta["descriptor_enrich_reason"] = "descriptor_enrich_llm_config_missing"
                if require_desc_llm:
                    raise RuntimeError("character descriptor enrich require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            if not meta.get("descriptor_enrich_llm_used"):
                descriptor_source = _deterministic_enrich_sparse_character_descriptor(descriptor_source)
                meta["descriptor_enrich_fallback"] = "deterministic"
        meta["descriptor_for_prompt"] = descriptor_source

    merged_descriptor = _merge_unique_segments(descriptor_source, raw_prompt_for_merge, limit=1400)
    merged_descriptor = _apply_role_focus(entity_type=entity_type_norm, role=role_text, descriptor=merged_descriptor)

    identity_anchor_text = ""
    if entity_type_norm == "character" and bool(enable_anchor_analysis):
        anchor_source_text = _merge_unique_segments(descriptor_source, raw_prompt_for_merge, limit=1800)
        anchor_candidates = _extract_character_anchor_candidates(anchor_source_text)
        meta["identity_anchor_candidates_raw"] = anchor_candidates[:10]
        meta["identity_anchor_candidate_count_raw"] = len(anchor_candidates)
        meta["identity_anchor_filter_llm_used"] = False
        meta["identity_anchor_llm_used"] = False
        meta["identity_anchor_audit_used"] = False

        if anchor_candidates:
            enable_filter_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_ENABLE_LLM", default=True)
            require_filter_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_REQUIRE_LLM", default=False)

            enable_anchor_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_ENABLE_LLM", default=True)
            require_anchor_llm = env_flag("DREAMWEAVER_LIBRARY_ANCHOR_REQUIRE_LLM", default=False)
            anchor_api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
            anchor_base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
            filter_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_ANCHOR_FILTER_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_ANCHOR_MODEL",
                default="qwen-plus",
            )
            filter_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_ANCHOR_FILTER_TIMEOUT", "90") or "90")

            anchor_model = pick_model(
                primary_env="DREAMWEAVER_LIBRARY_ANCHOR_MODEL",
                fallback_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL",
                default="qwen-plus",
            )
            anchor_timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_ANCHOR_TIMEOUT", "90") or "90")

            view_for_anchor = _character_view_from_role(role_text)
            default_anchor_limit = 6 if view_for_anchor in {"side", "back", "bust_three_quarter", "bust_side"} else 8
            anchor_candidates_final = _deterministic_filter_character_anchor_candidates(
                anchor_candidates,
                limit=default_anchor_limit,
                view=view_for_anchor,
            )
            meta["identity_anchor_candidates_det"] = anchor_candidates_final[:8]
            meta["identity_anchor_candidate_count_det"] = len(anchor_candidates_final)
            if enable_filter_llm and anchor_api_key and anchor_base_url:
                try:
                    filter_out = _llm_filter_character_anchor_candidates(
                        name=name_norm,
                        role=role_text,
                        descriptor=anchor_source_text,
                        anchor_candidates=anchor_candidates,
                        style_preset=preset,
                        api_key=anchor_api_key,
                        base_url=anchor_base_url,
                        model=filter_model,
                        timeout_s=filter_timeout_s,
                    )
                    if filter_out:
                        filtered_from_llm, filter_meta = filter_out
                        if filtered_from_llm:
                            anchor_candidates_final = filtered_from_llm
                        meta.update({"identity_anchor_filter_llm_used": True, **filter_meta})
                    else:
                        meta["identity_anchor_filter_reason"] = "invalid_llm_output"
                        if require_filter_llm:
                            raise RuntimeError("character anchor filter LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["identity_anchor_filter_llm_error"] = str(exc)
                    if require_filter_llm:
                        raise RuntimeError(f"character anchor filter LLM failed: {exc}") from exc
            else:
                if not enable_filter_llm:
                    meta["identity_anchor_filter_reason"] = "filter_llm_disabled"
                else:
                    meta["identity_anchor_filter_reason"] = "filter_llm_config_missing"
                if require_filter_llm:
                    raise RuntimeError("character anchor filter require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            if not anchor_candidates_final:
                meta["identity_anchor_reason"] = "no_filtered_anchor_candidate"
                if require_anchor_llm:
                    raise RuntimeError("character anchor candidate empty after filter")

            meta["identity_anchor_candidates"] = anchor_candidates_final[:8]
            meta["identity_anchor_candidate_count"] = len(anchor_candidates_final)

            if enable_anchor_llm and anchor_api_key and anchor_base_url:
                try:
                    anchor_out = _llm_refine_character_identity_anchor(
                        name=name_norm,
                        role=role_text,
                        descriptor=anchor_source_text,
                        anchor_candidates=anchor_candidates_final,
                        style_preset=preset,
                        api_key=anchor_api_key,
                        base_url=anchor_base_url,
                        model=anchor_model,
                        timeout_s=anchor_timeout_s,
                    )
                    if anchor_out:
                        identity_anchor_text, anchor_meta = anchor_out
                        meta.update({"identity_anchor_llm_used": True, **anchor_meta})
                        meta["identity_anchor"] = identity_anchor_text
                    else:
                        meta["identity_anchor_reason"] = "invalid_llm_output"
                        if require_anchor_llm:
                            raise RuntimeError("character anchor LLM output invalid")
                except Exception as exc:  # noqa: BLE001
                    meta["identity_anchor_llm_error"] = str(exc)
                    if require_anchor_llm:
                        raise RuntimeError(f"character anchor LLM failed: {exc}") from exc
            else:
                if not enable_anchor_llm:
                    meta["identity_anchor_reason"] = "anchor_llm_disabled"
                else:
                    meta["identity_anchor_reason"] = "anchor_llm_config_missing"
                if require_anchor_llm:
                    raise RuntimeError("character anchor require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

            # Final deterministic audit: normalize and strip non-visual semantics.
            identity_anchor_text, anchor_audit_source = _finalize_identity_anchor_text(
                identity_anchor_text,
                anchor_candidates_final,
                view_for_anchor,
            )
            meta["identity_anchor_audit_used"] = True
            meta["identity_anchor_audit_source"] = anchor_audit_source
            if identity_anchor_text:
                meta["identity_anchor"] = identity_anchor_text
            elif not str(meta.get("identity_anchor_reason") or "").strip():
                meta["identity_anchor_reason"] = "no_valid_anchor_after_audit"
        else:
            meta["identity_anchor_reason"] = "no_anchor_candidate"
    elif entity_type_norm == "character":
        meta["identity_anchor_reason"] = "anchor_analysis_disabled"

    final_descriptor = merged_descriptor
    if mode == "ai":
        enable_llm = env_flag("DREAMWEAVER_LIBRARY_PROMPT_ENABLE_LLM", default=True)
        require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag("DREAMWEAVER_LIBRARY_PROMPT_REQUIRE_LLM", default=False)
        api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
        model = pick_model(primary_env="DREAMWEAVER_LIBRARY_PROMPT_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen-plus")
        timeout_s = int(os.getenv("DREAMWEAVER_LIBRARY_PROMPT_TIMEOUT", "120") or "120")
        if enable_llm and api_key and base_url:
            try:
                out = _llm_refine_descriptor(
                    entity_type=entity_type_norm,
                    name=name_norm,
                    role=role_text,
                    source_text=merged_descriptor,
                    style_preset=preset,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=timeout_s,
                )
                if out:
                    final_descriptor, llm_meta = out
                    final_descriptor = _apply_role_focus(entity_type=entity_type_norm, role=role_text, descriptor=final_descriptor)
                    meta.update({"llm_used": True, **llm_meta})
                else:
                    meta["llm_reason"] = "invalid_llm_output"
            except Exception as exc:  # noqa: BLE001
                meta["llm_error"] = str(exc)
                if require_llm:
                    raise RuntimeError(f"library prompt LLM failed: {exc}") from exc
        elif require_llm:
            raise RuntimeError("library prompt require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

    if mode == "template" and raw_prompt_text and (not bool(force_template_rebuild)):
        prompt = normalize_library_prompt(prompt=raw_prompt_text, style_prompt=style_text, ratio=ratio_norm)
    else:
        prompt = build_library_prompt(
            entity_type=entity_type_norm,
            name=name_norm,
            descriptor=final_descriptor,
            style_prompt=style_text,
            ratio=ratio_norm,
        )
        prompt = normalize_library_prompt(prompt=prompt, style_prompt=style_text, ratio=ratio_norm)

    prompt = _clean_character_prompt_conflicts(prompt=prompt, role=role_text)
    prompt = _canonicalize_character_prompt(
        prompt=prompt,
        role=role_text,
        style_prompt=style_text,
        ratio=ratio_norm,
        name=name_norm,
        identity_anchor=identity_anchor_text,
    )
    return prompt, negative_prompt, meta
