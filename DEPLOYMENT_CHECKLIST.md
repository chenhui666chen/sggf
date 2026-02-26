# 云端部署检查清单

## 📋 部署前检查清单

### 服务器配置
- [ ] 已购买云服务器（阿里云ECS / 腾讯云CVM / AWS EC2 / DigitalOcean等）
- [ ] 服务器配置满足最低要求（2核CPU、4GB内存、40GB存储）
- [ ] 已配置服务器安全组，开放80、443端口
- [ ] 已配置SSH访问（端口22，建议限制IP）

### 域名配置
- [ ] 已拥有域名（sggf.net）
- [ ] 已配置DNS解析，A记录指向服务器IP（101.132.154.143）
- [ ] 已配置www子域名的A记录
- [ ] DNS解析已生效（使用 `nslookup sggf.net` 或 `dig sggf.net` 验证）

### SSL证书
- [ ] 已准备SSL证书文件（cert.pem、key.pem）
- [ ] SSL证书有效（使用 `openssl x509 -in ssl/cert.pem -noout -dates` 验证）
- [ ] SSL证书域名匹配（sggf.net 和 www.sggf.net）
- [ ] SSL证书文件已放置在项目目录的ssl/文件夹中

### 项目文件
- [ ] docker-compose.yml 文件存在
- [ ] backend/Dockerfile 文件存在
- [ ] frontend/Dockerfile 文件存在
- [ ] nginx.conf 文件存在
- [ ] deploy.sh 部署脚本存在
- [ ] 所有必需的目录和文件都已上传到服务器

### 环境变量配置
- [ ] backend/.env 文件存在
- [ ] .env 文件存在
- [ ] DEBUG=False（生产环境）
- [ ] JWT_SECRET已设置为强随机密钥（使用 `openssl rand -hex 32` 生成）
- [ ] DATABASE_URL配置正确（Docker环境：`postgresql://novel_user:NovelPostgres0t649OyRUaI@postgres:5432/novel_db`）
- [ ] REDIS_URL配置正确（Docker环境：`redis://:NovelRedis2024!@redis:6379/0`）
- [ ] CORS_ORIGINS配置正确（生产环境：`["https://sggf.net", "https://www.sggf.net"]`）
- [ ] 所有API密钥已配置正确（DEEPSEEK_API_KEY、DASHSCOPE_API_KEY等）

### API密钥检查
- [ ] DeepSeek API密钥已配置（DEEPSEEK_API_KEY）
- [ ] 阿里云百炼API密钥已配置（DASHSCOPE_API_KEY）
- [ ] Embedding API密钥已配置（EMBEDDING_API_KEY）
- [ ] 腾讯云API密钥已配置（TENCENT_SECRET_ID、TENCENT_SECRET_KEY）
- [ ] Mureka API密钥已配置（MUREKA_API_KEY）
- [ ] 可灵AI密钥已配置（KLINGAI_ACCESS_KEY、KLINGAI_SECRET_KEY）
- [ ] 所有API密钥有效且有足够的配额

### 数据库配置
- [ ] PostgreSQL密码已设置（NovelPostgres0t649OyRUaI）
- [ ] PostgreSQL用户已创建（novel_user）
- [ ] PostgreSQL数据库已创建（novel_db）
- [ ] 数据库连接池配置正确（DB_POOL_SIZE、DB_MAX_OVERFLOW等）

### Redis配置
- [ ] Redis密码已设置（NovelRedis2024!）
- [ ] Redis持久化已启用（appendonly yes）
- [ ] Redis健康检查已配置

### Nginx配置
- [ ] nginx.conf 文件配置正确
- [ ] SSL证书路径配置正确（/etc/nginx/ssl/cert.pem、/etc/nginx/ssl/key.pem）
- [ ] 上游服务器配置正确（backend:8000、frontend:3000）
- [ ] WebSocket代理配置正确（/ws/ 路径）
- [ ] HTTP到HTTPS重定向已配置

### 防火墙配置
- [ ] 防火墙已开放80端口（HTTP）
- [ ] 防火墙已开放443端口（HTTPS）
- [ ] 防火墙已开放22端口（SSH，建议限制IP）
- [ ] 其他不必要的端口已关闭

### Docker配置
- [ ] Docker已安装
- [ ] Docker服务已启动
- [ ] Docker Compose已安装
- [ ] Docker服务已设置为开机自启
- [ ] 当前用户有Docker执行权限

### 备份准备
- [ ] 已准备数据库备份策略
- [ ] 已准备文件备份策略
- [ ] 已准备配置文件备份策略
- [ ] 已准备恢复流程文档

---

## 🚀 部署步骤

### 方法1：使用Windows部署脚本（推荐）

1. **打开命令提示符或PowerShell**
   ```bash
   cd C:\Users\cuigu\novel_writing_agent
   ```

2. **运行部署脚本**
   ```bash
   deploy_to_cloud.bat
   ```

3. **等待部署完成**
   - 脚本会自动上传文件
   - 自动执行部署脚本
   - 自动检查服务状态

### 方法2：手动部署

1. **上传项目文件**
   ```bash
   scp -r C:\Users\cuigu\novel_writing_agent root@101.132.154.143:/root/
   ```

2. **SSH登录服务器**
   ```bash
   ssh root@101.132.154.143
   ```

3. **进入项目目录**
   ```bash
   cd /root/novel_writing_agent
   ```

