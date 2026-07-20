from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudio
from app.services.audiobook.project_exporter import resolve_existing_audio_path
from app.services.audiobook.prompt_audio_asr_provider import (
    PromptAudioAsrProvider,
    PromptAudioAsrProviderError,
)
from app.services.audiobook.prompt_audio_review_writer import (
    PromptAudioReviewError,
    apply_prompt_audio_manual_review_fields,
    load_final_audio_review_payload,
    select_prompt_audio_review_model,
)


class PromptAudioTranscriptRunnerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _resolve_chapter_audio_file(chapter_audio: ChapterAudio) -> Path:
    audio_path = str(getattr(chapter_audio, "audio_path", "") or "").strip()
    if not audio_path:
        raise PromptAudioTranscriptRunnerError("audio_source_unavailable", "章节音频路径为空")
    resolved = resolve_existing_audio_path(audio_path)
    if resolved is None:
        raise PromptAudioTranscriptRunnerError("audio_source_unavailable", "章节音频文件不存在或不可读")
    return resolved


def execute_prompt_audio_transcript(
    db: Session,
    *,
    chapter_audio: ChapterAudio,
    provider: Optional[PromptAudioAsrProvider],
    target_model: Optional[str] = None,
    provider_call_allowed: bool = False,
) -> Dict[str, Any]:
    final_audio_review = load_final_audio_review_payload(chapter_audio)
    model = select_prompt_audio_review_model(final_audio_review, target_model)

    if provider is None:
        return {
            "transcript_status": "skipped",
            "reason": "asr_provider_not_configured",
            "provider_configured": False,
            "model": model,
        }

    provider_name = str(getattr(provider, "name", "") or "unknown")
    provider_model = str(getattr(provider, "model", "") or "")
    if not provider_call_allowed:
        return {
            "transcript_status": "skipped",
            "reason": "asr_cost_not_confirmed",
            "provider_configured": True,
            "provider": provider_name,
            "provider_model": provider_model,
            "model": model,
        }

    audio_file = _resolve_chapter_audio_file(chapter_audio)
    try:
        asr_result = provider.transcribe(
            str(audio_file),
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=chapter_audio.audiobook_project_id,
            chapter_id=chapter_audio.chapter_id,
            target_model=model,
        )
    except PromptAudioAsrProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PromptAudioAsrProviderError("asr_provider_request_failed", str(exc)) from exc

    transcript = str(asr_result.transcript or "").strip()
    if not transcript:
        raise PromptAudioTranscriptRunnerError("asr_empty_transcript", "ASR provider 未返回转写文本")

    prompt_audio_quality, manual_review_fields = apply_prompt_audio_manual_review_fields(
        chapter_audio=chapter_audio,
        model=model,
        field_values={"asr_transcript": transcript},
        reviewed_by=None,
        transcript_source=f"{asr_result.provider}_asr",
        asr_provider=asr_result.provider,
        asr_provider_model=asr_result.model,
    )
    db.add(chapter_audio)
    db.commit()
    db.refresh(chapter_audio)

    return {
        "transcript_status": "completed",
        "provider_configured": True,
        "provider": asr_result.provider,
        "provider_model": asr_result.model,
        "model": model,
        "transcript_length": len(transcript),
        "manual_review_fields": manual_review_fields,
        "prompt_audio_quality": prompt_audio_quality,
        "metadata": asr_result.metadata,
    }


def normalize_prompt_audio_transcript_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, PromptAudioReviewError):
        return {"reason": exc.code, "message": str(exc)}
    if isinstance(exc, PromptAudioAsrProviderError):
        return {"reason": exc.code, "message": str(exc)}
    if isinstance(exc, PromptAudioTranscriptRunnerError):
        return {"reason": exc.code, "message": str(exc)}
    return {"reason": "asr_transcript_failed", "message": str(exc)}
