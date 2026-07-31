---
kind: external_dependency
name: Redis缓存与消息队列
slug: redis
category: external_dependency
category_hints:
    - vendor_identity
    - client_constraint
scope:
    - '**'
---

用作Celery任务队列的Broker和Result Backend，以及应用缓存层。容器化部署时使用Redis 7 Alpine镜像，端口映射6380:6379，启用密码认证和AOF持久化。CELERY_BROKER_URL和CELERY_RESULT_BACKEND均指向同一Redis实例。生产环境必须修改默认密码NovelRedis2024!。