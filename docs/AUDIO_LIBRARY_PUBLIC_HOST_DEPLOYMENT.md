# 音频素材库公网域名部署说明

本文说明共享音乐库/音效库的公网访问域名配置。当前建议把 `audio.sggf.net` 作为独立素材域名，但必须先完成 DNS、证书和对象存储/CDN 映射验证，再启用后端配置。

## 当前结论

- `audio.sggf.net` 已绑定到自有 OSS Bucket `sggf-audio-library`，并已通过 `shared/audio_library/healthcheck.txt` 验证公网读取。
- 生产共享素材库应优先使用 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=aliyun_oss` 上传到自有 OSS，而不是继续依赖 DashScope 临时上传空间。
- `dashscope_oss` 仍保留为兼容过渡路径，但不应与 `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=https://audio.sggf.net` 混用；否则会把 DashScope 对象错误改写为自有 OSS 域名。
- 启用自定义公网域名后，只有带 `object_key` 或 `cloud_uri` 的云端素材才会动态切换为新域名；历史上只有旧 `public_url` 的记录不会被强行改写。

## 推荐架构

生产环境优先采用：

1. 自有对象存储或可绑定自定义域名的 CDN 作为共享音频文件存储层。
2. `audio.sggf.net` 作为独立素材域名，CNAME 到 CDN/OSS 提供的域名。
3. 后端数据库只保存素材元数据、授权信息、`cloud_uri`、`object_key` 和 `public_url`，不保存音频二进制。
4. 后端本地 `backend/data/audio_library/` 仅作为导入暂存、质量检测和混音缓存。

不建议让 FastAPI 长期反代大音频文件。后端反代会增加应用进程带宽和连接压力，也会让缓存、Range 请求、CDN 命中和下载限速更难控制。

## DNS 配置

如果使用 CDN/OSS：

```text
audio.sggf.net CNAME <cdn-or-oss-public-domain>
```

如果临时走服务器反代：

```text
audio.sggf.net A 101.132.154.143
```

服务器反代只适合过渡验证。正式使用前需要确认 Nginx 能正确映射到对象存储或静态素材目录，并支持音频 Range 请求。

## 启用前验证

在启用 `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST` 前，至少完成以下验证：

```powershell
Resolve-DnsName "audio.sggf.net"
curl.exe -I "https://audio.sggf.net/shared/audio_library/healthcheck.txt"
```

期望结果：

- DNS 能解析到 CDN/OSS 或服务器地址。
- HTTPS 证书覆盖 `audio.sggf.net`（证书续期机制见根目录 [SSL_AUTO_RENEW_GUIDE.md](../SSL_AUTO_RENEW_GUIDE.md) 的 audio.sggf.net 章节）。
- 测试对象返回 `200` 或 `206`。
- `Content-Type` 对音频文件正确。
- Range 请求可用，音频播放器可拖动进度。

## 后端配置

DNS 和公网访问验证通过后，再设置：

```env
AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=aliyun_oss
AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET=sggf-audio-library
AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX=shared/audio_library
AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=https://audio.sggf.net
AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID=<RAM access key id>
AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET=<RAM access key secret>
# 仅使用临时 STS 凭证时设置：
# AUDIOBOOK_AUDIO_LIBRARY_OSS_SECURITY_TOKEN=<STS security token>
```

Docker Compose 已支持从环境变量读取：

```yaml
AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET:-}
AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT:-}
AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID:-}
AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET:-}
AUDIOBOOK_AUDIO_LIBRARY_OSS_SECURITY_TOKEN: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_SECURITY_TOKEN:-}
AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST: ${AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST:-}
```

因此生产服务器只需要在部署环境中设置变量并重启后端、Celery 和 Nginx。

RAM 用户或角色建议只授予素材前缀的最小权限：

```text
oss:PutObject
oss:GetObject
oss:HeadObject
oss:DeleteObject
oss:ListObjects
```

资源范围限制在：

```text
acs:oss:*:*:sggf-audio-library
acs:oss:*:*:sggf-audio-library/shared/audio_library/*
```

## 禁止事项

- 不要在 `audio.sggf.net` DNS/HTTPS/OSS 公共读取未验证通过时启用 `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=https://audio.sggf.net`。
- 不要把 `dashscope_oss` 上传出的对象改写到 `audio.sggf.net`；自定义域名必须配合 `aliyun_oss` 和自有 Bucket 使用。
- 不要在没有验证 CDN/OSS 映射前执行真实 `cloud-sync`。
- 不要把只有 `public_url`、没有 `object_key/cloud_uri` 的历史素材批量改写到新域名。
- 不要把公开素材平台当作可直接批量镜像下载的数据源；正式入库仍需 manifest、授权字段和 dry-run/confirm 流程。

## 切换流程

1. 创建 `audio.sggf.net` DNS 记录。
2. 绑定 CDN/OSS 或 Nginx 反代，并配置 HTTPS 证书。
3. 上传一个测试对象到 `shared/audio_library/healthcheck.txt`。
4. 运行 DNS、HTTPS、Range 请求验证。
5. 创建最小权限 RAM 用户或角色，并设置 `aliyun_oss` 所需环境变量。
6. 重启后端、Celery 和 Nginx。
7. 打开素材库列表和预览接口，确认返回或跳转到 `https://audio.sggf.net/shared/audio_library/...`。
8. 再执行 `cloud-sync` dry-run；确认无误后才执行 `dry_run=false, confirm=true`。
