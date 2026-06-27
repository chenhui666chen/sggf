"""
细纲提取器 - 从已写章节内容反向提取结构化细纲

用于大纲扩展场景：
- 当用户已写完部分章节，想扩展大纲时
- 从已写内容中提取细纲，确保大纲与实际内容一致
- 避免AI生成与已写内容矛盾的大纲
"""

from typing import Any, Dict, List, Optional
from core.langchain_bridge import create_model_llm
import json
import logging

logger = logging.getLogger(__name__)


class OutlineExtractor:
    """细纲提取器：从章节内容反向提取结构化细纲"""
    
    def __init__(self, llm: Optional[Any] = None):
        """
        初始化细纲提取器
        
        Args:
            llm: 语言模型实例，如果不提供则使用默认配置
        """
        if llm is None:
            from app.core.config import settings
            model = getattr(settings, "DEEPSEEK_MODEL", None) or getattr(settings, "MODEL_NAME", "qwen3.7-plus")
            self.llm = create_model_llm(model=model, temperature=0.3)
        else:
            self.llm = llm
    
    def extract_from_chapter(
        self,
        chapter_content: str,
        chapter_number: int,
        chapter_title: str,
        genre: str = "",
        world_context: str = "",
    ) -> Dict[str, Any]:
        """
        从单个章节内容中提取结构化细纲
        
        Args:
            chapter_content: 章节正文内容
            chapter_number: 章节序号
            chapter_title: 章节标题
            genre: 题材类型（修仙/玄幻/都市等）
            world_context: 世界观背景（可选，帮助提取更准确）
        
        Returns:
            结构化细纲字典，包含：
            - chapter_number: 章节号
            - title: 章节标题
            - scene_goal: 场景目标
            - conflict_design: 冲突设计
            - key_events: 关键事件列表
            - involved_characters: 涉及人物
            - character_progress: 人物推进
            - plot_function: 情节作用
            - ending_hook: 结尾钩子
            - highlight_type: 爽点类型（可选）
            - foreshadowing_item: 伏笔事项（可选）
        """
        logger.info(f"🔍 开始提取第{chapter_number}章细纲：{chapter_title}")
        
        # 截取内容（避免超长）
        content_preview = chapter_content[:4000] if len(chapter_content) > 4000 else chapter_content
        word_count = len(chapter_content.replace(' ', '').replace('\n', ''))
        
        # 构建提取提示词
        prompt = self._build_extraction_prompt(
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            content=content_preview,
            genre=genre,
            world_context=world_context,
            word_count=word_count
        )
        
        try:
            # 调用LLM提取
            response = self.llm.invoke(prompt)
            result_text = response.content if hasattr(response, 'content') else str(response)
            
            # 解析提取结果
            extracted_data = self._parse_extraction_result(result_text)
            
            # 补充元数据
            extracted_data.update({
                "chapter_number": chapter_number,
                "title": chapter_title,
                "word_count": word_count,
                "extraction_method": "ai_extraction"
            })
            
            logger.info(f"✅ 第{chapter_number}章细纲提取完成")
            return extracted_data
            
        except Exception as e:
            logger.error(f"❌ 提取第{chapter_number}章细纲失败: {e}")
            # 返回降级结果
            return self._create_fallback_outline(
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                content=content_preview
            )
    
    def extract_batch(
        self,
        chapters: List[Dict[str, Any]],
        genre: str = "",
        world_context: str = "",
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        批量提取多个章节的细纲
        
        Args:
            chapters: 章节列表，每个元素包含 {chapter_number, title, content}
            genre: 题材类型
            world_context: 世界观背景
            progress_callback: 进度回调函数 callback(current, total, chapter_number)
        
        Returns:
            细纲列表
        """
        logger.info(f"📚 开始批量提取 {len(chapters)} 章细纲")
        
        extracted_outlines = []
        total = len(chapters)
        
        for idx, chapter_data in enumerate(chapters, 1):
            try:
                outline = self.extract_from_chapter(
                    chapter_content=chapter_data.get("content", ""),
                    chapter_number=chapter_data.get("chapter_number", idx),
                    chapter_title=chapter_data.get("title", f"第{idx}章"),
                    genre=genre,
                    world_context=world_context
                )
                extracted_outlines.append(outline)
                
                # 回调进度
                if progress_callback:
                    progress_callback(idx, total, chapter_data.get("chapter_number", idx))
                    
            except Exception as e:
                logger.error(f"❌ 提取第{idx}章时失败: {e}")
                # 继续处理下一章
                continue
        
        logger.info(f"✅ 批量提取完成，成功 {len(extracted_outlines)}/{total} 章")
        return extracted_outlines
    
    def _build_extraction_prompt(
        self,
        chapter_number: int,
        chapter_title: str,
        content: str,
        genre: str,
        world_context: str,
        word_count: int
    ) -> str:
        """构建细纲提取提示词"""
        
        genre_context = f"\n题材类型：{genre}" if genre else ""
        world_ctx = f"\n\n【世界观背景】\n{world_context[:500]}" if world_context else ""
        
        prompt = f"""你是一位专业的网文编辑，擅长从已写章节中提取结构化细纲。

【任务】
请从以下章节内容中提取细纲要素，确保提取结果准确反映实际剧情发展。

【章节信息】
- 章节号：第{chapter_number}章
- 标题：{chapter_title}
- 字数：约{word_count}字{genre_context}{world_ctx}

【章节内容】
{content}

【提取要求】
请按以下格式提取细纲（必须基于实际内容，不要臆测）：

## 场景目标
（30-50字，本章主要想达成什么目标？主角的核心诉求是什么？）

## 冲突设计
（80-120字，本章的主要冲突是什么？冲突如何展开和升级？包含几个关键节点）

## 关键事件
（列出3-5个关键情节节点，每个10-20字）
1. 
2. 
3. 

## 涉及人物
（列出本章最关键的出场人物，使用顿号分隔）

## 人物推进
（30-60字，本章人物关系、立场、心理或能力出现了什么关键变化）

## 情节作用
（30-60字，本章在整段剧情中的职责，例如承接/升级/转折/伏笔回收）

## 结尾钩子
（20-40字，章节结尾留下什么悬念或下一章驱动力）

## 爽点类型
（可选，20-40字；如本章没有明确爽点可写“无”）

## 伏笔事项
（可选，20-40字；如没有明确伏笔可写“无”）

【注意事项】
1. 必须基于实际内容提取，不要添加原文没有的情节
2. 如果某个要素在章节中不明显，说明"未明确体现"
3. 使用简洁、专业的语言描述
4. 保持客观中立，不做主观评价
"""
        return prompt
    
    def _parse_extraction_result(self, result_text: str) -> Dict[str, Any]:
        """解析LLM返回的提取结果"""
        
        # 初始化结果字典
        extracted = {
            "scene_goal": "",
            "conflict_design": "",
            "key_events": [],
            "involved_characters": "",
            "character_progress": "",
            "plot_function": "",
            "ending_hook": "",
            "highlight_type": "",
            "foreshadowing_item": "",
        }
        
        try:
            # 按段落拆分
            sections = result_text.split("##")
            
            for section in sections:
                section = section.strip()
                if not section:
                    continue
                
                # 提取场景目标
                if section.startswith("场景目标") or section.startswith("场景目标"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["scene_goal"] = content.replace("（", "").replace("）", "")[:200]
                
                # 提取冲突设计
                elif section.startswith("冲突设计"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["conflict_design"] = content.replace("（", "").replace("）", "")[:300]
                
                # 提取关键事件
                elif section.startswith("关键事件"):
                    lines = section.split("\n")[1:]  # 跳过标题行
                    events = []
                    for line in lines:
                        line = line.strip()
                        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
                            # 移除序号
                            event = line.lstrip("0123456789.-•、 ").strip()
                            if event and len(event) > 3:
                                events.append(event[:100])
                    extracted["key_events"] = events[:5]  # 最多5个

                elif section.startswith("涉及人物"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["involved_characters"] = content.replace("（", "").replace("）", "")[:120]

                elif section.startswith("人物推进"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["character_progress"] = content.replace("（", "").replace("）", "")[:200]

                elif section.startswith("情节作用"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["plot_function"] = content.replace("（", "").replace("）", "")[:200]

                elif section.startswith("结尾钩子"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["ending_hook"] = content.replace("（", "").replace("）", "")[:150]

                elif section.startswith("爽点类型"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["highlight_type"] = content.replace("（", "").replace("）", "")[:150]

                elif section.startswith("伏笔事项"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["foreshadowing_item"] = content.replace("（", "").replace("）", "")[:150]
            
            # 验证关键字段
            if not extracted["scene_goal"]:
                extracted["scene_goal"] = "场景目标未明确提取"
            if not extracted["conflict_design"]:
                extracted["conflict_design"] = "冲突设计未明确提取"
            if not extracted["involved_characters"]:
                extracted["involved_characters"] = "待补充"
            if not extracted["character_progress"]:
                extracted["character_progress"] = "人物关系或状态出现阶段性变化。"
            if not extracted["plot_function"]:
                extracted["plot_function"] = "承接本章已发生事件并推动后续主线。"
            
            return extracted
            
        except Exception as e:
            logger.error(f"⚠️ 解析提取结果失败: {e}")
            return extracted
    
    def _create_fallback_outline(
        self,
        chapter_number: int,
        chapter_title: str,
        content: str
    ) -> Dict[str, Any]:
        """创建降级细纲（当AI提取失败时）"""
        
        # 简单提取前200字作为摘要
        summary = content[:200].strip() + "..." if len(content) > 200 else content.strip()
        
        return {
            "chapter_number": chapter_number,
            "title": chapter_title,
            "scene_goal": f"[自动提取] {chapter_title}",
            "conflict_design": summary,
            "key_events": [],
            "involved_characters": "待补充",
            "character_progress": "人物关系或状态出现阶段性变化。",
            "plot_function": "承接本章已发生事件并推动后续主线。",
            "ending_hook": "待补充",
            "highlight_type": "",
            "foreshadowing_item": "",
            "extraction_method": "fallback"
        }
    
    def format_outline_text(self, outline_data: Dict[str, Any]) -> str:
        """
        将提取的细纲数据格式化为标准文本
        
        Args:
            outline_data: 提取的细纲字典
        
        Returns:
            格式化的细纲文本
        """
        chapter_num = outline_data.get("chapter_number", 0)
        title = outline_data.get("title", "")
        
        text = f"### 第{chapter_num}章：{title}\n\n"
        
        # 场景目标
        if outline_data.get("scene_goal"):
            text += f"**场景目标**：{outline_data['scene_goal']}\n\n"
        
        # 冲突设计
        if outline_data.get("conflict_design"):
            text += f"**冲突设计**：{outline_data['conflict_design']}\n\n"
        
        # 关键事件
        if outline_data.get("key_events"):
            text += "**关键事件**：\n"
            for idx, event in enumerate(outline_data["key_events"], 1):
                text += f"{idx}. {event}\n"
            text += "\n"

        if outline_data.get("involved_characters"):
            text += f"**涉及人物**：{outline_data['involved_characters']}\n\n"

        if outline_data.get("character_progress"):
            text += f"**人物推进**：{outline_data['character_progress']}\n\n"

        if outline_data.get("plot_function"):
            text += f"**情节作用**：{outline_data['plot_function']}\n\n"

        if outline_data.get("ending_hook"):
            text += f"**结尾钩子**：{outline_data['ending_hook']}\n\n"

        if outline_data.get("highlight_type"):
            text += f"**爽点类型**：{outline_data['highlight_type']}\n\n"

        if outline_data.get("foreshadowing_item"):
            text += f"**伏笔事项**：{outline_data['foreshadowing_item']}\n\n"
        
        return text


def create_outline_extractor(llm: Optional[Any] = None) -> OutlineExtractor:
    """
    创建细纲提取器实例的工厂函数
    
    Args:
        llm: 可选的LLM实例
    
    Returns:
        OutlineExtractor实例
    """
    return OutlineExtractor(llm=llm)

