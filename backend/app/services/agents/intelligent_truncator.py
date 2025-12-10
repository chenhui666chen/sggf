"""
AI辅助智能截断器 - 混合规则+AI语义理解

功能：
1. 规则快速筛选(保留⭐️高优先级内容)
2. AI语义摘要(压缩超出部分)
3. 确保关键信息不丢失
"""
from typing import Dict, Any
import re
from langchain_core.messages import SystemMessage, HumanMessage
from .llm_singleton import create_deepseek_llm


class IntelligentTruncator:
    """AI辅助智能截断器"""
    
    def __init__(self):
        # 使用qwen-turbo做快速摘要（成本低、速度快、100万tokens上下文）
        self.summarizer_llm = create_deepseek_llm(task_type="summarize")
    
    def intelligent_truncate(
        self, 
        content: str, 
        target_length: int,
        content_type: str = "outline"  # outline/character/worldview
    ) -> dict:
        """
        混合策略截断:
        1. 规则快速筛选(保留70%)
        2. AI语义摘要(压缩30%)
        
        Args:
            content: 原始内容
            target_length: 目标长度(字符)
            content_type: 内容类型(outline/character/worldview)
            
        Returns:
            {
                "content": 处理后的内容,
                "method": 使用的方法,
                "original_length": 原始长度,
                "final_length": 最终长度,
                "compression_ratio": 压缩比
            }
        """
        
        if not content or len(content) <= target_length:
            return {
                "content": content,
                "method": "no_truncate",
                "original_length": len(content),
                "final_length": len(content),
                "compression_ratio": 1.0
            }
        
        print(f"\n{'='*70}")
        print(f"【智能截断器】开始处理 {content_type}")
        print(f"   原始长度: {len(content):,}字符")
        print(f"   目标长度: {target_length:,}字符")
        print(f"   需压缩: {(1 - target_length/len(content))*100:.1f}%")
        print(f"{'='*70}\n")
        
        # 第一步: 规则筛选高优先级内容
        high_priority = self._extract_by_rules(content)
        
        current_length = len(high_priority)
        print(f"📋 规则筛选后: {current_length:,}字符 (保留{current_length/len(content)*100:.1f}%)")
        
        # 第二步: 评估是否需要AI摘要
        if current_length <= target_length:
            # 规则筛选已满足，无需AI
            print(f"✅ 规则筛选已满足目标，无需AI摘要\n")
            return {
                "content": high_priority,
                "method": "rule_based",
                "original_length": len(content),
                "final_length": current_length,
                "compression_ratio": current_length / len(content)
            }
        
        # 第三步: AI语义摘要（仅处理超出部分）
        print(f"🤖 启动AI摘要: 处理超出的 {current_length - target_length:,}字符...")
        
        # 计算保留多少规则筛选的内容
        keep_length = int(target_length * 0.7)  # 保留70%给规则筛选结果
        summarize_budget = target_length - keep_length  # 30%给AI摘要
        
        kept_part = high_priority[:keep_length]
        overflow_part = high_priority[keep_length:]
        
        try:
            summary = self._ai_summarize(
                overflow_part, 
                content_type,
                target_length=summarize_budget
            )
            
            result = kept_part + "\n\n" + summary
            
            print(f"✅ AI摘要完成: {len(overflow_part):,}字 → {len(summary):,}字")
            print(f"📊 最终结果: {len(result):,}字符 (压缩{(1-len(result)/len(content))*100:.1f}%)\n")
            
            return {
                "content": result,
                "method": "hybrid",
                "original_length": len(content),
                "final_length": len(result),
                "compression_ratio": len(result) / len(content)
            }
            
        except Exception as e:
            print(f"⚠️  AI摘要失败，回退到规则截断: {e}\n")
            fallback = high_priority[:target_length] + "\n\n⚠️ [已截断]"
            return {
                "content": fallback,
                "method": "fallback",
                "original_length": len(content),
                "final_length": len(fallback),
                "compression_ratio": len(fallback) / len(content)
            }
    
    def _extract_by_rules(self, content: str) -> str:
        """规则快速筛选 - 保留⭐️标记内容
        
        Args:
            content: 原始内容
            
        Returns:
            筛选后的内容
        """
        paragraphs = content.split('\n\n')
        
        # 优先级分组
        priority_groups = {5: [], 4: [], 3: [], 2: [], 1: [], 0: []}
        
        for para in paragraphs:
            if not para.strip():
                continue
            
            stars = para.count('⭐')
            priority_groups[min(stars, 5)].append(para)
        
        # 优先保留高星级
        result = []
        for stars in [5, 4, 3, 2, 1, 0]:
            if priority_groups[stars]:
                result.extend(priority_groups[stars])
        
        return '\n\n'.join(result)
    
    def _ai_summarize(
        self, 
        content: str, 
        content_type: str,
        target_length: int
    ) -> str:
        """AI语义摘要 - 提取关键情节点
        
        Args:
            content: 待摘要的内容
            content_type: 内容类型
            target_length: 目标长度(字符)
            
        Returns:
            摘要后的文本
        """
        
        # 针对不同内容类型的专用Prompt
        prompts = {
            "outline": f"""
你是一位专业的故事分析师。请从以下大纲中提取**最关键的情节要素**，压缩到约{target_length}字。

【原始大纲】
{content}

【提取要求】
1. **保留核心转折点**: 主角突破、反派登场、身份揭秘等
2. **保留关键冲突**: 主线冲突的升级节点
3. **保留高潮章节**: 标注⭐⭐⭐⭐⭐的章节
4. **删除日常铺垫**: 过渡章节、细节描写可省略

【输出格式】
- 第X章: [简要概括关键事件]
- 第Y章: [转折点描述]
...

只输出摘要，不要解释。控制在{target_length}字符以内。
""",
            "character": f"""
请从以下人物设定中提取**核心人物关系和特质**，压缩到约{target_length}字。

【原始人物】
{content}

【提取要求】
1. 保留主要人物姓名、阵营、核心能力
2. 保留关键人物关系（仇恨、师徒、情感）
3. 删除详细背景故事、外貌描写

【输出格式】
- 人物名: [阵营] [核心特质] [关键关系]

只输出摘要。控制在{target_length}字符以内。
""",
            "worldview": f"""
请从以下世界观设定中提取**核心体系规则**，压缩到约{target_length}字。

【原始世界观】
{content}

【提取要求】
1. 保留力量体系划分（境界、等级）
2. 保留核心规则（修炼方式、资源稀缺性）
3. 删除详细历史背景、地理描写

只输出摘要。控制在{target_length}字符以内。
"""
        }
        
        prompt = prompts.get(content_type, prompts["outline"])
        
        # 调用qwen-turbo快速摘要
        response = self.summarizer_llm.invoke([
            SystemMessage(content="你是专业的内容提取专家，擅长从长文本中提取关键信息。"),
            HumanMessage(content=prompt)
        ])
        
        summary = response.content.strip()
        
        # 如果摘要超出预算，强制截断
        if len(summary) > target_length * 1.2:  # 允许20%溢出
            summary = summary[:target_length] + "..."
        
        return summary


def truncate_with_ai_assist(
    content: str,
    target_length: int,
    content_type: str = "outline"
) -> str:
    """
    便捷函数：AI辅助截断
    
    Args:
        content: 原始内容
        target_length: 目标长度(字符)
        content_type: 内容类型
        
    Returns:
        截断后的内容
    """
    truncator = IntelligentTruncator()
    result = truncator.intelligent_truncate(content, target_length, content_type)
    return result["content"]
