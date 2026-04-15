"""
分层摘要策略 - 自适应上下文整形器

核心策略:
1. pass_through: 输入未超过目标模型安全窗口时，直接透传原文
2. shape_context: 保留局部原文，只把远端内容压成结构化骨架
3. map_reduce: 超大文本才执行分块摘要 + 汇总
"""
import logging
import os
import re
from typing import Dict, Any, Optional, Tuple, List

from langchain_core.messages import SystemMessage, HumanMessage

# 🛡️ 全局禁用代理配置 - 确保直连 API
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    if proxy_var in os.environ:
        del os.environ[proxy_var]

from core.langchain_bridge import create_task_llm
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized
from .knowledge_base import NovelKnowledgeBase
from .structured_memory_store import StructuredMemoryStore

logger = logging.getLogger(__name__)


class LayeredSummarizer:
    """分层摘要器 - 根据模型能力自适应整形上下文"""

    DEFAULT_MODEL_LIMIT = 32000
    DEFAULT_TARGET_TOKENS = 2048
    CHUNK_SUMMARY_MODEL = "qwen3.5-plus"
    REDUCE_SUMMARY_MODEL = "qwen3.5-plus"

    # 模型选择只决定“最终任务用什么模型更合适”，上下文是否压缩由 mode 再决定
    MODEL_SELECTION_RULES = {
        "outline_expand": [
            ((0, 40), ("qwen3.5-plus", 0.70)),
            ((40, 150), ("qwen3.5-plus", 0.65)),
            ((150, 9999), ("qwen3.5-plus", 0.28)),
        ],
        "character_expand": [
            ((0, 15), ("qwen3.5-plus", 0.65)),
            ((15, 60), ("qwen3.5-plus", 0.60)),
            ((60, 200), ("qwen3.5-plus", 0.55)),
            ((200, 9999), ("qwen3.5-plus", 0.28)),
        ],
        "chapter_generation": [
            ((0, 40), ("qwen3-max", 0.78)),
            ((40, 150), ("qwen3.5-plus", 0.70)),
            ((150, 9999), ("qwen-long", 0.35)),
        ],
        "structure_design": [
            ((0, 60), ("deepseek-reasoner", 0.70)),
            ((60, 200), ("qwen3.5-plus", 0.65)),
            ((200, 9999), ("qwen-long", 0.32)),
        ],
    }

    SECTION_WEIGHTS = {
        "outline_expand": {"outline": 0.33, "detail": 0.18, "characters": 0.20, "worldview": 0.13, "memory": 0.16},
        "character_expand": {"outline": 0.18, "detail": 0.10, "characters": 0.42, "worldview": 0.12, "memory": 0.18},
        "chapter_generation": {"outline": 0.30, "detail": 0.23, "characters": 0.16, "worldview": 0.11, "memory": 0.20},
        "structure_design": {"outline": 0.32, "detail": 0.14, "characters": 0.20, "worldview": 0.16, "memory": 0.18},
    }

    def __init__(
        self,
        knowledge_base: Optional[NovelKnowledgeBase] = None,
        persist_directory: str = "memory_data",
        structured_memory_store: Optional[StructuredMemoryStore] = None,
    ):
        """初始化分层摘要器

        Args:
            knowledge_base: 知识库实例(用于 RAG 检索)
        """
        self.knowledge_base = knowledge_base
        self._llm_cache: Dict[Tuple[str, str, float, Optional[int]], Any] = {}
        self.structured_memory_store = structured_memory_store or StructuredMemoryStore(persist_directory=persist_directory)
        # 保留该属性，兼容历史调用和调试习惯
        self.skeleton_llm = self._get_llm(self.CHUNK_SUMMARY_MODEL, task_type="summarize", temperature=0.2, max_tokens=1500)

    def prepare_context_for_expansion(
        self,
        outline: str,
        characters: str,
        worldview: str,
        scenario: str = "outline_expand",
        current_count: int = 50,
        focus_range: Optional[Tuple[int, int]] = None,
        project_id: Optional[int] = None,
    ) -> dict:
        """
        为扩展任务准备优化上下文

        Args:
            outline: 情节大纲
            characters: 人物设定
            worldview: 世界观设定
            scenario: 使用场景
            current_count: 当前章节数或人物数
            focus_range: 聚焦范围

        Returns:
            {
                "context": 优化后的上下文,
                "selected_model": 选择的模型,
                "stats": 统计信息
            }
        """

        logger.debug(f"\n{'=' * 70}")
        logger.debug(f"【分层摘要器】开始处理 {scenario}")
        logger.debug(f"   当前规模: {current_count} {'章' if 'chapter' in scenario or 'outline' in scenario else '人'}")
        logger.debug(f"{'=' * 70}\n")

        selected_model, target_ratio = self._select_model(scenario, current_count)
        model_limit = self._get_model_limit(selected_model)
        target_tokens = max(self.DEFAULT_TARGET_TOKENS, int(model_limit * target_ratio))

        original_context = self._assemble_context(
            outline=outline,
            memory_text="",
            detail_content="",
            characters=characters,
            worldview=worldview,
            mode="raw",
        )
        original_tokens = self._estimate_tokens(original_context)
        mode = self._select_preparation_mode(original_tokens, target_tokens, model_limit)
        persisted_payload = self.structured_memory_store.load(project_id)
        persisted_memory = persisted_payload.get("structured_memory", {}) if isinstance(persisted_payload, dict) else {}

        logger.debug("📊 模型选择:")
        logger.debug(f"   - 选择模型: {selected_model}")
        logger.debug(f"   - 模型上下文上限: {model_limit:,}")
        logger.debug(f"   - 目标tokens: {target_tokens:,} ({target_ratio * 100:.0f}%使用率)")
        logger.debug(f"   - 原始tokens: {original_tokens:,}")
        logger.debug(f"   - 处理模式: {mode}\n")

        if mode == "pass_through":
            current_structured_memory = self._build_structured_memory(
                outline=outline,
                characters=characters,
                worldview=worldview,
                detail_content="",
                focus_range=focus_range,
            )
            structured_memory = self.structured_memory_store.merge(current_structured_memory, persisted_memory)
            memory_text = self._render_structured_memory(
                structured_memory=structured_memory,
                budget_tokens=min(1200, max(280, int(target_tokens * 0.12))),
            )
            memory_tokens = self._estimate_tokens(memory_text)
            include_memory = original_tokens + memory_tokens <= target_tokens
            final_context = self._assemble_context(
                outline=outline,
                memory_text=memory_text if include_memory else "",
                detail_content="",
                characters=characters,
                worldview=worldview,
                mode=mode,
            )
            skeleton_tokens = 0
            detail_tokens = 0
            if not include_memory:
                memory_text = ""
                memory_tokens = 0
            section_strategies = {"outline": "raw", "characters": "raw", "worldview": "raw"}
        else:
            budgets = self._allocate_section_budgets(scenario, target_tokens)

            outline_section, outline_strategy = self._shape_section(
                content=outline,
                content_type="outline",
                budget_tokens=budgets["outline"],
                mode=mode,
            )
            character_section, character_strategy = self._shape_section(
                content=characters,
                content_type="character",
                budget_tokens=budgets["characters"],
                mode=mode,
            )
            worldview_section, worldview_strategy = self._shape_section(
                content=worldview,
                content_type="worldview",
                budget_tokens=budgets["worldview"],
                mode=mode,
            )

            detail_content = self._add_detailed_sections(
                outline=outline,
                characters=characters,
                current_count=current_count,
                available_tokens=budgets["detail"],
                focus_range=focus_range,
            )
            current_structured_memory = self._build_structured_memory(
                outline=outline,
                characters=characters,
                worldview=worldview,
                detail_content=detail_content,
                focus_range=focus_range,
            )
            structured_memory = self.structured_memory_store.merge(current_structured_memory, persisted_memory)
            memory_text = self._render_structured_memory(
                structured_memory=structured_memory,
                budget_tokens=budgets["memory"],
            )
            memory_tokens = self._estimate_tokens(memory_text)
            detail_tokens = self._estimate_tokens(detail_content)
            skeleton_tokens = (
                self._estimate_tokens(outline_section)
                + self._estimate_tokens(character_section)
                + self._estimate_tokens(worldview_section)
            )

            final_context = self._assemble_context(
                outline=outline_section,
                memory_text=memory_text,
                detail_content=detail_content,
                characters=character_section,
                worldview=worldview_section,
                mode=mode,
            )

            if self._estimate_tokens(final_context) > target_tokens:
                detail_content = self._shrink_text_to_token_budget(detail_content, max(int(budgets["detail"] * 0.6), 0))
                detail_tokens = self._estimate_tokens(detail_content)
                final_context = self._assemble_context(
                    outline=outline_section,
                    memory_text=memory_text,
                    detail_content=detail_content,
                    characters=character_section,
                    worldview=worldview_section,
                    mode=mode,
                )

            if self._estimate_tokens(final_context) > target_tokens:
                memory_text = self._render_structured_memory(
                    structured_memory=structured_memory,
                    budget_tokens=max(int(budgets["memory"] * 0.65), 0),
                )
                memory_tokens = self._estimate_tokens(memory_text)
                final_context = self._assemble_context(
                    outline=outline_section,
                    memory_text=memory_text,
                    detail_content=detail_content,
                    characters=character_section,
                    worldview=worldview_section,
                    mode=mode,
                )

            if self._estimate_tokens(final_context) > target_tokens:
                memory_text = ""
                memory_tokens = 0
                final_context = self._assemble_context(
                    outline=outline_section,
                    memory_text="",
                    detail_content=detail_content,
                    characters=character_section,
                    worldview=worldview_section,
                    mode=mode,
                )

            if self._estimate_tokens(final_context) > target_tokens:
                final_context = self._shrink_text_to_token_budget(final_context, target_tokens)

            section_strategies = {
                "outline": outline_strategy,
                "characters": character_strategy,
                "worldview": worldview_strategy,
            }

            logger.debug("📋 上下文整形完成:")
            logger.debug(f"   - 大纲策略: {outline_strategy}")
            logger.debug(f"   - 人物策略: {character_strategy}")
            logger.debug(f"   - 世界观策略: {worldview_strategy}")
            logger.debug(f"   - 结构化记忆tokens: {memory_tokens:,}")
            logger.debug(f"   - 骨架tokens: {skeleton_tokens:,}")
            logger.debug(f"   - 详细片段tokens: {detail_tokens:,}\n")

        final_tokens = self._estimate_tokens(final_context)
        effective_context_ratio = final_tokens / max(original_tokens, 1)
        token_compression_ratio = min(effective_context_ratio, 1.0)
        char_compression_ratio = len(final_context) / max(len(outline) + len(characters) + len(worldview), 1)

        logger.debug("✅ 上下文准备完成:")
        logger.debug(f"   - 最终tokens: {final_tokens:,} / {target_tokens:,}")
        logger.debug(f"   - token上下文比: {effective_context_ratio * 100:.1f}%")
        logger.debug(f"   - token压缩比(兼容口径): {token_compression_ratio * 100:.1f}%")
        logger.debug(f"   - 字符压缩比: {char_compression_ratio * 100:.1f}%")
        logger.debug(f"{'=' * 70}\n")

        if project_id is not None:
            self.structured_memory_store.save(
                project_id=project_id,
                structured_memory=structured_memory,
                memory_text=memory_text,
                metadata={
                    "scenario": scenario,
                    "selected_model": selected_model,
                    "mode": mode,
                    "current_count": current_count,
                },
            )

        return {
            "context": final_context,
            "selected_model": selected_model,
            "memory_text": memory_text,
            "structured_memory": structured_memory,
            "stats": {
                "mode": mode,
                "model_limit_tokens": model_limit,
                "original_tokens": original_tokens,
                "memory_tokens": memory_tokens,
                "skeleton_tokens": skeleton_tokens,
                "detail_tokens": detail_tokens,
                "total_tokens": final_tokens,
                "target_tokens": target_tokens,
                "compression_ratio": token_compression_ratio,
                "effective_context_ratio": effective_context_ratio,
                "char_compression_ratio": char_compression_ratio,
                "section_strategies": section_strategies,
            },
        }

    @classmethod
    def estimate_selected_model_and_ratio(cls, scenario: str, current_count: int) -> Tuple[str, float]:
        """基于场景和规模预估最终任务使用的模型和安全上下文比例"""
        try:
            normalized_count = max(0, int(current_count or 0))
        except Exception:
            normalized_count = 0

        rules = cls.MODEL_SELECTION_RULES.get(scenario, cls.MODEL_SELECTION_RULES["outline_expand"])

        for (min_count, max_count), (model, ratio) in rules:
            if min_count <= normalized_count < max_count:
                normalized_model = normalize_model_id(model) or model
                return normalized_model, ratio

        return normalize_model_id("qwen3.5-plus") or "qwen3.5-plus", 0.30

    @classmethod
    def estimate_selected_model(cls, scenario: str, current_count: int) -> str:
        """仅返回最终任务的预估模型，用于分析/计划阶段对齐执行选模逻辑"""
        model, _ = cls.estimate_selected_model_and_ratio(scenario, current_count)
        return model

    def _select_model(self, scenario: str, current_count: int) -> Tuple[str, float]:
        """根据场景和规模智能选择模型"""
        return self.estimate_selected_model_and_ratio(scenario, current_count)

    def _get_model_limit(self, model_id: str) -> int:
        """从统一模型注册中心读取模型上下文限制"""
        ensure_model_hub_initialized()
        normalized_model = normalize_model_id(model_id) or model_id

        try:
            from core.model_hub import model_hub

            spec = model_hub.registry.get_spec(normalized_model)
            if spec and spec.constraints and spec.constraints.max_context_tokens:
                return int(spec.constraints.max_context_tokens)
        except Exception as exc:
            logger.debug(f"⚠️  读取模型配置失败: {exc}，回退到默认上限 {self.DEFAULT_MODEL_LIMIT}")

        return self.DEFAULT_MODEL_LIMIT

    def _get_safe_input_budget(
        self,
        model_id: str,
        usage_ratio: float = 0.72,
        reserve_output_tokens: int = 1200,
    ) -> int:
        """计算某个模型在摘要任务中较安全的输入预算"""
        limit = self._get_model_limit(model_id)
        return max(1500, int(limit * usage_ratio) - reserve_output_tokens)

    def _select_preparation_mode(self, total_tokens: int, target_tokens: int, model_limit: int) -> str:
        """根据实际输入规模决定上下文处理模式"""
        if total_tokens <= target_tokens:
            return "pass_through"

        if total_tokens <= max(target_tokens * 3, model_limit):
            return "shape_context"

        return "map_reduce"

    def _allocate_section_budgets(self, scenario: str, target_tokens: int) -> Dict[str, int]:
        """为各个上下文区块分配预算"""
        weights = self.SECTION_WEIGHTS.get(scenario, self.SECTION_WEIGHTS["outline_expand"])
        return {
            key: max(0, int(target_tokens * weight))
            for key, weight in weights.items()
        }

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数量"""
        if not text:
            return 0

        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(text)
        en_chars = total_chars - cn_chars

        cn_tokens = cn_chars / 1.5
        en_tokens = en_chars / 4.0

        return int(cn_tokens + en_tokens)

    def _tokens_to_chars(self, token_count: int) -> int:
        """粗略把 token 预算换算成字符预算"""
        return max(200, int(token_count * 1.6))

    def _shape_section(
        self,
        content: str,
        content_type: str,
        budget_tokens: int,
        mode: str,
    ) -> Tuple[str, str]:
        """根据预算和模式决定某个区块是保留原文还是摘要"""
        if not content.strip():
            return "", "empty"

        content_tokens = self._estimate_tokens(content)
        if budget_tokens <= 0:
            shrunk = self._shrink_text_to_token_budget(content, 0)
            return shrunk, "trimmed"

        if content_tokens <= budget_tokens:
            return content, "raw"

        force_map_reduce = mode == "map_reduce"
        skeleton = self._generate_skeleton(
            content=content,
            content_type=content_type,
            target_tokens=budget_tokens,
            force_map_reduce=force_map_reduce,
        )
        strategy = "map_reduce" if force_map_reduce or self._estimate_tokens(content) > self._get_safe_input_budget(self.CHUNK_SUMMARY_MODEL) else "skeleton"
        return skeleton, strategy

    def _generate_skeleton(
        self,
        content: str,
        content_type: str,
        target_tokens: int,
        force_map_reduce: bool = False,
    ) -> str:
        """生成结构化骨架"""
        if not content:
            return ""

        if len(content) < 500:
            return self._shrink_text_to_token_budget(content, target_tokens)

        content_tokens = self._estimate_tokens(content)
        safe_input_budget = self._get_safe_input_budget(self.CHUNK_SUMMARY_MODEL)

        if force_map_reduce or content_tokens > safe_input_budget:
            return self._generate_skeleton_map_reduce(content, content_type, target_tokens)

        return self._generate_skeleton_once(
            content=content,
            content_type=content_type,
            target_tokens=target_tokens,
            model_id=self.CHUNK_SUMMARY_MODEL,
        )

    def _generate_skeleton_once(
        self,
        content: str,
        content_type: str,
        target_tokens: int,
        model_id: Optional[str] = None,
    ) -> str:
        """单次摘要调用"""
        model_name = normalize_model_id(model_id) or self.CHUNK_SUMMARY_MODEL
        target_chars = self._tokens_to_chars(target_tokens)
        prompt = self._build_skeleton_prompt(content=content, content_type=content_type, target_chars=target_chars)

        try:
            llm = self._get_llm(model_name, task_type="summarize", temperature=0.2, max_tokens=min(2000, max(512, target_tokens)))
            response = llm.invoke(
                [
                    SystemMessage(content="你是专业的长篇小说上下文整理器，擅长保留结构、约束与关键状态。"),
                    HumanMessage(content=prompt),
                ]
            )
            skeleton = str(response.content).strip()
            return self._shrink_text_to_token_budget(skeleton, target_tokens)
        except Exception as exc:
            logger.debug(f"⚠️  骨架生成失败: {exc}，回退到规则截断")
            return self._rule_based_truncate(content, target_chars)

    def _generate_skeleton_map_reduce(self, content: str, content_type: str, target_tokens: int) -> str:
        """对超大文本执行 map-reduce 摘要"""
        chunk_budget = max(1200, min(4500, self._get_safe_input_budget(self.CHUNK_SUMMARY_MODEL)))
        chunks = self._split_text_by_tokens(content, chunk_budget)
        if not chunks:
            return self._rule_based_truncate(content, self._tokens_to_chars(target_tokens))

        per_chunk_tokens = max(180, min(900, int(target_tokens / max(len(chunks), 1)) + 120))
        partial_summaries: List[str] = []

        for index, chunk in enumerate(chunks, start=1):
            partial = self._generate_skeleton_once(
                content=chunk,
                content_type=content_type,
                target_tokens=per_chunk_tokens,
                model_id=self.CHUNK_SUMMARY_MODEL,
            )
            partial_summaries.append(f"【分片{index}】\n{partial}")

        combined_summary = "\n\n".join(partial_summaries)
        if self._estimate_tokens(combined_summary) <= target_tokens:
            return combined_summary

        reduce_model = self.REDUCE_SUMMARY_MODEL
        reduce_safe_budget = self._get_safe_input_budget(reduce_model, usage_ratio=0.55, reserve_output_tokens=1500)

        if self._estimate_tokens(combined_summary) > reduce_safe_budget:
            combined_summary = self._rule_based_truncate(combined_summary, self._tokens_to_chars(reduce_safe_budget))

        try:
            reduce_prompt = f"""以下是同一份长文本的分块摘要，请整合为统一骨架。

