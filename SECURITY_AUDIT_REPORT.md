# 🔒 小说写作系统 - 项目隔离安全审计报告

**审计日期**: 2025-11-13  
**审计范围**: 多用户环境下的数据安全性和项目隔离机制  
**审计结果**: ⚠️ **发现 5 个高危漏洞，3 个中危漏洞**

---

## 📋 执行摘要

本次审计全面检查了小说写作系统的项目隔离机制，发现了多个严重的安全漏洞，可能导致：
- ❌ **跨项目数据泄露**：用户可以访问其他用户的项目数据
- ❌ **未授权操作**：用户可以修改/删除其他用户的内容
- ❌ **WebSocket 房间劫持**：用户可以监听其他项目的实时消息
- ❌ **向量数据库污染**：不同项目的知识库数据可能混淆

**严重程度分布**:
- 🔴 **高危 (Critical)**: 5 个
- 🟠 **中危 (Medium)**: 3 个
- 🟢 **低危 (Low)**: 0 个

---

## 🔴 高危漏洞 (Critical)

### 1. WebSocket 房间未验证项目所有权 ⚠️⚠️⚠️

**位置**: `backend/app/websocket/manager.py:131-151`

**问题描述**:
```python
@sio.event
async def join_project(sid, data):
    """加入项目房间"""
    project_id = data.get('project_id')
    if not project_id:
        await sio.emit('error', {'message': '缺少 project_id'}, room=sid)
        return
    
    room = f'project_{project_id}'
    await sio.enter_room(sid, room)  # ❌ 没有验证用户是否拥有该项目
```

**安全风险**:
- 任何用户都可以加入任意项目的 WebSocket 房间
- 可以实时监听其他用户项目的工作流进度、生成内容等敏感信息
- 可能导致商业机密泄露

**影响范围**: 所有使用 WebSocket 实时通知的功能

**修复建议**:
```python
@sio.event
async def join_project(sid, data):
    """加入项目房间"""
    try:
        project_id = data.get('project_id')
        user_id = data.get('user_id')  # 需要从认证信息中获取
        
        if not project_id or not user_id:
            await sio.emit('error', {'message': '缺少必要参数'}, room=sid)
            return
        
        # ✅ 验证项目所有权
        from app.db.base import get_db
        from app.models.project import Project
        db = next(get_db())
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == user_id
        ).first()
        
        if not project:
            await sio.emit('error', {'message': '无权访问该项目'}, room=sid)
            return
        
        room = f'project_{project_id}'
        await sio.enter_room(sid, room)
        # ...
```

---

### 2. 统计 API 缺少项目所有权验证 ⚠️⚠️⚠️

**位置**: `backend/app/api/v1/statistics.py:17-165`

**问题描述**:
```python
@router.get("/workflow/stage-durations")
async def get_stage_durations(
    project_id: int | None = None,
    recent_count: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # ❌ 如果指定了 project_id，没有验证用户是否拥有该项目
    if project_id:
        query = text("""
            SELECT task_type, AVG(duration_seconds) as avg_duration_seconds
            FROM generation_history
            WHERE project_id = :project_id  # ❌ 直接使用 project_id
```

**安全风险**:
- 用户可以查询任意项目的统计数据
- 可能泄露其他用户的工作流耗时、任务执行情况等信息

**修复建议**:
```python
@router.get("/workflow/stage-durations")
async def get_stage_durations(
    project_id: int | None = None,
    recent_count: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # ✅ 验证项目所有权
    if project_id:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == current_user.id
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
    
    # 继续执行查询...
```

---

### 3. 工作流状态查询缺少验证 ⚠️⚠️⚠️

**位置**: `backend/app/api/v1/workflow.py:718-736`

**问题描述**:
```python
@router.get("/status/{project_id}")
async def get_workflow_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取工作流程状态"""
    try:
        status_data = await coordinator.get_workflow_status()
        return {
            "status": "success",
            "project_id": project_id,  # ❌ 没有验证项目所有权
            "workflow": status_data,
        }
```

**安全风险**:
- 用户可以查询任意项目的工作流状态
- 可能泄露其他用户的创作进度

**修复建议**: 添加项目所有权验证（同上）

---

### 4. 任务状态查询缺少项目关联验证 ⚠️⚠️

**位置**: `backend/app/api/v1/workflow.py:1081-1298`

**问题描述**:
```python
@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取任务状态"""
    # ❌ 只验证了 task_id 存在，没有验证任务所属的项目是否属于当前用户
    query = text("""
        SELECT task_id, status, result, error, created_at, completed_at
        FROM generation_history
        WHERE task_id = :task_id
    """)
```

**安全风险**:
- 用户可以通过猜测或枚举 task_id 查询其他用户的任务状态
- 可能泄露生成内容、错误信息等敏感数据

**修复建议**:
```python
@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取任务状态"""
    # ✅ 关联验证项目所有权
    query = text("""
        SELECT gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
        FROM generation_history gh
        INNER JOIN projects p ON gh.project_id = p.id
        WHERE gh.task_id = :task_id AND p.user_id = :user_id
    """)
    result = db.execute(query, {
        "task_id": task_id,
        "user_id": current_user.id
    }).fetchone()
```

---

### 5. 向量数据库查询缺少强制项目过滤 ⚠️⚠️

**位置**: `backend/app/api/v1/knowledge.py:49-93`

**问题描述**:
```python
@router.post("/search")
async def search_knowledge(
    request: SearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """向量搜索知识库"""
    kb = get_knowledge_base()
    results = kb.search(
        request.query, 
        k=request.k, 
        filter_type=request.filter_type,
        project_id=request.project_id  # ❌ project_id 是可选的，用户可以不传
    )
```

