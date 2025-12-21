"""
智能化音乐系统 - 高潮点检测与情绪曲线分析

核心功能：
1. ClimaxDetector - 高潮点智能检测器
2. EmotionCurveAnalyzer - 情绪曲线智能分析器
3. IntelligentMusicEnhancer - 音乐智能增强器
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ClimaxType(str, Enum):
    """高潮类型"""
    BATTLE = "battle"  # 战斗高潮
    REVELATION = "revelation"  # 真相揭示
    EMOTIONAL = "emotional"  # 情感高潮
    TURNING_POINT = "turning_point"  # 剧情转折


@dataclass
class ClimaxPoint:
    """高潮点"""
    segment_idx: int
    climax_type: ClimaxType
    intensity: float  # 强度 0-1
    recommended_music: str
    description: str = ""


class EmotionTransition(str, Enum):
    """情绪转变趋势"""
    RISING = "rising"  # 上升
    FALLING = "falling"  # 下降
    STABLE = "stable"  # 稳定
    SUDDEN_SHIFT = "sudden_shift"  # 突变


@dataclass
class EmotionSegment:
    """情绪段落"""
    start_idx: int
    end_idx: int
    dominant_emotion: str
    intensity: float  # 强度 0-1
    transition: EmotionTransition


@dataclass
class EmotionShift:
    """情绪转折点"""
    idx: int
    from_emotion: str
    to_emotion: str
    shift_type: str  # calm_to_tense, tense_to_sad等


class ClimaxDetector:
    """
    🎯 高潮点智能检测器
    
    多维度检测高潮点：
    1. 情绪强度突变（calm→tense, tense→epic）
    2. 对话节奏加快（句子变短，停顿减少）
    3. 音效密度增加（battle/explosion类音效）
    4. LLM标注的is_climax标记
    """
    
    # 情绪强度映射
    EMOTION_INTENSITY = {
        "calm": 0.2,
        "peaceful": 0.2,
        "neutral": 0.3,
        "joyful": 0.5,
        "romantic": 0.5,
        "mysterious": 0.6,
        "sad": 0.6,
        "tense": 0.8,
        "angry": 0.8,
        "epic": 1.0,
    }
    
    # 高能音效关键词
    HIGH_ENERGY_EFFECTS = [
        "explosion", "battle", "clash", "thunder", "roar",
        "爆炸", "战斗", "碰撞", "雷声", "咆哮", "剑刃", "枪声"
    ]
    
    def detect_climax_points(
        self,
        script_segments: List[Any]
    ) -> List[ClimaxPoint]:
        """
        检测章节中的高潮点
        
        Args:
            script_segments: 剧本片段列表
        
        Returns:
            高潮点列表
        """
        logger.info("🎯 开始检测高潮点...")
        climax_points = []
        
        for i, seg in enumerate(script_segments):
            score = 0.0
            climax_type = ClimaxType.EMOTIONAL
            description_parts = []
            
            # 1. 情绪突变检测（权重0.4）
            if i > 0:
                prev_emotion = getattr(script_segments[i-1], 'emotion', 'neutral')
                curr_emotion = getattr(seg, 'emotion', 'neutral')
                
                prev_intensity = self.EMOTION_INTENSITY.get(prev_emotion, 0.3)
                curr_intensity = self.EMOTION_INTENSITY.get(curr_emotion, 0.3)
                
                intensity_jump = curr_intensity - prev_intensity
                
                if intensity_jump >= 0.4:  # 强度突然提升
                    score += 0.4
                    description_parts.append(f"情绪突变({prev_emotion}→{curr_emotion})")
                    
                    # 判断高潮类型
                    if curr_emotion in ["tense", "epic"]:
                        climax_type = ClimaxType.BATTLE
                    elif curr_emotion in ["sad", "angry"]:
                        climax_type = ClimaxType.EMOTIONAL
            
            # 2. 音效密度检测（权重0.3）
            sound_effects = getattr(seg, 'sound_effects', []) or []
            if isinstance(sound_effects, list):
                # 检查高能音效
                high_energy_count = 0
                for effect in sound_effects:
                    if isinstance(effect, str):
                        effect_name = effect
                    elif isinstance(effect, dict):
                        effect_name = effect.get('name', '')
                    else:
                        effect_name = str(effect)
                    
                    if any(keyword in effect_name.lower() for keyword in self.HIGH_ENERGY_EFFECTS):
                        high_energy_count += 1
                
                if high_energy_count >= 2:
                    score += 0.3
                    description_parts.append(f"{high_energy_count}个高能音效")
                    climax_type = ClimaxType.BATTLE
                elif len(sound_effects) >= 3:
                    score += 0.15
                    description_parts.append(f"{len(sound_effects)}个音效")
            
            # 3. LLM标注检测（权重0.3）
            if getattr(seg, 'is_climax', False):
                score += 0.3
                description_parts.append("LLM标注高潮")
            
            # 4. 文本长度和节奏检测（权重0.2）
            text = getattr(seg, 'text', '')
            if text:
                # 短句密集（<15字）可能是激烈对话
                if len(text) < 15 and getattr(seg, 'type', '') == 'dialogue':
                    score += 0.1
                    description_parts.append("短促对话")
                
                # 长段落且情绪强烈可能是独白高潮
                if len(text) > 80 and getattr(seg, 'emotion', '') in ['epic', 'tense', 'angry']:
                    score += 0.1
                    description_parts.append("情绪独白")
            
            # 如果分数达到阈值，标记为高潮点
            if score >= 0.6:
                recommended_music = self._select_climax_music(
                    getattr(seg, 'emotion', 'epic'),
                    climax_type
                )
                
                climax_points.append(ClimaxPoint(
                    segment_idx=i,
                    climax_type=climax_type,
                    intensity=min(1.0, score),
                    recommended_music=recommended_music,
                    description=" + ".join(description_parts)
                ))
                
                logger.info(
                    f"  ✅ 检测到高潮点 #{i}: {climax_type.value} "
                    f"(强度={score:.2f}) - {' + '.join(description_parts)}"
                )
        
        logger.info(f"🎯 检测完成，共发现 {len(climax_points)} 个高潮点")
        return climax_points
    
    def _select_climax_music(
        self,
        emotion: str,
        climax_type: ClimaxType
    ) -> str:
        """根据情绪和高潮类型选择配乐"""
        if climax_type == ClimaxType.BATTLE:
            return "激烈战斗配乐（快节奏，打击乐为主）"
        elif climax_type == ClimaxType.REVELATION:
            return "真相揭示配乐（悬疑转史诗，弦乐+铜管）"
        elif climax_type == ClimaxType.EMOTIONAL:
            if emotion == "sad":
                return "情感高潮配乐（悲伤，小提琴+钢琴）"
            elif emotion == "angry":
                return "情感爆发配乐（愤怒，重型弦乐）"
            else:
                return "情感高潮配乐（史诗感，管弦乐）"
        else:
            return "剧情转折配乐（神秘感，氛围音乐）"


class EmotionCurveAnalyzer:
    """
    📈 情绪曲线智能分析器
    
    分析章节的情绪流动，识别：
    1. 情绪段落（连续相似情绪）
    2. 情绪转折点（突然变化）
    3. 情绪趋势（上升/下降/稳定）
    """
    
    # 情绪分组（用于判断相似情绪）
    EMOTION_GROUPS = {
        "calm": ["calm", "peaceful", "neutral"],
        "positive": ["joyful", "romantic", "happy"],
        "negative": ["sad", "melancholic"],
        "intense": ["tense", "mysterious", "suspense"],
        "extreme": ["epic", "angry", "excited"],
    }
    
    def analyze_chapter_emotion_flow(
        self,
        script_segments: List[Any]
    ) -> Dict[str, Any]:
        """
        分析章节情绪流动
        
        Returns:
            {
                "segments": [EmotionSegment, ...],
                "climax_points": [15, 42],
                "emotional_shifts": [EmotionShift, ...],
                "overall_trend": "rising/falling/mixed"
            }
        """
        logger.info("📈 开始分析情绪曲线...")
        
        if not script_segments:
            return {
                "segments": [],
                "climax_points": [],
                "emotional_shifts": [],
                "overall_trend": "stable"
            }
        
        # 1. 提取情绪序列
        emotion_sequence = [
            getattr(seg, 'emotion', 'neutral')
            for seg in script_segments
        ]
        
        # 2. 识别情绪段落
        emotion_segments = self._identify_emotion_segments(emotion_sequence)
        
        # 3. 识别情绪转折点
        emotional_shifts = self._identify_emotional_shifts(emotion_sequence)
        
        # 4. 计算整体趋势
        overall_trend = self._calculate_overall_trend(emotion_sequence)
        
        # 5. 标记高潮点（基于强度突变）
        climax_indices = self._identify_climax_indices(emotion_sequence)
        
        result = {
            "segments": emotion_segments,
            "climax_points": climax_indices,
            "emotional_shifts": emotional_shifts,
            "overall_trend": overall_trend
        }
        
        logger.info(
            f"📈 分析完成: {len(emotion_segments)}个情绪段落, "
            f"{len(emotional_shifts)}个转折点, "
            f"{len(climax_indices)}个高潮点, "
            f"整体趋势={overall_trend}"
        )
        
        return result
    
    def _identify_emotion_segments(
        self,
        emotion_sequence: List[str]
    ) -> List[EmotionSegment]:
        """识别情绪段落（连续相似情绪）"""
        if not emotion_sequence:
            return []
        
        segments = []
        start_idx = 0
        current_group = self._get_emotion_group(emotion_sequence[0])
        
        for i in range(1, len(emotion_sequence)):
            emotion_group = self._get_emotion_group(emotion_sequence[i])
            
            # 如果情绪组发生变化，结束当前段落
            if emotion_group != current_group:
                # 计算段落主导情绪和强度
                segment_emotions = emotion_sequence[start_idx:i]
                dominant_emotion = max(set(segment_emotions), key=segment_emotions.count)
                avg_intensity = self._calculate_average_intensity(segment_emotions)
                
                # 判断趋势
                transition = self._calculate_segment_transition(segment_emotions)
                
                segments.append(EmotionSegment(
                    start_idx=start_idx,
                    end_idx=i - 1,
                    dominant_emotion=dominant_emotion,
                    intensity=avg_intensity,
                    transition=transition
                ))
                
                start_idx = i
                current_group = emotion_group
        
        # 添加最后一个段落
        segment_emotions = emotion_sequence[start_idx:]
        dominant_emotion = max(set(segment_emotions), key=segment_emotions.count)
        avg_intensity = self._calculate_average_intensity(segment_emotions)
        transition = self._calculate_segment_transition(segment_emotions)
        
        segments.append(EmotionSegment(
            start_idx=start_idx,
            end_idx=len(emotion_sequence) - 1,
            dominant_emotion=dominant_emotion,
            intensity=avg_intensity,
            transition=transition
        ))
        
        return segments
    
    def _identify_emotional_shifts(
        self,
        emotion_sequence: List[str]
    ) -> List[EmotionShift]:
        """识别情绪转折点"""
        shifts = []
        
        for i in range(1, len(emotion_sequence)):
            prev_emotion = emotion_sequence[i - 1]
            curr_emotion = emotion_sequence[i]
            
            if prev_emotion != curr_emotion:
                # 检查是否是显著转折（跨情绪组）
                prev_group = self._get_emotion_group(prev_emotion)
                curr_group = self._get_emotion_group(curr_emotion)
                
                if prev_group != curr_group:
                    shift_type = f"{prev_emotion}_to_{curr_emotion}"
                    
                    shifts.append(EmotionShift(
                        idx=i,
                        from_emotion=prev_emotion,
                        to_emotion=curr_emotion,
                        shift_type=shift_type
                    ))
        
        return shifts
    
    def _calculate_overall_trend(
        self,
        emotion_sequence: List[str]
    ) -> str:
        """计算整体情绪趋势"""
        if len(emotion_sequence) < 3:
            return "stable"
        
        # 将情绪转换为强度序列
        from .intelligence import ClimaxDetector
        intensity_sequence = [
            ClimaxDetector.EMOTION_INTENSITY.get(e, 0.3)
            for e in emotion_sequence
        ]
        
        # 计算前1/3和后1/3的平均强度
        third = len(intensity_sequence) // 3
        early_avg = sum(intensity_sequence[:third]) / max(1, third)
        late_avg = sum(intensity_sequence[-third:]) / max(1, third)
        
        diff = late_avg - early_avg
        
        if diff > 0.15:
            return "rising"
        elif diff < -0.15:
            return "falling"
        else:
            return "mixed"
    
    def _identify_climax_indices(
        self,
        emotion_sequence: List[str]
    ) -> List[int]:
        """识别高潮点索引（基于强度突变）"""
        from .intelligence import ClimaxDetector
        climax_indices = []
        
        for i in range(1, len(emotion_sequence)):
            prev_intensity = ClimaxDetector.EMOTION_INTENSITY.get(
                emotion_sequence[i - 1], 0.3
            )
            curr_intensity = ClimaxDetector.EMOTION_INTENSITY.get(
                emotion_sequence[i], 0.3
            )
            
            # 强度突然提升≥0.4，标记为高潮点
            if curr_intensity - prev_intensity >= 0.4:
                climax_indices.append(i)
        
        return climax_indices
    
    def _get_emotion_group(self, emotion: str) -> str:
        """获取情绪所属组"""
        for group_name, emotions in self.EMOTION_GROUPS.items():
            if emotion in emotions:
                return group_name
        return "other"
    
    def _calculate_average_intensity(self, emotions: List[str]) -> float:
        """计算平均情绪强度"""
        from .intelligence import ClimaxDetector
        intensities = [
            ClimaxDetector.EMOTION_INTENSITY.get(e, 0.3)
            for e in emotions
        ]
        return sum(intensities) / max(1, len(intensities))
    
    def _calculate_segment_transition(
        self,
        emotions: List[str]
    ) -> EmotionTransition:
        """计算段落内的情绪趋势"""
        if len(emotions) <= 2:
            return EmotionTransition.STABLE
        
        from .intelligence import ClimaxDetector
        intensities = [
            ClimaxDetector.EMOTION_INTENSITY.get(e, 0.3)
            for e in emotions
        ]
        
        # 计算前后差异
        early_avg = sum(intensities[:len(intensities)//2]) / max(1, len(intensities)//2)
        late_avg = sum(intensities[len(intensities)//2:]) / max(1, len(intensities) - len(intensities)//2)
        
        diff = late_avg - early_avg
        
        if diff > 0.2:
            return EmotionTransition.RISING
        elif diff < -0.2:
            return EmotionTransition.FALLING
        else:
            return EmotionTransition.STABLE


class IntelligentMusicEnhancer:
    """
    🎼 音乐智能增强器
    
    基于高潮点和情绪曲线，智能调整音乐方案：
    1. 高潮点自动添加强化配乐
    2. 情绪上升段音乐渐强
    3. 情绪转折点添加转场音乐
    """
    
    def __init__(
        self,
        climax_detector: ClimaxDetector,
        emotion_analyzer: EmotionCurveAnalyzer
    ):
        self.climax_detector = climax_detector
        self.emotion_analyzer = emotion_analyzer
    
    def enhance_music_cues(
        self,
        music_cues: List[Any],
        script_segments: List[Any],
        chapter_structure: Dict[str, Any]
    ) -> List[Any]:
        """
        智能增强音乐方案
        
        Args:
            music_cues: 原始音乐提示列表
            script_segments: 剧本片段
            chapter_structure: 章节结构
        
        Returns:
            增强后的音乐提示列表
        """
        logger.info("🎼 开始智能增强音乐方案...")
        
        # 1. 检测高潮点
        climax_points = self.climax_detector.detect_climax_points(script_segments)
        
        # 2. 分析情绪曲线
        emotion_flow = self.emotion_analyzer.analyze_chapter_emotion_flow(script_segments)
        
        # 3. 为高潮点添加强化配乐
        enhanced_cues = list(music_cues)
        for climax in climax_points:
            # 检查是否已有音乐
            has_existing = any(
                cue.get('timestamp', 0) == climax.segment_idx
                for cue in enhanced_cues
            )
            
            if not has_existing:
                # 添加高潮配乐
                enhanced_cues.append({
                    'timestamp': climax.segment_idx,
                    'type': 'climax',
                    'mood': script_segments[climax.segment_idx].emotion if climax.segment_idx < len(script_segments) else 'epic',
                    'description': f"高潮配乐 - {climax.recommended_music}",
                    'volume': 0.35,  # 高潮音量更大
                    'duration': 45.0,  # 持续时间更长
                    'sync_with_dialogue': True,
                    'fade_in': 2.0,
                    'fade_out': 5.0
                })
                logger.info(f"  ✅ 添加高潮配乐 #{climax.segment_idx}: {climax.recommended_music}")
        
        # 4. 为情绪转折点添加转场音乐
        for shift in emotion_flow['emotional_shifts']:
            # 检查附近是否已有音乐
            has_nearby = any(
                abs(cue.get('timestamp', 0) - shift.idx) < 5
                for cue in enhanced_cues
            )
            
            if not has_nearby:
                enhanced_cues.append({
                    'timestamp': shift.idx,
                    'type': 'transition',
                    'mood': shift.to_emotion,
                    'description': f"情绪转场 - {shift.from_emotion}→{shift.to_emotion}",
                    'volume': 0.18,  # 转场音乐音量较低
                    'duration': 10.0,
                    'sync_with_dialogue': True,
                    'fade_in': 3.0,
                    'fade_out': 3.0
                })
                logger.info(f"  ✅ 添加转场音乐 #{shift.idx}: {shift.shift_type}")
        
        logger.info(f"🎼 增强完成: {len(music_cues)} → {len(enhanced_cues)} 个音乐提示")
        return enhanced_cues
