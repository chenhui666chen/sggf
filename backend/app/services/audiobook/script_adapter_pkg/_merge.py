"""
片段合并与验证 Mixin

包含 _merge_short_segments, _validate_semantic_integrity, _is_natural_short_utterance 方法
"""
import logging
from typing import List

from ._dataclasses import ScriptSegment

logger = logging.getLogger(__name__)


class MergeMixin:
    """片段合并与验证方法"""
    
    def get_statistics(self, segments: List[ScriptSegment]) -> dict:
        """获取剧本统计"""
        return {
            "total_segments": len(segments),
            "dialogue_count": sum(1 for s in segments if s.type == "dialogue"),
            "narration_count": sum(1 for s in segments if s.type == "narration"),
            "monologue_count": sum(1 for s in segments if s.type == "monologue"),
            "unique_speakers": len(set(s.speaker for s in segments)),
            "emotion_distribution": self._count_emotions(segments),
            "sound_effects_count": sum(len(s.sound_effects) for s in segments),
            "music_cues_count": sum(1 for s in segments if s.music_cue)
        }
    
    def _count_emotions(self, segments: List[ScriptSegment]) -> dict:
        """统计情感分布"""
        emotions = {}
        for seg in segments:
            emotions[seg.emotion] = emotions.get(seg.emotion, 0) + 1
        return emotions
    
    def _merge_short_segments(self, segments: List[ScriptSegment], min_length: int = 10) -> List[ScriptSegment]:
        """
        合并过短片段，确保语义完整性
        
        策略：
        1. 短对话（<10字）合并到前后的旁白或同角色对话
        2. 短旁白（<15字）合并到相邻旁白
        3. 保持情感一致性
        4. 对部分"自然短句"（如"好。""行。"）允许保留，不强制合并
        
        Args:
            segments: 原始片段列表
            min_length: 最小片段长度（字数）
        
        Returns:
            合并后的片段列表
        """
        if not segments:
            return segments
        
        merged = []
        i = 0
        
        while i < len(segments):
            current = segments[i]
            current_len = len(current.text)

            if current_len < min_length and self._is_natural_short_utterance(current, min_length):
                merged.append(current)
                i += 1
                continue
            
            if current_len < min_length and i + 1 < len(segments):
                next_seg = segments[i + 1]
                
                if current.type == "dialogue" and next_seg.type == "dialogue":
                    if current.speaker != next_seg.speaker:
                        merged.append(current)
                        i += 1
                        continue
                
                if current.type == "dialogue":
                    if next_seg.type == "narration" or next_seg.speaker == current.speaker:
                        if next_seg.type == "narration":
                            merged_text = f'"{current.text}"，{next_seg.text}'
                        else:
                            merged_text = f"{current.text}{next_seg.text}"
                        
                        merged_segment = ScriptSegment(
                            type=next_seg.type,
                            text=merged_text,
                            speaker=next_seg.speaker,
                            emotion=next_seg.emotion,
                            performance_notes=f"{current.performance_notes}; {next_seg.performance_notes}".strip("; "),
                            pause_before=current.pause_before,
                            pause_after=next_seg.pause_after,
                            sound_effects=(current.sound_effects or []) + (next_seg.sound_effects or []),
                            music_cue=next_seg.music_cue or current.music_cue,
                            original_text=f"{current.original_text} {next_seg.original_text}",
                            adaptation_reason=f"合并短对话({current_len}字)与后续片段，保持语义完整"
                        )
                        merged.append(merged_segment)
                        i += 2
                        continue
                
                elif current.type == "narration" and next_seg.type == "narration":
                    merged_text = f"{current.text}{next_seg.text}"
                    merged_segment = ScriptSegment(
                        type="narration",
                        text=merged_text,
                        speaker="旁白",
                        emotion=next_seg.emotion,
                        performance_notes=f"{current.performance_notes} + {next_seg.performance_notes}".strip(),
                        pause_before=current.pause_before,
                        pause_after=next_seg.pause_after,
                        sound_effects=(current.sound_effects or []) + (next_seg.sound_effects or []),
                        music_cue=next_seg.music_cue or current.music_cue,
                        original_text=f"{current.original_text} {next_seg.original_text}",
                        adaptation_reason=f"合并短旁白: {current.adaptation_reason}"
                    )
                    merged.append(merged_segment)
                    i += 2
                    continue
            
            merged.append(current)
            i += 1
        
        logger.info(f"片段合并统计: {len(segments)} -> {len(merged)} (减少 {len(segments) - len(merged)} 个短片段)")
        return merged
    
    def _validate_semantic_integrity(self, segments: List[ScriptSegment]) -> List[ScriptSegment]:
        """
        语义完整性验证：检查并报告过短片段
        
        Args:
            segments: 片段列表
        
        Returns:
            验证后的片段列表（如果有问题会警告）
        """
        min_length = 15
        if self.strategy and hasattr(self.strategy, 'min_segment_length'):
            min_length = self.strategy.min_segment_length
        
        short_segments = []
        natural_short_segments = []
        for idx, seg in enumerate(segments):
            seg_len = len(seg.text)
            if seg_len < min_length:
                if self._is_natural_short_utterance(seg, min_length):
                    natural_short_segments.append({
                        "index": idx,
                        "text": seg.text,
                        "length": seg_len,
                        "type": seg.type,
                        "speaker": seg.speaker
                    })
                else:
                    short_segments.append({
                        "index": idx,
                        "text": seg.text,
                        "length": seg_len,
                        "type": seg.type,
                        "speaker": seg.speaker
                    })
        
        if natural_short_segments:
            logger.info(f"检测到 {len(natural_short_segments)} 个自然短片段（对白/独白/节奏短旁白），已从语义错误统计中排除")
        
        if short_segments:
            logger.warning(f"语义完整性验证失败：发现 {len(short_segments)} 个过短片段 (<{min_length}字)：")
            for item in short_segments[:5]:
                logger.warning(f"   [{item['index']}] {item['type']} - {item['speaker']}: '{item['text']}' ({item['length']}字)")
            if len(short_segments) > 5:
                logger.warning(f"   ... 还有 {len(short_segments) - 5} 个过短片段未显示")
            logger.warning("建议：调整LLM Prompt或增强合并逻辑")
        else:
            logger.info(f"语义完整性验证通过：所有片段均 >={min_length}字，或属于自然短句")
        
        return segments
    
    def _is_natural_short_utterance(self, seg: ScriptSegment, min_length: int) -> bool:
        """
        判断一个短片段是否属于"自然短句/节奏短旁白"，例如：
        - 简短而完整的对白/独白（如"好。""行。"）
        - 章节标题或有声小说节奏点短旁白（如"它在呼吸。""陆衍不信邪。"）
        - 带完整终止标点且长度虽短但语义完整
        - 强烈情绪的短句（惊讶/愤怒/紧张）
        这类片段允许在长度上略低于 min_length，而不视为语义错误。
        """
        text = (seg.text or "").strip()
        if not text:
            return False

        length = len(text)
        if length >= min_length:
            return False

        if "..." in text or "……" in text:
            return False

        if seg.type == "narration":
            return self._is_natural_short_narration_beat(text, seg)

        if seg.type not in ("dialogue", "monologue"):
            return False

        whitelist = {
            "嗯", "哦", "好", "好吧", "好啊", "行", "可以", "不行", "不", "是",
            "别闹", "闭嘴", "滚", "快走", "走", "别说了", "住口", "够了",
            "什么", "啊", "嗯？", "哈？", "真的？", "是吗",
            "等等。", "等一下。", "停。", "不对。", "有意思。", "明白了。",
            "这不可能。", "你说什么？", "怎么回事？", "为什么？",
        }
        if text in whitelist:
            return True
        
        strong_emotions = ["angry", "tense", "excited", "shocked", "fearful"]
        if seg.emotion in strong_emotions and text.endswith(("!", "！", "?", "？")):
            if length >= 8:
                return True

        if text[-1] in ("。", "！", "?", "？", "!") and length >= 3:
            return True

        return False

    def _is_natural_short_narration_beat(self, text: str, seg: ScriptSegment) -> bool:
        """判断短旁白是否是可保留的有声小说节奏点，而非破碎语义片段。"""
        if text.startswith("第") and "章" in text[:8] and len(text) >= 6:
            return True

        if not text.endswith(("。", "！", "?", "？", "!")):
            return False

        stripped_text = text.rstrip("。！?？！!")
        if len(stripped_text) < 4:
            return False

        semantic_markers = (
            "是",
            "在",
            "不",
            "就是",
            "只有",
            "唯一",
            "机会",
            "掌心",
            "裂隙",
            "呼吸",
            "信邪",
        )
        if any(marker in stripped_text for marker in semantic_markers):
            return True

        strong_emotions = {"tense", "excited", "shocked", "fearful", "mysterious", "solemn"}
        return seg.emotion in strong_emotions and len(stripped_text) >= 8
