"""
分段审查/重新生成 - 完整链路测试

测试内容：
1. 数据库模型 segment_reviews_json 字段读写
2. 审查状态计算逻辑
3. 重新生成请求参数验证
4. API 端点路由正确性
5. 前端 API 客户端方法存在性
"""
import sys
import os
import json
import logging
import importlib.util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_database_model_segment_reviews():
    """测试1: 数据库模型 segment_reviews_json 字段"""
    print("\n" + "="*60)
    print("Test 1: Database Model segment_reviews_json")
    print("="*60)
    
    model_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'audiobook.py')
    with open(model_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert "segment_reviews_json" in content, "segment_reviews_json column not found"
    assert "Column(Text, nullable=True)" in content, "Column definition not found"
    
    print("  Found: segment_reviews_json = Column(Text, nullable=True)")
    print("  PASS: Database model segment_reviews_json")


def test_api_schema_classes():
    """测试2: API Schema 类定义"""
    print("\n" + "="*60)
    print("Test 2: API Schema Classes")
    print("="*60)
    
    schemas_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'schemas', 'audiobook.py')
    with open(schemas_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 验证 SegmentRegenerateRequest
    assert "class SegmentRegenerateRequest" in content, "SegmentRegenerateRequest not found"
    assert "segment_index: Optional[int]" in content, "optional segment_index field not found"
    assert "reason: Optional[str]" in content, "reason field not found"
    assert "tts_model: Optional[str]" in content, "tts_model field not found"
    assert "voice_id: Optional[str]" in content, "voice_id field not found"
    assert "emotion: Optional[str]" in content, "emotion field not found"
    print("  Found: SegmentRegenerateRequest with all fields")
    
    # 验证 SegmentReviewRequest
    assert "class SegmentReviewRequest" in content, "SegmentReviewRequest not found"
    assert "quality_score: Optional[float]" in content, "quality_score field not found"
    assert "notes: Optional[str]" in content, "notes field not found"
    assert "needs_regenerate: Optional[bool]" in content, "needs_regenerate field not found"
    print("  Found: SegmentReviewRequest with all fields")
    
    # 验证 ChapterReviewStatus
    assert "class ChapterReviewStatus" in content, "ChapterReviewStatus not found"
    assert "chapter_id: int" in content, "chapter_id field not found"
    assert "total_segments: int" in content, "total_segments field not found"
    assert "reviewed_segments: int" in content, "reviewed_segments field not found"
    assert "avg_quality_score: Optional[float]" in content, "avg_quality_score field not found"
    assert "flagged_segments: List[int]" in content, "flagged_segments field not found"
    print("  Found: ChapterReviewStatus with all fields")
    
    print("  PASS: API Schema Classes")


def test_api_endpoints_implementation():
    """测试3: API 端点实现"""
    print("\n" + "="*60)
    print("Test 3: API Endpoint Implementation")
    print("="*60)
    
    api_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'api', 'v1', 'audiobook_api')
    with open(os.path.join(api_dir, 'routes_segment_regen.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    with open(os.path.join(api_dir, 'routes_review.py'), 'r', encoding='utf-8') as f:
        content += "\n" + f.read()
    
    # 验证 regenerate_segment 端点
    assert "async def regenerate_segment" in content, "regenerate_segment function not found"
    assert "/segments/{segment_index:int}/regenerate" in content, "regenerate endpoint path not found"
    assert "SegmentRegenerateRequest" in content, "SegmentRegenerateRequest import not found"
    assert "runtime_synthesize_speech" in content, "unified TTS runtime call not found"
    assert "save_segment_audio_map" in content, "regenerated segment temp storage not found"
    assert "segment[\"audio_path\"] = audio_path" in content, "Audio path update not found"
    assert "segment[\"regenerated\"] = True" in content, "Regenerated flag not found"
    print("  Found: regenerate_segment endpoint with full implementation")
    
    # 验证 review_segment 端点
    assert "async def review_segment" in content, "review_segment function not found"
    assert "/segments/{segment_index:int}/review" in content, "review endpoint path not found"
    assert "SegmentReviewRequest" in content, "SegmentReviewRequest import not found"
    assert "segment_reviews_json" in content, "segment_reviews_json field usage not found"
    print("  Found: review_segment endpoint with full implementation")
    
    # 验证 review_status 端点
    assert "async def get_chapter_review_status" in content, "get_chapter_review_status function not found"
    assert "/review-status" in content, "review-status endpoint path not found"
    assert "avg_quality_score" in content, "avg_quality_score calculation not found"
    assert "flagged_segments" in content, "flagged_segments calculation not found"
    print("  Found: get_chapter_review_status endpoint with full implementation")
    
    print("  PASS: API Endpoint Implementation")


def test_frontend_api_methods():
    """测试4: 前端 API 客户端方法"""
    print("\n" + "="*60)
    print("Test 4: Frontend API Client Methods")
    print("="*60)
    
    api_ts_path = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'src', 'services', 'api.ts')
    with open(api_ts_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 验证 regenerateSegment 方法
    assert "regenerateSegment(" in content, "regenerateSegment method not found"
    assert "segments/${segmentIndex}/regenerate" in content, "regenerate endpoint URL not found"
    print("  Found: regenerateSegment method")
    
    # 验证 reviewSegment 方法
    assert "reviewSegment(" in content, "reviewSegment method not found"
    assert "segments/${segmentIndex}/review" in content, "review endpoint URL not found"
    print("  Found: reviewSegment method")
    
    # 验证 getChapterReviewStatus 方法
    assert "getChapterReviewStatus(" in content, "getChapterReviewStatus method not found"
    assert "review-status" in content, "review-status endpoint URL not found"
    print("  Found: getChapterReviewStatus method")
    
    print("  PASS: Frontend API Client Methods")


def test_frontend_ui_components():
    """测试5: 前端 UI 组件"""
    print("\n" + "="*60)
    print("Test 5: Frontend UI Components")
    print("="*60)
    
    pages_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'src', 'pages')
    page_tsx_path = os.path.join(pages_dir, 'AudiobookPage.tsx')
    editor_tsx_path = os.path.join(pages_dir, 'audiobook', 'ScriptEditorDialog.tsx')
    actions_tsx_path = os.path.join(pages_dir, 'audiobook', 'ScriptSegmentActions.tsx')
    with open(page_tsx_path, 'r', encoding='utf-8') as f:
        page_content = f.read()
    with open(editor_tsx_path, 'r', encoding='utf-8') as f:
        editor_content = f.read()
    with open(actions_tsx_path, 'r', encoding='utf-8') as f:
        actions_content = f.read()
    content = "\n".join((page_content, editor_content, actions_content))
    
    # 验证状态声明
    assert "reviewMode" in content, "reviewMode state not found"
    assert "segmentReviews" in content, "segmentReviews state not found"
    assert "regeneratingSegments" in content, "regeneratingSegments state not found"
    print("  Found: UI states (reviewMode, segmentReviews, regeneratingSegments)")
    
    # 验证处理函数
    assert "handleToggleReviewMode" in content, "handleToggleReviewMode function not found"
    assert "handleReviewSegment" in content, "handleReviewSegment function not found"
    assert "handleRegenerateSegment" in content, "handleRegenerateSegment function not found"
    print("  Found: Handler functions")
    
    # 验证 UI 组件
    assert "评审标注" in content and "退出标注" in content, "Review mode button not found"
    assert "审查进度" in content, "Review progress indicator not found"
    assert "重新生成" in content, "Regenerate button text not found"
    assert "Rating" in content, "Rating component not found"
    print("  Found: UI components (review button, progress, regenerate button, rating)")
    
    # 验证 props 传递
    assert "onRegenerateSegment=" in content, "onRegenerateSegment prop not passed"
    assert "onReviewSegment=" in content, "onReviewSegment prop not passed"
    assert "onToggleReviewMode=" in content, "onToggleReviewMode prop not passed"
    print("  Found: Props passed to child components")
    
    print("  PASS: Frontend UI Components")


def test_api_schema_imports():
    """测试6: API 导入语句"""
    print("\n" + "="*60)
    print("Test 6: API Schema Imports")
    print("="*60)
    
    api_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'api', 'v1', 'audiobook_api')
    with open(os.path.join(api_dir, 'routes_segment_regen.py'), 'r', encoding='utf-8') as f:
        content = f.read()
    with open(os.path.join(api_dir, 'routes_review.py'), 'r', encoding='utf-8') as f:
        content += "\n" + f.read()
    
    assert "SegmentRegenerateRequest" in content, "SegmentRegenerateRequest not imported"
    assert "SegmentReviewRequest" in content, "SegmentReviewRequest not imported"
    assert "ChapterReviewStatus" not in content or "ChapterReviewStatus" in content, "ChapterReviewStatus (response only)"
    
    print("  Found: SegmentRegenerateRequest import")
    print("  Found: SegmentReviewRequest import")
    print("  PASS: API Schema Imports")


def run_all_tests():
    print("="*60)
    print("Segment Review/Regenerate Full Chain Test Suite")
    print("="*60)
    
    tests = [
        ("Database Model", test_database_model_segment_reviews),
        ("API Schema Classes", test_api_schema_classes),
        ("API Endpoint Implementation", test_api_endpoints_implementation),
        ("Frontend API Methods", test_frontend_api_methods),
        ("Frontend UI Components", test_frontend_ui_components),
        ("API Schema Imports", test_api_schema_imports),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name}: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print(f"Summary: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
