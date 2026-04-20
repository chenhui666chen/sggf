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

class EpicFrameworkMixin:
    def _legacy_generate_epic_framework(self, world_setting: str, characters: str,
                               total_volumes: int, total_chapters_range: tuple[int, int]) -> Dict[str, Any]:
        """生成史诗框架（超长网文总体规划）
        
        为1000+章的超长网文生成宏观框架，每卷仅200-300字概要
        
        Args:
            world_setting: 世界观设定
            characters: 人物设定
            total_volumes: 总卷数(10-50卷)
            total_chapters_range: 总章节范围(min, max)
            
        Returns:
            史诗框架字典，包含:
            - expanded_outline: 史诗框架内容
            - total_volumes: 总卷数
            - estimated_chapters: 预估总章节数
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"🌟 【史诗框架生成器】{total_volumes}卷，预计{total_chapters_range[0]}-{total_chapters_range[1]}章")
        logger.debug(f"{'='*70}\n")
        
        framework_prompt = f"""你是顶级网文架构师，擅长规划超长篇网文（1000章以上）。

【任务】
规划一部{total_volumes}卷的超长网文，预计{total_chapters_range[0]}-{total_chapters_range[1]}章

【当前设定】
世界观：
{world_setting}

主要人物：
{characters[:1000] if characters else '待完善'}

【输出要求】
⚠️ 这是史诗框架，不是详细大纲！每卷仅需200-300字概要

## 一、整体叙事节奏
分为前中后三期，每期占多少卷，预计章节数：
- 前期（第1-X卷）：主题/场景 → Y章
- 中期（第X-Y卷）：主题/场景 → Z章
- 后期（第Y-{total_volumes}卷）：主题/场景 → W章

## 二、境界/实力体系进阶
🔥 根据题材和总章数智能规划：

【境界密度规则】
- 若总章数 < 500：大境界3-5个，每大境界80-150章
- 若500-1500章：大境界5-8个，每大境界100-200章
- 若 > 1500章：大境界8-12个，每大境界120-250章

【题材适配】
- 修仙类：炼气→1-9层→筑基→金丹→元婴→化神→合体→渡劫（可下分初/中/后期）
- 玄幻类：战士→战师1-9星→大斗师→斗灵→斗圣→斗帝
- 武侠类：三流→二流→一流→宗师→大宗师→武圣
- 都市类：以财富/权势/影响力为阶段，如：起步→初有成就→行业精英→领域霸主

【具体要求】
1. 首先分析世界观是什么题材（修仙/玄幻/武侠/都市/其他）
2. 根据总章数{total_chapters_range[0]}-{total_chapters_range[1]}决定大境界数量
3. 每个大境界应分配60-200章，避免500+章才进阶一次
4. 修仙类需考虑小境界（如炼气1-9层），提供更频繁的成就感
5. 列出具体的境界进阶路径，格式如：
   - 第1-3卷：炼气1层→9层（约120-180章）
   - 第4-6卷：筑基初期→后期（约150-200章）
   - 第7-10卷：金丹初期→后期（约200-280章）
   - ...

⚠️ 关键：不要固定“有5卷一个大境界”，而是根据题材和总章数灵活调整！

## 三、{total_volumes}卷概要
❗️❗️ 每卷最多{VOLUME_DETAIL_MAX_CHAPTERS}章！如果内容多就增加卷数，不要让单卷超过{VOLUME_DETAIL_MAX_CHAPTERS}章 ❗️❗️

每卷格式：
【第X卷】卷名（预计30-{VOLUME_DETAIL_MAX_CHAPTERS}章，不得超过{VOLUME_DETAIL_MAX_CHAPTERS}章）
- 核心：本卷主题/目标
- 境界：主角境界范围（如：炼气3层→7层）
- 主要敌人：本卷Boss
- 卷末高潮：关键事件

## 四、关键伏笔布局
| 伏笔 | 埋设位置 | 铺垫卷 | 揭秘卷 |
|------|---------|--------|--------|
| 主角真实身份 | 第X卷 | 第Y,Z卷 | 第W卷 |
| 天道黑幕 | 第A卷 | 第B,C卷 | 第D卷 |
(至少10条跨卷伏笔)

## 五、核心人物生命周期
| 角色 | 登场 | 活跃期 | 退场/转型 |
|------|------|--------|-------------|
| 女主 | 第1卷 | 1-{total_volumes}卷 | 始终在线 |
| 师父 | 第1卷 | 1-8卷 | 第9卷羽化 |
(主要角色的登场退场规划)

