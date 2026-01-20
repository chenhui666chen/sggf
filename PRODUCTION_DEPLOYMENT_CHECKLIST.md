# 生产环境部署配置清单 - sggf.net

## ✅ 已完成的配置

### 1. 后端配置（backend/.env）
- ✅ 数据库：PostgreSQL
- ✅ DEBUG模式：已关闭
- ✅ CORS域名：已配置为 sggf.net
- ✅ Redis密码：已配置
- ✅ 数据库连接池：已配置
- ✅ JWT密钥：需要修改（见下方）

### 2. 前端配置（frontend/.env）
- ✅ API URL：https://sggf.net
- ✅ WebSocket URL：wss://sggf.net

### 3. Nginx配置（nginx.conf）
- ✅ 域名：已配置为 sggf.net
- ✅ HTTP到HTTPS重定向：已配置
- ✅ SSL配置：已配置（需要证书）

### 4. Docker Compose配置（docker-compose.yml）
- ✅ PostgreSQL：已优化配置
- ✅ Redis：已配置密码
- ✅ Backend：已配置连接池和多worker
- ✅ Frontend：已配置生产环境变量
- ✅ 资源限制：已配置

## ⚠️ 部署前必须完成的配置

### 1. 修改安全密钥（必须）

```bash
# 生成PostgreSQL密码
openssl rand -base64 32

# 生成Redis密码
openssl rand -base64 16

# 生成JWT密钥
openssl rand -hex 32
```

**需要修改的文件：**
- `backend/.env` 中的 `POSTGRES_PASSWORD`
- `backend/.env` 中的 `REDIS_URL` 中的密码
- `backend/.env` 中的 `JWT_SECRET`
- `docker-compose.yml` 中的环境变量

### 2. 配置SSL证书

**证书路径：** `./ssl/cert.pem` 和 `./ssl/key.pem`

**获取证书方式：**

#### 方式一：Let's Encrypt（免费）
```bash
# 安装certbot
apt-get install certbot

# 获取证书
certbot certonly --standalone -d sggf.net -d www.sggf.net

# 复制证书
cp /etc/letsencrypt/live/sggf.net/fullchain.pem ./ssl/cert.pem
cp /etc/letsencrypt/live/sggf.net/privkey.pem ./ssl/key.pem
```

#### 方式二：购买商业SSL证书
1. 从证书提供商购买SSL证书
2. 下载证书文件（.pem或.crt格式）
3. 将证书文件放到 `./ssl/` 目录
4. 重命名为 `cert.pem` 和 `key.pem`

#### 方式三：自签名证书（仅用于测试）
```bash
# 生成自签名证书
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ./ssl/key.pem \
  -out ./ssl/cert.pem \
  -subj "/C=CN/ST=State/L=City/O=Organization/CN=sggf.net"
```

### 3. DNS配置

**需要配置的DNS记录：**

| 记录类型 | 主机记录 | 记录值 | 说明 |
|----------|---------|--------|------|
| A | sggf.net | 你的服务器IP | 主域名 |
| A | www.sggf.net | 你的服务器IP | www子域名 |
| CNAME | api.sggf.net | sggf.net | API子域名（可选） |
| CNAME | ws.sggf.net | sggf.net | WebSocket子域名（可选） |

### 4. 防火墙配置

**需要开放的端口：**

| 端口 | 协议 | 说明 |
|------|------|------|
| 80 | TCP | HTTP（重定向到HTTPS） |
| 443 | TCP | HTTPS |
| 22 | TCP | SSH（仅管理需要） |

**不需要开放的端口：**
- 5432（PostgreSQL）- 仅容器内部通信
- 6379（Redis）- 仅容器内部通信
- 8000（Backend）- 通过Nginx代理
- 3000（Frontend）- 通过Nginx代理

## 🚀 部署步骤

### 步骤1：准备服务器