4. **执行部署脚本**
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```

---

## ✅ 部署后验证

### 服务状态检查
- [ ] 所有容器状态为 "Up"（`docker-compose ps`）
- [ ] PostgreSQL容器健康状态为 "healthy"
- [ ] Redis容器健康状态为 "healthy"
- [ ] Backend容器正常运行
- [ ] Frontend容器正常运行
- [ ] Nginx容器正常运行

### 日志检查
- [ ] Backend日志无错误（`docker-compose logs backend`）
- [ ] Frontend日志无错误（`docker-compose logs frontend`）
- [ ] PostgreSQL日志无错误（`docker-compose logs postgres`）
- [ ] Redis日志无错误（`docker-compose logs redis`）
- [ ] Nginx日志无错误（`docker-compose logs nginx`）

### 功能测试
- [ ] 可以访问 https://sggf.net
- [ ] 页面正常加载，样式正确
- [ ] 可以访问 https://www.sggf.net
- [ ] API健康检查正常（`curl https://sggf.net/api/v1/health`）
- [ ] 用户注册功能正常
- [ ] 用户登录功能正常
- [ ] WebSocket连接正常

### 性能测试
- [ ] 页面加载时间正常（<3秒）
- [ ] API响应时间正常（<1秒）
- [ ] 并发访问测试正常
- [ ] 服务器资源使用正常（CPU <80%，内存 <80%）

---

## 🔒 安全检查

### 密码安全
- [ ] 所有默认密码已修改
- [ ] JWT_SECRET已设置为强随机密钥
- [ ] PostgreSQL密码足够复杂
- [ ] Redis密码足够复杂
- [ ] 所有密码已妥善保管

### SSH安全
- [ ] SSH端口已修改（建议改为非默认端口）
- [ ] Root登录已禁用（建议）
- [ ] 密码登录已禁用（建议使用密钥登录）
- [ ] SSH访问已限制IP（建议）

### 防火墙安全
- [ ] 只开放必要的端口（80、443）
- [ ] SSH端口已限制IP（建议）
- [ ] 其他不必要的端口已关闭

### SSL/TLS安全
- [ ] 使用TLS 1.2或以上
- [ ] SSL证书有效且未过期
- [ ] 使用强加密套件
- [ ] HSTS已启用（建议）

---

## 📊 监控和维护

### 监控设置
- [ ] 服务器资源监控已设置
- [ ] 应用性能监控已设置
- [ ] 错误日志监控已设置
- [ ] 告警通知已设置

### 备份策略
- [ ] 数据库自动备份已配置
- [ ] 文件自动备份已配置
- [ ] 配置文件自动备份已配置
- [ ] 备份恢复测试已完成

### 更新策略
- [ ] 系统更新策略已制定
- [ ] Docker更新策略已制定
- [ ] 应用更新策略已制定
- [ ] 安全补丁更新策略已制定

---

## 📞 故障排查

### 常见问题检查

#### 容器启动失败
- [ ] 检查容器日志（`docker-compose logs <service>`）
- [ ] 检查端口占用（`netstat -tlnp`）
- [ ] 检查磁盘空间（`df -h`）
- [ ] 检查内存使用（`free -h`）

#### 数据库连接失败
- [ ] 检查PostgreSQL容器状态
- [ ] 检查数据库连接字符串
- [ ] 检查数据库用户权限
- [ ] 检查防火墙规则

#### API访问失败
- [ ] 检查Nginx配置
- [ ] 检查Backend容器状态
- [ ] 检查CORS配置
- [ ] 检查API日志

#### WebSocket连接失败
- [ ] 检查Nginx WebSocket配置
- [ ] 检查Backend WebSocket服务
- [ ] 检查防火墙规则
- [ ] 检查SSL证书

---

## 📝 部署记录

### 部署信息
- **部署日期**: ___________
- **部署人员**: ___________
- **服务器IP**: 101.132.154.143
- **域名**: sggf.net
- **部署方法**: □ Windows脚本 □ 手动部署

### 服务器信息
- **云服务商**: ___________
- **服务器类型**: ___________
- **CPU**: ___________
- **内存**: ___________
- **存储**: ___________
- **操作系统**: ___________

### 配置信息
- **JWT_SECRET**: ___________
- **PostgreSQL密码**: ___________
- **Redis密码**: ___________
- **SSH端口**: ___________

### 部署结果
- **部署状态**: □ 成功 □ 失败
- **所有容器状态**: □ 正常 □ 异常
- **功能测试**: □ 通过 □ 失败
- **性能测试**: □ 通过 □ 失败

### 备注
_________________________________________________________________________
_________________________________________________________________________
_________________________________________________________________________

---

## 📚 相关文档

- [云端部署指南](./CLOUD_DEPLOYMENT_GUIDE.md)
- [阿里云百炼API限流处理方案](./ALIYUN_RATE_LIMIT_SOLUTION.md)
- [阿里云百炼提示词优化总结](./ALIYUN_PROMPT_OPTIMIZATION_SUMMARY.md)

---

## 💡 提示

1. **首次部署建议**：在测试环境先完成部署和测试，确认无误后再部署到生产环境
2. **备份重要**：部署前务必备份所有配置文件和数据
3. **逐步验证**：部署完成后逐步验证各项功能，确保所有功能正常
4. **监控告警**：部署完成后设置监控和告警，及时发现和解决问题
5. **定期维护**：定期更新系统和应用，保持系统安全和稳定