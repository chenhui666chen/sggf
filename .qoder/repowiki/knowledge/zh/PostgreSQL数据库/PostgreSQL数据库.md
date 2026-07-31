---
kind: external_dependency
name: PostgreSQL数据库
slug: postgresql
category: external_dependency
category_hints:
    - vendor_identity
    - client_constraint
scope:
    - '**'
---

项目强制使用的关系型数据库，不再支持SQLite模式。通过DATABASE_URL连接，版本为PostgreSQL 15 Alpine镜像。容器化部署时端口映射为5432，默认用户novel_user，数据库novel_db。生产环境必须通过环境变量覆盖默认凭证，不能直接使用开发配置。