```bash
# 1. 安装Docker和Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# 2. 克隆代码
git clone <your-repo-url> /opt/novel_writing_agent
cd /opt/novel_writing_agent

# 3. 创建SSL目录
mkdir -p ssl
```

### 步骤2：配置环境变量

```bash
# 1. 复制环境变量模板
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 2. 修改backend/.env
# 编辑以下配置：
# - DATABASE_URL（如果使用云数据库）
# - POSTGRES_PASSWORD（如果使用Docker PostgreSQL）
# - REDIS_URL（如果使用云Redis）
# - JWT_SECRET（必须修改）
# - CORS_ORIGINS（已配置为sggf.net）

# 3. 生成并更新密码
# 使用openssl生成强密码并更新到.env文件
```

### 步骤3：配置SSL证书

```bash
# 将SSL证书放到ssl目录
cp your-cert.pem ssl/cert.pem
cp your-key.pem ssl/key.pem

# 设置正确的权限
chmod 600 ssl/key.pem
chmod 644 ssl/cert.pem
```

### 步骤4：启动服务

```bash
# 1. 启动所有服务
docker-compose up -d

# 2. 查看服务状态
docker-compose ps

# 3. 查看日志
docker-compose logs -f backend

# 4. 等待服务启动（约30秒）
sleep 30
```

### 步骤5：验证部署

```bash
# 1. 健康检查
curl https://sggf.net/health

# 预期输出：{"status":"ok","version":"1.0.0"}

# 2. 检查前端
curl -I https://sggf.net/

# 预期输出：HTTP/1.1 200 OK

# 3. 检查API
curl https://sggf.net/api/v1/projects

# 预期输出：401 Unauthorized（需要认证）或项目列表

# 4. 检查数据库连接
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT version();"

# 5. 检查Redis连接
docker exec -it novel_redis redis-cli -a <your-redis-password> ping

# 预期输出：PONG
```

## 🔍 故障排查

### 问题1：无法访问网站

**检查步骤：**
```bash
# 1. 检查服务状态
docker-compose ps

# 2. 查看Nginx日志
docker-compose logs nginx

# 3. 检查SSL证书
ls -la ssl/

# 4. 测试本地访问
curl -k https://localhost
```

### 问题2：API请求失败

**检查步骤：**
```bash
# 1. 查看Backend日志
docker-compose logs backend

# 2. 检查数据库连接
docker exec -it novel_backend python -c "from app.db.base import engine; print(engine.connect())"

# 3. 检查CORS配置
# 查看浏览器控制台的网络请求
```

### 问题3：WebSocket连接失败

**检查步骤：**
```bash
# 1. 查看Nginx配置
cat nginx.conf | grep -A 10 "location /ws/"

# 2. 检查WebSocket日志
docker-compose logs backend | grep websocket

# 3. 测试WebSocket连接
wscat -c wss://sggf.net/ws/
```

## 📊 性能优化建议

### 1. 数据库优化

```bash
# 定期运行VACUUM
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "VACUUM ANALYZE;"

# 查看慢查询
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "
SELECT query, mean_exec_time, calls 
FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;
"
```

### 2. 缓存优化

```bash
# 查看Redis缓存命中率
docker exec -it novel_redis redis-cli -a <password> INFO stats

# 清理过期缓存
docker exec -it novel_redis redis-cli -a <password> --scan 0 --pattern '*' | xargs redis-cli -a <password> DEL
```

### 3. Nginx优化

```nginx
# 在nginx.conf中添加
# 启用Gzip压缩
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss;

# 启用缓存
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=1g inactive=60m;
```

## 🔒 安全加固建议

### 1. 定期更新密码

```bash
# 每90天更新一次数据库密码
# 每90天更新一次Redis密码
# 每90天更新一次JWT密钥
```

### 2. 配置防火墙

```bash
# 使用ufw防火墙
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw deny 5432/tcp  # PostgreSQL
ufw deny 6379/tcp  # Redis
ufw enable
```

