"""
可灵AI音效生成测试 - 使用提供的密钥
API文档: https://app.klingai.com/cn/dev/document-api/apiReference/model/textToAudio
"""

import asyncio
import httpx
import time
from jose import jwt

# 用户提供的密钥
ACCESS_KEY = "AFTBQy3LQgdRKhNNdKyhpLdEQRRJ3ENJ"
SECRET_KEY = "ytfdFdN8JRhPQHBgBNmCpgLPdTYnd93g"

# API配置
BASE_URL = "https://api.klingai.com/v1/audio/text-to-audio"

def generate_jwt_token():
    """生成JWT Token"""
    current_time = int(time.time())
    
    headers = {
        "alg": "HS256",
        "typ": "JWT"
    }
    
    payload = {
        "iss": ACCESS_KEY,
        "exp": current_time + 1800,  # 30分钟有效期
        "nbf": current_time - 5  # 5秒前生效
    }
    
    token = jwt.encode(payload, SECRET_KEY, headers=headers)
    return token

def get_headers():
    """获取请求头"""
    token = generate_jwt_token()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

async def create_task(prompt: str, duration: float = 5.0):
    """创建音效生成任务"""
    payload = {
        "prompt": prompt,
        "duration": duration,
        "external_task_id": f"test_{int(time.time())}"
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            BASE_URL,
            json=payload,
            headers=get_headers()
        )
        
        return response.json()

async def query_task(task_id: str):
    """查询任务状态"""
    url = f"{BASE_URL}/{task_id}"
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            url,
            headers=get_headers()
        )
        
        return response.json()

async def generate_effect(prompt: str, duration: float = 5.0, max_wait: int = 60):
    """生成音效（等待完成）"""
    print(f"\n{'='*60}")
    print(f"生成音效: {prompt}")
    print(f"时长: {duration}秒")
    print(f"{'='*60}")
    
    # 1. 创建任务
    print("\n[1/2] 创建任务...")
    create_result = await create_task(prompt, duration)
    
    print(f"响应: {create_result}")
    
    if create_result.get("code") != 0:
        error_msg = create_result.get("message", "未知错误")
        error_code = create_result.get("code")
        
        print(f"\n❌ 任务创建失败")
        print(f"   错误码: {error_code}")
        print(f"   错误信息: {error_msg}")
        
        # 错误码说明
        error_explanations = {
            1000: "身份验证失败 - 检查Authorization是否正确",
            1001: "Authorization为空 - 在RequestHeader中填写正确的Authorization",
            1002: "Authorization值非法 - 在RequestHeader中填写正确的Authorization",
            1003: "Authorization未到有效时间 - 检查token的开始生效时间",
            1004: "Authorization已失效 - 检查token的有效期",
            1100: "账户异常 - 检查账户配置信息",
            1101: "账户欠费（后付费场景）- 进行账户充值",
            1102: "资源包已用完/已过期（预付费场景）- 购买额外的资源包",
            1103: "请求的资源无权限 - 检查账户权限",
            1200: "请求参数非法 - 检查请求参数是否正确",
            1300: "触发平台策略 - 检查是否触发平台策略",
            1301: "触发平台的内容安全策略 - 检查输入内容",
            1302: "API请求过快 - 降低请求频率",
            1303: "并发或QPS超出限制 - 降低请求频率",
            1304: "触发平台的IP白名单策略 - 联系客服",
            5000: "服务器内部错误 - 稍后重试",
            5001: "服务器暂时不可用 - 稍后重试",
            5002: "服务器内部超时 - 稍后重试"
        }
        
        if error_code in error_explanations:
            print(f"\n💡 解决方案: {error_explanations[error_code]}")
        
        return None
    
    task_data = create_result.get("data", {})
    task_id = task_data.get("task_id")
    task_status = task_data.get("task_status")
    
    print(f"✅ 任务创建成功")
    print(f"   任务ID: {task_id}")
    print(f"   初始状态: {task_status}")
    
    # 2. 轮询任务状态
    print(f"\n[2/2] 等待任务完成...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        query_result = await query_task(task_id)
        
        if query_result.get("code") != 0:
            print(f"⚠️  查询失败: {query_result.get('message')}")
            await asyncio.sleep(2)
            continue
        
        task_data = query_result.get("data", {})
        current_status = task_data.get("task_status")
        
        print(f"   当前状态: {current_status}")
        
        if current_status == "succeed":
            task_result = task_data.get("task_result", {})
            audios = task_result.get("audios", [])
            
            if audios:
                audio = audios[0]
                print(f"\n✅ 音效生成成功!")
                print(f"   任务ID: {task_id}")
                print(f"   MP3 URL: {audio.get('url_mp3')}")
                print(f"   WAV URL: {audio.get('url_wav')}")
                print(f"   MP3 时长: {audio.get('duration_mp3')}秒")
                print(f"   WAV 时长: {audio.get('duration_wav')}秒")
                return {
                    "task_id": task_id,
                    "url_mp3": audio.get('url_mp3'),
                    "url_wav": audio.get('url_wav'),
                    "duration_mp3": audio.get('duration_mp3'),
                    "duration_wav": audio.get('duration_wav')
                }
        
        elif current_status == "failed":
            error_msg = task_data.get("task_status_msg", "未知错误")
            print(f"\n❌ 任务失败: {error_msg}")
            return None
        
        await asyncio.sleep(3)
    
    print(f"\n❌ 任务超时（等待{max_wait}秒）")
    return None

async def main():
    """主测试函数"""
    print("=" * 60)
    print("可灵AI音效生成测试")
    print("=" * 60)
    
    print(f"\nAPI配置:")
    print(f"  Access Key: {ACCESS_KEY[:10]}...{ACCESS_KEY[-5:]}")
    print(f"  Secret Key: {SECRET_KEY[:10]}...{SECRET_KEY[-5:]}")
    print(f"  API URL: {BASE_URL}")
    
    # 测试用例
    test_cases = [
        {"prompt": "狗叫声", "duration": 3.0},
        {"prompt": "敲门声", "duration": 3.0},
        {"prompt": "雷声", "duration": 5.0},
        {"prompt": "大雨", "duration": 5.0},
        {"prompt": "风声", "duration": 5.0}
    ]
    
    print(f"\n测试用例数量: {len(test_cases)}")
    print("开始测试...\n")
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"测试用例 {i}/{len(test_cases)}")
        print(f"{'='*60}")
        
        result = await generate_effect(
            prompt=test_case["prompt"],
            duration=test_case["duration"],
            max_wait=60
        )
        
        if result:
            results.append(result)
        
        # 添加延迟避免频率限制
        if i < len(test_cases):
            print(f"\n⏳ 等待5秒后继续下一个测试...")
            await asyncio.sleep(5)
    
    # 总结
    print(f"\n{'='*60}")
    print("测试总结")
    print(f"{'='*60}")
    print(f"总测试数: {len(test_cases)}")
    print(f"成功数: {len(results)}")
    print(f"失败数: {len(test_cases) - len(results)}")
    
    if results:
        print(f"\n✅ 成功生成的音效:")
        for i, result in enumerate(results, 1):
            print(f"  {i}. {result['url_mp3']}")
    
    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