记住：这是框架，不是详细大纲，保持高层视角！"""

        logger.debug("【第一步】生成史诗框架...")
        
        # 🛡️ 重试机制：处理网络波动
        import time
        max_retries = 3
        retry_delays = [2, 4, 8]  # 指数退避
        
        for attempt in range(max_retries):
            try:
                framework_content = self.creative_director.process(framework_prompt, {})
                logger.debug("✅ 史诗框架生成完成\n")
                break  # 成功则跳出重试循环
            except Exception as e:
                error_str = str(e).lower()
                # 检查是否是网络连接错误
                is_connection_error = any(keyword in error_str for keyword in [
                    'connection', 'ssl', 'timeout', 'eof', 'network', 'reset'
                ])
                
                if is_connection_error and attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.debug(f"⚠️ 网络连接失败，{delay}秒后重试（第{attempt + 1}/{max_retries}次）...")
                    time.sleep(delay)
                    continue
                else:
                    # 非网络错误或最后一次重试失败
                    logger.debug(f"❌ 史诗框架生成失败: {e}")
                    raise
        
        logger.debug(f"{'='*70}")
        logger.debug(f"【史诗框架生成】完成！")
        logger.debug(f"{'='*70}\n")
        
        return {
            "expanded_outline": framework_content,
            "total_volumes": total_volumes,
            "estimated_chapters": (total_chapters_range[0] + total_chapters_range[1]) // 2,
            "framework_type": "epic"
        }


    def _extract_core_storyline_from_framework(self, framework_content: str) -> str:
        """从史诗框架中提取核心主线
        
        Args:
            framework_content: 史诗框架内容
            
        Returns:
            核心主线部分的提示词
        """
        import re
        
        if not framework_content:
            return ""
        
        # 尝试匹配整体叙事节奏部分
        patterns = [
            r'##\s*[一1][、.]?\s*故事总纲(?:与终局)?[\s\S]*?(?=##\s*[二2]|$)',
            r'##\s*一[、.]?\s*整体叙事节奏[\s\S]*?(?=##\s*[二2]|$)',
            r'【核心主线】[\s\S]*?(?=【|##|$)',
            r'核心主线[:：][\s\S]*?(?=\n\n|##|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, framework_content)
            if match:
                storyline = match.group(0).strip()
                # 限制长度
                if len(storyline) > 500:
                    storyline = storyline[:500] + "..."
                return f"\n【🎯 全书核心主线（从史诗框架提取）】\n{storyline}\n"
        
        # 如果找不到特定部分，提取框架开头部分作为概览
        overview = framework_content[:800] if len(framework_content) > 800 else framework_content
        return f"\n【🎯 全书框架概览】\n{overview}\n"
    
    def _format_foreshadowings_list(self, foreshadowings: List[Any]) -> str:
        """格式化伏笔列表为文本
        
        Args:
            foreshadowings: 伏笔列表，支持字典列表或字符串列表
            
        Returns:
            格式化后的文本
        """
        if not foreshadowings:
            return "无"
        
        result = []
        for item in foreshadowings:
            # 🌟 支持两种格式：字典和字符串
            if isinstance(item, dict):
                # 字典格式：{"content": "...", "planted_volume": X, "reveal_volume": Y}
                content = item.get('content', '未知伏笔')
                planted_vol = item.get('planted_volume', '?')
                reveal_vol = item.get('reveal_volume', '?')
                result.append(f"- {content}（埋设于第{planted_vol}卷，揭秘于第{reveal_vol}卷）")
            elif isinstance(item, str):
                # 字符串格式：直接是伏笔内容
                result.append(f"- {item}")
            else:
                result.append(f"- {str(item)}")
        
        return "\n   ".join(result) if result else "无"
    
    def _generate_foreshadowing_checklist_hint(self, 
                                               pending_foreshadowings: Optional[List[Dict[str, Any]]], 
                                               target_volume_index: int) -> str:
        """生成伏笔检查清单提示
        
        Args:
            pending_foreshadowings: 待处理伏笔列表
            target_volume_index: 当前卷索引
            
        Returns:
            伏笔检查清单文本
        """
        if not pending_foreshadowings:
            return "✅ 第X章：埋设主角身份伏笔（符合史诗框架）\n✅ 第Y章：提及相关线索（为后续卷铺垫）"
        
        checklist_lines = []
        for item in pending_foreshadowings:
            action = item.get('action', 'plant')
            content = item.get('content', '未知伏笔')
            
            if action == 'plant':
                reveal_vol = item.get('reveal_volume', '?')
                checklist_lines.append(f"✅ 第??章：埋设『{content[:20]}...』伏笔（将于第{reveal_vol}卷揭秘）")
            elif action == 'pave':
                planted_vol = item.get('planted_volume', '?')
                checklist_lines.append(f"✅ 第??章：铺垫『{content[:20]}...』（第{planted_vol}卷埋设，本卷强化暗示）")
            elif action == 'reveal':
                planted_vol = item.get('planted_volume', '?')
                checklist_lines.append(f"✅ 第??章：揭秘『{content[:20]}...』（第{planted_vol}卷埋设，本卷完成回收）")
        
        return "\n".join(checklist_lines) if checklist_lines else "✅ 无特定伏笔任务"


