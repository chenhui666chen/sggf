"""
文本解析器 - 智能分离对话与旁白

核心功能：
1. 对话/旁白识别（正则+AI辅助）
2. 说话人识别（复用角色识别能力）
3. 情感标注（复用author_voice_system）
"""
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextSegment:
    """文本片段"""
    type: str  # "dialogue" | "narration"
    text: str
    speaker: str  # 角色名 or "旁白"
    emotion: str  # "neutral" | "happy" | "sad" | "angry" | "excited"
    position: int  # 在原文中的位置
    context_before: str = ""  # 前文上下文（用于情感分析）
    context_after: str = ""   # 后文上下文


class TextParser:
    """
    文本解析器 - 智能解析章节内容
    
    复用能力：
    - CharacterDesignerAgent: 角色识别
    - author_voice_system: 情感分析
    """
    
    def __init__(self, knowledge_base=None):
        # 暂时不使用 knowledge_base，简化实现
        # from app.services.agents.knowledge_base import NovelKnowledgeBase
        # self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.knowledge_base = knowledge_base
        
        # 对话标记模式（支持多种引号）
        self.dialogue_patterns = [
            r'[""]([^"""]+)[""]',  # 双引号
            r'「([^」]+)」',        # 日式引号
            r'『([^』]+)』',        # 书名号式
        ]
    
    async def parse_chapter(
        self,
        chapter_content: str,
        character_list: Optional[List[str]] = None
    ) -> List[TextSegment]:
        """
        解析章节内容
        
        Args:
            chapter_content: 章节文本
            character_list: 已知角色列表（可选）
        
        Returns:
            文本片段列表
        """
        logger.info(f"📖 开始解析章节，长度: {len(chapter_content)} 字符")
        
        # 1. 分离对话和旁白
        segments = self._split_dialogue_narration(chapter_content)
        logger.info(f"   ✅ 识别到 {len(segments)} 个片段")
        
        # 2. 识别说话人
        if character_list:
            segments = self._identify_speakers(segments, character_list)
        
        # 3. 情感标注
        segments = await self._tag_emotions(segments)
        
        return segments
    
    def _split_dialogue_narration(self, text: str) -> List[TextSegment]:
        """
        分离对话和旁白
        
        策略：
        1. 正则匹配引号内容为对话
        2. 引号外内容为旁白
        3. 保持原文顺序
        4. **关键优化**：从对话前的旁白中剔除引导语（如"XXX说："、"XXX问道："等）
        """
        segments = []
        position = 0
        
        # 说话人引导语模式（如"张三说："、"他问道："等）
        speaker_intro_pattern = r'[，。；]?([^，。！？；：""\n]{0,15}(?:说|道|问|答|笑|叹|喊|叫|开口|沉声|冷笑|轻声|嘀咕|低语|高声)[：:])$'
        
        # 逐段处理
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                continue
            
            # 查找所有对话
            dialogues = []
            for pattern in self.dialogue_patterns:
                for match in re.finditer(pattern, paragraph):
                    dialogues.append({
                        'text': match.group(1),
                        'start': match.start(),
                        'end': match.end()
                    })
            
            # 按位置排序
            dialogues.sort(key=lambda x: x['start'])
            
            # 提取对话和旁白
            last_pos = 0
            for dialogue in dialogues:
                # 对话前的旁白（原始文本）
                narration_before = paragraph[last_pos:dialogue['start']].strip()
                
                if narration_before:
                    # **关键修复**：检查是否以说话人引导语结尾（如"张三说："）
                    # 如果是，则将引导语从旁白中移除，避免旁白和对话混淆
                    match = re.search(speaker_intro_pattern, narration_before)
                    if match:
                        # 移除说话人引导语
                        intro_text = match.group(1)
                        narration_text = narration_before[:match.start()].strip()
                        
                        # 只有当移除引导语后还有实质内容时，才添加旁白片段
                        if narration_text:
                            segments.append(TextSegment(
                                type="narration",
                                text=narration_text,
                                speaker="旁白",
                                emotion="neutral",
                                position=position
                            ))
                            position += len(narration_text)
                    else:
                        # 没有说话人引导语，直接使用全部文本
                        segments.append(TextSegment(
                            type="narration",
                            text=narration_before,
                            speaker="旁白",
                            emotion="neutral",
                            position=position
                        ))
                        position += len(narration_before)
                
                # 对话
                dialogue_text = dialogue['text'].strip()
                if dialogue_text:  # 过滤空对话
                    segments.append(TextSegment(
                        type="dialogue",
                        text=dialogue_text,
                        speaker="未知",  # 待识别
                        emotion="neutral",
                        position=position
                    ))
                    position += len(dialogue_text)
                
                last_pos = dialogue['end']
            
            # 段落末尾的旁白
            final_narration = paragraph[last_pos:].strip()
            if final_narration:
                segments.append(TextSegment(
                    type="narration",
                    text=final_narration,
                    speaker="旁白",
                    emotion="neutral",
                    position=position
                ))
                position += len(final_narration)
        
        return segments
    
    def _identify_speakers(
        self, 
        segments: List[TextSegment],
        character_list: List[str]
    ) -> List[TextSegment]:
        """
        识别说话人
        
        策略：
        1. 查找对话前后的"XXX说"、"XXX道"等标记
        2. 基于上下文推断（连续对话的说话人交替）
        3. 匹配已知角色名
        """
        for i, segment in enumerate(segments):
            if segment.type != "dialogue":
                continue
            
            # 获取前后文
            context_before = ""
            context_after = ""
            
            if i > 0:
                context_before = segments[i-1].text
            if i < len(segments) - 1:
                context_after = segments[i+1].text
            
            # 查找说话人标记
            speaker = self._extract_speaker_from_context(
                context_before, 
                context_after,
                character_list
            )
            
            segment.speaker = speaker or "未知角色"
            segment.context_before = context_before[-50:]  # 保留最后50字
            segment.context_after = context_after[:50]      # 保留前50字
        
        return segments
    
    def _extract_speaker_from_context(
        self,
        before: str,
        after: str,
        character_list: List[str]
    ) -> Optional[str]:
        """从上下文提取说话人"""
        # 常见说话标记
        patterns = [
            r'([^，。！？：""]+)(?:说|道|问|答|笑|叹|喊|叫)[:：]?',
            r'([^，。！？：""]+)(?:开口|沉声|冷笑|轻声)[:：]?',
        ]
        
        # 先检查后文
        for pattern in patterns:
            match = re.search(pattern, after[:30])
            if match:
                name = match.group(1).strip()
                # 匹配角色列表
                for char in character_list:
                    if char in name or name in char:
                        return char
        
        # 再检查前文
        for pattern in patterns:
            match = re.search(pattern, before[-30:])
            if match:
                name = match.group(1).strip()
                for char in character_list:
                    if char in name or name in char:
                        return char
        
        return None
    
    async def _tag_emotions(
        self, 
        segments: List[TextSegment]
    ) -> List[TextSegment]:
        """
        情感标注
        
        复用 author_voice_system 的情感分析能力
        
        简化版：基于关键词匹配
        高级版：可调用LLM进行情感分析
        """
        # 情感关键词库
        emotion_keywords = {
            "happy": ["笑", "高兴", "开心", "哈哈", "欣喜", "愉快"],
            "sad": ["哭", "伤心", "难过", "悲伤", "眼泪", "哀"],
            "angry": ["怒", "生气", "愤怒", "吼", "喝", "骂"],
            "excited": ["激动", "兴奋", "惊", "啊", "天啊", "！！"],
            "calm": ["平静", "淡淡", "轻声", "缓缓", "沉默"],
        }
        
        for segment in segments:
            # 分析文本 + 上下文
            full_context = segment.context_before + segment.text + segment.context_after
            
            # 情感得分
            emotion_scores = {}
            for emotion, keywords in emotion_keywords.items():
                score = sum(1 for kw in keywords if kw in full_context)
                if score > 0:
                    emotion_scores[emotion] = score
            
            # 选择最高分情感
            if emotion_scores:
                segment.emotion = max(emotion_scores.items(), key=lambda x: x[1])[0]
            else:
                segment.emotion = "neutral"
        
        return segments
    
    def get_statistics(self, segments: List[TextSegment]) -> Dict[str, Any]:
        """获取解析统计"""
        dialogue_count = sum(1 for s in segments if s.type == "dialogue")
        narration_count = len(segments) - dialogue_count
        
        speakers = set(s.speaker for s in segments if s.type == "dialogue")
        emotions = {}
        for s in segments:
            emotions[s.emotion] = emotions.get(s.emotion, 0) + 1
        
        return {
            "total_segments": len(segments),
            "dialogue_count": dialogue_count,
            "narration_count": narration_count,
            "unique_speakers": len(speakers),
            "speakers": list(speakers),
            "emotion_distribution": emotions
        }
