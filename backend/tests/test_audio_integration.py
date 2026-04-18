"""
集成测试 - 所有音频优化功能

测试内容：
1. 智能文本分段
2. 词语替换修正
3. STT 回验
4. 完整工作流集成测试
"""
import sys
import os
import io
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("❌ pydub 不可用")
    sys.exit(1)

# 直接从文件导入避免循环依赖
import importlib.util

def load_module(module_name, file_path):
    """动态加载模块"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# 加载模块
base_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'services', 'audiobook')

audio_mixer_module = load_module("audio_mixer", os.path.join(base_path, 'audio_mixer.py'))
AudioMixer = audio_mixer_module.AudioMixer

segmenter_module = load_module("smart_segmenter", os.path.join(base_path, 'smart_segmenter.py'))
SmartTextSegmenter = segmenter_module.SmartTextSegmenter
SegmentType = segmenter_module.SegmentType

substitutor_module = load_module("word_substitutor", os.path.join(base_path, 'word_substitutor.py'))
WordSubstitutor = substitutor_module.WordSubstitutor

stt_module = load_module("stt_verifier", os.path.join(base_path, 'stt_verifier.py'))
STTVerifier = stt_module.STTVerifier


def test_smart_segmentation():
    """测试智能文本分段"""
    print("\n" + "="*60)
    print("📝 测试1: 智能文本分段")
    print("="*60)
    
    # 创建分段器
    segmenter = SmartTextSegmenter(
        max_segment_length=100,
        enable_paragraph_split=True,
        enable_sentence_split=True,
        enable_phrase_split=True,
    )
    
    # 测试文本（包含多段落、多句子）
    test_text = """
这是一段测试文本。它包含多个句子！
这是第二个段落，有不同的内容。
第三个段落：这里有一些特殊的内容，包括逗号、分号等标点符号。
    """.strip()
    
    print(f"  原始文本长度: {len(test_text)} 字符")
    
    # 执行分段
    segments = segmenter.segment(test_text, chapter_info="测试章节")
    
    print(f"  分段数量: {len(segments)}")
    print(f"  分段详情:")
    for i, seg in enumerate(segments):
        print(f"    [{i}] ({seg.segment_type.value}): {seg.text[:30]}...")
    
    # 验证每个片段不超过最大长度
    for seg in segments:
        assert len(seg.text) <= segmenter.max_segment_length, \
            f"片段超长: {len(seg.text)} > {segmenter.max_segment_length}"
    
    # 验证分段类型
    segment_types = [seg.segment_type for seg in segments]
    assert any(t in segment_types for t in [SegmentType.PARAGRAPH, SegmentType.SENTENCE, SegmentType.PHRASE]), \
        "应该包含至少一种分段类型"
    
    print("  ✅ 智能文本分段测试通过")
    return True


def test_word_substitution():
    """测试词语替换修正"""
    print("\n" + "="*60)
    print("🔄 测试2: 词语替换修正")
    print("="*60)
    
    # 创建替换器
    substitutor = WordSubstitutor(
        enable_default_rules=True,
    )
    
    # 添加保护词
    substitutor.add_protected_word("张三")
    substitutor.add_protected_word("李四")
    
    # 测试文本
    test_text = "张三说：1+2=3，API 很好用！"
    
    print(f"  原始文本: {test_text}")
    
    # 执行替换
    result = substitutor.substitute(test_text)
    
    print(f"  处理后文本: {result.processed_text}")
    print(f"  替换次数: {len(result.substitutions_made)}")
    for orig, repl in result.substitutions_made:
        print(f"    '{orig}' -> '{repl}'")
    print(f"  保护词: {result.protected_words}")
    
    # 验证保护词未被替换
    assert "张三" in result.processed_text, "保护词'张三'应该被保留"
    
    # 验证替换生效
    assert result.substitutions_made, "应该有替换记录"
    
    print("  ✅ 词语替换修正测试通过")
    return True


def test_stt_verification():
    """测试 STT 回验"""
    print("\n" + "="*60)
    print("🎤 测试3: STT 回验")
    print("="*60)
    
    # 创建验证器（使用降级模式）
    verifier = STTVerifier(
        model_size="base",
        language="zh",
        similarity_threshold=0.75,
        enable_whisper=False  # 降级模式
    )
    
    # 测试文本
    test_text = "这是一段测试文本，用于验证 STT 回验功能。"
    
    print(f"  原始文本: {test_text}")
    
    # 模拟音频数据（静音）
    silent_audio = AudioSegment.silent(duration=1000)
    audio_buffer = io.BytesIO()
    silent_audio.export(audio_buffer, format="mp3")
    audio_data = audio_buffer.getvalue()
    
    # 执行验证（降级模式）
    result = verifier.verify(
        audio_data=audio_data,
        original_text=test_text,
        audio_format="mp3"
    )
    
    print(f"  验证成功: {result.success}")
    print(f"  相似度: {result.similarity_score:.2f}")
    print(f"  词错误率: {result.word_error_rate:.2f}")
    print(f"  通过: {result.passed}")
    print(f"  置信度: {result.confidence:.2f}")
    
    # 降级模式应该返回成功
    assert result.success, "降级模式应该返回成功"
    assert result.similarity_score > 0.5, "降级模式应该有较高相似度"
    
    # 测试相似度计算
    sim = verifier._calculate_similarity("测试文本", "测试文本")
    assert sim == 1.0, "相同文本相似度应为 1.0"
    
    sim2 = verifier._calculate_similarity("测试文本", "不同内容")
    assert 0.0 <= sim2 <= 1.0, "相似度应在 0-1 之间"
    
    print("  ✅ STT 回验测试通过")
    return True


def test_integrated_workflow():
    """测试完整工作流集成"""
    print("\n" + "="*60)
    print("🔄 测试4: 完整工作流集成")
    print("="*60)
    
    # 1. 文本分段
    segmenter = SmartTextSegmenter(max_segment_length=50)
    
    test_text = """
