"""
提示词进化系统 - 历史经验智能去重与优化

核心功能：
1. 语义去重：使用LLM识别并合并语义相似的经验
2. 效果排序：基于历史表现优先保留高效策略
3. 自动触发：在特定时机自动清理和优化经验库
4. 质量追踪：记录每条经验的使用频率和效果
"""
import logging
import re
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter

from core.unified_llm_client import get_llm_client
from core.model_resolution import TaskType

logger = logging.getLogger(__name__)


@dataclass
class ExperienceItem:
    """增强版经验条目（带效果追踪）"""
    text: str                               # 经验文本
    category: str                           # 类别：effective/ineffective/forbidden/best_practice
    appearance_count: int = 1               # 出现次数
    source_reports: List[str] = field(default_factory=list)  # 来源报告ID
    first_seen: Optional[str] = None        # 首次出现时间
    last_seen: Optional[str] = None         # 最近出现时间
    
    # 效果追踪（可选，当有数据时填充）
    avg_score_improvement: Optional[float] = None   # 平均降分效果
    success_rate: Optional[float] = None            # 成功率
    
    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "category": self.category,
            "appearance_count": self.appearance_count,
            "source_reports": self.source_reports,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "avg_score_improvement": self.avg_score_improvement,
            "success_rate": self.success_rate
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'ExperienceItem':
        return ExperienceItem(
            text=data["text"],
            category=data["category"],
            appearance_count=data.get("appearance_count", 1),
            source_reports=data.get("source_reports", []),
            first_seen=data.get("first_seen"),
            last_seen=data.get("last_seen"),
            avg_score_improvement=data.get("avg_score_improvement"),
            success_rate=data.get("success_rate")
        )


@dataclass
class OptimizationResult:
    """优化结果"""
    original_count: int                     # 原始条目数
    deduplicated_count: int                 # 去重后数量
    merged_groups: List[List[str]]          # 合并的组
    top_strategies: List[ExperienceItem]    # TOP策略
    removed_low_quality: List[str]          # 移除的低质量经验
    optimization_summary: str               # 优化摘要


