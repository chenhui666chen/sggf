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
from dataclasses import dataclass, field

from app.services.audiobook.duration_estimator import estimate_narration_duration_seconds
from app.services.audiobook.script_render_mode import normalize_script_audio_engine_mode

logger = logging.getLogger(__name__)

STRONG_AUDIOBOOK_EMOTIONS = {
    "angry",
    "excited",
    "fearful",
    "mysterious",
    "nervous",
    "shout",
    "surprised",
    "tense",
}
ACTION_SOUND_HINTS = (
    "爆发",
    "倒地",
    "轰然",
    "脆响",
    "龟裂",
    "碎裂",
    "撞",
    "砸",
    "冲",
    "奔",
    "踉跄",
    "脚步",
    "风声",
    "雨声",
    "雷声",
    "尖啸",
    "惨叫",
    "干呕",
    "门响",
    "开门",
    "关门",
    "剑",
    "刀",
    "骨",
)
QUOTED_DIALOGUE_RE = re.compile(r"[“「『\"]([^“”「」『\"]{2,80})[”」』\"]")


@dataclass
class QualityIssue:
    """质量问题"""
    location: str  # 位置标识（如chapter1_para5）
    severity: str  # critical/major/minor
    category: str  # script/audio/pacing
    description: str
    suggestion: str
    # 扩展字段（LLM 维度评审，向后兼容）
    dimension: str = ""  # 所属维度 key（如 dialogue_naturalness）
    fix_type: str = ""  # deterministic / llm_rewrite / none
    target_fields: List[str] = field(default_factory=list)  # 建议修改的字段
    segment_index: int = -1  # 对应片段下标（-1 表示未指定）


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

    # LLM 维度评审结果（融合后填充）
    llm_dimensions: Dict[str, Any] = field(default_factory=dict)


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
        self.audio_engine_mode = "legacy_stems"
        self.quality_standards = self._init_quality_standards()
    
    def _init_quality_standards(self) -> Dict[str, Any]:
        """初始化质量标准（更贴近有声小说实战节奏）"""
        return {
            # 段落：朗读友好
            "max_paragraph_length": 120,  # 单段建议不超过 120 字（LLM 已经做了分段）
            "max_dialogue_length": 120,  # 单段对白/独白建议不超过 120 字

            # 时长：按统一中文有声书朗读语速估算，建议单集在 10-35 分钟之间
            "max_episode_duration": 35 * 60,  # 最大单集时长（秒）
            "min_episode_duration": 10 * 60,  # 最小单集时长

            # 音效密度：推荐每分钟 2-6 个音效，高于 8 视为明显过多
            "min_sound_effects_per_minute": 2,
            "max_sound_effects_per_minute": 6,
            "hard_max_sound_effects_per_minute": 8,

            # 音乐覆盖率：推荐 15%-40%，超过 60% 视为几乎全程铺乐
            "music_coverage_target_min": 0.15,
            "music_coverage_target_max": 0.40,
            "max_music_coverage": 0.60,
        }
    
    def review_script(
        self,
        script_segments: List[Dict[str, Any]],
        novel_genre: str = "",
        audio_engine_mode: Optional[str] = None,
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
            novel_genre: 小说类型（如“都市”“玄幻”“悬疑”等），用于选择细分质量配置
        
        Returns:
            质量报告
        """
        logger.info(f"🔍 评审有声剧本: {len(script_segments)} 个片段...")

        # 根据小说类型应用细分质量标准
        genre = (novel_genre or "").strip().lower()
        standards = dict(self.quality_standards)
        if genre:
            standards = self._apply_genre_overrides(standards, genre)
        self.quality_standards = standards
        logger.info(f"   使用质量标准: {self.quality_standards}")
        
        issues = []
        
        # 1. 剧本质量评审
        script_quality = self._review_script_quality(script_segments, issues)
        
        # 2. 音频平衡评审
        audio_balance = self._review_audio_balance(script_segments, issues)
        effective_engine_mode = normalize_script_audio_engine_mode(
            audio_engine_mode or self.audio_engine_mode
        )
        audio_balance["render_readiness"] = self._review_render_readiness(
            script_segments,
            issues,
            audio_engine_mode=effective_engine_mode,
        )
        
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

    def _review_render_readiness(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue],
        *,
        audio_engine_mode: str,
    ) -> Dict[str, Any]:
        if audio_engine_mode == "seed_scene":
            return self._review_seed_scene_readiness(segments, issues)
        return self._review_legacy_stems_readiness(segments, issues)

    def _review_seed_scene_readiness(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue],
    ) -> Dict[str, Any]:
        segment_count = len(segments)
        scene_context_count = sum(
            1 for segment in segments if str(segment.get("instruct_scene") or "").strip()
        )
        effects = [
            effect
            for segment in segments
            for effect in list(segment.get("sound_effects") or [])
            if effect
        ]
        timed_effect_count = sum(
            1
            for effect in effects
            if str(self._cue_value(effect, "timing") or "").strip().lower()
            in {
                "before",
                "pre",
                "during",
                "trigger",
                "after",
                "post",
                "continuous",
                "throughout",
                "until_text",
            }
        )
        music_cues = [
            segment.get("music_cue") or segment.get("music_cue_simple")
            for segment in segments
            if segment.get("music_cue") or segment.get("music_cue_simple")
        ]
        lifecycle_music_count = sum(
            1
            for cue in music_cues
            if any(
                marker in str(self._cue_value(cue, "style") or cue)
                for marker in (
                    "进入",
                    "淡入",
                    "延续",
                    "持续",
                    "渐强",
                    "渐弱",
                    "变化",
                    "切换",
                    "停止",
                    "淡出",
                )
            )
        )

        scene_context_coverage = self._coverage(scene_context_count, segment_count)
        relative_timing_coverage = self._coverage(timed_effect_count, len(effects))
        music_lifecycle_coverage = self._coverage(lifecycle_music_count, len(music_cues))
        ready = (
            scene_context_coverage > 0
            and relative_timing_coverage >= 1.0
            and music_lifecycle_coverage >= 1.0
        )

        if segment_count and scene_context_coverage == 0:
            issues.append(
                QualityIssue(
                    location="overall",
                    severity="minor",
                    category="audio",
                    description="Seed 场景缺少环境与空间状态",
                    suggestion="为场景首段和真实转场补充 instruct_scene，并在连续片段中保持声学状态一致",
                )
            )
        if effects and relative_timing_coverage < 1.0:
            issues.append(
                QualityIssue(
                    location="overall",
                    severity="minor",
                    category="audio",
                    description="Seed 声音事件缺少相对时序",
                    suggestion="明确声音发生在台词之前、期间、之后或持续到场景结束",
                )
            )
        if music_cues and music_lifecycle_coverage < 1.0:
            issues.append(
                QualityIssue(
                    location="overall",
                    severity="minor",
                    category="audio",
                    description="Seed 配乐提示缺少生命周期",
                    suggestion="说明音乐何时进入、变化、停止或淡出，而不是只写情绪标签",
                )
            )

        return {
            "mode": "seed_scene",
            "status": "ready" if ready else "needs_attention",
            "scene_context_coverage": scene_context_coverage,
            "relative_timing_coverage": relative_timing_coverage,
            "music_lifecycle_coverage": music_lifecycle_coverage,
        }

    def _review_legacy_stems_readiness(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue],
    ) -> Dict[str, Any]:
        effects = [
            effect
            for segment in segments
            for effect in list(segment.get("sound_effects") or [])
            if effect
        ]
        executable_effect_count = sum(
            1
            for effect in effects
            if str(self._cue_value(effect, "name") or effect).strip()
            and str(self._cue_value(effect, "timing") or "").strip()
            and any(
                self._cue_value(effect, field) is not None
                for field in (
                    "asset_id",
                    "volume",
                    "duration",
                    "delay",
                    "fade_in",
                    "fade_out",
                    "position_3d",
                )
            )
        )
        executable_effect_coverage = self._coverage(
            executable_effect_count,
            len(effects),
        )
        ready = executable_effect_coverage >= 1.0
        if effects and not ready:
            issues.append(
                QualityIssue(
                    location="overall",
                    severity="minor",
                    category="audio",
                    description="分轨音效缺少可执行参数",
                    suggestion="补充明确音效名称、timing，以及素材 ID、音量、时长、延迟或淡入淡出参数",
                )
            )
        return {
            "mode": "legacy_stems",
            "status": "ready" if ready else "needs_attention",
            "executable_effect_coverage": executable_effect_coverage,
        }

    @staticmethod
    def _cue_value(cue: Any, field: str) -> Any:
        if isinstance(cue, dict):
            return cue.get(field)
        return getattr(cue, field, None)

    @staticmethod
    def _coverage(ready_count: int, total_count: int) -> float:
        if total_count <= 0:
            return 1.0
        return round(ready_count / total_count, 4)
    
    def _review_script_quality(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审剧本质量"""
        naturalness_score = 10.0
        clarity_score = 10.0
        engagement_score = 10.0
        max_narration_length = int(self.quality_standards.get("max_paragraph_length", 120))
        max_dialogue_length = int(self.quality_standards.get("max_dialogue_length", max_narration_length))
        long_segment_count = 0
        quoted_dialogue_count = 0
        weak_pause_count = 0
        action_without_effect_count = 0
        expressive_segment_count = 0
        missing_performance_notes_count = 0
        missing_delivery_plan_count = 0
        
        for i, seg in enumerate(segments):
            text = str(seg.get("text", "") or "").strip()
            location = f"segment_{i}"
            segment_type = str(seg.get("type", "narration") or "narration").strip().lower()
            speaker = str(seg.get("speaker", "") or "").strip()
            emotion = str(seg.get("emotion", "") or "").strip().lower()
            performance_notes = str(seg.get("performance_notes", "") or "").strip()
            text_length = len(text)
            
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
            if text_length > 100 and text.count("，") < 2:
                clarity_score -= 0.2

            # 有声播讲单元长度检查：过长会导致 TTS 呼吸点不明确，也会削弱音效/停顿触发。
            segment_max_length = max_dialogue_length if segment_type in {"dialogue", "monologue"} else max_narration_length
            if text_length > segment_max_length:
                long_segment_count += 1
                severity = "major" if text_length > segment_max_length * 1.5 else "minor"
                if long_segment_count <= 5:
                    issues.append(QualityIssue(
                        location=location,
                        severity=severity,
                        category="pacing",
                        description=f"单段过长（{text_length}字，建议不超过{segment_max_length}字）",
                        suggestion="按动作拍点、情绪转折或因果推进拆分，给 TTS 留出自然呼吸点"
                    ))
                clarity_score -= 0.6 if severity == "major" else 0.3
                engagement_score -= 0.2

            # 旁白里混入明确引号台词时，应拆出 dialogue，避免全部用旁白音色朗读。
            if segment_type == "narration" and self._contains_quoted_dialogue(text):
                quoted_dialogue_count += 1
                if quoted_dialogue_count <= 5:
                    issues.append(QualityIssue(
                        location=location,
                        severity="minor",
                        category="script",
                        description="旁白片段中疑似混入可拆分对白",
                        suggestion="将引号内台词拆成 dialogue，并保留说话人归属；旁白只承载动作和场景"
                    ))
                clarity_score -= 0.3

            if segment_type == "dialogue" and (not speaker or speaker == "旁白"):
                issues.append(QualityIssue(
                    location=location,
                    severity="major",
                    category="script",
                    description="对话片段缺少有效说话人",
                    suggestion="补充真实角色名；如果无法判断说话人，应改为 narration"
                ))
                clarity_score -= 0.5

            expressive = emotion in STRONG_AUDIOBOOK_EMOTIONS or text_length > 80
            if expressive:
                expressive_segment_count += 1
                if not performance_notes:
                    missing_performance_notes_count += 1
                if not self._has_actionable_delivery_plan(seg):
                    missing_delivery_plan_count += 1
                    if missing_delivery_plan_count <= 5:
                        issues.append(QualityIssue(
                            location=location,
                            severity="minor",
                            category="script",
                            description="强表现片段缺少可执行朗读意图",
                            suggestion="补充 delivery_plan，至少包含模型、朗读方式、微表演标签或导演指导，便于按 TTS 模型生成风格指令"
                        ))
                    engagement_score -= 0.2

            if self._needs_breath_pause(text, emotion) and self._segment_pause_after(seg) < 0.12:
                weak_pause_count += 1
                if weak_pause_count <= 5:
                    issues.append(QualityIssue(
                        location=location,
                        severity="minor",
                        category="pacing",
                        description="强情绪片段缺少停顿",
                        suggestion="为紧张、惊惧、怒喊或强转折片段设置 pause_after，通常 0.2-0.6 秒更自然"
                    ))
                engagement_score -= 0.15

            if (
                segment_type == "narration"
                and self._looks_like_action_or_environment_cue(text)
                and not self._segment_has_sound_effects(seg)
            ):
                action_without_effect_count += 1
                if action_without_effect_count <= 5:
                    issues.append(QualityIssue(
                        location=location,
                        severity="minor",
                        category="audio",
                        description="动作或环境片段缺少音效提示",
                        suggestion="为关键动作/环境补充少量 sound_effects，避免只靠旁白描述听觉事件"
                    ))
                engagement_score -= 0.15

        if long_segment_count > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="pacing",
                description=f"存在较多过长播讲片段（{long_segment_count}段）",
                suggestion="优先批量拆分长旁白和长独白，按场景动作与情绪转折形成可播讲单元"
            ))

        if quoted_dialogue_count > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="script",
                description=f"多处旁白疑似混入对白（{quoted_dialogue_count}段）",
                suggestion="统一将明确台词拆成 dialogue，减少旁白音色代读角色台词"
            ))

        if weak_pause_count > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="pacing",
                description=f"多处强情绪片段缺少停顿（{weak_pause_count}段）",
                suggestion="统一为强情绪、转折和战斗片段补充 pause_after，增强听感呼吸"
            ))

        if action_without_effect_count > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"多处动作/环境片段未标注音效（{action_without_effect_count}段）",
                suggestion="只为关键动作补充音效，避免过密，同时让重要听觉事件可被生成器捕捉"
            ))

        performance_notes_coverage = (
            1.0 - (missing_performance_notes_count / expressive_segment_count)
            if expressive_segment_count
            else 1.0
        )
        delivery_plan_coverage = (
            1.0 - (missing_delivery_plan_count / expressive_segment_count)
            if expressive_segment_count
            else 1.0
        )
        if expressive_segment_count >= 5 and performance_notes_coverage < 0.5:
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="script",
                description=f"强表现片段的演绎提示覆盖不足（约 {performance_notes_coverage * 100:.0f}%）",
                suggestion="为强情绪、长旁白和关键转折补充 performance_notes，说明语速、音量、停顿和情绪方向"
            ))
            engagement_score -= 0.6
        
        return {
            "naturalness_score": max(0, min(10, naturalness_score)),
            "clarity_score": max(0, min(10, clarity_score)),
            "engagement_score": max(0, min(10, engagement_score)),
            "total_segments": len(segments),
            "average_segment_length": sum(len(s.get("text", "")) for s in segments) / len(segments) if segments else 0,
            "long_segment_count": long_segment_count,
            "quoted_dialogue_in_narration_count": quoted_dialogue_count,
            "weak_pause_count": weak_pause_count,
            "action_without_effect_count": action_without_effect_count,
            "performance_notes_coverage": performance_notes_coverage,
            "delivery_plan_coverage": delivery_plan_coverage,
            "missing_delivery_plan_count": missing_delivery_plan_count,
        }
    
    def _detect_awkward_words(self, text: str) -> List[str]:
        """检测可能拗口、不适合朗读的词汇

        说明：
        - 这里先用一套简单的启发式规则，后续可以接 LLM 做更智能的评审
        - 目标是发现：书面化过重、成串叠词、生僻词堆叠等情况
        """
        candidates = [
            "之乎者也",
            "不禁感叹",
            "不由得感叹",
            "不禁赞叹",
            "不由得说道",
            "不禁说道",
            "蓦然回首",
            "恍若隔世",
            "不胜唏嘘",
        ]

        awkward = []
        for w in candidates:
            if w in text:
                awkward.append(w)

        # 规则2：连续三个以上相同的字（容易念错 / 听感别扭）
        repeat_pattern = re.compile(r"(.)\1{2,}")
        for m in repeat_pattern.finditer(text):
            awkward.append(m.group(0))

        # 去重
        return list(dict.fromkeys(awkward))

    def _contains_quoted_dialogue(self, text: str) -> bool:
        """识别旁白中疑似可以拆成 dialogue 的引号台词。"""
        for match in QUOTED_DIALOGUE_RE.finditer(str(text or "")):
            quoted = match.group(1).strip()
            if re.search(r"[。！？!?]", quoted):
                return True
            if len(quoted) >= 8 and re.search(r"(你|我|咱|别|不要|怎么|什么|为什么|吗|呢|吧|快|走|救命|住手)", quoted):
                return True
        return False

    def _needs_breath_pause(self, text: str, emotion: str) -> bool:
        """强情绪或强转折片段需要最小停顿，避免 TTS 连读成平铺旁白。"""
        normalized_emotion = str(emotion or "").strip().lower()
        if normalized_emotion in STRONG_AUDIOBOOK_EMOTIONS:
            return True
        value = str(text or "")
        return bool(re.search(r"[！？!]{1,}|必须走|突然|猛地|轰然|当场|一息之间", value))

    def _segment_pause_after(self, segment: Dict[str, Any]) -> float:
        voice_params = segment.get("voice_params") if isinstance(segment.get("voice_params"), dict) else {}
        value = voice_params.get("pause_after", segment.get("pause_after", 0.0))
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _segment_has_sound_effects(self, segment: Dict[str, Any]) -> bool:
        sound_effects = segment.get("sound_effects")
        sound_effects_simple = segment.get("sound_effects_simple")
        return bool(sound_effects) or bool(sound_effects_simple)

    def _has_actionable_delivery_plan(self, segment: Dict[str, Any]) -> bool:
        voice_params = segment.get("voice_params") if isinstance(segment.get("voice_params"), dict) else {}
        delivery_plan = voice_params.get("delivery_plan")
        if not isinstance(delivery_plan, dict):
            return False
        has_model = bool(delivery_plan.get("model") or voice_params.get("resolved_tts_model") or voice_params.get("tts_model"))
        has_mode = bool(delivery_plan.get("delivery_mode"))
        has_guidance = bool(
            delivery_plan.get("director_guidance")
            or delivery_plan.get("micro_tags")
            or delivery_plan.get("pause_strategy")
            or delivery_plan.get("stress_words")
        )
        return has_model and has_mode and has_guidance

    def _looks_like_action_or_environment_cue(self, text: str) -> bool:
        value = str(text or "")
        return any(keyword in value for keyword in ACTION_SOUND_HINTS)
    
    def _apply_genre_overrides(self, standards: Dict[str, Any], genre: str) -> Dict[str, Any]:
        """根据小说类型对质量标准做细分调整。

        说明：
        - 都市/言情/校园：允许略高的背景音乐覆盖率，音效保持中等。
        - 玄幻/仙侠/热血/冒险：允许更高的音效密度和略高的音乐覆盖率。
        - 悬疑/推理/惊悚/恐怖：整体更克制，强调静音和环境音，背景音乐覆盖率下调。
        - 其他类型：使用默认标准。
        """
        g = genre

        # 都市、言情、校园 等相对温和题材
        if ("都市" in g) or ("言情" in g) or ("校园" in g) or ("日常" in g):
            standards["min_sound_effects_per_minute"] = 1
            standards["max_sound_effects_per_minute"] = 5
            standards["hard_max_sound_effects_per_minute"] = 7
            standards["music_coverage_target_min"] = 0.20
            standards["music_coverage_target_max"] = 0.50
            standards["max_music_coverage"] = 0.70

        # 玄幻、仙侠、热血、冒险 等偏戏剧化题材
        elif ("玄幻" in g) or ("仙侠" in g) or ("奇幻" in g) or ("热血" in g) or ("冒险" in g):
            standards["min_sound_effects_per_minute"] = 3
            standards["max_sound_effects_per_minute"] = 8
            standards["hard_max_sound_effects_per_minute"] = 10
            standards["music_coverage_target_min"] = 0.20
            standards["music_coverage_target_max"] = 0.50
            standards["max_music_coverage"] = 0.70

        # 悬疑、推理、惊悚、恐怖 等需要静音张力的题材
        elif ("悬疑" in g) or ("推理" in g) or ("惊悚" in g) or ("恐怖" in g):
            standards["min_sound_effects_per_minute"] = 1
            standards["max_sound_effects_per_minute"] = 4
            standards["hard_max_sound_effects_per_minute"] = 6
            standards["music_coverage_target_min"] = 0.05
            standards["music_coverage_target_max"] = 0.25
            standards["max_music_coverage"] = 0.40

        # 其他类型（包括科幻等）保持默认
        return standards
    
    def _review_audio_balance(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审音频平衡"""
        total_effects = 0
        total_music_cues = 0
        
        for seg in segments:
            # 防御性检查：确保 sound_effects 是列表类型
            sound_effects = seg.get("sound_effects", [])
            if sound_effects is None:
                sound_effects = []
            total_effects += len(sound_effects)
            
            if seg.get("music_cue"):
                total_music_cues += 1
        
        # 估算时长：复用生成链路的有声书中文朗读语速，避免密度评审偏高。
        total_text_length = sum(len(s.get("text", "")) for s in segments)
        estimated_duration = self._estimate_total_duration_seconds(segments)
        estimated_duration_minutes = estimated_duration / 60
        
        # 音效密度
        effects_per_minute = total_effects / estimated_duration_minutes if estimated_duration_minutes > 0 else 0

        target_min_effects = self.quality_standards.get("min_sound_effects_per_minute", 2)
        target_max_effects = self.quality_standards.get("max_sound_effects_per_minute", 6)
        hard_max_effects = self.quality_standards.get("hard_max_sound_effects_per_minute", target_max_effects + 2)

        sound_effect_rating = "适中"
        if effects_per_minute > hard_max_effects:
            sound_effect_rating = "严重偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"音效密度严重过高（约 {effects_per_minute:.1f}/分钟）",
                suggestion="仅保留关键情节所需音效，删除背景性或重复音效"
            ))
        elif effects_per_minute > target_max_effects:
            sound_effect_rating = "偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"音效偏多（约 {effects_per_minute:.1f}/分钟）",
                suggestion="合并相近音效触发点，避免每一句都叠加音效"
            ))
        elif 0 < effects_per_minute < target_min_effects:
            sound_effect_rating = "偏少"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description="音效略少，部分环境描写可以转化为音效",
                suggestion="为重要环境或动作场景补充少量高质量音效"
            ))
        elif effects_per_minute == 0 and total_text_length > 800:
            sound_effect_rating = "明显不足"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description="长篇文本完全没有音效标注",
                suggestion="为关键环境/动作场景设计基础音效，例如雨声、脚步声、环境氛围音"
            ))
        else:
            sound_effect_rating = "适中"

        # 音乐密度
        music_rating = "适中"
        music_coverage = total_music_cues / len(segments) if segments else 0
        target_min_music = self.quality_standards.get("music_coverage_target_min", 0.15)
        target_max_music = self.quality_standards.get("music_coverage_target_max", 0.40)
        max_music_coverage = self.quality_standards.get("max_music_coverage", 0.60)

        if music_coverage > max_music_coverage:
            music_rating = "严重偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"背景音乐覆盖率过高（约 {music_coverage*100:.0f}% 片段有BGM）",
                suggestion="保留开头/结尾/高潮等关键位置的配乐，减少连续长时间背景音乐"
            ))
        elif music_coverage > target_max_music:
            music_rating = "偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"背景音乐略多（约 {music_coverage*100:.0f}% 片段有BGM）",
                suggestion="适当减少非关键段落的配乐，给对话和旁白留出空间"
            ))
        elif 0 < music_coverage < target_min_music:
            music_rating = "偏少"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description="背景音乐略少",
                suggestion="在情绪起伏较大的片段增加少量配乐，增强氛围"
            ))
        elif music_coverage == 0 and total_text_length > 800:
            music_rating = "明显不足"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description="长篇章节没有任何背景音乐提示",
                suggestion="为章节开头/结尾或关键转折点增加简短背景音乐"
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
        # 估算时长：与音效/配乐时间线使用同一朗读语速。
        estimated_duration = self._estimate_total_duration_seconds(segments)
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
        segment_durations = [
            self._estimate_segment_duration_seconds(s)
            for s in segments
        ]
        avg_length = sum(segment_lengths) / len(segment_lengths) if segment_lengths else 0
        avg_duration = sum(segment_durations) / len(segment_durations) if segment_durations else 0.0
        
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
            "average_segment_duration": f"{avg_duration:.1f}秒",
            "total_segments": len(segments)
        }

    def _estimate_total_duration_seconds(self, segments: List[Dict[str, Any]]) -> float:
        return sum(self._estimate_segment_duration_seconds(segment) for segment in segments)

    def _estimate_segment_duration_seconds(self, segment: Dict[str, Any]) -> float:
        return estimate_narration_duration_seconds(segment.get("text", ""), min_duration=0.0)
    
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
            suggestions.append("优化剧本：控制单段长度，拆清对白/旁白，并替换拗口表达")
        
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

    # ------------------------------------------------------------------
    # LLM 维度评审融合
    # ------------------------------------------------------------------

    def merge_llm_review(
        self,
        report: AudioQualityReport,
        llm_report: Any,
        *,
        rule_weight: float = 0.5,
        llm_weight: float = 0.5,
    ) -> AudioQualityReport:
        """
        将 LLM 维度评审结果融合到规则评审报告中。

        Args:
            report: 规则评审产出的 AudioQualityReport
            llm_report: LLMQualityReport 实例（可为 None / 空报告）
            rule_weight: 规则分权重（默认 0.5）
            llm_weight: LLM 分权重（默认 0.5）

        Returns:
            融合后的 report（原地修改并返回）
        """
        # 空报告降级：LLM 评审失败或无维度分时，保留纯规则分
        if (
            llm_report is None
            or not getattr(llm_report, "dimensions", None)
            or getattr(llm_report, "avg_score", 0) <= 0
        ):
            return report

        # 1. 填充 llm_dimensions
        report.llm_dimensions = dict(llm_report.dimensions)

        # 2. 融合 LLM issues 到 report.issues
        llm_issues = getattr(llm_report, "issues", None) or []
        for llm_issue in llm_issues:
            merged_issue = QualityIssue(
                location=f"segment_{getattr(llm_issue, 'segment_index', -1)}",
                severity=getattr(llm_issue, "severity", "minor"),
                category="llm_quality",
                description=getattr(llm_issue, "description", ""),
                suggestion=getattr(llm_issue, "suggestion", ""),
                dimension=getattr(llm_issue, "dimension", ""),
                fix_type=getattr(llm_issue, "fix_type", "none"),
                target_fields=list(getattr(llm_issue, "target_fields", None) or []),
                segment_index=getattr(llm_issue, "segment_index", -1),
            )
            report.issues.append(merged_issue)

        # 3. 计算融合总分
        rule_score = report.overall_score  # 0-100
        llm_avg = float(getattr(llm_report, "avg_score", 0))  # 0-10
        llm_score_100 = llm_avg * 10  # 转换为 0-100

        fused_score = round(
            rule_weight * rule_score + llm_weight * llm_score_100, 1
        )
        fused_score = max(0.0, min(100.0, fused_score))
        report.overall_score = fused_score
        report.overall_grade = self._score_to_grade(fused_score)

        # 4. 补充修订建议
        llm_major = [i for i in llm_issues if getattr(i, "severity", "") in ("critical", "major")]
        if llm_major:
            report.revision_suggestions.append(
                f"【LLM维度】优化 {len(llm_major)} 个质感问题"
                f"（均分 {llm_avg:.1f}/10）"
            )

        logger.info(
            "融合评审: rule=%.1f + llm=%.1f → fused=%.1f (%s)",
            rule_score, llm_score_100, fused_score, report.overall_grade,
        )
        return report

    @staticmethod
    def _score_to_grade(score: float) -> str:
        """分数转等级。"""
        if score >= 95:
            return "A+"
        elif score >= 90:
            return "A"
        elif score >= 85:
            return "A-"
        elif score >= 80:
            return "B+"
        elif score >= 75:
            return "B"
        elif score >= 70:
            return "B-"
        elif score >= 65:
            return "C+"
        elif score >= 60:
            return "C"
        elif score >= 55:
            return "C-"
        elif score >= 50:
            return "D"
        return "F"
