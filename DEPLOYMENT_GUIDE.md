# 拾光工坊 - 部署指南

## 📋 概述

本文档说明如何将"拾光工坊"从开发环境部署到生产环境。

## 🔧 环境配置说明

### 开发环境（当前配置）

**数据库：** SQLite
**DEBUG模式：** 开启
**数据库URL：** `sqlite:///../novel_app.db`

**适用场景：**
- 本地开发
- 功能测试
- 快速迭代

### 生产环境配置

**数据库：** PostgreSQL
**DEBUG模式：** 关闭
**数据库URL：** `postgresql://novel_user:password@host:5432/novel_db`

**适用场景：**
- 正式部署
- 大规模商用
- 高并发场景

## 🚀 部署步骤

### 步骤1：修改后端配置（backend/.env）

```bash
# 1. 关闭DEBUG模式
DEBUG=False

# 2. 切换到PostgreSQL
# 注释掉SQLite配置
# DATABASE_URL=sqlite:///../novel_app.db

# 取消注释PostgreSQL配置
DATABASE_URL=postgresql://novel_user:novel_secure_password_2024@localhost:5432/novel_db

# 3. 修改安全密钥（必须！）
# 生成强密码
openssl rand -base64 32  # PostgreSQL密码
openssl rand -base64 16  # Redis密码
openssl rand -hex 32     # JWT密钥

# 更新以下配置：
# - DATABASE_URL 中的密码
# - REDIS_URL 中的密码
# - JWT_SECRET
```

### 步骤2：修改Docker Compose配置（docker-compose.yml）

```yaml
# 确保以下配置正确：

backend:
  environment:
    # 数据库配置
    DATABASE_URL: postgresql://novel_user:novel_secure_password_2024@postgres:5432/novel_db
    # Redis配置
    REDIS_URL: redis://:redis_secure_password_2024@redis:6379/0
    # JWT密钥
    JWT_SECRET: CHANGE_THIS_TO_SECURE_RANDOM_KEY_MIN_32_BYTES
    # 关闭DEBUG
    DEBUG: "False"
    # 连接池配置
    DB_POOL_SIZE: 20
    DB_MAX_OVERFLOW: 10
    DB_POOL_TIMEOUT: 30
    DB_POOL_RECYCLE: 3600
    DB_POOL_PRE_PING: "True"

postgres:
  environment:
    POSTGRES_USER: novel_user
    POSTGRES_PASSWORD: novel_secure_password_2024  # 修改为实际密码
    POSTGRES_DB: novel_db

redis:
  command: redis-server --requirepass redis_secure_password_2024 --appendonly yes
```

### 步骤3：配置SSL证书

```bash
# 创建SSL目录
mkdir -p ssl

# 方式一：Let's Encrypt（免费）
certbot certonly --standalone -d sggf.net -d www.sggf.net
cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem

# 方式二：使用已有证书
cp your-cert.pem ssl/cert.pem
cp your-key.pem ssl/key.pem
```

### 步骤4：启动服务

```bash
# 1. 启动所有服务
docker-compose up -d

# 2. 查看服务状态
docker-compose ps

# 3. 查看日志
docker-compose logs -f backend

# 4. 等待服务启动
sleep 30
```

### 步骤5：数据迁移（如果有SQLite数据）

```bash
# 如果有旧的SQLite数据，运行迁移脚本
python migrate_to_postgres.py

# 验证数据
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT COUNT(*) FROM users;"
```

### 步骤6：验证部署

```bash
# 1. 健康检查
curl https://sggf.net/health

# 预期输出：{"status":"ok","version":"1.0.0"}

# 2. 检查前端
curl -I https://sggf.net/

# 3. 检查API
curl https://sggf.net/api/v1/projects

# 4. 检查数据库连接
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT version();"
```

## 🔄 开发与生产环境切换

### 从生产切换回开发

```bash
# 1. 修改 backend/.env
DEBUG=True
DATABASE_URL=sqlite:///../novel_app.db

# 2. 重启后端服务
docker-compose restart backend

# 或者本地开发直接运行
python backend/app/main.py
```

