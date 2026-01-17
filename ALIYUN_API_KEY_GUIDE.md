# 阿里云百炼 API 密钥配置

配置以 `.env` 为准，建议：

- 从 `.env.example` 复制生成 `.env`
- 填写 `DASHSCOPE_API_KEY` 以及需要启用的模型 `*_API_KEY/*_BASE_URL/*_MODEL_ID`
- 启动后端后如遇调用失败，以日志/异常信息为准排查

模型变量名与调用方式见 `ALIYUN_QUICKSTART.md`。
