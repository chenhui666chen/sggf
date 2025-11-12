"""
知识库API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List
import json
import csv
import io

from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse
)
from app.core.security import get_current_user

# 导入向量库
try:
    from app.services.agents.knowledge_base import NovelKnowledgeBase
    VECTOR_DB_AVAILABLE = True
    _VectorKBType = NovelKnowledgeBase
except ImportError as e:
    VECTOR_DB_AVAILABLE = False
    _VectorKBType = None  # type: ignore
    print(f"⚠️ 向量库未启用: {e}")
    print("   只使用数据库存储，语义搜索功能将不可用")

router = APIRouter(prefix="/api/v1/projects", tags=["knowledge_base"])

# 全局向量库实例
_vector_kb = None  # type: ignore

def get_vector_kb():
    """获取向量库实例"""
    global _vector_kb
    if not VECTOR_DB_AVAILABLE or _VectorKBType is None:
        return None
    if _vector_kb is None:
        try:
            _vector_kb = _VectorKBType()
        except Exception as e:
            print(f"⚠️ 向量库初始化失败: {e}")
            return None
    return _vector_kb

def sync_to_vector_db(kb_type: str, name: str, content: str, metadata: dict | None = None):
    """同步到向量数据库"""
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return  # 向量库不可用，静默跳过
    
    try:
        meta = metadata or {}
        if kb_type == "world":
            vector_kb.add_world_setting(name, content, meta)
        elif kb_type == "character":
            vector_kb.add_character(name, content, meta)
        elif kb_type == "plot":
            vector_kb.add_chapter(0, name, content, meta)  # 情节使用chapter方法
        elif kb_type == "chapter":
            # 提取章节号（如果在metadata中提供）
            chapter_num = int(metadata.get("chapter_number", 0)) if metadata and "chapter_number" in metadata else 0
            vector_kb.add_chapter(chapter_num, name, content, meta)
        print(f"✅ 已同步到向量库: {kb_type} - {name}")
    except Exception as e:
        print(f"⚠️ 向量库同步失败: {e}")


@router.get("/{project_id}/knowledge-base")
async def get_knowledge_base(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的知识库"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # 直接在数据库查询时按类型过滤，避免类型检查问题
    world_settings = db.query(KnowledgeBase).filter(
        KnowledgeBase.project_id == project_id,
        KnowledgeBase.type == "world"
    ).all()

    characters = db.query(KnowledgeBase).filter(
        KnowledgeBase.project_id == project_id,
        KnowledgeBase.type == "character"
    ).all()

    plot_outline = db.query(KnowledgeBase).filter(
        KnowledgeBase.project_id == project_id,
        KnowledgeBase.type == "plot"
    ).all()

    # 转换为Pydantic模型以便序列化
    return {
        "world_settings": [KnowledgeBaseResponse.from_orm(item) for item in world_settings],
        "characters": [KnowledgeBaseResponse.from_orm(item) for item in characters],
        "plot_outline": [KnowledgeBaseResponse.from_orm(item) for item in plot_outline]
    }


@router.post("/{project_id}/world-settings", response_model=KnowledgeBaseResponse)
async def add_world_setting(
    project_id: int,
    kb_data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """添加世界观设定"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = KnowledgeBase(
        project_id=project_id,
        type="world",
        name=kb_data.name,
        content=kb_data.content
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    # 🆕 同步到向量数据库
    if kb_data.content:  # 只在内容不为空时同步
        sync_to_vector_db(
            kb_type="world",
            name=kb_data.name,
            content=kb_data.content,
            metadata={"project_id": str(project_id), "kb_id": kb.id}  # 🎯 project_id 转字符串
        )
    
    return kb


