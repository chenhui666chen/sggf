"""
测试Instruct情感控制修复
验证使用Instruct时参数不会超出兼容范围
"""
import asyncio
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def test_instruct_emotion_fix():
    """测试Instruct情感修复"""
    print("=" * 70)
    print("🧪 测试Instruct情感控制修复（错误码428问题）")
    print("=" * 70)
    
    # 导入TTS引擎
    from app.services.audiobook.tts_engine import TTSEngine, TTSProvider
    
    # 创建TTS引擎实例
    tts_engine = TTSEngine(
        primary_provider=TTSProvider.ALIYUN,
        enable_cache=False,  # 禁用缓存，确保真实调用
        max_concurrent=1
    )
    
    print(f"\n✅ TTS引擎配置:")
    print(f"   Provider: {tts_engine.provider}")
    print(f"   Model: {tts_engine.model}")
    
    # 测试用例：之前会触发428错误的配置
    test_cases = [
        {
            "name": "excited情感 + longanyang音色",
            "text": "岁岁，今天我们要开始新的实验了。",
            "voice_params": {
                "speaker": "longanyang",
                "pitch": 58,
                "speed": 1.21,
                "volume": 55
            },
            "emotion": "excited",
            "description": "之前触发428错误的典型场景"
        },
        {
            "name": "angry情感 + longanyang音色",
            "text": "你竟敢背叛我！",
            "voice_params": {
                "speaker": "longanyang",
                "pitch": 60,
                "speed": 1.15,
                "volume": 60
            },
            "emotion": "angry",
            "description": "高音色参数 + 愤怒情感"
        },
        {
            "name": "happy情感 + longanhuan音色",
            "text": "今天真是个美好的日子！",
            "voice_params": {
                "speaker": "longanhuan",
                "pitch": 55,
                "speed": 1.10,
                "volume": 50
            },
            "emotion": "happy",
            "description": "测试另一个Instruct音色"
        },
        {
            "name": "neutral情感（不使用Instruct）",
            "text": "这是一段普通的叙述文本。",
            "voice_params": {
                "speaker": "longanyang",
                "pitch": 50,
                "speed": 1.0,
                "volume": 50
            },
            "emotion": "neutral",
            "description": "neutral情感不使用Instruct"
        }
    ]
    
    print(f"\n📝 测试用例数量: {len(test_cases)}个")
    
    # 执行测试
    success_count = 0
    fail_count = 0
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'=' * 70}")
        print(f"测试用例 {i}/{len(test_cases)}: {test_case['name']}")
        print(f"说明: {test_case['description']}")
        print(f"{'=' * 70}")
        print(f"📝 文本: {test_case['text']}")
        print(f"🎤 音色: {test_case['voice_params']['speaker']}")
        print(f"🎭 情感: {test_case['emotion']}")
        print(f"🎚️ 参数: pitch={test_case['voice_params']['pitch']}, "
              f"speed={test_case['voice_params']['speed']}, "
              f"volume={test_case['voice_params']['volume']}")
        
        try:
            # 调用TTS
            audio_bytes = await tts_engine.synthesize(
                text=test_case['text'],
                voice_params=test_case['voice_params'],
                emotion=test_case['emotion']
            )
            
            if audio_bytes and len(audio_bytes) > 0:
                print(f"✅ 成功！音频大小: {len(audio_bytes)} 字节")
                success_count += 1
                results.append({
                    "name": test_case['name'],
                    "status": "✅ 成功",
                    "size": len(audio_bytes)
                })
                
                # 保存测试音频
                filename = f"test_instruct_{i}_{test_case['emotion']}.mp3"
                with open(filename, 'wb') as f:
                    f.write(audio_bytes)
                print(f"💾 已保存到: {filename}")
            else:
                print(f"❌ 失败：返回空音频")
                fail_count += 1
                results.append({
                    "name": test_case['name'],
                    "status": "❌ 失败（空音频）",
                    "size": 0
                })
                
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 异常: {error_msg}")
            
            # 检查是否是428错误
            if "428" in error_msg:
                print(f"⚠️ 检测到428错误！修复可能未生效")
            
            fail_count += 1
            results.append({
                "name": test_case['name'],
                "status": f"❌ 失败（{error_msg[:50]}...）",
                "size": 0
            })
        
        # 等待一下再测试下一个
        if i < len(test_cases):
            await asyncio.sleep(2)
    
    # 汇总结果
    print("\n" + "=" * 70)
    print("📊 测试结果汇总")
    print("=" * 70)
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['name']}: {result['status']}")
        if result['size'] > 0:
            print(f"   音频大小: {result['size']} 字节")
    
    print(f"\n统计:")
    print(f"✅ 成功: {success_count}/{len(test_cases)}")
    print(f"❌ 失败: {fail_count}/{len(test_cases)}")
    
    if success_count == len(test_cases):
        print("\n🎉 恭喜！所有测试通过！")
        print("✅ Instruct情感修复成功，不再触发428错误！")
        print("✅ 参数控制正常，Instruct指令正确应用！")
    elif success_count > 0:
        print(f"\n⚠️ 部分成功 ({success_count}/{len(test_cases)})")
        print("💡 请检查失败的用例，可能需要进一步调整")
    else:
        print("\n❌ 全部失败")
        print("💡 请检查:")
        print("   1. 修复代码是否正确应用（重启后端服务）")
        print("   2. 阿里云API配置是否正确")
        print("   3. 后端日志中的详细错误信息")
    
    return success_count == len(test_cases)

async def main():
    """主函数"""
    print("\n🚀 开始Instruct情感修复测试...")
    
    # 检查API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 未配置 DASHSCOPE_API_KEY")
        return
    
    print(f"🔑 API Key: {api_key[:20]}...")
    
    # 运行测试
    success = await test_instruct_emotion_fix()
    
    if success:
        print("\n✅ 测试完成！修复验证通过！")
    else:
        print("\n⚠️ 测试完成，但存在问题，请查看详细日志")

if __name__ == "__main__":
    asyncio.run(main())
