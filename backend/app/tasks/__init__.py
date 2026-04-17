"""
Celery task registrations.
"""
from .audiobook_tasks import (  # noqa: F401
    run_full_audiobook_task,
    run_script_generation_task,
    run_audio_from_scripts_task,
)

from .dreamweaver_tasks import run_dreamweaver_task  # noqa: F401

from .feedback_tasks import apply_feedback_to_profiles_task, collect_qc_feedback_task  # noqa: F401
