"""
STT 回验模块 - 语音转文本验证 TTS 质量

核心功能：
1. 使用 Whisper 将 TTS 生成的音频转回文本
2. 对比原始文本和回验文本的相似度
3. 质量评分和阈值判断
4. 智能重试决策（低于阈值时标记重试）
"""
import io
import logging
import tempfile
import os
import re
import string
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_HOMOPHONE_GROUPS = (
    ("there", "their", "theyre"),
    ("to", "too", "two"),
    ("your", "youre"),
    ("hear", "here"),
    ("right", "write"),
    ("know", "no"),
    ("knew", "new"),
    ("peace", "piece"),
    ("through", "threw"),
    ("bare", "bear"),
    ("wait", "weight"),
    ("week", "weak"),
    ("passed", "past"),
)
_HOMOPHONE_CANONICAL = {
    word: group[0]
    for group in _HOMOPHONE_GROUPS
    for word in group
}


@dataclass
class STTVerificationResult:
    """STT 验证结果"""
    success: bool                  # 验证是否成功
    original_text: str             # 原始文本
    recognized_text: str           # STT 识别文本
    similarity_score: float        # 相似度得分 (0.0 - 1.0)
    word_error_rate: float         # 词错误率 (0.0 - 1.0)
    passed: bool                   # 是否通过质量检查
    confidence: float              # 置信度
    error_message: str = ""        # 错误信息
    skipped: bool = False


