# Audiobook Task Queue Architecture

## Goals

- Move long–running audiobook generation off the FastAPI event loop.
- Persist task state so UI/API calls survive process restarts.
- Provide a single place to query status for “full pipeline”, “script only”, and “audio from script” jobs.

## Building Blocks

| Component | Purpose |
|-----------|---------|
| `Celery` | Executes background jobs. Uses Redis for broker/result backend (config via `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`). On Windows run with `-P solo` to avoid `WinError 5` from prefork mode. |
| `app/models/audiobook_task.py` | Stores durable task metadata (celery task id, project, chapter scope, type, status, progress, timestamps, detail/error JSON). |
| `AudiobookJobTracker` | Lightweight helper that updates `audiobook_tasks` rows as Celery jobs advance. Called from background coroutines and WebSocket progress hooks. |
| `app/services/audiobook/background_jobs.py` | Async workers that previously lived in the API module. They still orchestrate `AudiobookEngine`, but now accept a `tracker` to record progress. |
| `app/tasks/audiobook_tasks.py` | Celery task definitions. They invoke the async background jobs via `asyncio.run`, wrap them in DB transactions, and handle status transitions. |

## Flow

1. API endpoint validates request and creates/updates `AudiobookProject`/`ChapterAudio` rows.
2. API creates an `AudiobookTask` row with `status="pending"` and enqueues the proper Celery task (full, script_only, or from_scripts) passing the row id.
3. Celery worker picks up the job, marks the row as `running`, and executes the async background function.
4. Background function invokes `tracker.update_stage(...)` after each major milestone (per–chapter progress, stage transitions). Tracker updates DB and emits WebSocket events via the existing `ws_manager`.
5. Upon completion/failure the Celery task marks the row `completed`/`failed`, stores summary or error, and updates timestamps.
6. API endpoints (`/api/v1/audiobook/tasks`, `/tasks/{id}`) read from `AudiobookTaskRepository` instead of the in–memory tracker.

## Deployment Checklist

1. Ensure Redis is reachable and set `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` in `.env` / environment.
2. Start worker from project root (Windows uses `-P solo`):  
   `celery -A app.celery_app.celery_app worker -P solo -Q audiobook -l info`
3. Run FastAPI app as usual (uvicorn). API only enqueues jobs now.
4. Optional: run `celery -A app.celery_app.celery_app beat` if future scheduled jobs are required (not needed yet).

## Status Schema (audiobook_tasks)

| Field | Description |
|-------|-------------|
| `celery_task_id` | `task_id` from Celery, unique + indexed. |
| `task_type` | `full`, `script_only`, `audio_from_scripts`. |
| `status` | `pending`, `running`, `completed`, `failed`. |
| `current_stage` | Human text for UI (“voice_design”, etc.). |
| `progress` | Float `0-1`, derived from completed chapters / total. |
| `detail_json` | JSON blob for stage metrics / summary. |
| `error_message` | Most recent failure reason. |
| timestamps | created/updated/started/finished at UTC. |

This table is indexed by `audiobook_project_id` and `chapter_id` allowing the UI to query per–project or per–chapter jobs efficiently.

## API Changes

- `POST /api/v1/audiobook/projects` – now returns `{"job_id": "...", "task_type": "full"}` in addition to project id.
- `POST /api/v1/audiobook/projects/{id}/generate-audio-from-scripts` – enqueues `audio_from_scripts` job instead of running inline.
- `GET /api/v1/audiobook/tasks` and `/tasks/{task_id}/status` read from the persistent table.

The old in-memory polling remains temporarily for backwards compatibility but is no longer required; consumers should migrate to the new endpoints/WS events.
