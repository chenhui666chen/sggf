"""
对话真实性模块 - 增强对话的真实性、潜台词和自然感
"""
from typing import Dict, Any, List, Optional
import re
from langchain_community.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from .config import Config


def create_deepseek_llm(task_type: str = "default"):
    """创建LLM实例"""
    return ChatOpenAI(
        model_name=Config.MODEL_NAME or "deepseek-reasoner",
        temperature=Config.TEMPERATURE,
        openai_api_key=Config.DEEPSEEK_API_KEY or "",
        openai_api_base=Config.DEEPSEEK_API_BASE or "https://api.deepseek.com/v1"
    )


class DialogueAuthenticityEngine:
    """对话真实性引擎 - 增强对话的真实感和潜台词"""
    
    def __init__(self):
        """初始化引擎"""
        Config.validate()
        self.llm = create_deepseek_llm()
        
        # 填充词库
        self.filler_words = [
            "嗯", "那个", "你知道的", "我是说", "就是", "算了",
            "呃", "额", "嗯...嗯", "怎么说呢", "反正", "总之"
        ]
        
        # 打断模式
        self.interruption_patterns = [
            "等等，我想说的是",
            "不对，我的意思是",
            "我说错了，应该是",
            "等一下，让我重新说"
        ]
        
        # 潜台词示例库
        self.subtext_examples = {
            "我很好": "我其实不好，但我不想让你担心",
            "没关系": "其实我很在意，但我选择隐忍",
            "随便": "我有想法，但我不想强加给你",
            "我不知道": "我知道但我不想说，或者我真的不知道"
        }
    
    def enhance_dialogue(self, content: str) -> str:
        """
        增强对话的真实性
        
        Args:
            content: 原始内容
            
        Returns:
            增强后的内容
        """
        # 提取对话部分
        dialogues = self._extract_dialogues(content)
        
        if not dialogues:
            return content
        
        # 对每个对话进行增强
        enhanced_content = content
        for original_dialogue in dialogues:
            enhanced_dialogue = self._enhance_single_dialogue(original_dialogue)
            enhanced_content = enhanced_content.replace(original_dialogue, enhanced_dialogue, 1)
        
        return enhanced_content
    
    def _extract_dialogues(self, content: str) -> List[str]:
        """提取对话部分"""
        # 匹配中文引号内的对话
        pattern = r'["""]([^""]*)["""]'
        matches = re.findall(pattern, content)
        return matches
    
    def _enhance_single_dialogue(self, dialogue: str) -> str:
        """增强单个对话"""
        # 检查是否需要添加潜台词
        for surface, subtext in self.subtext_examples.items():
            if surface in dialogue:
                # 添加潜台词提示
                return f'"{dialogue}"（潜台词：{subtext}）'
        
        # 随机添加填充词
        if len(dialogue) > 10 and "嗯" not in dialogue:
            # 在对话开头或中间添加填充词
            import random
            if random.random() > 0.5:
                filler = random.choice(self.filler_words)
                dialogue = f"{filler}...{dialogue}"
        
        return f'"{dialogue}"'
    
    def add_subtext_to_dialogue(self, dialogue: str, subtext: str) -> str:
        """
        为对话添加潜台词
        
        Args:
            dialogue: 对话内容
            subtext: 潜台词
            
        Returns:
            带有潜台词的对话
        """
        return f'"{dialogue}"（潜台词：{subtext}）'
    
    def inject_interruptions(self, dialogue: str) -> str:
        """
        注入打断和重复
        
        Args:
            dialogue: 对话内容
            
        Returns:
            包含打断的对话
        """
        import random
        
        # 随机选择是否添加打断
        if random.random() > 0.7:
            interruption = random.choice(self.interruption_patterns)
            # 在对话中间插入打断
            mid_point = len(dialogue) // 2
            return f'"{dialogue[:mid_point]}..."\n"不对，我的意思是{dialogue[mid_point:]}"'
        
        return f'"{dialogue}"'
    
    def add_filler_words(self, dialogue: str) -> str:
        """
        添加填充词和情绪词
        
        Args:
            dialogue: 对话内容
            
        Returns:
            添加了填充词的对话
        """
        import random
        
        if random.random() > 0.6:
            filler = random.choice(self.filler_words)
            return f'"{filler}...{dialogue}"'
        
        return f'"{dialogue}"'
    
    def optimize_dialogue_rhythm(self, content: str) -> str:
        """
        优化对话节奏
        
        Args:
            content: 原始内容
            
        Returns:
            优化后的内容
        """
        optimization_prompt = f"""请优化以下文本中的对话节奏，使其更加自然真实：

【原始文本】
{content}

【优化要求】
1. 对话不应该过于高效和信息密集
2. 添加真实的对话元素：打断、重复、犹豫
3. 使用"嗯"、"那个"等填充词
4. 让对话显得更像真实的人在交流
5. 保留对话的核心意思，只改进表达方式

【重要】
- 不要改变对话的主要内容
- 只改进表达方式和节奏
- 让对话听起来更自然

请直接输出优化后的文本，不要包含任何说明。"""
        
        messages = [
            SystemMessage(content="你是一位对话编剧，专门优化对话的真实性和节奏。"),
            HumanMessage(content=optimization_prompt)
        ]

        response = self.llm.invoke(messages)
        return response.content
    
    def analyze_dialogue_authenticity(self, content: str) -> Dict[str, Any]:
        """
        分析对话的真实性
        
        Args:
            content: 内容
            
        Returns:
            真实性分析结果
        """
        result = {
            "authenticity_score": 0.0,
            "issues": [],
            "suggestions": []
        }
        
        score = 100.0
        
        # 检查是否有足够的对话
        dialogue_count = len(self._extract_dialogues(content))
        if dialogue_count == 0:
            result["issues"].append("缺少对话内容")
            score -= 20
        elif dialogue_count < 3:
            result["suggestions"].append("建议增加更多对话")
            score -= 10
        
        # 检查是否有填充词
        has_filler = any(filler in content for filler in self.filler_words)
        if not has_filler:
            result["suggestions"].append("建议添加填充词（如'嗯'、'那个'等）以增加真实感")
            score -= 5
        
        # 检查是否有打断
        has_interruption = "..." in content or "不对" in content or "等等" in content
        if not has_interruption:
            result["suggestions"].append("建议添加对话打断以增加真实感")
            score -= 5
        
        # 检查对话长度
        for dialogue in self._extract_dialogues(content):
            if len(dialogue) > 100:
                result["suggestions"].append(f"对话过长：'{dialogue[:50]}...'，建议分割")
                score -= 3
        
        result["authenticity_score"] = max(0, score)
        return result


# 便捷函数
def enhance_dialogue_authenticity(content: str) -> str:
    """便捷函数：增强对话真实性"""
    engine = DialogueAuthenticityEngine()
    return engine.enhance_dialogue(content)


def optimize_dialogue_rhythm(content: str) -> str:
    """便捷函数：优化对话节奏"""
    engine = DialogueAuthenticityEngine()
    return engine.optimize_dialogue_rhythm(content)


def analyze_dialogue_authenticity(content: str) -> Dict[str, Any]:
    """便捷函数：分析对话真实性"""
    engine = DialogueAuthenticityEngine()
    return engine.analyze_dialogue_authenticity(content)

