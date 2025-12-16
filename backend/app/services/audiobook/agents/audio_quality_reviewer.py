"""
AudioQualityReviewer - 音频质量评审官Agent

核心职责：
1. 评审有声剧本的听觉体验质量
2. 检查对话自然度和信息密度
3. 评估音效/音乐的平衡性
4. 识别节奏和时长问题
"""

import logging
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    """质量问题"""
    location: str  # 位置标识（如chapter1_para5）
    severity: str  # critical/major/minor
    category: str  # script/audio/pacing
    description: str
    suggestion: str


@dataclass
class AudioQualityReport:
    """音频质量报告"""
    # 剧本质量
    script_quality: Dict[str, Any]
    
    # 音频平衡
    audio_balance: Dict[str, Any]
    
    # 节奏评估
    pacing: Dict[str, Any]
    
    # 问题列表
    issues: List[QualityIssue]
    
    # 总评
    overall_grade: str  # A+/A/A-/B+/B/B-/C+/C/C-/D/F
    overall_score: float  # 0-100
    
    # 修订建议
    revision_suggestions: List[str]


class AudioQualityReviewer:
    """
    音频质量评审官Agent
    
    评审有声剧本的各个维度质量
    """
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（可选，用于智能评审）
        """
        self.llm_client = llm_client
        self.quality_standards = self._init_quality_standards()
    
    def _init_quality_standards(self) -> Dict[str, Any]:
        """初始化质量标准"""
        return {
            "max_sentence_length": 50,  # 最大句子长度（字）
            "max_paragraph_length": 200,  # 最大段落长度
            "min_pause_between_sentences": 0.3,  # 最小句间停顿（秒）
            "max_episode_duration": 40 * 60,  # 最大单集时长（秒）
            "min_episode_duration": 15 * 60,  # 最小单集时长
            "max_sound_effects_per_minute": 6,  # 每分钟最大音效数
            "max_music_coverage": 0.5,  # 最大音乐覆盖率
        }
    
    def review_script(
        self,
        script_segments: List[Dict[str, Any]]
    ) -> AudioQualityReport:
        """
        评审有声剧本
        
        Args:
            script_segments: 剧本片段列表
                [
                    {
                        "type": "dialogue|narration|monologue",
                        "text": "文本内容",
                        "speaker": "角色名",
                        "emotion": "情绪",
                        "performance_notes": "表演提示",
                        "sound_effects": ["音效1"],
                        "music_cue": "音乐提示"
                    }
                ]
        
        Returns:
            质量报告
        """
        logger.info(f"🔍 评审有声剧本: {len(script_segments)} 个片段...")
        
        issues = []
        
        # 1. 剧本质量评审
        script_quality = self._review_script_quality(script_segments, issues)
        
        # 2. 音频平衡评审
        audio_balance = self._review_audio_balance(script_segments, issues)
        
        # 3. 节奏评审
        pacing = self._review_pacing(script_segments, issues)
        
        # 4. 计算总评
        overall_score, overall_grade = self._calculate_overall_score(
            script_quality,
            audio_balance,
            pacing
        )
        
        # 5. 生成修订建议
        revision_suggestions = self._generate_suggestions(issues)
        
        report = AudioQualityReport(
            script_quality=script_quality,
            audio_balance=audio_balance,
            pacing=pacing,
            issues=issues,
            overall_grade=overall_grade,
            overall_score=overall_score,
            revision_suggestions=revision_suggestions
        )
        
        logger.info(f"   ✅ 评审完成: {overall_grade} ({overall_score:.1f}分)")
        logger.info(f"   发现 {len(issues)} 个问题")
        
        return report
    
    def _review_script_quality(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审剧本质量"""
        naturalness_score = 10.0
        clarity_score = 10.0
        engagement_score = 10.0
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            location = f"segment_{i}"
            
            # 检查句子长度
            sentences = re.split(r'[。！？]', text)
            for j, sentence in enumerate(sentences):
                if len(sentence) > self.quality_standards["max_sentence_length"]:
                    issues.append(QualityIssue(
                        location=f"{location}_sentence_{j}",
                        severity="major",
                        category="script",
                        description=f"句子过长（{len(sentence)}字）",
                        suggestion="建议拆分为多个短句"
                    ))
                    naturalness_score -= 0.5
            
            # 检查拗口词汇
            awkward_words = self._detect_awkward_words(text)
            if awkward_words:
                issues.append(QualityIssue(
                    location=location,
                    severity="minor",
                    category="script",
                    description=f"发现拗口词汇: {', '.join(awkward_words)}",
                    suggestion="建议替换为口语化表达"
                ))
                naturalness_score -= 0.3
            
            # 检查信息密度
            if len(text) > 100 and text.count("，") < 2:
                clarity_score -= 0.2
        
        return {
            "naturalness_score": max(0, min(10, naturalness_score)),
            "clarity_score": max(0, min(10, clarity_score)),
            "engagement_score": max(0, min(10, engagement_score)),
            "total_segments": len(segments),
            "average_segment_length": sum(len(s.get("text", "")) for s in segments) / len(segments) if segments else 0
        }
    
    def _detect_awkward_words(self, text: str) -> List[str]:
        """检测拗口词汇"""
        # 常见拗口词列表（示例）
        awkward_patterns = [
            r'诡谲', r'晦涩', r'逻辑悖论', r'具象化',
            r'赋能', r'颗粒度', r'闭环'
        ]
        
        found = []
        for pattern in awkward_patterns:
            if re.search(pattern, text):
                found.append(pattern)
        
        return found
    
    def _review_audio_balance(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审音频平衡"""
        total_effects = 0
        total_music_cues = 0
        
        for seg in segments:
            total_effects += len(seg.get("sound_effects", []))
            if seg.get("music_cue"):
                total_music_cues += 1
        
        # 估算时长（粗略）
        total_text_length = sum(len(s.get("text", "")) for s in segments)
        estimated_duration_minutes = total_text_length / 10 / 60  # 假设10字/秒
        
        # 音效密度
        effects_per_minute = total_effects / estimated_duration_minutes if estimated_duration_minutes > 0 else 0
        
        sound_effect_rating = "适中"
        if effects_per_minute > self.quality_standards["max_sound_effects_per_minute"]:
            sound_effect_rating = "偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"音效密度过高（{effects_per_minute:.1f}/分钟）",
                suggestion="建议减少非关键音效"
            ))
        elif effects_per_minute < 2:
            sound_effect_rating = "偏少"
        
        # 音乐密度
        music_rating = "适中"
        music_coverage = total_music_cues / len(segments) if segments else 0
        if music_coverage > 0.3:
            music_rating = "偏多"
        elif music_coverage < 0.1:
            music_rating = "偏少"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description="背景音乐较少",
                suggestion="建议在关键场景增加背景音乐"
            ))
        
        # 角色音色区分度
        speakers = set(s.get("speaker") for s in segments if s.get("type") == "dialogue")
        voice_differentiation = "清晰" if len(speakers) <= 5 else "可能混淆"
        
        if len(speakers) > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"角色过多（{len(speakers)}个）",
                suggestion="建议确保角色音色差异明显"
            ))
        
        return {
            "sound_effects": sound_effect_rating,
            "music": music_rating,
            "voice_differentiation": voice_differentiation,
            "total_effects": total_effects,
            "total_music_cues": total_music_cues,
            "effects_per_minute": effects_per_minute
        }
    
    def _review_pacing(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审节奏"""
        # 估算总时长
        total_text_length = sum(len(s.get("text", "")) for s in segments)
        estimated_duration = total_text_length / 10  # 10字/秒
        estimated_duration_minutes = estimated_duration / 60
        
        pacing_issues = []
        
        # 检查时长
        if estimated_duration > self.quality_standards["max_episode_duration"]:
            pacing_issues.append(f"时长过长（{estimated_duration_minutes:.1f}分钟）")
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="pacing",
                description=f"单集时长过长（{estimated_duration_minutes:.1f}分钟）",
                suggestion=f"建议控制在{self.quality_standards['max_episode_duration']/60}分钟以内"
            ))
        elif estimated_duration < self.quality_standards["min_episode_duration"]:
            pacing_issues.append(f"时长过短（{estimated_duration_minutes:.1f}分钟）")
        
        # 检查节奏变化
        segment_lengths = [len(s.get("text", "")) for s in segments]
        avg_length = sum(segment_lengths) / len(segment_lengths) if segment_lengths else 0
        
        # 如果连续多个片段都很长，可能节奏拖沓
        slow_segments = []
        for i, length in enumerate(segment_lengths):
            if length > avg_length * 1.5:
                slow_segments.append(i)
        
        if len(slow_segments) > len(segments) * 0.3:
            pacing_issues.append("部分片段节奏拖沓")
            issues.append(QualityIssue(
                location="segments_" + ",".join(map(str, slow_segments[:3])),
                severity="minor",
                category="pacing",
                description="部分片段过长，节奏拖沓",
                suggestion="建议加快节奏或增加停顿"
            ))
        
        return {
            "estimated_duration": f"{estimated_duration_minutes:.1f}分钟",
            "pacing_issues": pacing_issues,
            "average_segment_duration": f"{avg_length/10:.1f}秒",
            "total_segments": len(segments)
        }
    
    def _calculate_overall_score(
        self,
        script_quality: Dict[str, Any],
        audio_balance: Dict[str, Any],
        pacing: Dict[str, Any]
    ) -> tuple:
        """计算总评分"""
        # 剧本质量权重50%
        script_score = (
            script_quality["naturalness_score"] * 0.4 +
            script_quality["clarity_score"] * 0.3 +
            script_quality["engagement_score"] * 0.3
        ) * 5  # 转换为50分制
        
        # 音频平衡权重30%
        audio_score = 30.0  # 默认满分
        if audio_balance["sound_effects"] == "偏多" or audio_balance["sound_effects"] == "偏少":
            audio_score -= 5
        if audio_balance["music"] == "偏多" or audio_balance["music"] == "偏少":
            audio_score -= 5
        if audio_balance["voice_differentiation"] == "可能混淆":
            audio_score -= 10
        
        # 节奏权重20%
        pacing_score = 20.0  # 默认满分
        if pacing["pacing_issues"]:
            pacing_score -= len(pacing["pacing_issues"]) * 5
        
        total_score = max(0, script_score + audio_score + pacing_score)
        
        # 转换为等级
        if total_score >= 95:
            grade = "A+"
        elif total_score >= 90:
            grade = "A"
        elif total_score >= 85:
            grade = "A-"
        elif total_score >= 80:
            grade = "B+"
        elif total_score >= 75:
            grade = "B"
        elif total_score >= 70:
            grade = "B-"
        elif total_score >= 65:
            grade = "C+"
        elif total_score >= 60:
            grade = "C"
        elif total_score >= 55:
            grade = "C-"
        elif total_score >= 50:
            grade = "D"
        else:
            grade = "F"
        
        return total_score, grade
    
    def _generate_suggestions(
        self,
        issues: List[QualityIssue]
    ) -> List[str]:
        """生成修订建议"""
        suggestions = []
        
        # 按严重程度分组
        critical_issues = [i for i in issues if i.severity == "critical"]
        major_issues = [i for i in issues if i.severity == "major"]
        
        if critical_issues:
            suggestions.append(f"【紧急】修复 {len(critical_issues)} 个严重问题")
        
        if major_issues:
            suggestions.append(f"【重要】优化 {len(major_issues)} 个主要问题")
        
        # 按类别生成建议
        script_issues = [i for i in issues if i.category == "script"]
        if script_issues:
            suggestions.append("优化剧本：简化长句、替换拗口词汇")
        
        audio_issues = [i for i in issues if i.category == "audio"]
        if audio_issues:
            suggestions.append("调整音频平衡：优化音效和音乐密度")
        
        pacing_issues = [i for i in issues if i.category == "pacing"]
        if pacing_issues:
            suggestions.append("调整节奏：控制时长和段落长度")
        
        if not suggestions:
            suggestions.append("质量优秀，无需修订")
        
        return suggestions
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "quality_standards": self.quality_standards
        }
