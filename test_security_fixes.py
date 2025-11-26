"""
安全修复验证测试脚本

测试所有已修复的安全漏洞，确保跨用户访问被正确阻止。

运行方式:
    python test_security_fixes.py
"""
import requests
import json
from typing import Dict, Any

# 配置
API_BASE_URL = "http://localhost:8000"

class SecurityTester:
    def __init__(self):
        self.user_a_token = None
        self.user_b_token = None
        self.user_a_project_id = None
        self.user_b_project_id = None
        
    def register_and_login(self, username: str, password: str) -> str:
        """注册并登录用户，返回 token"""
        # 注册
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/v1/auth/register",
                json={"username": username, "password": password, "email": f"{username}@test.com"}
            )
            print(f"✅ 用户 {username} 注册成功" if response.status_code == 200 else f"⚠️  用户 {username} 可能已存在")
        except Exception as e:
            print(f"⚠️  注册失败: {e}")
        
        # 登录
        response = requests.post(
            f"{API_BASE_URL}/api/v1/auth/login",
            json={"username": username, "password": password}
        )
        
        if response.status_code == 200:
            token = response.json()["access_token"]
            print(f"✅ 用户 {username} 登录成功")
            return token
        else:
            raise Exception(f"登录失败: {response.text}")
    
    def create_project(self, token: str, project_name: str) -> int:
        """创建项目，返回 project_id"""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": project_name, "description": "测试项目"}
        )
        
        if response.status_code == 200:
            project_id = response.json()["id"]
            print(f"✅ 项目 '{project_name}' 创建成功 (ID: {project_id})")
            return project_id
        else:
            raise Exception(f"创建项目失败: {response.text}")
    
    def test_cross_user_project_access(self):
        """测试跨用户项目访问"""
        print("\n" + "="*60)
        print("🧪 测试 1: 跨用户项目访问")
        print("="*60)
        
        # 用户 B 尝试访问用户 A 的项目
        response = requests.get(
            f"{API_BASE_URL}/api/v1/projects/{self.user_a_project_id}",
            headers={"Authorization": f"Bearer {self.user_b_token}"}
        )
        
        if response.status_code == 404:
            print("✅ PASS: 用户 B 无法访问用户 A 的项目 (404)")
        else:
            print(f"❌ FAIL: 用户 B 可以访问用户 A 的项目 (状态码: {response.status_code})")
    
    def test_statistics_api_isolation(self):
        """测试统计 API 隔离"""
        print("\n" + "="*60)
        print("🧪 测试 2: 统计 API 项目隔离")
        print("="*60)
        
        # 用户 B 尝试查询用户 A 项目的统计数据
        response = requests.get(
            f"{API_BASE_URL}/workflow/stage-durations?project_id={self.user_a_project_id}",
            headers={"Authorization": f"Bearer {self.user_b_token}"}
        )
        
        if response.status_code == 404:
            print("✅ PASS: 用户 B 无法查询用户 A 项目的统计数据 (404)")
        else:
            print(f"❌ FAIL: 用户 B 可以查询用户 A 项目的统计数据 (状态码: {response.status_code})")
    
    def test_workflow_status_isolation(self):
        """测试工作流状态查询隔离"""
        print("\n" + "="*60)
        print("🧪 测试 3: 工作流状态查询隔离")
        print("="*60)
        
        # 用户 B 尝试查询用户 A 项目的工作流状态
        response = requests.get(
            f"{API_BASE_URL}/api/v1/workflow/status/{self.user_a_project_id}",
            headers={"Authorization": f"Bearer {self.user_b_token}"}
        )
        
        if response.status_code == 404:
            print("✅ PASS: 用户 B 无法查询用户 A 项目的工作流状态 (404)")
        else:
            print(f"❌ FAIL: 用户 B 可以查询用户 A 项目的工作流状态 (状态码: {response.status_code})")
    
    def test_vector_search_isolation(self):
        """测试向量搜索隔离"""
        print("\n" + "="*60)
        print("🧪 测试 4: 向量搜索项目隔离")
        print("="*60)
        
        # 用户 B 尝试搜索用户 A 项目的知识库
        response = requests.post(
            f"{API_BASE_URL}/api/v1/knowledge/search",
            headers={"Authorization": f"Bearer {self.user_b_token}"},
            json={"query": "测试", "project_id": self.user_a_project_id}
        )
        
        if response.status_code == 404:
            print("✅ PASS: 用户 B 无法搜索用户 A 项目的知识库 (404)")
        else:
            print(f"❌ FAIL: 用户 B 可以搜索用户 A 项目的知识库 (状态码: {response.status_code})")
    
    def test_knowledge_add_isolation(self):
        """测试知识库添加操作隔离"""
        print("\n" + "="*60)
        print("🧪 测试 5: 知识库添加操作隔离")
        print("="*60)
        
        # 用户 B 尝试向用户 A 的项目添加知识库
        response = requests.post(
            f"{API_BASE_URL}/api/v1/knowledge/world-setting",
            headers={"Authorization": f"Bearer {self.user_b_token}"},
            json={
                "title": "恶意添加",
                "content": "测试内容",
                "metadata": {"project_id": self.user_a_project_id}
            }
        )
        
        if response.status_code == 404:
            print("✅ PASS: 用户 B 无法向用户 A 项目添加知识库 (404)")
        else:
            print(f"❌ FAIL: 用户 B 可以向用户 A 项目添加知识库 (状态码: {response.status_code})")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "🔒 " + "="*58)
        print("🔒 安全修复验证测试")
        print("🔒 " + "="*58)
        
        # 准备测试环境
        print("\n📋 准备测试环境...")
        self.user_a_token = self.register_and_login("test_user_a", "password123")
        self.user_b_token = self.register_and_login("test_user_b", "password123")
        
        self.user_a_project_id = self.create_project(self.user_a_token, "用户A的项目")
        self.user_b_project_id = self.create_project(self.user_b_token, "用户B的项目")
        
        # 运行测试
        self.test_cross_user_project_access()
        self.test_statistics_api_isolation()
        self.test_workflow_status_isolation()
        self.test_vector_search_isolation()
        self.test_knowledge_add_isolation()
        
        # 总结
        print("\n" + "="*60)
        print("✅ 测试完成！")
        print("="*60)
        print("\n注意:")
        print("- 所有测试应该返回 404 (Not Found)")
        print("- 如果返回 200 或其他状态码，说明存在安全漏洞")
        print("- WebSocket 测试需要手动进行（使用浏览器开发者工具）")
        print("\n")

if __name__ == "__main__":
    tester = SecurityTester()
    try:
        tester.run_all_tests()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

