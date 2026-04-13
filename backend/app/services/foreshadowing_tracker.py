"""
伏笔追踪系统 - 确保长篇小说伏笔不丢失、不遗忘

核心功能：
1. 从长篇框架中自动提取伏笔清单
2. 管理伏笔的生命周期（planted → paving → revealed）
3. 根据当前卷获取待处理的伏笔任务
4. 生成伏笔约束提示词

存储方式：
- 项目级JSON存储（存储在project_settings表的专用字段）
- 支持持久化和跨会话访问

三层体系定位：
- 顶层框架锚定：伏笔清单来源于长篇框架
- 卷级接口约束：每卷的伏笔任务（埋设/铺垫/揭秘）
- 章节锚点承接：伏笔检查清单嵌入提示词
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ForeshadowingStatus(Enum):
    """伏笔状态枚举"""
    PLANNED = "planned"      # 已规划但未埋设
    PLANTED = "planted"      # 已埋设
    PAVING = "paving"        # 铺垫中
    REVEALED = "revealed"    # 已揭秘/回收
    ABANDONED = "abandoned"  # 已放弃


class Foreshadowing:
    """单个伏笔的数据结构"""
    
    def __init__(self, 
                 content: str,
                 planted_volume: int,
                 reveal_volume: int,
                 pave_volumes: Optional[List[int]] = None,
                 planted_chapter: Optional[int] = None,
                 reveal_chapter: Optional[int] = None,
                 status: str = "planned",
                 importance: str = "normal",
                 notes: str = ""):
        """
        Args:
            content: 伏笔内容描述
            planted_volume: 埋设卷
            reveal_volume: 揭秘卷
            pave_volumes: 铺垫卷列表
            planted_chapter: 埋设章节（具体章节号，可选）
            reveal_chapter: 揭秘章节（具体章节号，可选）
            status: 状态（planned/planted/paving/revealed/abandoned）
            importance: 重要性（critical/important/normal/minor）
            notes: 备注
        """
        self.id = f"fs_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(content) % 10000}"
        self.content = content
        self.planted_volume = planted_volume
        self.reveal_volume = reveal_volume
        self.pave_volumes = pave_volumes or []
        self.planted_chapter = planted_chapter
        self.reveal_chapter = reveal_chapter
        self.status = status
        self.importance = importance
        self.notes = notes
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "planted_volume": self.planted_volume,
            "reveal_volume": self.reveal_volume,
            "pave_volumes": self.pave_volumes,
            "planted_chapter": self.planted_chapter,
            "reveal_chapter": self.reveal_chapter,
            "status": self.status,
            "importance": self.importance,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Foreshadowing':
        """从字典创建"""
        fs = cls(
            content=data.get("content", ""),
            planted_volume=data.get("planted_volume", 1),
            reveal_volume=data.get("reveal_volume", 1),
            pave_volumes=data.get("pave_volumes", []),
            planted_chapter=data.get("planted_chapter"),
            reveal_chapter=data.get("reveal_chapter"),
            status=data.get("status", "planned"),
            importance=data.get("importance", "normal"),
            notes=data.get("notes", "")
        )
        fs.id = data.get("id", fs.id)
        fs.created_at = data.get("created_at", fs.created_at)
        fs.updated_at = data.get("updated_at", fs.updated_at)
        return fs


class ForeshadowingTracker:
    """伏笔追踪器 - 管理项目所有伏笔的生命周期"""
    
    def __init__(self, project_id: int, llm=None):
        """初始化伏笔追踪器
        
        Args:
            project_id: 项目ID
            llm: LLM实例（用于AI提取，可选）
        """
        self.project_id = project_id
        self.llm = llm
        self.foreshadowings: List[Foreshadowing] = []
        self._loaded = False
    
    def extract_from_framework(self, framework_content: str) -> List[Foreshadowing]:
        """从长篇框架中提取伏笔清单
        
        解析长篇框架的「关键伏笔布局」表格，提取所有伏笔信息
        
        Args:
            framework_content: 长篇框架内容
            
        Returns:
            提取的伏笔列表
        """
        logger.info(f"📝 开始从长篇框架中提取伏笔清单...")
        
        if not framework_content:
            logger.warning("⚠️ 框架内容为空")
            return []
        
        extracted = []
        
        # 方法1：尝试解析表格格式
        table_foreshadowings = self._extract_from_table(framework_content)
        if table_foreshadowings:
            extracted.extend(table_foreshadowings)
            logger.info(f"✅ 从表格中提取到 {len(table_foreshadowings)} 条伏笔")
        
        # 方法2：尝试解析列表格式
        list_foreshadowings = self._extract_from_list(framework_content)
        if list_foreshadowings:
            # 去重（基于内容相似度）
            for fs in list_foreshadowings:
                if not any(self._is_similar(fs.content, existing.content) for existing in extracted):
                    extracted.append(fs)
            logger.info(f"✅ 从列表中补充提取到 {len(list_foreshadowings)} 条伏笔")
        
        # 方法3：如果都没提取到且有LLM，使用AI提取
        if not extracted and self.llm:
            try:
                ai_foreshadowings = self._ai_extract_foreshadowings(framework_content)
                extracted.extend(ai_foreshadowings)
                logger.info(f"✅ AI提取到 {len(ai_foreshadowings)} 条伏笔")
            except Exception as e:
                logger.warning(f"⚠️ AI提取失败: {e}")
        
        # 更新内部列表
        self.foreshadowings = extracted
        self._loaded = True
        
        logger.info(f"📋 伏笔提取完成，共 {len(extracted)} 条")
        return extracted
    
    def _extract_from_table(self, content: str) -> List[Foreshadowing]:
        """从表格格式提取伏笔
        
        解析类似以下格式：
        | 伏笔 | 埋设位置 | 铺垫卷 | 揭秘卷 |
        |------|---------|--------|--------|
        | 主角真实身份 | 第1卷 | 第3,5卷 | 第8卷 |
        """
        foreshadowings = []
        
        # 查找伏笔表格区域
        table_patterns = [
            r'##\s*[四4][、.]?\s*关键伏笔布局[\s\S]*?(?=##\s*[五5]|$)',
            r'关键伏笔布局[\s\S]*?(?=##|$)',
            r'\|[^\n]*伏笔[^\n]*\|[\s\S]*?(?=\n\n|##|$)',
        ]
        
        table_content = ""
        for pattern in table_patterns:
            match = re.search(pattern, content)
            if match:
                table_content = match.group(0)
                break
        
        if not table_content:
            return []
        
        # 解析表格行
        # 匹配 | 伏笔内容 | 第X卷 | 第Y,Z卷 | 第W卷 |
        row_pattern = r'\|\s*([^|]+)\s*\|\s*第?(\d+)[卷章]?\s*\|\s*([^|]*)\s*\|\s*第?(\d+)[卷章]?\s*\|'
        
        for match in re.finditer(row_pattern, table_content):
            content_text = match.group(1).strip()
            planted_vol = int(match.group(2))
            pave_text = match.group(3).strip()
            reveal_vol = int(match.group(4))
            
            # 跳过表头
            if '伏笔' in content_text or '埋设' in content_text or '---' in content_text:
                continue
            
            # 解析铺垫卷
            pave_volumes = []
            pave_numbers = re.findall(r'(\d+)', pave_text)
            for num in pave_numbers:
                vol = int(num)
                if planted_vol < vol < reveal_vol:
                    pave_volumes.append(vol)
            
            fs = Foreshadowing(
                content=content_text,
                planted_volume=planted_vol,
                reveal_volume=reveal_vol,
                pave_volumes=pave_volumes,
                status="planned",
                importance="important" if reveal_vol - planted_vol > 3 else "normal"
            )
            foreshadowings.append(fs)
        
        return foreshadowings
    
    def _extract_from_list(self, content: str) -> List[Foreshadowing]:
        """从列表格式提取伏笔
        
        解析类似以下格式：
        - 主角真实身份伏笔（第1卷埋设，第8卷揭秘）
        """
        foreshadowings = []
        
        # 匹配列表项
        list_patterns = [
            r'-\s*([^（(]+)[（(]第?(\d+)卷?埋设[，,]?\s*第?(\d+)卷?揭秘[）)]',
            r'-\s*([^：:]+)[：:]\s*第?(\d+)卷?埋设[，,→]\s*第?(\d+)卷?揭秘',
            r'伏笔\d*[：:]\s*([^（(]+)[（(]?第?(\d+)卷?.*?第?(\d+)卷?[）)]?',
        ]
        
        for pattern in list_patterns:
            for match in re.finditer(pattern, content):
                content_text = match.group(1).strip()
                planted_vol = int(match.group(2))
                reveal_vol = int(match.group(3))
                
                if len(content_text) < 3:
                    continue
                
                fs = Foreshadowing(
                    content=content_text,
                    planted_volume=planted_vol,
                    reveal_volume=reveal_vol,
                    status="planned"
                )
                foreshadowings.append(fs)
        
        return foreshadowings
    
    def _ai_extract_foreshadowings(self, content: str) -> List[Foreshadowing]:
        """使用AI提取伏笔"""
        from langchain_core.messages import SystemMessage, HumanMessage
        
        # 限制输入长度
        content_limited = content[:6000] if len(content) > 6000 else content
        
        prompt = f"""请从以下长篇框架中提取所有伏笔信息。

