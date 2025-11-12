"""
项目管理模块 - 管理小说创作项目的生命周期
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import os


class ProjectStatus(Enum):
    """项目状态"""
    PLANNING = "planning"           # 规划中
    IN_PROGRESS = "in_progress"     # 进行中
    REVIEW = "review"               # 审阅中
    REVISION = "revision"           # 修改中
    COMPLETED = "completed"         # 已完成
    ARCHIVED = "archived"           # 已归档


class TaskStatus(Enum):
    """任务状态"""
    TODO = "todo"                   # 待做
    IN_PROGRESS = "in_progress"     # 进行中
    COMPLETED = "completed"         # 已完成
    BLOCKED = "blocked"             # 被阻止


@dataclass
class Task:
    """任务"""
    task_id: str
    name: str
    description: str
    assigned_to: str                # 分配给哪个Agent
    status: TaskStatus = TaskStatus.TODO
    priority: int = 1               # 优先级 1-5
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    output: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "status": self.status.value,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "output": self.output,
            "dependencies": self.dependencies
        }


@dataclass
class Chapter:
    """章节"""
    chapter_num: int
    title: str
    description: str
    status: TaskStatus = TaskStatus.TODO
    content: Optional[str] = None
    word_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    feedback: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "chapter_num": self.chapter_num,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "content": self.content,
            "word_count": self.word_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "feedback": self.feedback
        }


class NovelProject:
    """小说项目管理"""
    
    def __init__(self, project_id: str, title: str, author: str, genre: str):
        """初始化项目"""
        self.project_id = project_id
        self.title = title
        self.author = author
        self.genre = genre
        self.status = ProjectStatus.PLANNING
        
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        
        # 项目内容
        self.concept: Optional[str] = None
        self.world_setting: Optional[str] = None
        self.characters: Dict[str, str] = {}
        self.plot_outline: Optional[str] = None
        self.chapters: Dict[int, Chapter] = {}
        
        # 任务管理
        self.tasks: Dict[str, Task] = {}
        self.task_counter = 0
        
        # 统计信息
        self.total_word_count = 0
        self.completed_chapters = 0
        self.total_chapters = 0
    
    def add_task(self, name: str, description: str, assigned_to: str, 
                priority: int = 1, dependencies: Optional[List[str]] = None) -> str:
        """添加任务"""
        self.task_counter += 1
        task_id = f"task_{self.task_counter}"
        
        task = Task(
            task_id=task_id,
            name=name,
            description=description,
            assigned_to=assigned_to,
            priority=priority,
            dependencies=dependencies or []
        )
        
        self.tasks[task_id] = task
        print(f"✓ 任务已添加: {name} (分配给 {assigned_to})")
        
        return task_id
    
    def update_task_status(self, task_id: str, status: TaskStatus, output: Optional[str] = None):
        """更新任务状态"""
        if task_id not in self.tasks:
            print(f"✗ 任务不存在: {task_id}")
            return
        
        task = self.tasks[task_id]
        task.status = status
        task.updated_at = datetime.now()
        
        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now()
            if output:
                task.output = output
        
        print(f"✓ 任务状态已更新: {task.name} → {status.value}")
    
    def add_chapter(self, chapter_num: int, title: str, description: str):
        """添加章节"""
        chapter = Chapter(
            chapter_num=chapter_num,
            title=title,
            description=description
        )
        
        self.chapters[chapter_num] = chapter
        self.total_chapters += 1
        print(f"✓ 章节已添加: 第{chapter_num}章 - {title}")
    
    def update_chapter(self, chapter_num: int, content: Optional[str] = None, 
                      status: Optional[TaskStatus] = None, feedback: Optional[str] = None):
        """更新章节"""
        if chapter_num not in self.chapters:
            print(f"✗ 章节不存在: 第{chapter_num}章")
            return
        
        chapter = self.chapters[chapter_num]
        
        if content:
            chapter.content = content
            chapter.word_count = len(content.split())
            self.total_word_count = sum(c.word_count for c in self.chapters.values())
        
        if status:
            chapter.status = status
            if status == TaskStatus.COMPLETED:
                self.completed_chapters += 1
        
        if feedback:
            chapter.feedback.append(feedback)
        
        chapter.updated_at = datetime.now()
        print(f"✓ 章节已更新: 第{chapter_num}章")
    
    def get_task_by_agent(self, agent_name: str) -> List[Task]:
        """获取分配给特定Agent的所有任务"""
        return [task for task in self.tasks.values() if task.assigned_to == agent_name]
    
    def get_pending_tasks(self) -> List[Task]:
        """获取所有待处理任务"""
        return [task for task in self.tasks.values() 
                if task.status in [TaskStatus.TODO, TaskStatus.IN_PROGRESS]]
    
    def get_blocked_tasks(self) -> List[Task]:
        """获取所有被阻止的任务"""
        return [task for task in self.tasks.values() if task.status == TaskStatus.BLOCKED]
    
    def get_project_progress(self) -> Dict[str, Any]:
        """获取项目进度"""
        total_tasks = len(self.tasks)
        completed_tasks = len([t for t in self.tasks.values() 
                              if t.status == TaskStatus.COMPLETED])
        
        progress_percent = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
        
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": len(self.get_pending_tasks()),
            "blocked_tasks": len(self.get_blocked_tasks()),
            "progress_percent": progress_percent,
            "total_chapters": self.total_chapters,
            "completed_chapters": self.completed_chapters,
            "total_word_count": self.total_word_count
        }
    
    def print_project_summary(self):
        """打印项目摘要"""
        print(f"\n{'='*70}")
        print(f"【项目摘要】{self.title}")
        print(f"{'='*70}")
        print(f"项目ID: {self.project_id}")
        print(f"作者: {self.author}")
        print(f"类型: {self.genre}")
        print(f"状态: {self.status.value}")
        print(f"创建时间: {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        progress = self.get_project_progress()
        print(f"\n【进度】")
        print(f"  任务: {progress['completed_tasks']}/{progress['total_tasks']} "
              f"({progress['progress_percent']:.1f}%)")
        print(f"  章节: {progress['completed_chapters']}/{progress['total_chapters']}")
        print(f"  字数: {progress['total_word_count']}")
        
        if self.concept:
            print(f"\n【概念】")
            print(f"  {self.concept[:100]}...")
        
        if self.characters:
            print(f"\n【人物】")
            for name in list(self.characters.keys())[:3]:
                print(f"  - {name}")
            if len(self.characters) > 3:
                print(f"  ... 还有 {len(self.characters) - 3} 个人物")
        
        print(f"{'='*70}\n")
    
    def export_to_json(self, filepath: str):
        """导出项目为JSON"""
        data = {
            "project_id": self.project_id,
            "title": self.title,
            "author": self.author,
            "genre": self.genre,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "concept": self.concept,
            "world_setting": self.world_setting,
            "characters": self.characters,
            "plot_outline": self.plot_outline,
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
            "chapters": {num: chapter.to_dict() for num, chapter in self.chapters.items()},
            "progress": self.get_project_progress()
        }
        
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 项目已导出: {filepath}")
    
    @classmethod
    def load_from_json(cls, filepath: str) -> 'NovelProject':
        """从JSON加载项目"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        project = cls(
            project_id=data['project_id'],
            title=data['title'],
            author=data['author'],
            genre=data['genre']
        )
        
        project.status = ProjectStatus(data['status'])
        project.concept = data.get('concept')
        project.world_setting = data.get('world_setting')
        project.characters = data.get('characters', {})
        project.plot_outline = data.get('plot_outline')
        
        print(f"✓ 项目已加载: {filepath}")
        return project