class ExperienceOptimizer:
    """历史经验智能去重与优化器"""
    
    def __init__(self):
        self.llm_client = get_llm_client()
        
        # 优化配置
        self.similarity_threshold = 0.85        # 语义相似度阈值
        self.min_appearance_count = 2           # 最小出现次数（低于此值的需要特别审查）
        self.top_n_per_category = 15            # 每个类别保留的TOP数量
        
        # 清理规则
        self.remove_if_appearance_lt = 1        # 仅出现1次且效果未知的经验可删除
        self.remove_if_too_vague = True         # 删除过于模糊的经验
    
    async def optimize_experiences(
        self,
        all_reports: List[Dict],
        genre: Optional[str] = None
    ) -> OptimizationResult:
        """
        智能优化所有历史经验
        
        Args:
            all_reports: 所有经验报告列表
            genre: 可选的题材过滤
        
        Returns:
            OptimizationResult
        """
        logger.info(f"🔧 开始优化历史经验，共 {len(all_reports)} 个报告")
        
        # 1. 提取并统计所有经验
        logger.info("📊 步骤1: 提取并统计经验...")
        experiences = self._extract_all_experiences(all_reports, genre)
        original_count = sum(len(exps) for exps in experiences.values())
        logger.info(f"   提取到 {original_count} 条经验（有效:{len(experiences['effective'])}, "
                   f"无效:{len(experiences['ineffective'])}, 禁止:{len(experiences['forbidden'])}, "
                   f"最佳:{len(experiences['best_practice'])}）")
        
        # 2. 语义去重（每个类别独立处理）
        logger.info("🔍 步骤2: 语义去重...")
        deduplicated = {}
        merged_groups_all = []
        
        for category, items in experiences.items():
            if not items:
                deduplicated[category] = []
                continue
            
            logger.info(f"   处理类别: {category} ({len(items)}条)")
            dedup_items, merged_groups = await self._semantic_deduplication(items, category)
            deduplicated[category] = dedup_items
            merged_groups_all.extend(merged_groups)
            logger.info(f"   ✅ {category}: {len(items)} -> {len(dedup_items)} (合并了{len(merged_groups)}组)")
        
        deduplicated_count = sum(len(exps) for exps in deduplicated.values())
        
        # 3. 质量过滤（移除低质量经验）
        logger.info("🧹 步骤3: 质量过滤...")
        filtered, removed = self._quality_filter(deduplicated)
        logger.info(f"   移除低质量经验 {len(removed)} 条")
        
        # 4. 按效果排序并保留TOP N
        logger.info("📈 步骤4: 效果排序...")
        top_strategies = self._rank_and_select_top(filtered)
        
        # 5. 生成优化摘要
        summary = self._generate_summary(
            original_count, deduplicated_count, len(removed), 
            merged_groups_all, top_strategies
        )
        
        result = OptimizationResult(
            original_count=original_count,
            deduplicated_count=deduplicated_count,
            merged_groups=merged_groups_all,
            top_strategies=top_strategies,
            removed_low_quality=removed,
            optimization_summary=summary
        )
        
        logger.info(f"✅ 优化完成: {original_count} -> {len(top_strategies)} 条核心经验")
        return result
    
    def _extract_all_experiences(
        self, 
        reports: List[Dict],
        genre: Optional[str] = None
    ) -> Dict[str, List[ExperienceItem]]:
        """
        从所有报告中提取经验，并统计出现频率
        
        Returns:
            {"effective": [...], "ineffective": [...], "forbidden": [...], "best_practice": [...]}
        """
        # 使用字典统计每条经验的出现情况
        experience_tracker: Dict[str, Dict[str, ExperienceItem]] = {
            "effective": {},
            "ineffective": {},
            "forbidden": {},
            "best_practice": {}
        }
        
        # 题材过滤
        # - 兼容历史数据：缺失 genre 视为「通用」
        # - 「通用」视为不过滤（全量），避免误杀其它题材的高质量经验
        if genre and genre != "通用":
            reports = [r for r in reports if (r.get("genre") or "通用") == genre]
        
        # 按时间排序（最新的优先）
        sorted_reports = sorted(
            reports,
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )
        
        for report in sorted_reports:
            report_id = report.get("evolution_id", "unknown")
            created_at = report.get("created_at", "")
            
            # 处理4种类型的经验
            for category in ["effective_strategies", "ineffective_strategies", 
                           "forbidden_patterns", "best_practices"]:
                # 映射到简化的类别名
                category_key = category.replace("_strategies", "").replace("_patterns", "").replace("_practices", "_practice")
                
                for exp_text in report.get(category, []):
                    if not exp_text or not exp_text.strip():
                        continue
                    
                    exp_text = exp_text.strip()
                    
                    if exp_text in experience_tracker[category_key]:
                        # 已存在，增加计数
                        item = experience_tracker[category_key][exp_text]
                        item.appearance_count += 1
                        item.source_reports.append(report_id)
                        item.last_seen = created_at
                    else:
                        # 新经验
                        experience_tracker[category_key][exp_text] = ExperienceItem(
                            text=exp_text,
                            category=category_key,
                            appearance_count=1,
                            source_reports=[report_id],
                            first_seen=created_at,
                            last_seen=created_at
                        )
        
        # 转换为列表
        result = {
            category: list(items.values())
            for category, items in experience_tracker.items()
        }
        
        return result
    
    async def _semantic_deduplication(
        self,
        items: List[ExperienceItem],
        category: str
    ) -> Tuple[List[ExperienceItem], List[List[str]]]:
        """
        使用LLM进行语义去重（分批处理大量经验）
        
        Args:
            items: 待去重的经验列表
            category: 经验类别
        
        Returns:
            (去重后的经验列表, 合并的组列表)
        """
        if len(items) <= 3:
            # 数量太少，不需要去重
            return items, []
        
        # 🆕 分批处理：如果经验数量超过100条，分批去重
        batch_size = 100
        if len(items) > batch_size:
            logger.info(f"   📦 经验数量较多（{len(items)}条），采用分批处理...")
            return await self._batch_semantic_deduplication(items, category, batch_size)
        
        # 正常单批处理
        
        # 🆕 构建去重提示词（带时间戳）
        items_text = "\n".join([
            f"{i+1}. {item.text} (出现{item.appearance_count}次, 最新: {item.last_seen or '未知'})"
            for i, item in enumerate(items)
        ])
        
        category_name_map = {
            "effective": "有效策略",
            "ineffective": "无效策略",
            "forbidden": "禁止模式",
            "best_practice": "最佳实践"
        }
        category_display = category_name_map.get(category, category)
        
        prompt = f"""请分析以下【{category_display}】列表，识别并合并语义相同或高度相似的条目。

原始列表：
{items_text}

任务要求：
1. 识别语义相同或高度相似（>85%）的条目
2. 将相似条目合并为一条，保留最具体、最可操作的表述
3. 合并时优先保留出现次数多的表述
4. 如果表述质量相当，合并为包含示例的完整版本
5. 完全不同的条目保持独立

🆕 **冲突检测与时间优先级：**
6. 识别相互矛盾或对立的经验条目（如"多用A" vs "少用A"）
7. 当发现冲突时，**优先保留最新的经验**（最近更新时间），删除旧的
8. 在输出中明确标记哪些是因冲突而被删除的旧经验

输出格式（严格遵守）：
===MERGED_GROUPS===
[如果有合并，每组一行，格式: 序号1,序号2,序号3|合并后的文本]
[如果没有合并，输出: 无需合并]
===MERGED_GROUPS_END===

===CONFLICT_REMOVED===
[如果有冲突，每个被删除的旧经验一行，格式: 序号|原因]
[如果没有冲突，输出: 无冲突]
===CONFLICT_REMOVED_END===

===DEDUPLICATED_LIST===
[去重后的完整列表，每行一条]
===DEDUPLICATED_LIST_END===

示例输出：
===MERGED_GROUPS===
1,5,8|用身体反应/具体动作替代直接情感陈述（如"喉咙发紧"替代"感到悲伤"）
===MERGED_GROUPS_END===

===CONFLICT_REMOVED===
3|与第15条冲突，第15条更新，保留新的
===CONFLICT_REMOVED_END===

===DEDUPLICATED_LIST===
用身体反应/具体动作替代直接情感陈述（如"喉咙发紧"替代"感到悲伤"）
对话中增加语气词和省略（如"嗯""啊""呢"）
...
===DEDUPLICATED_LIST_END===
"""
        
        try:
            # 调用LLM
            messages = [
                {"role": "system", "content": "你是经验去重专家，擅长识别语义相似的文本并进行智能合并。"},
                {"role": "user", "content": prompt}
            ]
            
            response = await self.llm_client.chat(
                messages=messages,
                task_type=TaskType.REVIEW_CHECK,
                temperature=0.3,  # 低温度，保证稳定输出
                use_cache=False
            )
            
            # 🐛 调试：输出LLM响应的前500字符
            logger.debug(f"   📝 LLM响应预览: {response[:500]}...")
            
            # 解析响应
            deduplicated_texts, merged_groups = self._parse_deduplication_response(response)
            
            # 🐛 调试：输出解析结果
            logger.debug(f"   📊 解析结果: {len(deduplicated_texts)} 条文本, {len(merged_groups)} 个合并组")
            
            if not deduplicated_texts:
                logger.warning(f"   ⚠️ LLM去重失败，保持原样")
                # 🐛 输出完整响应以便调试
                logger.warning(f"   🐛 完整响应:\n{response}")
                return items, []
            
            # 重建ExperienceItem列表（合并出现次数和来源）
            text_to_original_items = {}
            for item in items:
                text_to_original_items[item.text] = item
            
            deduplicated_items = []
            for new_text in deduplicated_texts:
                # 尝试找到对应的原始item
                matched_item = None
                max_similarity = 0
                
                for original_text, original_item in text_to_original_items.items():
                    similarity = self._simple_text_similarity(new_text, original_text)
                    if similarity > max_similarity:
                        max_similarity = similarity
                        matched_item = original_item
                
                if matched_item and max_similarity > 0.6:
                    # 复制原始item，更新文本
                    new_item = ExperienceItem(
                        text=new_text,
                        category=category,
                        appearance_count=matched_item.appearance_count,
                        source_reports=matched_item.source_reports.copy(),
                        first_seen=matched_item.first_seen,
                        last_seen=matched_item.last_seen,
                        avg_score_improvement=matched_item.avg_score_improvement,
                        success_rate=matched_item.success_rate
                    )
                else:
                    # 新生成的文本，创建新item
                    new_item = ExperienceItem(
                        text=new_text,
                        category=category,
                        appearance_count=1,
                        source_reports=[],
                        first_seen=datetime.now().isoformat(),
                        last_seen=datetime.now().isoformat()
                    )
                
                deduplicated_items.append(new_item)
            
            # 处理合并组（合并出现次数）
            for group_indices, merged_text in merged_groups:
                # 找到合并后的item
                merged_item = None
                for item in deduplicated_items:
                    if self._simple_text_similarity(item.text, merged_text) > 0.8:
                        merged_item = item
                        break
                
                if merged_item:
                    # 合并所有原始item的统计信息
                    total_count = 0
                    all_sources = []
                    earliest_seen = None
                    latest_seen = None
                    
                    for idx in group_indices:
                        if 0 <= idx < len(items):
                            original_item = items[idx]
                            total_count += original_item.appearance_count
                            all_sources.extend(original_item.source_reports)
                            
                            if earliest_seen is None or (original_item.first_seen and original_item.first_seen < earliest_seen):
                                earliest_seen = original_item.first_seen
                            if latest_seen is None or (original_item.last_seen and original_item.last_seen > latest_seen):
                                latest_seen = original_item.last_seen
                    
                    merged_item.appearance_count = total_count
                    merged_item.source_reports = list(set(all_sources))  # 去重
                    merged_item.first_seen = earliest_seen
                    merged_item.last_seen = latest_seen
            
            return deduplicated_items, [[items[i].text for i in group_indices] for group_indices, _ in merged_groups]
            
        except Exception as e:
            logger.error(f"   ❌ 语义去重失败: {e}")
            return items, []
    
    def _parse_deduplication_response(self, response: str) -> Tuple[List[str], List[Tuple[List[int], str]]]:
        """
        解析LLM的去重响应（增强容错 + 冲突检测）
        
        Returns:
            (去重后的文本列表, [(合并的序号列表, 合并后文本), ...])
        """
        deduplicated_texts = []
        merged_groups = []
        conflict_removed = []  # 🆕 新增：冲突被删除的经验
        
        # 🆕 解析MERGED_GROUPS（增强容错）
        merged_match = re.search(r'===MERGED_GROUPS===\s*(.*?)\s*===MERGED_GROUPS_END===', response, re.DOTALL)
        if merged_match:
            merged_content = merged_match.group(1).strip()
            if merged_content and merged_content != "无需合并":
                for line in merged_content.split('\n'):
                    line = line.strip()
                    if not line or line == "无需合并":
                        continue
                    # 格式: 1,5,8|合并后的文本
                    if '|' in line:
                        try:
                            indices_part, text_part = line.split('|', 1)
                            indices = [int(i.strip())-1 for i in indices_part.split(',') if i.strip().isdigit()]  # 转为0-based
                            if indices and text_part.strip():  # 🆕 确保有效
                                merged_groups.append((indices, text_part.strip()))
                        except (ValueError, IndexError) as e:
                            logger.debug(f"   ⚠️ 跳过无效合并行: {line} ({e})")
                            continue
        
        # 🆕 新增：解析CONFLICT_REMOVED
        conflict_match = re.search(r'===CONFLICT_REMOVED===\s*(.*?)\s*===CONFLICT_REMOVED_END===', response, re.DOTALL)
        if conflict_match:
            conflict_content = conflict_match.group(1).strip()
            if conflict_content and conflict_content != "无冲突":
                for line in conflict_content.split('\n'):
                    line = line.strip()
                    if not line or line == "无冲突":
                        continue
                    # 格式: 3|原因
                    if '|' in line:
                        try:
                            idx_part, reason_part = line.split('|', 1)
                            idx = int(idx_part.strip()) - 1  # 转为0-based
                            conflict_removed.append((idx, reason_part.strip()))
                            logger.info(f"   🗑️ 冲突删除: 第{idx+1}条 - {reason_part.strip()}")
                        except (ValueError, IndexError) as e:
                            logger.debug(f"   ⚠️ 跳过无效冲突行: {line} ({e})")
                            continue
        
        # 🆕 解析DEDUPLICATED_LIST（增强容错）
        dedup_match = re.search(r'===DEDUPLICATED_LIST===\s*(.*?)\s*===DEDUPLICATED_LIST_END===', response, re.DOTALL)
        if dedup_match:
            dedup_content = dedup_match.group(1).strip()
            for line in dedup_content.split('\n'):
                line = line.strip()
                # 🆕 过滤空行、编号、分隔符
                if not line:
                    continue
                # 移除常见的编号格式
                line = re.sub(r'^\d+[.、)]\s*', '', line)  # 移除1. 或 1、或 1)
                line = re.sub(r'^[-*·]\s*', '', line)  # 移除- * ·
                if line and len(line) > 3:  # 🆕 至少要有4个字符
                    deduplicated_texts.append(line)
        
        # 🆕 如果没有找到标记块，尝试直接解析整个响应
        if not deduplicated_texts:
            logger.warning("   ⚠️ 未找到标准格式标记，尝试备用解析...")
            # 备用策略：将每一行都当作一条经验
            for line in response.split('\n'):
                line = line.strip()
                # 过滤明显是标记或指令的行
                if not line or line.startswith('===') or line.startswith('#') or line.startswith('【') or line in ['无需合并', '无冲突', '任务要求', '输出格式', '原始列表']:
                    continue
                # 移除编号
                line = re.sub(r'^\d+[.、)]\s*', '', line)
                line = re.sub(r'^[-*·]\s*', '', line)
                if line and len(line) > 3 and not line.endswith('：'):
                    deduplicated_texts.append(line)
        
        return deduplicated_texts, merged_groups
    
    def _simple_text_similarity(self, text1: str, text2: str) -> float:
        """简单的文本相似度计算（基于字符集合）"""
        if not text1 or not text2:
            return 0.0
        
        # 转换为字符集合
        set1 = set(text1)
        set2 = set(text2)
        
        # Jaccard相似度
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    async def _batch_semantic_deduplication(
        self,
        items: List[ExperienceItem],
        category: str,
        batch_size: int = 100
    ) -> Tuple[List[ExperienceItem], List[List[str]]]:
        """
        🆕 分批语义去重：处理大量经验
        
        策略：
        1. 先按出现次数排序，高频经验优先
        2. 分批处理，每批100条
        3. 每批去重后合并结果
        4. 最后对合并结果再做一次去重
        """
        logger.info(f"   📦 开始分批去重: 总计{len(items)}条，每批{batch_size}条")
        
        # 步骤1：按出现次数排序（高频经验优先）
        sorted_items = sorted(items, key=lambda x: (x.appearance_count, x.last_seen or ""), reverse=True)
        
        # 步骤2：分批
        batches = [sorted_items[i:i+batch_size] for i in range(0, len(sorted_items), batch_size)]
        logger.info(f"   📦 分为{len(batches)}个批次")
        
        # 步骤3：每批去重
        all_deduplicated = []
        all_merged_groups = []
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"   📦 处理第{batch_idx}/{len(batches)}批（{len(batch)}条）...")
            
            # 调用单批去重逻辑（复用现有方法）
            batch_text = "\n".join([
                f"{i+1}. {item.text} (出现{item.appearance_count}次, 最新: {item.last_seen or '未知'})" 
                for i, item in enumerate(batch)
            ])
            
            # 简化prompt（分批时不需要那么详细）
            deduplicated_batch, merged_batch = await self._deduplicate_single_batch(
                batch, category, batch_idx
            )
            
            all_deduplicated.extend(deduplicated_batch)
            all_merged_groups.extend(merged_batch)
        
        logger.info(f"   ✅ 分批去重完成，得到{len(all_deduplicated)}条")
        
        # 步骤4：对合并结果再做一次轻量去重（只去除完全重复）
        if len(all_deduplicated) > batch_size:
            logger.info(f"   🔄 结果仍较多，进行最终去重...")
            final_deduplicated, final_merged = await self._deduplicate_single_batch(
                all_deduplicated, category, batch_idx=0, is_final=True
            )
            return final_deduplicated, all_merged_groups + final_merged
        
        return all_deduplicated, all_merged_groups
    
    async def _deduplicate_single_batch(
        self,
        batch: List[ExperienceItem],
        category: str,
        batch_idx: int,
        is_final: bool = False
    ) -> Tuple[List[ExperienceItem], List[List[str]]]:
        """单批次去重（简化版）"""
        batch_text = "\n".join([
            f"{i+1}. {item.text}" 
            for i, item in enumerate(batch)
        ])
        
        category_name_map = {
            "effective": "有效策略",
            "ineffective": "无效策略",
            "forbidden": "禁止模式",
            "best_practice": "最佳实践"
        }
        category_display = category_name_map.get(category, category)
        
        # 简化prompt
        prompt = f"""请对以下【{category_display}】列表去重，合并相似项。

{batch_text}

请直接输出去重后的列表，每行一条，不要编号："""
        
        try:
            messages = [
                {"role": "system", "content": "你是经验去重专家。"},
                {"role": "user", "content": prompt}
            ]
            
            response = await self.llm_client.chat(
                messages=messages,
                task_type=TaskType.REVIEW_CHECK,
                temperature=0.3,
                use_cache=False
            )
            
            # 简单解析：每行一条
            deduplicated_texts = []
            for line in response.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                # 移除编号
                line = re.sub(r'^\d+[.、)]\s*', '', line)
                line = re.sub(r'^[-*·]\s*', '', line)
                if len(line) > 3:
                    deduplicated_texts.append(line)
            
            # 重建 ExperienceItem
            deduplicated_items = []
            for text in deduplicated_texts:
                # 找最相似的原始项
                best_match = max(batch, key=lambda x: self._simple_text_similarity(text, x.text))
                if self._simple_text_similarity(text, best_match.text) > 0.5:
                    deduplicated_items.append(ExperienceItem(
                        text=text,
                        category=category,
                        appearance_count=best_match.appearance_count,
                        source_reports=best_match.source_reports.copy(),
                        first_seen=best_match.first_seen,
                        last_seen=best_match.last_seen
                    ))
            
            logger.info(f"     ✅ 批次{batch_idx}: {len(batch)} → {len(deduplicated_items)}")
            return deduplicated_items, []
            
        except Exception as e:
            logger.error(f"     ❌ 批次{batch_idx}去重失败: {e}，保持原样")
            return batch, []
    
    def _quality_filter(
        self,
        experiences: Dict[str, List[ExperienceItem]]
    ) -> Tuple[Dict[str, List[ExperienceItem]], List[str]]:
        """
        质量过滤：移除低质量经验
        
        移除规则：
        1. 仅出现1次且过于模糊的经验
        2. 过于简短（<5个字）且无实质内容的经验
        3. 包含明显错误或矛盾的经验
        
        Returns:
            (过滤后的经验, 被移除的经验文本列表)
        """
        filtered = {}
        removed = []
        
        for category, items in experiences.items():
            filtered_items = []
            
            for item in items:
                should_remove = False
                
                # 规则1: 仅出现1次且过于模糊
                if item.appearance_count == 1 and self._is_too_vague(item.text):
                    should_remove = True
                    removed.append(f"[{category}] {item.text} (过于模糊)")
                
                # 规则2: 过于简短
                if len(item.text) < 5:
                    should_remove = True
                    removed.append(f"[{category}] {item.text} (过于简短)")
                
                # 规则3: 包含明显无效词汇（针对有效策略）
                if category == "effective" and any(word in item.text for word in ["不要", "避免", "禁止"]):
                    should_remove = True
                    removed.append(f"[{category}] {item.text} (负面表述误入有效策略)")
                
                if not should_remove:
                    filtered_items.append(item)
            
            filtered[category] = filtered_items
        
        return filtered, removed
    
    def _is_too_vague(self, text: str) -> bool:
        """判断经验是否过于模糊"""
        vague_patterns = [
            r"^注意",
            r"^避免.*问题",
            r"^保持.*即可",
            r"^适当.*调整",
            r"^合理.*使用",
            r"尽量",
            r"可能",
            r"一般",
        ]
        
        for pattern in vague_patterns:
            if re.search(pattern, text):
                return True
        
        # 没有具体操作或示例
        if len(text) < 15 and '（' not in text and '如' not in text and '例如' not in text:
            return True
        
        return False
    
    def _rank_and_select_top(
        self,
        experiences: Dict[str, List[ExperienceItem]]
    ) -> List[ExperienceItem]:
        """
        按效果排序并选择TOP经验
        
        排序规则：
        1. 出现次数（频率越高优先级越高）
        2. 最近使用时间（越新越优先）
        3. 文本质量（有示例的优先）
        
        Returns:
            所有类别的TOP经验合并列表
        """
        top_strategies = []
        
        for category, items in experiences.items():
            # 排序
            sorted_items = sorted(
                items,
                key=lambda x: (
                    x.appearance_count,                                    # 出现次数（降序）
                    x.last_seen or "",                                     # 最近时间（降序）
                    1 if '（' in x.text or '如' in x.text else 0,         # 有示例优先
                    -len(x.text)                                           # 更详细的优先
                ),
                reverse=True
            )
            
            # 选择TOP N
            top_items = sorted_items[:self.top_n_per_category]
            top_strategies.extend(top_items)
            
            logger.info(f"   {category}: 保留TOP {len(top_items)}/{len(items)}")
        
        return top_strategies
    
    def _generate_summary(
        self,
        original_count: int,
        deduplicated_count: int,
        removed_count: int,
        merged_groups: List[List[str]],
        top_strategies: List[ExperienceItem]
    ) -> str:
        """生成优化摘要"""
        lines = []
        lines.append("=" * 60)
        lines.append("📊 历史经验优化报告")
        lines.append("=" * 60)
        lines.append(f"原始经验数: {original_count}")
        lines.append(f"去重后数量: {deduplicated_count}")
        lines.append(f"移除低质量: {removed_count}")
        lines.append(f"最终保留: {len(top_strategies)}")
        lines.append(f"压缩比例: {len(top_strategies)/original_count*100:.1f}%")
        lines.append("")
        
        lines.append(f"🔀 合并组数: {len(merged_groups)}")
        if merged_groups:
            for i, group in enumerate(merged_groups[:5], 1):  # 只显示前5组
                lines.append(f"  {i}. 合并了 {len(group)} 条相似经验")
        
        lines.append("")
        lines.append("📈 各类别TOP经验分布:")
        category_counter = Counter(item.category for item in top_strategies)
        for category, count in category_counter.items():
            lines.append(f"  - {category}: {count}条")
        
        lines.append("")
        lines.append("🏆 高频经验TOP 5:")
        top_5 = sorted(top_strategies, key=lambda x: x.appearance_count, reverse=True)[:5]
        for i, item in enumerate(top_5, 1):
            lines.append(f"  {i}. [{item.category}] {item.text[:50]}... (出现{item.appearance_count}次)")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def should_trigger_optimization(
        self,
        total_reports: int,
        last_optimization_count: int
    ) -> bool:
        """
        判断是否应该触发优化
        
        触发条件：
        1. 新增报告数 >= 20
        2. 总报告数 > 40
        
        Args:
            total_reports: 当前总报告数
            last_optimization_count: 上次优化时的报告数
        
        Returns:
            是否应该触发
        """
        new_reports = total_reports - last_optimization_count
        
        # 条件1: 新增20个报告
        if new_reports >= 20:
            logger.info(f"✅ 触发条件1: 新增 {new_reports} 个报告（阈值:20）")
            return True
        
        # 条件2: 总数>40且未优化过
        if total_reports > 40 and last_optimization_count == 0:
            logger.info(f"✅ 触发条件2: 总报告数 {total_reports}（阈值:40）")
            return True
        
        return False


# 单例实例
_optimizer: Optional[ExperienceOptimizer] = None


def get_experience_optimizer() -> ExperienceOptimizer:
    """获取经验优化器单例"""
    global _optimizer
    if _optimizer is None:
        _optimizer = ExperienceOptimizer()
    return _optimizer

