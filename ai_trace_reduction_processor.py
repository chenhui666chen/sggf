"""
AI痕迹降低处理器 - 对生成的小说文本进行二次精修，降低AI痕迹
实现四层精修体系：思想灵魂、结构节奏、人物对话、语言细节
"""
from typing import Dict, Any, List, Optional
import re
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from config import Config


def create_deepseek_llm():
    """创建DeepSeek LLM实例"""
    return ChatOpenAI(
        model_name=Config.MODEL_NAME or "deepseek-reasoner",
        temperature=Config.TEMPERATURE,
        openai_api_key=Config.DEEPSEEK_API_KEY or "",
        openai_api_base=Config.DEEPSEEK_API_BASE or "https://api.deepseek.com/v1"
    )


class AITraceReductionProcessor:
    """AI痕迹降低处理器 - 对生成的文本进行四层精修"""
    
    def __init__(self):
        """初始化处理器"""
        Config.validate()
        self.llm = create_deepseek_llm()
        self.processing_history = []
    
    def reduce_ai_traces(self, content: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        主方法：对内容进行全面的AI痕迹降低处理
        
        Args:
            content: 原始生成的文本内容
            context: 项目上下文（包含作者腔调、人物设定等）
            
        Returns:
            降低AI痕迹后的文本
        """
        if not content or len(content.strip()) == 0:
            return content
        
        print("\n【AI痕迹降低处理】启动四层精修...")
        
        # 第一层：灵魂注入
        print("  第一层：注入作者灵魂和价值观...")
        content = self._inject_author_soul(content, context)
        
        # 第二层：结构节奏优化
        print("  第二层：优化叙事结构和节奏...")
        content = self._optimize_narrative_structure(content, context)
        
        # 第三层：人物对话活化
        print("  第三层：增强人物复杂性和对话真实性...")
        content = self._enhance_dialogue_authenticity(content, context)
        
        # 第四层：语言细节打磨
        print("  第四层：精修语言细节和五感描写...")
        content = self._refine_language_details(content, context)
        
        print("  ✅ 四层精修完成！\n")
        return content
    
    def _inject_author_soul(self, content: str, context: Optional[Dict] = None) -> str:
        """
        第一层：注入作者灵魂
        - 强化独特的价值观和道德立场
        - 增加人性化的思考和矛盾
        """
        soul_prompt = f"""请对以下文本进行"灵魂注入"处理，使其更具人性化和独特性：

【原始文本】
{content}

【处理要求】
1. 强化人物的内心矛盾和道德困境
2. 添加更多的人性化思考和反思
3. 体现独特的价值观（而非中立观点）
4. 让人物的选择显得更有代价和意义
5. 增加对人性复杂性的探讨

【重要】
- 保持原有的情节和字数
- 只修改表达方式和心理描写
- 让读者感受到"作者的灵魂"而非"AI的生成"

请直接输出修改后的文本，不要包含任何说明。"""
        
        messages = [
            SystemMessage(content="你是一位文学编辑，专门为AI生成的文本注入人性化的灵魂。"),
            HumanMessage(content=soul_prompt)
        ]
        
        response = self.llm(messages)
        return response.content
    
    def _optimize_narrative_structure(self, content: str, context: Optional[Dict] = None) -> str:
        """
        第二层：优化叙事结构
        - 打破完美的情节推进
        - 引入生活的随机性
        - 优化节奏和张弛
        """
        structure_prompt = f"""请对以下文本进行"结构优化"处理，使其更具真实感：

【原始文本】
{content}

【处理要求】
1. 检查是否有过于完美的情节推进，如有则添加意外或阻碍
2. 优化节奏：快速推进和缓慢细节交替
3. 添加"生活的随机性"：巧合、误会、计划失败等
4. 确保转折点自然而非生硬
5. 增加悬念的合理延迟

【重要】
- 保持原有的主要情节
- 只在细节处添加真实感
- 避免改变故事的核心走向

请直接输出修改后的文本，不要包含任何说明。"""
        
        messages = [
            SystemMessage(content="你是一位叙事结构专家，专门优化故事的真实感和节奏。"),
            HumanMessage(content=structure_prompt)
        ]
        
        response = self.llm(messages)
        return response.content
    
    def _enhance_dialogue_authenticity(self, content: str, context: Optional[Dict] = None) -> str:
        """
        第三层：增强对话真实性
        - 添加潜台词和言外之意
        - 注入打断、重复、废话
        - 优化对话节奏
        """
        dialogue_prompt = f"""请对以下文本进行"对话真实性"处理，使对话更加自然真实：

【原始文本】
{content}

【处理要求】
1. 检查对话中的潜台词：说A意思是B
2. 添加真实的对话元素：
   - 打断和重复
   - "嗯..."、"那个..."等填充词
   - 因情绪而语无伦次的表现
3. 减少对话的信息密度，让对话更自然
4. 添加沉默和非语言表现
5. 优化对话的节奏和韵律

【重要】
- 保持对话的核心意思
- 只改进表达方式
- 让对话听起来像真实的人在说话

请直接输出修改后的文本，不要包含任何说明。"""
        
        messages = [
            SystemMessage(content="你是一位对话编剧，专门为文本增强对话的真实性和潜台词。"),
            HumanMessage(content=dialogue_prompt)
        ]
        
        response = self.llm(messages)
        return response.content
    
    def _refine_language_details(self, content: str, context: Optional[Dict] = None) -> str:
        """
        第四层：精修语言细节
        - 优化词汇选择
        - 增强句式节奏
        - 注入五感细节
        """
        language_prompt = f"""请对以下文本进行"语言精修"处理，使其更具文学性和感染力：

【原始文本】
{content}

【处理要求】
1. 词汇优化：
   - 用具体词汇替代抽象表述
   - 避免生僻成语和堆砌
   - 使用更有画面感的词汇

2. 句式节奏：
   - 长短句交错，增强节奏感
   - 主被动句灵活切换
   - 合理使用破折号、省略号

3. 五感细节：
   - 添加听觉细节（声音、音乐等）
   - 添加嗅觉细节（气味、香气等）
   - 添加触觉细节（质感、温度等）
   - 添加味觉细节（味道、滋味等）
   - 添加本体感（身体感受）

4. 移除陈词滥调和套路表述

【重要】
- 保持原有的内容和字数
- 只改进表达方式
- 让文字更有质感和沉浸感

请直接输出修改后的文本，不要包含任何说明。"""
        
        messages = [
            SystemMessage(content="你是一位文学语言大师，专门精修文本的语言细节和五感描写。"),
            HumanMessage(content=language_prompt)
        ]
        
        response = self.llm(messages)
        return response.content
    
    def get_processing_history(self) -> List[Dict[str, Any]]:
        """获取处理历史"""
        return self.processing_history
    
    def clear_history(self):
        """清空处理历史"""
        self.processing_history.clear()


# 便捷函数
def reduce_ai_traces(content: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    便捷函数：快速降低AI痕迹
    
    Args:
        content: 原始文本
        context: 项目上下文
        
    Returns:
        降低AI痕迹后的文本
    """
    processor = AITraceReductionProcessor()
    return processor.reduce_ai_traces(content, context)

