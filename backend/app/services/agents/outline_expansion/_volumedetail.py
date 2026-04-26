"""Outline expansion mixin."""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from ..knowledge_base import NovelKnowledgeBase
from ..memory_manager import NovelMemoryManager
from ..agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
from ..layered_summarizer import LayeredSummarizer
from ...volume_connector import VolumeConnector
from ...foreshadowing_tracker import ForeshadowingTracker
from ...consistency_validator import ConsistencyValidator, get_consistency_validator, get_chapter_renumberer
from ..character_recognizer import CharacterRecognizer
from ..character_plot_validator import CharacterPlotValidator
from ...character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _merge_parsed_character,
    normalize_character_name,
)
from ...character_runtime_context import build_character_prompt_context_from_text
from ._constants import *

def _resolve_chapter_renumberer():
    try:
        from .. import outline_expander as outline_expander_module

        factory = getattr(outline_expander_module, "get_chapter_renumberer", None)
        if callable(factory):
            return factory()
    except Exception:
        pass
    return get_chapter_renumberer()


def _resolve_consistency_validator(*, strict_mode: bool = True):
    try:
        from .. import outline_expander as outline_expander_module

        factory = getattr(outline_expander_module, "get_consistency_validator", None)
        if callable(factory):
            return factory(strict_mode=strict_mode)
    except Exception:
        pass
    return get_consistency_validator(strict_mode=strict_mode)


class VolumeDetailMixin:
    def _legacy_expand_volume_detail(self, framework_content: str, target_volume_index: int,
                            world_setting: str, characters: str,
                            start_chapter_num: int,
                            chapters_count_range: tuple[int, int],
                            prev_volume_summary: Optional[Dict[str, Any]] = None,
                            pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
                            core_storyline: Optional[str] = None,
                            framework_header: Optional[str] = None,
                            framework_footer: Optional[str] = None) -> Dict[str, Any]:
        """基于史诗框架详细扩展单卷（三层体系增强版）
        
        根据已有的史诗框架，将指定的卷扩展为详细的章节大纲。
        采用「顶层框架锚定+卷级接口约束+章节锚点承接」三层体系。
        
        Args:
            framework_content: 史诗框架内容
            target_volume_index: 扩展第几卷
            world_setting: 世界观设定
            characters: 人物设定
            start_chapter_num: 起始章节号
            chapters_count_range: 本卷章节数量范围(min, max)，AI在此范围内自由发挥
            prev_volume_summary: 上一卷摘要信息（可选），包含：
                - core_plot_completed: 本卷完成的核心剧情
                - character_status_update: 人物状态更新
                - new_foreshadowings: 新埋下的伏笔
                - ending_hook: 卷尾钩子
                - next_volume_target: 下卷开局目标
            pending_foreshadowings: 待处理伏笔清单（可选），每项包含：
                - content: 伏笔内容
                - planted_volume: 埋设卷
                - action: 本卷动作（plant/pave/reveal）
            core_storyline: 全书核心主线（可选）
            framework_header: 🌟 框架头部（整体叙事节奏、境界体系等全局约束）
            framework_footer: 🌟 框架尾部（伏笔布局、人物生命周期等全局约束）
            
        Returns:
            单卷详细字典，包含:
            - expanded_outline: 详细大纲
            - volume_index: 卷索引
            - chapter_count: 实际章节数
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"📖 【单卷详细扩展】第{target_volume_index}卷，从第{start_chapter_num}章开始，生成{chapters_count_range[0]}-{chapters_count_range[1]}章")
        logger.debug(f"{'='*70}\n")

        # 🚀 统一使用 deepseek-v4-pro（384K 超长输出），不再按章节数切换模型
        avg_chapters = (chapters_count_range[0] + chapters_count_range[1]) // 2
        estimated_words = avg_chapters * 450  # 每章约450字
        model_name = self.estimate_volume_detail_model(chapters_count_range)
        selected_architect = self.plot_architect_plus if model_name == "qwen3.5-plus" else self.plot_architect_r1
        logger.debug(
            "Volume detail runtime model selected | model=%s avg_chapters=%s estimated_words=%s",
            model_name,
            avg_chapters,
            estimated_words,
        )
        logger.debug(
            f"✅ 单卷详细扩展统一使用 deepseek-v4-pro（{avg_chapters}章，约{estimated_words}字，384K 输出）"
        )

        # 🛡️ 临时修复：清空历史记忆，避免旧消息导致API错误
        logger.debug("🧹 清空历史记忆，避免旧消息影响...")
        self.plot_architect.memory_manager.clear_history()
        self.creative_director.memory_manager.clear_history()
        
        # 🆕 获取题材专属的章节细纲模板和补充说明
        chapter_template = self.genre_module.get('chapter_detail_template', '')
        outline_tips = self.genre_module.get('outline_detail_tips', '')  # 🆕 新增：题材补充说明
        template_example = chapter_template.format(
            chapter_num=1,
            chapter_title="章节标题"
        ) if chapter_template else ""
        
        # ==================== 🆕 三层体系增强 ====================
        
        # 1️⃣ 构建「顶层框架锚点」- 全书核心主线
        core_storyline_section = ""
        if core_storyline:
            core_storyline_section = f"""\n【🎯 全书核心主线（不可偏离）】\n{core_storyline}\n"""
        else:
            # 尝试从史诗框架中提取核心主线
            core_storyline_section = self._extract_core_storyline_from_framework(framework_content)
        
        # 2️⃣ 构建「卷级接口约束」- 上一卷衔接信息
        prev_volume_section = ""
        if prev_volume_summary and target_volume_index > 1:
            new_foreshadowings_text = self._format_foreshadowings_list(
                prev_volume_summary.get('new_foreshadowings', [])
            )
            prev_volume_section = f"""\n【📚 前置锚点（必须严格遵循）】

