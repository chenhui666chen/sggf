"""
内容创作进化系统 - 变体路由器

负责：
1. 5%采样决策（每20次生成1次使用变体）
2. 变体选择（使用当前测试变体或最佳版本）
3. 记录路由决策
"""
import hashlib
import random
import logging
from datetime import datetime
from typing import Tuple, Optional

from .models import PromptVariant, GenerationRecord, GenerationStage
from .storage import get_storage

logger = logging.getLogger(__name__)


class VariantRouter:
    """变体流量路由器"""
    
    def __init__(self, variant_ratio: float = 0.05):
        """
        初始化路由器
        
        Args:
            variant_ratio: 变体测试比例，默认5%（每20次1次）
        """
        self.variant_ratio = variant_ratio
        self.storage = get_storage()
    
    def should_use_variant(self, project_id: int, chapter_number: int = 0) -> bool:
        """
        决定是否使用变体提示词
        
        使用项目ID+章节号做哈希，保证：
        1. 同项目同章节始终使用同一决策（避免重生成时切换）
        2. 整体比例约为5%
        
        Args:
            project_id: 项目ID
            chapter_number: 章节号（可选）
            
        Returns:
            是否使用变体
        """
        # 使用哈希确保决策一致性
        key = f"{project_id}_{chapter_number}_{datetime.now().strftime('%Y%m%d')}"
        hash_value = int(hashlib.md5(key.encode()).hexdigest(), 16)
        
        # 取模判断是否落入变体区间
        is_variant = (hash_value % 100) < (self.variant_ratio * 100)
        
        if is_variant:
            logger.info(f"🧪 项目 {project_id} 章节 {chapter_number} 使用变体测试")
        
        return is_variant
    
    def get_prompt_for_generation(
        self,
        module_name: str,
        genre: str,
        project_id: int,
        chapter_number: int = 0,
        default_prompt: str = ""
    ) -> Tuple[str, str, bool]:
        """
        获取生成用的提示词
        
        Args:
            module_name: 模块名（如 chapter_prompt, outline_prompt）
            genre: 题材
            project_id: 项目ID
            chapter_number: 章节号
            default_prompt: 默认提示词（无变体时使用）
            
        Returns:
            (prompt_text, version_id, is_variant)
        """
        is_variant = self.should_use_variant(project_id, chapter_number)
        
        if is_variant:
            # 尝试获取当前激活的测试变体
            variant = self.storage.get_active_variant(module_name, genre)
            if variant:
                logger.info(f"🧪 使用测试变体: {variant.variant_id}")
                return variant.prompt_text, variant.variant_id, True
            else:
                # 没有激活的变体，使用最佳版本
                best = self.storage.get_current_best(module_name, genre)
                if best:
                    logger.info(f"📌 无测试变体，使用最佳版本: {best.variant_id}")
                    return best.prompt_text, best.variant_id, False
        else:
            # 正常流量，使用最佳版本
            best = self.storage.get_current_best(module_name, genre)
            if best:
                return best.prompt_text, best.variant_id, False
        
        # 都没有，使用默认
        logger.debug(f"📝 使用默认提示词: {module_name}/{genre}")
        return default_prompt, "default", False
    
    def record_generation(
        self,
        project_id: int,
        chapter_id: Optional[int],
        genre: str,
        stage: GenerationStage,
        prompt_version_id: str,
        prompt_module: str,
        is_variant: bool,
        content: str,
        ai_score: Optional[dict] = None
    ) -> GenerationRecord:
        """
        记录一次生成
        
        Args:
            project_id: 项目ID
            chapter_id: 章节ID（如果是章节生成）
            genre: 题材
            stage: 生成阶段
            prompt_version_id: 使用的提示词版本ID
            prompt_module: 提示词模块名
            is_variant: 是否是变体测试
            content: 生成的内容
            ai_score: AI质量评分（如果有）
            
        Returns:
            生成记录对象
        """
        from .models import AIQualityScore, ImplicitFeedback, FeedbackStatus
        
        # 创建记录
        record = GenerationRecord(
            project_id=project_id,
            chapter_id=chapter_id,
            stage=stage,
            genre=genre,
            prompt_version_id=prompt_version_id,
            prompt_module=prompt_module,
            is_variant=is_variant,
            generated_content=content[:500] if content else "",  # 只存摘要
            content_length=len(content) if content else 0,
        )
        
        # 如果有AI评分，添加进去
        if ai_score:
            record.ai_quality_score = AIQualityScore(
                genre_fit=ai_score.get("genre_fit", 0),
                cool_point=ai_score.get("cool_point", 0),
                rhythm=ai_score.get("rhythm", 0),
                consistency=ai_score.get("consistency", 0),
                hook=ai_score.get("hook", 0),
                writing=ai_score.get("writing", 0),
            )
        
        # 初始化隐式反馈（待后续收集）
        record.implicit_feedback = ImplicitFeedback(
            original_length=len(content) if content else 0,
            status=FeedbackStatus.PENDING
        )
        
        # 保存记录
        self.storage.save_generation_record(record)
        
        # 如果是变体，更新会话统计
        if is_variant:
            session = self.storage.get_or_create_session(prompt_module, genre)
            session.total_samples += 1
            self.storage.save_session(session)
        
        logger.info(f"📊 记录生成: project={project_id}, variant={is_variant}")
        return record


