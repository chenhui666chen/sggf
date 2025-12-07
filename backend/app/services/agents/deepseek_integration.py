"""
DeepSeek集成模块 - 处理AI生成内容和回调机制
"""

import json
import threading
import queue
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from .multi_agent_framework import MultiAgentNovelWritingFramework
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager


class GenerationTask:
    """生成任务类"""
    
    def __init__(self, task_id: str, task_type: str, project_id: int, user_id: int, 
                 params: Dict[str, Any], callback: Optional[Callable] = None):
        self.task_id = task_id
        self.task_type = task_type  # 'concept', 'world', 'character', 'plot', 'chapter'
        self.project_id = project_id
        self.user_id = user_id
        self.params = params
        self.callback = callback
        self.status = 'pending'  # pending, running, completed, failed
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now().isoformat()
        self.completed_at: Optional[str] = None


class DeepSeekIntegration:
    """DeepSeek集成管理器"""
    
    def __init__(self):
        """初始化DeepSeek集成"""
        self.framework = MultiAgentNovelWritingFramework()
        self.task_queue = queue.Queue()
        self.tasks = {}  # task_id -> GenerationTask
        self.callbacks = {}  # task_id -> callback_url
        self.worker_thread = None
        self.running = False
        self.tasks_lock = threading.Lock()  # ✅ 添加线程锁，保护tasks字典
    
    def start(self):
        """启动后台工作线程"""
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            print("✅ DeepSeek集成工作线程已启动")
    
    def stop(self):
        """停止后台工作线程"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
            print("✅ DeepSeek集成工作线程已停止")
    
    def _worker_loop(self):
        """后台工作循环"""
        while self.running:
            try:
                # 从队列获取任务（超时1秒）
                task = self.task_queue.get(timeout=1)
                self._process_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 工作线程错误: {e}")
    
    def _process_task(self, task: GenerationTask):
        """处理生成任务"""
        try:
            task.status = 'running'
            # ✅ 使用锁保护字典操作
            with self.tasks_lock:
                self.tasks[task.task_id] = task
            print(f"🔄 处理任务: {task.task_id} ({task.task_type})")
            print(f"📋 任务状态已更新: {task.status}（已加锁）")
            
            # 根据任务类型调用相应的框架方法
            if task.task_type == 'concept':
                result = self.framework.start_project(
                    project_title=task.params.get('title', ''),
                    genre=task.params.get('genre', ''),
                    initial_concept=task.params.get('description', '')
                )
            elif task.task_type == 'world':
                result = self.framework.build_world(
                    world_description=task.params.get('description', '')
                )
            elif task.task_type == 'character':
                result = self.framework.create_characters(
                    character_requirements=task.params.get('requirements', '')
                )
            elif task.task_type == 'plot':
                result = self.framework.design_plot(
                    plot_requirements=task.params.get('requirements', '')
                )
            elif task.task_type == 'chapter':
                result = self.framework.write_chapter(
                    chapter_num=task.params.get('chapter_number', 1),
                    chapter_requirements=task.params.get('requirements', '')
                )
            # 支持工作流程阶段
            elif task.task_type.startswith('stage_'):
                stage = task.task_type.replace('stage_', '')
                result = self._execute_workflow_stage(stage, task.params)
            else:
                raise ValueError(f"未知的任务类型: {task.task_type}")
            
            task.status = 'completed'
            task.result = result
            task.completed_at = datetime.now().isoformat()
            # ✅ 使用锁保护字典操作
            with self.tasks_lock:
                self.tasks[task.task_id] = task
            
            print(f"✅ 任务完成: {task.task_id}")
            print(f"📋 任务状态: {task.status}, 结果长度: {len(result) if result else 0} 字符（已加锁）")
            
            # 调用回调函数
            if task.callback:
                try:
                    task.callback(task)
                except Exception as e:
                    print(f"❌ 回调执行失败: {e}")
        
        except Exception as e:
            task.status = 'failed'
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
            # ✅ 使用锁保护字典操作
            with self.tasks_lock:
                self.tasks[task.task_id] = task
            
            print(f"❌ 任务失败: {task.task_id} - {e}")
            print(f"📋 任务状态: {task.status}, 错误: {task.error}（已加锁）")
            import traceback
            traceback.print_exc()
            
            # 调用回调函数
            if task.callback:
                try:
                    task.callback(task)
                except Exception as callback_error:
                    print(f"❌ 回调执行失败: {callback_error}")
    
    def _execute_workflow_stage(self, stage: str, params: Dict[str, Any]) -> str:
        """执行工作流程阶段"""
        from .agent_coordinator import CreativeDirectorCoordinator
        import sqlite3
        
        coordinator = CreativeDirectorCoordinator()
        
        # 🔧 从参数中加载项目上下文（已经从数据库加载）
        coordinator.project_context = {
            'project_title': params.get('title', ''),
            'project_genre': params.get('genre', ''),
            'user_requirement': params.get('requirement', ''),
            'concept': params.get('concept', ''),
            'world_setting': params.get('world_setting', ''),
            'characters': params.get('characters', ''),
            'plot_outline': params.get('plot_outline', ''),
            'chapter_draft': params.get('chapter_draft', ''),
            'review_report': params.get('review_report', ''),
            'chapters': [],  # ✅ 初始化章节列表，用于 _stage_three_content_creation
        }
        
        print(f"📋 执行阶段: {stage}")
        print(f"📦 上下文数据: concept={len(coordinator.project_context.get('concept', ''))} chars, "
              f"plot_outline={len(coordinator.project_context.get('plot_outline', ''))} chars, "
              f"chapter_draft={len(coordinator.project_context.get('chapter_draft', ''))} chars")
        
        result_text = ''
        project_id = params.get('project_id')
        
        try:
            if stage == 'concept':
                result = coordinator._stage_one_concept_development(
                    params.get('requirement', f"创作一部{params.get('genre', '')}类型的小说")
                )
                # concept阶段返回三个部分
                result_text = result.get('concept', '')
                
                # 🔧 保存三个部分到数据库
                if project_id:
                    self._save_stage_result(project_id, 'concept', {
                        'concept': result.get('concept', ''),
                        'world_setting': result.get('world_setting', ''),
                        'characters': result.get('characters', '')
                    })
                
            elif stage == 'structure':
                result = coordinator._stage_two_structure_design({
                    'world_setting': coordinator.project_context.get('world_setting', ''),
                    'characters': coordinator.project_context.get('characters', '')
                })
                result_text = result.get('plot_outline', '')
                
                # 保存到数据库
                if project_id:
                    self._save_stage_result(project_id, 'structure', {'plot_outline': result_text})
                
            elif stage == 'content':
                result = coordinator._stage_three_content_creation({
                    'plot_outline': coordinator.project_context.get('plot_outline', ''),
                    'concept': coordinator.project_context.get('concept', '')
                })
                result_text = result.get('content', '')
                
                # 保存到数据库
                if project_id:
                    self._save_stage_result(project_id, 'content', {'chapter_draft': result_text})
                
            elif stage == 'review':
                # 🔧 使用从数据库加载的 chapter_draft
                chapter_draft = coordinator.project_context.get('chapter_draft', '')
                if not chapter_draft:
                    print("⚠️  警告: 章节初稿内容为空")
                    return "错误：章节初稿内容为空，无法进行评审"
                
                print(f"📝 评审章节内容，长度: {len(chapter_draft)} 字符")
                result = coordinator._stage_four_quality_review({
                    'content': chapter_draft,
                    'plot_outline': coordinator.project_context.get('plot_outline', ''),
                    'concept': coordinator.project_context.get('concept', '')
                })
                result_text = result.get('review', '')
                
                # 保存到数据库
                if project_id:
                    self._save_stage_result(project_id, 'review', {'review_report': result_text})
                
            elif stage == 'iteration':
                review_report = coordinator.project_context.get('review_report', '')
                chapter_draft = coordinator.project_context.get('chapter_draft', '')
                
                # 🔧 验证数据完整性
                if not review_report:
                    print("⚠️  警告: 评审报告内容为空")
                    return "错误：评审报告内容为空，无法进行迭代优化"
                
                if not chapter_draft:
                    print("⚠️  警告: 章节初稿内容为空")
                    return "错误：章节初稿内容为空，无法进行迭代优化"
                
                print(f"🔄 迭代优化章节内容，评审报告长度: {len(review_report)} 字符，章节初稿长度: {len(chapter_draft)} 字符")
                
                # 🔧 修复：使用正确的参数结构
                result = coordinator._stage_five_iteration_optimization({
                    'review': review_report,  # ✅ 使用 'review' 键，匹配方法签名
                    'content': chapter_draft
                })
                result_text = result.get('revised_content', '')
                
                # 保存到数据库
                if project_id:
                    self._save_stage_result(project_id, 'iteration', {'final_version': result_text})
                
            else:
                result_text = f"阶段 {stage} 执行完成"
            
            print(f"✅ 阶段 {stage} 执行成功，结果长度: {len(result_text)} 字符")
            return result_text
            
        except Exception as e:
            error_msg = f"执行阶段 {stage} 失败: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return error_msg
    
    def _save_stage_result(self, project_id: int, stage: str, data: Dict[str, str]):
        """保存阶段执行结果到数据库"""
        import sqlite3
        
        try:
            conn = sqlite3.connect('novel_app.db')
            c = conn.cursor()
            
            print(f"🔍 [_save_stage_result] 准备保存: project_id={project_id}, stage={stage}")
            print(f"🔍 [_save_stage_result] 数据键: {list(data.keys())}")
            for key, value in data.items():
                print(f"🔍 [_save_stage_result] {key} 长度: {len(value) if value else 0} 字符")
            
            # 先检查记录是否存在
            c.execute('SELECT project_id FROM project_settings WHERE project_id = ?', (project_id,))
            existing_record = c.fetchone()
            
            if not existing_record:
                print(f"⚠️  记录不存在，先创建 project_settings 记录: project_id={project_id}")
                c.execute('''INSERT INTO project_settings 
                            (project_id, stage_one_status, stage_two_status, stage_three_status, stage_four_status, stage_five_status)
                            VALUES (?, 'pending', 'pending', 'pending', 'pending', 'pending')''',
                         (project_id,))
                conn.commit()
                print(f"✅ 已创建 project_settings 记录: project_id={project_id}")
            
            # ✅ 阶段到状态字段的映射
            stage_status_map = {
                'concept': 'stage_one_status',
                'structure': 'stage_two_status',
                'content': 'stage_three_status',
                'review': 'stage_four_status',
                'iteration': 'stage_five_status'
            }
            
            status_column = stage_status_map.get(stage)
            
            # 根据阶段更新相应的字段和状态
            rows_affected = 0
            if stage == 'concept':
                # ✅ 同时更新内容和状态
                c.execute(f'''
                    UPDATE project_settings 
                    SET concept = ?, world_setting = ?, characters = ?, {status_column} = 'completed', updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                ''', (data.get('concept', ''), data.get('world_setting', ''), 
                      data.get('characters', ''), project_id))
                rows_affected = c.rowcount
            elif stage == 'structure':
                c.execute(f'''
                    UPDATE project_settings 
                    SET plot_outline = ?, {status_column} = 'completed', updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                ''', (data.get('plot_outline', ''), project_id))
                rows_affected = c.rowcount
            elif stage == 'content':
                c.execute(f'''
                    UPDATE project_settings 
                    SET chapter_draft = ?, {status_column} = 'completed', updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                ''', (data.get('chapter_draft', ''), project_id))
                rows_affected = c.rowcount
            elif stage == 'review':
                c.execute(f'''
                    UPDATE project_settings 
                    SET review_report = ?, {status_column} = 'completed', updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                ''', (data.get('review_report', ''), project_id))
                rows_affected = c.rowcount
            elif stage == 'iteration':
                c.execute(f'''
                    UPDATE project_settings 
                    SET final_version = ?, {status_column} = 'completed', updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                ''', (data.get('final_version', ''), project_id))
                rows_affected = c.rowcount
            
            conn.commit()
            conn.close()
            
            if rows_affected > 0:
                print(f"💾 阶段 {stage} 结果已保存到数据库 (影响 {rows_affected} 行)")
                print(f"✅ 状态已更新: {status_column} = completed")
            else:
                print(f"⚠️  阶段 {stage} UPDATE 未影响任何行，可能 project_id={project_id} 不存在")
            
        except Exception as e:
            print(f"❌ 保存阶段结果失败: {e}")
            import traceback
            traceback.print_exc()
    
    def submit_task(self, task_type: str, project_id: int, user_id: int, 
                   params: Dict[str, Any], callback: Optional[Callable] = None) -> str:
        """提交生成任务"""
        import uuid
        task_id = str(uuid.uuid4())
        
        print(f"🔍 [submit_task] 实例 ID: {id(self)}")
        print(f"🔍 [submit_task] 任务字典 ID: {id(self.tasks)}")
        
        task = GenerationTask(
            task_id=task_id,
            task_type=task_type,
            project_id=project_id,
            user_id=user_id,
            params=params,
            callback=callback
        )
        
        # ✅ 使用锁保护字典操作，立即将任务添加到字典中
        with self.tasks_lock:
            self.tasks[task_id] = task
            current_count = len(self.tasks)
        
        print(f"📝 任务已提交并添加到字典: {task_id} ({task_type})")
        print(f"📊 当前任务字典大小: {current_count}")
        print(f"✅ 任务状态: {task.status}（已加锁保护）")
        
        # 将任务添加到队列中等待处理
        self.task_queue.put(task)
        
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        print(f"🔍 [get_task_status] 实例 ID: {id(self)}")
        print(f"🔍 [get_task_status] 任务字典 ID: {id(self.tasks)}")
        print(f"🔍 查询任务状态: {task_id}")
        
        # ✅ 使用锁保护字典访问
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            current_count = len(self.tasks)
            all_task_ids = list(self.tasks.keys())
        
        print(f"📊 当前任务总数: {current_count}（已加锁）")
        
        if not task:
            print(f"⚠️  任务不存在: {task_id}")
            print(f"📋 所有任务ID: {all_task_ids}")
            return None
        
        print(f"✅ 找到任务: {task_id}, 状态: {task.status}")
        
        return {
            'task_id': task.task_id,
            'task_type': task.task_type,
            'status': task.status,
            'result': task.result,
            'error': task.error,
            'created_at': task.created_at,
            'completed_at': task.completed_at
        }
    
    def get_all_tasks(self, user_id: int) -> list:
        """获取用户的所有任务"""
        return [
            self.get_task_status(task_id)
            for task_id, task in self.tasks.items()
            if task.user_id == user_id
        ]


# 全局集成实例
deepseek_integration = DeepSeekIntegration()

print("🔍 [deepseek_integration.py] 全局实例已创建")
print(f"🔍 [deepseek_integration.py] 实例 ID: {id(deepseek_integration)}")
print(f"🔍 [deepseek_integration.py] 任务字典 ID: {id(deepseek_integration.tasks)}")

