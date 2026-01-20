"""
生成自签名SSL证书（用于测试）
注意：自签名证书会导致浏览器显示安全警告，仅用于本地测试
生产环境请使用Let's Encrypt或购买商业SSL证书
"""
import subprocess
import os

def generate_self_signed_cert():
    """生成自签名SSL证书"""
    
    # 创建ssl目录
    ssl_dir = os.path.join(os.path.dirname(__file__), 'ssl')
    os.makedirs(ssl_dir, exist_ok=True)
    
    cert_path = os.path.join(ssl_dir, 'cert.pem')
    key_path = os.path.join(ssl_dir, 'key.pem')
    
    # 生成自签名证书
    cmd = [
        'openssl', 'req', '-x509', '-nodes', '-days', '365',
        '-newkey', 'rsa:2048',
        '-keyout', key_path,
        '-out', cert_path,
        '-subj', '/C=CN/ST=Beijing/L=Beijing/O=拾光工坊/CN=sggf.net'
    ]
    
    print("=" * 60)
    print("生成自签名SSL证书")
    print("=" * 60)
    print()
    print(f"证书文件: {cert_path}")
    print(f"私钥文件: {key_path}")
    print()
    print("正在生成证书...")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ 证书生成成功！")
        print()
        print("⚠️  注意事项：")
        print("   - 自签名证书会导致浏览器显示安全警告")
        print("   - 仅用于本地测试，生产环境请使用Let's Encrypt或购买SSL证书")
        print("   - 详见 SSL_CERTIFICATE_GUIDE.md")
        print()
        print("=" * 60)
        
        # 设置权限
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)
        print("✅ 文件权限已设置")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ 证书生成失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        return False
    
    return True

if __name__ == "__main__":
    generate_self_signed_cert()
