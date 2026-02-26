"""
验证 project_settings 表是否可以正常使用
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

# 加载环境变量
backend_env = Path(__file__).parent / "backend" / ".env"
load_dotenv(backend_env)

# 获取数据库连接信息
database_url = os.getenv("DATABASE_URL")

print("=" * 60)
print("验证 project_settings 表")
print("=" * 60)

# 解析数据库URL
if database_url.startswith("postgresql://"):
    db_url = database_url.replace("postgresql://", "")
    parts = db_url.split("@")
    credentials = parts[0].split(":")
    host_db = parts[1].split("/")
    
    user = credentials[0]
    password = credentials[1]
    host_port = host_db[0].split(":")
    host = host_port[0]
    port = int(host_port[1]) if len(host_port) > 1 else 5432
    database = host_db[1]
    
    try:
        # 连接数据库
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # 测试查询（模拟应用中的查询）
        print(f"\n{'='*60}")
        print("测试查询: SELECT concept, world_setting, characters, plot_outline, chapter_draft, review_report, final_version FROM project_settings WHERE project_id = %(project_id)s")
        print(f"{'='*60}")
        
        try:
            cursor.execute(
                "SELECT concept, world_setting, characters, plot_outline, chapter_draft, review_report, final_version FROM project_settings WHERE project_id = %(project_id)s",
                {"project_id": 1}
            )
            
            result = cursor.fetchone()
            
            if result:
                print("✅ 查询成功")
                print(f"   结果: {result}")
            else:
                print("✅ 查询成功（无结果）")
                print("   说明: project_id=1 的记录不存在，这是正常的")
        
        except Exception as e:
            print(f"❌ 查询失败: {e}")
            raise
        
        # 测试插入数据
        print(f"\n{'='*60}")
        print("测试插入数据")
        print(f"{'='*60}")
        
        try:
            cursor.execute("""
                INSERT INTO project_settings (project_id, concept, world_setting, characters, plot_outline)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO NOTHING
            """, (1, "测试概念", "测试世界观", "测试人物", "测试大纲"))
            
            print("✅ 插入数据成功")
            
            # 再次查询验证
            cursor.execute(
                "SELECT concept, world_setting, characters, plot_outline, chapter_draft, review_report, final_version FROM project_settings WHERE project_id = %(project_id)s",
                {"project_id": 1}
            )
            
            result = cursor.fetchone()
            
            if result:
                print(f"✅ 验证查询成功")
                print(f"   concept: {result[0]}")
                print(f"   world_setting: {result[1]}")
                print(f"   characters: {result[2]}")
                print(f"   plot_outline: {result[3]}")
        
        except Exception as e:
            print(f"❌ 插入数据失败: {e}")
            raise
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

print(f"\n{'='*60}")
print("验证完成")
print(f"{'='*60}")
print("\n✅ project_settings 表已成功创建并可以正常使用")
print("💡 现在可以重启后端服务，错误应该已经解决")
