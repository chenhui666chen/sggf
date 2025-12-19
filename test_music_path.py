"""测试音乐文件路径拼接逻辑"""
from pathlib import Path

# 模拟 engine.py 的路径计算（engine.py 在 backend/app/services/audiobook/ 下）
engine_file = Path(__file__).parent / "backend/app/services/audiobook/engine.py"
base_dir = engine_file.resolve().parents[3] / "data" / "audio_library"

# 模拟从 ai_music.py 返回的相对路径
file_ref = "music_cache/c79210d23558d5df38a65dc43db46c54.mp3"
music_path = base_dir / file_ref

print("=" * 70)
print("🎵 音乐文件路径测试")
print("=" * 70)
print(f"Engine 文件位置: {engine_file}")
print(f"Base dir (audio_library): {base_dir}")
print(f"相对路径 (从ai_music返回): {file_ref}")
print(f"拼接后的完整路径: {music_path}")
print(f"文件是否存在: {music_path.exists()}")

if music_path.exists():
    print(f"✅ 文件找到！大小: {music_path.stat().st_size / 1024 / 1024:.2f} MB")
else:
    print(f"❌ 文件不存在！")
    # 尝试其他可能的路径
    alt_path = Path(__file__).parent / "backend/backend/data/audio_library" / file_ref
    print(f"\n尝试备选路径: {alt_path}")
    print(f"备选路径是否存在: {alt_path.exists()}")
