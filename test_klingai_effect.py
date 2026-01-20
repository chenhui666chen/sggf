"""
测试可灵AI音效生成功能
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载backend目录的.env文件
backend_env = Path(__file__).parent / "backend" / ".env"
if backend_env.exists():
    load_dotenv(backend_env)
    print(f"✅ 已加载环境变量: {backend_env}")

# 添加backend到路径
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.services.audiobook.klingai_effect_generator import KlingAIEffectGenerator


async def test_klingai_effect_generation():
    """测试可灵AI音效生成"""
    print("=" * 60)
    print("测试可灵AI音效生成")
    print("=" * 60)
    
    # 创建生成器（需要配置API密钥）
    access_key = os.getenv("KLINGAI_ACCESS_KEY")
    secret_key = os.getenv("KLINGAI_SECRET_KEY")
    
    generator = KlingAIEffectGenerator(
        access_key=access_key,
        secret_key=secret_key
    )
    
    if not generator.access_key or not generator.secret_key:
        print("❌ 未配置可灵AI API密钥(KLINGAI_ACCESS_KEY 或 KLINGAI_SECRET_KEY)")
        print("请在环境变量中设置 KLINGAI_ACCESS_KEY 和 KLINGAI_SECRET_KEY")
        return
    
    # 测试用例
    test_cases = [
        {
            "prompt": "大雨",
            "duration": 5.0,
            "description": "环境音 - 大雨"
        },
        {
            "prompt": "风声",
            "duration": 5.0,
            "description": "环境音 - 风声"
        },
        {
            "prompt": "脚步声",
            "duration": 3.0,
            "description": "动作音 - 脚步声"
        },
        {
            "prompt": "心跳声",
            "duration": 3.0,
            "description": "情绪音 - 心跳声"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}/{len(test_cases)}: {test_case['description']}")
        print(f"  Prompt: {test_case['prompt']}")
        print(f"  时长: {test_case['duration']}秒")
        
        try:
            result = await generator.generate_effect_async(
                prompt=test_case['prompt'],
                duration=test_case['duration'],
                max_wait=60
            )
            
            if result.success:
                print(f"  ✅ 生成成功!")
                print(f"     MP3 URL: {result.audio_url_mp3}")
                print(f"     WAV URL: {result.audio_url_wav}")
                print(f"     MP3 时长: {result.duration_mp3}秒")
                print(f"     WAV 时长: {result.duration_wav}秒")
                print(f"     任务ID: {result.task_id}")
            else:
                print(f"  ❌ 生成失败: {result.error}")
        except Exception as e:
            print(f"  ❌ 异常: {e}")
        
        # 添加延迟避免频率限制
        if i < len(test_cases):
            print(f"  ⏳ 等待3秒...")
            await asyncio.sleep(3)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


def test_klingai_sync():
    """测试可灵AI同步生成"""
    print("\n" + "=" * 60)
    print("测试可灵AI同步音效生成")
    print("=" * 60)
    
    access_key = os.getenv("KLINGAI_ACCESS_KEY")
    secret_key = os.getenv("KLINGAI_SECRET_KEY")
    
    generator = KlingAIEffectGenerator(
        access_key=access_key,
        secret_key=secret_key
    )
    
    if not generator.access_key or not generator.secret_key:
        print("❌ 未配置可灵AI API密钥(KLINGAI_ACCESS_KEY 或 KLINGAI_SECRET_KEY)")
        return
    
    # 测试创建任务
    print("\n1. 测试创建任务...")
    task_info = generator.create_task(
        prompt="大雨",
        duration=5.0,
        external_task_id="test_001"
    )
    
    if task_info:
        print(f"  ✅ 任务创建成功")
        print(f"     任务ID: {task_info.get('task_id')}")
        print(f"     状态: {task_info.get('task_status')}")
        
        # 测试查询任务
        print("\n2. 测试查询任务...")
        task_id = task_info.get('task_id')
        result = generator.query_task(task_id=task_id)
        
        if result:
            print(f"  ✅ 任务查询成功")
            print(f"     状态: {result.get('task_status')}")
            print(f"     更新时间: {result.get('updated_at')}")
            
            # 如果任务完成，获取音频URL
            if result.get('task_status') == 'succeed':
                task_result = result.get('task_result', {})
                audios = task_result.get('audios', [])
                if audios:
                    audio = audios[0]
                    print(f"     MP3 URL: {audio.get('url_mp3')}")
                    print(f"     WAV URL: {audio.get('url_wav')}")
    else:
        print("  ❌ 任务创建失败")
    
    print("\n" + "=" * 60)
    print("同步测试完成")
    print("=" * 60)


if __name__ == "__main__":
    # 运行异步测试
    asyncio.run(test_klingai_effect_generation())
    
    # 运行同步测试
    test_klingai_sync()
