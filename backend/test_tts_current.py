"""
测试当前TTS配置是否正常工作
模拟实际有声书生成场景
"""
import asyncio
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def test_current_tts():
    """测试当前TTS引擎配置"""
    print("=" * 60)
    print("🧪 测试当前TTS引擎配置")
    print("=" * 60)
    
    # 导入TTS引擎
    from app.services.audiobook.tts_engine import TTSEngine
    
    # 创建TTS引擎实例（使用当前配置）
    tts_engine = TTSEngine(
        provider="aliyun",
        enable_cache=False,  # 禁用缓存，确保真实调用
        max_concurrent=1
    )
    
    print(f"\n✅ TTS引擎配置:")
    print(f"   Provider: {tts_engine.provider}")
    print(f"   并发数: {tts_engine.max_concurrent}")
    print(f"   请求间隔: {tts_engine.request_delay}秒")
    
    # 测试文本（模拟实际场景的多个片段）
    test_texts = [
        "在月光下，古老的城堡静静伫立。",
        "她轻轻推开了那扇尘封已久的门。",
        "突然，远处传来了一阵神秘的歌声。"
    ]
    
    # 音色配置（使用默认配置）
    voice_params = {
        "speaker": "longxiaochun",  # cosyvoice-v1支持的音色
        "pitch": 0,
        "speed": 1.0
    }
    
    print(f"\n📝 测试文本数量: {len(test_texts)}个")
    print(f"🎤 音色配置: {voice_params}")
    
    # 逐个测试
    success_count = 0
    fail_count = 0
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n{'=' * 60}")
        print(f"测试 {i}/{len(test_texts)}: {text}")
        print(f"{'=' * 60}")
        
        try:
            # 调用TTS
            audio_bytes = await tts_engine.synthesize(
                text=text,
                voice_params=voice_params,
                emotion="neutral"
            )
            
            if audio_bytes and len(audio_bytes) > 0:
                print(f"✅ 成功！音频大小: {len(audio_bytes)} 字节")
                success_count += 1
                
                # 保存到临时文件验证
                temp_file = f"test_audio_{i}.mp3"
                with open(temp_file, 'wb') as f:
                    f.write(audio_bytes)
                print(f"   已保存到: {temp_file}")
            else:
                print(f"❌ 失败：返回空音频")
                fail_count += 1
                
        except Exception as e:
            print(f"❌ 异常: {e}")
            fail_count += 1
        
        # 等待一下再测试下一个（模拟实际场景）
        if i < len(test_texts):
            print(f"\n⏳ 等待{tts_engine.request_delay}秒后继续...")
            await asyncio.sleep(tts_engine.request_delay)
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    print(f"✅ 成功: {success_count}/{len(test_texts)}")
    print(f"❌ 失败: {fail_count}/{len(test_texts)}")
    
    if success_count == len(test_texts):
        print("\n🎉 恭喜！所有测试通过，TTS系统工作正常！")
        print("💡 现在可以安心生成有声书了！")
    elif success_count > 0:
        print("\n⚠️ 部分成功，可能存在间歇性问题")
        print("💡 建议检查后端日志查看详细错误信息")
    else:
        print("\n❌ 全部失败，请检查:")
        print("   1. 阿里云账户余额是否充足")
        print("   2. cosyvoice-v1服务是否已开通")
        print("   3. API Key权限是否正确")
    
    return success_count == len(test_texts)

async def main():
    """主函数"""
    print("\n🚀 开始TTS系统测试...")
    print("⏰ 测试时间:", asyncio.get_event_loop().time())
    
    # 检查API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 未配置 DASHSCOPE_API_KEY")
        return
    
    print(f"🔑 API Key: {api_key[:20]}...")
    
    # 运行测试
    success = await test_current_tts()
    
    if success:
        print("\n✅ 测试完成！系统已就绪！")
    else:
        print("\n⚠️ 测试完成，但存在问题，请查看详细日志")

if __name__ == "__main__":
    asyncio.run(main())
