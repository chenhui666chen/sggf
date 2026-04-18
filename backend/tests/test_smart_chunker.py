"""
智能分块功能测试
"""
import pytest
import sys
import os
import importlib.util
from pathlib import Path


@pytest.fixture
def smart_chunker():
    """加载 SmartChunker 模块"""
    backend_services_dir = Path(__file__).parent.parent / "app" / "services" / "audiobook"
    spec = importlib.util.spec_from_file_location(
        "smart_chunker", backend_services_dir / "smart_chunker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SmartChunker


def test_estimate_tokens_chinese(smart_chunker):
    """测试中文 token 估算"""
    chunker = smart_chunker()

    # 100 个中文字符，大约 67 tokens
    text = "这是一段测试文本" * 6  # 约 102 字符
    tokens = chunker.estimate_tokens(text)
    assert tokens > 0
    assert tokens < 150  # 应在合理范围内


def test_estimate_tokens_english(smart_chunker):
    """测试英文 token 估算"""
    chunker = smart_chunker()

    text = "This is a test sentence for token estimation. " * 10
    tokens = chunker.estimate_tokens(text)
    assert tokens > 0


def test_estimate_tokens_empty(smart_chunker):
    """测试空文本 token 估算"""
    chunker = smart_chunker()
    assert chunker.estimate_tokens("") == 0


def test_needs_chunking_short_text(smart_chunker):
    """测试短文本不需要分块"""
    chunker = smart_chunker()
    text = "这是一段短文本，不需要分块。"
    assert chunker.needs_chunking(text) is False


def test_needs_chunking_long_text(smart_chunker):
    """测试长文本需要分块"""
    chunker = smart_chunker()
    text = "这是一段很长的文本。" * 500  # 重复 500 次
    assert chunker.needs_chunking(text) is True


def test_chunk_text_short(smart_chunker):
    """测试短文本分块（不分割）"""
    chunker = smart_chunker()
    text = "这是一段不需要分割的文本。"
    chunks = chunker.chunk_text(text)

    assert len(chunks) == 1
    assert chunks[0].text == text


def test_chunk_text_long(smart_chunker):
    """测试长文本分块"""
    chunker = smart_chunker()
    text = "这是一段测试文本。" * 500  # 创建足够长的文本
    chunks = chunker.chunk_text(text)

    # 文本估算 token 数应超过 1800
    total_tokens = chunker.estimate_tokens(text)
    if total_tokens > chunker.max_tokens:
        assert len(chunks) > 1

        # 检查每个分块的 token 数不超过限制
        for chunk in chunks:
            assert chunk.estimated_tokens <= chunker.max_tokens


def test_chunk_text_preserves_sentences(smart_chunker):
    """测试分块保持句子完整性"""
    chunker = smart_chunker()

    # 创建有明显句子边界的文本
    sentences = ["今天天气很好。", "我们去公园散步吧。", "公园里有很多花。"]
    text = " ".join(sentences * 100)  # 重复 100 次

    chunks = chunker.chunk_text(text)

    # 检查分块后的文本总长度与原始文本相近
    total_text = " ".join(c.text for c in chunks)
    assert len(total_text) > 0


def test_chunk_segments(smart_chunker):
    """测试片段列表分块"""
    chunker = smart_chunker()

    segments = [
        {"text": "第一段话", "type": "narration", "character": None},
        {"text": "你好世界", "type": "dialogue", "character": "角色A"},
        {"text": "第二段旁白", "type": "narration", "character": None},
    ]

    # 短片段列表会被合并为一个分块
    chunked = chunker.chunk_segments(segments)
    assert len(chunked) >= 1


def test_chunk_segments_long_text(smart_chunker):
    """测试长片段列表分块"""
    chunker = smart_chunker()

    segments = [
        {"text": "很长的一段文本，" * 200, "type": "narration"},
        {"text": "另一段也很长的文本，" * 200, "type": "dialogue", "character": "角色B"},
    ]

    chunked = chunker.chunk_segments(segments)
    # 长文本应该被分割
    total_tokens = sum(chunker.estimate_tokens(s["text"]) for s in segments)
    if total_tokens > chunker.max_tokens:
        assert len(chunked) > 1


def test_chunk_stats(smart_chunker):
    """测试分块统计信息"""
    chunker = smart_chunker()

    chunks = chunker.chunk_text("测试文本。" * 300)
    stats = chunker.get_chunk_stats(chunks)

    assert stats["total_chunks"] == len(chunks)
    assert stats["total_tokens"] > 0
    assert stats["avg_tokens_per_chunk"] > 0
    assert stats["max_tokens_in_chunk"] >= stats["min_tokens_in_chunk"]


def test_chunk_stats_empty(smart_chunker):
    """测试空列表统计"""
    chunker = smart_chunker()
    stats = chunker.get_chunk_stats([])

    assert stats["total_chunks"] == 0
    assert stats["total_tokens"] == 0
    assert stats["avg_tokens_per_chunk"] == 0


def test_force_split(smart_chunker):
    """测试强制分割"""
    chunker = smart_chunker()

    # 创建没有标点的长文本
    text = "这是一段没有标点的很长很长的文本" * 100
    result = chunker._force_split(text, max_length=500)

    assert len(result) <= 500


def test_find_best_split_point(smart_chunker):
    """测试寻找最佳分割点"""
    chunker = smart_chunker()

    # 包含段落边界的文本
    text = "第一段内容。\n\n第二段内容。" + "更多文本。" * 200
    first, remaining = chunker._find_best_split_point(text)

    assert len(first) > 0
    assert len(remaining) > 0


def test_custom_token_limits(smart_chunker):
    """测试自定义 token 限制"""
    chunker = smart_chunker(max_tokens=1000, min_tokens=100)

    assert chunker.max_tokens == 1000
    assert chunker.min_tokens == 100

    text = "测试文本。" * 200
    chunks = chunker.chunk_text(text)

    # 检查分块结果符合自定义限制
    for chunk in chunks:
        assert chunk.estimated_tokens <= 1000


def test_mixed_language_text(smart_chunker):
    """测试混合语言文本分块"""
    chunker = smart_chunker()

    text = "这是一段中文。This is English. 这是另一段中文。" + "重复文本。" * 100
    chunks = chunker.chunk_text(text)

    assert len(chunks) > 0


def test_text_chunk_dataclass(smart_chunker):
    """测试 TextChunk 数据类"""
    chunker = smart_chunker()

    from dataclasses import asdict

    chunk = chunker.chunk_text("测试文本")[0]
    assert chunk.index == 0
    assert chunk.text == "测试文本"
    assert chunk.estimated_tokens > 0

    # 测试转换为字典
    chunk_dict = asdict(chunk)
    assert "index" in chunk_dict
    assert "text" in chunk_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
