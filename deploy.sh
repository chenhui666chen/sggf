#!/bin/bash
# 拾光工坊 - 一键部署脚本
# 使用方法：./deploy.sh [选项]
# 选项：
#   --update    仅更新代码，不重新构建
#   --rebuild   重新构建所有镜像
#   --backup    部署前备份数据库
#   --help      显示帮助信息

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
PROJECT_DIR="/root/novel_writing_agent"
BACKUP_DIR="/root/backups"
LOG_FILE="/root/deploy.log"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令行参数
UPDATE_ONLY=false
REBUILD=false
BACKUP=false

for arg in "$@"; do
    case $arg in
        --update)
            UPDATE_ONLY=true
            ;;
        --rebuild)
            REBUILD=true
            ;;
        --backup)
            BACKUP=true
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --update    仅更新代码，不重新构建"
            echo "  --rebuild   重新构建所有镜像"
            echo "  --backup    部署前备份数据库"
            echo "  --help      显示此帮助信息"
            exit 0
            ;;
    esac
done

# 记录日志
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> $LOG_FILE
}

# 创建备份目录
create_backup_dir() {
    print_info "创建备份目录..."
    mkdir -p $BACKUP_DIR
    log "创建备份目录: $BACKUP_DIR"
}

# 备份数据库
backup_database() {
    print_info "备份数据库..."
    local backup_file="$BACKUP_DIR/db_backup_$TIMESTAMP.sql"
    
    cd $PROJECT_DIR
    docker-compose exec -T postgres pg_dump -U novel_user novel_db > $backup_file
    
    if [ $? -eq 0 ]; then
        print_success "数据库备份成功: $backup_file"
        log "数据库备份成功: $backup_file"
        
        # 删除 7 天前的备份
        find $BACKUP_DIR -name "db_backup_*.sql" -mtime +7 -delete
        print_info "已删除 7 天前的旧备份"
    else
        print_error "数据库备份失败"
        log "数据库备份失败"
        exit 1
    fi
}

# 备份 Redis
backup_redis() {
    print_info "备份 Redis 数据..."
    local backup_file="$BACKUP_DIR/redis_backup_$TIMESTAMP.rdb"
    
    cd $PROJECT_DIR
    docker-compose exec redis redis-cli -a NovelRedis2024! BGSAVE
    sleep 2
    docker cp novel_redis:/data/dump.rdb $backup_file
    
    if [ $? -eq 0 ]; then
        print_success "Redis 备份成功: $backup_file"
        log "Redis 备份成功: $backup_file"
    else
        print_warning "Redis 备份失败（继续部署）"
    fi
}

# 备份上传文件
backup_uploads() {
    print_info "备份上传文件..."
    local backup_file="$BACKUP_DIR/uploads_backup_$TIMESTAMP.tar.gz"
    
    cd $PROJECT_DIR
    tar -czf $backup_file backend/uploads 2>/dev/null || true
    
    if [ $? -eq 0 ]; then
        print_success "上传文件备份成功: $backup_file"
        log "上传文件备份成功: $backup_file"
    else
        print_warning "上传文件备份失败（继续部署）"
    fi
}

# 停止服务
stop_services() {
    print_info "停止应用服务..."
    cd $PROJECT_DIR
    docker-compose stop backend frontend nginx
    log "停止应用服务"
    print_success "应用服务已停止"
}

# 拉取最新代码
pull_code() {
    print_info "拉取最新代码..."
    cd $PROJECT_DIR
    
    if [ -d ".git" ]; then
        local tracked_changes
        tracked_changes=$(git status --porcelain --untracked-files=no)
        if [ -n "$tracked_changes" ]; then
            print_error "检测到未提交的已跟踪改动，已停止自动拉取以避免覆盖现场文件"
            git status --short
            log "Git 工作区存在未提交的已跟踪改动，停止自动拉取"
            exit 1
        fi

        local current_branch
        current_branch=$(git rev-parse --abbrev-ref HEAD)
        if [ "$current_branch" != "main" ]; then
            print_error "当前分支不是 main：$current_branch，已停止自动部署"
            log "当前分支不是 main：$current_branch"
            exit 1
        fi

        git fetch origin

        local ahead behind
        read -r ahead behind <<EOF
$(git rev-list --left-right --count HEAD...origin/main)
EOF

        if [ "$ahead" -gt 0 ]; then
            print_error "当前分支包含未推送或已分叉提交，拒绝自动快进，请人工确认后再部署"
            log "检测到本地分支 ahead/diverged，停止自动拉取"
            exit 1
        fi

        if [ "$behind" -eq 0 ]; then
            log "代码已是最新"
            print_success "代码已是最新"
            return 0
        fi

        git merge --ff-only origin/main
        log "拉取最新代码"
        print_success "代码更新成功"
    else
        print_warning "不是 Git 仓库，跳过代码更新"
    fi
}

