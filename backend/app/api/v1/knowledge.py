"""
知识库API路由 - 向量搜索和知识管理
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from pydantic import BaseModel
import sys
import os

# 添加根目录到系统路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from app.db.base import get_db
from app.core.security import get_current_user
from knowledge_base import NovelKnowledgeBase

# 请求模型
class SearchRequest(BaseModel):
    query: str
    k: int = 5
    filter_type: str | None = None
    project_id: int | None = None  # 🆕 新增：项目隔离

class AddWorldSettingRequest(BaseModel):
    title: str
    content: str
    metadata: Dict[str, Any] | None = None

class AddCharacterRequest(BaseModel):
    name: str
    profile: str
    metadata: Dict[str, Any] | None = None

class AddChapterRequest(BaseModel):
    chapter_num: int
    title: str
    content: str
    metadata: Dict[str, Any] | None = None

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

# 全局知识库实例
_knowledge_base: NovelKnowledgeBase | None = None

def get_knowledge_base() -> NovelKnowledgeBase:
    """获取知识库实例"""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = NovelKnowledgeBase()
    return _knowledge_base


@router.post("/search")
async def search_knowledge(
    request: SearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    向量搜索知识库
    
    请求体:
    {
        "query": "搜索查询",
        "k": 5,
        "filter_type": "character",  // 可选: world_setting, character, chapter
        "project_id": 1  // 🆕 强烈推荐：确保项目隔离
    }
    """
    try:
        kb = get_knowledge_base()
        results = kb.search(
            request.query, 
            k=request.k, 
            filter_type=request.filter_type,
            project_id=request.project_id  # 🎯 使用项目过滤
        )
        
        # 转换结果为JSON格式
        search_results = [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in results
        ]
        
        return {
            "status": "success",
            "query": request.query,
            "count": len(search_results),
            "results": search_results,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜索失败: {str(e)}",
        )


@router.post("/world-setting")
async def add_world_setting(
    request: AddWorldSettingRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    添加世界观设定
    
    请求体:
    {
        "title": "世界观标题",
        "content": "世界观内容",
        "metadata": {"project_id": 1}
    }
    """
    try:
        kb = get_knowledge_base()
        
        # 添加用户ID到元数据
        metadata = request.metadata or {}
        metadata["user_id"] = current_user.get("id")
        
        kb.add_world_setting(request.title, request.content, metadata)
        
        return {
            "status": "success",
            "message": f"世界观设定 '{request.title}' 已添加",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加失败: {str(e)}",
        )


@router.post("/character")
async def add_character(
    request: AddCharacterRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    添加角色档案
    
    请求体:
    {
        "name": "角色名称",
        "profile": "角色档案",
        "metadata": {"project_id": 1}
    }
    """
    try:
        kb = get_knowledge_base()
        
        # 添加用户ID到元数据
        metadata = request.metadata or {}
        metadata["user_id"] = current_user.get("id")
        
        kb.add_character(request.name, request.profile, metadata)
        
        return {
            "status": "success",
            "message": f"角色 '{request.name}' 已添加",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加失败: {str(e)}",
        )


@router.post("/chapter")
async def add_chapter(
    request: AddChapterRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    添加章节内容
    
    请求体:
    {
        "chapter_num": 1,
        "title": "章节标题",
        "content": "章节内容",
        "metadata": {"project_id": 1}
    }
    """
    try:
        kb = get_knowledge_base()
        
        # 添加用户ID到元数据
        metadata = request.metadata or {}
        metadata["user_id"] = current_user.get("id")
        
        kb.add_chapter(request.chapter_num, request.title, request.content, metadata)
        
        return {
            "status": "success",
            "message": f"第{request.chapter_num}章 '{request.title}' 已添加",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加失败: {str(e)}",
        )


@router.get("/character/{character_name}")
async def get_character_info(
    character_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取角色信息"""
    try:
        kb = get_knowledge_base()
        results = kb.get_character_info(character_name)
        
        character_info = [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in results
        ]
        
        return {
            "status": "success",
            "character_name": character_name,
            "count": len(character_info),
            "info": character_info,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询失败: {str(e)}",
        )


@router.get("/chapter/{chapter_num}")
async def get_chapter_summary(
    chapter_num: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取章节摘要"""
    try:
        kb = get_knowledge_base()
        results = kb.get_chapter_summary(chapter_num)
        
        chapter_summary = [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in results
        ]
        
        return {
            "status": "success",
            "chapter_num": chapter_num,
            "count": len(chapter_summary),
            "summary": chapter_summary,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询失败: {str(e)}",
        )