### 3. 启用安全头

```nginx
# 在nginx.conf的HTTPS server块中添加
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### 4. 配置速率限制

```nginx
# 在nginx.conf中添加
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

location /api/v1/auth/login {
    limit_req zone=login_limit burst=10 nodelay;
    ...
}

location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    ...
}
```

## 📈 监控告警

### 1. 健康检查

```bash
# 设置定期健康检查
*/5 * * * * curl -f https://sggf.net/health || echo "Health check failed" | mail -s "Alert" admin@sggf.net
```

### 2. 日志监控

```bash
# 监控错误日志
tail -f backend/logs/app.log | grep ERROR | mail -s "Error detected" admin@sggf.net
```

### 3. 资源监控

建议使用以下工具：
- Prometheus + Grafana
- Datadog
- New Relic
- 阿里云云监控

## 🔄 备份策略

### 自动备份

```bash
# 添加到crontab
0 2 * * * /usr/local/bin/docker-compose exec -T postgres pg_dump -U novel_user novel_db | gzip > /backup/novel_$(date +\%Y\%m\%d).sql.gz

# 保留最近30天的备份
find /backup -name "novel_*.sql.gz" -mtime +30 -delete
```

### 手动备份

```bash
# 备份数据库
docker-compose exec postgres pg_dump -U novel_user novel_db > backup_$(date +%Y%m%d).sql

# 备份上传文件
docker-compose exec postgres psql -U novel_user -d novel_db -c "\dt" | grep uploads

# 备份向量数据库
tar -czf chroma_backup_$(date +%Y%m%d).tar.gz backend/chroma_db/
```

## 📋 部署前最终检查清单

### 安全配置
- [ ] 已修改PostgreSQL密码
- [ ] 已修改Redis密码
- [ ] 已修改JWT密钥
- [ ] 已配置SSL证书
- [ ] 已配置防火墙规则
- [ ] 已启用安全头
- [ ] 已配置速率限制

### 网络配置
- [ ] DNS记录已配置
- [ ] 域名已指向服务器IP
- [ ] HTTP自动重定向到HTTPS
- [ ] WebSocket配置正确

### 服务配置
- [ ] PostgreSQL连接正常
- [ ] Redis连接正常
- [ ] Backend服务正常
- [ ] Frontend服务正常
- [ ] Nginx代理正常

### 功能验证
- [ ] 健康检查端点正常
- [ ] 用户注册/登录正常
- [ ] API请求正常
- [ ] WebSocket连接正常
- [ ] 文件上传正常
- [ ] 数据库操作正常

### 性能优化
- [ ] 数据库连接池已配置
- [ ] Redis缓存已配置
- [ ] Nginx缓存已配置
- [ ] Gzip压缩已启用
- [ ] 静态资源CDN已配置（可选）

### 监控备份
- [ ] 日志监控已配置
- [ ] 健康检查已配置
- [ ] 自动备份已配置
- [ ] 告警通知已配置
- [ ] 监控仪表板已配置

## 📞 技术支持

如遇到部署问题，请检查以下资源：

1. **日志文件：**
   - Backend: `backend/logs/app.log`
   - Nginx: Docker logs (`docker-compose logs nginx`)

2. **文档：**
   - [POSTGRESQL_DEPLOYMENT.md](POSTGRESQL_DEPLOYMENT.md)
   - [README.md](README.md)

3. **健康检查：**
   - `https://sggf.net/health`

## 🎉 部署完成后

部署成功后，请：

1. **访问网站：** https://sggf.net
2. **测试功能：** 创建账户、创建项目、测试API
3. **监控日志：** 定期查看服务日志
4. **备份数据：** 定期备份数据库和上传文件
5. **更新密码：** 定期更新安全密钥

---

**部署日期：** ___________
**部署人员：** ___________
**服务器IP：** ___________
**备注：** ___________
