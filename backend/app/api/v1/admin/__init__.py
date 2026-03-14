"""
管理控制台路由组
"""
from fastapi import APIRouter
from . import users, roles, logs, stats, query

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

router.include_router(users.router, prefix="/users", tags=["admin-users"])
router.include_router(roles.router, prefix="/roles", tags=["admin-roles"])
router.include_router(logs.router, prefix="/logs", tags=["admin-logs"])
router.include_router(stats.router, prefix="/stats", tags=["admin-stats"])
router.include_router(query.router, prefix="/query", tags=["admin-query"])