【长篇框架】
{content_limited}

【提取要求】
找出所有明确提及的伏笔、悬念、暗示，按以下JSON格式输出：

{{
    "foreshadowings": [
        {{
            "content": "伏笔内容描述",
            "planted_volume": 1,
            "reveal_volume": 5,
            "pave_volumes": [2, 3, 4]
        }}
    ]
}}

只输出JSON，不要其他内容。"""

        response = self.llm.invoke([
            SystemMessage(content="你是专业的伏笔分析专家。只输出JSON格式。"),
            HumanMessage(content=prompt)
        ])
        
        # 解析响应
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            data = json.loads(json_match.group(0))
            foreshadowings = []
            for item in data.get("foreshadowings", []):
                fs = Foreshadowing(
                    content=item.get("content", ""),
                    planted_volume=item.get("planted_volume", 1),
                    reveal_volume=item.get("reveal_volume", 1),
                    pave_volumes=item.get("pave_volumes", []),
                    status="planned"
                )
                foreshadowings.append(fs)
            return foreshadowings
        
        return []
    
    def _is_similar(self, text1: str, text2: str, threshold: float = 0.6) -> bool:
        """简单的文本相似度检查"""
        if not text1 or not text2:
            return False
        
        # 简单的Jaccard相似度
        set1 = set(text1)
        set2 = set(text2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return (intersection / union) > threshold if union > 0 else False
    
    def get_tasks_for_volume(self, volume_index: int) -> List[Dict[str, Any]]:
        """获取指定卷的伏笔任务
        
        根据伏笔的埋设/铺垫/揭秘位置，返回本卷需要处理的伏笔
        
        Args:
            volume_index: 卷索引
            
        Returns:
            伏笔任务列表，每项包含action字段指示本卷动作
        """
        tasks = []
        
        for fs in self.foreshadowings:
            task = None
            
            # 本卷需要埋设
            if fs.planted_volume == volume_index and fs.status in ["planned", "planted"]:
                task = {
                    "content": fs.content,
                    "action": "plant",
                    "planted_volume": fs.planted_volume,
                    "reveal_volume": fs.reveal_volume,
                    "importance": fs.importance
                }
            
            # 本卷需要铺垫
            elif volume_index in fs.pave_volumes and fs.status in ["planted", "paving"]:
                task = {
                    "content": fs.content,
                    "action": "pave",
                    "planted_volume": fs.planted_volume,
                    "reveal_volume": fs.reveal_volume,
                    "importance": fs.importance
                }
            
            # 本卷需要揭秘
            elif fs.reveal_volume == volume_index and fs.status in ["planted", "paving"]:
                task = {
                    "content": fs.content,
                    "action": "reveal",
                    "planted_volume": fs.planted_volume,
                    "reveal_volume": fs.reveal_volume,
                    "importance": fs.importance
                }
            
            if task:
                tasks.append(task)
        
        # 按重要性排序
        importance_order = {"critical": 0, "important": 1, "normal": 2, "minor": 3}
        tasks.sort(key=lambda x: importance_order.get(x.get("importance", "normal"), 2))
        
        return tasks
    
    def update_status(self, foreshadowing_id: str, new_status: str):
        """更新伏笔状态
        
        Args:
            foreshadowing_id: 伏笔ID
            new_status: 新状态
        """
        for fs in self.foreshadowings:
            if fs.id == foreshadowing_id:
                fs.status = new_status
                fs.updated_at = datetime.now().isoformat()
                logger.info(f"✅ 伏笔「{fs.content[:20]}...」状态更新为: {new_status}")
                return True
        return False
    
    def mark_volume_completed(self, volume_index: int):
        """标记某卷完成后，自动更新相关伏笔状态
        
        Args:
            volume_index: 已完成的卷索引
        """
        for fs in self.foreshadowings:
            # 如果本卷是埋设卷，更新状态为 planted
            if fs.planted_volume == volume_index and fs.status == "planned":
                fs.status = "planted"
                fs.updated_at = datetime.now().isoformat()
            
            # 如果本卷是揭秘卷，更新状态为 revealed
            elif fs.reveal_volume == volume_index and fs.status in ["planted", "paving"]:
                fs.status = "revealed"
                fs.updated_at = datetime.now().isoformat()
            
            # 如果本卷是铺垫卷，更新状态为 paving
            elif volume_index in fs.pave_volumes and fs.status == "planted":
                fs.status = "paving"
                fs.updated_at = datetime.now().isoformat()
    
    def to_json(self) -> str:
        """序列化为JSON字符串"""
        data = {
            "project_id": self.project_id,
            "foreshadowings": [fs.to_dict() for fs in self.foreshadowings],
            "updated_at": datetime.now().isoformat()
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def from_json(self, json_str: str):
        """从JSON字符串加载"""
        if not json_str:
            return
        
        try:
            data = json.loads(json_str)
            self.foreshadowings = [
                Foreshadowing.from_dict(fs_data) 
                for fs_data in data.get("foreshadowings", [])
            ]
            self._loaded = True
            logger.info(f"✅ 加载了 {len(self.foreshadowings)} 条伏笔记录")
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON解析失败: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """获取伏笔统计摘要"""
        status_counts = {}
        for fs in self.foreshadowings:
            status_counts[fs.status] = status_counts.get(fs.status, 0) + 1
        
        return {
            "total": len(self.foreshadowings),
            "by_status": status_counts,
            "pending_reveal": len([fs for fs in self.foreshadowings 
                                   if fs.status in ["planted", "paving"]])
        }
    
    def generate_prompt_section(self, volume_index: int) -> str:
        """生成本卷的伏笔约束提示词
        
        这是 expand_volume_detail() 中 foreshadowing_section 的数据来源
        
        Args:
            volume_index: 当前卷索引
            
        Returns:
            伏笔约束提示词文本
        """
        tasks = self.get_tasks_for_volume(volume_index)
        
        if not tasks:
            return ""
        
        section = "\n【🎭 本卷伏笔任务】\n"
        
        plant_tasks = [t for t in tasks if t['action'] == 'plant']
        pave_tasks = [t for t in tasks if t['action'] == 'pave']
        reveal_tasks = [t for t in tasks if t['action'] == 'reveal']
        
        if plant_tasks:
            section += "\n**本卷需埋设的伏笔**：\n"
            for t in plant_tasks:
                importance_icon = "🔴" if t['importance'] == 'critical' else "🟡" if t['importance'] == 'important' else "⚪"
                section += f"{importance_icon} {t['content']}（将于第{t['reveal_volume']}卷揭秘）\n"
        
        if pave_tasks:
            section += "\n**本卷需铺垫的伏笔**（已埋设，需强化暗示）：\n"
            for t in pave_tasks:
                section += f"- {t['content']}（埋设于第{t['planted_volume']}卷，揭秘于第{t['reveal_volume']}卷）\n"
        
        if reveal_tasks:
            section += "\n**本卷需揭秘的伏笔**（完成回收，解答悬念）：\n"
            for t in reveal_tasks:
                section += f"- {t['content']}（埋设于第{t['planted_volume']}卷）\n"
        
        return section


def get_foreshadowing_tracker(project_id: int, llm=None) -> ForeshadowingTracker:
    """获取伏笔追踪器实例
    
    Args:
        project_id: 项目ID
        llm: LLM实例（可选）
        
    Returns:
        ForeshadowingTracker实例
    """
    return ForeshadowingTracker(project_id=project_id, llm=llm)
