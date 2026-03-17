# PostgreSQL生产环境部署指南

## 概述

本项目已从SQLite迁移到PostgreSQL，以支持大规模商用部署。PostgreSQL提供更好的性能、并发能力和数据完整性。

## 配置变更

### 1. 数据库连接

**本地开发环境：**
```bash
DATABASE_URL=postgresql://novel_user:novel_secure_password_2024@localhost:5432/novel_db
```

**Docker环境：**
```bash
DATABASE_URL=postgresql://novel_user:novel_secure_password_2024@postgres:5432/novel_db
```

### 2. 连接池配置

在`.env`文件中配置：
```bash
# 数据库连接池配置（生产环境优化）
DB_POOL_SIZE=20          # 连接池大小
DB_MAX_OVERFLOW=10        # 最大溢出连接数
DB_POOL_TIMEOUT=30         # 连接超时（秒）
DB_POOL_RECYCLE=3600      # 连接回收时间（秒）
DB_POOL_PRE_PING=True      # 连接前ping检查
```

### 3. PostgreSQL性能优化

在`docker-compose.yml`中已配置以下优化参数：

```yaml
command:
  - "postgres"
  - "-c" "max_connections=200"        # 最大连接数
  - "-c" "shared_buffers=256MB"       # 共享缓冲区
  - "-c" "effective_cache_size=1GB"     # 有效缓存大小
  - "-c" "maintenance_work_mem=64MB"   # 维护工作内存
  - "-c" "checkpoint_completion_target=0.9"
  - "-c" "wal_buffers=16MB"           # WAL缓冲区
  - "-c" "default_statistics_target=100"
  - "-c" "random_page_cost=1.1"       # SSD优化
  - "-c" "effective_io_concurrency=200"
  - "-c" "work_mem=4MB"               # 每个查询的工作内存
  - "-c" "min_wal_size=1GB"           # 最小WAL大小
  - "-c" "max_wal_size=4GB"           # 最大WAL大小
```

## 部署步骤

### 方式一：使用Docker Compose（推荐）

命令示例优先使用 `docker compose`。如果你的环境仍然只有旧版独立命令，也可以替换为 `docker-compose`。

1. **启动服务**
```bash
docker compose up -d
```

2. **验证PostgreSQL连接**
```bash
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT version();"
```

3. **查看日志**
```bash
docker compose logs postgres
```

### 方式二：使用云数据库服务

如果使用阿里云RDS、腾讯云PostgreSQL等云服务：

1. **修改.env配置**
```bash
DATABASE_URL=postgresql://username:password@host:port/database
```

2. **跳过 Docker Compose 中的 PostgreSQL 服务**
```bash
# 注释掉postgres服务
# postgres:
#   image: postgres:15-alpine
#   ...
```

3. **直接启动后端服务**
```bash
docker compose up -d backend redis frontend nginx
```

## 数据迁移

### 从SQLite迁移到PostgreSQL

如果已有SQLite数据，使用迁移脚本：

```bash
# 1. 确保PostgreSQL正在运行
docker compose up -d postgres

# 2. 运行迁移脚本
python migrate_to_postgres.py

# 3. 验证数据
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT COUNT(*) FROM users;"
```

### 使用Alembic进行数据库迁移

```bash
# 生成迁移脚本
alembic revision --autogenerate -m "描述"

# 执行迁移
alembic upgrade head

# 回滚迁移
alembic downgrade -1
```

## 性能监控

### 1. 查看连接数
```bash
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT count(*) FROM pg_stat_activity;"
```

### 2. 查看数据库大小
```bash
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT pg_size_pretty(pg_database_size('novel_db'));"
```

### 3. 查看慢查询
```bash
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
```

## 备份与恢复

### 备份数据库

```bash
# 备份到SQL文件
docker exec novel_postgres pg_dump -U novel_user novel_db > backup_$(date +%Y%m%d_%H%M%S).sql

# 备份到压缩文件
docker exec novel_postgres pg_dump -U novel_user novel_db | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

### 恢复数据库

```bash
# 从SQL文件恢复
cat backup.sql | docker exec -i novel_postgres psql -U novel_user -d novel_db