**安全风险**:
- 如果用户不传 `project_id`，会搜索所有项目的知识库
- 可能泄露其他用户的世界观设定、人物档案等创作内容
- 向量数据库中的 `project_id` 过滤是可选的，不够安全

**修复建议**:
```python
@router.post("/search")
async def search_knowledge(
    request: SearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """向量搜索知识库"""
    # ✅ 强制要求 project_id
    if not request.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id is required"
        )
    
    # ✅ 验证项目所有权
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    kb = get_knowledge_base()
    results = kb.search(
        request.query, 
        k=request.k, 
        filter_type=request.filter_type,
        project_id=request.project_id  # ✅ 已验证的 project_id
    )
```

---

## 🟠 中危漏洞 (Medium)

### 6. AI 辅助功能缺少项目验证 ⚠️

**位置**: `backend/app/api/v1/ai_assist.py:79-161`

**问题描述**:
```python
@router.post("/generate-character", response_model=CharacterGenerateResponse)
async def generate_character(
    request: CharacterGenerateRequest,
    current_user: User = Depends(get_current_user)
):
    # ❌ project_id 是可选的，没有验证
    result = agent.process(
        prompt,
        context={
            "genre": request.genre,
            "role": request.role,
            "project_id": request.project_id  # 可选，未验证
        }
    )
```

**安全风险**: 中等 - 虽然不会直接泄露数据，但可能导致资源滥用

**修复建议**: 如果提供了 `project_id`，应验证所有权

---

### 7. 知识库添加操作缺少项目验证 ⚠️

**位置**: `backend/app/api/v1/knowledge.py:96-199`

**问题描述**:
```python
@router.post("/world-setting")
async def add_world_setting(
    request: AddWorldSettingRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    # ❌ metadata 中的 project_id 未验证
    metadata = request.metadata or {}
    metadata["user_id"] = current_user.get("id")
    
    kb.add_world_setting(request.title, request.content, metadata)
```

**安全风险**: 用户可能向其他用户的项目添加知识库数据

**修复建议**: 验证 `metadata["project_id"]` 的所有权

---

### 8. 简单后端服务器存在多处权限验证不足 ⚠️

**位置**: `simple_backend_server.py` (多处)

**问题描述**: 虽然大部分端点都有验证，但代码质量参差不齐，存在潜在风险

**修复建议**: 统一使用 FastAPI 的依赖注入机制，废弃 `simple_backend_server.py`

---

## ✅ 做得好的地方

### 1. 数据库层面的隔离 ✅

**优点**:
- 所有主要 API 端点（projects, chapters, knowledge_base, reviews, memories）都正确验证了项目所有权
- 使用了级联删除（CASCADE）确保数据一致性
- 外键约束正确设置

**示例**:
```python
# ✅ 正确的验证模式
@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
```

### 2. 章节和评审 API 的权限验证 ✅

**优点**:
- 章节操作通过项目验证间接验证权限
- 评审操作通过章节→项目的双重验证

**示例**:
```python
# ✅ 双重验证
@router.post("/{chapter_id}/review", response_model=ReviewResponse)
async def create_review(
    chapter_id: int,
    review_data: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
```

### 3. 向量数据库支持项目过滤 ✅

**优点**:
- `NovelKnowledgeBase.search()` 支持 `project_id` 参数
- `delete_project()` 方法可以清理项目的向量数据

**问题**: 过滤是可选的，需要在 API 层强制执行

---

## 🛠️ 修复优先级

### P0 (立即修复)
1. ✅ WebSocket 房间验证
2. ✅ 统计 API 项目验证
3. ✅ 任务状态查询验证

### P1 (本周修复)
4. ✅ 向量搜索强制项目过滤
5. ✅ 工作流状态查询验证

### P2 (下周修复)
6. ✅ AI 辅助功能项目验证
7. ✅ 知识库操作项目验证
8. ✅ 废弃 simple_backend_server.py

---

## 📝 修复检查清单

- [x] WebSocket `join_project` 添加项目所有权验证 ✅
- [x] 统计 API 添加项目验证逻辑 ✅
- [x] 工作流状态 API 添加验证 ✅
- [x] 任务状态查询添加项目关联验证 ✅
- [x] 向量搜索强制要求 project_id 并验证 ✅
- [x] AI 辅助功能验证 project_id（如果提供）✅
- [x] 知识库添加操作验证 project_id ✅
- [ ] 编写集成测试验证修复效果
- [ ] 进行渗透测试
- [x] 更新安全文档 ✅

---

## 🔍 测试建议

### 1. 跨用户访问测试
```python
# 测试用例：用户A尝试访问用户B的项目
def test_cross_user_access():
    # 创建两个用户
    user_a = create_user("alice")
    user_b = create_user("bob")
    
    # 用户B创建项目
    project_b = create_project(user_b, "Bob's Novel")
    
    # 用户A尝试访问
    response = client.get(
        f"/api/v1/projects/{project_b.id}",
        headers={"Authorization": f"Bearer {user_a.token}"}
    )
    
    assert response.status_code == 404  # 应该返回404而不是403
```

### 2. WebSocket 房间劫持测试
```python
def test_websocket_room_hijacking():
    # 用户A加入用户B的项目房间
    sio_client.emit('join_project', {'project_id': project_b.id})
    
    # 应该收到错误消息
    response = sio_client.receive()
    assert response['event'] == 'error'
```

---

## 📚 参考资料

- [OWASP Top 10 - Broken Access Control](https://owasp.org/Top10/A01_2021-Broken_Access_Control/)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)
- [SQLAlchemy Security Considerations](https://docs.sqlalchemy.org/en/14/faq/security.html)

---

**审计人员**: Augment Agent  
**审计工具**: 代码审查 + 静态分析  
**下次审计**: 修复完成后进行复审

