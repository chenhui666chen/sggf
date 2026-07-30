"""快速验证 _strip_ai_formatting 格式清洗逻辑"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

from app.services.prompt_evolution.novel_rules import _strip_ai_formatting, preprocess_text


def test_markdown_bold():
    text = "这是**加粗内容**的文本"
    result, logs = _strip_ai_formatting(text)
    assert result == "这是加粗内容的文本", f"Got: {repr(result)}"
    assert "清除Markdown加粗" in logs


def test_markdown_heading():
    text = "# 标题内容\n正文段落"
    result, logs = _strip_ai_formatting(text)
    assert result == "标题内容\n正文段落", f"Got: {repr(result)}"
    assert "清除Markdown标题" in logs


def test_markdown_list():
    text = "- 列表项一\n- 列表项二"
    result, logs = _strip_ai_formatting(text)
    assert result == "列表项一\n列表项二", f"Got: {repr(result)}"


def test_half_width_punct():
    text = "中文,逗号.句号;分号"
    result, logs = _strip_ai_formatting(text)
    assert result == "中文，逗号。句号；分号", f"Got: {repr(result)}"


def test_half_width_punct_not_in_english():
    """英文上下文不应替换"""
    text = "Hello, world. Test"
    result, _ = _strip_ai_formatting(text)
    assert result == "Hello, world. Test", f"Got: {repr(result)}"


def test_chinese_space():
    text = "中文 字符 间空格"
    result, logs = _strip_ai_formatting(text)
    assert result == "中文字符间空格", f"Got: {repr(result)}"


def test_chinese_numbering():
    text = "（一）第一段\n（二）第二段"
    result, logs = _strip_ai_formatting(text)
    assert result == "第一段\n第二段", f"Got: {repr(result)}"


def test_consecutive_blank_lines():
    text = "段落一\n\n\n\n段落二"
    result, logs = _strip_ai_formatting(text)
    assert result == "段落一\n\n段落二", f"Got: {repr(result)}"


def test_normal_text_unchanged():
    text = "这是一段正常的中文文本，没有任何AI格式特征。"
    result, logs = _strip_ai_formatting(text)
    assert result == text, f"Got: {repr(result)}"
    assert logs == []


def test_ordered_list():
    text = "1. 第一项\n2. 第二项\n3. 第三项"
    result, logs = _strip_ai_formatting(text)
    assert result == "第一项\n第二项\n第三项", f"Got: {repr(result)}"


def test_inline_code():
    text = "使用`print`函数输出"
    result, logs = _strip_ai_formatting(text)
    assert result == "使用print函数输出", f"Got: {repr(result)}"


def test_preprocess_integration():
    """验证 preprocess_text 正确集成格式清洗"""
    text = "**他不禁**感叹道"
    result, logs = preprocess_text(text)
    assert "**" not in result
    assert "不禁" not in result
    assert "清除Markdown加粗" in logs
    assert "删除AI标志词: 不禁" in logs


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS: {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL: {t.__name__} - {e}")
    print(f"\n{passed} passed, {failed} failed")