@router.post("/{project_id}/characters", response_model=KnowledgeBaseResponse)
async def add_character(
    project_id: int,
    kb_data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """添加人物设定"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = KnowledgeBase(
        project_id=project_id,
        type="character",
        name=kb_data.name,
        content=kb_data.content
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    # 🆕 同步到向量数据库
    if kb_data.content:  # 只在内容不为空时同步
        sync_to_vector_db(
            kb_type="character",
            name=kb_data.name,
            content=kb_data.content,
            metadata={"project_id": str(project_id), "kb_id": kb.id}  # 🎯 project_id 转字符串
        )
    
    return kb


@router.post("/{project_id}/plot-outline", response_model=KnowledgeBaseResponse)
async def add_plot_outline(
    project_id: int,
    kb_data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """添加情节大纲"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = KnowledgeBase(
        project_id=project_id,
        type="plot",
        name=kb_data.name,
        content=kb_data.content
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    # 🆕 同步到向量数据库
    if kb_data.content:  # 只在内容不为空时同步
        sync_to_vector_db(
            kb_type="plot",
            name=kb_data.name,
            content=kb_data.content,
            metadata={"project_id": str(project_id), "kb_id": kb.id}  # 🎯 project_id 转字符串
        )
    
    return kb


@router.put("/{project_id}/knowledge-base/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    project_id: int,
    kb_id: int,
    kb_data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新知识库项"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.project_id == project_id
    ).first()
    
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base item not found"
        )
    
    for key, value in kb_data.dict(exclude_unset=True).items():
        setattr(kb, key, value)
    
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


@router.delete("/{project_id}/knowledge-base/{kb_id}")
async def delete_knowledge_base(
    project_id: int,
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除知识库项"""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.project_id == project_id
    ).first()
    
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base item not found"
        )
    
    db.delete(kb)
    db.commit()
    return {"message": "Knowledge base item deleted successfully"}


@router.post("/{project_id}/knowledge-base/batch-import")
async def batch_import_knowledge(
    project_id: int,
    file: UploadFile = File(...),
    kb_type: str = "world",  # world, character, plot
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量导入知识库
    支持CSV、JSON、Markdown格式
    """
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 验证类型
    if kb_type not in ["world", "character", "plot"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid knowledge base type. Must be 'world', 'character', or 'plot'"
        )
    
    try:
        # 读取文件内容
        content = await file.read()
        filename = file.filename or ""
        
        # 根据文件类型解析
        items = []
        
        if filename.endswith('.csv'):
            # 解析CSV
            items = parse_csv(content.decode('utf-8'))
        elif filename.endswith('.json'):
            # 解析JSON
            items = parse_json(content.decode('utf-8'))
        elif filename.endswith('.md') or filename.endswith('.markdown'):
            # 解析Markdown
            items = parse_markdown(content.decode('utf-8'))
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file format. Only CSV, JSON, and Markdown are supported."
            )
        
        # 批量创建知识库条目
        imported_count = 0
        for item in items:
            name = item.get('name', 'Untitled')
            content = item.get('content', '')
            
            kb = KnowledgeBase(
                project_id=project_id,
                type=kb_type,
                name=name,
                content=content
            )
            db.add(kb)
            
            # 同步到向量数据库
            if content:
                sync_to_vector_db(
                    kb_type=kb_type,
                    name=name,
                    content=content,
                    metadata={"project_id": str(project_id)}  # 🎯 project_id 转字符串
                )
            
            imported_count += 1
        
        db.commit()
        
        return {
            "message": "Import successful",
            "imported": imported_count,
            "type": kb_type
        }
        
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File encoding error. Please use UTF-8 encoding."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}"
        )


def parse_csv(content: str) -> List[dict]:
    """
    解析CSV文件
    预期格式：name,content
    """
    items = []
    reader = csv.DictReader(io.StringIO(content))
    
    for row in reader:
        if 'name' in row and 'content' in row:
            items.append({
                'name': row['name'].strip(),
                'content': row['content'].strip()
            })
    
    return items


def parse_json(content: str) -> List[dict]:
    """
    解析JSON文件
    预期格式：
    [
        {"name": "xxx", "content": "xxx"},
        {"name": "xxx", "content": "xxx"}
    ]
    """
    try:
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("JSON must be an array of objects")
        
        items = []
        for item in data:
            if isinstance(item, dict) and 'name' in item:
                items.append({
                    'name': item['name'],
                    'content': item.get('content', '')
                })
        
        return items
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {str(e)}")


