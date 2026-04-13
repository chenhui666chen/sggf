"""
数据库查询管理 API
提供安全的 SQL 查询功能，包含权限控制、安全验证、审计日志
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.user import User
from app.core.permissions import require_admin
from app.utils.sql_validator import SQLValidator, SQLSecurityError
from app.models.admin_log import AdminOperationLog

router = APIRouter(prefix="/query", tags=["admin-query"])
logger = logging.getLogger(__name__)


@router.post("/execute")
async def execute_query(
    sql: str,
    description: Optional[str] = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    执行只读 SQL 查询
    
    安全限制：
    - 只允许 SELECT 查询
    - 自动添加 LIMIT 1000 限制
    - 禁止危险操作（DROP, DELETE, UPDATE 等）
    - 敏感数据自动脱敏
    - 查询超时 5 秒
    
    Args:
        sql: SQL 查询语句
        description: 查询描述（用于审计日志）
        db: 数据库会话
        current_user: 当前用户
        
    Returns:
        {
            "columns": ["id", "username", "email"],
            "data": [{"id": 1, "username": "admin", "email": "a***@example.com"}],
            "row_count": 1,
            "execution_time_ms": 15.5,
            "masked_fields": ["email"]
        }
    """
    start_time = time.time()
    
    # 1. SQL 安全验证
    is_safe, result = SQLValidator.validate(sql)
    if not is_safe:
        # 记录审计日志
        log_operation(
            db=db,
            user=current_user,
            sql=sql,
            status="rejected",
            error=result,
            description=description
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SQL 安全验证失败：{result}"
        )
    
    safe_sql = result
    
    try:
        # 2. 设置查询超时
        db.execute(text(f"SET statement_timeout = {SQLValidator.QUERY_TIMEOUT_MS}"))
        
        # 3. 执行查询
        query_result = db.execute(text(safe_sql))
        rows = query_result.fetchall()
        
        # 4. 获取列名
        columns = list(query_result.keys()) if hasattr(query_result, 'keys') else []
        
        # 5. 转换为字典列表
        data = []
        for row in rows:
            row_dict = dict(zip(columns, row)) if columns else {}
            data.append(row_dict)
        
        # 6. 数据脱敏
        masked_fields = []
        for col in columns:
            if SQLValidator.should_mask_field(col):
                masked_fields.append(col)
        
        if masked_fields:
            for i, row_dict in enumerate(data):
                data[i] = SQLValidator.mask_result(columns, row_dict)
        
        # 7. 计算执行时间
        execution_time_ms = (time.time() - start_time) * 1000
        
        # 8. 记录审计日志（成功）
        log_operation(
            db=db,
            user=current_user,
            sql=sql,
            status="success",
            row_count=len(data),
            execution_time_ms=execution_time_ms,
            description=description
        )
        
        return {
            "columns": columns,
            "data": data,
            "row_count": len(data),
            "execution_time_ms": round(execution_time_ms, 2),
            "masked_fields": masked_fields,
            "limit_applied": "LIMIT" not in sql.upper(),
            "warning": "查询结果已自动限制为 1000 行，敏感数据已脱敏" if masked_fields else "查询结果已自动限制为 1000 行"
        }
        
    except Exception as e:
        # 记录审计日志（失败）
        log_operation(
            db=db,
            user=current_user,
            sql=sql,
            status="error",
            error=str(e),
            description=description
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询执行失败：{str(e)}"
        )