1. **上一卷结尾内容**：
   - 核心剧情完成：{prev_volume_summary.get('core_plot_completed', '待填充')}
   - 卷尾钩子：{prev_volume_summary.get('ending_hook', '待填充')}
   - 下卷开局目标：{prev_volume_summary.get('next_volume_target', '待填充')}

2. **人物状态更新**：
   {prev_volume_summary.get('character_status_update', '待填充')}

3. **已埋下的伏笔**（需在本卷或后续卷回收）：
   {new_foreshadowings_text}

⚠️ **本卷第{start_chapter_num}章必须从上述「下卷开局目标」开始**，确保卷间无缝衔接！\n"""
        
        # 3️⃣ 构建「待处理伏笔约束」
        foreshadowing_section = ""
        if pending_foreshadowings:
            plant_items = [f for f in pending_foreshadowings if f.get('action') == 'plant']
            pave_items = [f for f in pending_foreshadowings if f.get('action') == 'pave']
            reveal_items = [f for f in pending_foreshadowings if f.get('action') == 'reveal']
            
            foreshadowing_section = "\n【🎭 本卷伏笔任务】\n"
            if plant_items:
                foreshadowing_section += "\n**本卷需埋设的伏笔**：\n"
                for item in plant_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（揭秘于第{item.get('reveal_volume', '?')}卷）\n"
            if pave_items:
                foreshadowing_section += "\n**本卷需铺垫的伏笔**（已埋设，需强化暗示）：\n"
                for item in pave_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（埋设于第{item.get('planted_volume', '?')}卷）\n"
            if reveal_items:
                foreshadowing_section += "\n**本卷需揭秘的伏笔**（完成回收）：\n"
                for item in reveal_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（埋设于第{item.get('planted_volume', '?')}卷）\n"
        
        # 4️⃣ 构建「卷尾过渡段约束」- 明确最后3章任务
        end_chapter_num = start_chapter_num + chapters_count_range[1] - 1
        volume_transition_section = f"""\n【📍 卷尾过渡段设计（极重要）】

本卷最后3章（约第{end_chapter_num-2}~{end_chapter_num}章）必须完成以下任务：

