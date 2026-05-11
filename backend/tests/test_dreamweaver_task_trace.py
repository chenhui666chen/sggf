from app.services.dreamweaver.task_trace import (
    build_dreamweaver_trace_context,
    merge_dreamweaver_trace_context,
)


class TestBuildDreamweaverTraceContext:
    def test_empty(self):
        result = build_dreamweaver_trace_context()
        assert result == {}

    def test_trace_id_from_explicit(self):
        result = build_dreamweaver_trace_context(trace_id="abc-123", celery_task_id="task-456")
        assert result["trace_id"] == "abc-123"
        assert result["celery_task_id"] == "task-456"

    def test_trace_id_fallback_to_celery_task_id(self):
        result = build_dreamweaver_trace_context(celery_task_id="task-789")
        assert result["trace_id"] == "task-789"

    def test_all_fields(self):
        result = build_dreamweaver_trace_context(
            trace_id="t-1",
            celery_task_id="c-1",
            project_id=42,
            user_id=7,
            run_id="run-abc",
            stage="storyboard",
            state="DONE",
            status="completed",
            progress=100,
            error_type="timeout",
            error_message="exceeded limit",
            queue="dreamweaver.gpu",
            source_chapter_count=3,
            quality_mode="quality",
            video_engine="wan_auto",
            billing_freeze_event_id="bf-1",
            billing_settle_event_id="bs-1",
            billing_release_event_id="br-1",
        )
        assert result["trace_id"] == "t-1"
        assert result["celery_task_id"] == "c-1"
        assert result["project_id"] == 42
        assert result["user_id"] == 7
        assert result["run_id"] == "run-abc"
        assert result["stage"] == "storyboard"
        assert result["state"] == "DONE"
        assert result["status"] == "completed"
        assert result["progress"] == 100
        assert result["error_type"] == "timeout"
        assert result["error_message"] == "exceeded limit"
        assert result["queue"] == "dreamweaver.gpu"
        assert result["source_chapter_count"] == 3
        assert result["quality_mode"] == "quality"
        assert result["video_engine"] == "wan_auto"
        assert result["billing_freeze_event_id"] == "bf-1"
        assert result["billing_settle_event_id"] == "bs-1"
        assert result["billing_release_event_id"] == "br-1"

    def test_none_values_excluded(self):
        result = build_dreamweaver_trace_context(
            trace_id="t-1",
            project_id=42,
            run_id=None,
            stage=None,
        )
        assert "trace_id" in result
        assert "project_id" in result
        assert "run_id" not in result
        assert "stage" not in result

    def test_zero_values_preserved(self):
        result = build_dreamweaver_trace_context(progress=0, source_chapter_count=0)
        assert result["progress"] == 0
        assert result["source_chapter_count"] == 0


class TestMergeDreamweaverTraceContext:
    def test_none_trace_context(self):
        detail = {"run_id": "r-1", "status": "running"}
        result = merge_dreamweaver_trace_context(detail, None)
        assert result == {"run_id": "r-1", "status": "running"}

    def test_empty_trace_context(self):
        detail = {"run_id": "r-1"}
        result = merge_dreamweaver_trace_context(detail, {})
        assert result == {"run_id": "r-1"}

    def test_adds_new_keys(self):
        detail = {"run_id": "r-1"}
        trace = {"trace_id": "t-1", "project_id": 42}
        result = merge_dreamweaver_trace_context(detail, trace)
        assert result == {"run_id": "r-1", "trace_id": "t-1", "project_id": 42}

    def test_does_not_overwrite_existing_keys(self):
        detail = {"run_id": "r-1", "status": "running"}
        trace = {"run_id": "r-2", "status": "completed", "trace_id": "t-1"}
        result = merge_dreamweaver_trace_context(detail, trace)
        assert result["run_id"] == "r-1"
        assert result["status"] == "running"
        assert result["trace_id"] == "t-1"

    def test_skips_none_values_in_trace(self):
        detail = {"run_id": "r-1"}
        trace = {"trace_id": "t-1", "stage": None, "error_type": None}
        result = merge_dreamweaver_trace_context(detail, trace)
        assert "trace_id" in result
        assert "stage" not in result
        assert "error_type" not in result

    def test_does_not_mutate_original_detail(self):
        detail = {"run_id": "r-1"}
        trace = {"trace_id": "t-1"}
        merge_dreamweaver_trace_context(detail, trace)
        assert detail == {"run_id": "r-1"}
