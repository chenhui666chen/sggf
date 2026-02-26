# 数据库迁移指南

本文档说明如何使用 Alembic 进行数据库迁移，包括从 SQLite 迁移到 PostgreSQL 的完整流程。

## 概述

- **当前状态**: SQLite 数据库包含历史数据（6 个用户，3 个项目）
- **目标数据库**: PostgreSQL（生产环境）
- **迁移工具**: Alembic
- **迁移脚本**: `migrate_to_postgres.py`

## 快速开始

### 1. 本地开发环境（SQLite）

```bash
# 初始化数据库（仅首次）
cd backend
python -c "from app.db.base import Base, engine; from app.models import *; Base.metadata.create_all(bind=engine)"

# 或者使用 Alembic（推荐）
alembic upgrade head
```

### 2. 生产环境（PostgreSQL）

```bash
# 确保 PostgreSQL 容器正在运行
docker-compose up -d postgres

# 运行数据库迁移
alembic upgrade head

# 如果有 SQLite 历史数据需要迁移
python migrate_to_postgres.py
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

## 从 SQLite 迁移到 PostgreSQL

### 前置条件

1. PostgreSQL 容器正在运行
2. 已配置 `DATABASE_URL` 环境变量
3. SQLite 数据库文件存在（`novel_app.db`）

### 迁移步骤

```bash
# 1. 确保 PostgreSQL 容器运行
docker-compose up -d postgres

# 2. 等待 PostgreSQL 就绪
docker-compose logs -f postgres

# 3. 运行迁移脚本
python migrate_to_postgres.py

# 4. 验证数据迁移
# 连接到 PostgreSQL 检查数据
docker exec -it novel_postgres psql -U novel_user -d novel_db -c "SELECT COUNT(*) FROM users;"
```

### 迁移脚本说明

`migrate_to_postgres.py` 会执行以下操作：

1. 读取 SQLite 数据库中的所有数据
2. 在 PostgreSQL 中创建表结构（通过 `Base.metadata.create_all`）
3. 逐表迁移数据：
   - 用户（users）
   - 项目（projects）
   - 角色（characters）
   - 记忆（memories）
   - 书籍（book_sources）
   - 章节（book_chapters）
   - 有声书项目（audiobook_projects）
   - 章节音频（chapter_audios）
4. 备份 SQLite 数据库为 `.db.backup`
5. 输出迁移统计信息

## 生产环境部署

### 首次部署

```bash
# 1. SSH 到服务器
ssh root@101.132.154.143

# 2. 导航到项目目录
cd /root/novel_writing_agent

# 3. 启动 PostgreSQL 容器
docker-compose up -d postgres

# 4. 等待 PostgreSQL 就绪
docker-compose logs -f postgres

# 5. 应用数据库迁移
docker-compose exec backend alembic upgrade head

# 6. 如果有 SQLite 数据需要迁移
docker-compose exec backend python migrate_to_postgres.py

# 7. 启动所有服务
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

### 1. 使用 Alembic 管理数据库结构

```bash
# 修改模型后，创建迁移
alembic revision --autogenerate -m "添加新字段"

# 检查生成的迁移脚本
# 编辑 backend/alembic/versions/xxx_添加新字段.py

# 应用迁移
alembic upgrade head
```

### 2. 本地开发使用 SQLite

```bash
# 设置环境变量
export DATABASE_URL=sqlite:///novel_app.db

# 应用迁移
alembic upgrade head
```

### 3. 测试环境使用 PostgreSQL

```bash
# 启动 PostgreSQL 容器
docker-compose up -d postgres

# 设置环境变量
export DATABASE_URL=postgresql://novel_user:NovelPostgres0t649OyRUaI@localhost:5432/novel_db

# 应用迁移
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

### 问题 4: 数据迁移失败

**原因**: SQLite 和 PostgreSQL 数据类型不兼容

**解决方案**:
1. 检查 `migrate_to_postgres.py` 中的数据转换逻辑
2. 手动修复不兼容的数据类型
3. 重新运行迁移脚本

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

- [backend/app/main.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/main.py): FastAPI 主应用
- [backend/app/db/base.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/db/base.py): 数据库基类配置
- [backend/alembic/env.py](file:///c:/Users/cuigu/novel_writing_agent/backend/alembic/env.py): Alembic 环境配置
- [migrate_to_postgres.py](file:///c:/Users/cuigu/novel_writing_agent/migrate_to_postgres.py): SQLite 到 PostgreSQL 迁移脚本
- [docker-compose.yml](file:///c:/Users/cuigu/novel_writing_agent/docker-compose.yml): Docker Compose 配置