1. **倒数第3章**（第{end_chapter_num-2}章左右）：完成本卷核心任务/Boss战/关键突破
2. **倒数第2章**（第{end_chapter_num-1}章左右）：抛出下一卷的核心悬念/新线索
3. **最后一章**（第{end_chapter_num}章左右）：明确下一卷的开局场景/目标，设置强力钩子\n"""
        
        # 5⃣️ 构建伏笔检查提示
        foreshadowing_checklist = self._generate_foreshadowing_checklist_hint(
            pending_foreshadowings, target_volume_index
        ) if pending_foreshadowings else "✅ 第X章：埋设主角身份伏笔（符合史诗框架）\n✅ 第Y章：提及相关线索（为后续卷铺垫）"
        
        # 6️⃣ 🌟 构建「全局约束模块」- 显式强调头部和尾部信息
        global_constraints_section = ""
        if framework_header or framework_footer:
            global_constraints_section = "\n【🌟 全局约束（必须严格遵循）】\n"
            
            if framework_header:
                # deepseek-v4-pro 384K 输出下放宽头部截断
                header_excerpt = framework_header[:12000] if len(framework_header) > 12000 else framework_header
                global_constraints_section += f"""\n**1⃣ 整体叙事节奏与境界体系**（本卷必须符合）：
{header_excerpt}
"""
            
            if framework_footer:
                # deepseek-v4-pro 384K 输出下放宽尾部截断
                footer_excerpt = framework_footer[:12000] if len(framework_footer) > 12000 else framework_footer
                global_constraints_section += f"""\n**2️⃣ 伏笔布局与人物周期**（本卷需配合）：
{footer_excerpt}

⚠️ 本卷的情节设计必须：
- 符合上述叙事节奏和境界进阶设定
- 配合全局伏笔布局（埋设/铺垫/揭秘）
- 保持人物生命周期的连续性
"""
        
        detail_prompt = f"""基于已有的史诗框架，详细扩展第{target_volume_index}卷。
{global_constraints_section}
{core_storyline_section}
{prev_volume_section}
{foreshadowing_section}
【史诗框架】
{framework_content}

【世界观设定】
{world_setting}

【人物设定】
{characters[:12000] if characters else '待完善'}

【扩展要求】
本卷章节编号从第{start_chapter_num}章开始，必须生成{chapters_count_range[0]}-{chapters_count_range[1]}章的详细大纲。

