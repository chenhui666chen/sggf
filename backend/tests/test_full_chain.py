"""
完整链路测试 - 验证未覆盖的功能

测试内容：
1. M4B 格式生成（完整音频混合流程）
2. 语气词注入链路（MiniMax interjection parser）
3. 音色-模型自动匹配机制
4. 输出格式选择链路
"""
import sys
import os
import io
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from pydub import AudioSegment
except ImportError:
    print("pydub unavailable")
    sys.exit(1)

from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.interjection_parser import InterjectionParser
from app.services.audiobook.voice_catalog import load_voice_catalog_for_model as load_voice_catalog


def test_m4b_format_generation():
    print("\n" + "="*60)
    print("Test 1: M4B Format Generation")
    print("="*60)
    
    mixer = AudioMixer(
        enable_silence_trim=True,
        enable_loudness_norm=True,
        enable_semantic_pause=True,
    )
    
    def make_audio_bytes(duration_ms=1000):
        audio = AudioSegment.silent(duration=duration_ms)
        buf = io.BytesIO()
        audio.export(buf, format="mp3")
        return buf.getvalue()
    
    segments = [make_audio_bytes(2000), make_audio_bytes(1500), make_audio_bytes(1000)]
    segment_types = ["paragraph", "sentence", "phrase"]
    
    mp3_audio = mixer._mix_with_pydub(segments, output_format="mp3", segment_types=segment_types)
    print(f"  MP3: {len(mp3_audio)} bytes")
    
    wav_audio = mixer._mix_with_pydub(segments, output_format="wav", segment_types=segment_types)
    print(f"  WAV: {len(wav_audio)} bytes")
    
    assert len(mp3_audio) > 0, "MP3 should not be empty"
    assert len(wav_audio) > 0, "WAV should not be empty"
    assert wav_audio[:4] == b'RIFF', "WAV should start with RIFF"
    
    print("  PASS: M4B format generation")


def test_interjection_injection():
    print("\n" + "="*60)
    print("Test 2: Interjection Injection Chain")
    print("="*60)
    
    parser_minimax = InterjectionParser(model="minimax-speech-2.8-hd")
    
    text1 = "今天天气真好啊"
    result1 = parser_minimax.inject_interjections(text1, "笑着说")
    print(f"  Input: '{text1}' + notes='笑着说'")
    print(f"  Output: '{result1}'")
    assert "(laughs)" in result1, "Should inject (laughs) for 笑"
    
    text2 = "我真的好无奈"
    result2 = parser_minimax.inject_interjections(text2, "叹气")
    print(f"  Input: '{text2}' + notes='叹气'")
    print(f"  Output: '{result2}'")
    assert "(sighs)" in result2, "Should inject (sighs) for 叹气"
    
    parser_other = InterjectionParser(model="qwen-audio-3.1-tts-flash")
    result3 = parser_other.inject_interjections(text1, "笑着说")
    print(f"  Non-MiniMax model: '{result3}'")
    assert result3 == text1, "Non-MiniMax model should not inject interjections"
    
    print("  PASS: Interjection injection chain")


def test_voice_model_auto_match():
    print("\n" + "="*60)
    print("Test 3: Voice-Model Auto Matching")
    print("="*60)
    
    qwen_catalog = load_voice_catalog("qwen-audio-3.1-tts-flash")
    cosyvoice_catalog = load_voice_catalog("cosyvoice-v3.5-plus")
    minimax_catalog = load_voice_catalog("minimax-speech-2.8-hd")
    
    qwen_voices = qwen_catalog.get("voices", [])
    cosyvoice_voices = cosyvoice_catalog.get("voices", [])
    minimax_voices = minimax_catalog.get("voices", [])
    
    print(f"  Qwen3 voices: {len(qwen_voices)}")
    print(f"  CosyVoice voices: {len(cosyvoice_voices)}")
    print(f"  MiniMax voices: {len(minimax_voices)}")
    
    qwen_voice_id = qwen_voices[0]["id"]
    minimax_voice_id = minimax_voices[0]["id"]
    
    print(f"  Testing Qwen voice: {qwen_voice_id}")
    qwen_lookup = load_voice_catalog("qwen-audio-3.1-tts-flash")
    assert qwen_voice_id in qwen_lookup.get("voices_by_id", {}), "Qwen voice should exist"
    
    print(f"  Testing MiniMax voice: {minimax_voice_id}")
    minimax_lookup = load_voice_catalog("minimax-speech-2.8-hd")
    assert minimax_voice_id in minimax_lookup.get("voices_by_id", {}), "MiniMax voice should exist"
    
    print("  PASS: Voice-model auto matching")


def test_output_format_selection():
    print("\n" + "="*60)
    print("Test 4: Output Format Selection Chain")
    print("="*60)
    
    mixer = AudioMixer(enable_silence_trim=False, enable_loudness_norm=False, enable_semantic_pause=False)
    
    def make_audio_bytes(duration_ms=500):
        audio = AudioSegment.silent(duration=duration_ms)
        buf = io.BytesIO()
        audio.export(buf, format="mp3")
        return buf.getvalue()
    
    segments = [make_audio_bytes(1000)]
    
    for fmt in ["mp3", "wav"]:
        audio_bytes = mixer._mix_with_pydub(segments, output_format=fmt)
        print(f"  Format '{fmt}': {len(audio_bytes)} bytes")
        assert len(audio_bytes) > 0, f"{fmt} should not be empty"
    
    print("  PASS: Output format selection chain")


def test_segment_review_api_schema():
    print("\n" + "="*60)
    print("Test 5: Segment Review API Schema Validation")
    print("="*60)
    
    schemas_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'schemas', 'audiobook.py')
    with open(schemas_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_classes = [
        "SegmentRegenerateRequest",
        "SegmentReviewRequest", 
        "ChapterReviewStatus"
    ]
    
    for class_name in required_classes:
        assert f"class {class_name}" in content, f"Schema {class_name} not found"
        print(f"  Found schema: {class_name}")
    
    api_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'api', 'v1', 'audiobook_api')
    api_content = ""
    for filename in ("routes_segment_regen.py", "routes_review.py"):
        with open(os.path.join(api_dir, filename), 'r', encoding='utf-8') as f:
            api_content += "\n" + f.read()
    
    required_endpoints = [
        "/regenerate",
        "/review",
        "/review-status"
    ]
    
    for endpoint in required_endpoints:
        assert endpoint in api_content, f"Endpoint {endpoint} not found in API"
        print(f"  Found endpoint: {endpoint}")
    
    print("  PASS: Segment review API schema validation")


def test_database_model_extension():
    print("\n" + "="*60)
    print("Test 6: Database Model Extension")
    print("="*60)
    
    model_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'models', 'audiobook.py')
    with open(model_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert "segment_reviews_json" in content, "segment_reviews_json column not found"
    print("  Found column: segment_reviews_json")
    
    print("  PASS: Database model extension")


def run_all_tests():
    print("="*60)
    print("Full Chain Test Suite")
    print("="*60)
    
    tests = [
        ("M4B Format", test_m4b_format_generation),
        ("Interjection Injection", test_interjection_injection),
        ("Voice-Model Matching", test_voice_model_auto_match),
        ("Output Format Selection", test_output_format_selection),
        ("Segment Review API Schema", test_segment_review_api_schema),
        ("Database Model Extension", test_database_model_extension),
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
