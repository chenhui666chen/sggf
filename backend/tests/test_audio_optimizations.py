"""
测试音频优化功能 - 真实链路验证

测试内容：
1. AudioMixer 静音修剪功能
2. AudioMixer 响度标准化功能  
3. AudioMixer 语义停顿功能
4. AudioMixer 完整音频混合流程
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
    print("❌ pydub 不可用，无法运行测试")
    sys.exit(1)

from app.services.audiobook.audio_mixer import AudioMixer


def create_test_audio(duration_ms=1000, frequency=440, volume_db=-20):
    """创建测试用的音频片段"""
    # 生成音频
    audio = AudioSegment.silent(duration=duration_ms)
    # 添加正弦波
    sine_wave = AudioSegment.silent(duration=duration_ms)
    
    # 创建简单的音频
    try:
        # 使用pydub生成测试音频
        audio = sine_wave.overlay(
            AudioSegment(
                data=bytes(int(128 + 127 * (i / 100.0) * (1 + volume_db/100)) % 256 for i in range(duration_ms)),
                sample_width=1,
                frame_rate=22050,
                channels=1
            )
        )
    except:
        # 简单生成静音音频作为替代
        audio = AudioSegment.silent(duration=duration_ms)
    
    return audio


def create_realistic_test_audio(text_content="这是一段测试音频"):
    """创建更真实的测试音频（带首尾静音）"""
    # 生成三段音频用于测试
    audio1 = AudioSegment.silent(duration=500)  # 500ms静音
    audio1 = audio1.overlay(AudioSegment.silent(duration=200))  # 添加一些内容
    
    audio2 = AudioSegment.silent(duration=800)  # 800ms静音
    
    audio3 = AudioSegment.silent(duration=600)  # 600ms静音
    
    return audio1, audio2, audio3


def test_silence_trimming():
    """测试静音修剪功能"""
    print("\n" + "="*60)
    print("🔊 测试1: 静音修剪功能")
    print("="*60)
    
    # 创建带首尾静音的音频
    original_audio = AudioSegment.silent(duration=1000)
    # 在中间添加一些"内容"
    middle_content = AudioSegment.silent(duration=200)
    test_audio = AudioSegment.silent(duration=300) + middle_content + AudioSegment.silent(duration=300)
    
    print(f"  原始音频长度: {len(test_audio)}ms")
    
    # 创建启用静音修剪的 AudioMixer
    mixer_trim = AudioMixer(enable_silence_trim=True, silence_trim_threshold=-40)
    
    # 测试静音修剪
    trimmed_audio = mixer_trim._trim_silence(test_audio)
    print(f"  修剪后音频长度: {len(trimmed_audio)}ms")
    
    # 创建不启用静音修剪的 AudioMixer
    mixer_no_trim = AudioMixer(enable_silence_trim=False)
    not_trimmed_audio = mixer_no_trim._trim_silence(test_audio)
    print(f"  不启用修剪的音频长度: {len(not_trimmed_audio)}ms")
    
    assert len(trimmed_audio) <= len(test_audio), "静音修剪应该减少音频长度"
    assert len(not_trimmed_audio) == len(test_audio), "不启用修剪时音频长度不应改变"
    
    print("  ✅ 静音修剪测试通过")


def test_trim_silence_keeps_tail_padding_for_word_endings():
    """尾部静音修剪必须保留韵尾缓冲。

    中文尾字的气声/自然衰减常低于 -40dBFS，若紧贴最后一个响音块一刀切断，
    会产生"最后一个字没吐完就被截断"的听感。
    """
    from pydub.generators import Sine

    speech = Sine(440).to_audio_segment(duration=1000).apply_gain(-6)
    audio = speech + AudioSegment.silent(duration=1200)

    mixer = AudioMixer(enable_silence_trim=True, silence_trim_threshold=-40)
    trimmed = mixer._trim_silence(audio)

    # 修剪后应比纯语音段至少多保留 200ms 韵尾缓冲
    assert len(trimmed) >= 1000 + 200, "尾部修剪不应贴着最后一个响音块切断"
    # 但也不应把 1200ms 尾部静音全部保留
    assert len(trimmed) <= 1000 + 600, "超出韵尾缓冲的尾部静音应被剪除"


def test_loudness_normalization():
    """测试响度标准化功能"""
    print("\n" + "="*60)
    print("📊 测试2: 响度标准化功能")
    print("="*60)
    
    # 创建带实际内容的音频（静音上叠加波形）
    def create_tone(duration_ms=1000, frequency=440, db_change=-20):
        tone = AudioSegment.silent(duration=duration_ms)
        try:
            sine_wave = AudioSegment(
                data=b''.join(
                    bytes([int(127 + 127 * __import__('math').sin(2 * __import__('math').pi * frequency * i / 22050))])
                    for i in range(int(duration_ms * 22050 / 1000))
                ),
                sample_width=1,
                frame_rate=22050,
                channels=1
            )
            tone = tone.overlay(sine_wave) + db_change
        except:
            tone = tone + db_change
        return tone
    
    quiet_audio = create_tone(db_change=-30)
    normal_audio = create_tone(db_change=-10)
    
    print(f"  低响度音频: {quiet_audio.dBFS:.1f} dBFS")
    print(f"  正常响度音频: {normal_audio.dBFS:.1f} dBFS")
    
    # 测试响度标准化
    mixer_norm = AudioMixer(enable_loudness_norm=True, target_loudness_lufs=-16.0)
    
    normalized_quiet = mixer_norm._normalize_loudness(quiet_audio)
    normalized_normal = mixer_norm._normalize_loudness(normal_audio)
    
    print(f"  标准化后低响度: {normalized_quiet.dBFS:.1f} dBFS")
    print(f"  标准化后正常响度: {normalized_normal.dBFS:.1f} dBFS")
    
    # 测试不启用标准化的情况 - 音频应该完全不变
    mixer_no_norm = AudioMixer(enable_loudness_norm=False)
    not_normalized = mixer_no_norm._normalize_loudness(quiet_audio)
    
    # 验证未启用标准化时返回同一对象
    assert not_normalized is quiet_audio or abs(not_normalized.dBFS - quiet_audio.dBFS) < 0.1, "不启用标准化时音频不应改变"
    
    print("  ✅ 响度标准化测试通过")


def test_semantic_pauses():
    """测试语义停顿功能"""
    print("\n" + "="*60)
    print("🔇 测试3: 语义停顿功能")
    print("="*60)
    
    # 创建音频片段
    audio1 = AudioSegment.silent(duration=1000)
    audio2 = AudioSegment.silent(duration=1000)
    audio3 = AudioSegment.silent(duration=1000)
    
    # 转换为bytes
    def audio_to_bytes(audio):
        buf = io.BytesIO()
        audio.export(buf, format="mp3")
        return buf.getvalue()
    
    segments = [audio_to_bytes(audio1), audio_to_bytes(audio2), audio_to_bytes(audio3)]
    
    # 测试带语义停顿的混合
    mixer_semantic = AudioMixer(
        enable_semantic_pause=True,
        paragraph_pause_ms=1500,
        sentence_pause_ms=500,
        phrase_pause_ms=250
    )
    
    # 测试不同段类型
    segment_types = ["paragraph", "sentence", "phrase"]
    result = mixer_semantic._mix_with_pydub(
        segments,
        segment_types=segment_types
    )
    
    print(f"  语义停顿混合结果长度: {len(result)} bytes")
    
    # 测试不启用语义停顿的混合
    mixer_no_semantic = AudioMixer(enable_semantic_pause=False, silence_duration=500)
    result_no_semantic = mixer_no_semantic._mix_with_pydub(segments)
    print(f"  无 semantic 停顿混合结果长度: {len(result_no_semantic)} bytes")
    
    print("  ✅ 语义停顿测试通过")


def test_full_mixing_pipeline():
    """测试完整混合流程"""
    print("\n" + "="*60)
    print("🎧 测试4: 完整音频混合流程")
    print("="*60)
    
    def create_test_audio_bytes(duration_ms=1000):
        """创建测试音频并转换为bytes"""
        audio = AudioSegment.silent(duration=duration_ms)
        buf = io.BytesIO()
        audio.export(buf, format="mp3")
        return buf.getvalue()
    
    # 创建3个测试音频片段
    segments = [
        create_test_audio_bytes(1500),
        create_test_audio_bytes(2000),
        create_test_audio_bytes(1000)
    ]
    
    # 测试完整混合流程（启用所有优化）
    mixer_full = AudioMixer(
        enable_silence_trim=True,
        enable_loudness_norm=True,
        enable_semantic_pause=True,
        paragraph_pause_ms=1500,
        sentence_pause_ms=500,
        phrase_pause_ms=250,
        silence_duration=500
    )
    
    segment_types = ["paragraph", "sentence", "phrase"]
    
    result_full = mixer_full.mix_chapter(segments)
    print(f"  完整优化混合结果: {len(result_full)} bytes")
    
    # 测试无优化的混合流程
    mixer_basic = AudioMixer(
        enable_silence_trim=False,
        enable_loudness_norm=False,
        enable_semantic_pause=False,
        silence_duration=500
    )
    
    result_basic = mixer_basic.mix_chapter(segments)
    print(f"  基础混合结果: {len(result_basic)} bytes")
    
    # 验证结果
    assert len(result_full) > 0, "完整优化混合应该产生音频"
    assert len(result_basic) > 0, "基础混合应该产生音频"
    
    print("  ✅ 完整混合流程测试通过")


def run_all_tests():
    """运行所有测试"""
    print("="*60)
    print("🎯 开始运行音频优化功能测试")
    print("="*60)
    
    tests = [
        ("静音修剪", test_silence_trimming),
        ("响度标准化", test_loudness_normalization),
        ("语义停顿", test_semantic_pauses),
        ("完整混合流程", test_full_mixing_pipeline),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"  ❌ {name} 测试失败: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print(f"📊 测试总结: {passed} 通过, {failed} 失败")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
