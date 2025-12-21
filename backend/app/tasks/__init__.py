"""
Celery task registrations.
"""
from .audiobook_tasks import (  # noqa: F401
    run_full_audiobook_task,
    run_script_generation_task,
    run_audio_from_scripts_task,
)

from .dreamweaver_tasks import run_dreamweaver_mock_task  # noqa: F401
