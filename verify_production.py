"""
生产环境部署验证脚本
"""
import subprocess
import requests
import time

def run_command(cmd, description):
    """运行命令并返回结果"""
    print(f"\n[检查] {description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"✅ {description} - 正常")
            return True
        else:
            print(f"❌ {description} - 失败")
            print(f"错误: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"⚠️ {description} - 超时")
        return False
    except Exception as e:
        print(f"❌ {description} - 异常: {e}")
        return False

def check_docker_services():
    """检查Docker服务状态"""
    print("\n" + "=" * 60)
    print("Docker服务检查")
    print("=" * 60)
    
    # 检查Docker是否运行
    if not run_command("docker ps", "Docker运行状态"):
        return False
    
    # 检查PostgreSQL
    run_command("docker exec novel_postgres pg_isready -U novel_user", "PostgreSQL连接")
    
    # 检查Redis
    run_command("docker exec novel_redis redis-cli -a MfDUzsb5%%&1uYW9N ping", "Redis连接")
    
    # 检查Backend
    run_command("docker exec novel_backend curl -f http://localhost:8000/health", "Backend健康检查")
    
    # 检查Frontend
    run_command("docker exec novel_frontend curl -f http://localhost:3000", "Frontend运行")
    
    # 检查Nginx
    run_command("docker exec novel_nginx nginx -t", "Nginx配置")
    
    return True

def check_api_endpoints():
    """检查API端点"""
    print("\n" + "=" * 60)
    print("API端点检查")
    print("=" * 60)
    
    # 等待服务启动
    print("\n[等待] 等待服务启动...")
    time.sleep(5)
    
    # 检查健康端点
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 健康检查 - 正常")
            print(f"   状态: {data.get('status')}")
            print(f"   版本: {data.get('version')}")
        else:
            print(f"❌ 健康检查 - 失败 (HTTP {response.status_code})")
    except Exception as e:
        print(f"❌ 健康检查 - 异常: {e}")
    
    # 检查API文档
    try:
        response = requests.get("http://localhost:8000/docs", timeout=5)
        if response.status_code == 200:
            print(f"✅ API文档 - 正常")
        else:
            print(f"❌ API文档 - 失败 (HTTP {response.status_code})")
    except Exception as e:
        print(f"❌ API文档 - 异常: {e}")
    
    return True

def check_database():
    """检查数据库连接"""
    print("\n" + "=" * 60)
    print("数据库检查")
    print("=" * 60)
    
    # 检查PostgreSQL版本
    run_command(
        "docker exec novel_postgres psql -U novel_user -d novel_db -c \"SELECT version();\"",
        "PostgreSQL版本"
    )
    
    # 检查数据库大小
    run_command(
        "docker exec novel_postgres psql -U novel_user -d novel_db -c \"SELECT pg_size_pretty(pg_database_size('novel_db'));\"",
        "数据库大小"
    )
    
    # 检查连接数
    run_command(
        "docker exec novel_postgres psql -U novel_user -d novel_db -c \"SELECT count(*) FROM pg_stat_activity;\"",
        "活动连接数"
    )
    
    return True

def check_ssl():
    """检查SSL配置"""
    print("\n" + "=" * 60)
    print("SSL配置检查")
    print("=" * 60)
    
    # 检查证书文件
    if run_command("dir ssl\\cert.pem", "证书文件存在"):
        run_command("dir ssl\\key.pem", "私钥文件存在")
    else:
        print("⚠️ SSL证书文件不存在，使用占位符证书")
    
    return True

def print_summary():
    """打印总结"""
    print("\n" + "=" * 60)
    print("验证总结")
    print("=" * 60)
    print()
    print("✅ 配置检查完成")
    print()
    print("下一步操作：")
    print("1. 配置DNS记录（sggf.net -> 服务器IP）")
    print("2. 获取真实SSL证书（替换占位符证书）")
    print("3. 配置防火墙规则（开放80、443端口）")
    print("4. 重启服务使配置生效")
    print()
    print("访问地址：")
    print("  - 前端: http://localhost:3000")
    print("  - 后端: http://localhost:8000")
    print("  - API文档: http://localhost:8000/docs")
    print("  - 健康检查: http://localhost:8000/health")
    print()
    print("生产环境访问（配置DNS后）：")
    print("  - 前端: https://sggf.net")
    print("  - 后端: https://sggf.net/api/")
    print("  - WebSocket: wss://sggf.net/ws/")
    print()
    print("=" * 60)

def main():
    """主函数"""
    print("=" * 60)
    print("拾光工坊 - 生产环境部署验证")
    print("=" * 60)
    
    # 检查Docker服务
    check_docker_services()
    
    # 检查API端点
    check_api_endpoints()
    
    # 检查数据库
    check_database()
    
    # 检查SSL配置
    check_ssl()
    
    # 打印总结
    print_summary()

if __name__ == "__main__":
    main()
