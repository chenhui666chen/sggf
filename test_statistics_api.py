"""
测试统计 API
"""
import requests
import json

# 配置
BASE_URL = "http://localhost:8000"
USERNAME = "test"
PASSWORD = "test123"

def get_token():
    """获取访问令牌"""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={
            "username": USERNAME,
            "password": PASSWORD
        }
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"登录失败: {response.status_code}")
        print(response.text)
        return None

def test_stage_durations(token):
    """测试获取阶段耗时"""
    headers = {"Authorization": f"Bearer {token}"}

    print("\n=== 测试 GET /api/v1/statistics/workflow/stage-durations ===")
    print("1. 全局平均耗时:")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations",
        headers=headers
    )

    print(f"状态码: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("响应数据:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"错误: {response.text}")

    print("\n2. 自适应预估（最近3次任务）:")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations",
        headers=headers,
        params={"recent_count": 3}
    )

    print(f"状态码: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("响应数据:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"错误: {response.text}")

def test_detailed_stage_durations(token):
    """测试获取详细阶段统计"""
    headers = {"Authorization": f"Bearer {token}"}
    
    print("\n=== 测试 GET /api/v1/statistics/workflow/stage-durations/detailed ===")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations/detailed",
        headers=headers
    )
    
    print(f"状态码: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("响应数据:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"错误: {response.text}")

if __name__ == "__main__":
    print("🔧 开始测试统计 API...")
    
    # 获取令牌
    token = get_token()
    if not token:
        print("❌ 无法获取访问令牌，测试终止")
        exit(1)
    
    print(f"✅ 成功获取访问令牌: {token[:20]}...")
    
    # 测试 API
    test_stage_durations(token)
    test_detailed_stage_durations(token)
    
    print("\n✅ 测试完成")

