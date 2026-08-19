"""
人物-大纲协同验证器 - 确保人物与情节相辅相成
"""
import logging
from typing import Dict, List, Any, Optional
from core.langchain_bridge import create_task_llm


logger = logging.getLogger(__name__)


class CharacterPlotValidator:
    """人物-大纲协同验证器"""

    def __init__(self, model: Optional[str] = None):
        """初始化验证器

        Args:
            model: 可选的指定模型 ID；缺省时走 default 任务路由。
                调用方在 default 任务模型不可用时应传入已验证可用的模型。
        """
        self.llm = create_task_llm(model=model, temperature=0.3)

    def validate_character_plot_alignment(
        self,
        characters: str,
        plot_outline: str,
        world_setting: str
    ) -> Dict[str, Any]:
        """验证人物与情节的对齐度

        Args:
            characters: 人物设定
            plot_outline: 情节大纲
            world_setting: 世界观设定

        Returns:
            验证结果字典
        """
        prompt = f"""你是一位资深小说编辑。请分析人物设定与情节大纲的匹配度。

【人物设定】
{characters[:8000]}

【情节大纲】
{plot_outline[:8000]}

【世界观】
{world_setting[:4000]}

请分析以下问题：

1. **人物-情节匹配度**（0-100分）
   - 每个主要人物在大纲中是否有明确的情节线？
   - 人物的动机是否能推动情节发展？
   - 是否存在"有人物无情节"或"有情节无人物"的情况？

2. **冗余人物识别**
   - 列出可能冗余的人物（在情节中作用不明确）
   - 说明为什么认为这些人物冗余

3. **缺失人物识别**
   - 根据情节需要，是否缺少关键角色？
   - 列出建议补充的人物类型

4. **人物关系合理性**
   - 人物之间的关系是否支撑情节冲突？
   - 是否存在关系设定但情节中未体现的情况？

5. **改进建议**
   - 具体的优化建议（3-5条）

请按以下格式输出：

## 匹配度评分
总分：XX/100

## 冗余人物
- 人物A：原因...
- 人物B：原因...

## 缺失人物
- 角色类型A：需要理由...
- 角色类型B：需要理由...

## 关系合理性问题
- 问题1：...
- 问题2：...

## 改进建议
1. ...
2. ...
3. ..."""

        try:
            response = self.llm.invoke(prompt)
            result_text = response.content if hasattr(response, 'content') else str(response)

            # 解析结果
            validation_result = self._parse_validation_result(result_text)
            return validation_result

        except Exception as e:
            logger.warning(f"⚠️ 人物-情节对齐验证失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "score": 0,
                "redundant_characters": [],
                "missing_characters": [],
                "relationship_issues": [],
                "suggestions": []
            }

    def _parse_validation_result(self, text: str) -> Dict[str, Any]:
        """解析验证结果

        Args:
            text: AI返回的文本

        Returns:
            结构化的验证结果
        """
        import re

        result = {
            "success": True,
            "score": 0,
            "redundant_characters": [],
            "missing_characters": [],
            "relationship_issues": [],
            "suggestions": [],
            "raw_text": text
        }

        # 提取评分（容忍冒号粗体/空格变体："总分：85"、"总分**: **85/100"、"总分 85分"）
        score_match = re.search(r'总分[^0-9\n]{0,16}(\d{1,3})', text)
        if score_match:
            result["score"] = min(100, int(score_match.group(1)))

        # 提取冗余人物（容忍 "## 冗余人物"、"## 1. 冗余人物"、"**冗余人物**" 等标题变体）
        redundant_section = re.search(r'#+\s*\d*[.、)]?\s*\*{0,2}冗余人物\*{0,2}\s*\n(.*?)(?=\n#|\Z)', text, re.DOTALL)
        if redundant_section:
            lines = redundant_section.group(1).strip().split('\n')
            for line in lines:
                if line.strip().startswith(('-', '•', '*')):
                    item = line.strip().lstrip('-•*').strip()
                    if item:
                        result["redundant_characters"].append(item)

        # 提取缺失人物
        missing_section = re.search(r'#+\s*\d*[.、)]?\s*\*{0,2}缺失人物\*{0,2}\s*\n(.*?)(?=\n#|\Z)', text, re.DOTALL)
        if missing_section:
            lines = missing_section.group(1).strip().split('\n')
            for line in lines:
                if line.strip().startswith(('-', '•', '*')):
                    item = line.strip().lstrip('-•*').strip()
                    if item:
                        result["missing_characters"].append(item)

        # 提取关系问题
        relationship_section = re.search(r'#+\s*\d*[.、)]?\s*\*{0,2}关系合理性问题\*{0,2}\s*\n(.*?)(?=\n#|\Z)', text, re.DOTALL)
        if relationship_section:
            lines = relationship_section.group(1).strip().split('\n')
            for line in lines:
                if line.strip().startswith(('-', '•', '*')):
                    item = line.strip().lstrip('-•*').strip()
                    if item:
                        result["relationship_issues"].append(item)

        # 提取改进建议
        suggestions_section = re.search(r'## 改进建议\s*\n(.*?)(?=\Z)', text, re.DOTALL)
        if suggestions_section:
            lines = suggestions_section.group(1).strip().split('\n')
            for line in lines:
                if re.match(r'^\d+\.', line.strip()):
                    result["suggestions"].append(line.strip())

        return result

    def suggest_character_for_plot(
        self,
        plot_segment: str,
        existing_characters: List[str],
        world_setting: str
    ) -> Dict[str, Any]:
        """为特定情节段落建议需要的人物

        Args:
            plot_segment: 情节片段
            existing_characters: 已有人物列表
            world_setting: 世界观设定

        Returns:
            建议的人物信息
        """
        existing_chars_str = '、'.join(existing_characters) if existing_characters else '无'

        prompt = f"""请分析以下情节片段，判断是否需要新增人物。

【情节片段】
{plot_segment}

【已有人物】
{existing_chars_str}

【世界观】
{world_setting[:500]}

请分析：
1. 这个情节是否可以用已有人物完成？
2. 如果需要新人物，需要什么类型的角色？
3. 这个角色的核心作用是什么？

请按以下格式输出：

## 是否需要新人物
是/否

## 新人物类型（如果需要）
角色定位：...
核心作用：...
建议特征：...

## 理由
..."""

        try:
            response = self.llm.invoke(prompt)
            result_text = response.content if hasattr(response, 'content') else str(response)

            return {
                "success": True,
                "needs_new_character": "是" in result_text.split('\n')[0],
                "suggestion": result_text
            }

        except Exception as e:
            logger.debug(f"❌ 建议生成失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "needs_new_character": False,
                "suggestion": ""
            }

    def generate_integrated_expansion_plan(
        self,
        characters: str,
        plot_outline: str,
        world_setting: str,
        target_character_count: int,
        target_chapter_count: int
    ) -> Dict[str, Any]:
        """生成人物-大纲协同扩展计划

        Args:
            characters: 当前人物设定
            plot_outline: 当前大纲
            world_setting: 世界观
            target_character_count: 目标人物数
            target_chapter_count: 目标章节数

        Returns:
            协同扩展计划
        """
        # 第一步：验证当前对齐度
        validation = self.validate_character_plot_alignment(
            characters, plot_outline, world_setting
        )

        logger.debug(f"\n📊 当前人物-情节匹配度: {validation['score']}/100")

        if validation['score'] < 60:
            logger.debug("⚠️ 匹配度较低，建议先优化现有人物与情节的关联")

        # 第二步：生成扩展计划
        prompt = f"""请制定人物与大纲的协同扩展计划。

【当前状态】
- 人物数：约{len(characters.split('###'))}个
- 大纲章节：约{len(plot_outline.split('##'))}章
- 匹配度评分：{validation['score']}/100

【目标】
- 目标人物数：{target_character_count}个
- 目标章节数：{target_chapter_count}章

【验证发现的问题】
冗余人物：{', '.join(validation['redundant_characters'][:3]) if validation['redundant_characters'] else '无'}
缺失人物：{', '.join(validation['missing_characters'][:3]) if validation['missing_characters'] else '无'}

请制定扩展计划：

## 第一阶段：优化现有（优先级最高）
1. 处理冗余人物：...
2. 补充缺失人物：...
3. 强化人物-情节关联：...

## 第二阶段：协同扩展
1. 大纲扩展重点：...
2. 配套人物扩展：...
3. 关系网络构建：...

## 第三阶段：验证与调整
1. 验证点：...
2. 调整策略：...

## 扩展顺序建议
先扩展大纲还是先扩展人物？理由：..."""

        try:
            response = self.llm.invoke(prompt)
            plan_text = response.content if hasattr(response, 'content') else str(response)

            return {
                "success": True,
                "validation_score": validation['score'],
                "validation_details": validation,
                "expansion_plan": plan_text,
                "recommended_order": self._extract_expansion_order(plan_text)
            }

        except Exception as e:
            logger.debug(f"❌ 计划生成失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "validation_score": validation['score'],
                "validation_details": validation
            }

    def _extract_expansion_order(self, plan_text: str) -> str:
        """提取扩展顺序建议

        Args:
            plan_text: 计划文本

        Returns:
            'plot_first' | 'character_first' | 'parallel'
        """
        if '先扩展大纲' in plan_text or '优先大纲' in plan_text:
            return 'plot_first'
        elif '先扩展人物' in plan_text or '优先人物' in plan_text:
            return 'character_first'
        else:
            return 'parallel'
