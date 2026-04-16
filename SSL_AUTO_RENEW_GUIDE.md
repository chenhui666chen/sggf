# SSL 证书自动续期配置指南

## 📋 证书信息

- **域名**: sggf.net
- **证书类型**: Let's Encrypt (ECDSA)
- **有效期**: 90 天
- **当前过期时间**: 2026-05-08
- **剩余天数**: 56 天

## ✅ 自动续期配置

### 配置状态
- ✅ Certbot 已安装 (版本 5.3.0)
- ✅ Cron 服务已启动
- ✅ 自动续期任务已配置

### Cron 任务内容

```bash
0 0,12 * * * certbot renew --quiet --post-hook 'cd /data/apps/novel_writing_agent && cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem && cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem && docker-compose restart nginx'
```

### 执行时间
- 每天执行两次：午夜 0:00 和中午 12:00
- certbot 会自动判断是否需要续期（仅在证书过期前 30 天内才会实际续期）

### 续期流程
1. certbot 检查证书是否需要续期
2. 如果需要，自动向 Let's Encrypt 申请新证书
3. 复制新证书到项目 ssl 目录
4. 重启 nginx 容器使新证书生效

## 🔍 验证命令

### 查看已配置的 cron 任务
```bash
crontab -l
```

### 查看证书列表和过期时间
```bash
certbot certificates
```

### 手动测试续期（不会实际续期，仅测试）
```bash
certbot renew --dry-run
```

### 查看 cron 日志
```bash
grep CRON /var/log/cron
```

### 手动执行续期命令
```bash
cd /data/apps/novel_writing_agent
cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem
cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem
docker-compose restart nginx
```

## 📁 证书路径

| 类型 | Let's Encrypt 路径 | 项目路径 |
|------|-------------------|----------|
| 完整证书 | `/etc/letsencrypt/live/sggf.net/fullchain.pem` | `/data/apps/novel_writing_agent/ssl/cert.pem` |
| 私钥 | `/etc/letsencrypt/live/sggf.net/privkey.pem` | `/data/apps/novel_writing_agent/ssl/key.pem` |

## 🔧 Nginx SSL 配置

Nginx 容器挂载了以下 SSL 证书文件：
- `./ssl/cert.pem:/etc/nginx/ssl/cert.pem`
- `./ssl/key.pem:/etc/nginx/ssl/key.pem`

## ⚠️ 注意事项

1. **证书过期前 30 天**：certbot 会自动续期
2. **续期后**：nginx 会自动重启加载新证书
3. **监控提醒**：建议设置证书过期提醒（过期前 7 天）
4. **手动干预**：如果自动续期失败，需要手动执行续期命令

## 🚨 故障排查

### 如果证书过期
1. 手动续期：
   ```bash
   certbot renew --force-renewal
   ```
2. 复制证书：
   ```bash
   cp /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem
   cp /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem
   ```
3. 重启 nginx：
   ```bash
   docker-compose restart nginx
   ```

### 如果 cron 未运行
```bash
service cron start
# 或
systemctl start crond
```

## 📊 配置时间

- **配置时间**: 2026-03-13
- **配置状态**: ✅ 已完成
- **下次检查时间**: 2026-03-14 00:00
