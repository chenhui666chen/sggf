""" 
测试RAG增强搜索API
"""
import requests
import json

# 配置
BASE_URL = "http://localhost:8000"
TOKEN = None  # 将在登录后填充

def login():
    """登录获取token"""
    global TOKEN
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "test", "password": "test123"}
    )
    if response.status_code == 200:
        TOKEN = response.json().get("access_token")
        print(f"✅ 登录成功")
        return True
    else:
        print(f"❌ 登录失败: {response.text}")
        return False

def test_enhanced_search():
    print("=" * 60)
    print("测试 RAG 增强搜索 API")
    print("=" * 60)
    
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    # 测试1: 增强搜索API
    print("\n【测试1】增强搜索 /search-enhanced ...")
    response = requests.post(
        f"{BASE_URL}/api/v1/knowledge/search-enhanced",
        headers=headers,
        json={
            "query": "修炼",
            "project_id": 3,
            "k": 5,
            "filter_types": ["chapter"],
            "min_score": 0.0
        }
    )
    if response.status_code == 200:
        data = response.json()
        print(f"  ✅ 状态: {data.get('status')}")
        print(f"  ✅ 结果数: {data.get('count')}")
        if data.get('results'):
            r = data['results'][0]
            print(f"  ✅ 第一个结果分数: {r.get('score')}")
    else:
        print(f"  ❌ 失败: {response.status_code} - {response.text[:200]}")
    
    # 测试2: 人物搜索API
    print("\n【测试2】人物搜索 /search-by-characters ...")
    response = requests.post(
        f"{BASE_URL}/api/v1/knowledge/search-by-characters",
        headers=headers,
        params={
            "project_id": 3,
            "character_names": json.dumps(["李铁柱"]),
            "k": 5
        }
    )
    if response.status_code == 200:
        data = response.json()
        print(f"  ✅ 状态: {data.get('status')}")
        print(f"  ✅ 结果数: {data.get('count')}")
    else:
        print(f"  ❌ 失败: {response.status_code} - {response.text[:200]}")
    
    # 测试3: 最近章节搜索API
    print("\n【测试3】最近章节搜索 /search-recent-chapters ...")
    response = requests.post(
        f"{BASE_URL}/api/v1/knowledge/search-recent-chapters",
        headers=headers,
        params={
            "project_id": 3,
            "query": "主角",
            "last_n_chapters": 5,
            "k": 5
        }
    )
    if response.status_code == 200:
        data = response.json()
        print(f"  ✅ 状态: {data.get('status')}")
        print(f"  ✅ 结果数: {data.get('count')}")
    else:
        print(f"  ❌ 失败: {response.status_code} - {response.text[:200]}")
    
    print("\n" + "=" * 60)
    print("✅ API测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    if login():
        test_enhanced_search()
