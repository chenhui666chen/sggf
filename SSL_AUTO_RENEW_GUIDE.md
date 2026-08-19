# SSL 证书自动续期配置指南

## 🏗️ 双域名架构总览

本项目涉及两个独立域名的 HTTPS 证书，托管位置与续期机制完全不同：

| 域名 | 托管位置 | 证书来源 | 续期机制 | 状态 |
|------|---------|---------|---------|------|
| `sggf.net`（主站） | 自建服务器 nginx（101.132.154.143） | Let's Encrypt | certbot webroot + cron（每天 0:00 / 12:00） | ✅ 自动续期正常 |
| `audio.sggf.net`（音频库） | 阿里云 OSS 自定义域名（bucket `sggf-audio-library`） | Let's Encrypt | certbot DNS-01 签发 → CAS 上传 → OSS 重绑定 + cron（每天 01:30） | ✅ 自动续期正常 |

> ⚠️ **历史教训**：audio.sggf.net 此前绑定的是阿里云 DigiCert 免费证书，**绑定 OSS 后不自动续期**，曾于 2026-08-06 过期导致音频库 HTTPS 长时间不可用（`curl` 报证书过期）。2026-08-11 已迁移到 Let's Encrypt 并落地全自动续期。

---

## 一、sggf.net（主站）

### 📋 证书信息

- **域名**: sggf.net
- **证书类型**: Let's Encrypt (ECDSA)
- **有效期**: 90 天
- **当前过期时间**: 2026-09-23（certbot 会在到期前 30 天自动续期）
- **签发方式**: webroot 验证（HTTP-01）

### ✅ 自动续期配置

- Certbot 5.3.0 已安装，cron 服务已启动
- Cron 任务（每天 0:00 / 12:00 各执行一次，certbot 自行判断是否到期）：

```bash
0 0,12 * * * certbot renew --quiet --no-random-sleep-on-renew --deploy-hook 'cd /data/apps/novel_writing_agent && cp -f /etc/letsencrypt/live/sggf.net/fullchain.pem ssl/cert.pem && cp -f /etc/letsencrypt/live/sggf.net/privkey.pem ssl/key.pem && chmod 644 ssl/cert.pem && chmod 600 ssl/key.pem && docker-compose up -d --force-recreate nginx'
```

### 📁 证书路径

| 类型 | Let's Encrypt 路径 | 项目路径 |
|------|-------------------|----------|
| 完整证书 | `/etc/letsencrypt/live/sggf.net/fullchain.pem` | `/data/apps/novel_writing_agent/ssl/cert.pem` |
| 私钥 | `/etc/letsencrypt/live/sggf.net/privkey.pem` | `/data/apps/novel_writing_agent/ssl/key.pem` |

### 🔧 Nginx SSL 配置

Nginx 容器挂载 `./ssl/cert.pem` 与 `./ssl/key.pem`，续期后通过 deploy-hook 自动 `docker-compose up -d --force-recreate nginx` 加载新证书。

---

## 二、audio.sggf.net（OSS 音频库域名）

### 📋 证书信息

- **域名**: audio.sggf.net（含 www.audio.sggf.net），CNAME → `sggf-audio-library.cn-shanghai.taihangtop.cn`
- **证书类型**: Let's Encrypt (ECDSA)
- **有效期**: 90 天
- **当前过期时间**: 2026-11-09
- **签发方式**: DNS-01 验证（域名在阿里云云解析 hichina NS，通过 alidns API 自动添加/删除 TXT 记录）

### 🧩 续期链路（为何不能用 certbot 直接续期）

OSS 自定义域名的 HTTPS 证书由 OSS 服务端校验，不能像 nginx 一样直接加载 certbot 证书文件，必须走"上传到证书服务（CAS）→ 重绑定到 CNAME"链路：

```
certbot renew（DNS-01 签发新证书）
        ↓
aliyun cas UploadUserCertificate（上传到云盾证书，返回 CertId）
        ↓
oss2 list_bucket_cname（读取当前绑定的旧 cert_id 作为 previous_cert_id）
        ↓
oss2 put_bucket_cname（CertInfo(cert_id=新, previous_cert_id=旧) 重绑定）
```

### 📜 关键文件（服务器端）