要求:
1. 去重合并重复信息
2. 保留结构、人物状态、冲突链、世界规则
3. 尽量按条目输出，便于后续生成阶段引用
4. 控制在{self._tokens_to_chars(target_tokens)}字符以内

【分块摘要】
{combined_summary}
"""
            llm = self._get_llm(reduce_model, task_type="summarize", temperature=0.2, max_tokens=min(2500, max(800, target_tokens)))
            response = llm.invoke(
                [
                    SystemMessage(content="你是专业的长篇小说整书级摘要器，擅长整合多段摘要并保持逻辑一致。"),
                    HumanMessage(content=reduce_prompt),
                ]
            )
            reduced = str(response.content).strip()
            return self._shrink_text_to_token_budget(reduced, target_tokens)
        except Exception as exc:
            logger.debug(f"⚠️  map-reduce 汇总失败: {exc}，回退到规则截断")
            return self._rule_based_truncate(combined_summary, self._tokens_to_chars(target_tokens))

    def _build_skeleton_prompt(self, content: str, content_type: str, target_chars: int) -> str:
        """构建不同内容类型的骨架摘要提示词"""
        prompts = {
            "outline": f"""
请将以下大纲整理为结构化骨架，仅保留:
1. 篇章/卷结构
2. 核心冲突链
3. 关键转折点（尽量保留章节号）
4. 已铺设但尚未回收的重要伏笔
5. 当前仍生效的硬约束

