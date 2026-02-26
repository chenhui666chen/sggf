# 快速部署指南

## 🚀 一键部署（推荐）

### Windows用户

1. **打开命令提示符或PowerShell**
   ```bash
   cd C:\Users\cuigu\novel_writing_agent
   ```

2. **运行部署脚本**
   ```bash
   deploy_to_cloud.bat
   ```

3. **等待部署完成**
   - 脚本会自动上传文件到服务器
   - 自动执行部署脚本
   - 自动检查服务状态

4. **访问应用**
   - 打开浏览器访问：https://sggf.net

---

## 📋 部署前准备（5分钟）

### 1. 检查服务器配置

确保您的阿里云ECS服务器已配置：
- ✅ 安全组开放80、443端口
- ✅ 域名sggf.net已解析到服务器IP（101.132.154.143）

### 2. 检查本地文件

确保以下文件存在：
- ✅ `docker-compose.yml`
- ✅ `backend/.env`
- ✅ `ssl/cert.pem`
- ✅ `ssl/key.pem`

### 3. 修改生产环境配置

编辑 `backend/.env`，确保以下配置正确：
```bash
DEBUG=False
JWT_SECRET=<生成新的强随机密钥>
CORS_ORIGINS=["https://sggf.net", "https://www.sggf.net"]
```

**生成JWT密钥**：
```bash
openssl rand -hex 32
```

---

## 🛠️ 手动部署（10分钟）

### 步骤1：上传项目文件

```bash
scp -r C:\Users\cuigu\novel_writing_agent root@101.132.154.143:/root/
```

### 步骤2：SSH登录服务器

```bash
ssh root@101.132.154.143
```

### 步骤3：执行部署脚本

```bash
cd /root/novel_writing_agent
chmod +x deploy.sh
./deploy.sh
```

### 步骤4：验证部署

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 测试API
curl https://sggf.net/api/v1/health
```

---

## ✅ 部署后验证

### 1. 检查服务状态

```bash
docker-compose ps
```

所有服务应该都是 "Up" 状态。

### 2. 访问应用

在浏览器中访问：
- **HTTP**: http://sggf.net（会自动重定向到HTTPS）
- **HTTPS**: https://sggf.net
- **API**: https://sggf.net/api

### 3. 测试功能

- ✅ 页面正常加载
- ✅ 用户注册/登录功能正常
- ✅ API调用正常
- ✅ WebSocket连接正常

---

## 🔧 常用管理命令

### 查看日志
```bash
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs -f"
```

### 停止服务
```bash
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose stop"
```

### 重启服务
```bash
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose restart"
```

### 查看状态
```bash
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"
```

---

## 📚 详细文档

- [完整部署指南](./CLOUD_DEPLOYMENT_GUIDE.md)
- [部署检查清单](./DEPLOYMENT_CHECKLIST.md)

---

## ❓ 遇到问题？

### 问题1：SCP命令未找到
**解决方案**：安装Git Bash或OpenSSH客户端

### 问题2：部署脚本执行失败
**解决方案**：
```bash
ssh root@101.132.154.143
cd /root/novel_writing_agent
./deploy.sh
```

### 问题3：容器启动失败
**解决方案**：
```bash
ssh root@101.132.154.143
cd /root/novel_writing_agent
docker-compose logs backend
```

### 问题4：无法访问网站
**解决方案**：
1. 检查域名解析：`nslookup sggf.net`
2. 检查安全组配置
3. 检查防火墙配置
4. 查看Nginx日志：`docker-compose logs nginx`

---

## 💡 提示

1. **首次部署**：建议在测试环境先完成部署和测试
2. **备份重要**：部署前务必备份所有配置文件
3. **逐步验证**：部署完成后逐步验证各项功能
4. **监控告警**：部署完成后设置监控和告警

---

## 📞 技术支持

如遇到问题，请：
1. 查看[完整部署指南](./CLOUD_DEPLOYMENT_GUIDE.md)
2. 查看[部署检查清单](./DEPLOYMENT_CHECKLIST.md)
3. 检查服务日志：`docker-compose logs -f`
4. 检查容器状态：`docker-compose ps`

---

**部署时间估算**：
- 一键部署：5-10分钟
- 手动部署：10-15分钟
- 首次部署（包含测试）：30分钟-1小时