| 文件 | 作用 |
|------|------|
| `/opt/oss_cert_renew.sh` | 自动续期总脚本（certbot renew → CAS 上传 → OSS 重绑定），日志 `/var/log/oss_cert_renew.log` |
| `/opt/dns_auth.sh` | certbot DNS-01 auth hook：alidns `AddDomainRecord` 自动添加 `_acme-challenge` TXT 记录，等待 30s 传播 |
| `/opt/dns_cleanup.sh` | certbot DNS-01 cleanup hook：按 `/tmp/dns_record_<域名>` 记录的 RecordId 删除 TXT 记录 |
| `/etc/letsencrypt/live/audio.sggf.net/` | 证书存放路径（fullchain.pem / privkey.pem） |
| `/etc/letsencrypt/renewal/audio.sggf.net.conf` | certbot 续期配置（`authenticator = manual`，hooks 指向 /opt/） |

### ⏰ 自动续期

- Cron 任务（每天 01:30，证书到期前 30 天内才实际续期）：

```bash
30 1 * * * /opt/oss_cert_renew.sh
```

- 脚本核心要点：
  - 上传证书名称带时间戳 `audio-sggf-net-$(date +%Y%m%d-%H%M%S)`，防止同日重复运行报 `NameRepeat`
  - 从项目 `.env` 读取 OSS AK/SK（`AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID/SECRET`），注意加 `tr -d '\r'` 去除 CRLF
  - 重绑定必须传 `previous_cert_id`（当前绑定的旧证书 ID），否则报 `CasRenewCertificateConflict`
- 所需 RAM 权限（RAM 用户 `oss-bucket-put-object`）：`AliyunOSSFullAccess` + `AliyunYundunCertFullAccess` + `AliyunDNSFullAccess`

### 🔍 验证命令

```bash
# 查看自动续期任务
crontab -l | grep oss_cert

# 查看证书列表与过期时间
certbot certificates

# 查看续期日志（含上传 CertId / previous cert id / bind status）
tail -50 /var/log/oss_cert_renew.log

# 查看当前 CNAME 绑定的证书（应返回 cert_id 与到期时间）
python3 - <<'PYEOF'
import sys, oss2
# 从 .env 读取 AK/SK 后执行：
# bucket = oss2.Bucket(oss2.Auth(ak, sk), 'https://oss-cn-shanghai.aliyuncs.com', 'sggf-audio-library')
# r = bucket.list_bucket_cname()
# for c in r.cname: print(c.domain, c.certificate.cert_id, c.certificate.valid_end_date)
PYEOF

# 验证 HTTPS 实际可用
curl -vI https://audio.sggf.net/shared/audio_library/healthcheck.txt
```

### 🚨 故障排查

| 报错/现象 | 原因 | 处理 |
|----------|------|------|
| `CasRenewCertificateConflict` | 重绑定未传旧证书 ID | 先 `list_bucket_cname` 取当前 `cert_id`（含 `-cn-hangzhou` 后缀）作为 `previous_cert_id` |
| `NameRepeat` | 同名证书重复上传 | 证书名加时间戳 `%Y%m%d-%H%M%S` |
| `API.Forbidden` | cas API 未带区域 | 所有 `aliyun cas` 命令必须加 `--RegionId cn-hangzhou` |
| `InvalidAccessKeyId` | `.env` 提取的 AK/SK 带 CRLF | 提取时加 `tr -d '\r'` |
| `InsufficientQuota` | 阿里云免费证书额度耗尽 | 已改用 Let's Encrypt（服务器 certbot 直接签发），不再依赖阿里云免费证书 |
| 证书过期但 cron 没续 | 到期前 30 天内才会续期 | 手动执行 `/opt/oss_cert_renew.sh` 查看日志 |
| HTTPS 偶发 `000`（curl 超时） | OSS 节点响应抖动，TLS 正常 | 多测几次或稍后复测，非证书问题 |

---

## 📊 配置时间

- **sggf.net**：2026-03-13 配置，2026-08-11 复核（证书 2026-09-23 到期，机制正常）
- **audio.sggf.net**：2026-08-11 配置（由阿里云免费证书迁移至 Let's Encrypt），当前证书 2026-11-09 到期