class ProjectManager:
    """项目管理器 - 管理多个项目"""
    
    def __init__(self):
        """初始化项目管理器"""
        self.projects: Dict[str, NovelProject] = {}
        self.current_project: Optional[NovelProject] = None
    
    def create_project(self, project_id: str, title: str, author: str, 
                      genre: str) -> NovelProject:
        """创建新项目"""
        project = NovelProject(project_id, title, author, genre)
        self.projects[project_id] = project
        self.current_project = project
        print(f"✓ 项目已创建: {title}")
        return project
    
    def get_project(self, project_id: str) -> Optional[NovelProject]:
        """获取项目"""
        return self.projects.get(project_id)
    
    def set_current_project(self, project_id: str) -> bool:
        """设置当前项目"""
        if project_id in self.projects:
            self.current_project = self.projects[project_id]
            print(f"✓ 当前项目已切换: {self.current_project.title}")
            return True
        return False
    
    def list_projects(self) -> List[NovelProject]:
        """列出所有项目"""
        return list(self.projects.values())
    
    def print_all_projects(self):
        """打印所有项目"""
        print(f"\n{'='*70}")
        print("【所有项目】")
        print(f"{'='*70}")
        
        for project in self.projects.values():
            progress = project.get_project_progress()
            print(f"\n{project.title}")
            print(f"  作者: {project.author}")
            print(f"  类型: {project.genre}")
            print(f"  状态: {project.status.value}")
            print(f"  进度: {progress['completed_tasks']}/{progress['total_tasks']} 任务")
            print(f"  字数: {progress['total_word_count']}")
        
        print(f"\n{'='*70}\n")

