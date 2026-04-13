"""  
章节摘要生成器 - 自动生成核心事件摘要，减少AI上下文长度
"""
from typing import Dict, Any, List, Optional
import json
import logging

logger = logging.getLogger(__name__)
from .agents import CreativeDirectorAgent
from core.langchain_bridge import create_task_llm
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager


class ChapterSummarizer:
    """章节摘要生成器
    
    功能：
    1. 为每个章节生成核心事件摘要（200-300字）
    2. 提取关键信息：人物、事件、地点、转折
    3. 生成新章节时使用摘要而非全文
    4. 大幅减少AI上下文长度，支持更长的小说
    """
    
    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 db_session = None):
        """初始化摘要生成器
        
        Args:
            knowledge_base: 知识库实例
            memory_manager: 记忆管理器实例
            db_session: 数据库会话，用于缓存摘要
        """
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.db_session = db_session
        
        # 初始化AI Agent
        self.creative_director = CreativeDirectorAgent(self.knowledge_base, self.memory_manager)
        self.llm = create_task_llm()
    
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
        
        # 生成核心摘要
        summary_prompt = f"""你是一位专业的内容提炼专家。请为以下章节生成精炼的核心事件摘要。

【章节信息】
- 章节编号：第{chapter_number}章
- 章节标题：{chapter_title}

【完整章节内容】
{chapter_content}

请生成约{summary_length}字的核心事件摘要，包括：

1. **核心事件摘要**（{summary_length}字以内）
   - 本章发生了什么（主线情节）
   - 人物做了什么重要决定或行动
   - 情节如何推进

2. **关键人物**（列出3-5个本章出场的重要人物）
   - 格式：人物名 - 在本章的作用

3. **核心事件**（列出2-4个关键事件）
   - 格式：事件描述（一句话）

4. **重要地点**（列出1-3个重要场景）
   - 格式：地点名 - 发生了什么

5. **情节推进**（一句话说明本章如何推动整体故事）

6. **悬念/伏笔**（如果有，列出1-2个）
   - 格式：悬念描述

要求：
- 摘要要精炼，突出核心事件
- 忽略次要细节和环境描写
- 保留关键对话内容（如果有重要信息）
- 标注重要转折点
- 用客观叙述的方式，不要有"本章""这一章"等字眼

示例格式：
【核心事件摘要】
主角接到神秘任务，前往某交易市场调查黑客组织。在交易大厅遇到了旧识，从对方口中得知组织内部出现叛徒。主角决定潜入组织内部查明真相，但发现自己的记忆被篡改过。章节结尾，神秘人出现并警告主角不要深入调查。

【关键人物】
- 主角：接受任务并展开调查
- 旧识：提供关键情报
- 神秘人：未知身份，发出警告

【核心事件】
- 接到调查黑客组织的任务
- 在交易市场遇到旧识
- 发现自己的记忆被篡改
- 神秘人出现并警告

【重要地点】
- 交易市场：主角与旧识会面的地方
- 实验室：发现记忆篡改的地点

【情节推进】
揭示了主角记忆被篡改的真相，为后续调查埋下伏笔

【悬念/伏笔】
- 神秘人的真实身份和目的
- 谁篡改了主角的记忆

请严格按照以上格式生成摘要：
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
            "key_characters": parsed_summary.get("key_characters", []),
            "key_events": parsed_summary.get("key_events", []),
            "key_locations": parsed_summary.get("key_locations", []),
            "plot_advancement": parsed_summary.get("plot_advancement", ""),
            "hooks": parsed_summary.get("hooks", []),
            "summary_length": len(summary_result)
        }
        
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


    def _parse_summary_result(self, summary_text: str) -> Dict[str, Any]:
        """解析AI生成的摘要文本，提取结构化信息
        
        Args:
            summary_text: AI生成的完整摘要文本
            
        Returns:
            结构化的摘要字典
        """
        parsed = {
            "core_summary": "",
            "key_characters": [],
            "key_events": [],
            "key_locations": [],
            "plot_advancement": "",
            "hooks": []
        }
        
        try:
            # 提取核心事件摘要
            if "【核心事件摘要】" in summary_text:
                parts = summary_text.split("【核心事件摘要】")
                if len(parts) > 1:
                    content = parts[1].split("【")[0].strip()
                    parsed["core_summary"] = content
            
            # 提取关键人物
            if "【关键人物】" in summary_text:
                parts = summary_text.split("【关键人物】")
                if len(parts) > 1:
                    content = parts[1].split("【")[0].strip()
                    # 按行分割，过滤空行和标题行
                    lines = [line.strip() for line in content.split("\n") if line.strip() and line.strip().startswith("-")]
                    parsed["key_characters"] = [line.lstrip("- ").strip() for line in lines]
            
            # 提取核心事件
            if "【核心事件】" in summary_text:
                parts = summary_text.split("【核心事件】")
                if len(parts) > 1:
                    content = parts[1].split("【")[0].strip()
                    lines = [line.strip() for line in content.split("\n") if line.strip() and line.strip().startswith("-")]
                    parsed["key_events"] = [line.lstrip("- ").strip() for line in lines]
            
            # 提取重要地点
            if "【重要地点】" in summary_text:
                parts = summary_text.split("【重要地点】")
                if len(parts) > 1:
                    content = parts[1].split("【")[0].strip()
                    lines = [line.strip() for line in content.split("\n") if line.strip() and line.strip().startswith("-")]
                    parsed["key_locations"] = [line.lstrip("- ").strip() for line in lines]
            
            # 提取情节推进
            if "【情节推进】" in summary_text:
                parts = summary_text.split("【情节推进】")
                if len(parts) > 1:
                    content = parts[1].split("【")[0].strip()
                    parsed["plot_advancement"] = content
            
            # 提取悬念/伏笔
            if "【悬念/伏笔】" in summary_text:
                parts = summary_text.split("【悬念/伏笔】")
                if len(parts) > 1:
                    content = parts[1].strip()
                    lines = [line.strip() for line in content.split("\n") if line.strip() and line.strip().startswith("-")]
                    parsed["hooks"] = [line.lstrip("- ").strip() for line in lines]
        
        except Exception as e:
            logger.debug(f"⚠️ 解析摘要时出现错误：{e}")
            logger.debug(f"   将使用完整摘要作为核心摘要")
            parsed["core_summary"] = summary_text
        
        return parsed
    
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
            
            # 将结构化数据转为JSON保存
            summary_data = {
                "key_characters": summary.get("key_characters", []),
                "key_events": summary.get("key_events", []),
                "key_locations": summary.get("key_locations", []),
                "plot_advancement": summary.get("plot_advancement", ""),
                "hooks": summary.get("hooks", [])
            }
            
            result = self.db_session.execute(update_query, {
                "summary": summary.get("core_summary", ""),
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
                    summary_dict.update(summary_data)
                except Exception:
                    pass
            else:
                # 如果没有结构化数据，使用默认值
                summary_dict.update({
                    "key_characters": [],
                    "key_events": [],
                    "key_locations": [],
                    "plot_advancement": "",
                    "hooks": []
                })
            
            return summary_dict
            
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
                             db_session = None) -> ChapterSummarizer:
    """创建章节摘要生成器的工厂函数
    
    Args:
        knowledge_base: 知识库实例
        memory_manager: 记忆管理器实例
        db_session: 数据库会话，用于缓存摘要
        
    Returns:
        配置好的ChapterSummarizer实例
    """
    return ChapterSummarizer(knowledge_base, memory_manager, db_session)

