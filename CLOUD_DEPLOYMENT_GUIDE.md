# 拾光工坊 - 云端部署指南

## 📋 目录

1. [部署选项](#部署选项)
2. [阿里云ECS部署](#阿里云ecs部署)
3. [其他云服务商部署](#其他云服务商部署)
4. [部署前准备](#部署前准备)
5. [部署后验证](#部署后验证)
6. [常见问题](#常见问题)

---

## 🚀 部署选项

### 选项1：阿里云ECS（推荐）

**优势**：
- ✅ 已有完整部署脚本（`deploy.sh`）
- ✅ 配置文件已针对阿里云优化
- ✅ 域名和SSL证书已配置
- ✅ 部署流程简单，一键部署

**服务器信息**：
- 域名：`sggf.net`
- IP地址：`101.132.154.143`
- 需要开放的端口：80, 443

### 选项2：其他云服务商

支持的服务商：
- 腾讯云
- 华为云
- AWS
- DigitalOcean
- Vultr
- 其他支持Docker的云服务器

---

## 📦 阿里云ECS部署

### 步骤1：准备服务器

#### 1.1 购买/配置ECS实例

**推荐配置**：
- **CPU**：2核或以上
- **内存**：4GB或以上
- **操作系统**：Alibaba Cloud Linux 3 / CentOS 7+ / Ubuntu 20.04+
- **带宽**：5Mbps或以上（根据访问量调整）
- **存储**：40GB SSD或以上

#### 1.2 配置安全组

在阿里云控制台配置安全组规则：

| 协议 | 端口范围 | 授权对象 | 描述 |
|------|---------|---------|------|
| TCP | 22 | 0.0.0.0/0 | SSH（生产环境建议限制IP） |
| TCP | 80 | 0.0.0.0/0 | HTTP |
| TCP | 443 | 0.0.0.0/0 | HTTPS |

#### 1.3 配置域名解析

在阿里云域名控制台添加A记录：

| 主机记录 | 记录类型 | 记录值 | TTL |
|---------|---------|--------|-----|
| @ | A | 101.132.154.143 | 600 |
| www | A | 101.132.154.143 | 600 |

### 步骤2：上传项目文件

#### 2.1 方法1：使用SCP上传（推荐）

```bash
# 在本地Windows PowerShell中执行
scp -r C:\Users\cuigu\novel_writing_agent root@101.132.154.143:/root/
```

#### 2.2 方法2：使用Git克隆

```bash
# 在服务器上执行
git clone <your-repository-url> /root/novel_writing_agent
cd /root/novel_writing_agent
```

#### 2.3 方法3：使用SFTP工具

使用WinSCP、FileZilla等SFTP工具上传整个项目目录到服务器的 `/root/novel_writing_agent/`

### 步骤3：配置环境变量

#### 3.1 检查环境变量文件

```bash
# SSH登录服务器
ssh root@101.132.154.143

# 进入项目目录
cd /root/novel_writing_agent

# 检查环境变量文件
ls -la backend/.env
ls -la .env
```

#### 3.2 修改生产环境配置

编辑 `backend/.env` 文件，确保以下配置正确：

```bash
# 生产环境必须修改的配置
DEBUG=False
JWT_SECRET=<生成新的强随机密钥>

# 数据库配置（Docker环境）
DATABASE_URL=postgresql://novel_user:NovelPostgres0t649OyRUaI@postgres:5432/novel_db

# Redis配置（Docker环境）
REDIS_URL=redis://:NovelRedis2024!@redis:6379/0

# CORS配置（生产环境）
CORS_ORIGINS=["https://sggf.net", "https://www.sggf.net"]
```

**生成JWT密钥**：
```bash
openssl rand -hex 32
```

### 步骤4：准备SSL证书

#### 4.1 检查SSL证书

```bash
# 检查SSL证书目录
ls -la ssl/

# 应该看到：
# cert.pem
# key.pem
```

#### 4.2 使用Let's Encrypt免费证书（可选）

如果需要免费SSL证书：

```bash
# 安装certbot
yum install -y certbot

# 获取证书
certbot certonly --standalone -d sggf.net -d www.sggf.net

# 复制证书到项目目录
cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem
```

### 步骤5：执行部署脚本

#### 5.1 赋予执行权限

```bash
chmod +x deploy.sh
```

#### 5.2 执行部署

```bash
./deploy.sh
```

部署脚本会自动完成以下操作：
1. ✅ 检查系统环境
2. ✅ 安装Docker
3. ✅ 安装Docker Compose
4. ✅ 配置防火墙
5. ✅ 创建项目目录
6. ✅ 检查项目文件
7. ✅ 停止旧容器
8. ✅ 启动服务
9. ✅ 健康检查

### 步骤6：验证部署

#### 6.1 检查服务状态

```bash
# 查看所有容器状态
docker-compose ps

# 应该看到所有服务都是 "Up" 状态
```

#### 6.2 查看服务日志

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres
docker-compose logs -f redis
```

#### 6.3 访问应用

在浏览器中访问：
- **HTTP**: http://sggf.net（会自动重定向到HTTPS）
- **HTTPS**: https://sggf.net
- **API**: https://sggf.net/api

#### 6.4 测试API

```bash
# 测试健康检查
curl https://sggf.net/health

# 测试API
curl https://sggf.net/api/v1/health
```

### 步骤7：数据库迁移（首次部署）

```bash
# 进入后端容器
docker-compose exec backend bash

# 执行数据库迁移
python -c "from app.db.session import engine; from app.db.base import Base; Base.metadata.create_all(bind=engine)"

# 退出容器
exit
```

---

## 🌐 其他云服务商部署

### 腾讯云

#### 1. 购买/配置CVM实例

**推荐配置**：
- CPU：2核或以上
- 内存：4GB或以上
- 操作系统：CentOS 7+ / Ubuntu 20.04+
- 带宽：5Mbps或以上

#### 2. 配置安全组

开放端口：22, 80, 443

#### 3. 配置域名解析

在腾讯云DNSPod添加A记录，指向服务器IP

#### 4. 上传项目并部署

使用与阿里云相同的部署流程

### AWS EC2

#### 1. 启动EC2实例

**推荐配置**：
- 实例类型：t3.medium或以上
- AMI：Ubuntu 20.04 LTS
- 存储：40GB GP3

#### 2. 配置安全组

开放端口：22, 80, 443

#### 3. 配置域名解析

在Route 53添加A记录

#### 4. 上传项目并部署

使用与阿里云相同的部署流程

### DigitalOcean

#### 1. 创建Droplet

**推荐配置**：
- 计划：Basic / $20/月 或以上
- 区域：选择距离用户最近的区域
- 操作系统：Ubuntu 22.04 LTS

#### 2. 配置防火墙

开放端口：22, 80, 443

#### 3. 配置域名解析

在DigitalOcean DNS添加A记录

#### 4. 上传项目并部署

使用与阿里云相同的部署流程

---

## ✅ 部署前准备

### 检查清单

- [ ] 已购买云服务器
- [ ] 已配置服务器安全组（开放80、443端口）
- [ ] 已配置域名解析（A记录指向服务器IP）
- [ ] 已准备SSL证书文件（cert.pem、key.pem）
- [ ] 已修改生产环境配置（JWT_SECRET、CORS_ORIGINS等）
- [ ] 已上传项目文件到服务器
- [ ] 已检查所有API密钥配置正确

### 环境变量检查

确保以下环境变量已正确配置：

```bash
# backend/.env
DEBUG=False
JWT_SECRET=<强随机密钥>
DATABASE_URL=postgresql://novel_user:NovelPostgres0t649OyRUaI@postgres:5432/novel_db
REDIS_URL=redis://:NovelRedis2024!@redis:6379/0
CORS_ORIGINS=["https://sggf.net", "https://www.sggf.net"]

# .env
DEEPSEEK_API_KEY=<你的DeepSeek API密钥>
DASHSCOPE_API_KEY=<你的阿里云百炼API密钥>
EMBEDDING_API_KEY=<你的Embedding API密钥>
```

---

## 🔍 部署后验证

### 1. 服务状态检查

```bash
# 查看所有容器状态
docker-compose ps

# 检查容器资源使用
docker stats
```

### 2. 日志检查

```bash
# 查看后端日志
docker-compose logs backend --tail=100

# 查看前端日志
docker-compose logs frontend --tail=100

# 查看Nginx日志
docker-compose logs nginx --tail=100
```

### 3. 功能测试

#### 3.1 前端访问

访问 https://sggf.net，检查：
- 页面是否正常加载
- 样式是否正确
- 功能是否可用

#### 3.2 API测试

```bash
# 健康检查
curl https://sggf.net/api/v1/health

# 用户注册
curl -X POST https://sggf.net/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"test@example.com","password":"test123456"}'

# 用户登录
curl -X POST https://sggf.net/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test123456"}'
```

#### 3.3 WebSocket测试

```bash
# 测试WebSocket连接
wscat -c wss://sggf.net/ws
```

### 4. 性能测试

```bash
# 使用ab进行压力测试
ab -n 1000 -c 10 https://sggf.net/
```

---

## 🛠️ 常见问题

### 问题1：Docker安装失败

**解决方案**：
```bash
# 清理旧版本
yum remove docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine

# 重新安装
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
systemctl start docker
systemctl enable docker
```

### 问题2：容器启动失败

**解决方案**：
```bash
# 查看容器日志
docker-compose logs backend

# 检查端口占用
netstat -tlnp | grep -E ':(8000|3000|5432|6379)'

# 重新构建容器
docker-compose build --no-cache backend
docker-compose up -d backend
```

### 问题3：数据库连接失败

**解决方案**：
```bash
# 检查PostgreSQL容器状态
docker-compose ps postgres

# 查看PostgreSQL日志
docker-compose logs postgres

# 进入PostgreSQL容器测试连接
docker-compose exec postgres psql -U novel_user -d novel_db -c "SELECT 1"
```

### 问题4：SSL证书错误

**解决方案**：
```bash
# 检查证书文件
ls -la ssl/
cat ssl/cert.pem
cat ssl/key.pem

# 检查证书有效期
openssl x509 -in ssl/cert.pem -noout -dates

# 重新加载Nginx
docker-compose restart nginx
```

### 问题5：前端无法访问后端API

**解决方案**：
```bash
# 检查CORS配置
cat backend/.env | grep CORS_ORIGINS

# 检查Nginx配置
cat nginx.conf

# 检查后端服务状态
docker-compose ps backend
curl http://localhost:8000/api/v1/health
```

### 问题6：WebSocket连接失败

**解决方案**：
```bash
# 检查Nginx WebSocket配置
cat nginx.conf | grep -A 10 "location /ws/"

# 检查后端WebSocket服务
docker-compose logs backend | grep -i websocket

# 测试WebSocket连接
wscat -c ws://localhost:8000/ws
```

### 问题7：API限流错误

**解决方案**：
```bash
# 检查限流配置
cat backend/.env | grep -i rate

# 查看限流日志
docker-compose logs backend | grep -i rate

# 调整限流配置（在backend/.env中）
# RATE_LIMIT_ENABLED=false
```

---

## 📊 管理命令

### 服务管理

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose stop

# 重启服务
docker-compose restart

# 停止并删除容器
docker-compose down

# 重新构建并启动
docker-compose up -d --build
```

### 日志管理

```bash
# 查看所有日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend

# 查看最近100行日志
docker-compose logs --tail=100 backend
```

### 数据库管理

```bash
# 进入PostgreSQL容器
docker-compose exec postgres psql -U novel_user -d novel_db

# 备份数据库
docker-compose exec postgres pg_dump -U novel_user novel_db > backup.sql

# 恢复数据库
docker-compose exec -T postgres psql -U novel_user novel_db < backup.sql
```

### Redis管理

```bash
# 进入Redis容器
docker-compose exec redis redis-cli -a NovelRedis2024!

# 清空Redis缓存
docker-compose exec redis redis-cli -a NovelRedis2024! FLUSHALL
```

---

## 🔒 安全建议

### 1. 修改默认密码

```bash
# 生成强密码
openssl rand -base64 32

# 修改docker-compose.yml中的密码
# POSTGRES_PASSWORD=<新密码>
# Redis密码: redis-server --requirepass <新密码>
```

### 2. 限制SSH访问

```bash
# 编辑SSH配置
vi /etc/ssh/sshd_config

# 修改以下配置
Port 2222  # 修改默认端口
PermitRootLogin no  # 禁止root登录
PasswordAuthentication no  # 禁用密码登录

# 重启SSH服务
systemctl restart sshd
```

### 3. 配置防火墙

```bash
# 只开放必要端口
firewall-cmd --permanent --add-port=2222/tcp  # SSH
firewall-cmd --permanent --add-port=80/tcp   # HTTP
firewall-cmd --permanent --add-port=443/tcp  # HTTPS
firewall-cmd --reload
```

### 4. 定期更新

```bash
# 更新系统
yum update -y

# 更新Docker
yum update docker-ce -y

# 更新Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
```

---

## 📈 监控和优化

### 1. 资源监控

```bash
# 查看容器资源使用
docker stats

# 查看磁盘使用
df -h

# 查看内存使用
free -h
```

### 2. 日志轮转

```bash
# 配置Docker日志轮转
vi /etc/docker/daemon.json

# 添加以下配置
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}

# 重启Docker
systemctl restart docker
```

### 3. 性能优化

```bash
# 调整Docker资源限制（在docker-compose.yml中）
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 4G
    reservations:
      cpus: '1'
      memory: 2G
```

---

## 📞 技术支持

如遇到问题，请：

1. 查看本文档的"常见问题"部分
2. 检查服务日志：`docker-compose logs -f`
3. 查看容器状态：`docker-compose ps`
4. 检查环境变量配置：`cat backend/.env`

---

## 📝 更新日志

- 2026-02-07：创建云端部署指南
- 包含阿里云ECS、腾讯云、AWS、DigitalOcean部署方案
- 添加完整的部署前准备和部署后验证流程
- 添加常见问题解决方案和安全管理建议