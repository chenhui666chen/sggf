---
kind: external_dependency
name: Nginx反向代理服务器
slug: nginx
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

生产环境的反向代理和静态资源服务器，处理HTTPS终止和请求路由。容器化部署使用nginx:alpine镜像，监听80和443端口。支持Let's Encrypt证书自动续期，SSL证书路径通过NGINX_SSL_CERT_PATH和NGINX_SSL_KEY_PATH环境变量配置。生产配置文件为nginx-prod.conf。