@router.get("/history")
async def get_query_history(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    获取查询历史记录
    
    Args:
        page: 页码
        page_size: 每页数量
        db: 数据库会话
        current_user: 当前用户
        
    Returns:
        查询历史列表
    """
    try:
        # 查询最近的查询操作日志
        logs = db.query(AdminOperationLog).filter(
            AdminOperationLog.operation_type == "QUERY",
            AdminOperationLog.user_id == current_user.id
        ).order_by(
            AdminOperationLog.created_at.desc()
        ).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        
        total = db.query(AdminOperationLog).filter(
            AdminOperationLog.operation_type == "QUERY",
            AdminOperationLog.user_id == current_user.id
        ).count()
        
        history = []
        for log in logs:
            history.append({
                "id": log.id,
                "sql": log.details.get("sql", "") if log.details else "",
                "description": log.details.get("description", "") if log.details else "",
                "status": log.status,
                "row_count": log.details.get("row_count", 0) if log.details else 0,
                "execution_time_ms": log.details.get("execution_time_ms", 0) if log.details else 0,
                "created_at": log.created_at.isoformat() if log.created_at else None
            })
        
        return {
            "items": history,
            "total": total,
            "page": page,
            "page_size": page_size
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取查询历史失败：{str(e)}"
        )


@router.get("/tables")
async def get_database_tables(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    获取数据库表列表
    
    Args:
        db: 数据库会话
        current_user: 当前用户
        
    Returns:
        表列表及其基本信息
    """
    try:
        # 查询所有表
        result = db.execute(text("""
            SELECT 
                table_name,
                table_schema
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        
        tables = []
        for row in result:
            table_name = row[0]
            
            # 获取表的行数
            count_result = db.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            )
            row_count = count_result.scalar()
            
            tables.append({
                "name": table_name,
                "row_count": row_count
            })
        
        return {
            "tables": tables,
            "total": len(tables)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取表列表失败：{str(e)}"
        )


@router.get("/table-schema/{table_name}")
async def get_table_schema(
    table_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    获取表结构信息
    
    Args:
        table_name: 表名
        db: 数据库会话
        current_user: 当前用户
        
    Returns:
        表结构信息
    """
    try:
        # 验证表名安全性（防止 SQL 注入）
        if not table_name.isidentifier():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的表名"
            )
        
        # 查询列信息
        result = db.execute(text("""
            SELECT 
                column_name,
                data_type,
                is_nullable,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_name = :table_name
            ORDER BY ordinal_position
        """), {"table_name": table_name})
        
        columns = []
        for row in result:
            columns.append({
                "name": row[0],
                "type": row[1],
                "nullable": row[2] == "YES",
                "max_length": row[3],
                "precision": row[4],
                "scale": row[5],
                "sensitive": SQLValidator.should_mask_field(row[0])
            })
        
        # 查询索引信息
        index_result = db.execute(text("""
            SELECT 
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = :table_name
        """), {"table_name": table_name})
        
        indexes = []
        for row in index_result:
            indexes.append({
                "name": row[0],
                "definition": row[1]
            })
        
        return {
            "table_name": table_name,
            "columns": columns,
            "indexes": indexes,
            "sensitive_columns": [col["name"] for col in columns if col["sensitive"]]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取表结构失败：{str(e)}"
        )


def log_operation(
    db: Session,
    user: User,
    sql: str,
    status: str,
    error: Optional[str] = None,
    row_count: Optional[int] = None,
    execution_time_ms: Optional[float] = None,
    description: Optional[str] = None
):
    """
    记录查询操作日志
    
    Args:
        db: 数据库会话
        user: 操作用户
        sql: 执行的 SQL
        status: 操作状态（success/error/rejected）
        error: 错误信息
        row_count: 返回行数
        execution_time_ms: 执行时间
        description: 查询描述
    """
    try:
        # 对 SQL 进行脱敏（避免日志中暴露完整 SQL）
        # 如果 SQL 太长，只记录前 1000 字符
        sql_preview = sql[:1000] if len(sql) > 1000 else sql
        
        log = AdminOperationLog(
            user_id=user.id,
            username=user.username,
            operation_type="QUERY",
            resource="DATABASE",
            action="EXECUTE_QUERY",
            status=status,
            ip_address="",  # 可以从 request 中获取
            details={
                "sql": sql_preview,
                "description": description,
                "row_count": row_count,
                "execution_time_ms": execution_time_ms,
                "error": error
            }
        )
        
        db.add(log)
        db.commit()
        
    except Exception as e:
        # 日志记录失败不应影响主流程
        logger.debug(f"记录查询日志失败：{e}")
        db.rollback()
