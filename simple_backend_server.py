#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的后端服务器 - 用于演示
集成DeepSeek AI生成功能
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sqlite3
import os
from datetime import datetime, timedelta
import hashlib
import base64
import threading
import uuid
import re
import sys
import io

# 设置 UTF-8 编码以支持中文和 emoji（Windows 兼容）
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 导入DeepSeek集成模块
try:
    from deepseek_integration import deepseek_integration
    DEEPSEEK_AVAILABLE = True
except ImportError:
    DEEPSEEK_AVAILABLE = False
    print("⚠️  DeepSeek集成模块不可用")
except Exception as e:
    DEEPSEEK_AVAILABLE = False
    print(f"⚠️  DeepSeek集成模块加载失败: {e}")

# 导入Agent协调器
try:
    from agent_coordinator import CreativeDirectorCoordinator
    from knowledge_base import NovelKnowledgeBase
    from memory_manager import NovelMemoryManager
    AGENT_COORDINATOR_AVAILABLE = True
    print("✅ Agent协调器已加载")
except ImportError as e:
    AGENT_COORDINATOR_AVAILABLE = False
    print(f"⚠️  Agent协调器加载失败 (ImportError): {e}")
except Exception as e:
    AGENT_COORDINATOR_AVAILABLE = False
    print(f"⚠️  Agent协调器加载失败 (Exception): {e}")

# 数据库初始化
DB_FILE = "novel_app.db"

# ========== 全局阶段映射配置 ==========
# 统一定义阶段名称到数据库字段的映射关系，确保GET/POST/PUT端点使用相同的映射

# 阶段到数据库列的映射（用于按钮内容的获取和保存）
STAGE_TO_COLUMN_MAP = {
    'concept': 'concept',               # 概念开发 → 故事概念
    'world_builder': 'world_setting',   # 世界观架构师 → 世界观设定
    'character_designer': 'characters', # 人物设计师 → 人物设定
    'structure': 'plot_outline',        # 结构设计 → 情节大纲
    'content': 'chapter_draft',         # 内容创作 → 章节初稿
    'review': 'review_report',          # 质量评审 → 评审报告
    'iteration': 'final_version'        # 迭代优化 → 最终版本
}

