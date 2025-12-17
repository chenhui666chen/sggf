"""
阿里云TTS诊断脚本
用于排查418错误和配额问题
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def check_api_key():
    """检查API Key配置"""
    print("=" * 60)
    print("1️⃣  检查API Key配置")
    print("=" * 60)
    
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 未找到 DASHSCOPE_API_KEY")
        return False
    
    print(f"✅ API Key已配置: {api_key[:20]}...")
    return True

def test_basic_connection():
    """测试基本连接"""
    print("\n" + "=" * 60)
    print("2️⃣  测试阿里云DashScope基本连接")
    print("=" * 60)
    
    try:
        import dashscope
        dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
        
        # 尝试调用文本生成（最基础的服务）
        from dashscope import Generation
        
        response = Generation.call(
            model='qwen-turbo',
            prompt='你好'
        )
        
        if response.status_code == 200:
            print("✅ DashScope基本连接成功")
            return True
        else:
            print(f"❌ DashScope连接失败: {response.code} - {response.message}")
            return False
            
    except Exception as e:
        print(f"❌ DashScope连接异常: {e}")
        return False

def test_tts_models():
    """测试所有可用的TTS模型"""
    print("\n" + "=" * 60)
    print("3️⃣  测试TTS模型（依次尝试所有模型）")
    print("=" * 60)
    
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
    
    dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
    
    # 测试文本（简短且标准）
    test_text = "你好，这是测试。"
    
    # 所有可能的模型配置
    models_to_test = [
        {"model": "cosyvoice-v1", "voice": "longxiaochun", "name": "CosyVoice v1 (基础版)"},
        {"model": "sambert-zhichu-v1", "voice": "zhichu", "name": "Sambert知楚 v1"},
        {"model": "sambert-zhiru-v1", "voice": "zhiru", "name": "Sambert知如 v1"},
        {"model": "sambert-zhitian-v1", "voice": "zhitian", "name": "Sambert知甜 v1"},
    ]
    
    success_models = []
    failed_models = []
    
    for config in models_to_test:
        model_name = config["model"]
        voice_name = config["voice"]
        display_name = config["name"]
        
        print(f"\n📝 测试: {display_name}")
        print(f"   模型: {model_name}, 音色: {voice_name}")
        
        try:
            synthesizer = SpeechSynthesizer(
                model=model_name,
                voice=voice_name,
                format=AudioFormat.MP3_22050HZ_MONO_256KBPS
            )
            
            result = synthesizer.call(test_text)
            
            # 检查结果
            if isinstance(result, bytes) and len(result) > 0:
                print(f"   ✅ 成功！音频大小: {len(result)} 字节")
                success_models.append(display_name)
            elif result and hasattr(result, 'get_audio_data'):
                audio_data = result.get_audio_data()
                if audio_data and len(audio_data) > 0:
                    print(f"   ✅ 成功！音频大小: {len(audio_data)} 字节")
                    success_models.append(display_name)
                else:
                    print(f"   ❌ 失败：返回空音频")
                    failed_models.append(f"{display_name} (空音频)")
            else:
                print(f"   ❌ 失败：返回 {type(result)}")
                failed_models.append(f"{display_name} (异常返回)")
                
        except Exception as e:
            error_msg = str(e)
            
            # 分析错误类型
            if "418" in error_msg:
                print(f"   ❌ 418错误（配额/权限问题）")
                failed_models.append(f"{display_name} (418配额)")
            elif "Throttling" in error_msg:
                print(f"   ❌ 频率限制错误")
                failed_models.append(f"{display_name} (限流)")
            elif "Forbidden" in error_msg or "Access" in error_msg:
                print(f"   ❌ 权限错误（服务未开通）")
                failed_models.append(f"{display_name} (未开通)")
            else:
                print(f"   ❌ 其他错误: {error_msg[:100]}")
                failed_models.append(f"{display_name} (未知错误)")
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    if success_models:
        print(f"\n✅ 可用模型 ({len(success_models)}个):")
        for model in success_models:
            print(f"   • {model}")
    else:
        print("\n❌ 没有可用的模型！")
    
    if failed_models:
        print(f"\n❌ 不可用模型 ({len(failed_models)}个):")
        for model in failed_models:
            print(f"   • {model}")
    
    return len(success_models) > 0

def check_account_status():
    """检查账户状态建议"""
    print("\n" + "=" * 60)
    print("4️⃣  账户诊断建议")
    print("=" * 60)
    
    print("""
如果所有模型都失败（418错误），可能原因：

1️⃣  **服务未开通**
   👉 访问: https://dashscope.console.aliyun.com/
   👉 开通 "语音合成" 服务

2️⃣  **免费配额用尽**
   👉 查看配额: https://dashscope.console.aliyun.com/billing
   👉 考虑充值或升级套餐

3️⃣  **API Key权限不足**
   👉 检查API Key是否有TTS调用权限
   👉 可能需要重新生成API Key

4️⃣  **账户欠费**
   👉 检查阿里云账户余额
   👉 充值后等待生效

🔍 推荐操作：
   1. 先登录阿里云控制台检查服务开通状态
   2. 查看计费和配额使用情况
   3. 如需帮助，可联系阿里云技术支持
    """)

def main():
    """主诊断流程"""
    print("\n🔍 阿里云TTS诊断工具")
    print("用于排查418错误和配额问题\n")
    
    # 检查1: API Key
    if not check_api_key():
        print("\n⚠️ 请先配置 DASHSCOPE_API_KEY 环境变量")
        return
    
    # 检查2: 基本连接
    if not test_basic_connection():
        print("\n⚠️ DashScope基本服务连接失败，请检查网络和API Key")
        # 继续测试TTS（可能只是文本生成服务的问题）
    
    # 检查3: 测试所有TTS模型
    has_working_model = test_tts_models()
    
    # 检查4: 给出建议
    if not has_working_model:
        check_account_status()
    else:
        print("\n✅ 诊断完成！至少有一个模型可用")
        print("💡 建议使用测试成功的模型进行语音合成")

if __name__ == "__main__":
    main()
