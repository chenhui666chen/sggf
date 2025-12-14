"""
分层摘要策略 - 混合骨架提取+详细片段+智能模型选择

核心策略:
1. AI生成内容骨架 (10%压缩率)
2. RAG检索相关详细片段 (30%空间)
3. 根据章节数智能选择模型
4. 确保总输入不超过模型限制
"""
import os
from typing import Dict, Any, Optional, Tuple, List
import re
from langchain_core.messages import SystemMessage, HumanMessage

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]

from .llm_singleton import create_deepseek_llm
from .knowledge_base import NovelKnowledgeBase


class LayeredSummarizer:
    """分层摘要器 - 既保证精准又控制成本"""
    
    # 各模型的Token限制
    MODEL_LIMITS = {
        'qwen-max': 30720,
        'qwen-plus': 1000000,
        'qwen-turbo': 1000000,
        'qwen-long': 10000000,
        'deepseek-r1': 128000,
    }
    
    # 智能模型选择策略
    MODEL_SELECTION_RULES = {
        'outline_expand': {  # 大纲扩展场景
            (0, 30): ('qwen-max', 0.85),      # 0-30章: qwen-max, 文笔最好
            (30, 80): ('qwen-plus', 0.60),    # 30-80章: qwen-plus, 性价比
            (80, 999): ('qwen-long', 0.30),   # 80+章: qwen-long, 超长输入
        },
        'character_expand': {  # 人物扩展场景
            (0, 20): ('deepseek-r1', 0.80),   # 0-20人: R1推理
            (20, 50): ('qwen-plus', 0.60),    # 20-50人: qwen-plus
            (50, 999): ('qwen-long', 0.30),   # 50+人: qwen-long
        },
        'chapter_generation': {  # 章节生成场景
            (0, 20): ('qwen-max', 0.85),      # 0-20章: qwen-max
            (20, 50): ('qwen-long', 0.40),    # 20-50章: qwen-long
            (50, 999): ('qwen-long', 0.20),   # 50+章: qwen-long宽松
        },
        'structure_design': {  # 结构设计场景
            (0, 50): ('deepseek-r1', 0.80),   # 0-50章: R1推理(结构设计需要严谨逻辑)
            (50, 150): ('qwen-long', 0.40),   # 50-150章: qwen-long(大规模结构)
            (150, 999): ('qwen-long', 0.25),  # 150+章: qwen-long宽松
        }
    }
    
    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None):
        """初始化分层摘要器
        
        Args:
            knowledge_base: 知识库实例(用于RAG检索)
        """
        self.knowledge_base = knowledge_base
        # 使用qwen-turbo做骨架提取(成本低、速度快)
        self.skeleton_llm = create_deepseek_llm(task_type="summarize")
    
    def prepare_context_for_expansion(
        self,
        outline: str,
        characters: str,
        worldview: str,
        scenario: str = "outline_expand",  # outline_expand/character_expand/chapter_generation/structure_design
        current_count: int = 50,  # 当前章节数/人物数
        focus_range: Optional[Tuple[int, int]] = None  # 聚焦章节范围
    ) -> dict:
        """
        为扩展任务准备优化上下文
        
        策略:
        1. 完整内容 → AI提取骨架 (10%)
        2. 骨架 + 关键片段详情 (30%)
        3. 总输入控制在模型限制内
        
        Args:
            outline: 情节大纲
            characters: 人物设定
            worldview: 世界观设定
            scenario: 使用场景
            current_count: 当前章节数或人物数
            focus_range: 聚焦范围(用于章节生成)
            
        Returns:
            {
                "context": 优化后的上下文,
                "selected_model": 选择的模型,
                "stats": 统计信息
            }
        """
        
        print(f"\n{'='*70}")
        print(f"【分层摘要器】开始处理 {scenario}")
        print(f"   当前规模: {current_count} {'章' if 'chapter' in scenario or 'outline' in scenario else '人'}")
        print(f"{'='*70}\n")
        
        # 第一步: 智能选择模型
        selected_model, target_ratio = self._select_model(scenario, current_count)
        target_tokens = int(self.MODEL_LIMITS[selected_model] * target_ratio)
        
        print(f"📊 模型选择:")
        print(f"   - 选择模型: {selected_model}")
        print(f"   - 最大tokens: {self.MODEL_LIMITS[selected_model]:,}")
        print(f"   - 目标tokens: {target_tokens:,} ({target_ratio*100:.0f}%使用率)\n")
        
        # 第二步: 生成内容骨架 (AI摘要)
        outline_skeleton = self._generate_skeleton(outline, "outline") if outline else ""
        character_skeleton = self._generate_skeleton(characters, "character") if characters else ""
        worldview_skeleton = self._generate_skeleton(worldview, "worldview") if worldview else ""
        
        # 第三步: 计算骨架消耗
        skeleton_content = f"""
【故事骨架】
{outline_skeleton}

【人物体系】
{character_skeleton}

【世界观】
{worldview_skeleton}
"""
        skeleton_tokens = self._estimate_tokens(skeleton_content)
        
        print(f"📋 骨架生成完成:")
        print(f"   - 大纲: {len(outline):,}字 → {len(outline_skeleton):,}字 (压缩{(1-len(outline_skeleton)/max(len(outline),1))*100:.1f}%)")
        print(f"   - 人物: {len(characters):,}字 → {len(character_skeleton):,}字 (压缩{(1-len(character_skeleton)/max(len(characters),1))*100:.1f}%)")
        print(f"   - 世界观: {len(worldview):,}字 → {len(worldview_skeleton):,}字 (压缩{(1-len(worldview_skeleton)/max(len(worldview),1))*100:.1f}%)")
        print(f"   - 骨架总tokens: {skeleton_tokens:,}\n")
        
        # 第四步: 计算剩余空间，补充详细内容
        remaining_tokens = target_tokens - skeleton_tokens
        
        if remaining_tokens > 0:
            detailed_content = self._add_detailed_sections(
                outline=outline,
                characters=characters,
                current_count=current_count,
                available_tokens=remaining_tokens,
                focus_range=focus_range
            )
            detail_tokens = self._estimate_tokens(detailed_content)
            print(f"📝 详细片段补充:")
            print(f"   - 可用空间: {remaining_tokens:,} tokens")
            print(f"   - 实际使用: {detail_tokens:,} tokens\n")
        else:
            detailed_content = ""
            print(f"⚠️  骨架已用满预算，跳过详细片段\n")
        
        # 第五步: 组装最终上下文
        final_context = f"""
【故事骨架】
{outline_skeleton}

【近期详细内容】
{detailed_content}

【人物体系】
{character_skeleton}

【世界观】
{worldview_skeleton}

---
💡 提示: 以上内容为智能优化后的上下文，已保留所有关键信息
- 骨架: 覆盖全书结构和转折点
- 详细: 聚焦当前创作范围
"""
        
        final_tokens = self._estimate_tokens(final_context)
        
        print(f"✅ 上下文准备完成:")
        print(f"   - 最终tokens: {final_tokens:,} / {target_tokens:,} ({final_tokens/target_tokens*100:.1f}%)")
        print(f"   - 压缩比: {final_tokens/(self._estimate_tokens(outline+characters+worldview) or 1)*100:.1f}%")
        print(f"{'='*70}\n")
        
        return {
            "context": final_context,
            "selected_model": selected_model,
            "stats": {
                "skeleton_tokens": skeleton_tokens,
                "detail_tokens": self._estimate_tokens(detailed_content),
                "total_tokens": final_tokens,
                "target_tokens": target_tokens,
                "compression_ratio": final_tokens / max(len(outline) + len(characters) + len(worldview), 1)
            }
        }
    
    def _select_model(self, scenario: str, current_count: int) -> Tuple[str, float]:
        """根据场景和规模智能选择模型
        
        Args:
            scenario: 使用场景
            current_count: 当前章节数/人物数
            
        Returns:
            (model_name, target_ratio)
        """
        rules = self.MODEL_SELECTION_RULES.get(scenario, self.MODEL_SELECTION_RULES['outline_expand'])
        
        for (min_count, max_count), (model, ratio) in rules.items():
            if min_count <= current_count < max_count:
                return model, ratio
        
        # 默认返回qwen-long
        return 'qwen-long', 0.30
    
    def _estimate_tokens(self, text: str) -> int:
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
        
        # 中文约1.5字符/token，英文约4字符/token
        cn_tokens = cn_chars / 1.5
        en_tokens = en_chars / 4.0
        
        return int(cn_tokens + en_tokens)
    
    def _generate_skeleton(self, content: str, content_type: str) -> str:
        """生成内容骨架 - 10%压缩率
        
        Args:
            content: 原始内容
            content_type: 内容类型(outline/character/worldview)
            
        Returns:
            骨架摘要
        """
        
        if not content or len(content) < 500:
            return content  # 内容太短，无需压缩
        
        target_length = int(len(content) * 0.1)  # 压缩到10%
        
        # 针对不同内容类型的专用Prompt
        skeleton_prompts = {
            "outline": f"""
请将以下大纲提炼为**结构化骨架**，仅保留:
1. 卷/篇章结构划分
2. 每部分的核心冲突
3. 关键转折点(标注章节号和⭐️星级)
4. 高潮章节列表

【原始大纲】
{content}

【输出格式】
第1-20章: 起始篇 - 核心冲突: xxx
  - 第3章⭐⭐⭐⭐⭐: [关键转折简述]
  - 第18章⭐⭐⭐⭐⭐: [卷末高潮简述]
  
第21-40章: 成长篇 - 核心冲突: xxx
  ...

要求:
- 只输出骨架，删除所有细节描写
- 保留章节号和星级标记
- 控制在{target_length}字符以内
""",
            "character": f"""
请将以下人物设定提炼为**关系图谱**，格式:
- 主角: 姓名(核心能力) 
- 对手: 姓名(阵营/关系: xxx)
- 辅助: 姓名(阵营/关系: xxx)

【原始人物】
{content}

要求:
- 只保留姓名、阵营、核心特质、关键关系
- 删除详细背景、外貌、经历描写
- 控制在{target_length}字符以内
""",
            "worldview": f"""
请提炼世界观的**核心体系**:
- 力量体系: 境界1→境界2→...
- 核心规则: [最重要的2-3条规则]

【原始世界观】
{content}

要求:
- 只保留体系框架和核心规则
- 删除历史背景、地理详情
- 控制在{target_length}字符以内
"""
        }
        
        prompt = skeleton_prompts.get(content_type, skeleton_prompts["outline"])
        
        try:
            response = self.skeleton_llm.invoke([
                SystemMessage(content="你是专业的内容提取专家，擅长从长文本中提炼结构化骨架。"),
                HumanMessage(content=prompt)
            ])
            
            skeleton = response.content.strip()
            
            # 确保不超出目标长度
            if len(skeleton) > target_length * 1.2:
                skeleton = skeleton[:target_length] + "..."
            
            return skeleton
            
        except Exception as e:
            print(f"⚠️  骨架生成失败: {e}，使用规则截断")
            # 回退: 保留⭐️高优先级内容
            return self._rule_based_truncate(content, target_length)
    
    def _rule_based_truncate(self, content: str, target_length: int) -> str:
        """规则截断 - 保留⭐️高优先级内容
        
        Args:
            content: 原始内容
            target_length: 目标长度
            
        Returns:
            截断后的内容
        """
        paragraphs = content.split('\n\n')
        
        # 按星级分组
        priority_groups = {5: [], 4: [], 3: [], 2: [], 1: [], 0: []}
        for para in paragraphs:
            if not para.strip():
                continue
            stars = para.count('⭐')
            priority_groups[min(stars, 5)].append(para)
        
        # 优先保留高星级
        result = []
        current_length = 0
        
        for stars in [5, 4, 3, 2, 1, 0]:
            for para in priority_groups[stars]:
                if current_length + len(para) <= target_length:
                    result.append(para)
                    current_length += len(para)
                else:
                    break
            if current_length >= target_length:
                break
        
        return '\n\n'.join(result)
    
    def _add_detailed_sections(
        self,
        outline: str,
        characters: str,
        current_count: int,
        available_tokens: int,
        focus_range: Optional[Tuple[int, int]] = None
    ) -> str:
        """补充详细片段 - 聚焦当前创作范围
        
        Args:
            outline: 完整大纲
            characters: 完整人物设定
            current_count: 当前章节数
            available_tokens: 可用token空间
            focus_range: 聚焦章节范围
            
        Returns:
            详细片段文本
        """
        
        # 确定聚焦范围
        if focus_range:
            target_range = focus_range
        else:
            # 默认: 当前章节前后10章
            target_range = (
                max(1, current_count - 10),
                current_count + 10
            )
        
        print(f"🔍 聚焦范围: 第{target_range[0]}-{target_range[1]}章")
        
        # 方案1: 如果有知识库，使用RAG检索
        if self.knowledge_base:
            return self._rag_retrieve_relevant(
                target_range=target_range,
                available_tokens=available_tokens
            )
        
        # 方案2: 正则提取相关章节
        return self._regex_extract_range(
            outline=outline,
            target_range=target_range,
            available_tokens=available_tokens
        )
    
    def _rag_retrieve_relevant(
        self,
        target_range: Tuple[int, int],
        available_tokens: int
    ) -> str:
        """RAG检索相关章节
        
        Args:
            target_range: 目标章节范围
            available_tokens: 可用token数
            
        Returns:
            检索到的相关内容
        """
        try:
            # 构建查询
            query = f"第{target_range[0]}章到第{target_range[1]}章的情节内容"
            
            # 检索top-k文档
            k = min(20, int(available_tokens / 500))  # 每篇约500 tokens
            results = self.knowledge_base.search(query, k=k)
            
            # 组装结果
            relevant_docs = []
            total_chars = 0
            max_chars = int(available_tokens * 1.5)  # tokens转字符(约1.5倍)
            
            for doc in results:
                content = doc.page_content
                if total_chars + len(content) <= max_chars:
                    relevant_docs.append(content)
                    total_chars += len(content)
                else:
                    break
            
            print(f"   - RAG检索: {len(relevant_docs)}篇文档, {total_chars:,}字符")
            
            return '\n\n'.join(relevant_docs)
            
        except Exception as e:
            print(f"⚠️  RAG检索失败: {e}，回退到正则提取")
            return ""
    
    def _regex_extract_range(
        self,
        outline: str,
        target_range: Tuple[int, int],
        available_tokens: int
    ) -> str:
        """正则提取指定范围的章节
        
        Args:
            outline: 完整大纲
            target_range: 目标章节范围
            available_tokens: 可用token数
            
        Returns:
            提取的章节内容
        """
        detailed_sections = []
        
        for line in outline.split('\n'):
            # 匹配章节号
            match = re.search(r'第(\d+)章', line)
            if match:
                chapter_num = int(match.group(1))
                if target_range[0] <= chapter_num <= target_range[1]:
                    detailed_sections.append(line)
        
        detailed_text = '\n'.join(detailed_sections)
        
        # 如果超出可用空间，截断
        estimated_tokens = self._estimate_tokens(detailed_text)
        if estimated_tokens > available_tokens:
            # 缩小范围
            mid = (target_range[0] + target_range[1]) // 2
            shrink_range = (mid - 5, mid + 5)
            return self._regex_extract_range(outline, shrink_range, available_tokens)
        
        print(f"   - 正则提取: {len(detailed_sections)}章, {len(detailed_text):,}字符")
        
        return detailed_text


def prepare_smart_context(
    outline: str = "",
    characters: str = "",
    worldview: str = "",
    scenario: str = "outline_expand",
    current_count: int = 50,
    focus_range: Optional[Tuple[int, int]] = None,
    knowledge_base: Optional[NovelKnowledgeBase] = None
) -> Dict[str, Any]:
    """
    便捷函数: 智能准备上下文
    
    Args:
        outline: 情节大纲
        characters: 人物设定
        worldview: 世界观设定
        scenario: 使用场景
        current_count: 当前章节数/人物数
        focus_range: 聚焦范围
        knowledge_base: 知识库实例
        
    Returns:
        {
            "context": 优化后的上下文,
            "selected_model": 选择的模型,
            "stats": 统计信息
        }
    """
    summarizer = LayeredSummarizer(knowledge_base)
    return summarizer.prepare_context_for_expansion(
        outline=outline,
        characters=characters,
        worldview=worldview,
        scenario=scenario,
        current_count=current_count,
        focus_range=focus_range
    )
