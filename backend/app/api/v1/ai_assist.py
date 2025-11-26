"""
AI辅助功能API - 自动生成角色档案、冲突检测、一致性检查
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.db.base import get_db

# 导入Agent
try:
    from app.services.agents.agents import CharacterDesignerAgent, EventValidatorAgent, WorldArchitectAgent, ChapterLogicChecker
    AGENTS_AVAILABLE = True
    _CharacterAgent = CharacterDesignerAgent
    _EventAgent = EventValidatorAgent
    _WorldAgent = WorldArchitectAgent
    _ChapterLogicAgent = ChapterLogicChecker
except ImportError as e:
    print(f"⚠️ Agent模块导入失败: {e}")
    AGENTS_AVAILABLE = False
    _CharacterAgent = None  # type: ignore
    _EventAgent = None  # type: ignore
    _WorldAgent = None  # type: ignore
    _ChapterLogicAgent = None  # type: ignore

router = APIRouter(prefix="/api/v1/ai", tags=["ai_assist"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class CharacterGenerateRequest(BaseModel):
    """角色生成请求"""
    name: str
    brief_description: str
    genre: str = "奇幻"
    role: str = "主角"
    project_id: Optional[int] = None


class CharacterGenerateResponse(BaseModel):
    """角色生成响应"""
    status: str
    character: Dict[str, Any]


class ConflictDetectRequest(BaseModel):
    """冲突检测请求"""
    plot_events: List[Dict[str, Any]]
    project_id: Optional[int] = None


class ConflictDetectResponse(BaseModel):
    """冲突检测响应"""
    status: str
    has_conflicts: bool
    validation_result: Dict[str, Any]


class ConsistencyCheckRequest(BaseModel):
    """一致性检查请求"""
    world_settings: List[Dict[str, Any]]
    new_content: str
    project_id: Optional[int] = None


class ConsistencyCheckResponse(BaseModel):
    """一致性检查响应"""
    status: str
    is_consistent: bool
    consistency_check: Dict[str, Any]


class ChapterLogicIssue(BaseModel):
    """章节逻辑问题"""
    character_name: str
    technique_name: str
    issue_type: str  # "未掌握功法" | "境界不足"
    description: str
    suggestion: str


class ChapterLogicCheckRequest(BaseModel):
    """章节逻辑检查请求"""
    chapter_id: int
    project_id: int


class ChapterLogicCheckResponse(BaseModel):
    """章节逻辑检查响应"""
    status: str
    has_issues: bool
    issues: List[ChapterLogicIssue]
    summary: str


# ============================================================================
# API端点
# ============================================================================

@router.post("/generate-character", response_model=CharacterGenerateResponse)
async def generate_character(
    request: CharacterGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    自动生成角色档案 ✨

    使用CharacterDesignerAgent基于简单描述生成完整的角色档案，
    包括外貌、性格、背景、动机、能力等多个维度。

    参数:
    - name: 角色名称
    - brief_description: 简单描述
    - genre: 小说类型（奇幻、科幻、现代等）
    - role: 角色定位（主角、配角、反派等）
    - project_id: 项目ID（可选）

    返回:
    - character: 完整的角色档案
    """
    if not AGENTS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent服务暂不可用"
        )

    try:
        # ✅ 如果提供了 project_id，验证项目所有权
        if request.project_id:
            project = db.query(Project).filter(
                Project.id == request.project_id,
                Project.user_id == current_user.id
            ).first()

            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # 创建人物设计师Agent
        if _CharacterAgent is None:
            raise RuntimeError("CharacterDesignerAgent不可用")
        agent = _CharacterAgent()
        
        # 构建提示词
        prompt = f"""请创建完整的角色档案：

【基本信息】
- 角色名称：{request.name}
- 简要描述：{request.brief_description}
- 小说类型：{request.genre}
- 角色定位：{request.role}

【要求】
请提供详细的角色设定，包括：
1. **外貌特征**：身高、体型、面容、发型、标志性特征等
2. **性格特点**：主要性格特征、优点、缺点、性格矛盾等
3. **背景故事**：出身、成长经历、重要事件、家庭关系等
4. **核心动机**：目标、欲望、恐惧、信念等
5. **能力技能**：特殊能力、专业技能、战斗能力等
6. **人物关系**：与其他角色的关系（如果适用）
7. **成长空间**：角色可能的发展方向和成长弧光

请以结构化的方式输出，便于后续使用。
"""
        
        # 调用Agent生成
        result = agent.process(
            prompt,
            context={
                "genre": request.genre,
                "role": request.role,
                "project_id": request.project_id
            }
        )
        
        # 构建响应
        return CharacterGenerateResponse(
            status="success",
            character={
                "name": request.name,
                "genre": request.genre,
                "role": request.role,
                "profile": result,
                "generated_at": datetime.now().isoformat(),
                "generated_by": f"CharacterDesignerAgent (用户: {current_user.username})"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"角色生成失败: {str(e)}"
        )


@router.post("/detect-conflicts", response_model=ConflictDetectResponse)
async def detect_conflicts(
    request: ConflictDetectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    检测情节冲突 ✨

    使用EventValidatorAgent分析事件序列，检测逻辑矛盾、
    时间线错误、因果关系问题等。

    参数:
    - plot_events: 事件列表，每个事件包含章节号和内容
    - project_id: 项目ID（可选）

    返回:
    - has_conflicts: 是否存在冲突
    - validation_result: 详细的验证结果
    """
    if not AGENTS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent服务暂不可用"
        )

    try:
        # ✅ 如果提供了 project_id，验证项目所有权
        if request.project_id:
            project = db.query(Project).filter(
                Project.id == request.project_id,
                Project.user_id == current_user.id
            ).first()

            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # 创建事件验证官Agent
        if _EventAgent is None:
            raise RuntimeError("EventValidatorAgent不可用")
        agent = _EventAgent()
        
        # 格式化事件序列
        events_text = "\n".join([
            f"【第{event.get('chapter', '?')}章】{event.get('content', '')}"
            for event in request.plot_events
        ])
        
        # 调用Agent验证
        result = agent.validate_events(
            events_text,
            context={
                "project_id": request.project_id,
                "total_events": len(request.plot_events)
            }
        )
        
        # 解析是否有冲突（简单判断，可以优化）
        validation_text = result.get("validation_result", "")
        has_conflicts = any([
            "冲突" in validation_text,
            "矛盾" in validation_text,
            "不一致" in validation_text,
            "问题" in validation_text
        ])
        
        # 构建响应
        return ConflictDetectResponse(
            status="success",
            has_conflicts=has_conflicts,
            validation_result={
                "raw_result": result,
                "events_checked": len(request.plot_events),
                "validation_summary": validation_text[:500] + "..." if len(validation_text) > 500 else validation_text,
                "checked_at": datetime.now().isoformat(),
                "checked_by": f"EventValidatorAgent (用户: {current_user.username})"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"冲突检测失败: {str(e)}"
        )


@router.post("/check-consistency", response_model=ConsistencyCheckResponse)
async def check_consistency(
    request: ConsistencyCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    检查世界观一致性 ✨

    使用WorldArchitectAgent验证新内容是否与已有世界观设定一致，
    检测逻辑冲突和设定矛盾。

    参数:
    - world_settings: 已有的世界观设定列表
    - new_content: 需要检查的新内容
    - project_id: 项目ID（可选）

    返回:
    - is_consistent: 是否一致
    - consistency_check: 详细的检查结果
    """
    if not AGENTS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent服务暂不可用"
        )

    try:
        # ✅ 如果提供了 project_id，验证项目所有权
        if request.project_id:
            project = db.query(Project).filter(
                Project.id == request.project_id,
                Project.user_id == current_user.id
            ).first()

            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # 创建世界观架构师Agent
        if _WorldAgent is None:
            raise RuntimeError("WorldArchitectAgent不可用")
        agent = _WorldAgent()
        
        # 格式化已有设定
        settings_text = "\n".join([
            f"【{setting.get('type', '未分类')}】{setting.get('name', '未命名')}: {setting.get('content', '')}"
            for setting in request.world_settings
        ])
        
        # 构建检查提示词
        prompt = f"""请检查以下新内容是否与已有世界观设定保持一致：

【已有世界观设定】
{settings_text}

【待检查的新内容】
{request.new_content}

【检查要求】
请进行以下分析：
1. **逻辑一致性**：新内容是否与已有设定在逻辑上一致
2. **冲突检测**：是否存在直接矛盾或冲突
3. **科学性验证**：是否符合已设定的物理规则和社会规则
4. **一致性评分**：给出0-1的一致性评分（0=完全冲突，1=完全一致）
5. **改进建议**：如果存在问题，提供具体的修改建议

请以清晰、结构化的方式输出结果。
"""
        
        # 调用Agent检查
        result = agent.process(
            prompt,
            context={
                "project_id": request.project_id,
                "settings_count": len(request.world_settings)
            }
        )
        
        # 解析是否一致（简单判断，可以优化）
        result_lower = result.lower()
        is_consistent = not any([
            "冲突" in result,
            "矛盾" in result,
            "不一致" in result,
            "违反" in result,
            "inconsistent" in result_lower,
            "conflict" in result_lower
        ])
        
        # 尝试提取一致性评分（简单实现）
        consistency_score = 0.8 if is_consistent else 0.3  # 默认值
        
        # 构建响应
        return ConsistencyCheckResponse(
            status="success",
            is_consistent=is_consistent,
            consistency_check={
                "raw_result": result,
                "settings_checked": len(request.world_settings),
                "consistency_score": consistency_score,
                "analysis_summary": result[:500] + "..." if len(result) > 500 else result,
                "checked_at": datetime.now().isoformat(),
                "checked_by": f"WorldArchitectAgent (用户: {current_user.username})"
            }
        )
    except HTTPException:
        raise


@router.post("/check-chapter-logic", response_model=ChapterLogicCheckResponse)
async def check_chapter_logic(
    request: ChapterLogicCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """检查章节逻辑 - 验证角色功法使用和境界要求 ✨"""
    if not AGENTS_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent服务暂不可用"
        )

    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or access denied"
        )

    # 导入必要的模型
    from app.models.project import Chapter
    from app.models.character import Character, CharacterTechnique
    from app.models.setting import SettingItem, SettingCollection

    # 获取章节内容
    chapter = db.query(Chapter).filter(
        Chapter.id == request.chapter_id,
        Chapter.project_id == request.project_id
    ).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )

    if not chapter.content:
        return ChapterLogicCheckResponse(
            status="success",
            has_issues=False,
            issues=[],
            summary="章节内容为空，无需检查"
        )

    # 获取项目所有角色及其功法
    characters = db.query(Character).filter(
        Character.project_id == request.project_id
    ).all()

    character_techniques_map = {}
    character_realms = {}

    for char in characters:
        # 获取角色已掌握的功法
        techniques = db.query(CharacterTechnique).filter(
            CharacterTechnique.character_id == char.id
        ).all()
        technique_names = []
        for ct in techniques:
            item = db.query(SettingItem).filter(
                SettingItem.id == ct.technique_item_id
            ).first()
            if item:
                technique_names.append(item.name)

        character_techniques_map[char.name] = technique_names

        # 获取角色当前境界
        if char.current_realm_item_id:
            realm_item = db.query(SettingItem).filter(
                SettingItem.id == char.current_realm_item_id
            ).first()
            character_realms[char.name] = realm_item.name if realm_item else "未知"
        else:
            character_realms[char.name] = "未知"

    # 获取所有功法及其需求境界
    technique_requirements = {}
    technique_collections = db.query(SettingCollection).filter(
        SettingCollection.project_id == request.project_id,
        SettingCollection.category == "technique_system"
    ).all()

    for collection in technique_collections:
        items = db.query(SettingItem).filter(
            SettingItem.collection_id == collection.id
        ).all()
        for item in items:
            # 从tags中解析需求境界
            req_realm = "未知"
            if item.tags:
                import json
                try:
                    tags = json.loads(item.tags) if isinstance(item.tags, str) else item.tags
                    if isinstance(tags, list):
                        for tag in tags:
                            if isinstance(tag, str) and tag.startswith("REQ_REALM:"):
                                req_realm = tag.replace("REQ_REALM:", "")
                                break
                except (json.JSONDecodeError, ValueError):
                    pass
            technique_requirements[item.name] = req_realm

    # 调用Agent进行检查
    agent = _ChapterLogicAgent()
    check_result = agent.check_chapter_logic(
        chapter_content=chapter.content,
        character_techniques_map=character_techniques_map,
        character_realms=character_realms,
        technique_requirements=technique_requirements,
        context={"project_id": request.project_id, "chapter_id": request.chapter_id}
    )

    # 构建响应
    issues = []
    if "issues" in check_result and check_result["issues"]:
        for issue in check_result["issues"]:
            if isinstance(issue, dict):
                issues.append(ChapterLogicIssue(**issue))

    return ChapterLogicCheckResponse(
        status="success",
        has_issues=check_result.get("has_issues", False),
        issues=issues,
        summary=check_result.get("summary", "检查完成")
    )


# ============================================================================
# 健康检查端点
# ============================================================================

@router.get("/health")
async def ai_assist_health():
    """AI辅助服务健康检查"""
    return {
        "status": "ok",
        "agents_available": AGENTS_AVAILABLE,
        "available_features": [
            "generate-character",
            "detect-conflicts",
            "check-consistency"
        ] if AGENTS_AVAILABLE else [],
        "timestamp": datetime.now().isoformat()
    }
