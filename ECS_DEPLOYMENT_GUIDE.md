# 阿里云ECS部署指南

## 📋 部署前准备

### 服务器信息
- **实例ID**: i-uf63o8jyxhjc6sx2bhg3
- **公网IP**: 101.132.154.143
- **私网IP**: 172.25.81.103
- **地域**: 华东2（上海）
- **规格**: 2核8GB

### 数据库配置
- **类型**: PostgreSQL 15-alpine (Docker)
- **用户**: novel_user
- **密码**: NovelPostgres0t649OyRUaI
- **数据库**: novel_db

### Redis配置
- **类型**: Redis 7-alpine (Docker)
- **密码**: NovelRedis2024!
- **端口**: 6379

### 域名配置
- **域名**: sggf.net
- **SSL**: 已配置（cert.pem, key.pem）

---

## 🚀 部署步骤

### 第一步：上传项目文件到ECS

#### 方法1：使用SCP上传（推荐）
```bash
# 在本地Windows PowerShell中执行
scp -r C:\Users\cuigu\novel_writing_agent root@101.132.154.143:/root/
```

#### 方法2：使用Git克隆
```bash
# 在ECS上执行
ssh root@101.132.154.143
cd /root
git clone <your-repo-url>
cd novel_writing_agent
```

### 第二步：执行部署脚本

```bash
# SSH连接到ECS
ssh root@101.132.154.143

# 进入项目目录
cd /root/novel_writing_agent

# 赋予执行权限
chmod +x deploy.sh

# 执行部署脚本
./deploy.sh
```

### 第三步：配置阿里云安全组

1. 登录阿里云控制台
2. 进入"云服务器ECS" -> "安全组"
3. 找到实例的安全组，点击"配置规则"
4. 添加入站规则：

| 协议类型 | 端口范围 | 授权对象 | 描述 |
|----------|----------|----------|------|
| TCP | 80/80 | 0.0.0.0/0 | HTTP |
| TCP | 443/443 | 0.0.0.0/0 | HTTPS |
| TCP | 8000/8000 | 0.0.0.0/0 | Backend API（可选） |

### 第四步：配置域名解析

1. 登录域名管理控制台
2. 添加A记录：

| 主机记录 | 记录类型 | 记录值 | TTL |
|---------|----------|---------|-----|
| @ | A | 101.132.154.143 | 600 |
| www | A | 101.132.154.143 | 600 |

### 第五步：执行数据库迁移

```bash
# 在ECS上执行
cd /root/novel_writing_agent

# 赋予执行权限
chmod +x migrate.sh

# 执行迁移脚本
./migrate.sh
```

**重要提示：**
- 迁移会修改数据库表结构
- 脚本会自动备份数据库到 `/root/backups/`
- 如需回滚，执行：`docker-compose exec backend alembic downgrade base`

---

## 📊 服务架构

```
阿里云ECS (101.132.154.143)
├── PostgreSQL (Docker)
│   ├── 端口: 5432
│   ├── 用户: novel_user
│   └── 密码: NovelPostgres0t649OyRUaI
├── Redis (Docker)
│   ├── 端口: 6379
│   └── 密码: NovelRedis2024!
├── Backend (Docker)
│   ├── 端口: 8000
│   ├── 容器名: novel_backend
│   └── 工作进程: 2
├── Frontend (Docker)
│   ├── 端口: 3000
│   ├── 容器名: novel_frontend
│   └── 构建: React
└── Nginx (Docker)
    ├── 端口: 80, 443
    ├── 容器名: novel_nginx
    └── SSL: 已配置
```

---

## 🔧 管理命令

### 查看服务状态
```bash
cd /root/novel_writing_agent
docker-compose ps
```

### 查看日志
```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f nginx
```

### 重启服务
```bash
# 重启所有服务
docker-compose restart

# 重启特定服务
docker-compose restart backend
docker-compose restart frontend
docker-compose restart nginx
```

### 停止服务
```bash
docker-compose down
```

### 启动服务
```bash
docker-compose up -d
```

### 更新代码
```bash
# 1. 拉取最新代码
cd /root/novel_writing_agent
git pull

# 2. 重新构建并启动
docker-compose up -d --build

# 3. 清理旧镜像（可选）
docker image prune -f
```

---

## 🔍 故障排查

### 问题1：容器启动失败

**检查日志：**
```bash
docker-compose logs backend
docker-compose logs frontend
```

**常见原因：**
- 端口被占用
- 内存不足
- 配置文件错误

**解决方案：**
```bash
# 检查端口占用
netstat -tunlp | grep -E ':(80|443|8000|3000|5432|6379)'

# 检查内存使用
free -h

# 检查磁盘空间
df -h
```