### 从开发切换到生产

```bash
# 1. 修改 backend/.env
DEBUG=False
DATABASE_URL=postgresql://novel_user:password@host:5432/novel_db

# 2. 启动Docker服务
docker-compose up -d

# 3. 验证配置
docker-compose logs backend | grep "拾光工坊"
```

## ⚠️ 常见问题

### 问题1：SQLAlchemy连接错误

**错误信息：** `sqlalchemy.exc.OperationalError`

**原因：** PostgreSQL服务未启动或连接配置错误

**解决方案：**
```bash
# 1. 检查PostgreSQL是否运行
docker-compose ps postgres

# 2. 查看PostgreSQL日志
docker-compose logs postgres

# 3. 测试连接
docker exec -it novel_postgres psql -U novel_user -d novel_db

# 4. 如果是本地开发，使用SQLite
DATABASE_URL=sqlite:///../novel_app.db
```

### 问题2：CORS错误

**错误信息：** `Access to fetch at ... has been blocked by CORS policy`

**原因：** CORS域名配置不正确

**解决方案：**
```bash
# 检查 backend/.env 中的CORS配置
CORS_ORIGINS=["https://sggf.net", "https://www.sggf.net"]

# 重启后端服务
docker-compose restart backend
```

### 问题3：WebSocket连接失败

**错误信息：** `WebSocket connection failed`

**原因：** WebSocket URL配置错误或Nginx配置问题

**解决方案：**
```bash
# 1. 检查前端配置
VITE_WS_URL=wss://sggf.net

# 2. 检查Nginx配置
cat nginx.conf | grep -A 10 "location /ws/"

# 3. 测试WebSocket连接
wscat -c wss://sggf.net/ws/
```

## 📊 性能优化

### 数据库优化

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

### 缓存优化

```bash
# 查看Redis缓存命中率
docker exec -it novel_redis redis-cli -a <password> INFO stats

# 清理过期缓存
docker exec -it novel_redis redis-cli -a <password> FLUSHDB
```

## 🔒 安全检查清单

### 部署前必须完成

- [ ] 已修改PostgreSQL密码
- [ ] 已修改Redis密码
- [ ] 已修改JWT密钥
- [ ] 已配置SSL证书
- [ ] 已关闭DEBUG模式
- [ ] 已配置防火墙规则
- [ ] 已配置CORS域名
- [ ] 已配置DNS记录

### 部署后验证

- [ ] HTTPS访问正常
- [ ] 用户注册/登录正常
- [ ] API请求正常
- [ ] WebSocket连接正常
- [ ] 文件上传正常
- [ ] 数据库操作正常
- [ ] 健康检查端点正常

## 📈 监控与告警

### 健康检查

```bash
# 设置定期健康检查
*/5 * * * * curl -f https://sggf.net/health || echo "Health check failed"
```

### 日志监控

```bash
# 监控错误日志
tail -f backend/logs/app.log | grep ERROR

# 监控Nginx日志
docker-compose logs -f nginx | grep error
```

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
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz backend/uploads/
```

## 📞 技术支持

如遇到问题，请检查：

1. **日志文件：**
   - Backend: `backend/logs/app.log`
   - Nginx: `docker-compose logs nginx`
   - PostgreSQL: `docker-compose logs postgres`

2. **健康检查：**
   - `https://sggf.net/health`

3. **文档：**
   - [POSTGRESQL_DEPLOYMENT.md](POSTGRESQL_DEPLOYMENT.md)
   - [PRODUCTION_DEPLOYMENT_CHECKLIST.md](PRODUCTION_DEPLOYMENT_CHECKLIST.md)

## 🎉 部署完成

部署成功后，请：

1. **访问网站：** https://sggf.net
2. **测试功能：** 创建账户、创建项目、测试API
3. **监控日志：** 定期查看服务日志
4. **备份数据：** 定期备份数据库和上传文件
5. **更新密码：** 定期更新安全密钥

---

**应用名称：** 拾光工坊
**版本：** 1.0.0
**部署域名：** sggf.net
**数据库：** PostgreSQL（生产）/ SQLite（开发）
