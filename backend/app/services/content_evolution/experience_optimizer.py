"""
内容创作进化 - 经验库优化器

核心功能：
1. 去重合并：使用LLM智能去重，分批处理大量经验
2. 冲突检测：识别矛盾经验，保留最新的（70%新经验权重+30%频率）
3. 质量过滤：移除低质量经验
4. TOP排序：按效果排序并选择TOP经验

差异点（相比降AI率优化器）：
- 经验类型：variant_success/variant_failure/feedback_patterns
- 冲突判断：基于隐式反馈趋势（编辑量、保留率）
- 时间权重：70%新经验 + 30%频率
- 题材处理：按模块（世界观/人物/大纲）+题材双重分类
"""
import logging
import re
from datetime import datetime
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from core.unified_llm_client import get_llm_client
from core.model_resolution import TaskType

logger = logging.getLogger(__name__)


@dataclass
class ExperienceItem:
    """经验条目"""
    text: str                           # 经验文本
    category: str                       # 类别：variant_success/variant_failure/feedback_patterns
    appearance_count: int = 1           # 出现次数
    source_reports: List[str] = None    # 来源报告ID列表
    first_seen: str = None              # 首次出现时间
    last_seen: str = None               # 最近出现时间
    avg_score_improvement: float = 0.0  # 平均得分提升
    success_rate: float = 0.0           # 成功率


