# SSL证书配置说明

## 证书位置
证书文件应放置在项目根目录的 `ssl/` 文件夹中：

```
ssl/
├── cert.pem    # SSL证书文件
└── key.pem     # SSL私钥文件
```

## 获取SSL证书的方式

### 方式一：Let's Encrypt（免费，推荐用于生产环境）

**前提条件：**
- 域名已解析到服务器IP
- 服务器80端口可访问

**步骤：**

1. **安装certbot**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install certbot

# CentOS/RHEL
sudo yum install certbot
```

2. **获取证书**
```bash
# 停止nginx（如果运行中）
docker-compose stop nginx

# 获取证书
certbot certonly --standalone -d sggf.net -d www.sggf.net

# 证书位置
# /etc/letsencrypt/live/sggf.net/fullchain.pem  -> ssl/cert.pem
# /etc/letsencrypt/live/sggf.net/privkey.pem   -> ssl/key.pem
```

3. **复制证书到项目目录**
```bash
mkdir -p ssl
cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem

# 设置权限
chmod 644 ssl/cert.pem
chmod 600 ssl/key.pem
```

4. **设置自动续期**
```bash
# 添加cron任务
0 0,12 * * * certbot renew --quiet --post-hook "docker-compose restart nginx"
```

### 方式二：购买商业SSL证书（推荐用于正式生产）

**步骤：**

1. **购买证书**
   - 从证书提供商购买（如：DigiCert、GlobalSign、Let's Encrypt Pro等）
   - 选择域名：sggf.net 和 www.sggf.net

2. **下载证书**
   - 下载格式：PEM或CRT
   - 通常包含：证书文件 + 私钥文件 + CA证书链

3. **转换格式（如果需要）**
```bash
# 如果是CRT格式，转换为PEM
openssl x509 -in your-cert.crt -out cert.pem

# 如果私钥是其他格式
openssl rsa -in your-key.key -out key.pem
```

4. **复制到项目目录**
```bash
mkdir -p ssl
cp your-cert.pem ssl/cert.pem
cp your-key.pem ssl/key.pem

# 设置权限
chmod 644 ssl/cert.pem
chmod 600 ssl/key.pem
```

### 方式三：自签名证书（仅用于测试，不推荐生产环境）

**步骤：**

1. **生成自签名证书**
```bash
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem \
  -out ssl/cert.pem \
  -subj "/C=CN/ST=Beijing/L=Beijing/O=拾光工坊/CN=sggf.net"
```

2. **设置权限**
```bash
chmod 644 ssl/cert.pem
chmod 600 ssl/key.pem
```

3. **浏览器警告**
   - 自签名证书会导致浏览器显示"不安全"警告
   - 需要手动信任证书
   - 仅用于本地测试

## 证书验证

### 验证证书文件
```bash
# 检查证书文件
openssl x509 -in ssl/cert.pem -text -noout

# 检查私钥文件
openssl rsa -in ssl/key.pem -check

# 验证证书和私钥匹配
openssl x509 -noout -modulus -in ssl/cert.pem | openssl md5
openssl rsa -noout -modulus -in ssl/key.pem | openssl md5
# 两个MD5值应该相同
```

### 测试SSL连接
```bash
# 测试SSL连接
openssl s_client -connect sggf.net:443 -servername sggf.net

# 或使用在线工具
# https://www.ssllabs.com/ssltest/
```

## 证书续期

### Let's Encrypt自动续期
```bash
# 手动续期
certbot renew --quiet --post-hook "docker-compose restart nginx"

# 测试续期
certbot renew --dry-run
```

### 商业证书续期
- 在证书到期前30天联系证书提供商
- 购买续期服务
- 按照提供商的指南更新证书

## 故障排查

### 问题1：证书文件不存在
**错误：** `nginx: [emerg] BIO_new_file("/etc/nginx/ssl/cert.pem") failed`

**解决方案：**
```bash
# 检查证书文件是否存在
ls -la ssl/

# 如果不存在，创建证书目录并生成证书
mkdir -p ssl
# 按照上述方式获取证书
```

### 问题2：证书权限错误
**错误：** `nginx: [emerg] BIO_new_file("/etc/nginx/ssl/key.pem") failed (13: Permission denied)`

**解决方案：**
```bash
# 修改私钥文件权限
chmod 600 ssl/key.pem

# 修改证书文件权限
chmod 644 ssl/cert.pem
```

### 问题3：证书过期
**错误：** 浏览器显示"证书已过期"

**解决方案：**
```bash
# 检查证书过期时间
openssl x509 -in ssl/cert.pem -noout -dates

# 续期证书
certbot renew --force --post-hook "docker-compose restart nginx"
```

## 安全建议

1. **使用强加密算法**
   - 使用RSA 2048位或更高
   - 使用ECC（椭圆曲线）更安全

2. **启用HSTS**
   ```nginx
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
   ```

3. **定期更新证书**
   - Let's Encrypt：90天有效期，建议60天续期
   - 商业证书：1-2年有效期，到期前30天续期

4. **备份证书**
   ```bash
   # 备份证书
   cp ssl/cert.pem ssl/cert.pem.backup
   cp ssl/key.pem ssl/key.pem.backup
   ```

## 证书文件示例

### cert.pem（证书文件）
```
-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAJc1HiIAZAiIMA0GCSqGSIb3DQEBCwUAMIGHUxBh
...
-----END CERTIFICATE-----
```

### key.pem（私钥文件）
```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAvc7yB5yo3qZqJ4ZqZqZqZqZqZqZqZqZqZqZqZqZq
...
-----END RSA PRIVATE KEY-----
```

## 相关文档

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- [PRODUCTION_DEPLOYMENT_CHECKLIST.md](PRODUCTION_DEPLOYMENT_CHECKLIST.md)
- [nginx.conf](nginx.conf)

---

**注意事项：**
- 生产环境必须使用有效的SSL证书
- 不要将私钥文件提交到版本控制系统
- 定期检查证书有效期
- 及时续期即将过期的证书
