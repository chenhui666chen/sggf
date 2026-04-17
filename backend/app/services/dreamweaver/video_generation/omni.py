from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional


_FRAME_TYPE_ALIASES = {
    "first": "first_frame",
    "first_frame": "first_frame",
    "head": "first_frame",
    "start": "first_frame",
    "end": "end_frame",
    "end_frame": "end_frame",
    "last": "end_frame",
    "tail": "end_frame",
    "reference": "reference",
    "refer": "reference",
}
_FRAME_TYPE_ORDER = {"first_frame": 0, "end_frame": 1, "reference": 2}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_frame_type(value: Any) -> str:
    raw = _normalize_text(value).lower()
    return _FRAME_TYPE_ALIASES.get(raw, "reference")


def _resolve_existing_path(value: Any) -> Optional[str]:
    text = _normalize_text(value)
    if not text:
        return None
    path = Path(text)
    if path.exists():
        return str(path)
    return None


def _append_reference_frame(
    frames: list[Dict[str, Any]],
    *,
    image: Optional[str],
    image_type: str,
    source: str,
    max_items: int,
) -> None:
    if not image or len(frames) >= int(max_items):
        return
    normalized_type = _normalize_frame_type(image_type)
    for item in frames:
        if item.get("image") == image:
            existing_type = _normalize_frame_type(item.get("image_type"))
            if _FRAME_TYPE_ORDER.get(normalized_type, 99) < _FRAME_TYPE_ORDER.get(existing_type, 99):
                item["image_type"] = normalized_type
                item["source"] = source
            return
    frames.append({"image": image, "image_type": normalized_type, "source": source})


def collect_kling_omni_subject_ids(
    *,
    shot: Mapping[str, Any],
    job: Optional[Mapping[str, Any]] = None,
    provider: str = "kling",
    max_items: int = 3,
) -> list[str]:
    provider_key = _normalize_text(provider).lower() or "kling"
    subject_ids: list[str] = []
    for source in (
        shot.get("provider_subject_refs"),
        shot.get("subject_refs"),
        job.get("provider_subject_refs") if isinstance(job, Mapping) else None,
    ):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, Mapping):
                continue
            item_provider = _normalize_text(item.get("provider")).lower()
            if item_provider and item_provider != provider_key:
                continue
            subject_id = _normalize_text(item.get("subject_id") or item.get("element_id"))
            if not subject_id or subject_id in subject_ids:
                continue
            subject_ids.append(subject_id)
            if len(subject_ids) >= int(max_items):
                return subject_ids
    return subject_ids


def build_kling_omni_reference_frames(
    *,
    shot: Mapping[str, Any],
    job: Optional[Mapping[str, Any]] = None,
    max_items: int = 3,
) -> list[Dict[str, Any]]:
    frames: list[Dict[str, Any]] = []
    job_payload = dict(job or {})
    explicit = job_payload.get("omni_reference_frames")
    if isinstance(explicit, list):
        for item in explicit:
            if not isinstance(item, Mapping):
                continue
            image = _resolve_existing_path(item.get("image") or item.get("path") or item.get("image_path"))
            _append_reference_frame(
                frames,
                image=image,
                image_type=item.get("image_type") or item.get("type"),
                source=_normalize_text(item.get("source")) or "explicit",
                max_items=max_items,
            )
        if frames:
            return frames[: int(max_items)]

    inputs = job_payload.get("inputs") if isinstance(job_payload.get("inputs"), Mapping) else {}
    i2v_head_source = job_payload.get("i2v_head_source") if isinstance(job_payload.get("i2v_head_source"), Mapping) else {}
    bridge_mode = _normalize_text(i2v_head_source.get("mode")).lower()
    bridge_tail = _resolve_existing_path(i2v_head_source.get("tail_frame_path"))

    if bridge_mode == "prev_clip_tail" and bridge_tail:
        _append_reference_frame(
            frames,
            image=bridge_tail,
            image_type="first_frame",
            source="prev_clip_tail",
            max_items=max_items,
        )

    head = _resolve_existing_path(inputs.get("head"))
    tail = _resolve_existing_path(inputs.get("tail"))
    mid = _resolve_existing_path(inputs.get("mid"))

    if head:
        _append_reference_frame(
            frames,
            image=head,
            image_type="first_frame" if not frames else "reference",
            source="shot_head",
            max_items=max_items,
        )
    if tail:
        _append_reference_frame(
            frames,
            image=tail,
            image_type="end_frame",
            source="shot_tail",
            max_items=max_items,
        )
    if mid:
        _append_reference_frame(
            frames,
            image=mid,
            image_type="reference",
            source="shot_mid",
            max_items=max_items,
        )

    return sorted(
        frames[: int(max_items)],
        key=lambda item: (
            _FRAME_TYPE_ORDER.get(_normalize_frame_type(item.get("image_type")), 99),
            _normalize_text(item.get("image")),
        ),
    )


