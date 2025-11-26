"""
测试统计 API 修复
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_statistics_api():
    """测试统计 API 是否可以访问"""
    
    print("=" * 60)
    print("测试统计 API 修复")
    print("=" * 60)
    
    # 1. 先登录获取 token
    print("\n1. 登录获取 token...")
    login_response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    
    if login_response.status_code != 200:
        print(f"❌ 登录失败: {login_response.status_code}")
        print(login_response.text)
        return
    
    token = login_response.json()["access_token"]
    print(f"✅ 登录成功，token: {token[:20]}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. 测试统计 API
    print("\n2. 测试 GET /api/v1/statistics/workflow/stage-durations")
    
    # 2.1 全局平均耗时
    print("\n   2.1 全局平均耗时:")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations",
        headers=headers
    )
    
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ API 可以正常访问")
        data = response.json()
        print("   响应数据:")
        print(json.dumps(data, indent=4, ensure_ascii=False))
    else:
        print(f"   ❌ API 访问失败")
        print(f"   错误: {response.text}")
    
    # 2.2 自适应预估（最近3次任务）
    print("\n   2.2 自适应预估（最近3次任务）:")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations",
        headers=headers,
        params={"recent_count": 3}
    )
    
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ 自适应预估功能正常")
        data = response.json()
        print("   响应数据:")
        print(json.dumps(data, indent=4, ensure_ascii=False))
    else:
        print(f"   ❌ 自适应预估失败")
        print(f"   错误: {response.text}")
    
    # 2.3 指定项目
    print("\n   2.3 指定项目（project_id=1）:")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations",
        headers=headers,
        params={"project_id": 1}
    )
    
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ 项目过滤功能正常")
        data = response.json()
        print("   响应数据:")
        print(json.dumps(data, indent=4, ensure_ascii=False))
    else:
        print(f"   ❌ 项目过滤失败")
        print(f"   错误: {response.text}")
    
    # 3. 测试详细统计 API
    print("\n3. 测试 GET /api/v1/statistics/workflow/stage-durations/detailed")
    response = requests.get(
        f"{BASE_URL}/api/v1/statistics/workflow/stage-durations/detailed",
        headers=headers
    )
    
    print(f"   状态码: {response.status_code}")
    if response.status_code == 200:
        print("   ✅ 详细统计 API 正常")
        data = response.json()
        print("   响应数据:")
        print(json.dumps(data, indent=4, ensure_ascii=False))
    else:
        print(f"   ❌ 详细统计 API 失败")
        print(f"   错误: {response.text}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    try:
        test_statistics_api()
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