def parse_markdown(content: str) -> List[dict]:
    """
    解析Markdown文件
    预期格式：
    # 条目名称1
    内容...
    
    # 条目名称2
    内容...
    """
    items = []
    lines = content.split('\n')
    
    current_name = None
    current_content = []
    
    for line in lines:
        # 检测标题（以#开头）
        if line.strip().startswith('#'):
            # 保存上一个条目
            if current_name:
                items.append({
                    'name': current_name,
                    'content': '\n'.join(current_content).strip()
                })
            
            # 开始新条目
            current_name = line.strip().lstrip('#').strip()
            current_content = []
        else:
            # 添加内容
            if current_name:
                current_content.append(line)
    
    # 保存最后一个条目
    if current_name:
        items.append({
            'name': current_name,
            'content': '\n'.join(current_content).strip()
        })
    
    return items


@router.get("/{project_id}/knowledge-base/export")
async def export_knowledge_base(
    project_id: int,
    format: str = "json",  # json, markdown, csv
    kb_type: str | None = None,  # 可选：指定类型
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    导出知识库
    支持JSON、Markdown、CSV格式
    """
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 查询知识库条目
    query = db.query(KnowledgeBase).filter(KnowledgeBase.project_id == project_id)
    
    # 如果指定了类型，过滤
    if kb_type:
        query = query.filter(KnowledgeBase.type == kb_type)
    
    kb_items = query.all()
    
    # 根据格式生成内容
    if format == "json":
        content = export_to_json(kb_items)
        media_type = "application/json"
        filename = f"knowledge_base_{project_id}.json"
    elif format == "markdown":
        content = export_to_markdown(kb_items)
        media_type = "text/markdown"
        filename = f"knowledge_base_{project_id}.md"
    elif format == "csv":
        content = export_to_csv(kb_items)
        media_type = "text/csv"
        filename = f"knowledge_base_{project_id}.csv"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid format. Must be 'json', 'markdown', or 'csv'"
        )
    
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


def export_to_json(kb_items: List[KnowledgeBase]) -> str:
    """导出为JSON格式"""
    data = []
    for item in kb_items:
        created_at = getattr(item, 'created_at', None)
        updated_at = getattr(item, 'updated_at', None)
        data.append({
            "id": item.id,
            "type": item.type,
            "name": item.name,
            "content": item.content,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        })
    return json.dumps(data, ensure_ascii=False, indent=2)


def export_to_markdown(kb_items: List[KnowledgeBase]) -> str:
    """导出为Markdown格式"""
    lines = ["# Knowledge Base Export\n"]
    
    # 按类型分组
    grouped = {}
    for item in kb_items:
        if item.type not in grouped:
            grouped[item.type] = []
        grouped[item.type].append(item)
    
    # 生成Markdown
    type_names = {
        "world": "World Settings",
        "character": "Characters",
        "plot": "Plot Outline"
    }
    
    for kb_type, items in grouped.items():
        lines.append(f"\n## {type_names.get(kb_type, kb_type)}\n")
        for item in items:
            lines.append(f"\n### {item.name}\n")
            lines.append(f"{item.content}\n")
    
    return "\n".join(lines)


def export_to_csv(kb_items: List[KnowledgeBase]) -> str:
    """导出为CSV格式"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入表头
    writer.writerow(["id", "type", "name", "content", "created_at", "updated_at"])
    
    # 写入数据
    for item in kb_items:
        created_at = getattr(item, 'created_at', None)
        updated_at = getattr(item, 'updated_at', None)
        writer.writerow([
            item.id,
            item.type,
            item.name,
            item.content or "",
            created_at.isoformat() if created_at else "",
            updated_at.isoformat() if updated_at else "",
        ])
    
    return output.getvalue()