class STTVerifier:
    """
    STT 验证器
    
    使用 Whisper 模型进行语音转文本，验证 TTS 生成质量
    
    注意：需要安装 openai-whisper 或 whisper-api 依赖
    """
    
    def __init__(
        self,
        model_size: str = "base",    # Whisper 模型大小
        language: str = "zh",        # 验证语言
        similarity_threshold: float = 0.75,  # 相似度阈值
        enable_whisper: bool = False,  # 是否启用 Whisper（默认禁用，需要安装）
    ):
        self.model_size = model_size
        self.language = language
        self.similarity_threshold = similarity_threshold
        self.enable_whisper = enable_whisper
        
        self.whisper_model = None
        if enable_whisper:
            try:
                import whisper
                self.whisper_model = whisper.load_model(model_size)
                logger.info(f"✅ Whisper 模型加载成功: {model_size}")
            except ImportError:
                logger.warning("⚠️ Whisper 未安装，STT 验证已禁用")
                logger.info("   安装命令: pip install openai-whisper")
                self.enable_whisper = False
            except Exception as e:
                logger.error(f"❌ Whisper 模型加载失败: {e}")
                self.enable_whisper = False
        
        logger.info(
            f"STT 验证器初始化: model={model_size}, "
            f"language={language}, threshold={similarity_threshold}"
        )
    
    def verify(
        self,
        audio_data: bytes,
        original_text: str,
        audio_format: str = "mp3"
    ) -> STTVerificationResult:
        """
        验证 TTS 音频质量
        
        Args:
            audio_data: TTS 生成的音频数据
            original_text: 原始文本
            audio_format: 音频格式
        
        Returns:
            STTVerificationResult 验证结果
        """
        if not self.enable_whisper or not self.whisper_model:
            # 降级方案：使用简单的启发式验证
            return self._fallback_verification(original_text)
        
        try:
            # 将音频保存到临时文件
            with tempfile.NamedTemporaryFile(
                suffix=f".{audio_format}",
                delete=False
            ) as tmp_file:
                tmp_file.write(audio_data)
                tmp_path = tmp_file.name
            
            try:
                # 使用 Whisper 进行语音识别
                result = self.whisper_model.transcribe(
                    tmp_path,
                    language=self.language,
                    task="transcribe"
                )
                
                recognized_text = result.get("text", "").strip()
                
                # 计算相似度
                similarity = self._calculate_similarity(original_text, recognized_text)
                
                # 计算词错误率
                wer = self._calculate_word_error_rate(original_text, recognized_text)
                
                # 判断是否通过
                passed = similarity >= self.similarity_threshold
                
                return STTVerificationResult(
                    success=True,
                    original_text=original_text,
                    recognized_text=recognized_text,
                    similarity_score=similarity,
                    word_error_rate=wer,
                    passed=passed,
                    confidence=similarity
                )
            
            finally:
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        except Exception as e:
            logger.error(f"❌ STT 验证失败: {e}")
            return STTVerificationResult(
                success=False,
                original_text=original_text,
                recognized_text="",
                similarity_score=0.0,
                word_error_rate=1.0,
                passed=False,
                confidence=0.0,
                error_message=str(e)
            )
    
    def _fallback_verification(self, original_text: str) -> STTVerificationResult:
        """
        降级验证方案
        
        当 Whisper 不可用时，不应假定音频正确。返回 skipped，交由上层决定
        是否允许继续或进入人工审核。
        """
        return STTVerificationResult(
            success=False,
            original_text=original_text,
            recognized_text="",
            similarity_score=0.0,
            word_error_rate=1.0,
            passed=False,
            confidence=0.0,
            error_message="STT 验证未启用或模型不可用",
            skipped=True,
        )
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度
        
        使用顺序敏感的相似度，并先对源文本和 STT 文本执行同一套归一化。
        """
        normalized_text1, normalized_text2 = self._normalize_source_and_transcript(text1, text2)
        if not normalized_text1 or not normalized_text2:
            return 0.0

        return SequenceMatcher(None, normalized_text1, normalized_text2).ratio()

    def _normalize_compare_text(self, text: str) -> str:
        return self._normalize_common(text)

    def _normalize_source_and_transcript(self, source: str, transcript: str) -> Tuple[str, str]:
        normalized_source = self._normalize_common(source)
        normalized_transcript = self._normalize_common(transcript)
        normalized_transcript = self._normalize_spacing(normalized_source, normalized_transcript)
        normalized_source = self._normalize_homophones(normalized_source)
        normalized_transcript = self._normalize_homophones(normalized_transcript)
        return normalized_source, normalized_transcript

    def _normalize_common(self, text: str) -> str:
        """
        归一化 STT 对比文本。

        对源文本和转写文本使用同一规则，尽量消除标点、大小写、emoji、
        破折号等格式差异，但保留词边界。
        """
        value = str(text or "").casefold().strip()
        if not value:
            return ""

        value = value.translate({ord(ch): None for ch in "\u200b\u200c\u200d\ufeff"})
        value = value.replace("\u3000", " ")
        value = value.replace("’", "'").replace("‘", "'")
        value = value.replace("“", '"').replace("”", '"')
        value = re.sub(r"\b'|'\b", "", value)

        punctuation = (
            string.punctuation
            + "。！？；：，、"
            + "（）【】《》「」『』"
            + "\u2014\u2013…"
        )
        value = re.sub(f"[{re.escape(punctuation)}]", " ", value)
        value = re.sub(r"[^\w\s\u3400-\u4dbf\u4e00-\u9fff]", "", value)
        return re.sub(r"\s+", " ", value).strip()

    def _normalize_spacing(self, source: str, transcript: str) -> str:
        """
        对齐源文本和转写文本中的空格。

        这能处理 STT 常见的英文复合词拆分/合并问题：
        source=firefly, transcript=fire fly -> firefly；
        source=high school, transcript=highschool -> high school。
        """
        if not source or not transcript:
            return transcript

        matcher = SequenceMatcher(None, source, transcript, autojunk=False)
        normalized_parts: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                normalized_parts.append(transcript[j1:j2])
            elif tag == "delete":
                missing_source_part = source[i1:i2]
                if missing_source_part.isspace():
                    normalized_parts.append(missing_source_part)
            elif tag == "insert":
                inserted_transcript_part = transcript[j1:j2]
                if not inserted_transcript_part.isspace():
                    normalized_parts.append(inserted_transcript_part)
            elif tag == "replace":
                normalized_parts.append(transcript[j1:j2])
        return "".join(normalized_parts)

    def _tokenize_for_error_rate(self, text: str) -> list[str]:
        normalized = self._normalize_compare_text(text)
        return re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]|[a-z0-9]+", normalized)

    def _normalize_homophones(self, text: str) -> str:
        """
        规范化常见英文同音词，降低 STT 回验误报。

        该逻辑只用于源文本与转写文本的比较，不会改写 TTS 输入文本。
        """
        tokens = re.findall(r"[a-z0-9]+|\s+|.", str(text or ""))
        return "".join(_HOMOPHONE_CANONICAL.get(token, token) for token in tokens)
    
    def _calculate_word_error_rate(self, reference: str, hypothesis: str) -> float:
        """
        计算词错误率（Word Error Rate, WER）
        
        WER = (S + D + I) / N
        其中：
        - S: 替换次数
        - D: 删除次数  
        - I: 插入次数
        - N: 参考文本词数
        """
        normalized_reference, normalized_hypothesis = self._normalize_source_and_transcript(reference, hypothesis)
        ref_words = self._tokenize_for_error_rate(normalized_reference)
        hyp_words = self._tokenize_for_error_rate(normalized_hypothesis)
        if not ref_words or not hyp_words:
            return 1.0
        
        # 使用动态规划计算编辑距离
        m, n = len(ref_words), len(hyp_words)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if ref_words[i-1] == hyp_words[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = 1 + min(
                        dp[i-1][j],    # 删除
                        dp[i][j-1],    # 插入
                        dp[i-1][j-1]   # 替换
                    )
        
        edit_distance = dp[m][n]
        wer = edit_distance / m
        
        return min(1.0, wer)
    
    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model_size": self.model_size,
            "language": self.language,
            "threshold": self.similarity_threshold,
            "enabled": self.enable_whisper,
            "model_loaded": self.whisper_model is not None
        }
