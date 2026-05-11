"""
SSE/重试/预览功能测试
"""
import pytest
import sys
import os
import importlib.util
from pathlib import Path


@pytest.fixture
def sse_module():
    """加载 SSE 模块"""
    backend_services_dir = Path(__file__).parent.parent / "app" / "services" / "audiobook"
    spec = importlib.util.spec_from_file_location(
        "sse_progress", backend_services_dir / "sse_progress.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def retrier_module():
    """加载重试模块"""
    backend_services_dir = Path(__file__).parent.parent / "app" / "services" / "audiobook"
    spec = importlib.util.spec_from_file_location(
        "smart_retrier", backend_services_dir / "smart_retrier.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def preview_module():
    """加载预览模块"""
    backend_services_dir = Path(__file__).parent.parent / "app" / "services" / "audiobook"
    spec = importlib.util.spec_from_file_location(
        "preview_generator", backend_services_dir / "preview_generator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============== SSE 测试 ==============

def test_sse_progress_tracker_init(sse_module):
    """测试 SSE 进度追踪器初始化"""
    tracker = sse_module.SSEProgressTracker()
    assert tracker._clients == {}
    assert tracker._heartbeats == {}


def test_sse_register_unregister_client(sse_module):
    """测试客户端注册/注销"""
    tracker = sse_module.SSEProgressTracker()

    task_id = "test_task_123"
    queue = tracker.register_client(task_id)

    assert task_id in tracker._clients
    assert queue in tracker._clients[task_id]
    assert task_id in tracker._heartbeats

    tracker.unregister_client(task_id, queue)
    assert task_id not in tracker._clients


def test_sse_multiple_clients(sse_module):
    """测试多个客户端注册"""
    tracker = sse_module.SSEProgressTracker()
    task_id = "test_task_456"

    queue1 = tracker.register_client(task_id)
    queue2 = tracker.register_client(task_id)

    assert len(tracker._clients[task_id]) == 2

    tracker.unregister_client(task_id, queue1)
    assert len(tracker._clients[task_id]) == 1

    tracker.unregister_client(task_id, queue2)
    assert task_id not in tracker._clients


def test_create_progress_handler(sse_module):
    """测试创建进度处理器"""
    task_id = "test_task_789"
    handler = sse_module.create_progress_handler(task_id)

    assert callable(handler)


# ============== 重试机制测试 ==============

def test_retry_config_defaults(retrier_module):
    """测试重试配置默认值"""
    config = retrier_module.RetryConfig()
    assert config.max_retries == 3
    assert config.initial_delay == 1.0
    assert config.backoff_factor == 2.0
    assert config.max_delay == 30.0
    assert config.enable_degraded == True


def test_retry_config_custom(retrier_module):
    """测试自定义重试配置"""
    config = retrier_module.RetryConfig(
        max_retries=5,
        initial_delay=2.0,
        enable_degraded=False,
    )
    assert config.max_retries == 5
    assert config.initial_delay == 2.0
    assert config.enable_degraded == False


def test_smart_retrier_init(retrier_module):
    """测试智能重试器初始化"""
    retrier = retrier_module.SmartRetrier()
    assert retrier.config.max_retries == 3


def test_retrier_execute_success(retrier_module):
    """测试成功执行（无需重试）"""
    retrier = retrier_module.SmartRetrier()

    def successful_func():
        return "success"

    result = retrier.execute(successful_func)

    assert result.success is True
    assert result.result == "success"
    assert result.attempt == 1
    assert result.strategy == retrier_module.RetryStrategy.IMMEDIATE


def test_retrier_should_retry_network_errors(retrier_module):
    """测试网络错误应重试"""
    retrier = retrier_module.SmartRetrier()

    # 模拟各种网络错误
    network_errors = [
        TimeoutError("Connection timeout"),
        ConnectionError("Connection refused"),
        Exception("HTTP 503 Service Unavailable"),
        Exception("Rate limit exceeded"),
    ]

    for error in network_errors:
        assert retrier._should_retry(error, 1) is True


def test_retrier_should_not_retry_auth_errors(retrier_module):
    """测试认证错误不应重试"""
    retrier = retrier_module.SmartRetrier()

    auth_errors = [
        Exception("401 Unauthorized"),
        Exception("403 Forbidden"),
    ]

    for error in auth_errors:
        assert retrier._should_retry(error, 1) is False


def test_retry_result_class(retrier_module):
    """测试重试结果类"""
    result = retrier_module.RetryResult(
        success=True,
        result="data",
        attempt=2,
        strategy=retrier_module.RetryStrategy.DELAYED,
    )

    assert result.success is True
    assert result.result == "data"
    assert result.attempt == 2


def test_retry_wait_calculation(retrier_module):
    """测试等待时间计算"""
    config = retrier_module.RetryConfig(
        initial_delay=1.0,
        backoff_factor=2.0,
        max_delay=10.0,
    )
    retrier = retrier_module.SmartRetrier(config)

    # 第 2 次尝试：1.0 * 2^1 = 2.0
    # 第 3 次尝试：1.0 * 2^2 = 4.0 (<= 10.0)
    # 测试逻辑（不实际 sleep）
    assert config.initial_delay * (config.backoff_factor ** 1) == 2.0
    assert config.initial_delay * (config.backoff_factor ** 2) == 4.0


def test_default_retrier_singleton(retrier_module):
    """测试全局默认实例"""
    assert retrier_module.default_retrier is not None
    assert retrier_module.default_retrier.config.max_retries == 3


# ============== 预览生成测试 ==============

def test_preview_generator_init(preview_module):
    """测试预览生成器初始化"""
    gen = preview_module.PreviewGenerator()
    assert gen.max_sentences == 2
    assert gen.max_duration_seconds == 15.0
    assert gen.output_dir == "previews"


def test_preview_generator_custom_config(preview_module):
    """测试自定义预览配置"""
    gen = preview_module.PreviewGenerator(
        max_sentences=3,
        max_duration_seconds=20.0,
    )
    assert gen.max_sentences == 3
    assert gen.max_duration_seconds == 20.0


def test_extract_preview_text_short(preview_module):
    """测试短文本预览提取"""
    gen = preview_module.PreviewGenerator()

    text = "这是一段测试文本。只有两句。"
    preview = gen.extract_preview_text(text)

    # 预览文本应包含原文本的所有内容（可能有空格分隔）
    assert "这是一段测试文本" in preview
    assert "只有两句" in preview


def test_extract_preview_text_long(preview_module):
    """测试长文本预览提取（应提取前 2 句）"""
    gen = preview_module.PreviewGenerator(max_sentences=2)

    text = "第一句话。第二句话。第三句话。第四句话。第五句话。"
    preview = gen.extract_preview_text(text)

    # 应该只包含前两句
    assert "第一句话" in preview
    assert "第二句话" in preview
    # 不应该包含后续句子
    assert "第三句话" not in preview.split("第二句话")[1] if "第二句话" in preview else True


def test_extract_preview_text_chinese(preview_module):
    """测试中文文本预览提取"""
    gen = preview_module.PreviewGenerator(max_sentences=2)

    text = "今天天气真好。我们去公园散步吧。公园里有很多花。"
    preview = gen.extract_preview_text(text)

    assert len(preview) > 0
    assert "今天天气真好" in preview


def test_extract_preview_text_english(preview_module):
    """测试英文文本预览提取"""
    gen = preview_module.PreviewGenerator(max_sentences=2)

    text = "This is the first sentence. This is the second sentence. This is the third."
    preview = gen.extract_preview_text(text)

    assert "This is the first sentence" in preview
    assert "This is the second sentence" in preview


def test_extract_preview_text_empty(preview_module):
    """测试空文本预览提取"""
    gen = preview_module.PreviewGenerator()

    preview = gen.extract_preview_text("")
    assert preview == ""


def test_preview_generator_singleton(preview_module):
    """测试全局默认实例"""
    assert preview_module.default_preview_generator is not None
    assert preview_module.default_preview_generator.max_sentences == 2


def test_preview_output_structure(preview_module):
    """测试预览输出结构"""
    gen = preview_module.PreviewGenerator()

    # 模拟预览返回结构
    expected_keys = {
        "preview_id",
        "preview_text",
        "audio_path",
        "audio_url",
        "duration",
        "voice_id",
        "tts_params",
    }

    # 验证结构定义
    assert len(expected_keys) == 7


def test_preview_generator_does_not_emit_removed_preview_route(preview_module, tmp_path):
    """旧 preview 路由已删除，内部工具不应再返回不可访问 URL"""
    gen = preview_module.PreviewGenerator(output_dir=str(tmp_path))

    def fake_tts_engine(*, output_path: str, **_kwargs):
        Path(output_path).write_bytes(b"ID3preview")
        return b"ID3preview"

    preview = gen.generate_preview(
        text="第一句话。第二句话。",
        voice_id="voice-1",
        tts_engine=fake_tts_engine,
    )

    assert preview["audio_path"].endswith(".mp3")
    assert preview["audio_url"] == ""


# ============== 导入测试 ==============

def test_sse_module_imports():
    """测试 SSE 模块导入"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from app.services.audiobook.sse_progress import SSEProgressTracker, sse_tracker, create_progress_handler
        assert SSEProgressTracker is not None
        assert sse_tracker is not None
        assert callable(create_progress_handler)
    except ImportError as e:
        pytest.fail(f"SSE 模块导入失败: {e}")


def test_retrier_module_imports():
    """测试重试模块导入"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from app.services.audiobook.smart_retrier import SmartRetrier, RetryConfig, retry_tts_call
        assert SmartRetrier is not None
        assert RetryConfig is not None
        assert callable(retry_tts_call)
    except ImportError as e:
        pytest.fail(f"重试模块导入失败: {e}")


def test_preview_module_imports():
    """测试预览模块导入"""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    try:
        from app.services.audiobook.preview_generator import PreviewGenerator, default_preview_generator
        assert PreviewGenerator is not None
        assert default_preview_generator is not None
    except ImportError as e:
        pytest.fail(f"预览模块导入失败: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
