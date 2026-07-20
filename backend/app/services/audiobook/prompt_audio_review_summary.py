from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from app.models.audiobook import ChapterAudio


logger = logging.getLogger(__name__)


def _as_number(value: Any) -> Optional[float]:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _safe_divide(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


@dataclass
class _ModelAccumulator:
    model: str
    model_family: str = ""
    chapter_audio_count: int = 0
    reviewed_model_count: int = 0
    tag_parse_reviewed_count: int = 0
    tag_parse_success_count: int = 0
    text_contamination_reviewed_count: int = 0
    text_contamination_count: int = 0
    score_reviewed_count: int = 0
    score_sum: float = 0.0
    notes_count: int = 0
    asr_assist_count: int = 0
    asr_tag_residue_count: int = 0
    asr_suggested_contamination_count: int = 0
    asr_suggested_tag_parse_failure_count: int = 0
    segment_count: int = 0
    audio_segment_count: int = 0
    missing_audio_count: int = 0
    manual_review_segment_count: int = 0
    latest_reviewed_at: str = ""
    chapter_audio_ids: set[int] = field(default_factory=set)

    def add_model_entry(self, chapter_audio_id: int, model_entry: Dict[str, Any]) -> None:
        self.chapter_audio_ids.add(chapter_audio_id)
        self.chapter_audio_count = len(self.chapter_audio_ids)
        if not self.model_family:
            self.model_family = str(model_entry.get("model_family") or "").strip()

        self.segment_count += int(_as_number(model_entry.get("segments_count")) or 0)
        self.audio_segment_count += int(_as_number(model_entry.get("audio_segments_count")) or 0)
        self.missing_audio_count += int(_as_number(model_entry.get("missing_audio_count")) or 0)
        manual_indices = model_entry.get("manual_review_segment_indices")
        if isinstance(manual_indices, list):
            self.manual_review_segment_count += len(manual_indices)

        manual_fields = model_entry.get("manual_review_fields")
        if not isinstance(manual_fields, dict):
            return

        reviewed = False
        tag_parse_success = manual_fields.get("tag_parse_success")
        if isinstance(tag_parse_success, bool):
            reviewed = True
            self.tag_parse_reviewed_count += 1
            if tag_parse_success:
                self.tag_parse_success_count += 1

        text_contamination = manual_fields.get("text_contamination")
        if isinstance(text_contamination, bool):
            reviewed = True
            self.text_contamination_reviewed_count += 1
            if text_contamination:
                self.text_contamination_count += 1

        score = _as_number(manual_fields.get("score"))
        if score is not None:
            reviewed = True
            self.score_reviewed_count += 1
            self.score_sum += float(score)

        notes = str(manual_fields.get("notes") or "").strip()
        if notes:
            reviewed = True
            self.notes_count += 1

        asr_assist = manual_fields.get("asr_assist")
        if isinstance(asr_assist, dict) and asr_assist.get("available") is True:
            reviewed = True
            self.asr_assist_count += 1
            if asr_assist.get("detected_tag_residue") is True:
                self.asr_tag_residue_count += 1
            if asr_assist.get("suggested_text_contamination") is True:
                self.asr_suggested_contamination_count += 1
            if asr_assist.get("suggested_tag_parse_success") is False:
                self.asr_suggested_tag_parse_failure_count += 1

        reviewed_at = str(manual_fields.get("reviewed_at") or "").strip()
        if reviewed_at and reviewed_at > self.latest_reviewed_at:
            self.latest_reviewed_at = reviewed_at

        if reviewed:
            self.reviewed_model_count += 1

    def to_dict(self) -> Dict[str, Any]:
        average_score = (
            round(self.score_sum / self.score_reviewed_count, 2)
            if self.score_reviewed_count > 0
            else None
        )
        return {
            "model": self.model,
            "model_family": self.model_family,
            "chapter_audio_count": self.chapter_audio_count,
            "reviewed_model_count": self.reviewed_model_count,
            "tag_parse_reviewed_count": self.tag_parse_reviewed_count,
            "tag_parse_success_count": self.tag_parse_success_count,
            "tag_parse_success_rate": _safe_divide(
                self.tag_parse_success_count,
                self.tag_parse_reviewed_count,
            ),
            "text_contamination_reviewed_count": self.text_contamination_reviewed_count,
            "text_contamination_count": self.text_contamination_count,
            "text_contamination_rate": _safe_divide(
                self.text_contamination_count,
                self.text_contamination_reviewed_count,
            ),
            "score_reviewed_count": self.score_reviewed_count,
            "average_score": average_score,
            "notes_count": self.notes_count,
            "asr_assist_count": self.asr_assist_count,
            "asr_tag_residue_count": self.asr_tag_residue_count,
            "asr_suggested_contamination_count": self.asr_suggested_contamination_count,
            "asr_suggested_tag_parse_failure_count": self.asr_suggested_tag_parse_failure_count,
            "segment_count": self.segment_count,
            "audio_segment_count": self.audio_segment_count,
            "missing_audio_count": self.missing_audio_count,
            "manual_review_segment_count": self.manual_review_segment_count,
            "latest_reviewed_at": self.latest_reviewed_at or None,
        }


def load_prompt_audio_quality(chapter_audio: ChapterAudio) -> Optional[Dict[str, Any]]:
    raw_review = str(getattr(chapter_audio, "final_audio_review_json", "") or "").strip()
    if not raw_review:
        return None

    try:
        final_audio_review = json.loads(raw_review)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "忽略损坏的最终音频评审 JSON: chapter_audio_id=%s error=%s",
            getattr(chapter_audio, "id", None),
            exc,
        )
        return None

    if not isinstance(final_audio_review, dict):
        return None

    prompt_audio_quality = final_audio_review.get("prompt_audio_quality")
    return prompt_audio_quality if isinstance(prompt_audio_quality, dict) else None


