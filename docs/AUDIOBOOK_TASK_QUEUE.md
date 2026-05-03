# Audiobook Task Queue Architecture

Last updated: 2026-05-03

## Goals

- Move long–running audiobook generation off the FastAPI event loop.
- Persist task state so UI/API calls survive process restarts.
- Provide a single place to query status for full generation, script-only generation, audio-from-script generation, and project export jobs.
- Keep chapter-level run/checkpoint state consistent with top-level Celery task state.

## Building Blocks

| Component | Purpose |
|-----------|---------|
| `Celery` | Executes background jobs. Uses Redis for broker/result backend (config via `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`). On Windows run with `-P solo` to avoid `WinError 5` from prefork mode. |
| `app/models/audiobook_task.py` | Stores durable task metadata (celery task id, project, chapter scope, type, status, progress, timestamps, detail/error JSON). |
| `app/models/audiobook.py::ChapterAudioRun` | Stores chapter-level run state, resumable checkpoint JSON, temp segment metadata, failure diagnostics, and cleanup window. |
| `app/services/audiobook/task_support.py` | Creates task rows, pre-generates Celery task ids, creates queued chapter runs, builds resume checkpoint documents, and validates resumability. |
| `AudiobookJobTracker` | Updates `audiobook_tasks`, synchronizes associated chapter runs for stage/failure transitions, and emits SSE progress events. |
| `app/services/audiobook/background_jobs*.py` | Async orchestration for full generation, script-only generation, and audio-from-scripts generation. They call `AudiobookEngine` and report progress through the tracker. |
| `app/tasks/audiobook_tasks.py` | Celery task definitions. They invoke async background jobs via `asyncio.run`, handle status transitions, and also run project export tasks. |
| `app/services/audiobook/sse_progress.py` | Server-Sent Events progress stream used by the frontend, with polling fallback on the client side. |

## Flow

1. API endpoint validates request and creates/updates `AudiobookProject`/`ChapterAudio` rows as needed.
2. `enqueue_audiobook_task()` creates an `AudiobookTask` row with `status="pending"` and pre-generates the Celery task id.
3. The same Celery task id is persisted to `AudiobookTask.celery_task_id`.
4. The API pre-creates queued `ChapterAudioRun` rows for all target chapters and writes initial checkpoint documents before dispatch.
5. Resume requests bind source checkpoint data to the queued runs through a `before_dispatch` callback.
6. The Celery signature is dispatched with `apply_async(task_id=pre_generated_id)`, so the worker cannot run before task/run/checkpoint rows exist.
7. Celery worker marks the task as `running` and executes the async background function.
8. Background functions invoke `tracker.update_stage(...)` after major milestones. Tracker updates `AudiobookTask`, updates the relevant `ChapterAudioRun` when chapter detail exists, and emits SSE progress events.
9. Upon completion/failure the Celery task marks the row `completed`/`failed`, stores summary or error, and updates timestamps. Top-level failures also mark the same-task unfinished chapter runs as `failed`.
10. API endpoints (`/api/v1/audiobook/tasks`, `/tasks/{id}/status`) read durable task state from `AudiobookTaskRepository`.

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
| `task_type` | `full`, `script_only`, `audio_from_scripts`, `export_m4b`, `export_audacity`. |
| `status` | `pending`, `running`, `completed`, `failed`. |
| `current_stage` | Human text for UI (“voice_design”, etc.). |
| `progress` | Float `0-1`, derived from completed chapters / total. |
| `detail_json` | JSON blob for stage metrics / summary. |
| `error_message` | Most recent failure reason. |
| timestamps | created/updated/started/finished at UTC. |

This table is indexed by `audiobook_project_id` and `chapter_id` allowing the UI to query per–project or per–chapter jobs efficiently.

## Chapter Run / Checkpoint State

`chapter_audio_runs` is the source of truth for chapter-level recovery:

| Field | Description |
|-------|-------------|
| `run_type` | Generation mode that produced the run. |
| `celery_task_id` | Celery id that links the run to its top-level `AudiobookTask`. |
| `status` / `current_stage` | Chapter-level run state. |
| `checkpoint_json` | Resume metadata, including input hashes, completed segments, temp asset references, errors, and expiry. |
| `expires_at` | Resume window expiry for failed/paused/cancelled runs. |
| `error_message` | Chapter-level failure reason. |

Completed and explicitly failed runs are terminal for top-level failure fan-out. A generic top-level failure does not overwrite an already failed run with detailed chapter diagnostics.

## API Changes

- `POST /api/v1/audiobook/projects` – now returns `{"job_id": "...", "task_type": "full"}` in addition to project id.
- `POST /api/v1/audiobook/projects/{id}/generate-audio-from-scripts` – enqueues `audio_from_scripts` job instead of running inline.
- `POST /api/v1/audiobook/projects/{id}/exports/m4b/queue` and `/exports/audacity/queue` – enqueue project export jobs.
- `GET /api/v1/audiobook/tasks` and `/tasks/{task_id}/status` read from the persistent task table.
- `GET /api/v1/audiobook/tasks/{task_id}/stream` streams SSE progress after user/project authorization.

The frontend uses SSE as the primary live progress channel and keeps polling as a fallback. New consumers should not depend on process-local in-memory task state.

## Verification

Relevant regression tests:

```powershell
.\.venv\Scripts\python.exe -m pytest "backend/tests/test_audiobook_task_enqueue_order.py" "backend/tests/test_audiobook_job_tracker.py" "backend/tests/test_audiobook_runtime_truth.py" "backend/tests/test_audiobook_sse_routes.py"
```