class ContentExperienceOptimizer:
    """内容创作经验优化器"""
    
    def __init__(
        self,
        top_n_per_category: int = 15,  # 每类保留TOP 15（内容质量经验更复杂）
        llm_client = None  # 🆕 可选，用于测试
    ):
        """
        初始化经验优化器
        
        Args:
            top_n_per_category: 每个类别保留的TOP N数量
            llm_client: 可选，用于测试时Mock
        """
        self.top_n_per_category = top_n_per_category
        self.llm_client = llm_client or get_llm_client()  # 🆕 支持Mock
        
        logger.info(f"🎨 内容创作经验优化器初始化: 每类TOP {top_n_per_category}")
    
    async def optimize_experiences(
        self,
        experiences: Dict[str, List[ExperienceItem]],
        module_name: str = "chapter",  # 模块名（chapter/outline/character）
        genre: str = "通用"
    ) -> Tuple[List[ExperienceItem], str]:
        """
        优化经验库：去重、冲突检测、质量过滤、排序
        
        Args:
            experiences: 经验字典 {category: [ExperienceItem, ...]}
            module_name: 模块名称
            genre: 题材
        
        Returns:
            (TOP经验列表, 优化摘要)
        """
        logger.info(f"🎨 开始内容创作经验优化: {module_name}模块 | {genre}")
        
        original_count = sum(len(items) for items in experiences.values())
        logger.info(f"   📊 原始经验数: {original_count}")
        
        # 步骤1: 语义去重（分批处理）
        deduplicated_experiences = {}
        all_merged_groups = []
        
        for category, items in experiences.items():
            if not items:
                deduplicated_experiences[category] = []
                continue
            
            logger.info(f"   处理类别: {category} ({len(items)}条)")
            deduplicated, merged = await self._semantic_deduplication(items, category)
            deduplicated_experiences[category] = deduplicated
            all_merged_groups.extend(merged)
        
        deduplicated_count = sum(len(items) for items in deduplicated_experiences.values())
        logger.info(f"   ✅ 去重完成: {original_count} -> {deduplicated_count}")
        
        # 步骤2: 质量过滤
        filtered_experiences, removed = self._quality_filter(deduplicated_experiences)
        filtered_count = sum(len(items) for items in filtered_experiences.values())
        logger.info(f"   ✅ 质量过滤: {deduplicated_count} -> {filtered_count} (移除{len(removed)}条)")
        
        # 步骤3: 排序并选择TOP
        top_strategies = self._rank_and_select_top(filtered_experiences)
        logger.info(f"   ✅ 最终保留: {len(top_strategies)} 条核心经验")
        
        # 生成摘要
        summary = self._generate_summary(
            original_count,
            deduplicated_count,
            len(removed),
            all_merged_groups,
            top_strategies
        )
        
        return top_strategies, summary
    
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
        
        # 🆕 构建去重提示词（带时间戳和成功率）
        items_text = "\n".join([
            f"{i+1}. {item.text} (出现{item.appearance_count}次, 成功率{item.success_rate:.1%}, 最新: {item.last_seen or '未知'})"
            for i, item in enumerate(items)
        ])
        
        category_name_map = {
            "variant_success": "成功变体经验",
            "variant_failure": "失败变体教训",
            "feedback_patterns": "反馈规律"
        }
        category_display = category_name_map.get(category, category)
        
        prompt = f"""请分析以下【{category_display}】列表，识别并合并语义相同或高度相似的条目。

原始列表：
{items_text}

任务要求：
1. 识别语义相同或高度相似（>85%）的条目
2. 将相似条目合并为一条，保留最具体、最可操作的表述
3. 合并时优先保留成功率高、出现次数多的表述
4. 如果表述质量相当，合并为包含示例的完整版本
5. 完全不同的条目保持独立

🆕 **冲突检测与时间优先级：**
6. 识别相互矛盾的经验（如"增加描写提升质量" vs "减少描写提升节奏"）
7. 当发现冲突时，采用**加权策略**：新经验权重70% + 出现频率30%
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
1,5,8|增加细节描写可提升读者代入感（测试3次，成功率100%）
===MERGED_GROUPS_END===

===CONFLICT_REMOVED===
3|与第15条冲突（都关注描写，但第15条更新且成功率更高）
===CONFLICT_REMOVED_END===

===DEDUPLICATED_LIST===
增加细节描写可提升读者代入感（测试3次，成功率100%）
降低对话比例可提升叙事节奏（测试2次，成功率50%）
...
===DEDUPLICATED_LIST_END===
"""
        
        try:
            # 调用LLM
            messages = [
                {"role": "system", "content": "你是内容创作经验去重专家，擅长识别相似的创作规律并智能合并。"},
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
                        source_reports=matched_item.source_reports.copy() if matched_item.source_reports else [],
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
                            if original_item.source_reports:
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
                            indices = [int(x.strip()) - 1 for x in indices_part.split(',')]  # 转为0-based
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
                if not line:
                    continue
                # 移除常见编号格式
                line = re.sub(r'^\d+[.、)]\s*', '', line)
                line = re.sub(r'^[-*·]\s*', '', line)
                # 过滤明显是标记或分隔符的行
                if line.startswith('===') or line.startswith('#') or line.startswith('【'):
                    continue
                if line in ['无需合并', '无冲突', '任务要求', '输出格式', '原始列表']:
                    continue
                if len(line) > 3 and not line.endswith('：'):
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
        1. 先按成功率和出现次数排序，高价值经验优先
        2. 分批处理，每批100条
        3. 每批去重后合并结果
        4. 最后对合并结果再做一次去重
        """
        logger.info(f"   📦 开始分批去重: 总计{len(items)}条，每批{batch_size}条")
        
        # 步骤1：按成功率和出现次数排序（高价值经验优先）
        sorted_items = sorted(items, key=lambda x: (x.success_rate, x.appearance_count, x.last_seen or ""), reverse=True)
        
        # 步骤2：分批
        batches = [sorted_items[i:i+batch_size] for i in range(0, len(sorted_items), batch_size)]
        logger.info(f"   📦 分为{len(batches)}个批次")
        
        # 步骤3：每批去重
        all_deduplicated = []
        all_merged_groups = []
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"   📦 处理第{batch_idx}/{len(batches)}批（{len(batch)}条）...")
            
            # 调用单批去重逻辑（复用现有方法）
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
            "variant_success": "成功变体经验",
            "variant_failure": "失败变体教训",
            "feedback_patterns": "反馈规律"
        }
        category_display = category_name_map.get(category, category)
        
        # 简化prompt
        prompt = f"""请对以下【{category_display}】列表去重，合并相似项。

{batch_text}

请直接输出去重后的列表，每行一条，不要编号："""
        
        try:
            messages = [
                {"role": "system", "content": "你是内容创作经验去重专家。"},
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
                        source_reports=best_match.source_reports.copy() if best_match.source_reports else [],
                        first_seen=best_match.first_seen,
                        last_seen=best_match.last_seen,
                        avg_score_improvement=best_match.avg_score_improvement,
                        success_rate=best_match.success_rate
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
        3. 成功率为0的成功经验（矛盾）
        
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
                
                # 规则3: 成功经验但成功率为0（矛盾）
                if category == "variant_success" and item.success_rate == 0:
                    should_remove = True
                    removed.append(f"[{category}] {item.text} (成功率为0)")
                
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
        1. 成功率（越高越优先）
        2. 出现次数（频率越高越优先）
        3. 最近使用时间（越新越优先）
        4. 文本质量（有示例的优先）
        
        Returns:
            所有类别的TOP经验合并列表
        """
        top_strategies = []
        
        for category, items in experiences.items():
            # 排序
            sorted_items = sorted(
                items,
                key=lambda x: (
                    x.success_rate,                                      # 成功率（降序）
                    x.appearance_count,                                  # 出现次数（降序）
                    x.last_seen or "",                                   # 最近时间（降序）
                    1 if '（' in x.text or '如' in x.text else 0,       # 有示例优先
                    -len(x.text)                                         # 更详细的优先
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
        from collections import Counter
        
        lines = []
        lines.append("=" * 60)
        lines.append("🎨 内容创作经验优化报告")
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
        top_5 = sorted(top_strategies, key=lambda x: (x.success_rate, x.appearance_count), reverse=True)[:5]
        for i, item in enumerate(top_5, 1):
            lines.append(f"  {i}. [{item.category}] {item.text[:50]}... (成功率{item.success_rate:.1%}, 出现{item.appearance_count}次)")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def should_trigger_optimization(
        self,
        total_variants: int,
        last_optimization_count: int
    ) -> bool:
        """
        判断是否应该触发优化
        
        触发条件：
        1. 新增变体数 >= 15（内容质量经验积累更快）
        2. 总变体数 > 30
        
        Args:
            total_variants: 当前总变体数
            last_optimization_count: 上次优化时的变体数
        
        Returns:
            是否应该触发
        """
        new_variants = total_variants - last_optimization_count
        
        # 条件1: 新增15个变体
        if new_variants >= 15:
            logger.info(f"✅ 触发条件1: 新增 {new_variants} 个变体（阈值:15）")
            return True
        
        # 条件2: 总数>30且未优化过
        if total_variants > 30 and last_optimization_count == 0:
            logger.info(f"✅ 触发条件2: 总变体数 {total_variants}（阈值:30）")
            return True
        
        return False


# 单例实例
_optimizer: Optional[ContentExperienceOptimizer] = None


def get_content_experience_optimizer() -> ContentExperienceOptimizer:
    """获取内容创作经验优化器单例"""
    global _optimizer
    if _optimizer is None:
        _optimizer = ContentExperienceOptimizer()
    return _optimizer

