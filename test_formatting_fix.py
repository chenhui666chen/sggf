"""
测试内容格式化修复
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_formatting():
    """测试内容格式化是否正确"""
    
    print("=" * 60)
    print("测试内容格式化修复")
    print("=" * 60)
    
    # 1. 登录
    print("\n1. 登录...")
    login_response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    
    if login_response.status_code != 200:
        print(f"❌ 登录失败: {login_response.status_code}")
        return
    
    token = login_response.json()["access_token"]
    print(f"✅ 登录成功")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. 获取项目列表
    print("\n2. 获取项目列表...")
    projects_response = requests.get(
        f"{BASE_URL}/api/v1/projects",
        headers=headers
    )
    
    if projects_response.status_code != 200:
        print(f"❌ 获取项目列表失败")
        return
    
    projects = projects_response.json()
    if not projects:
        print("⚠️  没有项目，请先创建项目并运行工作流")
        return
    
    project_id = projects[0]["id"]
    print(f"✅ 找到项目: ID={project_id}, 标题={projects[0]['title']}")
    
    # 3. 获取工作流状态
    print(f"\n3. 获取项目 {project_id} 的工作流状态...")
    workflow_response = requests.get(
        f"{BASE_URL}/api/v1/workflow/status/{project_id}",
        headers=headers
    )
    
    if workflow_response.status_code != 200:
        print(f"❌ 获取工作流状态失败")
        return
    
    workflow_data = workflow_response.json()
    print(f"✅ 工作流状态获取成功")
    
    # 4. 检查各阶段的输出格式
    print("\n4. 检查各阶段输出格式...")
    stages = workflow_data.get("stages", {})
    
    for stage_name, stage_content in stages.items():
        if stage_content:
            print(f"\n   阶段: {stage_name}")
            print(f"   内容长度: {len(stage_content)} 字符")
            
            # 检查是否包含转义的换行符
            if "\\n" in stage_content:
                print(f"   ⚠️  包含转义的换行符 \\n")
                print(f"   前100字符: {stage_content[:100]}")
            else:
                print(f"   ✅ 没有转义的换行符")
            
            # 检查是否包含 Markdown 格式
            has_markdown = any([
                "###" in stage_content,
                "**" in stage_content,
                "---" in stage_content
            ])
            
            if has_markdown:
                print(f"   ✅ 包含 Markdown 格式标记")
            else:
                print(f"   ℹ️  不包含 Markdown 格式标记")
    
    # 5. 测试单个阶段内容获取
    print("\n5. 测试单个阶段内容获取...")
    for stage in ["concept", "structure", "content", "review", "iteration"]:
        response = requests.get(
            f"{BASE_URL}/api/v1/workflow/stage-content/{project_id}/{stage}",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            content = data.get("content", "")
            
            if content:
                print(f"\n   阶段: {stage}")
                print(f"   内容长度: {len(content)} 字符")
                
                if "\\n" in content:
                    print(f"   ⚠️  包含转义的换行符 \\n")
                    print(f"   前100字符: {content[:100]}")
                else:
                    print(f"   ✅ 没有转义的换行符")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("\n提示：")
    print("- 如果看到 '⚠️ 包含转义的换行符'，说明后端返回的数据有问题")
    print("- 如果看到 '✅ 没有转义的换行符'，说明后端修复成功")
    print("- 前端的 formatContent.ts 已经添加了处理 \\n 的逻辑作为备用")

if __name__ == "__main__":
    try:
        test_formatting()
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