def build_kling_omni_prompt(
    *,
    base_prompt: str,
    reference_frames: list[Dict[str, Any]],
    subject_ids: list[str],
) -> str:
    prompt = _normalize_text(base_prompt)
    hints: list[str] = []

    for index, item in enumerate(reference_frames, start=1):
        image_type = _normalize_frame_type(item.get("image_type"))
        placeholder = f"<<<image_{index}>>>"
        if image_type == "first_frame":
            hints.append(f"参考首帧{placeholder}")
        elif image_type == "end_frame":
            hints.append(f"参考尾帧{placeholder}")
        else:
            hints.append(f"参考画面{placeholder}")

    if subject_ids:
        subject_placeholders = [f"<<<element_{index}>>>" for index, _item in enumerate(subject_ids, start=1)]
        hints.append(f"保持主体{'、'.join(subject_placeholders)}一致")

    suffix = "，".join(hints).strip("，")
    if prompt and suffix:
        return f"{prompt}。{suffix}"
    return prompt or suffix


def build_kling_omni_plan(
    *,
    shot: Mapping[str, Any],
    job: Optional[Mapping[str, Any]] = None,
    model: str = "kling-v3-omni",
    provider: str = "kling",
    max_subjects: int = 3,
    max_frames: int = 3,
) -> Optional[Dict[str, Any]]:
    reference_frames = build_kling_omni_reference_frames(
        shot=shot,
        job=job,
        max_items=max_frames,
    )
    subject_ids = collect_kling_omni_subject_ids(
        shot=shot,
        job=job,
        provider=provider,
        max_items=max_subjects,
    )
    if not reference_frames and not subject_ids:
        return None

    prompt = build_kling_omni_prompt(
        base_prompt=_normalize_text(shot.get("video_prompt_generated") or shot.get("motion_prompt") or shot.get("desc")),
        reference_frames=reference_frames,
        subject_ids=subject_ids,
    )
    request_preview: Dict[str, Any] = {
        "provider": provider,
        "route": "kling_omni",
        "model": _normalize_text(model) or "kling-v3-omni",
        "prompt": prompt,
        "image": ",".join(item["image"] for item in reference_frames),
        "image_types": ",".join(item["image_type"] for item in reference_frames),
        "element_ids": list(subject_ids),
    }
    if not request_preview["image"]:
        request_preview.pop("image", None)
        request_preview.pop("image_types", None)
    if not subject_ids:
        request_preview.pop("element_ids", None)

    return {
        "provider": provider,
        "route": "kling_omni",
        "model": request_preview["model"],
        "reference_frames": reference_frames,
        "subject_ids": subject_ids,
        "prompt": prompt,
        "request_preview": request_preview,
    }


def apply_kling_omni_hints_to_job(
    job: MutableMapping[str, Any],
    *,
    shot: Mapping[str, Any],
    model: str = "kling-v3-omni",
    provider: str = "kling",
) -> MutableMapping[str, Any]:
    subject_refs = shot.get("provider_subject_refs")
    if isinstance(subject_refs, list):
        job["provider_subject_refs"] = [dict(item) for item in subject_refs if isinstance(item, Mapping)]
    else:
        job.pop("provider_subject_refs", None)

    plan = build_kling_omni_plan(
        shot=shot,
        job=job,
        model=model,
        provider=provider,
    )
    if plan is None:
        job.pop("omni_reference_frames", None)
        job.pop("kling_omni_plan", None)
        return job

    job["omni_reference_frames"] = [dict(item) for item in plan["reference_frames"]]
    job["kling_omni_plan"] = dict(plan["request_preview"])
    return job
