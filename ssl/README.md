本目录用于放置本地或宿主机挂载使用的 SSL 证书文件。

- 真实证书和私钥不要提交到 Git
- `docker-compose.yml` 会优先读取 `.env` 中的 `NGINX_SSL_CERT_PATH` 和 `NGINX_SSL_KEY_PATH`
- 如果未设置上述变量，Nginx 会回退读取 `ssl/cert.pem` 和 `ssl/key.pem`

生产环境推荐直接在 `.env` 中指向宿主机上的 Let's Encrypt 证书路径。
