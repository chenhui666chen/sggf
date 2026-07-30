"""Audiobook API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/audiobook", tags=["audiobook"])

from app.api.v1.audiobook_api import routes_tts
from app.api.v1.audiobook_api import routes_seed_scene_test
from app.api.v1.audiobook_api import routes_projects
from app.api.v1.audiobook_api import routes_character_scope
from app.api.v1.audiobook_api import routes_delete
from app.api.v1.audiobook_api import routes_tasks
from app.api.v1.audiobook_api import routes_download
from app.api.v1.audiobook_api import routes_script
from app.api.v1.audiobook_api import routes_segment_preview
from app.api.v1.audiobook_api import routes_segment_regen
from app.api.v1.audiobook_api import routes_review
from app.api.v1.audiobook_api import routes_prompt_audio_review
from app.api.v1.audiobook_api import routes_subtitle
from app.api.v1.audiobook_api import routes_smart_chunk
from app.api.v1.audiobook_api import routes_misc
from app.api.v1.audiobook_api import routes_audio_library
from app.api.v1.audiobook_api import routes_voice_pool
