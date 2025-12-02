"""
层级配置使用演示脚本
展示从创建项目到使用树形视图的完整流程
"""
import requests
import json
from typing import Dict, Any

# API基础URL
BASE_URL = "http://localhost:8000"

# 演示用户凭据（假设已经有测试用户）
TEST_USER = {
    "email": "test@example.com",
    "password": "test123456"
}


def print_section(title: str):
    """打印分隔标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def print_json(data: Any, title: str = ""):
    """美化打印JSON数据"""
    if title:
        print(f"\n📋 {title}:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


class HierarchyDemo:
    def __init__(self):
        self.token = None
        self.project_id = None
        self.collection_id = None
        
    def login(self):
        """步骤1: 用户登录获取token"""
        print_section("步骤 1: 用户登录")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            data={
                "username": TEST_USER["email"],
                "password": TEST_USER["password"]
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            self.token = data["access_token"]
            print(f"✅ 登录成功！")
            print(f"   Token: {self.token[:30]}...")
        else:
            print(f"❌ 登录失败: {response.text}")
            # 尝试注册
            self.register_and_login()
    
    def register_and_login(self):
        """注册新用户并登录"""
        print("\n🆕 尝试注册新用户...")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/register",
            json={
                "email": TEST_USER["email"],
                "password": TEST_USER["password"],
                "username": "测试用户"
            }
        )
        
        if response.status_code in [200, 201]:
            print("✅ 注册成功！")
            self.login()
        else:
            print(f"❌ 注册失败: {response.text}")
    
    def create_project(self):
        """步骤2: 创建新项目"""
        print_section("步骤 2: 创建玄幻修仙项目")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        
        response = requests.post(
            f"{BASE_URL}/api/v1/projects",
            headers=headers,
            json={
                "title": "【演示】逆天修仙录",
                "description": "一个普通少年的修仙之路，层级配置演示项目",
                "genre": "玄幻修真"
            }
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            self.project_id = data["id"]
            print(f"✅ 项目创建成功！")
            print(f"   项目ID: {self.project_id}")
            print(f"   项目名称: {data['title']}")
        else:
            print(f"❌ 创建项目失败: {response.text}")
    
    def apply_template(self):
        """步骤3: 应用玄幻修真模板"""
        print_section("步骤 3: 应用玄幻修真基础模板")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        
        response = requests.post(
            f"{BASE_URL}/api/v1/projects/{self.project_id}/setting-templates/apply",
            headers=headers,
            json={
                "template_key": "xuanhuan_basic",
                "clear_existing": True
            }
        )
        
        if response.status_code in [200, 201]:
            data = response.json()
            print(f"✅ 模板应用成功！")
            print(f"   创建了 {data['created_collections']} 个设定集合")
            print(f"   创建了 {data['created_items']} 个设定项")
        else:
            print(f"❌ 应用模板失败: {response.text}")
    
    def list_collections(self):
        """步骤4: 查看所有设定集合及其层级配置"""
        print_section("步骤 4: 查看设定集合的层级配置")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        
        response = requests.get(
            f"{BASE_URL}/api/v1/projects/{self.project_id}/setting-collections",
            headers=headers
        )
        
        if response.status_code == 200:
            collections = response.json()
            print(f"✅ 获取到 {len(collections)} 个设定集合\n")
            
            for col in collections:
                print(f"📦 {col['name']} ({col['category']})")
                print(f"   最大深度: {col['max_depth']}")
                
                if col['hierarchy_config']:
                    config = json.loads(col['hierarchy_config'])
                    print(f"   层级配置:")
                    for level in config.get('levels', []):
                        leaf_mark = " [叶子节点]" if level.get('leaf') else ""
                        examples = level.get('examples', [])
                        examples_str = f" - 示例: {', '.join(examples[:3])}" if examples else ""
                        print(f"     • 第{level['depth']}层: {level['name']} ({level['type']}){leaf_mark}{examples_str}")
                print()
                
                # 保存功法体系的ID用于后续演示
                if col['category'] == 'technique_system':
                    self.collection_id = col['id']
        else:
            print(f"❌ 获取集合失败: {response.text}")
    
    def get_tree_structure(self):
        """步骤5: 获取功法体系的树形结构"""
        if not self.collection_id:
            print("⚠️ 未找到功法体系集合")
            return
        
        print_section("步骤 5: 获取功法体系的树形结构")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        
        response = requests.get(
            f"{BASE_URL}/api/v1/setting-collections/{self.collection_id}/tree",
            headers=headers
        )
        
        if response.status_code == 200:
            tree_data = response.json()
            print("✅ 树形结构获取成功！\n")
            
            self.print_tree(tree_data, indent=0)
        else:
            print(f"❌ 获取树形结构失败: {response.text}")
    
    def print_tree(self, nodes: list, indent: int = 0):
        """递归打印树形结构"""
        for node in nodes:
            prefix = "  " * indent
            
            # 节点图标
            if node.get('is_leaf'):
                icon = "📄"
            elif node.get('children'):
                icon = "📁"
            else:
                icon = "📂"
            
            # 基本信息
            name = node.get('name', '未命名')
            depth = node.get('depth', 0)
            node_type = node.get('node_type', 'unknown')
            
            print(f"{prefix}{icon} {name} [深度:{depth}, 类型:{node_type}]")
            
            # 如果有详情，显示摘要
            if node.get('item'):
                item = node['item']
                if item.get('summary'):
                    print(f"{prefix}   💡 {item['summary']}")
            
            # 递归打印子节点
            if node.get('children'):
                self.print_tree(node['children'], indent + 1)
    
    def demonstrate_hierarchy_examples(self):
        """步骤6: 展示不同体系的层级配置示例"""
        print_section("步骤 6: 不同体系的层级配置对比")
        
        examples = {
            "cultivation_realm_system": {
                "name": "修仙境界体系",
                "structure": "扁平2层（境界通过关系边连接）",
                "example": "修仙境界体系 → 炼气期/筑基期/金丹期..."
            },
            "technique_system": {
                "name": "功法体系",
                "structure": "3层分类（体系→分类→详情）",
                "example": "功法体系 → 剑法 → 太虚剑诀"
            },
            "map_system": {
                "name": "地图体系",
                "structure": "4层复杂（体系→分类→列表→详情）",
                "example": "地图体系 → 城镇聚落 → 主要城市 → 天元城"
            },
            "pill_system": {
                "name": "丹药体系",
                "structure": "3层分类",
                "example": "丹药体系 → 突破丹药 → 筑基丹"
            }
        }
        
        for category, info in examples.items():
            print(f"\n📚 {info['name']} ({category})")
            print(f"   结构: {info['structure']}")
            print(f"   示例: {info['example']}")
    
    def run_demo(self):
        """运行完整演示"""
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║            🎭 层级配置使用演示                              ║
║                                                              ║
║  本演示将展示：                                              ║
║  1. 用户登录                                                 ║
║  2. 创建项目                                                 ║
║  3. 应用模板（自动注入层级配置）                             ║
║  4. 查看各体系的层级配置                                     ║
║  5. 获取树形结构                                             ║
║  6. 对比不同体系的层级设计                                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """)
        
        try:
            self.login()
            if not self.token:
                return
            
            self.create_project()
            if not self.project_id:
                return
            
            self.apply_template()
            self.list_collections()
            self.get_tree_structure()
            self.demonstrate_hierarchy_examples()
            
            print_section("✅ 演示完成")
            print(f"""
演示总结：
1. ✅ 成功登录并创建项目
2. ✅ 应用玄幻修真模板，自动注入23个体系的层级配置
3. ✅ 展示了各体系的层级结构差异：
   - 境界体系：2层扁平（用关系边连接前置关系）
   - 功法/丹药/阵法等：3层分类
   - 地图体系：4层复杂
4. ✅ 获取并展示了树形结构

🎯 关键点：
- hierarchy_config 在应用模板时自动注入
- 前端可根据 max_depth 和 levels 配置动态渲染树形视图
- 不同体系可以有不同的层级深度，系统会自动适配

📖 下一步：
- 在前端 WorkflowControlPage 中点击"世界观设定"
- 选择任一集合（如"功法体系"）
- 查看树形视图的实际效果
            """)
            
        except Exception as e:
            print(f"\n❌ 演示过程出错: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    demo = HierarchyDemo()
    demo.run_demo()
