"""
启动后端服务的脚本
"""
import subprocess
import sys
import os
import time

def start_backend():
    """启动后端服务"""
    try:
        # 切换到backend目录
        backend_path = os.path.join(os.path.dirname(__file__), 'backend')
        os.chdir(backend_path)
        
        print("🚀 启动后端服务...")
        print(f"工作目录: {os.getcwd()}")
        
        # 启动uvicorn服务器
        process = subprocess.Popen([
            sys.executable, '-m', 'uvicorn', 
            'app.main:application', 
            '--host', '0.0.0.0', 
            '--port', '8000'
        ])
        
        print(f"✅ 后端服务已启动 (PID: {process.pid})")
        print("访问地址: http://localhost:8000")
        print("API文档: http://localhost:8000/docs")
        
        # 等待几秒钟让服务启动
        time.sleep(5)
        
        return process
        
    except Exception as e:
        print(f"❌ 启动后端服务失败: {e}")
        return None

if __name__ == "__main__":
    process = start_backend()
    if process:
        try:
            # 保持进程运行
            process.wait()
        except KeyboardInterrupt:
            print("\n🛑 正在停止后端服务...")
            process.terminate()
            process.wait()
            print("✅ 后端服务已停止")