# 上传本地代码
upload_code() {
    print_info "上传代码到服务器..."
    print_warning "请确保在本地执行以下命令上传代码："
    echo ""
    echo "scp -r C:\\Users\\cuigu\\novel_writing_agent root@101.132.154.143:/root/"
    echo ""
    read -p "代码已上传？(y/n) " uploaded
    if [ "$uploaded" != "y" ]; then
        print_error "请先上传代码"
        exit 1
    fi
}

# 构建镜像
build_images() {
    print_info "构建 Docker 镜像..."
    cd $PROJECT_DIR

    if [ "$UPDATE_ONLY" = true ]; then
        print_info "已启用 --update，跳过镜像构建"
        log "跳过镜像构建"
        return 0
    fi
    
    if [ "$REBUILD" = true ]; then
        print_info "强制重新构建所有镜像..."
        docker-compose build --no-cache
    else
        print_info "构建镜像（使用缓存）..."
        docker-compose build
    fi
    
    log "构建镜像"
    print_success "镜像构建完成"
}

# 启动服务
start_services() {
    print_info "启动服务..."
    cd $PROJECT_DIR

    docker-compose up -d --remove-orphans
    
    log "启动服务"
    print_success "服务已启动"
}

# 等待服务就绪
wait_for_services() {
    print_info "等待服务就绪..."
    sleep 10
    
    local max_attempts=30
    local attempt=0
    local backend_ready=false
    local frontend_ready=false
    
    while [ $attempt -lt $max_attempts ]; do
        # 检查后端
        if curl -sf http://127.0.0.1:8000/health > /dev/null; then
            backend_ready=true
        fi
        
        # 检查前端
        if curl -sfI http://127.0.0.1:3000 > /dev/null; then
            frontend_ready=true
        fi

        if [ "$backend_ready" = true ] && [ "$frontend_ready" = true ]; then
            print_success "后端和前端服务均已就绪"
            return 0
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    
    echo ""
    
    if [ $attempt -ge $max_attempts ]; then
        if [ "$backend_ready" != true ]; then
            print_error "后端服务未就绪"
        fi
        if [ "$frontend_ready" != true ]; then
            print_error "前端服务未就绪"
        fi
        print_error "服务启动超时，请检查日志"
        log "服务启动超时"
        exit 1
    fi
}

# 运行数据库迁移
run_migrations() {
    print_info "运行数据库迁移..."
    cd $PROJECT_DIR
    docker-compose exec -T backend python -m alembic -c /app/alembic.ini upgrade heads
    
    if [ $? -eq 0 ]; then
        print_success "数据库迁移完成"
        log "数据库迁移完成"
    else
        print_warning "数据库迁移失败（可能已经是最新的）"
    fi
}

# 显示服务状态
show_status() {
    print_info "服务状态："
    cd $PROJECT_DIR
    docker-compose ps
    echo ""
    
    print_info "资源使用："
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
}

# 显示部署摘要
show_summary() {
    echo ""
    echo "=========================================="
    print_success "部署完成！"
    echo "=========================================="
    echo ""
    echo "访问地址："
    echo "  HTTP:  http://101.132.154.143"
    echo "  HTTPS: https://sggf.net"
    echo "  域名: https://www.sggf.net"
    echo ""
    echo "常用命令："
    echo "  查看日志: cd $PROJECT_DIR && docker-compose logs -f"
    echo "  重启服务: cd $PROJECT_DIR && docker-compose restart"
    echo "  停止服务: cd $PROJECT_DIR && docker-compose stop"
    echo "  查看状态: cd $PROJECT_DIR && docker-compose ps"
    echo ""
    echo "日志文件: $LOG_FILE"
    echo "=========================================="
}

# 主部署流程
main() {
    echo ""
    echo "=========================================="
    echo "  拾光工坊 - 自动部署脚本"
    echo "=========================================="
    echo ""
    log "开始部署流程"
    
    # 检查是否在服务器上
    if [ ! -d "$PROJECT_DIR" ]; then
        print_error "项目目录不存在: $PROJECT_DIR"
        print_info "请先上传代码到服务器"
        exit 1
    fi
    
    # 备份
    if [ "$BACKUP" = true ]; then
        create_backup_dir
        backup_database
        backup_redis
        backup_uploads
    fi
    
    # 更新代码
    pull_code
    
    # 先构建镜像，减少停机窗口
    build_images

    # 停止服务
    stop_services

    # 启动服务
    start_services
    
    # 等待就绪
    wait_for_services
    
    # 运行迁移
    run_migrations
    
    # 显示状态
    show_status
    
    # 显示摘要
    show_summary
    
    log "部署完成"
}

# 执行主流程
main "$@"
