"""
章节生成上下文优化器 - 智能管理情节大纲、世界观、人物设定等长文本

功能：
1. 动态评估各部分内容的token消耗
2. 基于重要性⭐️分级进行智能截断
3. 对超长内容使用摘要策略
4. 确保总输入不超过qwen-max的30720 tokens限制
"""
from typing import Dict, Any, Optional, Tuple
import re


class ContextOptimizer:
    """章节生成上下文优化器"""
    
    # Token估算：中文约1.5字符/token，英文约4字符/token
    CN_CHARS_PER_TOKEN = 1.5
    EN_CHARS_PER_TOKEN = 4.0
    
    # 各模型的Token限制
    MODEL_LIMITS = {
        'qwen-max': 30720,
        'qwen-long': 10000000,  # 1000万tokens
        'deepseek-r1': 128000,  # 约12.8万tokens
    }
    
    # 🆕 智能模型选择策略（根据章节数）
    MODEL_SELECTION_STRATEGY = {
        'chapter_planning': {  # 章节规划阶段
            'default': 'qwen-max',  # 默认使用max（推理质量高）
            'thresholds': [
                (0, 50, 'qwen-max', 0.85),      # 0-50章: qwen-max, 85%使用率
                (50, 999, 'qwen-long', 0.30),   # 50+章: qwen-long, 30%使用率（较宽松）
            ]
        },
        'content_creation': {  # 内容创作阶段
            'default': 'qwen-max',
            'thresholds': [
                (0, 20, 'qwen-max', 0.85),      # 0-20章: qwen-max, 85%使用率
                (20, 50, 'qwen-long', 0.40),    # 20-50章: qwen-long, 40%使用率
                (50, 999, 'qwen-long', 0.20),   # 50+章: qwen-long, 20%使用率（很宽松）
            ]
        }
    }
    
    def __init__(self, target_token_ratio: float = 0.85, current_chapter: int = 1, stage: str = 'content_creation'):
        """初始化优化器
        
        Args:
            target_token_ratio: 目标token使用率（默认0.85，疕15%安全余量）
            current_chapter: 当前章节数（用于智能模型选择）
            stage: 当前阶段 ('chapter_planning' 或 'content_creation')
        """
        self.current_chapter = current_chapter
        self.stage = stage
        
        # 🆕 智能选择模型和目标比例
        self.selected_model, self.target_token_ratio = self._select_model_and_ratio()
        self.max_tokens = self.MODEL_LIMITS[self.selected_model]
        self.target_tokens = int(self.max_tokens * self.target_token_ratio)
        
        print(f"📊 上下文优化器初始化:")
        print(f"   - 当前章节: 第{self.current_chapter}章")
        print(f"   - 阶段: {stage}")
        print(f"   - 选择模型: {self.selected_model}")
        print(f"   - 最大tokens: {self.max_tokens:,}")
        print(f"   - 目标tokens: {self.target_tokens:,} ({self.target_token_ratio*100:.0f}%使用率)")
    
    def _select_model_and_ratio(self) -> tuple:
        """根据章节数和阶段智能选择模型和目标比例
        
        Returns:
            (model_name, target_ratio)
        """
        strategy = self.MODEL_SELECTION_STRATEGY.get(self.stage, self.MODEL_SELECTION_STRATEGY['content_creation'])
        
        # 查找匹配的阈值
        for min_chapter, max_chapter, model, ratio in strategy['thresholds']:
            if min_chapter <= self.current_chapter < max_chapter:
                return model, ratio
        
        # 默认返回
        return strategy['default'], 0.85
    
    def _get_content_priorities(self) -> dict:
        """根据选择的模型动态调整内容优先级和token预算
        
        Returns:
            CONTENT_PRIORITIES 字典
        """
        # 基础配置（qwen-max）
        base_config = {
            'previous_chapters_analysis': {'priority': 1, 'max_tokens': 8000},
            'chapter_plan': {'priority': 2, 'max_tokens': 3000},
            'characters': {'priority': 3, 'max_tokens': 4000},
            'world_setting': {'priority': 4, 'max_tokens': 4000},
            'plot_outline': {'priority': 5, 'max_tokens': 6000},
            'project_concept': {'priority': 6, 'max_tokens': 1000},
            'previous_ending': {'priority': 7, 'max_tokens': 500},
            'system_prompt': {'priority': 8, 'max_tokens': 1000},
            'instructions': {'priority': 9, 'max_tokens': 1000},
        }
        
        # 如果使用qwen-long，放宽限制
        if self.selected_model == 'qwen-long':
            # 根据章节数动态调整
            if self.current_chapter < 50:
                # 20-50章：适度放宽
                return {
                    'previous_chapters_analysis': {'priority': 1, 'max_tokens': 15000},  # 约2倍
                    'chapter_plan': {'priority': 2, 'max_tokens': 5000},
                    'characters': {'priority': 3, 'max_tokens': 8000},
                    'world_setting': {'priority': 4, 'max_tokens': 8000},
                    'plot_outline': {'priority': 5, 'max_tokens': 12000},  # 约2倍
                    'project_concept': {'priority': 6, 'max_tokens': 2000},
                    'previous_ending': {'priority': 7, 'max_tokens': 1000},
                    'system_prompt': {'priority': 8, 'max_tokens': 2000},
                    'instructions': {'priority': 9, 'max_tokens': 2000},
                }
            else:
                # 50+章：大幅放宽
                return {
                    'previous_chapters_analysis': {'priority': 1, 'max_tokens': 30000},  # 约4倍
                    'chapter_plan': {'priority': 2, 'max_tokens': 8000},
                    'characters': {'priority': 3, 'max_tokens': 15000},
                    'world_setting': {'priority': 4, 'max_tokens': 15000},
                    'plot_outline': {'priority': 5, 'max_tokens': 25000},  # 约4倍
                    'project_concept': {'priority': 6, 'max_tokens': 3000},
                    'previous_ending': {'priority': 7, 'max_tokens': 1500},
                    'system_prompt': {'priority': 8, 'max_tokens': 3000},
                    'instructions': {'priority': 9, 'max_tokens': 3000},
                }
        
        return base_config
    
    def estimate_tokens(self, text: str) -> int:
        """估算文本的token数量
        
        Args:
            text: 输入文本
            
        Returns:
            估算的token数量
        """
        if not text:
            return 0
        
        # 统计中英文字符
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text)
        en_chars = total_chars - cn_chars
        
        # 分别计算token数
        cn_tokens = cn_chars / self.CN_CHARS_PER_TOKEN
        en_tokens = en_chars / self.EN_CHARS_PER_TOKEN
        
        return int(cn_tokens + en_tokens)
    
    def extract_importance_stars(self, text: str) -> int:
        """提取文本的重要性星级（基于⭐️数量）
        
        Args:
            text: 输入文本
            
        Returns:
            星级数量(0-5)
        """
        if not text:
            return 0
        
        # 匹配⭐️或★符号
        stars = len(re.findall(r'[⭐️★]', text))
        return min(stars, 5)
    
    def split_by_importance(self, text: str) -> Dict[int, str]:
        """按重要性星级分割文本
        
        Args:
            text: 输入文本
            
        Returns:
            {星级: 对应文本片段} 的字典
        """
        if not text:
            return {}
        
        # 按段落分割
        paragraphs = text.split('\n\n')
        
        importance_groups = {5: [], 4: [], 3: [], 2: [], 1: [], 0: []}
        
        for para in paragraphs:
            if not para.strip():
                continue
            
            stars = self.extract_importance_stars(para)
            importance_groups[stars].append(para)
        
        # 合并各星级的内容
        result = {}
        for stars, paras in importance_groups.items():
            if paras:
                result[stars] = '\n\n'.join(paras)
        
        return result
    
    def summarize_text(self, text: str, target_length: int = 500) -> str:
        """智能摘要文本（保留关键信息）
        
        Args:
            text: 原文本
            target_length: 目标长度（字符）
            
        Returns:
            摘要后的文本
        """
        if len(text) <= target_length:
            return text
        
        # 策略1：提取带⭐️的关键内容
        importance_groups = self.split_by_importance(text)
        
        summary_parts = []
        current_length = 0
        
        # 优先保留高星级内容
        for stars in sorted(importance_groups.keys(), reverse=True):
            if stars not in importance_groups:
                continue
            
            content = importance_groups[stars]
            if current_length + len(content) <= target_length:
                summary_parts.append(content)
                current_length += len(content)
            else:
                # 截断并添加
                remaining = target_length - current_length
                if remaining > 100:  # 至少保留100字
                    summary_parts.append(content[:remaining] + "...")
                break
        
        if summary_parts:
            return '\n\n'.join(summary_parts)
        
        # 策略2：如果没有星级标记，按段落保留前部分
        paragraphs = text.split('\n\n')
        summary_parts = []
        current_length = 0
        
        for para in paragraphs:
            if current_length + len(para) <= target_length:
                summary_parts.append(para)
                current_length += len(para)
            else:
                remaining = target_length - current_length
                if remaining > 100:
                    summary_parts.append(para[:remaining] + "...")
                break
        
        return '\n\n'.join(summary_parts) if summary_parts else text[:target_length] + "..."
    
    def optimize_context(self, context_parts: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """优化整体上下文，确保不超过token限制
        
        Args:
            context_parts: {部分名称: 内容} 字典
            
        Returns:
            (优化后的上下文字典, 统计信息)
        """
        print(f"\n{'='*70}")
        print(f"【上下文优化器】开始优化上下文...")
        print(f"{'='*70}\n")
        
        # 1. 估算各部分的token消耗
        token_usage = {}
        total_tokens = 0
        
        for key, content in context_parts.items():
            tokens = self.estimate_tokens(content)
            token_usage[key] = tokens
            total_tokens += tokens
            print(f"📊 {key}: {tokens} tokens ({len(content)} 字符)")
        
        print(f"\n💾 当前总token数: {total_tokens} / {self.target_tokens} (目标)")
        
        # 2. 如果未超标，直接返回
        if total_tokens <= self.target_tokens:
            print(f"✅ Token使用在安全范围内，无需优化\n")
            return context_parts, {
                'original_tokens': total_tokens,
                'optimized_tokens': total_tokens,
                'savings': 0,
                'savings_percentage': 0,
                'details': token_usage
            }
        
        # 3. 需要优化：按优先级压缩
        print(f"\n⚠️  Token超标 ({total_tokens - self.target_tokens} tokens)，开始智能压缩...\n")
        
        optimized_parts = {}
        optimized_tokens = 0
        compression_log = []
        
        # 按优先级排序
        CONTENT_PRIORITIES = self._get_content_priorities()  # 🆕 动态获取优先级配置
        priorities = {}
        for key in context_parts.keys():
            if key in CONTENT_PRIORITIES:
                priorities[key] = CONTENT_PRIORITIES[key]['priority']
            else:
                priorities[key] = 99  # 未知部分放最后
        
        sorted_keys = sorted(priorities.keys(), key=lambda k: priorities[k])
        
        # 计算需要节省的token
        tokens_to_save = total_tokens - self.target_tokens
        
        # 对低优先级内容进行压缩
        for key in sorted_keys:
            content = context_parts[key]
            original_tokens = token_usage[key]
            
            if key in CONTENT_PRIORITIES:
                max_tokens = CONTENT_PRIORITIES[key]['max_tokens']
            else:
                max_tokens = 1000  # 默认限制
            
            if original_tokens > max_tokens:
                # 需要压缩
                target_chars = int(max_tokens * self.CN_CHARS_PER_TOKEN)
                compressed_content = self.summarize_text(content, target_chars)
                compressed_tokens = self.estimate_tokens(compressed_content)
                
                optimized_parts[key] = compressed_content
                optimized_tokens += compressed_tokens
                
                saved = original_tokens - compressed_tokens
                compression_log.append(f"🔧 {key}: {original_tokens} → {compressed_tokens} tokens (节省{saved})")
                
            else:
                # 无需压缩
                optimized_parts[key] = content
                optimized_tokens += original_tokens
        
        # 打印优化日志
        print("压缩详情:")
        for log in compression_log:
            print(f"   {log}")
        
        print(f"\n💾 优化后总token数: {optimized_tokens} / {self.target_tokens} (目标)")
        savings = total_tokens - optimized_tokens
        savings_pct = (savings / total_tokens * 100) if total_tokens > 0 else 0
        print(f"📉 节省: {savings} tokens ({savings_pct:.1f}%)\n")
        
        # 4. 如果还是超标，进一步压缩大纲
        if optimized_tokens > self.target_tokens:
            print(f"⚠️  仍然超标，对情节大纲进行进一步压缩...")
            
            if 'plot_outline' in optimized_parts:
                outline = optimized_parts['plot_outline']
                outline_tokens = self.estimate_tokens(outline)
                needed_reduction = optimized_tokens - self.target_tokens
                
                new_outline_tokens = max(2000, outline_tokens - needed_reduction)
                new_outline_chars = int(new_outline_tokens * self.CN_CHARS_PER_TOKEN)
                
                optimized_parts['plot_outline'] = self.summarize_text(outline, new_outline_chars)
                new_tokens = self.estimate_tokens(optimized_parts['plot_outline'])
                
                optimized_tokens = optimized_tokens - outline_tokens + new_tokens
                print(f"   🔧 plot_outline: {outline_tokens} → {new_tokens} tokens")
                print(f"   💾 最终token数: {optimized_tokens}")
        
        print(f"{'='*70}\n")
        
        return optimized_parts, {
            'original_tokens': total_tokens,
            'optimized_tokens': optimized_tokens,
            'savings': total_tokens - optimized_tokens,
            'savings_percentage': ((total_tokens - optimized_tokens) / total_tokens * 100) if total_tokens > 0 else 0,
            'details': token_usage,
            'compression_log': compression_log
        }
    
    def optimize_for_chapter_generation(
        self,
        plot_outline: str,
        world_setting: str,
        characters: str,
        previous_chapters_analysis: str,
        chapter_plan: str = "",
        project_concept: str = "",
        previous_ending: str = "",
        instructions: str = ""
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """为章节生成优化上下文（便捷方法）
        
        Args:
            plot_outline: 情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            previous_chapters_analysis: 前序章节分析
            chapter_plan: 章节规划
            project_concept: 项目概念
            previous_ending: 前一章结尾
            instructions: 创作指令
            
        Returns:
            (优化后的上下文字典, 统计信息)
        """
        context_parts = {}
        
        if plot_outline:
            context_parts['plot_outline'] = plot_outline
        if world_setting:
            context_parts['world_setting'] = world_setting
        if characters:
            context_parts['characters'] = characters
        if previous_chapters_analysis:
            context_parts['previous_chapters_analysis'] = previous_chapters_analysis
        if chapter_plan:
            context_parts['chapter_plan'] = chapter_plan
        if project_concept:
            context_parts['project_concept'] = project_concept
        if previous_ending:
            context_parts['previous_ending'] = previous_ending
        if instructions:
            context_parts['instructions'] = instructions
        
        return self.optimize_context(context_parts)


# 全局单例
_context_optimizer = None

def get_context_optimizer(current_chapter: int = 1, stage: str = 'content_creation') -> ContextOptimizer:
    """获取全局上下文优化器实例
    
    Args:
        current_chapter: 当前章节数
        stage: 当前阶段
    
    Returns:
        ContextOptimizer 实例
    """
    # 每次都创建新实例，因为需要传入章节数
    return ContextOptimizer(current_chapter=current_chapter, stage=stage)