# 从压缩文件恢复
gunzip -c backup.sql.gz | docker exec -i novel_postgres psql -U novel_user -d novel_db
```

### 定期自动备份

在`docker-compose.yml`中添加备份服务：

```yaml
backup:
  image: prodrigestivill/postgres-backup-local
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_DB: novel_db
    POSTGRES_USER: novel_user
    POSTGRES_PASSWORD: novel_secure_password_2024
    SCHEDULE: "@daily"              # 每天备份
    BACKUP_KEEP_DAYS: 7              # 保留7天
    BACKUP_KEEP_WEEKS: 4             # 保留4周
    BACKUP_KEEP_MONTHS: 6            # 保留6个月
  volumes:
    - ./backups:/backups
  depends_on:
    - postgres
```

## 安全配置

### 1. 修改默认密码

**必须修改以下密码：**

- PostgreSQL密码：`novel_secure_password_2024`
- Redis密码：`redis_secure_password_2024`
- JWT密钥：`CHANGE_THIS_TO_SECURE_RANDOM_KEY_MIN_32_BYTES`

**生成强密码：**
```bash
# PostgreSQL密码
openssl rand -base64 32

# Redis密码
openssl rand -base64 16

# JWT密钥
openssl rand -hex 32
```

### 2. 网络安全

- 不要将PostgreSQL端口（5432）暴露到公网
- 使用防火墙限制访问
- 配置PostgreSQL的`pg_hba.conf`只允许特定IP连接

### 3. SSL/TLS加密

生产环境建议启用SSL连接：

```bash
DATABASE_URL=postgresql://user:password@host:port/database?sslmode=require
```

## 故障排查

### 问题1：连接超时

**症状：** `psycopg2.OperationalError: server closed the connection unexpectedly`

**解决方案：**
1. 增加连接池大小
2. 增加`DB_POOL_TIMEOUT`
3. 检查PostgreSQL的`max_connections`配置

### 问题2：连接数不足

**症状：** `FATAL: remaining connection slots are reserved`

**解决方案：**
1. 增加`max_connections`配置
2. 增加连接池大小
3. 检查是否有连接泄漏

### 问题3：性能问题

**症状：** 查询响应慢

**解决方案：**
1. 运行`VACUUM ANALYZE`更新统计信息
2. 检查慢查询日志
3. 添加适当的索引
4. 调整`work_mem`和`maintenance_work_mem`

## 扩展性建议

### 1. 读写分离

对于高并发场景，配置主从复制：

```yaml
# 主库（写）
postgres-master:
  image: postgres:15-alpine
  ...

# 从库（读）
postgres-slave:
  image: postgres:15-alpine
  command: postgres -c 'hot_standby=on'
  ...
```

### 2. 连接池优化

根据服务器配置调整连接池：

```bash
# 4核8G服务器
DB_POOL_SIZE=30
DB_MAX_OVERFLOW=15

# 8核16G服务器
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=25
```

### 3. 分区表

对于大表（如`book_chapters`），考虑使用分区：

```sql
-- 按时间分区
CREATE TABLE book_chapters (
    id SERIAL,
    created_at TIMESTAMP DEFAULT NOW(),
    ...
) PARTITION BY RANGE (created_at);

-- 创建分区
CREATE TABLE book_chapters_2024 PARTITION OF book_chapters
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
```

## 监控告警

建议配置以下监控指标：

1. **数据库连接数**：超过80%告警
2. **查询响应时间**：超过1秒告警
3. **磁盘使用率**：超过80%告警
4. **CPU使用率**：超过70%告警
5. **内存使用率**：超过80%告警

可以使用以下工具：
- Prometheus + Grafana
- Datadog
- New Relic
- 阿里云云监控

## 参考资料

- [PostgreSQL官方文档](https://www.postgresql.org/docs/)
- [SQLAlchemy连接池文档](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [Docker PostgreSQL镜像](https://hub.docker.com/_/postgres)