class VariantGenerator:
    """变体生成器 - 使用AI随机生成变体方向"""
    
    def __init__(self, llm_caller=None):
        """
        初始化变体生成器
        
        Args:
            llm_caller: LLM调用函数，签名为 async (prompt, temperature) -> str
        """
        self.llm_caller = llm_caller
        self.storage = get_storage()
    
    async def generate_variant(
        self,
        current_prompt: str,
        module_name: str,
        genre: str,
        recent_scores: list = None,
        context: dict = None
    ) -> Optional[PromptVariant]:
        """
        生成一个新的提示词变体（AI随机探索方向）
        
        Args:
            current_prompt: 当前提示词
            module_name: 模块名
            genre: 题材
            recent_scores: 最近的评分数据（可选，用于指导优化方向）
            context: 额外上下文（可选）
            
        Returns:
            新的变体对象
        """
        if not self.llm_caller:
            logger.warning("未配置LLM调用器，无法生成变体")
            return None
        
        # 构建元优化提示词
        meta_prompt = self._build_meta_prompt(
            current_prompt, 
            module_name, 
            genre, 
            recent_scores,
            context
        )
        
        try:
            # 使用较高温度增加创造性
            result = await self.llm_caller(meta_prompt, temperature=0.9)
            
            # 解析结果
            new_prompt, mutation_desc = self._parse_variant_result(result)
            
            if not new_prompt:
                logger.warning("变体生成失败：无法解析结果")
                return None
            
            # 创建变体对象
            current_best = self.storage.get_current_best(module_name, genre)
            parent_id = current_best.variant_id if current_best else None
            
            variant = PromptVariant(
                module_name=module_name,
                genre=genre,
                prompt_text=new_prompt,
                parent_id=parent_id,
                mutation_description=mutation_desc,
                is_active=True,  # 激活用于测试
                is_current_best=False,
            )
            
            # 保存变体
            self.storage.save_variant(variant)
            logger.info(f"🧬 生成新变体: {variant.variant_id}, 方向: {mutation_desc[:50]}...")
            
            return variant
            
        except Exception as e:
            logger.error(f"变体生成异常: {e}")
            return None
    
    def _build_meta_prompt(
        self,
        current_prompt: str,
        module_name: str,
        genre: str,
        recent_scores: list = None,
        context: dict = None
    ) -> str:
        """构建元优化提示词（让AI自主决定优化方向）"""
        
        # 题材专属优化提示
        genre_hints = self._get_genre_optimization_hints(genre)
        
        # 最近评分反馈
        score_feedback = ""
        if recent_scores:
            avg_score = sum(recent_scores) / len(recent_scores)
            score_feedback = f"""
【最近效果反馈】
- 平均隐式反馈分数：{avg_score:.1f}/100
- 样本数量：{len(recent_scores)}
- 需要重点改进的方向：{'整体效果较好，可尝试微调' if avg_score > 70 else '需要较大改进'}
"""
        
        prompt = f"""你是一个网文创作提示词优化专家。请分析以下提示词，并自主探索一个创新的优化方向。

【当前提示词】
{current_prompt[:2000]}

【目标模块】{module_name}
【目标题材】{genre}

{genre_hints}

{score_feedback}

【你的任务】
1. 分析当前提示词的优缺点
2. **自主思考**一个可能提升生成质量的创新方向（不要拘泥于常规优化，可以大胆尝试）
3. 基于你想到的方向，生成一个改进版本

【可能的探索方向示例（仅供参考，鼓励你想出更有创意的方向）】
- 强化特定情感基调
- 引入新的叙事技巧
- 调整节奏控制策略
- 增强人物刻画深度
- 优化场景描写方式
- 改变开头/结尾策略
- 引入特定的修辞手法
- 调整对话与叙述比例
- 其他你想到的任何方向...

【输出格式】
<mutation_direction>
（你想到的优化方向，一句话描述）
</mutation_direction>

<improved_prompt>
（改进后的完整提示词）
</improved_prompt>
"""
        return prompt
    
    def _get_genre_optimization_hints(self, genre: str) -> str:
        """获取题材专属的优化提示"""
        hints = {
            "修仙": "【题材特点】读者期待：境界突破爽感、资源获取、越级战斗、宗门政治。优化时注意强化这些爽点的铺垫和释放。",
            "玄幻": "【题材特点】读者期待：血脉觉醒、力量体系、热血战斗、命运逆袭。优化时注意战斗场面的张力和节奏。",
            "都市": "【题材特点】读者期待：打脸逆袭、商战博弈、财富跨越、人际权谋。优化时注意情节反转的爽感和现实感。",
            "悬疑": "【题材特点】读者期待：线索布局、反转揭秘、紧张氛围、逻辑缜密。优化时注意悬念控制和信息释放节奏。",
            "言情": "【题材特点】读者期待：心动时刻、情感互动、甜虐交织、情感里程碑。优化时注意情感描写的细腻和代入感。",
            "耽美": "【题材特点】读者期待：暧昧张力、情感递进、人物魅力、表白爽点。优化时注意角色互动的化学反应。",
            "科幻": "【题材特点】读者期待：科技突破、星际探索、概念新颖、世界观宏大。优化时注意科幻概念的呈现和故事融合。",
            "纯文学": "【题材特点】读者期待：诗意表达、内心挖掘、人性探讨、顿悟时刻。优化时注意文学性和思想深度。",
        }
        return hints.get(genre, "【通用题材】注意叙事节奏、人物刻画、情节吸引力的平衡。")
    
    def _parse_variant_result(self, result: str) -> Tuple[str, str]:
        """解析变体生成结果"""
        import re
        
        # 提取优化方向
        direction_match = re.search(r'<mutation_direction>(.*?)</mutation_direction>', result, re.DOTALL)
        mutation_desc = direction_match.group(1).strip() if direction_match else "AI随机优化"
        
        # 提取改进后的提示词
        prompt_match = re.search(r'<improved_prompt>(.*?)</improved_prompt>', result, re.DOTALL)
        new_prompt = prompt_match.group(1).strip() if prompt_match else ""
        
        return new_prompt, mutation_desc


# 全局实例
_router_instance: Optional[VariantRouter] = None


def get_router() -> VariantRouter:
    """获取路由器实例（单例）"""
    global _router_instance
    if _router_instance is None:
        _router_instance = VariantRouter()
    return _router_instance
