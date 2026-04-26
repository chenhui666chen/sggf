"""
章节生成上下文优化器 - 智能管理情节大纲、世界观、人物设定等长文本

功能：
1. 动态评估各部分内容的token消耗
2. 基于重要性⭐️分级进行智能截断
3. 对超长内容使用摘要策略
4. 确保总输入不超过 qwen3-max 的 256K tokens 限制
"""
from typing import Dict, Any, Optional, Tuple
import logging
import re


logger = logging.getLogger(__name__)


class ContextOptimizer:
    """章节生成上下文优化器"""
    
    # Token估算：中文约1.5字符/token，英文约4字符/token
    CN_CHARS_PER_TOKEN = 1.5
    EN_CHARS_PER_TOKEN = 4.0
    
    # 各模型的Token限制
    MODEL_LIMITS = {
        'qwen-max': 30720,
        'qwen3-max': 256000,    # 256K tokens（上下文 256K）
        'qwen-plus': 1000000,   # 100万tokens
        'qwen-turbo': 1000000,  # 100万tokens (Qwen2.5-Turbo)
        'qwen-long': 10000000,  # 1000万tokens
        'deepseek-v4-pro': 1000000,  # 100万tokens
    }
    
    # 🆕 智能模型选择策略（根据章节数）
    MODEL_SELECTION_STRATEGY = {
        'chapter_planning': {  # 章节规划阶段
            'default': 'qwen3-max',  # 默认使用 qwen3-max（质量优先）
            'thresholds': [
                (0, 50, 'qwen3-max', 0.85),     # 0-50章: qwen3-max, 85%使用率
                (50, 999, 'qwen-long', 0.30),   # 50+章: qwen-long, 30%使用率（较宽松）
            ]
        },
        'content_creation': {  # 内容创作阶段
            'default': 'qwen3-max',
            'thresholds': [
                (0, 20, 'qwen3-max', 0.85),     # 0-20章: qwen3-max, 85%使用率
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
        
        logger.debug(f"📊 上下文优化器初始化:")
        logger.debug(f"   - 当前章节: 第{self.current_chapter}章")
        logger.debug(f"   - 阶段: {stage}")
        logger.debug(f"   - 选择模型: {self.selected_model}")
        logger.debug(f"   - 最大tokens: {self.max_tokens:,}")
        logger.debug(f"   - 目标tokens: {self.target_tokens:,} ({self.target_token_ratio*100:.0f}%使用率)")
    
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
        # 基础配置（qwen3-max）
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
    
    def extract_relevant_outline(
        self,
        full_outline: str,
        target_chapter: int,
        context_range: int = 2
    ) -> str:
        """智能提取当前章节相关的大纲内容
        
        从完整大纲中提取：
        1. 故事概述（必保留）
        2. 当前卷概述（如果有卷结构）
        3. 当前章节 + 前后N章的详细细纲
        4. 涉及当前章节的伏笔信息
        5. 本卷活跃的人物生命周期
        
        Args:
            full_outline: 完整大纲
            target_chapter: 目标章节号
            context_range: 上下文范围（前后各几章）
            
        Returns:
            提取后的精准大纲内容
        """
        if not full_outline or not full_outline.strip():
            return full_outline
        
        original_length = len(full_outline)
        logger.debug(f"\n🎯 【智能大纲提取】目标章节: 第{target_chapter}章, 原始长度: {original_length}字符")
        
        result_parts = []
        
        # 1️⃣ 提取故事概述（必保留）
        story_overview = self._extract_story_overview(full_outline)
        if story_overview:
            result_parts.append(story_overview)
            logger.debug(f"   ✅ 提取故事概述: {len(story_overview)}字符")
        
        # 2️⃣ 提取当前卷概述（如果有卷结构）
        volume_info = self._extract_current_volume_info(full_outline, target_chapter)
        if volume_info:
            result_parts.append(volume_info)
            logger.debug(f"   ✅ 提取当前卷信息: {len(volume_info)}字符")
        
        # 3️⃣ 提取当前章节 + 前后N章的细纲（核心）
        chapters_outline = self._extract_chapters_range(
            full_outline, 
            target_chapter, 
            context_range
        )
        if chapters_outline:
            result_parts.append(chapters_outline)
            logger.debug(f"   ✅ 提取章节细纲(第{max(1, target_chapter-context_range)}-{target_chapter+context_range}章): {len(chapters_outline)}字符")
        
        # 4️⃣ 提取涉及当前章节的伏笔信息
        foreshadowing = self._extract_relevant_foreshadowing(full_outline, target_chapter)
        if foreshadowing:
            result_parts.append(foreshadowing)
            logger.debug(f"   ✅ 提取相关伏笔: {len(foreshadowing)}字符")
        
        # 5️⃣ 提取本卷活跃的人物生命周期
        character_lifecycle = self._extract_active_characters(full_outline, target_chapter)
        if character_lifecycle:
            result_parts.append(character_lifecycle)
            logger.debug(f"   ✅ 提取人物生命周期: {len(character_lifecycle)}字符")
        
        # 合并结果
        if result_parts:
            extracted = "\n\n".join(result_parts)
            extracted_length = len(extracted)
            savings = original_length - extracted_length
            savings_pct = (savings / original_length * 100) if original_length > 0 else 0
            logger.debug(f"   💾 提取后长度: {extracted_length}字符, 节省: {savings}字符 ({savings_pct:.1f}%)")
            return extracted
        
        # 如果无法提取，返回原始大纲（稍后会被压缩）
        logger.debug(f"   ⚠️  无法识别大纲结构，返回原始内容")
        return full_outline
    
    def _extract_story_overview(self, outline: str) -> str:
        """提取故事概述部分"""
        patterns = [
            r'(##\s*一、故事概述.*?)(?=##\s*[二2]|---|【第|$)',
            r'(##\s*故事概述.*?)(?=##|---|【第|$)',
            r'(#\s*概述.*?)(?=##|#|---|【|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, outline, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _extract_current_volume_info(self, outline: str, target_chapter: int) -> str:
        """提取当前章节所属卷的概述信息"""
        estimated_volume = (target_chapter - 1) // 25 + 1
        
        patterns = [
            rf'(【第{estimated_volume}卷】.*?)(?=【第{estimated_volume + 1}卷】|####\s*第\d+章|##\s*[三四五六]|---\s*##|$)',
            rf'(###\s*【第{estimated_volume}卷】.*?)(?=###\s*【第|####\s*第\d+章|##\s*[三四五六]|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, outline, re.DOTALL)
            if match:
                volume_content = match.group(1).strip()
                chapter_start = re.search(r'####?\s*第\d+章', volume_content)
                if chapter_start:
                    return volume_content[:chapter_start.start()].strip()
                return volume_content[:1500]
        
        return ""
    
    def _extract_chapters_range(self, outline: str, target_chapter: int, context_range: int) -> str:
        """提取目标章节及前后N章的细纲"""
        start_chapter = max(1, target_chapter - context_range)
        end_chapter = target_chapter + context_range
        
        extracted_chapters = []
        
        for ch_num in range(start_chapter, end_chapter + 1):
            chapter_content = self._extract_single_chapter(outline, ch_num)
            if chapter_content:
                if ch_num == target_chapter:
                    extracted_chapters.append(f"🎯【当前创作章节】\n{chapter_content}")
                else:
                    extracted_chapters.append(chapter_content)
        
        if extracted_chapters:
            return "## 章节细纲\n\n" + "\n\n".join(extracted_chapters)
        
        return ""
    
    def _extract_single_chapter(self, outline: str, chapter_num: int) -> str:
        """提取单个章节的细纲"""
        patterns = [
            rf'(####\s*第{chapter_num}章[：:][^\n]*.*?)(?=####\s*第{chapter_num + 1}章|####\s*第\d+章|###\s*【|##\s*[三四五六]|---\s*##|$)',
            rf'(第{chapter_num}章[：:][^\n]*.*?)(?=第{chapter_num + 1}章[：:]|第\d+章[：:]|###\s*【|##\s*[三四五六]|---\s*##|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, outline, re.DOTALL)
            if match:
                content = match.group(1).strip()
                if len(content) > 800:
                    content = content[:800] + "..."
                return content
        
        return ""
    
    def _extract_relevant_foreshadowing(self, outline: str, target_chapter: int) -> str:
        """提取与当前章节相关的伏笔信息"""
        estimated_volume = (target_chapter - 1) // 25 + 1
        
        foreshadowing_patterns = [
            r'(##\s*[四4][.、]?\s*关键伏笔布局.*?)(?=##\s*[五六5-9]|---\s*##|$)',
            r'(##\s*伏笔.*?布局.*?)(?=##|---\s*##|$)',
            r'(伏笔埋设检查.*?)(?=##|$)',
        ]
        
        for pattern in foreshadowing_patterns:
            match = re.search(pattern, outline, re.DOTALL | re.IGNORECASE)
            if match:
                full_foreshadowing = match.group(1).strip()
                
                relevant_lines = []
                lines = full_foreshadowing.split('\n')
                
                for line in lines:
                    if line.strip().startswith('#') or line.strip().startswith('|'):
                        if '伏笔' in line or '---' in line or '埋设' in line or '揭秘' in line:
                            relevant_lines.append(line)
                    
                    volume_match = re.search(rf'第?({estimated_volume}|第{estimated_volume}卷)', line)
                    chapter_match = re.search(rf'第({target_chapter-5}|{target_chapter-4}|{target_chapter-3}|{target_chapter-2}|{target_chapter-1}|{target_chapter}|{target_chapter+1}|{target_chapter+2}|{target_chapter+3})章', line)
                    
                    if volume_match or chapter_match:
                        relevant_lines.append(line)
                
                if relevant_lines:
                    return "## 相关伏笔（本章附近）\n" + '\n'.join(relevant_lines)
        
        return ""
    
    def _extract_active_characters(self, outline: str, target_chapter: int) -> str:
        """提取本卷活跃的人物生命周期信息"""
        estimated_volume = (target_chapter - 1) // 25 + 1
        
        lifecycle_patterns = [
            r'(##\s*[五六5-6][.、]?\s*核心人物生命周期.*?)(?=##|---\s*##|$)',
            r'(##\s*人物.*?周期.*?)(?=##|---\s*##|$)',
            r'(人物出场统计.*?)(?=##|$)',
        ]
        
        for pattern in lifecycle_patterns:
            match = re.search(pattern, outline, re.DOTALL | re.IGNORECASE)
            if match:
                full_lifecycle = match.group(1).strip()
                
                relevant_lines = []
                lines = full_lifecycle.split('\n')
                
                for line in lines:
                    if line.strip().startswith('#') or '---' in line or '角色' in line or '登场' in line:
                        relevant_lines.append(line)
                        continue
                    
                    range_match = re.search(r'(\d+)[-~]+(\d+)卷', line)
                    if range_match:
                        start_vol = int(range_match.group(1))
                        end_vol = int(range_match.group(2))
                        if start_vol <= estimated_volume <= end_vol:
                            relevant_lines.append(line)
                            continue
                    
                    if f'第{estimated_volume}卷' in line or f'{estimated_volume}卷' in line:
                        relevant_lines.append(line)
                
                if relevant_lines:
                    return "## 本卷活跃人物\n" + '\n'.join(relevant_lines)
        
        return ""
    
    def optimize_context(self, context_parts: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """优化整体上下文，确保不超过token限制
        
        Args:
            context_parts: {部分名称: 内容} 字典
            
        Returns:
            (优化后的上下文字典, 统计信息)
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【上下文优化器】开始优化上下文...")
        logger.debug(f"{'='*70}\n")
        
        # 1. 估算各部分的token消耗
        token_usage = {}
        total_tokens = 0
        
        for key, content in context_parts.items():
            tokens = self.estimate_tokens(content)
            token_usage[key] = tokens
            total_tokens += tokens
            logger.debug(f"📊 {key}: {tokens} tokens ({len(content)} 字符)")
        
        logger.debug(f"\n💾 当前总token数: {total_tokens} / {self.target_tokens} (目标)")
        
        # 2. 如果未超标，直接返回
        if total_tokens <= self.target_tokens:
            logger.debug(f"✅ Token使用在安全范围内，无需优化\n")
            return context_parts, {
                'original_tokens': total_tokens,
                'optimized_tokens': total_tokens,
                'savings': 0,
                'savings_percentage': 0,
                'details': token_usage
            }
        
        # 3. 需要优化：按优先级压缩
        logger.debug(f"\n⚠️  Token超标 ({total_tokens - self.target_tokens} tokens)，开始智能压缩...\n")
        
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
        logger.debug("压缩详情:")
        for log in compression_log:
            logger.debug(f"   {log}")
        
        logger.debug(f"\n💾 优化后总token数: {optimized_tokens} / {self.target_tokens} (目标)")
        savings = total_tokens - optimized_tokens
        savings_pct = (savings / total_tokens * 100) if total_tokens > 0 else 0
        logger.debug(f"📉 节省: {savings} tokens ({savings_pct:.1f}%)\n")
        
        # 4. 如果还是超标，进一步压缩大纲
        if optimized_tokens > self.target_tokens:
            logger.debug(f"⚠️  仍然超标，对情节大纲进行进一步压缩...")
            
            if 'plot_outline' in optimized_parts:
                outline = optimized_parts['plot_outline']
                outline_tokens = self.estimate_tokens(outline)
                needed_reduction = optimized_tokens - self.target_tokens
                
                new_outline_tokens = max(2000, outline_tokens - needed_reduction)
                new_outline_chars = int(new_outline_tokens * self.CN_CHARS_PER_TOKEN)
                
                optimized_parts['plot_outline'] = self.summarize_text(outline, new_outline_chars)
                new_tokens = self.estimate_tokens(optimized_parts['plot_outline'])
                
                optimized_tokens = optimized_tokens - outline_tokens + new_tokens
                logger.debug(f"   🔧 plot_outline: {outline_tokens} → {new_tokens} tokens")
                logger.debug(f"   💾 最终token数: {optimized_tokens}")
        
        logger.debug(f"{'='*70}\n")
        
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
            # 🆕 智能提取当前章节相关的大纲内容
            extracted_outline = self.extract_relevant_outline(
                full_outline=plot_outline,
                target_chapter=self.current_chapter,
                context_range=2  # 前后各2章
            )
            context_parts['plot_outline'] = extracted_outline
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
