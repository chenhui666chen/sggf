# 数据库迁移指南

本文档说明如何使用 Alembic 进行数据库迁移。

## 概述

- **当前数据库**: PostgreSQL（生产环境）
- **迁移工具**: Alembic
- **注意**: 项目已完全迁移到 PostgreSQL，不再使用 SQLite

## 快速开始

### PostgreSQL 环境

```bash
# 确保 PostgreSQL 容器正在运行
docker-compose up -d postgres

# 运行数据库迁移
cd backend
alembic upgrade head
```

## Alembic 命令参考

### 创建迁移

```bash
# 自动生成迁移脚本（检测模型变化）
alembic revision --autogenerate -m "描述迁移内容"

# 手动创建迁移脚本
alembic revision -m "描述迁移内容"
```

### 应用迁移

```bash
# 应用所有待执行的迁移
alembic upgrade head

# 应用到特定版本
alembic upgrade <revision_id>

# 回滚一个版本
alembic downgrade -1

# 回滚到特定版本
alembic downgrade <revision_id>
```

### 查看迁移状态

```bash
# 查看当前版本
alembic current

# 查看迁移历史
alembic history

# 查看待执行的迁移
alembic heads
```

## 生产环境部署

### 首次部署

```bash
# 1. 启动 PostgreSQL 容器
docker-compose up -d postgres

# 2. 等待 PostgreSQL 就绪
docker-compose logs -f postgres

# 3. 应用数据库迁移
docker-compose exec backend alembic upgrade head

# 4. 启动所有服务
docker-compose up -d
```

### 更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 检查是否有新的迁移
docker-compose exec backend alembic current
docker-compose exec backend alembic heads

# 3. 应用新的迁移
docker-compose exec backend alembic upgrade head

# 4. 重启服务
docker-compose restart backend
```

## 开发环境最佳实践

### 使用 Alembic 管理数据库结构

```bash
# 修改模型后，创建迁移
cd backend
alembic revision --autogenerate -m "添加新字段"

# 检查生成的迁移脚本
# 编辑 backend/alembic/versions/xxx_添加新字段.py

# 应用迁移
alembic upgrade head
```

### PostgreSQL 开发环境

```bash
# 启动 PostgreSQL 容器
docker-compose up -d postgres

# 应用迁移
cd backend
alembic upgrade head
```

## 故障排除

### 问题 1: Alembic 检测不到模型变化

**原因**: `target_metadata` 未正确配置

**解决方案**: 确保 `backend/alembic/env.py` 中：
```python
from app.db.base import Base
target_metadata = Base.metadata
```

### 问题 2: 迁移脚本生成失败

**原因**: 模型导入路径问题

**解决方案**: 确保 `backend/alembic/env.py` 中正确设置了 Python 路径：
```python
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
```

### 问题 3: PostgreSQL 连接失败

**原因**: 容器未启动或网络配置问题

**解决方案**:
```bash
# 检查容器状态
docker-compose ps

# 查看日志
docker-compose logs postgres

# 测试连接
docker-compose exec postgres psql -U novel_user -d novel_db -c "SELECT 1;"
```

### 问题 4: 外键约束验证

**说明**: PostgreSQL 自动启用外键约束，确保数据完整性

**验证方法**:
```bash
# 检查外键约束配置
docker-compose exec postgres psql -U novel_user -d novel_db -c "
SELECT tc.constraint_name, tc.table_name, kcu.column_name,
       ccu.table_name AS foreign_table_name, rc.delete_rule
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.referential_constraints AS rc ON tc.constraint_name = rc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = 'dreamweaver_projects';
"
```

## 数据库备份与恢复

### 备份 PostgreSQL

```bash
# 备份整个数据库
docker-compose exec postgres pg_dump -U novel_user novel_db > backup.sql

# 备份特定表
docker-compose exec postgres pg_dump -U novel_user -t users novel_db > users_backup.sql
```

### 恢复 PostgreSQL

```bash
# 恢复整个数据库
docker-compose exec -T postgres psql -U novel_user novel_db < backup.sql

# 恢复特定表
docker-compose exec -T postgres psql -U novel_user novel_db < users_backup.sql
```

## 配置说明

### Alembic 配置文件

- `alembic.ini`: 主配置文件
  - `script_location`: 迁移脚本目录
  - `sqlalchemy.url`: 数据库连接 URL（可通过环境变量覆盖）

- `backend/alembic/env.py`: 迁移环境配置
  - `target_metadata`: 模型元数据
  - 数据库 URL 配置

- `backend/alembic/versions/`: 迁移脚本目录
  - 每个迁移脚本对应一个数据库版本

### 环境变量

```bash
# 数据库配置
DATABASE_URL=postgresql://novel_user:NovelPostgres0t649OyRUaI@postgres:5432/novel_db

# 连接池配置
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=True
```

## 注意事项

1. **生产环境必须使用 Alembic 迁移**，不要使用 `create_all`
2. **迁移脚本必须经过代码审查**，确保数据安全
3. **重要操作前先备份数据库**
4. **测试环境先验证迁移脚本**，再在生产环境执行
5. **保持迁移脚本的幂等性**，可以重复执行
6. **避免在迁移脚本中执行耗时操作**，大数据量迁移单独处理

## 相关文件

- [backend/app/main.py](backend/app/main.py): FastAPI 主应用
- [backend/app/db/base.py](backend/app/db/base.py): 数据库基类配置
- [backend/alembic/env.py](backend/alembic/env.py): Alembic 环境配置
- [docker-compose.yml](docker-compose.yml): Docker Compose 配置