def build_prompt_audio_review_summary(
    *,
    audiobook_project_id: int,
    chapter_audios: Iterable[ChapterAudio],
) -> Dict[str, Any]:
    model_accumulators: Dict[str, _ModelAccumulator] = {}
    chapter_audio_count = 0
    chapter_audio_with_quality_count = 0
    skipped_chapter_audio_count = 0

    for chapter_audio in chapter_audios:
        chapter_audio_count += 1
        prompt_audio_quality = load_prompt_audio_quality(chapter_audio)
        if not prompt_audio_quality:
            skipped_chapter_audio_count += 1
            continue

        by_model = prompt_audio_quality.get("by_model")
        if not isinstance(by_model, dict):
            skipped_chapter_audio_count += 1
            continue

        chapter_audio_with_quality_count += 1
        for model, raw_model_entry in by_model.items():
            if not isinstance(raw_model_entry, dict):
                continue
            model_name = str(model or "").strip()
            if not model_name:
                continue
            accumulator = model_accumulators.setdefault(
                model_name,
                _ModelAccumulator(model=model_name),
            )
            accumulator.add_model_entry(
                int(getattr(chapter_audio, "id", 0) or 0),
                raw_model_entry,
            )

    models = [
        accumulator.to_dict()
        for accumulator in sorted(
            model_accumulators.values(),
            key=lambda item: item.model,
        )
    ]
    coverage = {
        "chapter_audio_count": chapter_audio_count,
        "chapter_audio_with_quality_count": chapter_audio_with_quality_count,
        "skipped_chapter_audio_count": skipped_chapter_audio_count,
        "model_count": len(models),
        "reviewed_model_count": sum(item["reviewed_model_count"] for item in models),
        "tag_parse_reviewed_count": sum(item["tag_parse_reviewed_count"] for item in models),
        "tag_parse_success_count": sum(item["tag_parse_success_count"] for item in models),
        "text_contamination_reviewed_count": sum(
            item["text_contamination_reviewed_count"]
            for item in models
        ),
        "text_contamination_count": sum(item["text_contamination_count"] for item in models),
        "score_reviewed_count": sum(item["score_reviewed_count"] for item in models),
        "asr_assist_count": sum(item["asr_assist_count"] for item in models),
        "asr_tag_residue_count": sum(item["asr_tag_residue_count"] for item in models),
        "asr_suggested_contamination_count": sum(
            item["asr_suggested_contamination_count"]
            for item in models
        ),
        "asr_suggested_tag_parse_failure_count": sum(
            item["asr_suggested_tag_parse_failure_count"]
            for item in models
        ),
    }

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "coverage": coverage,
        "models": models,
    }


CSV_COLUMNS = [
    "model",
    "model_family",
    "chapter_audio_count",
    "reviewed_model_count",
    "tag_parse_reviewed_count",
    "tag_parse_success_count",
    "tag_parse_success_rate",
    "text_contamination_reviewed_count",
    "text_contamination_count",
    "text_contamination_rate",
    "score_reviewed_count",
    "average_score",
    "notes_count",
    "asr_assist_count",
    "asr_tag_residue_count",
    "asr_suggested_contamination_count",
    "asr_suggested_tag_parse_failure_count",
    "segment_count",
    "audio_segment_count",
    "missing_audio_count",
    "manual_review_segment_count",
    "latest_reviewed_at",
]


def build_prompt_audio_review_summary_csv(summary: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for model_summary in summary.get("models") or []:
        if not isinstance(model_summary, dict):
            continue
        writer.writerow({column: model_summary.get(column) for column in CSV_COLUMNS})
    return buffer.getvalue()