### 问题2：数据库连接失败

**检查PostgreSQL状态：**
```bash
docker-compose exec postgres pg_isready -U novel_user
```

**测试连接：**
```bash
docker-compose exec backend python -c "
from app.db.base import engine
engine.connect()
print('数据库连接成功')
"
```

### 问题3：无法访问网站

**检查Nginx配置：**
```bash
docker-compose exec nginx nginx -t
```

**检查防火墙：**
```bash
firewall-cmd --list-all
```

**检查安全组：**
- 确认阿里云安全组已开放80、443端口
- 确认安全组规则允许0.0.0.0/0访问

### 问题4：SSL证书错误

**检查证书文件：**
```bash
ls -la /root/novel_writing_agent/ssl/
```

**检查证书有效期：**
```bash
openssl x509 -in /root/novel_writing_agent/ssl/cert.pem -noout -dates
```

---

## 📈 性能优化

### 资源限制

当前配置已针对2核8GB服务器优化：

| 服务 | CPU限制 | 内存限制 | 预留资源 |
|------|---------|---------|----------|
| PostgreSQL | 1核 | 2GB | 0.5核/1GB |
| Redis | 0.5核 | 0.5GB | 0.2核/0.2GB |
| Backend | 1核 | 2GB | 0.5核/1GB |
| Frontend | 0.5核 | 0.5GB | 0.3核/0.2GB |
| Nginx | 0.2核 | 0.2GB | 0.1核/0.1GB |
| **总计** | **3.2核** | **5.2GB** | **1.6核/2.5GB** |

**剩余资源：约 0.4核 / 2.8GB（充足）**

### 数据库优化

PostgreSQL已配置以下优化：
- 连接池大小：20
- 最大溢出连接：10
- 连接超时：30秒
- 连接回收：3600秒
- 预检查：启用

### 缓存优化

Redis已配置：
- 持久化：AOF模式
- 密码保护：已启用
- 健康检查：已配置

---

## 🔒 安全建议

### 1. 修改默认密码

**PostgreSQL密码：**
```bash
# 生成新密码
openssl rand -base64 32

# 修改docker-compose.yml中的POSTGRES_PASSWORD
# 修改backend/.env中的DATABASE_URL
```

**Redis密码：**
```bash
# 生成新密码
openssl rand -base64 32

# 修改docker-compose.yml中的requirepass
# 修改backend/.env中的REDIS_URL
```

**JWT密钥：**
```bash
# 生成新密钥
openssl rand -hex 32

# 修改docker-compose.yml中的JWT_SECRET
```

### 2. 配置防火墙

```bash
# 只允许必要端口
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --reload
```

### 3. 启用fail2ban（可选）

```bash
# 安装fail2ban
yum install -y fail2ban

# 配置fail2ban
systemctl enable fail2ban
systemctl start fail2ban
```

---

## 📊 监控建议

### 1. 容器监控

```bash
# 查看容器资源使用
docker stats
```

### 2. 日志监控

```bash
# 查看实时日志
docker-compose logs -f --tail=100
```

### 3. 健康检查

```bash
# 检查服务健康状态
curl http://localhost:8000/health
curl https://sggf.net/health
```

---

## 🔄 更新部署

### 更新代码

```bash
cd /root/novel_writing_agent
git pull
docker-compose up -d --build
```

### 更新数据库

```bash
cd /root/novel_writing_agent
./migrate.sh
```

### 回滚版本

```bash
cd /root/novel_writing_agent
git log --oneline
git checkout <commit-hash>
docker-compose up -d --build
```

---

## 📞 技术支持

### 日志位置

- **应用日志**: `/root/novel_writing_agent/backend/logs/`
- **Nginx日志**: 容器内 `/var/log/nginx/`
- **数据库备份**: `/root/backups/`

### 常用命令

```bash
# SSH连接
ssh root@101.132.154.143

# 查看系统资源
htop

# 查看磁盘使用
df -h

# 查看内存使用
free -h

# 查看网络连接
netstat -tunlp
```

---

## ✅ 部署检查清单

- [ ] 项目文件已上传到ECS
- [ ] Docker和Docker Compose已安装
- [ ] 防火墙已配置（80、443端口）
- [ ] 阿里云安全组已配置
- [ ] 域名已解析到服务器IP
- [ ] SSL证书已准备
- [ ] 数据库迁移已执行
- [ ] 服务健康检查通过
- [ ] 网站可正常访问

---

## 📞 联系方式

如有问题，请检查：
1. [部署日志](#故障排查)
2. [服务状态](#管理命令)
3. [常见问题](#故障排查)

---

**部署版本**: 1.0.0
**更新时间**: 2026-01-20
**服务器**: 阿里云ECS (华东2-上海)
