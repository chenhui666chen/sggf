"""
章节摘要生成器 - 自动生成核心事件摘要，减少AI上下文长度
"""
from typing import Dict, Any, List, Optional
import json
import logging
import re

logger = logging.getLogger(__name__)
from .agents import CreativeDirectorAgent
from core.langchain_bridge import create_task_llm
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from app.services.chapter_adaptation_assets import attach_cross_media_adaptation_hints, load_summary_data
from app.services.exact_model_guard import require_exact_model


class ChapterSummarizer:
    """章节摘要生成器
    
    功能：
    1. 为每个章节生成核心事件摘要（200-300字）
    2. 提取关键信息：人物、事件、地点、转折
    3. 生成新章节时使用摘要而非全文
    4. 大幅减少AI上下文长度，支持更长的小说
    """

    EXTENDED_SUMMARY_DEFAULTS = {
        "scene_goal": "",
        "appearing_characters": [],
        "conflict_arc": {},
        "emotion_curve": "",
        "highlight": {},
        "gains": {},
        "ending_hook": {},
        "foreshadowing": [],
    }
    
    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 db_session = None,
                 model: Optional[str] = None):
        """初始化摘要生成器
        
        Args:
            knowledge_base: 知识库实例
            memory_manager: 记忆管理器实例
            db_session: 数据库会话，用于缓存摘要
            model: 指定摘要生成模型（🆕 免费档锁定模型用，缺省保持默认路由）
        """
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.db_session = db_session
        
        # 初始化AI Agent
        self.creative_director = CreativeDirectorAgent(self.knowledge_base, self.memory_manager)
        self.llm = create_task_llm(model=require_exact_model(model))
    
    def generate_chapter_summary(self, chapter_number: int, chapter_title: str, 
                                chapter_content: str, summary_length: int = 300) -> Dict[str, Any]:
        """生成单个章节的核心事件摘要
        
        Args:
            chapter_number: 章节编号
            chapter_title: 章节标题
            chapter_content: 章节完整内容
            summary_length: 摘要目标字数（默认300字）
            
        Returns:
            摘要字典，包含:
            - chapter_number: 章节编号
            - chapter_title: 章节标题
            - core_summary: 核心事件摘要
            - key_characters: 关键人物列表
            - key_events: 核心事件列表
            - key_locations: 重要地点列表
            - plot_advancement: 情节推进描述
            - hooks: 悬念/伏笔
        """
        logger.debug(f"\n【章节摘要生成器】正在为第{chapter_number}章生成摘要...")
        
        # 生成可复用的结构化章节资产
        summary_prompt = f"""你是一位专业的长篇小说章节资产整理专家。请为以下章节生成高密度、可复用的结构化摘要。

【章节信息】
- 章节编号：第{chapter_number}章
- 章节标题：{chapter_title}

【完整章节内容】
{chapter_content}

请严格按以下结构输出，并尽量补齐信息：

【核心事件摘要】
用{summary_length}字以内概括本章真正推进了什么，重点写主线推进、人物动作、冲突变化和阶段性结果。

【场景目标】
用一句话写清本章最核心的剧情目标。

【关键人物】
- 人物名：本章作用/状态变化

【核心事件】
- 事件描述

【重要地点】
- 地点名：该地点发生了什么

【冲突弧】
- 触发：冲突因何产生
- 升级：冲突如何升级
- 结果：冲突阶段性结果

【情绪曲线】
用短语概括，如“压抑→试探→反击→余震”。

【高光设计】
- 类型：如揭示/反转/爽点/情感爆发/动作高潮
- 描述：本章最值得保留的高光时刻

【本章收获】
- 人物收获：人物关系、状态、认知或能力上的变化
- 剧情推进：主线或支线被推进到什么位置

【情节推进】
一句话说明本章对整体故事的功能。

【结尾钩子】
- 类型：悬念/危机/揭示/反转/情感/伏笔
- 内容：结尾留下的继续阅读动力

【悬念/伏笔】
- 尚未回收的线索或后续必须承接的信息

输出要求：
- 只保留后续创作、协同扩展、连续性承接真正需要的信息
- 忽略次要描写、重复对话和纯氛围文字
- 人物名保持稳定，不要用“主角”“反派”替代真实称呼
- 如果某项确实没有内容，保留标题并写“无”或留空，不要编造
- 关键人物与出场人物要尽量覆盖本章实际推进剧情的人物
- 结尾钩子、伏笔、冲突弧必须优先准确，不要写成泛泛总结

请直接按上述标题输出：
"""
        
        # 调用AI生成摘要
        summary_result = self.creative_director.process(summary_prompt, {})
        
        # 解析摘要结果 - 提取结构化信息
        parsed_summary = self._parse_summary_result(summary_result)
        
        result = {
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "full_summary": summary_result,
            "core_summary": parsed_summary.get("core_summary", ""),
            "scene_goal": parsed_summary.get("scene_goal", ""),
            "key_characters": parsed_summary.get("key_characters", []),
            "appearing_characters": parsed_summary.get("appearing_characters", []),
            "key_events": parsed_summary.get("key_events", []),
            "key_locations": parsed_summary.get("key_locations", []),
            "conflict_arc": parsed_summary.get("conflict_arc", {}),
            "emotion_curve": parsed_summary.get("emotion_curve", ""),
            "highlight": parsed_summary.get("highlight", {}),
            "gains": parsed_summary.get("gains", {}),
            "plot_advancement": parsed_summary.get("plot_advancement", ""),
            "ending_hook": parsed_summary.get("ending_hook", {}),
            "foreshadowing": parsed_summary.get("foreshadowing", []),
            "hooks": parsed_summary.get("hooks", []),
            "summary_length": len(summary_result)
        }
        
        result = attach_cross_media_adaptation_hints(
            result,
            chapter_title=chapter_title,
            chapter_summary=result.get("core_summary", ""),
        )

        logger.debug(f"✅ 第{chapter_number}章摘要生成完成（{result['summary_length']}字）")
        logger.debug(f"   - 核心摘要：{len(result['core_summary'])}字")
        logger.debug(f"   - 关键人物：{len(result['key_characters'])}个")
        logger.debug(f"   - 核心事件：{len(result['key_events'])}个")
        
        return result
    
    def generate_batch_summaries(self, chapters: List[Dict[str, str]], 
                                summary_length: int = 300) -> List[Dict[str, Any]]:
        """批量生成多个章节的摘要
        
        Args:
            chapters: 章节列表，每个元素是字典 {"chapter_number": 1, "title": "...", "content": "..."}
            summary_length: 每个摘要的目标字数
            
        Returns:
            摘要列表
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【批量摘要生成】开始为 {len(chapters)} 个章节生成摘要")
        logger.debug(f"{'='*70}\n")
        
        summaries = []
        
        for i, chapter in enumerate(chapters, 1):
            chapter_number = int(chapter.get("chapter_number", i))
            chapter_title = chapter.get("title", f"第{chapter_number}章")
            chapter_content = chapter.get("content", "")
            
            if not chapter_content:
                logger.debug(f"⚠️ 第{chapter_number}章内容为空，跳过")
                continue
            
            # 生成摘要
            summary = self.generate_chapter_summary(
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                chapter_content=chapter_content,
                summary_length=summary_length
            )
            
            summaries.append(summary)
            
            logger.debug(f"进度：{i}/{len(chapters)} 完成\n")
        
        logger.debug(f"{'='*70}")
        logger.debug(f"【批量摘要生成】全部完成！共生成 {len(summaries)} 个摘要")
        logger.debug(f"{'='*70}\n")
        
        return summaries
    
    def create_context_for_new_chapter(self, previous_summaries: List[Dict[str, Any]], 
                                      recent_full_chapters: Optional[List[str]] = None,
                                      max_recent_chapters: int = 2) -> str:
        """为生成新章节创建优化的上下文
        
        策略：
        - 早期章节：使用摘要（节省token）
        - 最近章节：使用完整内容（保证衔接）
        - 平衡上下文长度和信息质量
        
        Args:
            previous_summaries: 之前所有章节的摘要列表
            recent_full_chapters: 最近几章的完整内容（可选）
            max_recent_chapters: 保留几章完整内容（默认2章）
            
        Returns:
            优化后的上下文字符串
        """
        logger.debug(f"\n【上下文优化器】为新章节创建优化上下文...")
        
        context_parts = []
        
        # 第一部分：早期章节摘要
        if len(previous_summaries) > max_recent_chapters:
            context_parts.append("【前期章节核心事件摘要】")
            context_parts.append("（以下是早期章节的核心事件摘要，用于了解整体剧情发展）\n")
            
            # 只使用摘要的章节
            early_summaries = previous_summaries[:-max_recent_chapters]
            
            for summary in early_summaries:
                chapter_num = summary.get("chapter_number", "?")
                chapter_title = summary.get("chapter_title", "未命名")
                full_summary = summary.get("full_summary", "")
                
                context_parts.append(f"第{chapter_num}章《{chapter_title}》摘要：")
                context_parts.append(full_summary)
                context_parts.append("")  # 空行
        
        # 第二部分：最近章节完整内容
        if recent_full_chapters and len(recent_full_chapters) > 0:
            context_parts.append("\n" + "="*70)
            context_parts.append("【最近章节完整内容】")
            context_parts.append("（以下是最近几章的完整内容，用于确保情节衔接自然）\n")
            
            # 同时获取最近章节的摘要信息
            recent_summaries = previous_summaries[-max_recent_chapters:] if len(previous_summaries) >= max_recent_chapters else previous_summaries
            
            for i, (full_content, summary) in enumerate(zip(recent_full_chapters[-max_recent_chapters:], recent_summaries)):
                chapter_num = summary.get("chapter_number", "?")
                chapter_title = summary.get("chapter_title", "未命名")
                
                context_parts.append(f"\n第{chapter_num}章《{chapter_title}》完整内容：")
                context_parts.append(full_content)
                context_parts.append("\n" + "-"*70)
        
        # 第三部分：统计信息
        total_chapters = len(previous_summaries)
        summary_count = max(0, total_chapters - max_recent_chapters)
        full_count = min(total_chapters, max_recent_chapters)
        
        context_parts.append(f"\n【上下文统计】")
        context_parts.append(f"- 总章节数：{total_chapters}")
        context_parts.append(f"- 摘要章节：{summary_count} 章（第1-{summary_count}章）")
        context_parts.append(f"- 完整章节：{full_count} 章（第{total_chapters-full_count+1}-{total_chapters}章）")
        
        context = "\n".join(context_parts)
        
        logger.debug(f"✅ 上下文优化完成")
        logger.debug(f"   - 总章节数：{total_chapters}")
        logger.debug(f"   - 使用摘要：{summary_count} 章")
        logger.debug(f"   - 使用完整内容：{full_count} 章")
        logger.debug(f"   - 总上下文长度：{len(context)} 字符\n")
        
        return context
    
    def estimate_context_savings(self, chapters: List[Dict[str, str]], 
                                summary_length: int = 300,
                                recent_full_count: int = 2) -> Dict[str, Any]:
        """估算使用摘要后的上下文节省量
        
        Args:
            chapters: 章节列表
            summary_length: 每个摘要的目标字数
            recent_full_count: 保留完整内容的最近章节数
            
        Returns:
            节省量统计字典
        """
        total_chapters = len(chapters)
        
        if total_chapters == 0:
            return {
                "total_chapters": 0,
                "full_context_length": 0,
                "optimized_context_length": 0,
                "savings": 0,
                "savings_percentage": 0
            }
        
        # 计算使用完整内容的总长度
        full_context_length = sum(len(ch.get("content", "")) for ch in chapters)
        
        # 计算优化后的长度
        # = (早期章节数 × 摘要长度) + (最近章节的完整长度)
        early_chapter_count = max(0, total_chapters - recent_full_count)
        recent_chapters = chapters[-recent_full_count:] if total_chapters >= recent_full_count else chapters
        recent_full_length = sum(len(ch.get("content", "")) for ch in recent_chapters)
        
        optimized_context_length = (early_chapter_count * summary_length) + recent_full_length
        
        # 计算节省量
        savings = full_context_length - optimized_context_length
        savings_percentage = (savings / full_context_length * 100) if full_context_length > 0 else 0
        
        return {
            "total_chapters": total_chapters,
            "full_context_length": full_context_length,
            "optimized_context_length": optimized_context_length,
            "savings": savings,
            "savings_percentage": savings_percentage,
            "early_chapter_count": early_chapter_count,
            "recent_full_count": len(recent_chapters),
            "avg_chapter_length": full_context_length // total_chapters if total_chapters > 0 else 0,
            "summary_length": summary_length
        }
    
    def print_savings_report(self, savings_stats: Dict[str, Any]):
        """打印上下文节省量报告
        
        Args:
            savings_stats: estimate_context_savings的返回值
        """
        logger.debug(f"\n{'='*70}")
        logger.debug("【上下文优化效果报告】")
        logger.debug(f"{'='*70}\n")
        
        logger.debug(f"📊 章节统计")
        logger.debug(f"   - 总章节数：{savings_stats['total_chapters']} 章")
        logger.debug(f"   - 使用摘要：{savings_stats['early_chapter_count']} 章")
        logger.debug(f"   - 保留完整：{savings_stats['recent_full_count']} 章")
        logger.debug(f"   - 平均章节长度：{savings_stats['avg_chapter_length']:,} 字符\n")
        
        logger.debug(f"💾 上下文长度对比")
        logger.debug(f"   - 原始上下文：{savings_stats['full_context_length']:,} 字符")
        logger.debug(f"   - 优化后上下文：{savings_stats['optimized_context_length']:,} 字符")
        logger.debug(f"   - 节省量：{savings_stats['savings']:,} 字符")
        logger.debug(f"   - 节省比例：{savings_stats['savings_percentage']:.1f}%\n")
        
        logger.debug(f"🎯 效果评估")
        if savings_stats['savings_percentage'] >= 70:
            logger.debug(f"   ✅ 优秀！大幅减少了上下文长度")
        elif savings_stats['savings_percentage'] >= 50:
            logger.debug(f"   ✅ 良好！有效减少了上下文长度")
        elif savings_stats['savings_percentage'] >= 30:
            logger.debug(f"   ⚠️  一般，建议增加使用摘要的章节数")
        else:
            logger.debug(f"   ⚠️  效果有限，可能是因为章节总数较少")
        
        logger.debug(f"\n💡 建议")
        if savings_stats['total_chapters'] <= 5:
            logger.debug(f"   - 当前章节较少，暂时不需要使用摘要优化")
        elif savings_stats['total_chapters'] <= 20:
            logger.debug(f"   - 建议保留最近 2-3 章完整内容，其余使用摘要")
        else:
            logger.debug(f"   - 建议保留最近 2-3 章完整内容，其余使用摘要")
            logger.debug(f"   - 预计可节省 {savings_stats['savings_percentage']:.0f}% 的上下文长度")
        
        logger.debug(f"\n{'='*70}\n")


    def _extract_section(self, summary_text: str, title: str) -> str:
        pattern = rf"【\s*{re.escape(title)}\s*】\s*(.*?)(?=\n\s*【[^】]+】|\Z)"
        match = re.search(pattern, summary_text, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _clean_scalar_text(self, value: Any, *, max_length: int = 200) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text or text in {"无", "暂无", "待补充", "无明显内容"}:
            return ""
        if len(text) > max_length:
            return text[: max_length - 3].rstrip() + "..."
        return text

    def _deduplicate_items(self, items: List[str]) -> List[str]:
        deduplicated: List[str] = []
        seen = set()
        for item in items:
            text = self._clean_scalar_text(item)
            if not text or text in seen:
                continue
            deduplicated.append(text)
            seen.add(text)
        return deduplicated

    def _parse_list_section(self, content: str) -> List[str]:
        if not content.strip():
            return []

        items: List[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^[-*•]\s*", line):
                line = re.sub(r"^[-*•]\s*", "", line).strip()
            elif re.match(r"^\d+[.)、]\s*", line):
                line = re.sub(r"^\d+[.)、]\s*", "", line).strip()
            text = self._clean_scalar_text(line)
            if text:
                items.append(text)

        if not items:
            inline_text = self._clean_scalar_text(content)
            if inline_text:
                items.append(inline_text)

        return self._deduplicate_items(items)

    def _parse_kv_section(self, content: str, label_map: Dict[str, str]) -> Dict[str, str]:
        parsed: Dict[str, str] = {}
        if not content.strip():
            return parsed

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^[-*•]\s*", "", line)
            line = re.sub(r"^\d+[.)、]\s*", "", line)
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue

            normalized_key = label_map.get(key.strip())
            normalized_value = self._clean_scalar_text(value)
            if normalized_key and normalized_value:
                parsed[normalized_key] = normalized_value

        if not parsed:
            fallback_text = self._clean_scalar_text(content)
            if fallback_text:
                first_key = next(iter(label_map.values()))
                parsed[first_key] = fallback_text

        return parsed

    def _extract_character_names(self, key_characters: List[str]) -> List[str]:
        names: List[str] = []
        for item in key_characters:
            text = self._clean_scalar_text(item, max_length=80)
            if not text:
                continue
            name = re.split(r"[:：\-（(]", text, maxsplit=1)[0].strip()
            if 0 < len(name) <= 20:
                names.append(name)
        return self._deduplicate_items(names)

    def _merge_hook_items(self, ending_hook: Dict[str, Any], foreshadowing: List[str], hooks: List[str]) -> List[str]:
        merged: List[str] = []
        ending_text = self._clean_scalar_text(ending_hook.get("content"), max_length=120)
        if ending_text:
            merged.append(ending_text)
        merged.extend(self._deduplicate_items(foreshadowing))
        merged.extend(self._deduplicate_items(hooks))
        return self._deduplicate_items(merged)

    def _build_summary_payload(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        raw_payload = {
            "core_summary": self._clean_scalar_text(summary.get("core_summary"), max_length=600),
            "scene_goal": self._clean_scalar_text(summary.get("scene_goal"), max_length=120),
            "key_characters": self._deduplicate_items(list(summary.get("key_characters") or [])),
            "appearing_characters": self._deduplicate_items(list(summary.get("appearing_characters") or [])),
            "key_events": self._deduplicate_items(list(summary.get("key_events") or [])),
            "key_locations": self._deduplicate_items(list(summary.get("key_locations") or [])),
            "conflict_arc": summary.get("conflict_arc") if isinstance(summary.get("conflict_arc"), dict) else {},
            "emotion_curve": self._clean_scalar_text(summary.get("emotion_curve"), max_length=80),
            "highlight": summary.get("highlight") if isinstance(summary.get("highlight"), dict) else {},
            "gains": summary.get("gains") if isinstance(summary.get("gains"), dict) else {},
            "plot_advancement": self._clean_scalar_text(summary.get("plot_advancement"), max_length=160),
            "ending_hook": summary.get("ending_hook") if isinstance(summary.get("ending_hook"), dict) else {},
            "foreshadowing": self._deduplicate_items(list(summary.get("foreshadowing") or [])),
            "hooks": self._deduplicate_items(list(summary.get("hooks") or [])),
        }
        normalized = self._normalize_summary_dict(
            raw_payload,
            chapter_number=summary.get("chapter_number"),
            chapter_title=summary.get("chapter_title", ""),
            full_summary=summary.get("full_summary", ""),
        )
        return attach_cross_media_adaptation_hints(
            normalized,
            chapter_title=summary.get("chapter_title", "") or "",
            chapter_summary=normalized.get("core_summary", ""),
        )

    def _normalize_summary_dict(
        self,
        payload: Dict[str, Any],
        *,
        chapter_number: Optional[int] = None,
        chapter_title: str = "",
        full_summary: str = "",
    ) -> Dict[str, Any]:
        summary_payload = load_summary_data(payload)
        normalized: Dict[str, Any] = {
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "full_summary": full_summary or self._clean_scalar_text(summary_payload.get("full_summary"), max_length=4000),
            "core_summary": self._clean_scalar_text(summary_payload.get("core_summary"), max_length=600),
            "key_characters": self._deduplicate_items(list(summary_payload.get("key_characters") or [])),
            "key_events": self._deduplicate_items(list(summary_payload.get("key_events") or [])),
            "key_locations": self._deduplicate_items(list(summary_payload.get("key_locations") or [])),
            "plot_advancement": self._clean_scalar_text(summary_payload.get("plot_advancement"), max_length=160),
            "hooks": self._deduplicate_items(list(summary_payload.get("hooks") or [])),
        }
        normalized.update(
            {
                key: value.copy() if isinstance(value, (list, dict)) else value
                for key, value in self.EXTENDED_SUMMARY_DEFAULTS.items()
            }
        )

        normalized["scene_goal"] = self._clean_scalar_text(summary_payload.get("scene_goal"), max_length=120)
        normalized["appearing_characters"] = self._deduplicate_items(
            list(summary_payload.get("appearing_characters") or [])
        )
        normalized["emotion_curve"] = self._clean_scalar_text(summary_payload.get("emotion_curve"), max_length=80)
        normalized["foreshadowing"] = self._deduplicate_items(list(summary_payload.get("foreshadowing") or []))

        conflict_arc = summary_payload.get("conflict_arc")
        if isinstance(conflict_arc, dict):
            normalized["conflict_arc"] = {
                key: self._clean_scalar_text(value, max_length=120)
                for key, value in conflict_arc.items()
                if self._clean_scalar_text(value, max_length=120)
            }
        elif self._clean_scalar_text(conflict_arc, max_length=120):
            normalized["conflict_arc"] = {"description": self._clean_scalar_text(conflict_arc, max_length=120)}

        highlight = summary_payload.get("highlight")
        if isinstance(highlight, dict):
            normalized["highlight"] = {
                key: self._clean_scalar_text(value, max_length=120)
                for key, value in highlight.items()
                if self._clean_scalar_text(value, max_length=120)
            }
        elif self._clean_scalar_text(highlight, max_length=120):
            normalized["highlight"] = {"description": self._clean_scalar_text(highlight, max_length=120)}

        gains = summary_payload.get("gains")
        if isinstance(gains, dict):
            normalized["gains"] = {
                key: self._clean_scalar_text(value, max_length=120)
                for key, value in gains.items()
                if self._clean_scalar_text(value, max_length=120)
            }

        ending_hook = summary_payload.get("ending_hook")
        if isinstance(ending_hook, dict):
            normalized["ending_hook"] = {
                key: self._clean_scalar_text(value, max_length=120)
                for key, value in ending_hook.items()
                if self._clean_scalar_text(value, max_length=120)
            }
        elif self._clean_scalar_text(ending_hook, max_length=120):
            normalized["ending_hook"] = {"content": self._clean_scalar_text(ending_hook, max_length=120)}

        if not normalized["appearing_characters"]:
            normalized["appearing_characters"] = self._extract_character_names(normalized["key_characters"])

        if not normalized["scene_goal"]:
            normalized["scene_goal"] = (
                self._clean_scalar_text(normalized.get("plot_advancement"), max_length=120)
                or (normalized["key_events"][0] if normalized["key_events"] else "")
                or self._clean_scalar_text(normalized["core_summary"], max_length=120)
            )

        if not normalized["plot_advancement"]:
            normalized["plot_advancement"] = (
                self._clean_scalar_text(normalized.get("scene_goal"), max_length=160)
                or self._clean_scalar_text(normalized["core_summary"], max_length=160)
            )

        if not normalized["ending_hook"] and normalized["hooks"]:
            normalized["ending_hook"] = {"content": normalized["hooks"][0]}

        if not normalized["foreshadowing"] and normalized["hooks"]:
            ending_content = self._clean_scalar_text(normalized["ending_hook"].get("content"), max_length=120)
            normalized["foreshadowing"] = [
                item for item in normalized["hooks"]
                if item and item != ending_content
            ]

        normalized["hooks"] = self._merge_hook_items(
            normalized.get("ending_hook", {}),
            normalized.get("foreshadowing", []),
            normalized.get("hooks", []),
        )

        for key, value in summary_payload.items():
            if key in normalized:
                continue
            if value in (None, "", [], {}):
                continue
            normalized[key] = value

        normalized["summary_length"] = len(normalized["full_summary"] or normalized["core_summary"] or "")
        return normalized

    def _parse_summary_result(self, summary_text: str) -> Dict[str, Any]:
        """解析AI生成的摘要文本，提取结构化信息"""
        parsed = {
            "core_summary": self._extract_section(summary_text, "核心事件摘要"),
            "scene_goal": self._extract_section(summary_text, "场景目标"),
            "key_characters": self._parse_list_section(self._extract_section(summary_text, "关键人物")),
            "key_events": self._parse_list_section(self._extract_section(summary_text, "核心事件")),
            "key_locations": self._parse_list_section(self._extract_section(summary_text, "重要地点")),
            "conflict_arc": self._parse_kv_section(
                self._extract_section(summary_text, "冲突弧"),
                {"触发": "trigger", "升级": "escalation", "结果": "result", "描述": "description"},
            ),
            "emotion_curve": self._extract_section(summary_text, "情绪曲线"),
            "highlight": self._parse_kv_section(
                self._extract_section(summary_text, "高光设计"),
                {"类型": "type", "描述": "description", "内容": "description"},
            ),
            "gains": self._parse_kv_section(
                self._extract_section(summary_text, "本章收获"),
                {"人物收获": "character_gains", "剧情推进": "plot_progress"},
            ),
            "plot_advancement": self._extract_section(summary_text, "情节推进"),
            "ending_hook": self._parse_kv_section(
                self._extract_section(summary_text, "结尾钩子"),
                {"类型": "type", "内容": "content", "描述": "content"},
            ),
            "foreshadowing": self._parse_list_section(self._extract_section(summary_text, "悬念/伏笔")),
        }

        parsed["appearing_characters"] = self._extract_character_names(parsed["key_characters"])
        parsed["hooks"] = self._merge_hook_items(
            parsed.get("ending_hook", {}),
            parsed.get("foreshadowing", []),
            [],
        )

        try:
            return self._normalize_summary_dict(
                parsed,
                full_summary=summary_text,
            )
        except Exception as e:
            logger.debug(f"⚠️ 解析摘要时出现错误：{e}")
            logger.debug("   将使用完整摘要作为核心摘要回退")
            return self._normalize_summary_dict(
                {
                    "core_summary": self._clean_scalar_text(summary_text, max_length=600),
                    "full_summary": summary_text,
                },
                full_summary=summary_text,
            )
    
    def save_summary_to_db(self, chapter_id: int, summary: Dict[str, Any]) -> bool:
        """保存摘要到数据库
        
        Args:
            chapter_id: 章节ID
            summary: 摘要数据
            
        Returns:
            是否保存成功
        """
        if not self.db_session:
            logger.debug("⚠️ 未配置数据库会话，无法保存摘要")
            return False
        
        try:
            import json
            from sqlalchemy import text
            
            # 使用原生SQL更新章节摘要
            update_query = text("""
                UPDATE chapters 
                SET summary = :summary, summary_data = :summary_data 
                WHERE id = :chapter_id
            """)
            
            # 将结构化数据转为统一的章节资产 schema 保存
            summary_data = self._build_summary_payload(summary)
            
            result = self.db_session.execute(update_query, {
                "summary": summary_data.get("core_summary", ""),
                "summary_data": json.dumps(summary_data, ensure_ascii=False),
                "chapter_id": chapter_id
            })
            
            if result.rowcount == 0:
                logger.debug(f"⚠️ 找不到章节 ID: {chapter_id}")
                return False
            
            self.db_session.commit()
            logger.debug(f"✅ 摘要已保存到数据库（章节 ID: {chapter_id}）")
            return True
            
        except Exception as e:
            logger.debug(f"❌ 保存摘要到数据库时出错：{e}")
            self.db_session.rollback()
            return False
    
    def load_summary_from_db(self, chapter_id: int) -> Optional[Dict[str, Any]]:
        """从数据库加载摘要
        
        Args:
            chapter_id: 章节ID
            
        Returns:
            摘要数据，如果不存在返回None
        """
        if not self.db_session:
            return None
        
        try:
            import json
            from sqlalchemy import text
            
            # 使用原生SQL查询章节摘要
            select_query = text("""
                SELECT chapter_number, title, summary, summary_data 
                FROM chapters 
                WHERE id = :chapter_id AND summary IS NOT NULL AND summary != ''
            """)
            
            result = self.db_session.execute(select_query, {"chapter_id": chapter_id}).fetchone()
            
            if not result:
                return None
            
            chapter_number, title, summary, summary_data_json = result
            
            # 构造摘要对象
            summary_dict = {
                "chapter_number": chapter_number,
                "chapter_title": title,
                "core_summary": summary,
                "full_summary": summary,  # 简化处理
                "summary_length": len(summary)
            }
            
            # 解析结构化数据
            if summary_data_json:
                try:
                    summary_data = json.loads(summary_data_json)
                    summary_dict.update(
                        self._normalize_summary_dict(
                            summary_data,
                            chapter_number=chapter_number,
                            chapter_title=title,
                            full_summary=summary,
                        )
                    )
                except Exception:
                    summary_dict.update(
                        self._normalize_summary_dict(
                            {"core_summary": summary},
                            chapter_number=chapter_number,
                            chapter_title=title,
                            full_summary=summary,
                        )
                    )
            else:
                # 如果没有结构化数据，回退到最小可用结构
                summary_dict.update(
                    self._normalize_summary_dict(
                        {"core_summary": summary},
                        chapter_number=chapter_number,
                        chapter_title=title,
                        full_summary=summary,
                    )
                )
            
            return attach_cross_media_adaptation_hints(
                summary_dict,
                chapter_title=title or "",
                chapter_summary=summary or "",
            )
            
        except Exception as e:
            logger.debug(f"⚠️ 从数据库加载摘要时出错：{e}")
            return None
    
    def get_or_generate_summary(self, chapter_id: int, chapter_number: int,
                               chapter_title: str, chapter_content: str,
                               summary_length: int = 300,
                               force_regenerate: bool = False) -> Dict[str, Any]:
        """获取或生成章节摘要（带缓存）
        
        优先从数据库加载，如果不存在则生成并保存。
        当章节正文已更新时，可通过 force_regenerate 强制跳过缓存。
        
        Args:
            chapter_id: 章节ID
            chapter_number: 章节编号
            chapter_title: 章节标题
            chapter_content: 章节内容
            summary_length: 摘要目标字数
            force_regenerate: 是否强制重新生成摘要
            
        Returns:
            摘要数据
        """
        # 1. 尝试从数据库加载
        if not force_regenerate:
            cached_summary = self.load_summary_from_db(chapter_id)
            if cached_summary:
                logger.debug(f"✅ 使用缓存的摘要（章节 ID: {chapter_id}）")
                return cached_summary
        else:
            logger.debug(f"🔄 检测到强制重生成，跳过缓存摘要（章节 ID: {chapter_id}）")
        
        # 2. 缓存不存在，生成新摘要
        logger.debug(f"🔄 缓存不存在或已失效，开始生成新摘要...")
        summary = self.generate_chapter_summary(
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            chapter_content=chapter_content,
            summary_length=summary_length
        )
        
        # 3. 保存到数据库
        self.save_summary_to_db(chapter_id, summary)
        
        return summary


def create_chapter_summarizer(knowledge_base: Optional[NovelKnowledgeBase] = None,
                             memory_manager: Optional[NovelMemoryManager] = None,
                             db_session = None,
                             model: Optional[str] = None) -> ChapterSummarizer:
    """创建章节摘要生成器的工厂函数
    
    Args:
        knowledge_base: 知识库实例
        memory_manager: 记忆管理器实例
        db_session: 数据库会话，用于缓存摘要
        model: 指定摘要生成模型（🆕 免费档锁定模型用，缺省保持默认路由）
        
    Returns:
        配置好的ChapterSummarizer实例
    """
    return ChapterSummarizer(knowledge_base, memory_manager, db_session, model=model)