这是一段长文本。它包含多个句子和段落。
第二个段落有不同的内容。
    """.strip()
    
    segments = segmenter.segment(test_text)
    print(f"  1. 分段完成: {len(segments)} 个片段")
    
    # 2. 词语替换
    substitutor = WordSubstitutor(enable_default_rules=True)
    processed_texts = []
    for seg in segments:
        result = substitutor.substitute(seg.text)
        processed_texts.append(result.processed_text)
    
    print(f"  2. 替换完成: 处理了 {len(processed_texts)} 个片段")
    
    # 3. 生成测试音频
    audio_segments = []
    for text in processed_texts:
        # 模拟 TTS 生成（静音音频）
        audio = AudioSegment.silent(duration=1000)
        buffer = io.BytesIO()
        audio.export(buffer, format="mp3")
        audio_segments.append(buffer.getvalue())
    
    print(f"  3. 音频生成完成: {len(audio_segments)} 个片段")
    
    # 4. 音频混合（带优化）
    mixer = AudioMixer(
        enable_silence_trim=True,
        enable_loudness_norm=True,
        enable_semantic_pause=True,
        paragraph_pause_ms=1500,
        sentence_pause_ms=500,
        phrase_pause_ms=250,
    )
    
    # 传递分段类型
    segment_types = [seg.segment_type.value for seg in segments]
    mixed_audio = mixer._mix_with_pydub(
        audio_segments,
        segment_types=segment_types
    )
    
    print(f"  4. 音频混合完成: {len(mixed_audio)} bytes")
    
    # 5. STT 验证（降级模式）
    verifier = STTVerifier(enable_whisper=False)
    full_text = " ".join(processed_texts)
    
    verification = verifier.verify(
        audio_data=mixed_audio,
        original_text=full_text,
        audio_format="mp3"
    )
    
    print(f"  5. STT 验证: {'通过' if verification.passed else '未通过'}")
    
    # 验证整个流程
    assert len(segments) > 0, "应该有分段结果"
    assert len(audio_segments) > 0, "应该有音频片段"
    assert len(mixed_audio) > 0, "应该有混合音频"
    assert verification.success, "STT 验证应该成功"
    
    print("  ✅ 完整工作流集成测试通过")
    return True


def test_edge_cases():
    """测试边界情况"""
    print("\n" + "="*60)
    print("🔍 测试5: 边界情况")
    print("="*60)
    
    # 测试1: 空文本分段
    segmenter = SmartTextSegmenter()
    empty_segments = segmenter.segment("")
    assert len(empty_segments) == 0, "空文本应该返回空列表"
    print("  ✅ 空文本分段正常")
    
    # 测试2: 超长文本分段
    long_text = "这是一段超长文本。" * 100
    long_segments = segmenter.segment(long_text)
    assert len(long_segments) > 1, "长文本应该被分成多个片段"
    for seg in long_segments:
        assert len(seg.text) <= segmenter.max_segment_length, \
            f"片段超长: {len(seg.text)}"
    print(f"  ✅ 长文本分段正常: {len(long_segments)} 个片段")
    
    # 测试3: 音频混合空列表
    mixer = AudioMixer()
    empty_mix = mixer.mix_chapter([])
    assert empty_mix == b"", "空列表混合应该返回空字节"
    print("  ✅ 空音频列表混合正常")
    
    # 测试4: STT 验证空文本
    verifier = STTVerifier(enable_whisper=False)
    empty_result = verifier.verify(b"", "")
    assert empty_result.success, "空文本验证应该成功（降级模式）"
    print("  ✅ 空文本 STT 验证正常")
    
    print("  ✅ 边界情况测试通过")
    return True


def run_all_tests():
    """运行所有集成测试"""
    print("="*60)
    print("🎯 开始运行音频优化功能集成测试")
    print("="*60)
    
    tests = [
        ("智能文本分段", test_smart_segmentation),
        ("词语替换修正", test_word_substitution),
        ("STT 回验", test_stt_verification),
        ("完整工作流集成", test_integrated_workflow),
        ("边界情况", test_edge_cases),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ {name} 测试失败: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print(f"📊 集成测试总结: {passed} 通过, {failed} 失败")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)