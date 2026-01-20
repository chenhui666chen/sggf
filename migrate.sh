#!/bin/bash

# 数据库迁移脚本
# 用于在ECS上执行数据库迁移

set -e

echo "=========================================="
echo "  数据库迁移脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}请使用root用户执行此脚本${NC}"
    exit 1
fi

# 进入项目目录
cd /root/novel_writing_agent

echo -e "${GREEN}[1/5] 检查Backend容器状态...${NC}"
if ! docker-compose ps | grep -q "novel_backend.*Up"; then
    echo -e "${RED}错误: Backend容器未运行${NC}"
    echo "请先启动服务: docker-compose up -d"
    exit 1
fi
echo -e "${GREEN}Backend容器运行正常${NC}"
echo ""

echo -e "${YELLOW}[2/5] 警告: 数据库迁移会修改表结构${NC}"
echo -e "${YELLOW}建议先备份数据库！${NC}"
echo ""
read -p "是否继续？(yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "已取消"
    exit 0
fi
echo ""

# 备份数据库
echo -e "${GREEN}[3/5] 备份数据库...${NC}"
BACKUP_DIR="/root/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/novel_db_backup_$(date +%Y%m%d_%H%M%S).sql"
docker-compose exec -T postgres pg_dump -U novel_user novel_db > "$BACKUP_FILE"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}数据库备份成功: $BACKUP_FILE${NC}"
else
    echo -e "${RED}数据库备份失败${NC}"
    exit 1
fi
echo ""

# 执行迁移
echo -e "${GREEN}[4/5] 执行数据库迁移...${NC}"
docker-compose exec backend alembic upgrade head
if [ $? -eq 0 ]; then
    echo -e "${GREEN}数据库迁移成功${NC}"
else
    echo -e "${RED}数据库迁移失败${NC}"
    echo -e "${YELLOW}正在尝试回滚...${NC}"
    docker-compose exec backend alembic downgrade base
    echo -e "${YELLOW}已回滚到初始状态${NC}"
    exit 1
fi
echo ""

# 验证迁移
echo -e "${GREEN}[5/5] 验证数据库结构...${NC}"
docker-compose exec backend python -c "
from app.db.base import engine
from sqlalchemy import inspect

inspector = inspect(engine)
tables = inspector.get_table_names()
print(f'数据库表数量: {len(tables)}')
print(f'表列表: {tables}')
"

echo ""
echo "=========================================="
echo -e "${GREEN}数据库迁移完成！${NC}"
echo "=========================================="
echo ""
echo "备份文件: $BACKUP_FILE"
echo ""
echo "如需回滚，执行："
echo "  docker-compose exec backend alembic downgrade base"
echo ""