# 阶段到输出预览内容的映射（右侧输出预览显示的内容）
# 注意: concept阶段的输出预览只显示concept字段，不包括world_setting和characters
STAGE_OUTPUT_PREVIEW_MAP = {
    'concept': 'concept',               # 输出预览显示: 故事概念
    'structure': 'plot_outline',        # 输出预览显示: 情节大纲  
    'content': 'chapter_draft',         # 输出预览显示: 章节初稿
    'review': 'review_report',          # 输出预览显示: 评审报告
    'iteration': 'final_version'        # 输出预览显示: 最终版本
}
# ========================================

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    try:
        # 检查 users 表是否存在
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        users_exists = c.fetchone()
        
        if users_exists:
            print("✅ 数据库基础表已存在")
            
            # 检查是否需要进行数据库迁移（添加新字段）
            c.execute("PRAGMA table_info(project_settings)")
            columns = [col[1] for col in c.fetchall()]
            
            # 检查是否存在新字段
            new_fields = ['chapter_draft', 'review_report', 'final_version']
            missing_fields = [field for field in new_fields if field not in columns]
            
            if missing_fields:
                print(f"🔄 检测到数据库结构更新，添加新字段: {', '.join(missing_fields)}")
                
                # 添加缺失的字段
                if 'chapter_draft' in missing_fields:
                    c.execute('''ALTER TABLE project_settings ADD COLUMN chapter_draft TEXT''')
                    print("✅ 已添加字段: chapter_draft (章节初稿)")
                    
                if 'review_report' in missing_fields:
                    c.execute('''ALTER TABLE project_settings ADD COLUMN review_report TEXT''')
                    print("✅ 已添加字段: review_report (质量评审报告)")
                    
                if 'final_version' in missing_fields:
                    c.execute('''ALTER TABLE project_settings ADD COLUMN final_version TEXT''')
                    print("✅ 已添加字段: final_version (最终版本)")
                
                conn.commit()
                print("✅ 数据库结构更新完成")
            else:
                print("✅ 数据库结构已是最新版本")
            
            conn.close()
            return

        print("📍 创建数据库表...")

        # 创建用户表
        c.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # 创建项目表
        c.execute('''CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            genre TEXT,
            status TEXT DEFAULT 'draft',
            word_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')

        # 创建章节表
        c.execute('''CREATE TABLE chapters (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            chapter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            status TEXT DEFAULT 'draft',
            word_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        # 创建项目设定表（存储五阶段工作流程的输出）
        c.execute('''CREATE TABLE project_settings (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL UNIQUE,
            concept TEXT,
            world_setting TEXT,
            characters TEXT,
            plot_outline TEXT,
            chapter_draft TEXT,
            review_report TEXT,
            final_version TEXT,
            stage_one_status TEXT DEFAULT 'pending',
            stage_two_status TEXT DEFAULT 'pending',
            stage_three_status TEXT DEFAULT 'pending',
            stage_four_status TEXT DEFAULT 'pending',
            stage_five_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        # 创建评审结果表
        c.execute('''CREATE TABLE review_results (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            chapter_id INTEGER,
            reviewer_feedback TEXT,
            quality_score REAL,
            needs_revision INTEGER DEFAULT 0,
            revision_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        )''')

        # 创建生成历史表
        c.execute('''CREATE TABLE generation_history (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            chapter_id INTEGER,
            task_type TEXT NOT NULL,
            task_id TEXT NOT NULL,
            prompt TEXT,
            result TEXT,
            status TEXT DEFAULT 'pending',
            quality_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (chapter_id) REFERENCES chapters(id)
        )''')

        # 创建工作流程会话表（保存用户的创作需求）
        c.execute('''CREATE TABLE workflow_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            requirement TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')

        conn.commit()
        print("✅ 数据库初始化完成")
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

class SimpleHandler(BaseHTTPRequestHandler):
    """简单的HTTP请求处理器"""

    # 全局Agent协调器实例
    _coordinator = None
    _coordinator_lock = threading.Lock()

    @classmethod
    def get_coordinator(cls):
        """获取或初始化Agent协调器"""
        if cls._coordinator is None and AGENT_COORDINATOR_AVAILABLE:
            with cls._coordinator_lock:
                if cls._coordinator is None:
                    try:
                        print("🔄 初始化Agent协调器...")
                        knowledge_base = NovelKnowledgeBase()
                        memory_manager = NovelMemoryManager()
                        cls._coordinator = CreativeDirectorCoordinator(knowledge_base, memory_manager)
                        print("✅ Agent协调器初始化成功")
                    except Exception as e:
                        print(f"❌ Agent协调器初始化失败: {e}")
                        cls._coordinator = None
        return cls._coordinator

    def send_cors_headers(self):
        """发送CORS头"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '3600')

    def send_json_response(self, status_code, data):
        """发送JSON响应（带CORS头）"""
        try:
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            # 使用 ensure_ascii=False 和 UTF-8 编码处理中文
            response_data = json.dumps(data, ensure_ascii=False, default=str)
            self.wfile.write(response_data.encode('utf-8'))
        except Exception as e:
            print(f"❌ [ERROR] 发送JSON响应失败: {e}")
            import traceback
            traceback.print_exc()

    def do_OPTIONS(self):
        """处理OPTIONS请求（CORS预检）"""
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def get_user_from_token(self, token):
        """从token中提取用户信息"""
        try:
            decoded = base64.b64decode(token).decode()
            user_id, username = decoded.split(':')
            return int(user_id), username
        except:
            return None, None

    def generate_chapter_title(self, content: str, chapter_number: int) -> str:
        """
        根据章节内容生成章节标题
        格式：第{章节编号}章 {AI生成的标题}
        """
        try:
            # 如果内容为空，使用默认标题
            if not content or len(content.strip()) == 0:
                return f"第{self._convert_number_to_chinese(chapter_number)}章 未命名"

            # 提取内容的前500个字符用于分析
            content_preview = content[:500]

            # 使用DeepSeek AI生成标题
            if DEEPSEEK_AVAILABLE:
                try:
                    # 调用DeepSeek框架生成标题
                    from multi_agent_framework import MultiAgentNovelWritingFramework
                    framework = MultiAgentNovelWritingFramework()

                    # 使用LLM生成标题
                    prompt = f"""请根据以下章节内容，生成一个简洁有意义的章节标题。
标题要求：
1. 长度：2-8个汉字
2. 能够概括章节的核心内容或主题
3. 简洁、有意义、吸引人

章节内容预览：
{content_preview}

请只返回标题文本，不要包含其他内容。"""

                    # 调用LLM
                    from agents import create_deepseek_llm
                    llm = create_deepseek_llm()
                    title_text = llm.predict(prompt)

                    # 清理标题（移除可能的引号或多余空格）
                    title_text = title_text.strip().strip('"\'')

                    # 确保标题长度在2-8个汉字
                    if len(title_text) > 8:
                        title_text = title_text[:8]
                    elif len(title_text) < 2:
                        title_text = "未命名"

                    return f"第{self._convert_number_to_chinese(chapter_number)}章 {title_text}"
                except Exception as e:
                    print(f"⚠️  AI生成标题失败: {e}，使用默认标题")
                    return f"第{self._convert_number_to_chinese(chapter_number)}章 未命名"
            else:
                # 如果DeepSeek不可用，使用简单的关键词提取
                return self._generate_simple_title(content, chapter_number)

        except Exception as e:
            print(f"❌ 生成章节标题出错: {e}")
            return f"第{self._convert_number_to_chinese(chapter_number)}章 未命名"

    def _convert_number_to_chinese(self, num: int) -> str:
        """将数字转换为中文"""
        chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
        if num <= 10:
            return chinese_nums[num]
        elif num < 20:
            return '十' + chinese_nums[num - 10]
        elif num < 100:
            return chinese_nums[num // 10] + '十' + (chinese_nums[num % 10] if num % 10 != 0 else '')
        else:
            return str(num)

    def _generate_simple_title(self, content: str, chapter_number: int) -> str:
        """
        简单的标题生成方法（当AI不可用时）
        通过提取内容中的关键词生成标题
        """
        try:
            # 移除标点符号和特殊字符
            cleaned = re.sub(r'[，。！？；：""''（）【】《》、]', ' ', content)
            words = cleaned.split()

            # 提取名词和形容词（简单启发式方法）
            keywords = []
            for word in words:
                if len(word) >= 2 and len(word) <= 4:
                    keywords.append(word)

            # 选择前几个关键词组成标题
            if keywords:
                title = ''.join(keywords[:3])[:8]
            else:
                title = "未命名"

            return f"第{self._convert_number_to_chinese(chapter_number)}章 {title}"
        except:
            return f"第{self._convert_number_to_chinese(chapter_number)}章 未命名"

    def do_GET(self):
        """处理GET请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # 健康检查
        if path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            response = {'status': 'ok', 'message': '后端服务运行正常'}
            self.wfile.write(json.dumps(response).encode())
            return

        # 获取项目列表
        if path == '/api/v1/projects' or path == '/api/projects':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT id, user_id, title, description, genre, status, word_count, created_at FROM projects WHERE user_id = ?', (user_id,))
            projects = c.fetchall()
            conn.close()

            projects_list = []
            for p in projects:
                projects_list.append({
                    'id': p[0],
                    'user_id': p[1],
                    'title': p[2],
                    'description': p[3],
                    'genre': p[4],
                    'status': p[5],
                    'word_count': p[6],
                    'created_at': p[7]
                })

            self.send_json_response(200, projects_list)
            return

        # 获取项目详情（包括所有五阶段信息）
        if path.startswith('/api/v1/projects/') and not path.endswith('/chapters'):
            try:
                project_id = int(path.split('/')[-1])
            except (ValueError, IndexError):
                # 如果不是数字，继续检查其他路由
                pass
            else:
                print(f"📍 GET /api/v1/projects/{project_id} 请求")

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    print(f"❌ 认证失败，token: {token}")
                    self.send_json_response(401, {'error': '未授权'})
                    return

                print(f"✅ 认证成功，user_id: {user_id}, username: {username}")

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 获取项目基本信息
                    c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        print(f"❌ 项目不存在，project_id: {project_id}, user_id: {user_id}")
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    print(f"✅ 项目找到: {project[2]}")

                    # 获取项目设定（五阶段信息）
                    c.execute('SELECT * FROM project_settings WHERE project_id = ?', (project_id,))
                    settings = c.fetchone()

                    # 获取章节列表
                    c.execute('SELECT * FROM chapters WHERE project_id = ? ORDER BY chapter_number', (project_id,))
                    chapters = c.fetchall()

                    # 获取最新的评审结果
                    c.execute('SELECT * FROM review_results WHERE project_id = ? ORDER BY created_at DESC LIMIT 1', (project_id,))
                    review = c.fetchone()

                    response = {
                        'id': project[0],
                        'user_id': project[1],
                        'title': project[2],
                        'description': project[3],
                        'genre': project[4],
                        'status': project[5],
                        'word_count': project[6],
                        'created_at': project[7],
                        'settings': {
                            'concept': settings[2] if settings else None,
                            'world_setting': settings[3] if settings else None,
                            'characters': settings[4] if settings else None,
                            'plot_outline': settings[5] if settings else None,
                            'stage_one_status': settings[6] if settings else 'pending',
                            'stage_two_status': settings[7] if settings else 'pending',
                            'stage_three_status': settings[8] if settings else 'pending',
                            'stage_four_status': settings[9] if settings else 'pending',
                            'stage_five_status': settings[10] if settings else 'pending',
                        } if settings else {},
                        'chapters': [
                            {
                                'id': ch[0],
                                'chapter_number': ch[2],
                                'title': ch[3],
                                'content': ch[4],
                                'status': ch[5],
                                'word_count': ch[6],
                                'created_at': ch[7]
                            } for ch in chapters
                        ],
                        'review': {
                            'feedback': review[3] if review else None,
                            'quality_score': review[4] if review else None,
                            'needs_revision': review[5] if review else 0,
                            'revision_count': review[6] if review else 0,
                            'created_at': review[7] if review else None
                        } if review else None
                    }

                    print(f"✅ 返回项目详情: {response['title']}")
                    self.send_json_response(200, response)
                except Exception as e:
                    print(f"❌ 获取项目详情出错: {e}")
                    import traceback
                    traceback.print_exc()
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 获取项目的章节列表
        if path.startswith('/api/v1/projects/') and path.endswith('/chapters'):
            parts = path.split('/')
            parts = [p for p in parts if p]  # 过滤空字符串
            if len(parts) >= 3 and parts[-2].isdigit():
                project_id = int(parts[-2])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 获取章节列表
                    c.execute('SELECT * FROM chapters WHERE project_id = ? ORDER BY chapter_number', (project_id,))
                    chapters = c.fetchall()

                    chapters_list = []
                    for ch in chapters:
                        chapters_list.append({
                            'id': ch[0],
                            'project_id': ch[1],
                            'chapter_number': ch[2],
                            'title': ch[3],
                            'content': ch[4],
                            'status': ch[5],
                            'word_count': ch[6],
                            'created_at': ch[7]
                        })

                    self.send_json_response(200, chapters_list)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 获取单个章节
        if path.startswith('/api/v1/chapters/') or path.startswith('/api/chapters/'):
            parts = path.split('/')
            if len(parts) >= 4 and parts[-1].isdigit():
                chapter_id = int(parts[-1])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证章节存在且属于用户的项目
                    c.execute('''SELECT ch.* FROM chapters ch
                               JOIN projects p ON ch.project_id = p.id
                               WHERE ch.id = ? AND p.user_id = ?''', (chapter_id, user_id))
                    chapter = c.fetchone()

                    if not chapter:
                        self.send_json_response(404, {'error': '章节不存在'})
                        return

                    response = {
                        'id': chapter[0],
                        'project_id': chapter[1],
                        'chapter_number': chapter[2],
                        'title': chapter[3],
                        'content': chapter[4],
                        'status': chapter[5],
                        'word_count': chapter[6],
                        'created_at': chapter[7]
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 获取任务状态
        if path.startswith('/api/v1/generate/') or path.startswith('/api/generate/'):
            if not DEEPSEEK_AVAILABLE:
                self.send_json_response(503, {'error': 'DeepSeek集成不可用'})
                return

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            # 提取task_id
            task_id = path.split('/')[-1]

            task_status = deepseek_integration.get_task_status(task_id)
            if not task_status:
                self.send_json_response(404, {'error': '任务不存在'})
                return

            self.send_json_response(200, task_status)
            return
        
        # API文档
        if path == '/docs':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>小说创作系统 - API文档</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                    .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
                    h1 { color: #333; }
                    .endpoint { background: #f9f9f9; padding: 15px; margin: 10px 0; border-left: 4px solid #007bff; }
                    .method { display: inline-block; padding: 5px 10px; border-radius: 3px; font-weight: bold; margin-right: 10px; }
                    .get { background: #61affe; color: white; }
                    .post { background: #49cc90; color: white; }
                    code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🎉 小说创作系统 - 简单后端API</h1>
                    <p>这是一个简化的后端服务器，用于演示前端应用。</p>
                    
                    <h2>可用端点</h2>
                    
                    <div class="endpoint">
                        <span class="method get">GET</span>
                        <code>/health</code>
                        <p>健康检查</p>
                    </div>
                    
                    <div class="endpoint">
                        <span class="method post">POST</span>
                        <code>/api/auth/register</code>
                        <p>用户注册</p>
                    </div>
                    
                    <div class="endpoint">
                        <span class="method post">POST</span>
                        <code>/api/auth/login</code>
                        <p>用户登录</p>
                    </div>
                    
                    <div class="endpoint">
                        <span class="method get">GET</span>
                        <code>/api/projects</code>
                        <p>获取项目列表</p>
                    </div>
                    
                    <div class="endpoint">
                        <span class="method post">POST</span>
                        <code>/api/projects</code>
                        <p>创建新项目</p>
                    </div>
                    
                    <h2>快速开始</h2>
                    <ol>
                        <li>打开前端应用: <a href="http://localhost:5173" target="_blank">http://localhost:5173</a></li>
                        <li>注册新账户</li>
                        <li>创建新项目</li>
                        <li>开始写作！</li>
                    </ol>
                    
                    <h2>测试用户</h2>
                    <p>用户名: <code>demo</code></p>
                    <p>密码: <code>demo123</code></p>
                </div>
            </body>
            </html>
            '''
            self.wfile.write(html.encode())
            return

        # 获取生成历史
        if path.startswith('/api/v1/generation-history/'):
            parts = path.split('/')
            parts = [p for p in parts if p]  # 过滤空字符串

            if len(parts) >= 4:
                resource_type = parts[-2]  # 'project' 或 'chapter'
                resource_id = parts[-1]

                if resource_id.isdigit():
                    resource_id = int(resource_id)

                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                    user_id, username = self.get_user_from_token(token)
                    if not user_id:
                        self.send_json_response(401, {'error': '未授权'})
                        return

                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()

                    try:
                        if resource_type == 'project':
                            # 验证项目存在且属于用户
                            c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (resource_id, user_id))
                            project = c.fetchone()

                            if not project:
                                self.send_json_response(404, {'error': '项目不存在'})
                                return

                            # 获取项目的生成历史
                            c.execute('SELECT * FROM generation_history WHERE project_id = ? ORDER BY created_at DESC', (resource_id,))
                            histories = c.fetchall()

                        elif resource_type == 'chapter':
                            # 验证章节存在
                            c.execute('SELECT * FROM chapters WHERE id = ?', (resource_id,))
                            chapter = c.fetchone()

                            if not chapter:
                                self.send_json_response(404, {'error': '章节不存在'})
                                return

                            # 验证章节所属项目属于用户
                            project_id = chapter[1]
                            c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                            project = c.fetchone()

                            if not project:
                                self.send_json_response(403, {'error': '无权访问此章节'})
                                return

                            # 获取章节的生成历史
                            c.execute('SELECT * FROM generation_history WHERE chapter_id = ? ORDER BY created_at DESC', (resource_id,))
                            histories = c.fetchall()

                        else:
                            self.send_json_response(400, {'error': '无效的资源类型'})
                            return

                        histories_list = []
                        for h in histories:
                            histories_list.append({
                                'id': h[0],
                                'project_id': h[1],
                                'chapter_id': h[2],
                                'task_type': h[3],
                                'task_id': h[4],
                                'prompt': h[5],
                                'result': h[6],
                                'status': h[7],
                                'quality_score': h[8],
                                'created_at': h[9],
                                'completed_at': h[10]
                            })

                        self.send_json_response(200, {'histories': histories_list})
                    except Exception as e:
                        self.send_json_response(500, {'error': str(e)})
                    finally:
                        conn.close()
                    return

        # 获取工作流程状态
        if path.startswith('/api/v1/workflow/status/'):
            parts = path.split('/')
            if len(parts) >= 5 and parts[-1].isdigit():
                project_id = int(parts[-1])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT id FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 返回工作流程状态
                    workflow_status = {
                        'project_id': project_id,
                        'status': 'idle',
                        'stages': {
                            'concept': {'status': 'pending', 'progress': 0},
                            'structure': {'status': 'pending', 'progress': 0},
                            'content': {'status': 'pending', 'progress': 0},
                            'review': {'status': 'pending', 'progress': 0},
                            'iteration': {'status': 'pending', 'progress': 0},
                        }
                    }
                    self.send_json_response(200, workflow_status)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 获取阶段内容 (GET请求)
        if path.startswith('/api/workflow/') and '/stage/' in path and path.endswith('/content'):
            # 路径格式: /api/workflow/{project_id}/stage/{stage}/content
            print(f'🔍 调试 - 收到阶段内容请求, path={path}')
            parts = path.split('/')
            print(f'🔍 调试 - split后: {parts}')
            parts = [p for p in parts if p]  # 过滤空字符串
            print(f'🔍 调试 - 过滤后: {parts}')
            print(f'🔍 调试 - len(parts)={len(parts)}, parts[2]={parts[2] if len(parts) > 2 else "N/A"}, parts[2].isdigit()={parts[2].isdigit() if len(parts) > 2 else False}')

            # parts 应该是: ['api', 'workflow', '2', 'stage', 'concept', 'content']
            if len(parts) >= 6 and parts[2].isdigit():
                print(f'🔍 调试 - 条件匹配成功，开始处理')
                project_id = int(parts[2])
                stage = parts[4]

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT id FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 根据阶段类型获取对应列的内容
                    # 使用全局映射常量 STAGE_TO_COLUMN_MAP
                    column_name = STAGE_TO_COLUMN_MAP.get(stage)
                    
                    if not column_name:
                        print(f'⚠️  未知的阶段: {stage}, 使用默认值')
                        column_name = 'concept'
                    
                    print(f'📍 阶段 {stage} 映射到列: {column_name}')

                    # 获取阶段内容
                    query = f'SELECT {column_name} FROM project_settings WHERE project_id = ?'
                    c.execute(query, (project_id,))
                    result = c.fetchone()

                    if result and result[0]:
                        content = result[0]
                        print(f'✅ 找到内容, 长度: {len(content)}')
                    else:
                        content = f'阶段 {stage} 的内容尚未生成'
                        print(f'⚠️  未找到内容')

                    response = {
                        'project_id': project_id,
                        'stage': stage,
                        'content': content
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    print(f'❌ 获取阶段内容失败: {e}')
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 404
        self.send_response(404)
        self.send_header('Content-type', 'application/json')
        self.send_cors_headers()
        self.end_headers()
        response = {'error': '端点未找到'}
        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        """处理POST请求"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}
        
        # 注册
        if path == '/api/v1/auth/register' or path == '/api/auth/register':
            username = data.get('username', '')
            email = data.get('email', '')
            password = data.get('password', '')

            if not all([username, email, password]):
                self.send_json_response(400, {'error': '缺少必要字段'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                password_hash = hashlib.sha256(password.encode()).hexdigest()
                c.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                         (username, email, password_hash))
                conn.commit()
                user_id = c.lastrowid

                token = base64.b64encode(f"{user_id}:{username}".encode()).decode()
                response = {
                    'access_token': token,
                    'token_type': 'bearer',
                    'user': {
                        'id': user_id,
                        'username': username,
                        'email': email
                    }
                }
                self.send_json_response(200, response)
            except sqlite3.IntegrityError:
                self.send_json_response(400, {'error': '用户名或邮箱已存在'})
            finally:
                conn.close()
            return
        
        # 登录
        if path == '/api/v1/auth/login' or path == '/api/auth/login':
            username = data.get('username', '')
            password = data.get('password', '')

            if not all([username, password]):
                self.send_json_response(400, {'error': '缺少必要字段'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            password_hash = hashlib.sha256(password.encode()).hexdigest()
            c.execute('SELECT id, username, email FROM users WHERE username = ? AND password_hash = ?',
                     (username, password_hash))
            user = c.fetchone()
            conn.close()

            if user:
                token = base64.b64encode(f"{user[0]}:{user[1]}".encode()).decode()
                response = {
                    'access_token': token,
                    'token_type': 'bearer',
                    'user': {
                        'id': user[0],
                        'username': user[1],
                        'email': user[2]
                    }
                }
                self.send_json_response(200, response)
            else:
                self.send_json_response(401, {'error': '用户名或密码错误'})
            return

        # 创建项目
        if path == '/api/v1/projects' or path == '/api/projects':
            print(f"📍 POST /api/v1/projects 请求")

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                print(f"❌ 认证失败，token: {token}")
                self.send_json_response(401, {'error': '未授权'})
                return

            print(f"✅ 认证成功，user_id: {user_id}, username: {username}")

            title = data.get('title', '')
            description = data.get('description', '')
            genre = data.get('genre', '')

            print(f"📍 项目数据: title={title}, description={description}, genre={genre}")

            if not title:
                print(f"❌ 项目标题为空")
                self.send_json_response(400, {'error': '项目标题不能为空'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                print(f"📍 准备插入项目到数据库")
                c.execute('''INSERT INTO projects (user_id, title, description, genre, status, word_count, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (user_id, title, description, genre, 'draft', 0, datetime.now().isoformat()))
                conn.commit()
                project_id = c.lastrowid

                print(f"✅ 项目创建成功，project_id: {project_id}")

                response = {
                    'id': project_id,
                    'user_id': user_id,
                    'title': title,
                    'description': description,
                    'genre': genre,
                    'status': 'draft',
                    'word_count': 0,
                    'created_at': datetime.now().isoformat()
                }
                print(f"📍 准备发送响应: {response}")
                self.send_json_response(200, response)
                print(f"✅ 响应已发送")
            except Exception as e:
                print(f"❌ 创建项目失败: {e}")
                import traceback
                traceback.print_exc()
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 获取项目详情（包括所有五阶段信息）
        if path.startswith('/api/v1/projects/') or path.startswith('/api/projects/'):
            try:
                project_id = int(path.split('/')[-1])
            except (ValueError, IndexError):
                self.send_json_response(400, {'error': '无效的项目ID'})
                return

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                # 获取项目基本信息
                c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                project = c.fetchone()

                if not project:
                    self.send_json_response(404, {'error': '项目不存在'})
                    return

                # 获取项目设定（五阶段信息）
                c.execute('SELECT * FROM project_settings WHERE project_id = ?', (project_id,))
                settings = c.fetchone()

                # 获取章节列表
                c.execute('SELECT * FROM chapters WHERE project_id = ? ORDER BY chapter_number', (project_id,))
                chapters = c.fetchall()

                # 获取最新的评审结果
                c.execute('SELECT * FROM review_results WHERE project_id = ? ORDER BY created_at DESC LIMIT 1', (project_id,))
                review = c.fetchone()

                response = {
                    'id': project[0],
                    'user_id': project[1],
                    'title': project[2],
                    'description': project[3],
                    'genre': project[4],
                    'status': project[5],
                    'word_count': project[6],
                    'created_at': project[7],
                    'settings': {
                        'concept': settings[2] if settings else None,
                        'world_setting': settings[3] if settings else None,
                        'characters': settings[4] if settings else None,
                        'plot_outline': settings[5] if settings else None,
                        'stage_one_status': settings[6] if settings else 'pending',
                        'stage_two_status': settings[7] if settings else 'pending',
                        'stage_three_status': settings[8] if settings else 'pending',
                        'stage_four_status': settings[9] if settings else 'pending',
                        'stage_five_status': settings[10] if settings else 'pending',
                    } if settings else {},
                    'chapters': [
                        {
                            'id': ch[0],
                            'chapter_number': ch[2],
                            'title': ch[3],
                            'content': ch[4],
                            'status': ch[5],
                            'word_count': ch[6],
                            'created_at': ch[7]
                        } for ch in chapters
                    ],
                    'review': {
                        'feedback': review[3] if review else None,
                        'quality_score': review[4] if review else None,
                        'needs_revision': review[5] if review else 0,
                        'revision_count': review[6] if review else 0,
                        'created_at': review[7] if review else None
                    } if review else None
                }

                self.send_json_response(200, response)
            except Exception as e:
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 初始化项目的五阶段工作流程
        if path == '/api/v1/projects/initialize-workflow' or path == '/api/projects/initialize-workflow':
            if not DEEPSEEK_AVAILABLE:
                self.send_json_response(503, {'error': 'DeepSeek集成不可用'})
                return

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            project_id = data.get('project_id', 0)

            if not project_id:
                self.send_json_response(400, {'error': '缺少project_id'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                # 验证项目存在
                c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                project = c.fetchone()

                if not project:
                    self.send_json_response(404, {'error': '项目不存在'})
                    return

                # 创建项目设定记录
                c.execute('''INSERT OR IGNORE INTO project_settings (project_id, stage_one_status, stage_two_status, stage_three_status, stage_four_status, stage_five_status)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                         (project_id, 'pending', 'pending', 'pending', 'pending', 'pending'))
                conn.commit()

                # 提交五阶段工作流程任务
                task_id = deepseek_integration.submit_task(
                    task_type='workflow',
                    project_id=project_id,
                    user_id=user_id,
                    params={
                        'title': project[2],
                        'genre': project[4],
                        'description': project[3]
                    }
                )

                response = {
                    'task_id': task_id,
                    'project_id': project_id,
                    'status': 'pending',
                    'message': '五阶段工作流程已启动，正在处理中...',
                    'stages': {
                        'stage_one': 'pending',
                        'stage_two': 'pending',
                        'stage_three': 'pending',
                        'stage_four': 'pending',
                        'stage_five': 'pending'
                    }
                }
                self.send_json_response(200, response)
            except Exception as e:
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 保存生成历史
        if path == '/api/v1/generation-history' or path == '/api/generation-history':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            project_id = data.get('project_id', 0)
            chapter_id = data.get('chapter_id')
            task_type = data.get('task_type', '')
            task_id = data.get('task_id', '')
            prompt = data.get('prompt', '')
            result = data.get('result', '')
            status = data.get('status', 'completed')
            quality_score = data.get('quality_score')

            if not project_id or not task_type:
                self.send_json_response(400, {'error': '缺少必要字段'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                c.execute('''INSERT INTO generation_history
                           (project_id, chapter_id, task_type, task_id, prompt, result, status, quality_score, completed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (project_id, chapter_id, task_type, task_id, prompt, result, status, quality_score, datetime.now().isoformat()))
                conn.commit()
                history_id = c.lastrowid

                response = {
                    'id': history_id,
                    'project_id': project_id,
                    'task_type': task_type,
                    'status': status,
                    'message': '生成历史已保存'
                }
                self.send_json_response(200, response)
            except Exception as e:
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 获取生成历史
        if path.startswith('/api/v1/generation-history/') or path.startswith('/api/generation-history/'):
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            # 获取项目ID或章节ID
            parts = path.split('/')
            resource_id = int(parts[-1]) if parts[-1].isdigit() else None
            resource_type = parts[-2] if len(parts) > 1 else None

            if not resource_id:
                self.send_json_response(400, {'error': '缺少资源ID'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                if resource_type == 'project':
                    # 获取项目的生成历史
                    c.execute('''SELECT * FROM generation_history
                               WHERE project_id = ?
                               ORDER BY created_at DESC''', (resource_id,))
                elif resource_type == 'chapter':
                    # 获取章节的生成历史
                    c.execute('''SELECT * FROM generation_history
                               WHERE chapter_id = ?
                               ORDER BY created_at DESC''', (resource_id,))
                else:
                    self.send_json_response(400, {'error': '无效的资源类型'})
                    return

                histories = c.fetchall()
                response = {
                    'histories': [
                        {
                            'id': h[0],
                            'project_id': h[1],
                            'chapter_id': h[2],
                            'task_type': h[3],
                            'task_id': h[4],
                            'prompt': h[5],
                            'result': h[6],
                            'status': h[7],
                            'quality_score': h[8],
                            'created_at': h[9],
                            'completed_at': h[10]
                        } for h in histories
                    ]
                }
                self.send_json_response(200, response)
            except Exception as e:
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 创建章节 - 支持两种路径格式
        # 格式1: POST /api/v1/chapters (project_id 在请求体中)
        # 格式2: POST /api/v1/projects/{projectId}/chapters (projectId 在 URL 中)
        if path == '/api/v1/chapters' or path == '/api/chapters' or (path.startswith('/api/v1/projects/') and path.endswith('/chapters')):
            print(f"📍 创建章节请求: path={path}")

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                print(f"❌ 未授权: token={token}")
                self.send_json_response(401, {'error': '未授权'})
                return

            # 支持两种路径格式
            # 格式1: /api/v1/chapters (project_id 在请求体中)
            # 格式2: /api/v1/projects/{projectId}/chapters (projectId 在 URL 中)
            project_id = data.get('project_id', 0)
            if not project_id and (path.startswith('/api/v1/projects/') and path.endswith('/chapters')):
                # 从 URL 中提取 projectId
                parts = path.split('/')
                parts = [p for p in parts if p]  # 过滤空字符串
                if len(parts) >= 3 and parts[-2].isdigit():
                    project_id = int(parts[-2])
                    print(f"📍 从URL提取project_id: {project_id}")

            chapter_number = data.get('chapter_number', 0)
            title = data.get('title', '')
            content = data.get('content', '')

            print(f"📍 章节参数: project_id={project_id}, chapter_number={chapter_number}, title={title[:50] if title else '(无)'}, content_len={len(content)}")

            if not project_id or not content:
                print(f"❌ 缺少必要字段: project_id={project_id}, content_len={len(content)}")
                self.send_json_response(400, {'error': '缺少必要字段'})
                return

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            try:
                # 验证项目存在
                c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                project = c.fetchone()

                if not project:
                    self.send_json_response(404, {'error': '项目不存在'})
                    return

                # 如果没有指定章节号，自动计算
                if not chapter_number:
                    c.execute('SELECT MAX(chapter_number) FROM chapters WHERE project_id = ?', (project_id,))
                    max_chapter = c.fetchone()[0]
                    chapter_number = (max_chapter or 0) + 1

                # 如果没有提供标题，自动生成标题
                if not title:
                    try:
                        title = self.generate_chapter_title(content, chapter_number)
                        print(f"✅ 自动生成章节标题: {title}")
                    except Exception as title_error:
                        print(f"⚠️  生成标题失败: {title_error}，使用默认标题")
                        # 使用简单的默认标题
                        chinese_num = self._convert_number_to_chinese(chapter_number)
                        title = f"第{chinese_num}章 未命名"
                else:
                    # 如果提供了标题但不包含章节编号，自动添加
                    if not title.startswith('第'):
                        try:
                            chinese_num = self._convert_number_to_chinese(chapter_number)
                            title = f"第{chinese_num}章 {title}"
                        except Exception as num_error:
                            print(f"⚠️  转换章节号失败: {num_error}，使用阿拉伯数字")
                            title = f"第{chapter_number}章 {title}"

                # 创建章节
                print(f"📍 开始插入章节到数据库...")
                try:
                    c.execute('''INSERT INTO chapters (project_id, chapter_number, title, content, word_count, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                         (project_id, chapter_number, title, content, len(content), datetime.now().isoformat()))
                    conn.commit()
                    chapter_id = c.lastrowid
                    print(f"✅ 章节创建成功: id={chapter_id}, project_id={project_id}, chapter_number={chapter_number}, title={title}")
                except Exception as db_error:
                    print(f"❌ 数据库插入失败: {db_error}")
                    import traceback
                    traceback.print_exc()
                    raise db_error

                response = {
                    'id': chapter_id,
                    'project_id': project_id,
                    'chapter_number': chapter_number,
                    'title': title,
                    'content': content,
                    'word_count': len(content),
                    'created_at': datetime.now().isoformat()
                }
                print(f"📍 返回响应: {response}")
                self.send_json_response(200, response)
            except Exception as e:
                print(f"❌ 创建章节失败: {str(e)}")
                import traceback
                traceback.print_exc()
                self.send_json_response(500, {'error': str(e)})
            finally:
                conn.close()
            return

        # 自动保存章节
        if path.startswith('/api/v1/chapters/') and path.endswith('/auto-save'):
            parts = path.split('/')
            if len(parts) >= 4 and parts[-2].isdigit():
                chapter_id = int(parts[-2])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                content = data.get('content', '')

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证章节存在且属于用户的项目
                    c.execute('''SELECT ch.* FROM chapters ch
                               JOIN projects p ON ch.project_id = p.id
                               WHERE ch.id = ? AND p.user_id = ?''', (chapter_id, user_id))
                    chapter = c.fetchone()

                    if not chapter:
                        self.send_json_response(404, {'error': '章节不存在'})
                        return

                    # 自动保存章节
                    c.execute('''UPDATE chapters SET content = ?, word_count = ? WHERE id = ?''',
                             (content, len(content), chapter_id))
                    conn.commit()

                    # 返回更新后的章节
                    c.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
                    updated_chapter = c.fetchone()

                    response = {
                        'chapter': {
                            'id': updated_chapter[0],
                            'project_id': updated_chapter[1],
                            'chapter_number': updated_chapter[2],
                            'title': updated_chapter[3],
                            'content': updated_chapter[4],
                            'word_count': updated_chapter[6],
                            'created_at': updated_chapter[7]
                        }
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 提交生成任务
        if path == '/api/v1/generate' or path == '/api/generate':
            if not DEEPSEEK_AVAILABLE:
                self.send_json_response(503, {'error': 'DeepSeek集成不可用'})
                return

            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            task_type = data.get('task_type', '')
            project_id = data.get('project_id', 0)
            params = data.get('params', {})

            if not task_type:
                self.send_json_response(400, {'error': '缺少task_type'})
                return

            try:
                # 提交任务到DeepSeek集成
                task_id = deepseek_integration.submit_task(
                    task_type=task_type,
                    project_id=project_id,
                    user_id=user_id,
                    params=params
                )

                response = {
                    'task_id': task_id,
                    'status': 'pending',
                    'message': '任务已提交，正在处理中...'
                }
                self.send_json_response(200, response)
            except Exception as e:
                self.send_json_response(500, {'error': str(e)})
            return

        # 启动工作流程
        if path == '/api/v1/workflow/start':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            project_id = data.get('project_id')
            requirement = data.get('requirement', '')

            if not project_id or not requirement:
                self.send_json_response(400, {'error': '缺少project_id或requirement'})
                return

            # 验证项目存在且属于用户
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT id FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
            project = c.fetchone()
            conn.close()

            if not project:
                self.send_json_response(404, {'error': '项目不存在'})
                return

            # 保存工作流程会话（用户输入的创作需求）
            try:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                # 删除旧的会话（如果存在）
                c.execute('DELETE FROM workflow_sessions WHERE project_id = ?', (project_id,))

                # 保存新的会话
                c.execute('''INSERT INTO workflow_sessions
                           (project_id, user_id, requirement, created_at)
                           VALUES (?, ?, ?, ?)''',
                         (project_id, user_id, requirement, datetime.now().isoformat()))
                conn.commit()
                conn.close()
                print(f"✅ 工作流程会话已保存: {requirement[:50]}...")
            except Exception as e:
                print(f"⚠️  保存工作流程会话失败: {e}")

            # 返回初始化的阶段信息
            stages = {
                'concept': {
                    'id': 'concept',
                    'name': '概念开发',
                    'status': 'pending',
                    'progress': 0,
                    'agents': [
                        {'id': 'creative-director', 'name': '创意总监', 'status': 'idle', 'progress': 0, 'message': ''},
                        {'id': 'worldview-architect', 'name': '世界观架构师', 'status': 'idle', 'progress': 0, 'message': ''},
                        {'id': 'character-designer', 'name': '人物设计师', 'status': 'idle', 'progress': 0, 'message': ''},
                    ],
                },
                'structure': {
                    'id': 'structure',
                    'name': '结构设计',
                    'status': 'pending',
                    'progress': 0,
                    'agents': [
                        {'id': 'plot-architect', 'name': '情节架构师', 'status': 'idle', 'progress': 0, 'message': ''},
                        {'id': 'event-validator', 'name': '事件验证官', 'status': 'idle', 'progress': 0, 'message': ''},
                    ],
                },
                'content': {
                    'id': 'content',
                    'name': '内容创作',
                    'status': 'pending',
                    'progress': 0,
                    'agents': [
                        {'id': 'content-creator', 'name': '内容创作师', 'status': 'idle', 'progress': 0, 'message': ''},
                        {'id': 'style-optimizer', 'name': '文风优化师', 'status': 'idle', 'progress': 0, 'message': ''},
                    ],
                },
                'review': {
                    'id': 'review',
                    'name': '质量评审',
                    'status': 'pending',
                    'progress': 0,
                    'agents': [
                        {'id': 'quality-reviewer', 'name': '质量评审官', 'status': 'idle', 'progress': 0, 'message': ''},
                    ],
                },
                'iteration': {
                    'id': 'iteration',
                    'name': '迭代优化',
                    'status': 'pending',
                    'progress': 0,
                    'agents': [
                        {'id': 'iteration-coordinator', 'name': '迭代协调官', 'status': 'idle', 'progress': 0, 'message': ''},
                    ],
                },
            }

            response = {'status': 'success', 'stages': stages}
            self.send_json_response(200, response)
            return

        # 执行阶段
        if path == '/api/v1/workflow/execute-stage':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            project_id = data.get('project_id')
            stage = data.get('stage', '')

            if not project_id or not stage:
                self.send_json_response(400, {'error': '缺少project_id或stage'})
                return

            # 验证项目存在且属于用户
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT id, title, genre FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
            project = c.fetchone()
            conn.close()

            if not project:
                self.send_json_response(404, {'error': '项目不存在'})
                return

            # 真正执行阶段 - 调用AI生成内容
            try:
                print(f"📍 执行阶段: {stage}, 项目ID: {project_id}")

                # 获取项目信息
                project_title = project[1]
                project_genre = project[2]

                # 尝试使用Agent协调器生成内容
                coordinator = self.get_coordinator()
                output = None
                output_data = None  # 初始化 output_data 变量，用于concept阶段的三个字段
                agents_info = []

                if coordinator:
                    print(f"🤖 使用Agent协调器执行阶段: {stage}")
                    try:
                        # 根据阶段类型调用相应的方法
                        if stage == 'concept':
                            print(f"  → 启动概念开发阶段...")

                            # 获取用户输入的创作需求
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute('SELECT requirement FROM workflow_sessions WHERE project_id = ?', (project_id,))
                            session = c.fetchone()
                            conn.close()

                            user_requirement = session[0] if session else f"创作一部{project_genre}类型的小说，标题为《{project_title}》"
                            print(f"  → 使用用户需求: {user_requirement[:50]}...")

                            # 执行概念开发，返回三个部分：concept, world_setting, characters
                            stage_result = coordinator._stage_one_concept_development(user_requirement)
                            
                            # 保存概念开发的三个输出，分别存储到三个字段
                            concept_text = stage_result.get('concept', '')
                            world_setting_text = stage_result.get('world_setting', '')
                            characters_text = stage_result.get('characters', '')
                            
                            # 合并为显示用的输出
                            output = f"【故事概念开发】\n\n{concept_text}"
                            
                            # 将三个部分分别保存到project_context，供后续阶段使用
                            coordinator.project_context['concept'] = concept_text
                            coordinator.project_context['world_setting'] = world_setting_text
                            coordinator.project_context['characters'] = characters_text
                            
                            # 保存三个输出以便后续保存到数据库
                            # 注意：这里使用一个特殊的字典结构，包含三个字段
                            output_data = {
                                'concept': concept_text,
                                'world_setting': world_setting_text,
                                'characters': characters_text
                            }
                            
                            agents_info = [
                                {'id': 'creative-director', 'name': '创意总监', 'status': 'completed', 'progress': 100, 'message': '完成'},
                                {'id': 'worldview-architect', 'name': '世界观架构师', 'status': 'completed', 'progress': 100, 'message': '完成'},
                                {'id': 'character-designer', 'name': '人物设计师', 'status': 'completed', 'progress': 100, 'message': '完成'},
                            ]
                        elif stage == 'structure':
                            print(f"  → 启动结构设计阶段...")

                            # 获取用户输入的创作需求
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute('SELECT requirement FROM workflow_sessions WHERE project_id = ?', (project_id,))
                            session = c.fetchone()
                            conn.close()

                            user_requirement = session[0] if session else ''

                            # 将用户需求添加到上下文
                            coordinator.project_context['user_requirement'] = user_requirement

                            # 获取之前的概念结果
                            concept_result = coordinator.project_context.get('concept', '')
                            stage_result = coordinator._stage_two_structure_design({
                                'world_setting': coordinator.project_context.get('world_setting', ''),
                                'characters': coordinator.project_context.get('characters', '')
                            })
                            output = f"【情节大纲设计】\n\n{stage_result.get('plot_outline', '')}"
                            agents_info = [
                                {'id': 'plot-architect', 'name': '情节架构师', 'status': 'completed', 'progress': 100, 'message': '完成'},
                                {'id': 'event-validator', 'name': '事件验证官', 'status': 'completed', 'progress': 100, 'message': '完成'},
                            ]
                        elif stage == 'content':
                            print(f"  → 启动内容创作阶段...")

                            # 获取用户输入的创作需求
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute('SELECT requirement FROM workflow_sessions WHERE project_id = ?', (project_id,))
                            session = c.fetchone()
                            conn.close()

                            user_requirement = session[0] if session else ''

                            # 将用户需求添加到上下文
                            coordinator.project_context['user_requirement'] = user_requirement

                            stage_result = coordinator._stage_three_content_creation({
                                'plot_outline': coordinator.project_context.get('plot_outline', ''),
                                'concept': coordinator.project_context.get('concept', {})
                            })
                            output = f"【章节初稿】\n\n{stage_result.get('content', '')}"
                            agents_info = [
                                {'id': 'creative-director', 'name': '创意总监', 'status': 'completed', 'progress': 100, 'message': '完成'},
                                {'id': 'content-creator', 'name': '内容创作师', 'status': 'completed', 'progress': 100, 'message': '完成'},
                                {'id': 'style-optimizer', 'name': '文风优化师', 'status': 'completed', 'progress': 100, 'message': '完成'},
                            ]
                        elif stage == 'review':
                            print(f"  → 启动质量评审阶段...")

                            # 获取用户输入的创作需求
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute('SELECT requirement FROM workflow_sessions WHERE project_id = ?', (project_id,))
                            session = c.fetchone()
                            conn.close()

                            user_requirement = session[0] if session else ''

                            # 将用户需求添加到上下文
                            coordinator.project_context['user_requirement'] = user_requirement

                            stage_result = coordinator._stage_four_quality_review({
                                'content': coordinator.project_context.get('chapters', [''])[0] if coordinator.project_context.get('chapters') else ''
                            })
                            output = f"【质量评审报告】\n\n{stage_result.get('review', '')}"
                            agents_info = [
                                {'id': 'quality-reviewer', 'name': '质量评审官', 'status': 'completed', 'progress': 100, 'message': '完成'},
                            ]
                        elif stage == 'iteration':
                            print(f"  → 启动迭代优化阶段...")

                            # 获取用户输入的创作需求
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute('SELECT requirement FROM workflow_sessions WHERE project_id = ?', (project_id,))
                            session = c.fetchone()
                            conn.close()

                            user_requirement = session[0] if session else ''

                            # 将用户需求添加到上下文
                            coordinator.project_context['user_requirement'] = user_requirement

                            review_result = coordinator.project_context.get('review_result', {})
                            stage_result = coordinator._stage_five_iteration_optimization(review_result)
                            output = f"【迭代优化完成】\n\n{stage_result.get('revised_content', '')}"
                            agents_info = [
                                {'id': 'iteration-coordinator', 'name': '迭代协调官', 'status': 'completed', 'progress': 100, 'message': '完成'},
                            ]

                        print(f"✅ Agent执行完成，生成内容长度: {len(output) if output else 0}")
                    except Exception as e:
                        print(f"⚠️  Agent执行出错: {e}，使用备用方案")
                        output = None

                # 如果Agent执行失败，使用备用方案
                if not output:
                    print(f"📋 使用备用方案生成内容...")
                    stage_outputs = {
                        'concept': f'故事概念开发\n\n项目: {project_title}\n类型: {project_genre}\n\n核心冲突: 主角面临的主要挑战\n主题思想: 故事要表达的核心理念\n目标读者: 青年科幻爱好者\n背景设定: 未来太空探险背景',
                        'structure': f'情节大纲设计\n\n第一幕: 引入\n- 介绍主角和世界观\n- 设置冲突\n\n第二幕: 发展\n- 主角面临挑战\n- 情节升级\n\n第三幕: 高潮\n- 最终对抗\n- 解决冲突\n\n第四幕: 结局\n- 收尾\n- 反思',
                        'content': f'章节初稿\n\n第一章 开始\n\n黑暗中，一个身影缓缓睁开眼睛。周围是陌生的环境，闪烁的灯光和低沉的机器声音充斥着整个空间。\n\n"你醒了，"一个声音从黑暗中传来，"欢迎来到星舰。"\n\n主角试图站起来，但身体还很虚弱。记忆片段在脑海中闪过——逃离、追捕、坠落...',
                        'review': f'质量评审报告\n\n内容完整性: ✓ 完整\n逻辑连贯性: ✓ 连贯\n人物塑造: ✓ 良好\n世界观设定: ✓ 清晰\n\n建议:\n1. 加强环境描写\n2. 深化人物心理\n3. 增加对话互动\n\n总体评分: 8/10',
                        'iteration': f'【最终版本 - 第一章 星际觉醒】\n\n无尽的黑暗中，一丝微光渐渐穿透意识的迷雾。{project_title}的主角缓缓睁开双眼，映入眼帘的是陌生而冰冷的金属穹顶，闪烁的蓝色指示灯在黑暗中勾勒出规则的几何图案。耳边传来低沉而有节奏的机器运转声,仿佛巨兽的心跳，在密闭的空间中回荡。\n\n"终于醒了,"一个略带沙哑的声音从阴影中传来,"欢迎来到【流浪者号】星舰。你已经沉睡了整整72个小时。"\n\n主角挣扎着想要坐起身来，但全身的肌肉却像生了锈一般僵硬。破碎的记忆片段在脑海中翻涌——夜色中的狂奔、追击者冰冷的枪口、从悬崖边缘的坠落，还有那个模糊的面孔在最后一刻说的话:"活下去，真相在星辰之上..."\n\n房间的灯光突然亮起，刺眼的白光让主角下意识地眯起眼睛。一个身材高大的人影走了过来，逆着光，看不清面容，但能感觉到对方审视的目光。\n\n"你的身份芯片已经被彻底清除,"那人继续说道，语气中带着一丝玩味,"在这艘船上，过去已经不重要了。重要的是，你能为我们做什么。"\n\n主角的喉咙干涩得仿佛要冒烟，艰难地发出沙哑的声音:"这里...是哪里?"\n\n"银河系第七星区，距离地球联邦控制区大约23光年,"那人走近了些，终于露出了面容——一张饱经风霜的脸，左眼角有一道狰狞的疤痕,"你现在在自由航行者联盟的领地。恭喜你，逃离了那个牢笼。"\n\n(本章完)\n\n---\n\n【优化说明】\n本版本已根据质量评审建议进行全面优化:\n✓ 增强了环境描写(星舰内部的视觉、听觉细节)\n✓ 深化了人物心理(主角的身体感受和记忆碎片)\n✓ 增加了对话互动(与神秘人物的对话推进情节)\n✓ 强化了悬念设置(身份之谜、真相暗示)\n✓ 优化了叙述节奏(由内到外，层层递进)'
                    }
                    output = stage_outputs.get(stage, f'阶段 {stage} 执行完成')
                    agents_info = [
                        {'id': 'agent-1', 'name': 'AI Agent', 'status': 'completed', 'progress': 100, 'message': '完成'}
                    ]

                # 保存阶段输出到project_settings表
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 检查是否已存在该项目的设置
                    c.execute('SELECT id FROM project_settings WHERE project_id = ?', (project_id,))
                    existing = c.fetchone()

                    # concept阶段特殊处理：需要保存三个字段
                    if stage == 'concept' and isinstance(output_data, dict):
                        if existing:
                            # 更新现有记录，保存三个字段
                            c.execute('''UPDATE project_settings 
                                       SET concept = ?, world_setting = ?, characters = ?, updated_at = ? 
                                       WHERE project_id = ?''',
                                     (output_data.get('concept', ''),
                                      output_data.get('world_setting', ''),
                                      output_data.get('characters', ''),
                                      datetime.now().isoformat(),
                                      project_id))
                        else:
                            # 插入新记录
                            c.execute('''INSERT INTO project_settings
                                       (project_id, concept, world_setting, characters, plot_outline,
                                        chapter_draft, review_report, final_version,
                                        stage_one_status, stage_two_status, stage_three_status,
                                        stage_four_status, stage_five_status, created_at, updated_at)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                     (project_id,
                                      output_data.get('concept', ''),       # concept 字段
                                      output_data.get('world_setting', ''), # world_setting 字段
                                      output_data.get('characters', ''),    # characters 字段
                                      '',  # plot_outline
                                      '',  # chapter_draft
                                      '',  # review_report
                                      '',  # final_version
                                      'pending', 'pending', 'pending', 'pending', 'pending',
                                      datetime.now().isoformat(), datetime.now().isoformat()))
                        print(f"✅ 概念开发阶段输出已保存：concept({len(output_data.get('concept', ''))}字符), world_setting({len(output_data.get('world_setting', ''))}字符), characters({len(output_data.get('characters', ''))}字符)")
                    else:
                        # 其他阶段：按照 STAGE_TO_COLUMN_MAP 保存单个字段
                        # 使用全局映射常量
                        column_name = STAGE_TO_COLUMN_MAP.get(stage, 'concept')

                        if existing:
                            # 更新现有记录
                            query = f'UPDATE project_settings SET {column_name} = ?, updated_at = ? WHERE project_id = ?'
                            c.execute(query, (output, datetime.now().isoformat(), project_id))
                        else:
                            # 插入新记录
                            # 注意：字段映射必须与 stage_column_map 一致
                            c.execute('''INSERT INTO project_settings
                                       (project_id, concept, world_setting, characters, plot_outline,
                                        chapter_draft, review_report, final_version,
                                        stage_one_status, stage_two_status, stage_three_status,
                                        stage_four_status, stage_five_status, created_at, updated_at)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                     (project_id,
                                      output if stage == 'concept' else '',      # concept 阶段 → concept 字段
                                      '',                                         # world_setting 字段（由world_builder阶段填充）
                                      '',                                         # characters 字段（由character_designer阶段填充）
                                      output if stage == 'structure' else '',     # structure 阶段 → plot_outline 字段
                                      output if stage == 'content' else '',       # content 阶段 → chapter_draft 字段
                                      output if stage == 'review' else '',        # review 阶段 → review_report 字段
                                      output if stage == 'iteration' else '',     # iteration 阶段 → final_version 字段
                                      'pending', 'pending', 'pending', 'pending', 'pending',
                                      datetime.now().isoformat(), datetime.now().isoformat()))
                        print(f"✅ 阶段输出已保存: {stage} → {column_name}")

                    conn.commit()
                except Exception as e:
                    print(f"❌ 保存阶段输出失败: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    conn.close()

                # 返回成功响应
                response = {
                    'status': 'success',
                    'stage': stage,
                    'output': output,
                    'agents': agents_info if agents_info else [
                        {'id': 'agent-1', 'name': 'AI Agent', 'status': 'completed', 'progress': 100, 'message': '完成'}
                    ]
                }
                self.send_json_response(200, response)
            except Exception as e:
                print(f"❌ 执行阶段失败: {e}")
                self.send_json_response(500, {'error': str(e)})
            return

        # 生成下一章
        if path.startswith('/api/workflow/') and path.endswith('/generate-next-chapter'):
            # 路径格式: /api/workflow/{project_id}/generate-next-chapter
            parts = path.split('/')
            parts = [p for p in parts if p]  # 过滤空字符串

            # parts 应该是: ['api', 'workflow', '2', 'generate-next-chapter']
            if len(parts) >= 4 and parts[2].isdigit():
                project_id = int(parts[2])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT id, title, genre FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    project_title = project[1]
                    project_genre = project[2]

                    print(f'📍 开始生成下一章，项目: {project_title}')

                    # 1. 获取项目数据（concept, world_setting, characters, plot_outline）
                    c.execute('''SELECT concept, world_setting, characters, plot_outline 
                               FROM project_settings WHERE project_id = ?''', (project_id,))
                    settings = c.fetchone()

                    if not settings:
                        self.send_json_response(400, {'error': '项目设定不存在，请先完成工作流程'})
                        return

                    concept, world_setting, characters, plot_outline = settings

                    # 2. 获取已生成章节
                    c.execute('''SELECT id, chapter_number, title, content 
                               FROM chapters 
                               WHERE project_id = ? 
                               ORDER BY chapter_number ASC''', (project_id,))
                    existing_chapters = c.fetchall()

                    # 计算下一章的编号
                    next_chapter_number = len(existing_chapters) + 1
                    print(f'📍 当前已有 {len(existing_chapters)} 章，即将生成第 {next_chapter_number} 章')

                    # 3. 调用创意总监分析并规划下一章
                    coordinator = self.get_coordinator()
                    if coordinator:
                        # 初始化项目上下文
                        coordinator.project_context = {
                            'project_id': project_id,
                            'project_title': project_title,
                            'project_genre': project_genre,
                            'concept': concept or '',
                            'world_setting': world_setting or '',
                            'characters': characters or '',
                            'plot_outline': plot_outline or '',
                            'existing_chapters': [
                                {
                                    'chapter_number': ch[1],
                                    'title': ch[2],
                                    'content': ch[3]
                                } for ch in existing_chapters
                            ],
                            'next_chapter_number': next_chapter_number
                        }

                        print(f'🤖 使用Agent协调器生成下一章规划...')
                        
                        # 调用创意总监生成下一章计划
                        prompt = f'''基于当前项目的所有上下文，为第{next_chapter_number}章制定创作计划。

项目信息：
- 标题：{project_title}
- 类型：{project_genre}

故事概念：
{concept or "未设置"}

情节大纲：
{plot_outline or "未设置"}

已生成 {len(existing_chapters)} 章

请制定第{next_chapter_number}章的创作计划，包括：
1. 章节主题
2. 核心事件
3. 人物发展
4. 情节推进'''
                        
                        try:
                            chapter_plan = coordinator.creative_director.process(prompt, coordinator.project_context)
                            print(f'✅ 下一章计划已生成')
                        except Exception as e:
                            print(f'⚠️  生成下一章计划失败: {e}')
                            chapter_plan = f'第{next_chapter_number}章创作计划'
                    else:
                        print(f'⚠️  Agent协调器不可用，使用默认计划')
                        chapter_plan = f'第{next_chapter_number}章创作计划'

                    # 4. 重置工作流状态到内容创作阶段
                    # 注意：这里不直接重置数据库，而是返回响应让前端进行跳转
                    # 前端会自动调用 execute-stage API 来执行内容创作阶段

                    response = {
                        'success': True,
                        'message': '已开始生成下一章',
                        'next_chapter_number': next_chapter_number,
                        'current_stage': 'content',
                        'chapter_plan': chapter_plan if 'chapter_plan' in locals() else ''
                    }
                    
                    print(f'✅ 生成下一章准备完成，返回响应')
                    self.send_json_response(200, response)
                except Exception as e:
                    print(f'❌ 生成下一章失败: {e}')
                    import traceback
                    traceback.print_exc()
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 重新生成阶段
        if path == '/api/v1/workflow/regenerate-stage':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

            user_id, username = self.get_user_from_token(token)
            if not user_id:
                self.send_json_response(401, {'error': '未授权'})
                return

            project_id = data.get('project_id')
            stage = data.get('stage', '')

            if not project_id or not stage:
                self.send_json_response(400, {'error': '缺少project_id或stage'})
                return

            # 验证项目存在且属于用户
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT id FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
            project = c.fetchone()
            conn.close()

            if not project:
                self.send_json_response(404, {'error': '项目不存在'})
                return

            # 模拟阶段重新生成
            response = {
                'status': 'success',
                'stage': stage,
                'output': f'阶段 {stage} 已重新生成',
                'agents': []
            }
            self.send_json_response(200, response)
            return

        # 404
        self.send_json_response(404, {'error': '端点未找到'})

    def do_PUT(self):
        """处理PUT请求"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        # 更新章节
        if path.startswith('/api/v1/chapters/') or path.startswith('/api/chapters/'):
            parts = path.split('/')
            if len(parts) >= 4 and parts[-1].isdigit():
                chapter_id = int(parts[-1])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                title = data.get('title')
                content = data.get('content')

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证章节存在且属于用户的项目
                    c.execute('''SELECT ch.* FROM chapters ch
                               JOIN projects p ON ch.project_id = p.id
                               WHERE ch.id = ? AND p.user_id = ?''', (chapter_id, user_id))
                    chapter = c.fetchone()

                    if not chapter:
                        self.send_json_response(404, {'error': '章节不存在'})
                        return

                    # 更新章节
                    update_fields = []
                    update_values = []

                    if title is not None:
                        update_fields.append('title = ?')
                        update_values.append(title)

                    if content is not None:
                        update_fields.append('content = ?')
                        update_values.append(content)
                        update_fields.append('word_count = ?')
                        update_values.append(len(content))

                    if update_fields:
                        update_values.append(chapter_id)
                        query = f"UPDATE chapters SET {', '.join(update_fields)} WHERE id = ?"
                        c.execute(query, update_values)
                        conn.commit()

                    # 返回更新后的章节
                    c.execute('SELECT * FROM chapters WHERE id = ?', (chapter_id,))
                    updated_chapter = c.fetchone()

                    response = {
                        'id': updated_chapter[0],
                        'project_id': updated_chapter[1],
                        'chapter_number': updated_chapter[2],
                        'title': updated_chapter[3],
                        'content': updated_chapter[4],
                        'word_count': updated_chapter[6],
                        'created_at': updated_chapter[7]
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 保存工作流程阶段内容
        if path.startswith('/api/workflow/') and '/stage/' in path and path.endswith('/content'):
            # 路径格式: /api/workflow/{project_id}/stage/{stage}/content
            print(f"📍 PUT 请求: path={path}")
            parts = path.split('/')
            print(f"📍 分割后: {parts}")
            parts = [p for p in parts if p]  # 过滤空字符串
            print(f"📍 过滤后: {parts}")
            print(f"📍 len(parts)={len(parts)}")

            # parts = ['api', 'workflow', '2', 'stage', 'iteration', 'content']
            # 索引:     0        1         2      3        4            5
            if len(parts) >= 6 and parts[2].isdigit():
                project_id = int(parts[2])  # 修复: parts[1] → parts[2]
                stage = parts[4]  # 修复: parts[3] → parts[4]
                print(f"📍 project_id={project_id}, stage={stage}")

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                content = data.get('content', '')
                continue_workflow = data.get('continue_workflow', False)

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 获取或创建项目设定
                    c.execute('SELECT * FROM project_settings WHERE project_id = ?', (project_id,))
                    settings = c.fetchone()

                    if not settings:
                        c.execute('''INSERT INTO project_settings (project_id, stage_one_status, stage_two_status, stage_three_status, stage_four_status, stage_five_status)
                                   VALUES (?, ?, ?, ?, ?, ?)''',
                                 (project_id, 'pending', 'pending', 'pending', 'pending', 'pending'))
                        conn.commit()

                    # 根据阶段更新对应的内容
                    # 使用全局映射常量 STAGE_TO_COLUMN_MAP
                    column_name = STAGE_TO_COLUMN_MAP.get(stage)
                    
                    if not column_name:
                        print(f'⚠️  未知的阶段: {stage}')
                        self.send_json_response(400, {'error': f'无效的阶段: {stage}'})
                        return
                    
                    # 更新数据库字段
                    update_query = f'UPDATE project_settings SET {column_name} = ?, updated_at = ? WHERE project_id = ?'
                    c.execute(update_query, (content, datetime.now().isoformat(), project_id))

                    conn.commit()

                    response = {
                        'success': True,
                        'message': '内容已保存',
                        'stage': stage,
                        'next_stage': 'structure' if stage == 'concept' else None,
                        'continue_workflow': continue_workflow
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 获取工作流程阶段内容
        if path.startswith('/api/workflow/') and '/stage/' in path and '/content' in path:
            # 路径格式: /api/workflow/{project_id}/stage/{stage}/content 或 /api/workflow/{project_id}/stage/{stage}/content?type=preview
            # 分离路径和查询参数
            if '?' in path:
                path_part, query_part = path.split('?', 1)
                query_params = parse_qs(query_part)
                request_type = query_params.get('type', ['button'])[0]  # 默认为'button'
            else:
                path_part = path
                request_type = 'button'  # 默认为'button'

            parts = path_part.split('/')
            parts = [p for p in parts if p]  # 过滤空字符串

            # parts = ['api', 'workflow', '1', 'stage', 'concept', 'content']
            # 索引:     0        1         2      3        4          5
            if len(parts) >= 6 and parts[2].isdigit():
                project_id = int(parts[2])
                stage = parts[4]

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 根据请求类型选择映射
                    if request_type == 'preview':
                        # 获取输出预览内容（使用STAGE_OUTPUT_PREVIEW_MAP）
                        column_name = STAGE_OUTPUT_PREVIEW_MAP.get(stage)
                        print(f'📍 获取输出预览: stage={stage}, column={column_name}')
                    else:
                        # 获取按钮内容（使用STAGE_TO_COLUMN_MAP）
                        column_name = STAGE_TO_COLUMN_MAP.get(stage)
                        print(f'📍 获取按钮内容: stage={stage}, column={column_name}')

                    if not column_name:
                        print(f'⚠️  未知的阶段: {stage}')
                        self.send_json_response(400, {'error': f'无效的阶段: {stage}'})
                        return

                    # 从数据库获取project_settings记录
                    c.execute('SELECT * FROM project_settings WHERE project_id = ?', (project_id,))
                    settings = c.fetchone()

                    if not settings:
                        self.send_json_response(404, {'error': '项目设定不存在'})
                        return

                    # 根据列名从settings中获取内容
                    # settings字段顺序: [id, project_id, concept, world_setting, characters, plot_outline,
                    #                    chapter_draft, review_report, final_version, ...]
                    column_index_map = {
                        'concept': 2,
                        'world_setting': 3,
                        'characters': 4,
                        'plot_outline': 5,
                        'chapter_draft': 6,
                        'review_report': 7,
                        'final_version': 8
                    }

                    column_index = column_index_map.get(column_name, 2)
                    content = settings[column_index] or ''

                    response = {
                        'stage': stage,
                        'content': content or '',
                        'generated_at': datetime.now().isoformat()
                    }
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 404
        self.send_json_response(404, {'error': '端点未找到'})

    def do_DELETE(self):
        """处理DELETE请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        print(f"🗑️ DELETE 请求: {path}")

        # 删除项目
        if path.startswith('/api/v1/projects/') or path.startswith('/api/projects/'):
            parts = path.split('/')
            # 过滤空字符串
            parts = [p for p in parts if p]
            print(f"📍 路径部分: {parts}, 长度: {len(parts)}")
            if len(parts) >= 3 and parts[-1].isdigit():
                project_id = int(parts[-1])
                print(f"✅ 删除项目 ID: {project_id}")

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证项目存在且属于用户
                    c.execute('SELECT * FROM projects WHERE id = ? AND user_id = ?', (project_id, user_id))
                    project = c.fetchone()

                    if not project:
                        self.send_json_response(404, {'error': '项目不存在'})
                        return

                    # 删除项目相关的所有数据
                    # 1. 删除生成历史
                    c.execute('DELETE FROM generation_history WHERE project_id = ?', (project_id,))

                    # 2. 删除评审结果
                    c.execute('DELETE FROM review_results WHERE project_id = ?', (project_id,))

                    # 3. 删除项目设定
                    c.execute('DELETE FROM project_settings WHERE project_id = ?', (project_id,))

                    # 4. 删除章节
                    c.execute('DELETE FROM chapters WHERE project_id = ?', (project_id,))

                    # 5. 删除项目
                    c.execute('DELETE FROM projects WHERE id = ?', (project_id,))

                    conn.commit()

                    response = {'message': '项目已删除', 'id': project_id}
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 删除章节
        if path.startswith('/api/v1/chapters/') or path.startswith('/api/chapters/'):
            parts = path.split('/')
            # 过滤空字符串
            parts = [p for p in parts if p]
            if len(parts) >= 3 and parts[-1].isdigit():
                chapter_id = int(parts[-1])

                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

                user_id, username = self.get_user_from_token(token)
                if not user_id:
                    self.send_json_response(401, {'error': '未授权'})
                    return

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                try:
                    # 验证章节存在且属于用户的项目
                    c.execute('''SELECT ch.* FROM chapters ch
                               JOIN projects p ON ch.project_id = p.id
                               WHERE ch.id = ? AND p.user_id = ?''', (chapter_id, user_id))
                    chapter = c.fetchone()

                    if not chapter:
                        self.send_json_response(404, {'error': '章节不存在'})
                        return

                    # 删除章节
                    c.execute('DELETE FROM chapters WHERE id = ?', (chapter_id,))
                    conn.commit()

                    response = {'message': '章节已删除', 'id': chapter_id}
                    self.send_json_response(200, response)
                except Exception as e:
                    self.send_json_response(500, {'error': str(e)})
                finally:
                    conn.close()
                return

        # 404
        self.send_json_response(404, {'error': '端点未找到'})

    def log_message(self, format, *args):
        """自定义日志输出"""
        print(f"[{self.log_date_time_string()}] {format % args}")

def run_server(port=8000):
    """运行服务器"""
    init_db()

    # 启动DeepSeek集成
    if DEEPSEEK_AVAILABLE:
        deepseek_integration.start()

    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, SimpleHandler)

    print(f"")
    print(f"{'='*50}")
    print(f"🚀 小说创作系统 - 简单后端服务器")
    print(f"{'='*50}")
    print(f"")
    print(f"✅ 服务器运行在: http://localhost:{port}")
    print(f"📚 API文档: http://localhost:{port}/docs")
    print(f"❤️  健康检查: http://localhost:{port}/health")
    if DEEPSEEK_AVAILABLE:
        print(f"🤖 DeepSeek集成: 已启用")
    else:
        print(f"⚠️  DeepSeek集成: 未启用")
    print(f"")
    print(f"按 Ctrl+C 停止服务器")
    print(f"")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n✅ 服务器已停止")
        if DEEPSEEK_AVAILABLE:
            deepseek_integration.stop()
        httpd.server_close()

if __name__ == '__main__':
    run_server()

