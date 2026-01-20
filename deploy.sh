#!/bin/bash

# 阿里云ECS部署脚本
# 用于在阿里云ECS上部署拾光工坊应用

set -e

echo "=========================================="
echo "  拾光工坊 - 阿里云ECS部署脚本"
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

# 检查系统
echo -e "${GREEN}[1/8] 检查系统环境...${NC}"
if [ -f /etc/alinux-release ]; then
    echo -e "${GREEN}检测到 Alibaba Cloud Linux${NC}"
    OS="alinux"
elif [ -f /etc/redhat-release ]; then
    echo -e "${GREEN}检测到 CentOS/RHEL${NC}"
    OS="centos"
elif [ -f /etc/debian_version ]; then
    echo -e "${GREEN}检测到 Debian/Ubuntu${NC}"
    OS="debian"
else
    echo -e "${RED}不支持的操作系统${NC}"
    exit 1
fi
echo ""

# 安装Docker
echo -e "${GREEN}[2/8] 安装Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo "正在安装Docker..."
    curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
    systemctl start docker
    systemctl enable docker
    echo -e "${GREEN}Docker安装完成${NC}"
else
    echo -e "${YELLOW}Docker已安装${NC}"
fi
echo ""

# 安装Docker Compose
echo -e "${GREEN}[3/8] 安装Docker Compose...${NC}"
if ! command -v docker-compose &> /dev/null; then
    echo "正在安装Docker Compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo -e "${GREEN}Docker Compose安装完成${NC}"
else
    echo -e "${YELLOW}Docker Compose已安装${NC}"
fi
echo ""

# 配置防火墙
echo -e "${GREEN}[4/8] 配置防火墙...${NC}"
if command -v firewall-cmd &> /dev/null; then
    echo "配置firewalld..."
    firewall-cmd --permanent --add-port=80/tcp
    firewall-cmd --permanent --add-port=443/tcp
    firewall-cmd --permanent --add-port=8000/tcp
    firewall-cmd --permanent --add-port=3000/tcp
    firewall-cmd --reload
    echo -e "${GREEN}防火墙配置完成${NC}"
elif command -v ufw &> /dev/null; then
    echo "配置ufw..."
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 8000/tcp
    ufw allow 3000/tcp
    echo -e "${GREEN}防火墙配置完成${NC}"
else
    echo -e "${YELLOW}未检测到防火墙，跳过配置${NC}"
fi
echo ""

# 创建项目目录
echo -e "${GREEN}[5/8] 创建项目目录...${NC}"
PROJECT_DIR="/root/novel_writing_agent"
if [ ! -d "$PROJECT_DIR" ]; then
    mkdir -p "$PROJECT_DIR"
    echo -e "${GREEN}项目目录创建完成: $PROJECT_DIR${NC}"
else
    echo -e "${YELLOW}项目目录已存在: $PROJECT_DIR${NC}"
fi
echo ""

# 检查项目文件
echo -e "${GREEN}[6/8] 检查项目文件...${NC}"
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
    echo -e "${RED}错误: 未找到docker-compose.yml文件${NC}"
    echo "请先上传项目文件到 $PROJECT_DIR"
    exit 1
fi
if [ ! -f "$PROJECT_DIR/backend/.env" ]; then
    echo -e "${RED}错误: 未找到backend/.env文件${NC}"
    echo "请先配置backend/.env文件"
    exit 1
fi
if [ ! -d "$PROJECT_DIR/ssl" ]; then
    echo -e "${RED}错误: 未找到ssl目录${NC}"
    echo "请先准备SSL证书文件"
    exit 1
fi
echo -e "${GREEN}项目文件检查通过${NC}"
echo ""

# 停止旧容器
echo -e "${GREEN}[7/8] 停止旧容器...${NC}"
cd "$PROJECT_DIR"
docker-compose down 2>/dev/null || true
echo -e "${GREEN}旧容器已停止${NC}"
echo ""

# 启动服务
echo -e "${GREEN}[8/8] 启动服务...${NC}"
docker-compose up -d
echo ""

# 等待服务启动
echo -e "${GREEN}等待服务启动...${NC}"
sleep 10

# 检查服务状态
echo -e "${GREEN}检查服务状态...${NC}"
docker-compose ps

# 健康检查
echo ""
echo -e "${GREEN}执行健康检查...${NC}"
sleep 5

# 检查PostgreSQL
if docker-compose ps | grep -q "novel_postgres.*Up"; then
    echo -e "${GREEN}✓ PostgreSQL 运行正常${NC}"
else
    echo -e "${RED}✗ PostgreSQL 启动失败${NC}"
fi

# 检查Redis
if docker-compose ps | grep -q "novel_redis.*Up"; then
    echo -e "${GREEN}✓ Redis 运行正常${NC}"
else
    echo -e "${RED}✗ Redis 启动失败${NC}"
fi

# 检查Backend
if docker-compose ps | grep -q "novel_backend.*Up"; then
    echo -e "${GREEN}✓ Backend 运行正常${NC}"
else
    echo -e "${RED}✗ Backend 启动失败${NC}"
fi

# 检查Frontend
if docker-compose ps | grep -q "novel_frontend.*Up"; then
    echo -e "${GREEN}✓ Frontend 运行正常${NC}"
else
    echo -e "${RED}✗ Frontend 启动失败${NC}"
fi

# 检查Nginx
if docker-compose ps | grep -q "novel_nginx.*Up"; then
    echo -e "${GREEN}✓ Nginx 运行正常${NC}"
else
    echo -e "${RED}✗ Nginx 启动失败${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}部署完成！${NC}"
echo "=========================================="
echo ""
echo "访问地址："
echo "  - HTTP:  http://sggf.net"
echo "  - HTTPS: https://sggf.net"
echo "  - API:   https://sggf.net/api"
echo ""
echo "管理命令："
echo "  - 查看日志: docker-compose logs -f"
echo "  - 停止服务: docker-compose down"
echo "  - 重启服务: docker-compose restart"
echo "  - 查看状态: docker-compose ps"
echo ""
echo -e "${YELLOW}重要提示：${NC}"
echo "  1. 请在阿里云控制台配置安全组，开放80、443端口"
echo "  2. 请确保域名sggf.net已解析到服务器IP: 101.132.154.143"
echo "  3. 首次部署需要执行数据库迁移"
echo ""