【原始大纲】
{content}

【输出要求】
- 尽量使用分段或条目
- 只保留决策所需信息，删除修辞性描述
- 控制在{target_chars}字符以内
""",
            "character": f"""
请将以下人物设定整理为关系图谱，仅保留:
1. 角色姓名/阵营/定位
2. 核心能力或核心特质
3. 与主角或主线的关键关系
4. 已发生的重要状态变化
5. 仍未解决的人物矛盾

【原始人物】
{content}

【输出要求】
- 优先保留角色之间的关系边
- 删除冗长背景和外貌描写
- 控制在{target_chars}字符以内
""",
            "worldview": f"""
请将以下世界观提炼为可执行约束，仅保留:
1. 力量/规则体系
2. 影响剧情推进的硬性限制
3. 关键势力格局
4. 已被剧情调用过的重要设定

【原始世界观】
{content}

【输出要求】
- 优先保留会影响剧情一致性的规则
- 删除纯背景性铺陈
- 控制在{target_chars}字符以内
""",
        }
        return prompts.get(content_type, prompts["outline"])

    def _get_llm(
        self,
        model_id: str,
        task_type: str = "summarize",
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """按模型缓存 LangChain LLM 包装器"""
        normalized_model = normalize_model_id(model_id) or model_id
        cache_key = (normalized_model, task_type, temperature, max_tokens)

        if cache_key not in self._llm_cache:
            self._llm_cache[cache_key] = create_task_llm(
                task_type=task_type,
                model=normalized_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return self._llm_cache[cache_key]

    def _rule_based_truncate(self, content: str, target_length: int) -> str:
        """规则截断 - 优先保留章节、星级和条目结构"""
        if not content:
            return ""

        paragraphs = [paragraph for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
        priority_groups = {5: [], 4: [], 3: [], 2: [], 1: [], 0: []}

        for para in paragraphs:
            stars = para.count("⭐")
            chapter_bonus = 1 if re.search(r"第\s*\d+\s*[章节回卷幕]", para) else 0
            bullet_bonus = 1 if para.lstrip().startswith(("-", "1.", "2.", "3.", "4.", "5.")) else 0
            score = min(stars + chapter_bonus + bullet_bonus, 5)
            priority_groups[score].append(para)

        result: List[str] = []
        current_length = 0

        for score in [5, 4, 3, 2, 1, 0]:
            for para in priority_groups[score]:
                if current_length + len(para) + 2 <= target_length:
                    result.append(para)
                    current_length += len(para) + 2
                elif not result:
                    result.append(para[:target_length])
                    current_length = target_length
                    break
            if current_length >= target_length:
                break

        return "\n\n".join(result)

    def _split_text_by_tokens(self, text: str, max_tokens: int) -> List[str]:
        """按 token 预算切分文本，优先保持段落完整"""
        if not text.strip():
            return []

        if self._estimate_tokens(text) <= max_tokens:
            return [text]

        units = [unit for unit in re.split(r"\n\s*\n", text) if unit.strip()]
        if not units:
            units = [text]

        chunks: List[str] = []
        current: List[str] = []
        current_tokens = 0

        for unit in units:
            unit_tokens = self._estimate_tokens(unit)

            if unit_tokens > max_tokens:
                oversized_parts = self._split_oversized_unit(unit, max_tokens)
                for part in oversized_parts:
                    part_tokens = self._estimate_tokens(part)
                    if current and current_tokens + part_tokens > max_tokens:
                        chunks.append("\n\n".join(current))
                        current = []
                        current_tokens = 0
                    current.append(part)
                    current_tokens += part_tokens
                continue

            if current and current_tokens + unit_tokens > max_tokens:
                chunks.append("\n\n".join(current))
                current = [unit]
                current_tokens = unit_tokens
            else:
                current.append(unit)
                current_tokens += unit_tokens

        if current:
            chunks.append("\n\n".join(current))

        return [chunk for chunk in chunks if chunk.strip()]

    def _split_oversized_unit(self, text: str, max_tokens: int) -> List[str]:
        """切分超长段落，按行/句子逐级退化"""
        line_parts = [line for line in text.splitlines() if line.strip()]
        if len(line_parts) > 1:
            return self._split_text_by_tokens("\n\n".join(line_parts), max_tokens)

        sentence_parts = [part for part in re.split(r"(?<=[。！？.!?；;])", text) if part.strip()]
        if len(sentence_parts) <= 1:
            approx_chars = self._tokens_to_chars(max_tokens)
            return [text[i:i + approx_chars] for i in range(0, len(text), approx_chars)]

        chunks: List[str] = []
        current = ""
        for part in sentence_parts:
            candidate = f"{current}{part}"
            if current and self._estimate_tokens(candidate) > max_tokens:
                chunks.append(current)
                current = part
            else:
                current = candidate

        if current:
            chunks.append(current)

        return chunks

    def _add_detailed_sections(
        self,
        outline: str,
        characters: str,
        current_count: int,
        available_tokens: int,
        focus_range: Optional[Tuple[int, int]] = None,
    ) -> str:
        """补充局部详细片段 - 优先保留当前创作窗口附近的原文块"""
        if available_tokens <= 0 or not outline.strip():
            return ""

        if focus_range:
            target_range = focus_range
        else:
            target_range = (max(1, current_count - 10), current_count + 10)

        logger.debug(f"🔍 聚焦范围: 第{target_range[0]}-{target_range[1]}章")

        if self.knowledge_base:
            rag_text = self._rag_retrieve_relevant(target_range=target_range, available_tokens=available_tokens)
            if rag_text.strip():
                return rag_text
            logger.debug("   - RAG 未返回可用内容，回退到章节块抽取")

        return self._regex_extract_range(outline=outline, target_range=target_range, available_tokens=available_tokens)

    def _rag_retrieve_relevant(self, target_range: Tuple[int, int], available_tokens: int) -> str:
        """RAG 检索相关章节"""
        try:
            query = f"第{target_range[0]}章到第{target_range[1]}章的情节内容"
            k = min(20, max(1, int(available_tokens / 500)))
            results = self.knowledge_base.search(query, k=k)

            if not results:
                logger.debug("   - RAG 检索结果为空")
                return ""

            relevant_docs: List[str] = []
            total_chars = 0
            max_chars = self._tokens_to_chars(available_tokens)

            for doc in results:
                content = getattr(doc, "page_content", "") or ""
                if not content.strip():
                    continue
                if total_chars + len(content) <= max_chars:
                    relevant_docs.append(content)
                    total_chars += len(content)
                elif not relevant_docs:
                    relevant_docs.append(content[:max_chars])
                    total_chars = max_chars
                    break
                else:
                    break

            logger.debug(f"   - RAG检索: {len(relevant_docs)}篇文档, {total_chars:,}字符")
            return "\n\n".join(relevant_docs)
        except Exception as exc:
            logger.debug(f"⚠️  RAG检索失败: {exc}，回退到章节块抽取")
            return ""

    def _regex_extract_range(
        self,
        outline: str,
        target_range: Tuple[int, int],
        available_tokens: int,
    ) -> str:
        """从大纲中提取指定章节范围的完整章节块"""
        blocks = self._extract_chapter_blocks(outline)
        if not blocks:
            logger.debug("   - 未识别到结构化章节，回退到窗口截断")
            return self._shrink_text_to_token_budget(outline, available_tokens)

        start, end = target_range
        center = (start + end) / 2
        selected_blocks = [block for block in blocks if start <= block["number"] <= end]
        if not selected_blocks:
            selected_blocks = sorted(blocks, key=lambda block: abs(block["number"] - center))[: min(6, len(blocks))]
            selected_blocks = sorted(selected_blocks, key=lambda block: block["number"])

        max_chars = self._tokens_to_chars(available_tokens)
        while selected_blocks:
            candidate = "\n\n".join(block["text"] for block in selected_blocks)
            if len(candidate) <= max_chars:
                logger.debug(f"   - 章节块提取: {len(selected_blocks)}章, {len(candidate):,}字符")
                return candidate

            if len(selected_blocks) == 1:
                trimmed = self._shrink_text_to_token_budget(selected_blocks[0]["text"], available_tokens)
                logger.debug(f"   - 单章过长，截断后返回: {len(trimmed):,}字符")
                return trimmed

            left_distance = abs(selected_blocks[0]["number"] - center)
            right_distance = abs(selected_blocks[-1]["number"] - center)
            if left_distance >= right_distance:
                selected_blocks.pop(0)
            else:
                selected_blocks.pop()

        return ""

    def _extract_chapter_blocks(self, outline: str) -> List[Dict[str, Any]]:
        """抽取大纲中的章节块，而不仅仅是章节标题行"""
        if not outline.strip():
            return []

        blocks: List[Dict[str, Any]] = []
        current_number: Optional[int] = None
        current_lines: List[str] = []

        for line in outline.splitlines():
            chapter_number = self._match_chapter_heading(line)
            if chapter_number is not None:
                if current_number is not None and current_lines:
                    text = "\n".join(current_lines).strip()
                    blocks.append({"number": current_number, "text": text})
                current_number = chapter_number
                current_lines = [line]
            elif current_number is not None:
                current_lines.append(line)

        if current_number is not None and current_lines:
            text = "\n".join(current_lines).strip()
            blocks.append({"number": current_number, "text": text})

        return blocks

    def _match_chapter_heading(self, line: str) -> Optional[int]:
        """识别章节标题行并返回章节号"""
        patterns = [
            r"^\s*(?:#+\s*)?第\s*([0-9一二三四五六七八九十百千万零两〇]+)\s*[章节回卷幕集]\b",
            r"^\s*Chapter\s+(\d+)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                return self._parse_chapter_number(match.group(1))

        return None

    def _parse_chapter_number(self, raw: str) -> int:
        """解析阿拉伯数字或常见中文数字"""
        text = (raw or "").strip()
        if text.isdigit():
            return int(text)

        digit_map = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

        total = 0
        current = 0
        for char in text:
            if char in digit_map:
                current = digit_map[char]
            elif char in unit_map:
                unit = unit_map[char]
                if current == 0:
                    current = 1
                total += current * unit
                current = 0

        total += current
        return total

    def _shrink_text_to_token_budget(self, text: str, target_tokens: int) -> str:
        """把文本压到给定 token 预算以内"""
        if not text or target_tokens <= 0:
            return ""

        if self._estimate_tokens(text) <= target_tokens:
            return text

        target_chars = self._tokens_to_chars(target_tokens)
        return self._rule_based_truncate(text, target_chars)

    def _build_structured_memory(
        self,
        outline: str,
        characters: str,
        worldview: str,
        detail_content: str,
        focus_range: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, List[str]]:
        """构建结构化记忆，用于后续生成阶段稳定引用"""
        character_names = [item["name"] for item in self._extract_character_states(characters)]

        memory = {
            "global_story_arcs": self._extract_story_arcs(outline, focus_range=focus_range),
            "character_states": [
                self._format_character_state(item)
                for item in self._extract_character_states(characters)
            ],
            "relationship_edges": self._extract_relationship_edges(
                outline=outline,
                characters=characters,
                detail_content=detail_content,
                character_names=character_names,
            ),
            "pending_foreshadowings": self._extract_pending_foreshadowings(outline, detail_content),
            "world_rules_hard_constraints": self._extract_world_rules(worldview, outline),
        }

        return {
            key: self._deduplicate_preserve_order(values)
            for key, values in memory.items()
            if values
        }

    def _extract_story_arcs(self, outline: str, focus_range: Optional[Tuple[int, int]] = None) -> List[str]:
        """抽取主线弧线和关键章节状态"""
        if not outline.strip():
            return []

        chapter_blocks = self._extract_chapter_blocks(outline)
        items: List[str] = []

        if chapter_blocks:
            selected_blocks: List[Dict[str, Any]] = []
            if focus_range:
                start, end = focus_range
                selected_blocks.extend([block for block in chapter_blocks if start <= block["number"] <= end][:4])

            selected_blocks.extend(chapter_blocks[:2])
            if len(chapter_blocks) > 2:
                selected_blocks.extend(chapter_blocks[-2:])

            seen_numbers = set()
            for block in selected_blocks:
                if block["number"] in seen_numbers:
                    continue
                seen_numbers.add(block["number"])
                summary = self._summarize_chapter_block(block["text"])
                if summary:
                    items.append(summary)

        keywords = ("主线", "支线", "卷", "篇", "高潮", "转折", "目标", "冲突", "危机", "结局", "线索")
        for line in outline.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(keyword in stripped for keyword in keywords):
                items.append(self._clean_memory_line(stripped, max_length=110))

        return items[:8]

    def _extract_character_states(self, characters: str) -> List[Dict[str, str]]:
        """抽取角色当前状态"""
        if not characters.strip():
            return []

        sections: List[str] = []
        if "###" in characters:
            sections = [section.strip() for section in re.split(r"\n(?=###\s*)", characters) if section.strip()]
        elif "【姓名】" in characters:
            sections = [section.strip() for section in re.split(r"\n(?=【姓名】)", characters) if section.strip()]
        else:
            sections = [characters]

        results: List[Dict[str, str]] = []
        seen_names = set()

        for section in sections:
            name = self._extract_character_name_from_section(section)
            if not name or name in seen_names:
                continue

            seen_names.add(name)
            role = self._extract_field_value(section, ["角色定位", "定位", "阵营", "身份"])
            ability = self._extract_field_value(section, ["核心能力", "能力", "特长", "修为", "当前等级", "当前修为"])
            trait = self._extract_field_value(section, ["性格特点", "核心特质", "性格"])
            motivation = self._extract_field_value(section, ["核心动机", "动机"])

            results.append(
                {
                    "name": name,
                    "role": role or "",
                    "ability": ability or "",
                    "trait": trait or "",
                    "motivation": motivation or "",
                }
            )

        return results[:10]

    def _extract_relationship_edges(
        self,
        outline: str,
        characters: str,
        detail_content: str,
        character_names: List[str],
    ) -> List[str]:
        """抽取显式关系和基于同章共现的弱关系"""
        items: List[str] = []
        relationship_keywords = ("关系", "盟友", "敌对", "宿敌", "师徒", "亲人", "同伴", "合作", "背叛")

        for line in characters.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(symbol in stripped for symbol in ("↔", "⇄", "->", "→", "←", "—")) or any(keyword in stripped for keyword in relationship_keywords):
                if any(name in stripped for name in character_names):
                    items.append(self._clean_memory_line(stripped, max_length=110))

        source_text = detail_content or outline
        for block in self._extract_chapter_blocks(source_text):
            text = block["text"]
            mentioned = [name for name in character_names if name in text]
            unique_mentioned = list(dict.fromkeys(mentioned))
            if len(unique_mentioned) >= 2:
                pair = f"{unique_mentioned[0]} <-> {unique_mentioned[1]}：第{block['number']}章同场推进"
                items.append(pair)

        return items[:8]

    def _extract_pending_foreshadowings(self, outline: str, detail_content: str) -> List[str]:
        """抽取待回收的伏笔和钩子"""
        items: List[str] = []
        keywords = ("伏笔", "悬念", "秘密", "线索", "真相", "钩子", "埋设", "回收", "谜团", "暗示")

        for source in [detail_content, outline]:
            if not source.strip():
                continue
            for line in source.splitlines():
                stripped = line.strip()
                if stripped and any(keyword in stripped for keyword in keywords):
                    items.append(self._clean_memory_line(stripped, max_length=110))

        return items[:8]

    def _extract_world_rules(self, worldview: str, outline: str) -> List[str]:
        """抽取世界规则硬约束"""
        items: List[str] = []
        keywords = ("规则", "限制", "禁忌", "必须", "不能", "不可", "代价", "副作用", "条件", "上限", "边界", "约束")

        for source in [worldview, outline]:
            if not source.strip():
                continue
            for line in source.splitlines():
                stripped = line.strip()
                if stripped and any(keyword in stripped for keyword in keywords):
                    items.append(self._clean_memory_line(stripped, max_length=110))

        return items[:8]

    def _format_character_state(self, item: Dict[str, str]) -> str:
        """把人物状态字典压成稳定的一行文本"""
        fragments = [item["name"]]
        if item.get("role"):
            fragments.append(f"定位={item['role']}")
        if item.get("ability"):
            fragments.append(f"能力/状态={item['ability']}")
        elif item.get("trait"):
            fragments.append(f"特质={item['trait']}")
        if item.get("motivation"):
            fragments.append(f"动机={item['motivation']}")

        return "；".join(fragments)

    def _extract_character_name_from_section(self, section: str) -> str:
        """从人物小节里提取姓名"""
        patterns = [
            r"【姓名】[:：]\s*([^\n【】]+)",
            r"###\s*【姓名】[:：]?\s*([^\n【】]+)",
            r"-\s*([^\s:：]+)\s*[:：]\s*(?:主角|反派|配角|盟友|导师|对手)",
        ]
        for pattern in patterns:
            match = re.search(pattern, section)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_field_value(self, section: str, field_names: List[str]) -> str:
        """按字段名提取人物属性"""
        for field_name in field_names:
            match = re.search(rf"[【\[]?{re.escape(field_name)}[】\]]?[:：]\s*([^\n]+)", section)
            if match:
                return match.group(1).strip()
        return ""

    def _summarize_chapter_block(self, block_text: str) -> str:
        """把章节块压成一条可索引记忆"""
        lines = [line.strip() for line in block_text.splitlines() if line.strip()]
        if not lines:
            return ""

        heading = lines[0]
        details: List[str] = []
        preferred_keywords = (
            "场景目标",
            "冲突设计",
            "关键事件",
            "人物推进",
            "情节作用",
            "信息落地",
            "结尾钩子",
            "伏笔事项",
            "线索",
        )

        for line in lines[1:]:
            if any(keyword in line for keyword in preferred_keywords):
                cleaned = re.sub(r"^[\-*•\d.]+\s*", "", line).strip()
                details.append(cleaned)
            if len(details) >= 2:
                break

        if not details and len(lines) > 1:
            details.append(re.sub(r"^[\-*•\d.]+\s*", "", lines[1]).strip())

        combined = f"{heading}：{'；'.join(details)}" if details else heading
        return self._clean_memory_line(combined, max_length=120)

    def _clean_memory_line(self, text: str, max_length: int = 120) -> str:
        """清洗结构化记忆行，去掉多余符号和空白"""
        cleaned = re.sub(r"\s+", " ", text or "").strip(" -•\t")
        if len(cleaned) > max_length:
            return cleaned[: max_length - 3].rstrip() + "..."
        return cleaned

    def _deduplicate_preserve_order(self, values: List[str]) -> List[str]:
        """保持顺序去重"""
        result: List[str] = []
        seen = set()
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _render_structured_memory(self, structured_memory: Dict[str, List[str]], budget_tokens: int) -> str:
        """把结构化记忆渲染成可供模型直接消费的文本"""
        if budget_tokens <= 0 or not structured_memory:
            return ""

        category_labels = [
            ("global_story_arcs", "主线弧线"),
            ("character_states", "人物状态"),
            ("relationship_edges", "关系边"),
            ("pending_foreshadowings", "待回收伏笔"),
            ("world_rules_hard_constraints", "世界规则硬约束"),
        ]

        trimmed_memory = {
            key: list(values)
            for key, values in structured_memory.items()
            if values
        }

        while True:
            rendered = self._render_memory_text(trimmed_memory, category_labels)
            if self._estimate_tokens(rendered) <= budget_tokens:
                return rendered

            reducible_key = self._pick_reducible_memory_key(trimmed_memory, category_labels)
            if not reducible_key:
                return self._shrink_text_to_token_budget(rendered, budget_tokens)

            trimmed_memory[reducible_key].pop()
            if not trimmed_memory[reducible_key]:
                trimmed_memory.pop(reducible_key, None)

    def _render_memory_text(
        self,
        structured_memory: Dict[str, List[str]],
        category_labels: List[Tuple[str, str]],
    ) -> str:
        """渲染结构化记忆文本"""
        parts: List[str] = ["【结构化记忆】"]

        for key, label in category_labels:
            values = structured_memory.get(key) or []
            if not values:
                continue
            parts.append(f"- {label}:")
            for value in values:
                parts.append(f"  - {value}")

        return "\n".join(parts).strip()

    def _pick_reducible_memory_key(
        self,
        structured_memory: Dict[str, List[str]],
        category_labels: List[Tuple[str, str]],
    ) -> str:
        """选择一个最适合裁剪的记忆类别"""
        candidate_items = [
            (key, len(structured_memory.get(key) or []))
            for key, _ in category_labels
            if structured_memory.get(key)
        ]
        if not candidate_items:
            return ""

        candidate_items.sort(key=lambda item: item[1], reverse=True)
        return candidate_items[0][0]

    def _assemble_context(
        self,
        outline: str,
        memory_text: str,
        detail_content: str,
        characters: str,
        worldview: str,
        mode: str,
    ) -> str:
        """统一组装上下文，保持返回结构兼容"""
        parts: List[str] = []

        if outline.strip():
            parts.append("【故事大纲】")
            parts.append(outline.strip())

        if memory_text.strip():
            parts.append(memory_text.strip())

        if detail_content.strip():
            parts.append("【局部原文片段】")
            parts.append(detail_content.strip())

        if characters.strip():
            parts.append("【人物体系】")
            parts.append(characters.strip())

        if worldview.strip():
            parts.append("【世界观】")
            parts.append(worldview.strip())

        if mode != "pass_through":
            parts.append("---")
            parts.append(f"上下文模式: {mode}")

        return "\n\n".join(parts).strip()


def prepare_smart_context(
    outline: str = "",
    characters: str = "",
    worldview: str = "",
    scenario: str = "outline_expand",
    current_count: int = 50,
    focus_range: Optional[Tuple[int, int]] = None,
    knowledge_base: Optional[NovelKnowledgeBase] = None,
    project_id: Optional[int] = None,
) -> Dict[str, Any]:
    """便捷函数: 智能准备上下文"""
    summarizer = LayeredSummarizer(knowledge_base)
    return summarizer.prepare_context_for_expansion(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario=scenario,
        current_count=current_count,
        focus_range=focus_range,
        project_id=project_id,
    )
