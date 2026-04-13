"""
卷间衔接约束器 - 确保卷卷衔接无缝

核心功能：
1. 从已生成的卷内容中提取关键信息摘要
2. 生成下一卷的前置锚点提示词
3. 支持AI智能提取和规则提取两种模式

三层体系定位：
- 顶层框架锚定：由长篇框架提供（不在本模块）
- 卷级接口约束：本模块核心功能
- 章节锚点承接：由提示词模板实现（在outline_expander.py）
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class VolumeConnector:
    """卷间衔接约束器 - 实现卷与卷之间的无缝衔接"""
    
    def __init__(self, llm=None):
        """初始化卷间衔接器
        
        Args:
            llm: LLM实例，用于AI智能提取（可选）
        """
        self.llm = llm
    
    def extract_volume_summary(self, volume_content: str, volume_index: int) -> Dict[str, Any]:
        """从已生成的卷内容中提取关键信息摘要
        
        这是卷间衔接的核心方法，提取的信息将用于下一卷的前置锚点
        
        Args:
            volume_content: 已生成的卷细纲内容
            volume_index: 当前卷索引
            
        Returns:
            摘要字典，包含：
            - core_plot_completed: 本卷完成的核心剧情
            - character_status_update: 人物状态更新
            - new_foreshadowings: 新埋下的伏笔列表
            - ending_hook: 卷尾钩子
            - next_volume_target: 下卷开局目标
            - volume_index: 卷索引
            - extracted_at: 提取时间
        """
        logger.info(f"📖 开始提取第{volume_index}卷摘要...")
        
        if not volume_content:
            logger.warning(f"⚠️ 第{volume_index}卷内容为空，返回默认摘要")
            return self._get_empty_summary(volume_index)
        
        # 优先使用AI智能提取
        if self.llm:
            try:
                summary = self._ai_extract_summary(volume_content, volume_index)
                if summary and summary.get('core_plot_completed'):
                    logger.info(f"✅ AI智能提取第{volume_index}卷摘要成功")
                    return summary
            except Exception as e:
                logger.warning(f"⚠️ AI提取失败: {e}，回退到规则提取")
        
        # 回退到规则提取
        summary = self._rule_extract_summary(volume_content, volume_index)
        logger.info(f"✅ 规则提取第{volume_index}卷摘要完成")
        return summary
    
    def _ai_extract_summary(self, volume_content: str, volume_index: int) -> Dict[str, Any]:
        """使用AI智能提取卷摘要
        
        Args:
            volume_content: 卷细纲内容
            volume_index: 卷索引
            
        Returns:
            提取的摘要字典
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        
        # 限制输入长度，取最后部分（卷尾信息更重要）
        content_for_extraction = volume_content
        if len(volume_content) > 8000:
            # 保留开头500字（卷主题）+ 最后6000字（卷尾详情）
            content_for_extraction = volume_content[:500] + "\n...\n" + volume_content[-6000:]
        
        extract_prompt = f"""请从以下第{volume_index}卷细纲中提取关键信息，用于下一卷的衔接。

【第{volume_index}卷细纲】
{content_for_extraction}

【提取要求】
请严格按以下JSON格式输出，不要添加任何其他内容：

{{
    "core_plot_completed": "本卷完成的核心剧情（100字以内，包含主要事件和结果）",
    "character_status_update": "主要人物当前状态（80字以内，如：主角境界/实力、关键配角变化）",
    "new_foreshadowings": [
        "伏笔1：简述埋设的伏笔内容",
        "伏笔2：如有其他伏笔"
    ],
    "ending_hook": "卷尾钩子/悬念（50字以内，本卷结尾留下的悬念）",
    "next_volume_target": "下卷开局目标/场景（50字以内，下一卷应该从哪里开始）"
}}

只输出JSON，不要有任何解释。"""

        response = self.llm.invoke([
            SystemMessage(content="你是专业的内容提取专家，擅长从长文本中提炼关键信息。只输出JSON格式。"),
            HumanMessage(content=extract_prompt)
        ])
        
        # 解析JSON响应
        response_text = response.content.strip()
        
        # 尝试提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            json_str = json_match.group(0)
            parsed = json.loads(json_str)
            
            # 确保新伏笔是列表格式
            if isinstance(parsed.get('new_foreshadowings'), str):
                parsed['new_foreshadowings'] = [parsed['new_foreshadowings']]
            
            parsed['volume_index'] = volume_index
            parsed['extracted_at'] = datetime.now().isoformat()
            parsed['extraction_method'] = 'ai'
            
            return parsed
        
        raise ValueError("无法从AI响应中解析JSON")
    
    def _rule_extract_summary(self, volume_content: str, volume_index: int) -> Dict[str, Any]:
        """使用规则提取卷摘要（兜底方案）
        
        Args:
            volume_content: 卷细纲内容
            volume_index: 卷索引
            
        Returns:
            提取的摘要字典
        """
        summary = {
            "core_plot_completed": "",
            "character_status_update": "",
            "new_foreshadowings": [],
            "ending_hook": "",
            "next_volume_target": "",
            "volume_index": volume_index,
            "extracted_at": datetime.now().isoformat(),
            "extraction_method": "rule"
        }
        
        # 1. 提取故事概述作为核心剧情
        overview_patterns = [
            r'##\s*一[、.]?\s*故事概述[\s\S]*?(?=##\s*[二2]|$)',
            r'【故事概述】[\s\S]*?(?=【|##|$)',
            r'故事概述[:：][\s\S]*?(?=\n\n|##|$)',
        ]
        for pattern in overview_patterns:
            match = re.search(pattern, volume_content)
            if match:
                overview = match.group(0).strip()
                # 取前200字
                summary["core_plot_completed"] = overview[:200] if len(overview) > 200 else overview
                break
        
        # 2. 提取最后几章的信息作为卷尾内容
        # 查找最后3个章节标题
        chapter_pattern = r'###?\s*第(\d+)章[：:][^\n]*'
        chapter_matches = list(re.finditer(chapter_pattern, volume_content))
        
        if chapter_matches:
            # 取最后3章
            last_chapters = chapter_matches[-3:] if len(chapter_matches) >= 3 else chapter_matches
            
            # 提取最后一章的结尾钩子
            if last_chapters:
                last_chapter_start = last_chapters[-1].start()
                last_chapter_content = volume_content[last_chapter_start:]
                
                # 查找结尾钩子
                hook_patterns = [
                    r'\*\*结尾钩子\*\*[：:]\s*([^\n]+)',
                    r'结尾钩子[：:]\s*([^\n]+)',
                    r'钩子[：:]\s*([^\n]+)',
                ]
                for pattern in hook_patterns:
                    match = re.search(pattern, last_chapter_content)
                    if match:
                        summary["ending_hook"] = match.group(1).strip()[:100]
                        break
        
        # 3. 提取伏笔信息
        foreshadowing_patterns = [
            r'##\s*[三3][、.]?\s*伏笔埋设检查[\s\S]*?(?=##|$)',
            r'伏笔埋设检查[\s\S]*?(?=##|$)',
            r'✅[^\n]*伏笔[^\n]*',
        ]
        for pattern in foreshadowing_patterns:
            matches = re.findall(pattern, volume_content)
            if matches:
                for match in matches[:5]:  # 最多5条
                    # 清理格式
                    clean_text = re.sub(r'[✅\*#]', '', match).strip()
                    if clean_text and len(clean_text) > 5:
                        summary["new_foreshadowings"].append(clean_text[:100])
                break
        
        # 4. 提取卷尾衔接检查中的下卷开局
        next_vol_patterns = [
            r'下卷开局场景[：:]\s*([^\n]+)',
            r'下卷目标[：:]\s*([^\n]+)',
            r'下一卷[：:]\s*([^\n]+)',
        ]
        for pattern in next_vol_patterns:
            match = re.search(pattern, volume_content)
            if match:
                summary["next_volume_target"] = match.group(1).strip()[:100]
                break
        
        # 5. 如果没有找到下卷目标，从结尾钩子推断
        if not summary["next_volume_target"] and summary["ending_hook"]:
            summary["next_volume_target"] = f"承接上卷悬念：{summary['ending_hook'][:50]}"
        
        # 6. 如果没有找到核心剧情，取内容开头
        if not summary["core_plot_completed"]:
            summary["core_plot_completed"] = volume_content[:200] + "..."
        
        return summary
    
    def _get_empty_summary(self, volume_index: int) -> Dict[str, Any]:
        """返回空摘要模板
        
        Args:
            volume_index: 卷索引
            
        Returns:
            空摘要字典
        """
        return {
            "core_plot_completed": "待填充",
            "character_status_update": "待填充",
            "new_foreshadowings": [],
            "ending_hook": "待填充",
            "next_volume_target": "待填充",
            "volume_index": volume_index,
            "extracted_at": datetime.now().isoformat(),
            "extraction_method": "empty"
        }
    
    def generate_next_volume_prefix(self, prev_volume_summary: Dict[str, Any], 
                                    next_volume_index: int) -> str:
        """生成下一卷的前置锚点提示词
        
        这是 expand_volume_detail() 中 prev_volume_section 的数据来源
        
        Args:
            prev_volume_summary: 上一卷的摘要信息
            next_volume_index: 下一卷的索引
            
        Returns:
            前置锚点提示词文本
        """
        if not prev_volume_summary:
            return ""
        
        prev_vol_idx = prev_volume_summary.get('volume_index', next_volume_index - 1)
        
        # 格式化伏笔列表
        foreshadowings = prev_volume_summary.get('new_foreshadowings', [])
        if isinstance(foreshadowings, list) and foreshadowings:
            foreshadowing_text = "\n".join([f"   - {f}" for f in foreshadowings])
        else:
            foreshadowing_text = "   - 无新增伏笔"
        
        prefix = f"""
【📚 前置锚点（第{next_volume_index}卷必须严格遵循）】

**承接自第{prev_vol_idx}卷**：

1. **上一卷核心剧情完成情况**：
   {prev_volume_summary.get('core_plot_completed', '待填充')}

2. **人物当前状态**：
   {prev_volume_summary.get('character_status_update', '待填充')}

3. **上一卷埋下的伏笔**（需在本卷或后续卷回收）：
{foreshadowing_text}

4. **上一卷结尾钩子**：
   {prev_volume_summary.get('ending_hook', '待填充')}

5. **本卷开局目标**（必须承接）：
   ⚠️ {prev_volume_summary.get('next_volume_target', '待填充')}

---
🔔 **衔接规则**：本卷第一章必须从「本卷开局目标」描述的场景/事件开始，不可跳跃或忽略上一卷结尾钩子！
"""
        return prefix
    
    def validate_volume_connection(self, prev_volume_content: str, 
                                   next_volume_content: str,
                                   prev_volume_index: int) -> Dict[str, Any]:
        """验证两卷之间的衔接是否正确
        
        Args:
            prev_volume_content: 上一卷内容
            next_volume_content: 下一卷内容
            prev_volume_index: 上一卷索引
            
        Returns:
            验证结果字典
        """
        issues = []
        
        # 1. 提取上一卷的结尾信息
        prev_summary = self.extract_volume_summary(prev_volume_content, prev_volume_index)
        
        # 2. 检查下一卷开头是否承接
        next_vol_start = next_volume_content[:1500]  # 取开头1500字
        
        # 检查是否提及上一卷的关键元素
        ending_hook = prev_summary.get('ending_hook', '')
        next_target = prev_summary.get('next_volume_target', '')
        
        # 简单的关键词匹配检查
        keywords_to_check = []
        if ending_hook:
            # 提取关键词（简单的分词）
            keywords_to_check.extend(re.findall(r'[\u4e00-\u9fa5]{2,4}', ending_hook))
        if next_target:
            keywords_to_check.extend(re.findall(r'[\u4e00-\u9fa5]{2,4}', next_target))
        
        # 去重并检查
        keywords_to_check = list(set(keywords_to_check))[:10]
        matched_keywords = [kw for kw in keywords_to_check if kw in next_vol_start]
        
        match_ratio = len(matched_keywords) / max(len(keywords_to_check), 1)
        
        if match_ratio < 0.3:
            issues.append({
                "type": "weak_connection",
                "severity": "warning",
                "message": f"第{prev_volume_index}卷与第{prev_volume_index+1}卷衔接较弱，"
                          f"关键词匹配率仅{match_ratio*100:.0f}%"
            })
        
        if match_ratio < 0.1:
            issues.append({
                "type": "connection_break",
                "severity": "error",
                "message": f"第{prev_volume_index}卷与第{prev_volume_index+1}卷可能存在衔接断裂"
            })
        
        return {
            "valid": len([i for i in issues if i['severity'] == 'error']) == 0,
            "issues": issues,
            "match_ratio": match_ratio,
            "matched_keywords": matched_keywords
        }


def get_volume_connector(llm=None) -> VolumeConnector:
    """获取卷间衔接器实例
    
    Args:
        llm: LLM实例（可选，用于AI智能提取）
        
    Returns:
        VolumeConnector实例
    """
    return VolumeConnector(llm=llm)
