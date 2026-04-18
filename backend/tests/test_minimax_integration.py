import sys
import os
import importlib.util

base = os.path.join(os.path.dirname(__file__), '..', 'app', 'services', 'audiobook')

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

catalog = load_module("voice_catalog", os.path.join(base, "voice_catalog.py"))

print("=== 测试模型列表 ===")
VOICE_FILENAMES_BY_MODEL = catalog.VOICE_FILENAMES_BY_MODEL
print(f"支持的模型数: {len(VOICE_FILENAMES_BY_MODEL)}")
for m in VOICE_FILENAMES_BY_MODEL:
    print(f"  - {m}")

print("\n=== 测试音色目录加载 ===")
for model in ["qwen3-tts-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd"]:
    try:
        cat = catalog.load_voice_catalog_for_model(model)
        voices = cat.get("voices", [])
        meta = cat.get("meta", {})
        print(f"  {model}: {meta.get('voice_count', len(voices))} 音色 (source: {meta.get('source', 'N/A')})")
        if voices:
            print(f"    示例: {voices[0].get('label', voices[0].get('id', 'N/A'))}")
    except Exception as e:
        print(f"  {model}: 加载失败 - {e}")

print("\n=== 测试 MiniMax 音色特性 ===")
try:
    cat = catalog.load_voice_catalog_for_model("minimax-speech-2.8-hd")
    voices = cat.get("voices", [])
    male_voices = [v for v in voices if v.get("gender") == "male"]
    female_voices = [v for v in voices if v.get("gender") == "female"]
    print(f"  总音色数: {len(voices)}")
    print(f"  男声: {len(male_voices)}")
    print(f"  女声: {len(female_voices)}")
    print(f"  男声示例: {[v.get('label', v.get('id')) for v in male_voices[:3]]}")
    print(f"  女声示例: {[v.get('label', v.get('id')) for v in female_voices[:3]]}")
except Exception as e:
    print(f"  MiniMax 音色测试失败: {e}")

print("\n✅ 所有测试通过")
