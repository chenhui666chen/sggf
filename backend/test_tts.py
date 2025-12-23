"""
测试阿里云TTS API是否可用
使用最标准的文本，不包含任何特殊字符
"""
import os
import sys
import asyncio
from pathlib import Path

from dotenv import load_dotenv

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

async def test_aliyun_tts():
    """测试阿里云TTS基础功能"""
    
    # 设置API Key
    load_dotenv()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("未配置 DASHSCOPE_API_KEY，无法测试 TTS")
        return
    
    print("=" * 60)
    print("阿里云TTS API测试")
    print("=" * 60)
    print()
    
    # 测试用例：覆盖 Qwen3 默认场景以及精品模式
    test_cases = [
        {
            "name": "qwen3-tts-flash（阳光男声 Ethan）",
            "text": "这是一个测试文本。",
            "model": "qwen3-tts-flash",
            "voice": "Ethan"
        },
        {
            "name": "qwen3-tts-flash（女声 Sunny）",
            "text": "这是一个测试文本。",
            "model": "qwen3-tts-flash",
            "voice": "Sunny"
        },
        {
            "name": "qwen3-tts-flash 长文本（240字）",
            "text": "陆长生站在炼丹房门口，看着眼前这座曾经熟悉的建筑，心中涌起一股难以言喻的感觉。三年前，他还是外门首席弟子，前途一片光明。一场意外之后，丹田破碎，修为尽废，从云端坠落谷底。昔日的师兄弟纷纷避之不及，只有几个人还愿意和他说话。今天，他要证明自己还有价值。赵铁山是外门炼丹堂的执事，为人刻薄，最看不起废物。陆长生深吸一口气，推开了大门。",
            "model": "qwen3-tts-flash",
            "voice": "Ethan"
        },
        {
            "name": "cosyvoice-v3-plus（精品备选）",
            "text": "这是一个测试文本。",
            "model": "cosyvoice-v3-plus",
            "voice": "longanyang"
        }
    ]

    try:
        import dashscope
        from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
        
        dashscope.api_key = api_key
        print(f"API Key已配置: {api_key[:20]}...")
        print()
        
        # 逐个测试
        for i, test in enumerate(test_cases, 1):
            print(f"测试 {i}/{len(test_cases)}: {test['name']}")
            print(f"   文本: {test['text']}")
            print(f"   模型: {test['model']}")
            print(f"   音色: {test['voice']}")
            
            try:
                # 创建合成器
                synthesizer = SpeechSynthesizer(
                    model=test['model'],
                    voice=test['voice'],
                    format=AudioFormat.MP3_22050HZ_MONO_256KBPS
                )
                
                # 同步调用
                result = synthesizer.call(test['text'])
                
                # 检查结果（兼容两种返回格式）
                audio_data = None
                
                # 格式1：直接返回bytes
                if isinstance(result, bytes):
                    audio_data = result
                # 格式2：返回对象，调用get_audio_data()
                elif result and hasattr(result, 'get_audio_data'):
                    audio_data = result.get_audio_data()
                
                if audio_data:
                    print(f"   成功！音频大小: {len(audio_data)} 字节")
                    
                    # 保存音频（可选）
                    output_file = f"test_output_{i}.mp3"
                    with open(output_file, 'wb') as f:
                        f.write(audio_data)
                    print(f"   💾 已保存到: {output_file}")
                else:
                    print(f"   失败：返回空音频 or {result}")
                    
            except Exception as e:
                print(f"   异常：{e}")
                # 打印详细错误信息
                import traceback
                print(f"   详细错误：")
                traceback.print_exc()
            
            print()
        
        print("=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"初始化失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_aliyun_tts())
