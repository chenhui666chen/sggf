from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app/api/v1/workflow/routes_optimize.py"

def _src():
    return SOURCE.read_text(encoding="utf-8")

def test_optimize_chapter_route_is_registered():
    text = _src()
    assert "/optimize-chapter" in text
    assert "async def optimize_chapter(" in text

def test_regenerate_progress_uses_helper():
    text = _src()
    assert "def _update_history_progress(" in text
    idx = text.index("正在准备生成章节")
    window = text[idx-400:idx+120]
    assert "_update_history_progress(" in window

def test_payload_and_post_save():
    text = _src()
    assert "content" in text
    assert text.count("start_chapter_post_save_task(") >= 2
    assert "reason" in text


def test_editor_buttons_use_chapter_scoped_context():
    text = _src()
    assert 'def _build_editor_chapter_context(' in text
    assert 'content_agent.process(regenerate_prompt)' in text
    assert 'create_chapter(' not in text
    assert 'outline_excerpt' in text


def test_optimize_imports_token_helpers():
    text = _src()
    assert '_estimate_tokens_by_chars,' in text
    assert 'current_score = _extract_iteration_review_score(review_report)' in text
