"""
细纲提取器 - 从已写章节内容反向提取结构化细纲

用于大纲扩展场景：
- 当用户已写完部分章节，想扩展大纲时
- 从已写内容中提取细纲，确保大纲与实际内容一致
- 避免AI生成与已写内容矛盾的大纲
"""

from typing import Dict, Any, Optional, List
from langchain_openai import ChatOpenAI
from .llm_singleton import create_routed_llm
import json
import logging

logger = logging.getLogger(__name__)


class OutlineExtractor:
    """细纲提取器：从章节内容反向提取结构化细纲"""
    
    def __init__(self, llm: Optional[ChatOpenAI] = None):
        """
        初始化细纲提取器
        
        Args:
            llm: 语言模型实例，如果不提供则使用默认配置
        """
        if llm is None:
            from app.core.config import settings
            model = getattr(settings, "DEEPSEEK_MODEL", None) or getattr(settings, "MODEL_NAME", "qwen3-max")
            self.llm = create_routed_llm(model=model, temperature=0.3)
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
            - scene_objective: 场景目标
            - conflict_design: 冲突设计
            - emotion_curve: 情绪曲线
            - climax_points: 爽点类型
            - ending_hook: 结尾钩子
            - key_events: 关键事件列表
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

## 情绪曲线
（30-50字，读者情绪如何变化？从什么状态到什么状态？）

## 爽点类型
（20-40字，本章的核心爽点是什么？打脸/逆袭/获得/突破/揭秘等）

## 结尾钩子
（20-40字，章节结尾留下什么悬念或期待？）

## 关键事件
（列出3-5个关键情节节点，每个10-20字）
1. 
2. 
3. 

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
            "scene_objective": "",
            "conflict_design": "",
            "emotion_curve": "",
            "climax_points": "",
            "ending_hook": "",
            "key_events": []
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
                    extracted["scene_objective"] = content.replace("（", "").replace("）", "")[:200]
                
                # 提取冲突设计
                elif section.startswith("冲突设计"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["conflict_design"] = content.replace("（", "").replace("）", "")[:300]
                
                # 提取情绪曲线
                elif section.startswith("情绪曲线"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["emotion_curve"] = content.replace("（", "").replace("）", "")[:200]
                
                # 提取爽点类型
                elif section.startswith("爽点类型"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["climax_points"] = content.replace("（", "").replace("）", "")[:150]
                
                # 提取结尾钩子
                elif section.startswith("结尾钩子"):
                    content = section.split("\n", 1)[-1].strip()
                    extracted["ending_hook"] = content.replace("（", "").replace("）", "")[:150]
                
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
            
            # 验证关键字段
            if not extracted["scene_objective"]:
                extracted["scene_objective"] = "场景目标未明确提取"
            if not extracted["conflict_design"]:
                extracted["conflict_design"] = "冲突设计未明确提取"
            
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
            "scene_objective": f"[自动提取] {chapter_title}",
            "conflict_design": summary,
            "emotion_curve": "未提取",
            "climax_points": "未提取",
            "ending_hook": "未提取",
            "key_events": [],
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
        if outline_data.get("scene_objective"):
            text += f"**场景目标**：{outline_data['scene_objective']}\n\n"
        
        # 冲突设计
        if outline_data.get("conflict_design"):
            text += f"**冲突设计**：{outline_data['conflict_design']}\n\n"
        
        # 情绪曲线
        if outline_data.get("emotion_curve"):
            text += f"**情绪曲线**：{outline_data['emotion_curve']}\n\n"
        
        # 爽点类型
        if outline_data.get("climax_points"):
            text += f"**爽点类型**：{outline_data['climax_points']}\n\n"
        
        # 结尾钩子
        if outline_data.get("ending_hook"):
            text += f"**结尾钩子**：{outline_data['ending_hook']}\n\n"
        
        # 关键事件
        if outline_data.get("key_events"):
            text += "**关键事件**：\n"
            for idx, event in enumerate(outline_data["key_events"], 1):
                text += f"{idx}. {event}\n"
            text += "\n"
        
        return text


def create_outline_extractor(llm: Optional[ChatOpenAI] = None) -> OutlineExtractor:
    """
    创建细纲提取器实例的工厂函数
    
    Args:
        llm: 可选的LLM实例
    
    Returns:
        OutlineExtractor实例
    """
    return OutlineExtractor(llm=llm)