⚠️ 【章节数量要求】：
- 最少章节数：{chapters_count_range[0]}章（不得少于此数量）
- 最多章节数：{chapters_count_range[1]}章（不得超过此数量）
- 建议章节数：{(chapters_count_range[0] + chapters_count_range[1]) // 2}章左右
- 如果剧情需要，可以在上述范围内自由调整，但必须完整输出每一章

{volume_transition_section}

🔥 【章节细纲模板】每章必须严格按以下格式：
## 二、第{target_volume_index}卷详细规划（第{start_chapter_num}-第{start_chapter_num + chapters_count_range[0] - 1}章至第{start_chapter_num + chapters_count_range[1] - 1}章）
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
'''

{outline_tips if outline_tips else ''}

Please输出完整的、重新整合后的网文大纲：

## 一、故事概述
[整合后的完整故事概述，300-500字]

## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）

⚠️ 【极重要】必须逐章完整输出，不得省略任何章节！
- 本卷必须包含{chapters_count_range[0]}-{chapters_count_range[1]}章，不得少于{chapters_count_range[0]}章
- 禁止使用"中间章节略"、"......略"、"精选第X章"等占位符
- 每一章都必须按照上述模板格式完整展开，包含所有必填字段
- 从第{start_chapter_num}章开始，一直写到本卷最后一章（至少第{start_chapter_num + chapters_count_range[0] - 1}章），中间不能断开
- 如果剧情需要更多章节，可以扩展到第{start_chapter_num + chapters_count_range[1] - 1}章

### 第{start_chapter_num}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 1}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 2}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 3}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第{start_chapter_num + 4}章、第{start_chapter_num + 5}章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

## 三、伏笔埋设检查
{foreshadowing_checklist}

## 四、卷尾衔接检查
✅ 本卷核心任务完成情况：（简述）
✅ 下卷开局场景：（明确描述）
✅ 卷尾钩子：（强力悬念）"""

        logger.debug(f"【第一步】详细扩展第{target_volume_index}卷（使用{model_name}模型）...")

        # 🛡️ 内容安全重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 第一次尝试：正常prompt
                # 后续尝试：添加内容安全约束
                if attempt > 0:
                    logger.debug(f"⚠️ 检测到内容安全问题，第{attempt + 1}次重试（共{max_retries}次）...")
                    # 在prompt末尾添加内容安全约束
                    safety_constraint = """

⚠️ 内容安全要求：
1. 避免包含暴力、血腥、恐怖等过度描写
2. 人物关系和情节发展应符合主流价值观
3. 使用委婉、克制的表达方式
4. 重点突出正面价值观和人物成长"""
                    detail_prompt_safe = detail_prompt + safety_constraint
                    volume_content = selected_architect.process(detail_prompt_safe, {})  # ✅ 使用选中的模型
                else:
                    volume_content = selected_architect.process(detail_prompt, {})  # ✅ 使用选中的模型
                
                logger.debug("✅ 单卷详细扩展完成\n")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是内容安全问题
                if 'data_inspection_failed' in error_str or 'inappropriate content' in error_str:
                    if attempt < max_retries - 1:
                        logger.debug(f"⚠️ 内容安全审查失败: {error_str[:100]}...")
                        continue  # 继续重试
                    else:
                        # 最后一次重试也失败，返回占位内容
                        logger.debug(f"❌ 第{target_volume_index}卷内容安全审查多次失败，使用占位内容")
                        volume_content = f"""## 第{target_volume_index}卷：内容生成失败

⚠️ 由于内容安全审查限制，本卷详细大纲暂时无法生成。
建议：
1. 调整世界观设定或人物关系，避免敏感内容
2. 手动编写本卷大纲
3. 稍后重试单卷扩展

章节范围：从第{start_chapter_num}章开始（预计{chapters_count_range[0]}-{chapters_count_range[1]}章）"""
                        break
                else:
                    # 非内容安全问题，直接抛出
                    raise
        
        logger.debug(f"{'='*70}")
        logger.debug(f"【单卷详细扩展】完成！")
        logger.debug(f"{'='*70}\n")
        
        # ✅ 三层体系整合：章节编号自动修正
        logger.debug(f"\n🔧 【章节编号修正器】检测第{target_volume_index}卷章节编号...")
        renumberer = _resolve_chapter_renumberer()
        renumber_result = renumberer.detect_and_fix(
            content=volume_content,
            expected_start=start_chapter_num,
            expected_count_range=chapters_count_range
        )
        
        # 使用修正后的内容
        volume_content = renumber_result["fixed_content"]
        if renumber_result["was_fixed"]:
            logger.debug(f"✅ {renumber_result['details']}")
        else:
            logger.debug(f"✅ {renumber_result['details']}")
        
        # 估算实际章节数(取范围中值)
        estimated_chapters = (chapters_count_range[0] + chapters_count_range[1]) // 2
        
        # 如果有修正结果，使用实际章节数
        if renumber_result["fixed_range"][1] > 0:
            actual_start = renumber_result["fixed_range"][0]
            actual_end = renumber_result["fixed_range"][1]
            estimated_chapters = actual_end - actual_start + 1
        
        # ✅ 三层体系整合：一致性校验（严格模式）
        logger.debug(f"\n🔍 【一致性校验器】开始校验第{target_volume_index}卷...")
        validator = _resolve_consistency_validator(strict_mode=True)
        validation_result = validator.validate(
            volume_content=volume_content,
            volume_index=target_volume_index,
            core_storyline=core_storyline or "",
            prev_volume_summary=prev_volume_summary,
            pending_foreshadowings=pending_foreshadowings,
            framework_content=framework_content
        )
        
        # 输出校验结果
        logger.debug(validation_result.get_summary())
        
        # 校验结果加入返回值
        validation_dict = validation_result.to_dict()
        
        return {
            "expanded_outline": volume_content,
            "volume_index": target_volume_index,
            "chapter_count": estimated_chapters,
            "current_chapter_count": estimated_chapters,
            # ✅ 新增：实际章节范围（修正后）
            "chapters_start": renumber_result["fixed_range"][0] if renumber_result["fixed_range"][0] > 0 else start_chapter_num,
            "chapters_end": renumber_result["fixed_range"][1] if renumber_result["fixed_range"][1] > 0 else start_chapter_num + estimated_chapters - 1,
            "renumber_result": renumber_result,
            # ✅ 新增：校验结果
            "validation": validation_dict,
            "validation_passed": validation_result.passed,
            "validation_issues": validation_dict.get('issues', []),
            "validation_suggestions": validation_dict.get('suggestions', [])
        }
    
    # ==================== 三层体系辅助方法 ====================

