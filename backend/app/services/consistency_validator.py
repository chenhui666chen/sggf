"""
一致性校验器 - 确保生成的细纲不偏离、不断裂、不遗漏

核心功能：
1. 主线一致性校验：检查本卷是否偏离史诗框架的核心主线
2. 卷间衔接校验：检查本卷开头是否承接上卷结尾
3. 伏笔完整性校验：检查本卷应处理的伏笔是否有遗漏

校验时机：
- 单卷生成完成后自动触发
- 可配置为阻断式（必须通过才保存）或提示式（警告但不阻断）

三层体系定位：
- 属于「反向校验」机制，在生成后对三层体系进行验证
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """问题严重程度"""
    ERROR = "error"        # 严重问题，建议重新生成
    WARNING = "warning"    # 警告，建议人工检查
    INFO = "info"          # 信息提示


class ValidationResult:
    """校验结果"""
    
    def __init__(self, passed: bool = True):
        self.passed = passed
        self.issues: List[Dict[str, Any]] = []
        self.dimension_scores: Dict[str, float] = {}
        self.suggestions: List[str] = []
        self.validated_at = datetime.now().isoformat()
    
    def add_issue(self, dimension: str, severity: IssueSeverity, 
                  message: str, details: str = ""):
        """添加一个问题"""
        self.issues.append({
            "dimension": dimension,
            "severity": severity.value,
            "message": message,
            "details": details
        })
        if severity == IssueSeverity.ERROR:
            self.passed = False
    
    def add_suggestion(self, suggestion: str):
        """添加改进建议"""
        self.suggestions.append(suggestion)
    
    def set_score(self, dimension: str, score: float):
        """设置维度得分（0-100）"""
        self.dimension_scores[dimension] = score
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "dimension_scores": self.dimension_scores,
            "suggestions": self.suggestions,
            "validated_at": self.validated_at,
            "error_count": len([i for i in self.issues if i['severity'] == 'error']),
            "warning_count": len([i for i in self.issues if i['severity'] == 'warning'])
        }
    
    def get_summary(self) -> str:
        """获取校验结果摘要"""
        status = "✅ 通过" if self.passed else "❌ 未通过"
        error_count = len([i for i in self.issues if i['severity'] == 'error'])
        warning_count = len([i for i in self.issues if i['severity'] == 'warning'])
        
        summary = f"校验结果：{status}\n"
        summary += f"- 严重问题：{error_count}\n"
        summary += f"- 警告：{warning_count}\n"
        
        if self.dimension_scores:
            summary += "\n各维度得分：\n"
            for dim, score in self.dimension_scores.items():
                summary += f"- {dim}：{score:.0f}分\n"
        
        if self.issues:
            summary += "\n问题详情：\n"
            for issue in self.issues:
                icon = "❌" if issue['severity'] == 'error' else "⚠️"
                summary += f"{icon} [{issue['dimension']}] {issue['message']}\n"
        
        if self.suggestions:
            summary += "\n改进建议：\n"
            for suggestion in self.suggestions:
                summary += f"💡 {suggestion}\n"
        
        return summary


class ConsistencyValidator:
    """一致性校验器"""
    
    def __init__(self, llm=None, strict_mode: bool = False):
        """初始化校验器
        
        Args:
            llm: LLM实例（用于AI校验，可选）
            strict_mode: 严格模式，开启后任何警告都会导致校验不通过
        """
        self.llm = llm
        self.strict_mode = strict_mode
    
    def validate(self, 
                 volume_content: str,
                 volume_index: int,
                 core_storyline: str = "",
                 prev_volume_summary: Optional[Dict[str, Any]] = None,
                 pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
                 framework_content: str = "") -> ValidationResult:
        """执行完整校验
        
        Args:
            volume_content: 生成的卷细纲内容
            volume_index: 当前卷索引
            core_storyline: 核心主线描述
            prev_volume_summary: 上一卷摘要（来自VolumeConnector）
            pending_foreshadowings: 本卷伏笔任务（来自ForeshadowingTracker）
            framework_content: 史诗框架内容
            
        Returns:
            ValidationResult 校验结果
        """
        logger.info(f"🔍 开始校验第{volume_index}卷一致性...")
        
        result = ValidationResult()
        
        if not volume_content:
            result.add_issue("general", IssueSeverity.ERROR, "卷内容为空")
            return result
        
        # 1. 主线一致性校验
        storyline_result = self._validate_storyline_consistency(
            volume_content, volume_index, core_storyline, framework_content
        )
        result.issues.extend(storyline_result['issues'])
        result.set_score("主线一致性", storyline_result['score'])
        
        # 2. 卷间衔接校验（第1卷跳过）
        if volume_index > 1 and prev_volume_summary:
            connection_result = self._validate_volume_connection(
                volume_content, volume_index, prev_volume_summary
            )
            result.issues.extend(connection_result['issues'])
            result.set_score("卷间衔接", connection_result['score'])
        else:
            result.set_score("卷间衔接", 100)
        
        # 3. 伏笔完整性校验
        if pending_foreshadowings:
            foreshadowing_result = self._validate_foreshadowing_coverage(
                volume_content, volume_index, pending_foreshadowings
            )
            result.issues.extend(foreshadowing_result['issues'])
            result.set_score("伏笔完整性", foreshadowing_result['score'])
        else:
            result.set_score("伏笔完整性", 100)
        
        # 4. 检查是否通过
        error_count = len([i for i in result.issues if i['severity'] == 'error'])
        warning_count = len([i for i in result.issues if i['severity'] == 'warning'])
        
        if error_count > 0:
            result.passed = False
        elif self.strict_mode and warning_count > 0:
            result.passed = False
        else:
            result.passed = True
        
        # 5. 生成建议
        result.suggestions = self._generate_suggestions(result)
        
        logger.info(f"✅ 第{volume_index}卷校验完成：{'通过' if result.passed else '未通过'}")
        return result
    
    def _validate_storyline_consistency(self, volume_content: str, 
                                        volume_index: int,
                                        core_storyline: str,
                                        framework_content: str) -> Dict[str, Any]:
        """校验主线一致性
        
        检查本卷是否偏离核心主线
        """
        issues = []
        score = 100
        
        # 如果没有核心主线，尝试从框架提取
        if not core_storyline and framework_content:
            core_storyline = self._extract_core_storyline(framework_content)
        
        if not core_storyline:
            return {"issues": [], "score": 100}  # 无法校验
        
        # 规则校验：检查关键词匹配
        storyline_keywords = self._extract_keywords(core_storyline)
        volume_keywords = self._extract_keywords(volume_content[:3000])  # 取开头部分
        
        if storyline_keywords:
            matched = len([kw for kw in storyline_keywords if kw in volume_content])
            match_ratio = matched / len(storyline_keywords)
            
            if match_ratio < 0.3:
                issues.append({
                    "dimension": "主线一致性",
                    "severity": IssueSeverity.WARNING.value,
                    "message": f"本卷与核心主线关键词匹配率较低（{match_ratio*100:.0f}%）",
                    "details": f"核心主线关键词：{', '.join(storyline_keywords[:5])}"
                })
                score = max(30, score - 40)
            elif match_ratio < 0.5:
                issues.append({
                    "dimension": "主线一致性",
                    "severity": IssueSeverity.INFO.value,
                    "message": f"本卷与核心主线关键词匹配率一般（{match_ratio*100:.0f}%）",
                    "details": ""
                })
                score = max(60, score - 20)
        
        # 检查本卷故事概述是否存在
        if not re.search(r'(故事概述|本卷概述|剧情梗概)', volume_content):
            issues.append({
                "dimension": "主线一致性",
                "severity": IssueSeverity.WARNING.value,
                "message": "未找到故事概述部分",
                "details": "建议在细纲开头包含本卷故事概述"
            })
            score = max(50, score - 20)
        
        return {"issues": issues, "score": score}
    
    def _validate_volume_connection(self, volume_content: str,
                                    volume_index: int,
                                    prev_volume_summary: Dict[str, Any]) -> Dict[str, Any]:
        """校验卷间衔接
        
        检查本卷开头是否承接上卷结尾
        
        🌟 优化后的校验逻辑：
        1. 扩大检测范围（前5000字）
        2. 增加多维度匹配（钩子 + 目标 + 人物状态 + 核心剧情）
        3. 降低误报阈值
        4. 关键词过少时跳过校验
        """
        issues = []
        score = 100
        
        # 🌟 扩大检测范围：取本卷开头内容（前5000字或第一章全部）
        # 尝试定位第一章结束位置
        first_chapter_end = 5000
        chapter_matches = list(re.finditer(r'第\d+章', volume_content))
        if len(chapter_matches) >= 2:
            first_chapter_end = chapter_matches[1].start()
        volume_start = volume_content[:max(first_chapter_end, 5000)]
        
        # 检查上卷结尾钩子是否被承接
        ending_hook = prev_volume_summary.get('ending_hook', '')
        next_target = prev_volume_summary.get('next_volume_target', '')
        character_status = prev_volume_summary.get('character_status_update', '')
        core_plot = prev_volume_summary.get('core_plot_completed', '')
        
        # 🌟 多维度提取关键词
        hook_keywords = self._extract_keywords(ending_hook, max_count=5)
        target_keywords = self._extract_keywords(next_target, max_count=5)
        character_keywords = self._extract_keywords(character_status, max_count=5)
        plot_keywords = self._extract_keywords(core_plot, max_count=5)
        
        # 合并去重
        all_keywords = list(set(hook_keywords + target_keywords + character_keywords + plot_keywords))
        
        # 🌟 关键词过少时跳过校验（避免误报）
        if len(all_keywords) < 3:
            logger.info(f"⚠️ 上卷摘要关键词不足（{len(all_keywords)}个），跳过卷间衔接校验")
            return {"issues": [], "score": 80}  # 给一个较高的默认分
        
        # 计算匹配率
        matched = [kw for kw in all_keywords if kw in volume_start]
        match_ratio = len(matched) / len(all_keywords)
        
        # 🌟 调整阈值：更宽容
        # 低于10%才算严重断裂，低于25%是警告
        if match_ratio < 0.1:
            issues.append({
                "dimension": "卷间衔接",
                "severity": IssueSeverity.ERROR.value,
                "message": f"本卷开头与上卷结尾衔接较弱（匹配率{match_ratio*100:.0f}%）",
                "details": f"上卷钩子：{ending_hook[:30]}... 匹配词：{matched[:3]}" if matched else f"上卷钩子：{ending_hook[:50]}"
            })
            score = 40  # 不再打过低的分
        elif match_ratio < 0.25:
            issues.append({
                "dimension": "卷间衔接",
                "severity": IssueSeverity.WARNING.value,
                "message": f"本卷开头与上卷衔接一般（匹配率{match_ratio*100:.0f}%）",
                "details": f"匹配关键词：{', '.join(matched[:5])}"
            })
            score = 60
        else:
            # 匹配较好
            score = 70 + int(match_ratio * 30)
            logger.info(f"✅ 卷间衔接校验通过，匹配率{match_ratio*100:.0f}%，关键词：{matched[:5]}")
        
        # 检查第一章是否存在（作为辅助检查）
        first_chapter_match = re.search(r'第\d+章', volume_content[:3000])
        if not first_chapter_match:
            issues.append({
                "dimension": "卷间衔接",
                "severity": IssueSeverity.INFO.value,  # 降级为INFO
                "message": "未找到明确的章节标题格式",
                "details": "建议使用标准章节格式（第X章）"
            })
        
        return {"issues": issues, "score": score}
    
    def _validate_foreshadowing_coverage(self, volume_content: str,
                                         volume_index: int,
                                         pending_foreshadowings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """校验伏笔完整性
        
        检查本卷应处理的伏笔是否有遗漏
        """
        issues = []
        score = 100
        
        if not pending_foreshadowings:
            return {"issues": [], "score": 100}
        
        # 按action分类
        plant_tasks = [t for t in pending_foreshadowings if t.get('action') == 'plant']
        pave_tasks = [t for t in pending_foreshadowings if t.get('action') == 'pave']
        reveal_tasks = [t for t in pending_foreshadowings if t.get('action') == 'reveal']
        
        total_tasks = len(pending_foreshadowings)
        covered_count = 0
        
        # 检查埋设任务
        for task in plant_tasks:
            content_keywords = self._extract_keywords(task.get('content', ''))
            if any(kw in volume_content for kw in content_keywords):
                covered_count += 1
            else:
                severity = IssueSeverity.ERROR if task.get('importance') == 'critical' else IssueSeverity.WARNING
                issues.append({
                    "dimension": "伏笔完整性",
                    "severity": severity.value,
                    "message": f"伏笔「{task.get('content', '')[:30]}...」应在本卷埋设但未找到",
                    "details": f"预计揭秘于第{task.get('reveal_volume', '?')}卷"
                })
        
        # 检查揭秘任务（更严格）
        for task in reveal_tasks:
            content_keywords = self._extract_keywords(task.get('content', ''))
            if any(kw in volume_content for kw in content_keywords):
                covered_count += 1
            else:
                issues.append({
                    "dimension": "伏笔完整性",
                    "severity": IssueSeverity.ERROR.value,
                    "message": f"伏笔「{task.get('content', '')[:30]}...」应在本卷揭秘但未找到",
                    "details": f"埋设于第{task.get('planted_volume', '?')}卷"
                })
        
        # 检查铺垫任务（宽松）
        for task in pave_tasks:
            content_keywords = self._extract_keywords(task.get('content', ''))
            if any(kw in volume_content for kw in content_keywords):
                covered_count += 1
            else:
                issues.append({
                    "dimension": "伏笔完整性",
                    "severity": IssueSeverity.INFO.value,
                    "message": f"伏笔「{task.get('content', '')[:30]}...」可在本卷铺垫但未明确提及",
                    "details": "铺垫非强制，但建议加入以增强连贯性"
                })
        
        # 计算得分
        if total_tasks > 0:
            coverage_ratio = covered_count / total_tasks
            score = int(coverage_ratio * 100)
        
        return {"issues": issues, "score": score}
    
    def _extract_core_storyline(self, framework_content: str) -> str:
        """从框架中提取核心主线"""
        patterns = [
            r'##\s*[一1][、.]?\s*核心主线[\s\S]*?(?=##|$)',
            r'核心主线[：:]\s*([^\n]+)',
            r'【核心主线】[\s\S]*?(?=【|##|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, framework_content)
            if match:
                return match.group(0)[:500]
        
        return ""
    
    def _extract_keywords(self, text: str, min_length: int = 2, max_count: int = 15) -> List[str]:
        """从文本中提取关键词
        
        简单的关键词提取，提取中文词语
        """
        if not text:
            return []
        
        # 提取连续的中文字符
        words = re.findall(r'[\u4e00-\u9fa5]{2,6}', text)
        
        # 过滤停用词
        stopwords = {'可以', '这个', '那个', '已经', '就是', '还是', '什么', '怎么',
                     '其中', '关于', '通过', '进行', '开始', '结束', '需要', '建议',
                     '第一', '第二', '第三', '本卷', '上卷', '下卷'}
        words = [w for w in words if w not in stopwords and len(w) >= min_length]
        
        # 去重并限制数量
        seen = set()
        unique_words = []
        for w in words:
            if w not in seen:
                seen.add(w)
                unique_words.append(w)
                if len(unique_words) >= max_count:
                    break
        
        return unique_words
    
    def _generate_suggestions(self, result: ValidationResult) -> List[str]:
        """根据校验结果生成改进建议"""
        suggestions = []
        
        # 根据维度得分生成建议
        if result.dimension_scores.get("主线一致性", 100) < 60:
            suggestions.append("在故事概述中明确本卷核心剧情与全书主线的关系")
            suggestions.append("确保主角在本卷中有明确的目标和成长")
        
        if result.dimension_scores.get("卷间衔接", 100) < 60:
            suggestions.append("第一章开头应直接承接上卷结尾的悬念或场景")
            suggestions.append("在章节概述中明确与上卷的时间、空间衔接")
        
        if result.dimension_scores.get("伏笔完整性", 100) < 60:
            suggestions.append("检查本卷应埋设/揭秘的伏笔是否在章节细纲中体现")
            suggestions.append("为需要揭秘的伏笔安排专门的章节或场景")
        
        # 根据问题类型生成建议
        error_dimensions = set([i['dimension'] for i in result.issues if i['severity'] == 'error'])
        
        if "卷间衔接" in error_dimensions:
            suggestions.insert(0, "⚠️ 建议重新生成本卷，确保与上卷无缝衔接")
        
        if "伏笔完整性" in error_dimensions:
            suggestions.insert(0, "⚠️ 有重要伏笔遗漏，建议补充相关章节内容")
        
        return suggestions
    
    def quick_check(self, volume_content: str) -> bool:
        """快速校验（仅检查基本格式）
        
        用于非关键场景的快速判断
        """
        if not volume_content or len(volume_content) < 500:
            return False
        
        # 检查是否有章节结构
        if not re.search(r'第\d+章', volume_content):
            return False
        
        # 检查是否有故事概述
        if not re.search(r'(故事概述|本卷概述|剧情)', volume_content):
            return False
        
        return True


class ChapterRenumberer:
    """章节编号自动修正器
    
    检测AI生成的章节编号是否与预期一致，若不一致则自动修正。
    确保多卷拼接时章节序号连续正确。
    """
    
    def __init__(self):
        """初始化章节编号修正器"""
        pass
    
    def detect_and_fix(self, content: str, expected_start: int, 
                       expected_count_range: tuple = None) -> Dict[str, Any]:
        """检测并修正章节编号
        
        Args:
            content: 生成的卷细纲内容
            expected_start: 预期起始章节号
            expected_count_range: 预期章节数量范围 (min, max)，可选
            
        Returns:
            修正结果字典：
            - fixed_content: 修正后的内容
            - was_fixed: 是否进行了修正
            - original_range: 原始章节范围 (start, end)
            - fixed_range: 修正后章节范围 (start, end)
            - offset: 偏移量
            - details: 详细信息
        """
        if not content:
            return {
                "fixed_content": content,
                "was_fixed": False,
                "original_range": (0, 0),
                "fixed_range": (0, 0),
                "offset": 0,
                "details": "内容为空"
            }
        
        # 1. 解析所有章节编号
        chapter_numbers = self._extract_chapter_numbers(content)
        
        if not chapter_numbers:
            return {
                "fixed_content": content,
                "was_fixed": False,
                "original_range": (0, 0),
                "fixed_range": (0, 0),
                "offset": 0,
                "details": "未找到章节编号"
            }
        
        original_start = min(chapter_numbers)
        original_end = max(chapter_numbers)
        
        # 2. 计算偏移量
        offset = expected_start - original_start
        
        # 3. 如果偏移量为0，无需修正
        if offset == 0:
            logger.info(f"✅ 章节编号正确：第{original_start}-{original_end}章，无需修正")
            return {
                "fixed_content": content,
                "was_fixed": False,
                "original_range": (original_start, original_end),
                "fixed_range": (original_start, original_end),
                "offset": 0,
                "details": "章节编号正确，无需修正"
            }
        
        # 4. 需要修正
        logger.warning(f"⚠️ 检测到章节编号偏差：AI生成第{original_start}-{original_end}章，预期从第{expected_start}章开始")
        logger.info(f"🔧 正在自动修正，偏移量: {offset:+d}")
        
        fixed_content = self._renumber_chapters(content, offset)
        
        fixed_start = original_start + offset
        fixed_end = original_end + offset
        
        logger.info(f"✅ 章节编号已修正：第{fixed_start}-{fixed_end}章")
        
        return {
            "fixed_content": fixed_content,
            "was_fixed": True,
            "original_range": (original_start, original_end),
            "fixed_range": (fixed_start, fixed_end),
            "offset": offset,
            "details": f"已将第{original_start}-{original_end}章修正为第{fixed_start}-{fixed_end}章（偏移{offset:+d}）"
        }
    
    def _extract_chapter_numbers(self, content: str) -> List[int]:
        """提取内容中的所有章节编号
        
        Args:
            content: 内容文本
            
        Returns:
            章节编号列表
        """
        # 匹配多种章节格式
        patterns = [
            r'第\s*(\d+)\s*章',           # 第X章
            r'###\s*第\s*(\d+)\s*章',      # ### 第X章
            r'####\s*第\s*(\d+)\s*章',     # #### 第X章
        ]
        
        numbers = set()
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                try:
                    numbers.add(int(match))
                except ValueError:
                    continue
        
        return sorted(list(numbers))
    
    def _renumber_chapters(self, content: str, offset: int) -> str:
        """重新编号所有章节
        
        Args:
            content: 原始内容
            offset: 偏移量（正数增加，负数减少）
            
        Returns:
            修正后的内容
        """
        def replace_chapter_num(match):
            """替换函数：将章节号加上偏移量"""
            prefix = match.group(1)  # 前缀（如 "第" 或 "### 第"）
            old_num = int(match.group(2))  # 原章节号
            suffix = match.group(3)  # 后缀（如 "章"）
            new_num = old_num + offset
            return f"{prefix}{new_num}{suffix}"
        
        # 匹配并替换所有章节编号格式
        # 格式1: 第X章
        result = re.sub(
            r'(第\s*)(\d+)(\s*章)',
            replace_chapter_num,
            content
        )
        
        # 格式2: ### 第X章（Markdown标题）
        result = re.sub(
            r'(###\s*第\s*)(\d+)(\s*章)',
            replace_chapter_num,
            result
        )
        
        # 格式3: #### 第X章
        result = re.sub(
            r'(####\s*第\s*)(\d+)(\s*章)',
            replace_chapter_num,
            result
        )
        
        # 格式4: 处理卷标题中的章节范围描述
        # 例如：第1卷详细规划（第1-第30章）→ 第1卷详细规划（第31-第60章）
        def replace_range(match):
            prefix = match.group(1)
            start_num = int(match.group(2)) + offset
            middle = match.group(3)
            end_num = int(match.group(4)) + offset
            suffix = match.group(5)
            return f"{prefix}{start_num}{middle}{end_num}{suffix}"
        
        result = re.sub(
            r'(第\s*)(\d+)(\s*[-—~至到]\s*第?\s*)(\d+)(\s*章)',
            replace_range,
            result
        )
        
        return result
    
    def validate_continuity(self, volumes_detail: Dict[int, Dict]) -> Dict[str, Any]:
        """验证多卷章节连续性
        
        Args:
            volumes_detail: 卷详情字典 {卷号: {chapters_start, chapters_end, outline}}
            
        Returns:
            验证结果
        """
        issues = []
        sorted_vols = sorted(volumes_detail.items())
        
        for i in range(len(sorted_vols) - 1):
            current_vol_num, current_vol = sorted_vols[i]
            next_vol_num, next_vol = sorted_vols[i + 1]
            
            current_end = current_vol.get("chapters_end", 0)
            next_start = next_vol.get("chapters_start", 0)
            
            if current_end + 1 != next_start:
                gap = next_start - current_end - 1
                issues.append({
                    "type": "gap" if gap > 0 else "overlap",
                    "volumes": [current_vol_num, next_vol_num],
                    "current_end": current_end,
                    "next_start": next_start,
                    "gap": gap,
                    "message": f"第{current_vol_num}卷结束于第{current_end}章，第{next_vol_num}卷从第{next_start}章开始"
                               + (f"（缺失{gap}章）" if gap > 0 else f"（重叠{-gap}章）")
                })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "total_volumes": len(volumes_detail),
            "chapter_range": (
                min(v.get("chapters_start", 0) for v in volumes_detail.values()) if volumes_detail else 0,
                max(v.get("chapters_end", 0) for v in volumes_detail.values()) if volumes_detail else 0
            )
        }


def get_consistency_validator(llm=None, strict_mode: bool = False) -> ConsistencyValidator:
    """获取一致性校验器实例
    
    Args:
        llm: LLM实例（可选）
        strict_mode: 严格模式
        
    Returns:
        ConsistencyValidator实例
    """
    return ConsistencyValidator(llm=llm, strict_mode=strict_mode)


def get_chapter_renumberer() -> ChapterRenumberer:
    """获取章节编号修正器实例
    
    Returns:
        ChapterRenumberer实例
    """
    return ChapterRenumberer()
