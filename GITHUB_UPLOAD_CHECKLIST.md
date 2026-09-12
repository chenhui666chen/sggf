# GitHub 上传检查清单

## 仓库范围

本仓库是拾光工坊全栈网站，包含 React/Vite 前端、FastAPI/Celery 后端、测试、部署配置和功能文档。

## 上传前检查

```powershell
git status --short
git diff --stat
git ls-files | Select-String -Pattern '\.env$|\.pem$|\.key$|\.crt$|\.db$|\.sqlite|node_modules|\.venv|dist/'
```

确认以下内容未被加入提交：

- 根目录、`backend/`、`frontend/` 和运行目录中的真实 `.env` 文件。
- `ssl/` 下的证书和私钥。
- `.venv/`、`node_modules/`、数据库、向量库和缓存。
- `backend/data/audio_library/` 中不适合进入 Git 历史的大型媒体资源。
- 临时运行目录、日志、测试缓存和本地工具配置。

当前仓库已有 GitHub 和 Gitee 远程地址。新账号注册完成后，确认目标仓库后再替换 `origin`，不要直接覆盖已有远程配置。
