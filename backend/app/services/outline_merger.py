"""
长篇框架与卷细纲智能拼接模块

功能：
1. 框架生成时添加锚点标记
2. 智能拼接框架与已扩展的卷细纲
3. 状态检测：是否已生成框架、已扩展哪些卷
4. 完整性校验：章节连续性、卷范围检查
"""
import re
import json
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)
MAX_CHAPTERS_PER_VOLUME = 100
MERGED_VOLUME_HEADING_PATTERN = re.compile(
    r'^\s*#{1,6}\s*【第\s*(?P<number>\d+)\s*卷】(?:\s*[《](?P<title>[^》\n]*)[》])?\s*$'
)
MERGED_VOLUME_HEADING_FALLBACK_PATTERN = re.compile(
    r'^\s*#{1,6}\s*【第\s*(?P<number>\d+)\s*卷】\s*(?P<title>[^\n]*)$'
)
MERGED_DETAIL_SUMMARY_PATTERN = re.compile(
    r'^\s*<summary>📖 第(?P<number>\d+)卷详细章节（第(?P<start>\d+)-(?P<end>\d+)章'
)
MERGED_OUTLINE_STATS_PATTERN = re.compile(r'^\s*_✅ 共\d+卷 .*_$')
CHAPTER_RANGE_LABEL_PATTERN = re.compile(
    r'(?P<label>覆盖章节|章节范围|章节区间|章节：)\s*[：:]\s*(?P<start>\d+)\s*[-~—至到]+\s*(?P<end>\d+)(?P<suffix>\s*章?)'
)
CHAPTER_RANGE_PATTERN = re.compile(
    r'第\s*(?P<start>\d+)\s*[-~—至到]+\s*(?:第\s*)?(?P<end>\d+)\s*章'
)
CHAPTER_NUMBER_PATTERN = re.compile(r'第\s*(?P<number>\d+)\s*章')
VOLUME_DETAIL_CHAPTER_HEADING_PATTERN = re.compile(
    r'(?m)^(?:#{1,6}\s*)?(?:\*\*)?\s*第\s*(?P<number>\d+)\s*章(?:\s*[：:、\-]\s*|\s+)?'
)
VOLUME_DETAIL_SECTION_HEADING_PATTERN_TEMPLATE = (
    r'(?m)^(?P<prefix>\s*(?:#{{1,6}}\s*)?(?:[一二三四1234][、.．，,]?\s*)?){title}\s*$'
)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_volume_detail_heading_numbers(detail_content: str) -> List[int]:
    if not detail_content or not detail_content.strip():
        return []

    numbers: List[int] = []
    seen: set[int] = set()
    for match in VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(detail_content):
        chapter_number = _safe_int(match.group("number"), 0)
        if chapter_number <= 0 or chapter_number in seen:
            continue
        seen.add(chapter_number)
        numbers.append(chapter_number)
    return numbers


def _extract_volume_detail_count_from_text(content: str) -> int:
    if not content or not content.strip():
        return 0

    heading_numbers = _extract_volume_detail_heading_numbers(content)
    if heading_numbers:
        return len(heading_numbers)

    range_match = CHAPTER_RANGE_PATTERN.search(content)
    if range_match:
        start = _safe_int(range_match.group("start"), 0)
        end = _safe_int(range_match.group("end"), 0)
        if end >= start > 0:
            return end - start + 1

    labeled_range_match = CHAPTER_RANGE_LABEL_PATTERN.search(content)
    if labeled_range_match:
        start = _safe_int(labeled_range_match.group("start"), 0)
        end = _safe_int(labeled_range_match.group("end"), 0)
        if end >= start > 0:
            return end - start + 1

    estimated_match = re.search(r'预计\s*(\d+)(?:\s*[-~—至到]+\s*(\d+))?\s*章', content)
    if estimated_match:
        lower = _safe_int(estimated_match.group(1), 0)
        upper = _safe_int(estimated_match.group(2) or lower, 0)
        return max(lower, upper, 0)

    exact_match = re.search(r'章节规模[：:]\s*(\d+)\s*章?', content)
    if exact_match:
        return max(_safe_int(exact_match.group(1), 0), 0)

    return 0


def _estimate_volume_chapter_count(vol_data: Dict[str, any]) -> int:
    if not isinstance(vol_data, dict):
        return 0

    chapter_count = max(_safe_int(vol_data.get("chapter_count"), 0), 0)
    if chapter_count > 0:
        return chapter_count

    chapter_range = vol_data.get("chapters_range") or [0, 0]
    if isinstance(chapter_range, (list, tuple)) and len(chapter_range) >= 2:
        start = _safe_int(chapter_range[0], 0)
        end = _safe_int(chapter_range[1], 0)
        if start > 0 and end >= start:
            return end - start + 1

    for field in ("detail", "summary"):
        estimated = _extract_volume_detail_count_from_text(str(vol_data.get(field) or ""))
        if estimated > 0:
            return estimated

    return 0


def _find_volume_detail_section_bounds(content: str, title: str) -> Optional[Tuple[int, int]]:
    if not content or not title:
        return None

    pattern = re.compile(
        VOLUME_DETAIL_SECTION_HEADING_PATTERN_TEMPLATE.format(title=re.escape(title))
    )
    match = pattern.search(content)
    if not match:
        return None

    start = match.start()
    next_match = pattern.search(content, match.end())
    if next_match:
        return start, next_match.start()

    next_heading_pattern = re.compile(r'(?m)^\s*#{1,6}\s*[一二三四五六七八九十1234567890]+[、.．，,]?\s*')
    next_heading = next_heading_pattern.search(content, match.end())
    if next_heading:
        return start, next_heading.start()

    return start, len(content)


def _extract_last_volume_detail_field_value(content: str, label: str) -> str:
    if not content or not label:
        return ""

    pattern = re.compile(
        rf"(?m)^\s*(?:[-*]\s*)?(?:✅\s*)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[：:]\s*(?P<value>.+?)\s*$"
    )
    matches = [match.group("value").strip() for match in pattern.finditer(content) if match.group("value")]
    return matches[-1] if matches else ""


def _build_volume_detail_fallback_foreshadow_lines(content: str) -> List[str]:
    lines: List[str] = []
    foreshadowing_matches = re.findall(
        r"(?m)^\s*[-*]\s*(?:\*\*)?伏笔事项(?:\*\*)?\s*[：:]\s*(.+?)\s*$",
        content or "",
    )
    for item in foreshadowing_matches[:3]:
        text = str(item or "").strip()
        if text:
            lines.append(f"- 待定章节：埋设 {text}")

    return lines or ["- 当前卷暂无强制伏笔任务。"]


def _ensure_volume_detail_tail_sections(content: str) -> str:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return ""

    foreshadowing_bounds = _find_volume_detail_section_bounds(normalized_content, "伏笔埋设检查")
    if foreshadowing_bounds is None:
        normalized_content = (
            normalized_content.rstrip()
            + "\n\n## 三、伏笔埋设检查\n"
            + "\n".join(_build_volume_detail_fallback_foreshadow_lines(normalized_content))
        ).strip()

    connection_bounds = _find_volume_detail_section_bounds(normalized_content, "卷尾衔接检查")
    last_plot_function = _extract_last_volume_detail_field_value(normalized_content, "情节作用")
    last_chapter_hook = _extract_last_volume_detail_field_value(normalized_content, "结尾钩子")
    fallback_completion = last_plot_function or "完成当前卷阶段推进，并将主线稳定交接到下一阶段。"
    fallback_hook = last_chapter_hook or "当前卷已在末章留下新的推进入口。"
    fallback_next_opening = (
        f"承接“{fallback_hook}”直接切入下一阶段行动。"
        if fallback_hook
        else "承接本卷末章局势，直接切入下一阶段行动。"
    )

    required_connection_lines: List[str] = []
    connection_text = normalized_content[connection_bounds[0]:connection_bounds[1]] if connection_bounds else ""
    if "本卷任务完成" not in connection_text and "本卷任务完成情况" not in connection_text:
        required_connection_lines.append(f"✅ 本卷任务完成：{fallback_completion}")
    if "下卷开局场景" not in connection_text:
        required_connection_lines.append(f"✅ 下卷开局场景：{fallback_next_opening}")
    if "卷尾钩子" not in connection_text:
        required_connection_lines.append(f"✅ 卷尾钩子：{fallback_hook}")

    if connection_bounds is None:
        normalized_content = (
            normalized_content.rstrip()
            + "\n\n## 四、卷尾衔接检查\n"
            + "\n".join(required_connection_lines or ["✅ 当前卷已形成基本承接结构。"])
        ).strip()
    elif required_connection_lines:
        insert_at = connection_bounds[1]
        before = normalized_content[:insert_at].rstrip()
        after = normalized_content[insert_at:].lstrip("\n")
        normalized_content = (
            before
            + "\n"
            + "\n".join(required_connection_lines)
            + ("\n\n" + after if after else "")
        ).strip()

    return normalized_content


def _shift_chapter_references(text: str, delta: int) -> str:
    if not text or delta == 0:
        return text

    def replace_labeled_range(match: re.Match[str]) -> str:
        start = _safe_int(match.group("start"), 0)
        end = _safe_int(match.group("end"), 0)
        return (
            f"{match.group('label')}：{start + delta}-{end + delta}{match.group('suffix') or ''}"
            if start > 0 and end > 0
            else match.group(0)
        )

    def replace_range(match: re.Match[str]) -> str:
        start = _safe_int(match.group("start"), 0)
        end = _safe_int(match.group("end"), 0)
        if start <= 0 or end <= 0:
            return match.group(0)
        return f"第{start + delta}-{end + delta}章"

    def replace_single(match: re.Match[str]) -> str:
        number = _safe_int(match.group("number"), 0)
        if number <= 0:
            return match.group(0)
        return f"第{number + delta}章"

    shifted = CHAPTER_RANGE_LABEL_PATTERN.sub(replace_labeled_range, text)
    shifted = CHAPTER_RANGE_PATTERN.sub(replace_range, shifted)
    shifted = CHAPTER_NUMBER_PATTERN.sub(replace_single, shifted)
    return shifted


def _renumber_volume_detail_content(
    detail_content: str,
    *,
    expected_start: int,
    original_start: int = 0,
) -> str:
    if not detail_content or not detail_content.strip():
        return detail_content

    heading_numbers = _extract_volume_detail_heading_numbers(detail_content)
    detected_start = heading_numbers[0] if heading_numbers else max(_safe_int(original_start, 0), 0)
    if detected_start <= 0:
        return detail_content

    delta = int(expected_start or 0) - detected_start
    return _shift_chapter_references(detail_content, delta)


def normalize_volume_detail_layout(
    volumes_data: Dict[str, any],
    *,
    rewrite_detail_content: bool = False,
) -> Dict[str, any]:
    if not isinstance(volumes_data, dict):
        return {
            "total_volumes": 0,
            "framework_generated_at": None,
            "framework_header": "",
            "framework_footer": "",
            "volumes": {},
        }

    normalized = json.loads(json.dumps(volumes_data, ensure_ascii=False))
    volumes = normalized.get("volumes")
    if not isinstance(volumes, dict):
        normalized["volumes"] = {}
        return normalized

    running_chapter_end = 0
    for vol_key, vol_data in sorted(volumes.items(), key=lambda item: int(item[0])):
        if not isinstance(vol_data, dict):
            continue

        chapter_count = _estimate_volume_chapter_count(vol_data)
        detail_text = str(vol_data.get("detail") or "").strip()
        if vol_data.get("type") == "detail" and detail_text:
            vol_data["detail"] = _ensure_volume_detail_tail_sections(detail_text)
            detail_text = str(vol_data.get("detail") or "").strip()
        if chapter_count <= 0:
            continue

        expected_start = running_chapter_end + 1
        expected_end = expected_start + chapter_count - 1
        original_range = vol_data.get("chapters_range") or [0, 0]
        original_start = _safe_int(original_range[0], 0)

        vol_data["chapter_count"] = chapter_count
        if vol_data.get("type") == "detail":
            vol_data["chapters_range"] = [expected_start, expected_end]
            if rewrite_detail_content and detail_text:
                vol_data["detail"] = _renumber_volume_detail_content(
                    detail_text,
                    expected_start=expected_start,
                    original_start=original_start,
                )
                vol_data["detail"] = _ensure_volume_detail_tail_sections(str(vol_data.get("detail") or ""))

        running_chapter_end = expected_end

    return normalized


def add_volume_anchors(framework: str, total_volumes: int) -> str:
    """
    为长篇框架添加锚点标记
    
    Args:
        framework: 原始框架内容
        total_volumes: 总卷数
    
    Returns:
        添加了锚点的框架内容
    """
    lines = framework.split('\n')
    result = []
    
    # 🔧 增强版：支持多种卷标题格式
    # 格式1: ## 第1卷：标题  或  ## 第1卷:标题
    # 格式2: ## 第1卷 标题  (无冒号)
    # 格式3: 第1卷：标题  (无markdown标题)
    # 格式4: 第一卷：标题  (中文数字)
    volume_patterns = [
        re.compile(r'^(#+)\s*第\s*([0-9]+)\s*卷\s*[：:]'),           # ## 第1卷：
        re.compile(r'^(#+)\s*第\s*([0-9]+)\s*卷\s+'),                # ## 第1卷 标题
        re.compile(r'^第\s*([0-9]+)\s*卷\s*[：:]'),                  # 第1卷：
        re.compile(r'^第\s*([0-9]+)\s*卷\s+'),                       # 第1卷 标题
        re.compile(r'^\*\*第\s*([0-9]+)\s*卷\s*[：:]'),             # **第1卷：
        re.compile(r'^\|\s*第\s*([0-9]+)\s*卷'),                     # | 第1卷 (表格格式)
    ]
    
    # 中文数字映射
    cn_num_map = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20
    }
    cn_volume_pattern = re.compile(r'^(#+)?\s*第([\u4e00-\u9fa5]+)卷\s*[：:]')
    
    added_volumes = set()  # 记录已添加锚点的卷
    
    for line in lines:
        vol_num = None
        matched = False
        
        # 尝试匹配阿拉伯数字格式
        for pattern in volume_patterns:
            match = pattern.match(line)
            if match:
                # 根据模式不同，数字在不同的组
                groups = match.groups()
                for g in groups:
                    if g and g.isdigit():
                        vol_num = int(g)
                        matched = True
                        break
                if matched:
                    break
        
        # 尝试匹配中文数字格式
        if not matched:
            cn_match = cn_volume_pattern.match(line)
            if cn_match:
                cn_num = cn_match.group(2)
                if cn_num in cn_num_map:
                    vol_num = cn_num_map[cn_num]
                    matched = True
        
        if matched and vol_num and vol_num not in added_volumes:
            # 在卷标题前插入起始锚点
            result.append(f'<!-- VOLUME_{vol_num}_ANCHOR_START -->')
            result.append(line)
            result.append(f'<!-- VOLUME_{vol_num}_ANCHOR_END -->')
            added_volumes.add(vol_num)
        else:
            result.append(line)
    
    # 🛡️ 如果没有匹配到任何卷，尝试回退方案：为每个卷手动添加锚点
    if len(added_volumes) == 0 and total_volumes > 0:
        logger.warning(f"⚠️ 未匹配到卷标题，使用回退方案：添加 {total_volumes} 个隐式锚点")
        # 在内容开头添加隐式锚点（让系统能识别框架存在）
        hidden_anchors = []
        for i in range(1, total_volumes + 1):
            hidden_anchors.append(f'<!-- VOLUME_{i}_ANCHOR_START --><!-- VOLUME_{i}_ANCHOR_END -->')
        result.insert(0, '<!-- EPIC_FRAMEWORK_ANCHORS: ' + ' '.join([str(i) for i in range(1, total_volumes + 1)]) + ' -->')
        result.insert(1, '\n'.join(hidden_anchors))
        logger.info(f"✅ 回退方案：已添加 {total_volumes} 个隐式锚点")
    else:
        logger.info(f"✅ 已为 {len(added_volumes)}/{total_volumes} 卷框架添加锚点标记")
    
    return '\n'.join(result)


def merge_framework_with_volumes(
    framework: str,
    volumes_detail: Dict[int, str]
) -> str:
    """
    智能拼接框架与卷细纲
    
    Args:
        framework: 长篇框架内容（可能包含锚点，也可能不包含）
        volumes_detail: 已扩展的卷细纲 {1: "第1卷细纲", 3: "第3卷细纲"}
    
    Returns:
        拼接后的完整大纲
    """
    if not framework:
        return ""
    
    if not volumes_detail:
        # 如果没有扩展的卷，返回框架（移除锚点）
        return _remove_anchor_marks(framework)
    
    # 🔧 检测框架是否包含锚点
    has_anchors = 'VOLUME_' in framework and 'ANCHOR_' in framework
    
    if has_anchors:
        # 有锚点：使用原有的精确插入逻辑
        return _merge_with_anchors(framework, volumes_detail)
    else:
        # 无锚点：直接在框架末尾追加细纲
        return _merge_append_mode(framework, volumes_detail)


def _merge_with_anchors(framework: str, volumes_detail: Dict[int, str]) -> str:
    """有锚点时的精确插入模式"""
    lines = framework.split('\n')
    result = []
    
    i = 0
    in_expanded_volume = False
    current_volume_num = None
    
    while i < len(lines):
        line = lines[i]
        
        # 检测卷锚点起始标记
        anchor_start_match = re.match(r'<!-- VOLUME_(\d+)_ANCHOR_START -->', line)
        if anchor_start_match:
            current_volume_num = int(anchor_start_match.group(1))
            in_expanded_volume = current_volume_num in volumes_detail
            i += 1
            continue
        
        # 检测卷锚点结束标记
        anchor_end_match = re.match(r'<!-- VOLUME_(\d+)_ANCHOR_END -->', line)
        if anchor_end_match:
            vol_num = int(anchor_end_match.group(1))
            
            if vol_num in volumes_detail:
                result.append('')
                result.append(f'<details open>')
                result.append(f'<summary>📖 第{vol_num}卷详细章节（点击收起/展开）</summary>')
                result.append('')
                result.append(volumes_detail[vol_num])
                result.append('')
                result.append('</details>')
                result.append('')
            
            in_expanded_volume = False
            current_volume_num = None
            i += 1
            continue
        
        if in_expanded_volume:
            next_volume_match = re.match(r'^(#+)\s*第([0-9]+)卷[：:]', line) if i + 1 < len(lines) else None
            if next_volume_match:
                in_expanded_volume = False
            else:
                i += 1
                continue
        
        result.append(line)
        i += 1
    
    result.append('')
    result.append('---')
    result.append(f'_✅ 已生成完整框架 | 已扩展卷：{sorted(volumes_detail.keys())} | 拼接时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}_')
    
    logger.info(f"✅ 框架拼接完成（锚点模式）：{len(volumes_detail)} 个卷的细纲已插入")
    return '\n'.join(result)


def _merge_append_mode(framework: str, volumes_detail: Dict[int, str]) -> str:
    """无锚点时的追加模式：直接在框架末尾追加所有细纲"""
    result = [_remove_anchor_marks(framework)]
    
    result.append('')
    result.append('---')
    result.append('')
    result.append('## 📖 已扩展的卷细纲')
    result.append('')
    
    # 按卷号排序追加
    for vol_num in sorted(volumes_detail.keys()):
        result.append(f'<details open>')
        result.append(f'<summary>📖 第{vol_num}卷详细章节（点击收起/展开）</summary>')
        result.append('')
        result.append(volumes_detail[vol_num])
        result.append('')
        result.append('</details>')
        result.append('')
    
    result.append('---')
    result.append(f'_✅ 已生成完整框架 | 已扩展卷：{sorted(volumes_detail.keys())} | 拼接时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}_')
    
    logger.info(f"✅ 框架拼接完成（追加模式）：{len(volumes_detail)} 个卷的细纲已追加")
    return '\n'.join(result)


def detect_framework_state(outline_content: str) -> Dict[str, any]:
    """
    检测框架状态
    
    Args:
        outline_content: 大纲内容
    
    Returns:
        {
            "hasFramework": bool,
            "totalVolumes": int,
            "expandedVolumes": [1, 3, 5],
            "frameworkGeneratedAt": datetime or None
        }
    """
    if not outline_content:
        return {
            "hasFramework": False,
            "totalVolumes": 0,
            "expandedVolumes": [],
            "frameworkGeneratedAt": None
        }
    
    # 🔧 增强检测：支持多种锚点标记格式
    # 检测是否有锚点标记（说明有框架）
    has_anchors = 'VOLUME_' in outline_content and 'ANCHOR_' in outline_content
    
    # 检测回退方案的隐式锚点
    has_epic_marker = 'EPIC_FRAMEWORK_ANCHORS:' in outline_content
    
    # 提取总卷数
    volume_numbers = set()
    
    # 方式1：从标准锚点提取
    volume_pattern = re.compile(r'<!-- VOLUME_(\d+)_ANCHOR_START -->')
    for match in volume_pattern.finditer(outline_content):
        volume_numbers.add(int(match.group(1)))
    
    # 方式2：从回退锚点标记提取
    if not volume_numbers and has_epic_marker:
        epic_marker_pattern = re.compile(r'<!-- EPIC_FRAMEWORK_ANCHORS: ([\d\s]+) -->')
        epic_match = epic_marker_pattern.search(outline_content)
        if epic_match:
            nums = epic_match.group(1).strip().split()
            for n in nums:
                if n.isdigit():
                    volume_numbers.add(int(n))
    
    # 方式3：如果仍然没有，尝试从卷标题直接提取
    if not volume_numbers:
        title_patterns = [
            re.compile(r'^(#+)?\s*第\s*(\d+)\s*卷', re.MULTILINE),
            re.compile(r'第\s*(\d+)\s*卷', re.MULTILINE),
        ]
        for pattern in title_patterns:
            for match in pattern.finditer(outline_content):
                groups = match.groups()
                for g in groups:
                    if g and g.isdigit():
                        volume_numbers.add(int(g))
            if volume_numbers:
                break
    
    total_volumes = max(volume_numbers) if volume_numbers else 0
    
    # 提取已扩展的卷编号（有<details>区块的卷）
    expanded_volumes = []
    detail_pattern = re.compile(r'<summary>📖 第(\d+)卷详细章节')
    for match in detail_pattern.finditer(outline_content):
        expanded_volumes.append(int(match.group(1)))
    
    # 尝试提取生成时间
    time_pattern = re.compile(r'拼接时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})')
    time_match = time_pattern.search(outline_content)
    generated_at = time_match.group(1) if time_match else None
    
    # 🛡️ 框架存在判断逻辑
    has_framework = (
        has_anchors or 
        has_epic_marker or 
        total_volumes >= 5  # 如果检测到足够多的卷，认为是框架
    )
    
    return {
        "hasFramework": has_framework,
        "totalVolumes": total_volumes,
        "expandedVolumes": sorted(expanded_volumes),
        "frameworkGeneratedAt": generated_at
    }


def validate_outline_integrity(
    framework: str,
    volumes_detail: Dict[int, Dict[str, any]]
) -> Dict[str, any]:
    """
    校验框架与细纲的完整性
    
    Args:
        framework: 框架内容
        volumes_detail: {
            1: {"chapters_start": 1, "chapters_end": 80, "outline": "..."},
            2: {"chapters_start": 81, "chapters_end": 152, "outline": "..."}
        }
    
    Returns:
        {
            "valid": bool,
            "issues": [{"type": "...", "message": "..."}],
            "declaredVolumes": int,
            "expandedVolumes": int
        }
    """
    issues = []
    
    # 1. 检查框架中声明的卷数
    state = detect_framework_state(framework)
    declared_volumes = state["totalVolumes"]
    
    # 2. 检查细节卷是否超出框架范围
    for vol_num in volumes_detail.keys():
        if vol_num > declared_volumes:
            issues.append({
                "type": "volume_out_of_range",
                "volume": vol_num,
                "message": f"第{vol_num}卷不在框架声明范围内（框架总卷数：{declared_volumes}）"
            })
    
    # 3. 检查章节连续性
    sorted_vols = sorted(volumes_detail.items())
    for i in range(len(sorted_vols) - 1):
        current_vol_num, current_vol = sorted_vols[i]
        next_vol_num, next_vol = sorted_vols[i + 1]
        
        current_end = current_vol.get("chapters_end", 0)
        next_start = next_vol.get("chapters_start", 0)
        
        if current_end + 1 != next_start:
            issues.append({
                "type": "chapter_gap",
                "volumes": [current_vol_num, next_vol_num],
                "message": f"第{current_vol_num}卷结束在第{current_end}章，"
                          f"但第{next_vol_num}卷从第{next_start}章开始（缺失 {next_start - current_end - 1} 章）"
            })
    
    # 4. 检查每一卷的章节范围是否合理
    for vol_num, vol_data in volumes_detail.items():
        chapters_count = vol_data.get("chapters_end", 0) - vol_data.get("chapters_start", 0) + 1
        if chapters_count < 10:
            issues.append({
                "type": "volume_too_short",
                "volume": vol_num,
                "message": f"第{vol_num}卷只有{chapters_count}章，建议至少10章"
            })
        elif chapters_count > MAX_CHAPTERS_PER_VOLUME:
            issues.append({
                "type": "volume_too_long",
                "volume": vol_num,
                "message": f"第{vol_num}卷有{chapters_count}章，超过每卷{MAX_CHAPTERS_PER_VOLUME}章上限，建议拆分为多卷"
            })
    
    result = {
        "valid": len(issues) == 0,
        "issues": issues,
        "declaredVolumes": declared_volumes,
        "expandedVolumes": len(volumes_detail)
    }
    
    if result["valid"]:
        logger.info(f"✅ 完整性校验通过：{declared_volumes}卷框架，{len(volumes_detail)}卷已扩展")
    else:
        logger.warning(f"⚠️ 完整性校验发现 {len(issues)} 个问题")
        for issue in issues:
            logger.warning(f"   - {issue['message']}")
    
    return result


def _remove_anchor_marks(content: str) -> str:
    """
    移除内容中的锚点标记
    
    Args:
        content: 包含锚点的内容
    
    Returns:
        移除锚点后的内容
    """
    lines = content.split('\n')
    result = []
    
    for line in lines:
        # 跳过锚点标记行
        if re.match(r'<!-- VOLUME_\d+_ANCHOR_(START|END) -->', line):
            continue
        result.append(line)
    
    return '\n'.join(result)


def extract_volume_detail(outline_content: str, volume_number: int) -> Optional[str]:
    """
    从拼接后的大纲中提取指定卷的细纲
    
    Args:
        outline_content: 完整大纲内容
        volume_number: 卷编号
    
    Returns:
        该卷的细纲内容，如果未找到返回None
    """
    # 匹配该卷的<details>区块
    pattern = re.compile(
        rf'<details[^>]*>\s*<summary>📖 第{volume_number}卷详细章节.*?</summary>\s*(.*?)\s*</details>',
        re.DOTALL
    )
    
    match = pattern.search(outline_content)
    if match:
        return match.group(1).strip()
    
    return None


# =====================================
# 🌟 新架构：卷级独立存储结构
# =====================================

def create_volume_entry(
    volume_num: int,
    title: str,
    summary: str,
    chapters_range: List[int] = None,
    chapter_count: int | None = None,
    detail: str = None,
    expanded_at: str = None
) -> Dict[str, any]:
    """
    创建单卷存储条目
    
    Args:
        volume_num: 卷号
        title: 卷标题
        summary: 框架阶段的卷概要
        chapters_range: 章节范围 [start, end]
        chapter_count: 章节数量（与全局起止编号解耦）
        detail: 细纲内容（展开后填入）
        expanded_at: 展开时间
    
    Returns:
        卷条目字典
    """
    return {
        "type": "detail" if detail else "framework",  # framework=未展开, detail=已展开
        "title": title,
        "summary": summary,                             # 保留原始概要（可回退）
        "detail": detail,                               # 细纲内容
        "chapters_range": chapters_range or [0, 0],
        "chapter_count": chapter_count,
        "expanded_at": expanded_at
    }


def parse_epic_volumes_json(json_str: str) -> Dict[str, any]:
    """
    解析新结构的 epic_volumes_detail JSON
    
    🌟 增强版结构格式：
    {
        "total_volumes": 5,
        "framework_generated_at": "2025-12-13T17:00:00",
        "framework_header": "一、整体叙事节奏...\n二、境界体系...",  // 🌟 头部通用信息
        "framework_footer": "四、关键伏笔...\n五、核心人物...",  // 🌟 尾部通用信息
        "volumes": {
            "1": {
                "type": "framework",
                "title": "初入南麓",
                "summary": "核心：林澈进入南麓艺术学院...",
                "detail": null,
                "chapters_range": [1, 80],
                "expanded_at": null
            }
        }
    }
    
    Returns:
        解析后的字典
    """
    if not json_str:
        return {
            "total_volumes": 0,
            "framework_generated_at": None,
            "framework_header": "",
            "framework_footer": "",
            "volumes": {}
        }
    
    try:
        data = json.loads(json_str)
        
        # 🔄 兼容旧结构：如果没有 "volumes" 键，说明是旧格式
        if "volumes" not in data:
            return _migrate_old_format(data)
        
        # 确保新字段存在
        if "framework_header" not in data:
            data["framework_header"] = ""
        if "framework_footer" not in data:
            data["framework_footer"] = ""
        if isinstance(data.get("volumes"), dict):
            for vol_data in data["volumes"].values():
                if not isinstance(vol_data, dict):
                    continue
                if "chapter_count" not in vol_data:
                    vol_data["chapter_count"] = _estimate_volume_chapter_count(vol_data)
        
        return data
    except json.JSONDecodeError as e:
        logger.error(f"❌ 解析 epic_volumes_detail JSON 失败: {e}")
        return {
            "total_volumes": 0,
            "framework_generated_at": None,
            "framework_header": "",
            "framework_footer": "",
            "volumes": {}
        }


def _migrate_old_format(old_data: Dict) -> Dict[str, any]:
    """
    将旧格式迁移到新结构
    
    旧格式：
    {
        "1": {"chapters_start": 1, "chapters_end": 80, "outline": "...", "generated_at": "..."},
        "2": {"chapters_start": 81, "chapters_end": 152, "outline": "..."}
    }
    """
    logger.info("🔄 检测到旧格式，正在迁移到新结构...")
    
    volumes = {}
    max_vol = 0
    
    for vol_key, vol_data in old_data.items():
        try:
            vol_num = int(vol_key)
            max_vol = max(max_vol, vol_num)
            
            volumes[vol_key] = {
                "type": "detail",  # 旧格式都是已展开的细纲
                "title": f"第{vol_num}卷",
                "summary": "",  # 旧格式没有保留概要
                "detail": vol_data.get("outline", ""),
                "chapters_range": [
                    vol_data.get("chapters_start", 0),
                    vol_data.get("chapters_end", 0)
                ],
                "chapter_count": max(
                    0,
                    _safe_int(vol_data.get("chapters_end"), 0) - _safe_int(vol_data.get("chapters_start"), 0) + 1,
                ),
                "expanded_at": vol_data.get("generated_at")
            }
        except (ValueError, TypeError):
            continue
    
    return {
        "total_volumes": max_vol,
        "framework_generated_at": None,
        "volumes": volumes
    }


def build_epic_volumes_json(data: Dict[str, any]) -> str:
    """
    构建新结构的 epic_volumes_detail JSON字符串
    
    Args:
        data: {
            "total_volumes": 10,
            "framework_generated_at": "...",
            "volumes": {...}
        }
    
    Returns:
        JSON字符串
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def _clean_outline_section_lines(lines: List[str]) -> str:
    cleaned_lines = list(lines)
    while cleaned_lines and not cleaned_lines[0].strip():
        cleaned_lines.pop(0)
    while cleaned_lines and not cleaned_lines[-1].strip():
        cleaned_lines.pop()
    while cleaned_lines and cleaned_lines[0].strip() == "---":
        cleaned_lines.pop(0)
        while cleaned_lines and not cleaned_lines[0].strip():
            cleaned_lines.pop(0)
    while cleaned_lines and cleaned_lines[-1].strip() == "---":
        cleaned_lines.pop()
        while cleaned_lines and not cleaned_lines[-1].strip():
            cleaned_lines.pop()
    return "\n".join(cleaned_lines).strip()


def _match_merged_volume_heading(line: str) -> Optional[re.Match[str]]:
    return MERGED_VOLUME_HEADING_PATTERN.match(line) or MERGED_VOLUME_HEADING_FALLBACK_PATTERN.match(line)


def _extract_merged_outline_title(match: re.Match[str], volume_num: int) -> str:
    title = str(match.groupdict().get("title") or "").strip()
    title = title.strip("《》").strip()
    return title or f"第{volume_num}卷"


def _parse_merged_outline_to_volumes(framework_content: str, total_volumes: int) -> Optional[Dict[str, any]]:
    lines = framework_content.split('\n')
    volume_positions: List[Tuple[int, str, int]] = []
    overview_start_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        if overview_start_idx is None and line.strip() == "## 📚 分卷概要":
            overview_start_idx = idx
        heading_match = _match_merged_volume_heading(line)
        if not heading_match:
            continue
        volume_num = _safe_int(heading_match.group("number"), 0)
        if volume_num <= 0:
            continue
        volume_positions.append(
            (volume_num, _extract_merged_outline_title(heading_match, volume_num), idx)
        )

    if not volume_positions:
        return None

    stats_line_idx: Optional[int] = None
    for idx in range(len(lines) - 1, -1, -1):
        if MERGED_OUTLINE_STATS_PATTERN.match(lines[idx].strip()):
            stats_line_idx = idx
            break

    header_end_idx = overview_start_idx if overview_start_idx is not None else volume_positions[0][2]
    framework_header = _clean_outline_section_lines(lines[:header_end_idx])
    effective_end_idx = stats_line_idx if stats_line_idx is not None else len(lines)
    footer_lines: List[str] = []
    volumes: Dict[str, any] = {}

    for idx, (volume_num, title, line_idx) in enumerate(volume_positions):
        next_line_idx = (
            volume_positions[idx + 1][2]
            if idx + 1 < len(volume_positions)
            else effective_end_idx
        )
        block_lines = lines[line_idx + 1:next_line_idx]

        if idx == len(volume_positions) - 1:
            divider_idx = next(
                (block_idx for block_idx, block_line in enumerate(block_lines) if block_line.strip() == "---"),
                None,
            )
            if divider_idx is not None:
                footer_lines = block_lines[divider_idx + 1:]
                block_lines = block_lines[:divider_idx]

        detail_start_idx = next(
            (block_idx for block_idx, block_line in enumerate(block_lines) if block_line.strip().startswith("<details")),
            None,
        )
        detail_content = None
        summary = ""
        chapter_range = [0, 0]
        chapter_count = None

        if detail_start_idx is not None:
            detail_end_idx = next(
                (
                    block_idx
                    for block_idx in range(detail_start_idx, len(block_lines))
                    if block_lines[block_idx].strip() == "</details>"
                ),
                None,
            )
            summary = _clean_outline_section_lines(block_lines[:detail_start_idx])
            if detail_end_idx is not None:
                detail_summary_idx = next(
                    (
                        block_idx
                        for block_idx in range(detail_start_idx, detail_end_idx + 1)
                        if MERGED_DETAIL_SUMMARY_PATTERN.match(block_lines[block_idx].strip())
                    ),
                    None,
                )
                if detail_summary_idx is not None:
                    detail_summary_match = MERGED_DETAIL_SUMMARY_PATTERN.match(
                        block_lines[detail_summary_idx].strip()
                    )
                    chapter_range = [
                        _safe_int(detail_summary_match.group("start"), 0),
                        _safe_int(detail_summary_match.group("end"), 0),
                    ]
                    if chapter_range[0] > 0 and chapter_range[1] >= chapter_range[0]:
                        chapter_count = chapter_range[1] - chapter_range[0] + 1
                    detail_content = _clean_outline_section_lines(
                        block_lines[detail_summary_idx + 1:detail_end_idx]
                    )
                else:
                    detail_content = _clean_outline_section_lines(
                        block_lines[detail_start_idx + 1:detail_end_idx]
                    )
            else:
                detail_content = _clean_outline_section_lines(block_lines[detail_start_idx + 1:])
        else:
            summary = _clean_outline_section_lines(block_lines)

        volumes[str(volume_num)] = create_volume_entry(
            volume_num=volume_num,
            title=title,
            summary=summary if summary else f"（第{volume_num}卷概要待填充）",
            chapters_range=chapter_range,
            chapter_count=chapter_count,
            detail=detail_content,
            expanded_at=None,
        )

    framework_footer = _clean_outline_section_lines(footer_lines)
    return {
        "total_volumes": total_volumes or len(volumes),
        "framework_generated_at": datetime.now().isoformat(),
        "framework_header": framework_header,
        "framework_footer": framework_footer,
        "volumes": volumes,
    }


def parse_framework_to_volumes(framework_content: str, total_volumes: int) -> Dict[str, any]:
    """
    🌟 解析AI生成的框架内容，提取头部、尾部和每卷内容
    
    框架结构分三部分：
    1. 头部(header): 整体叙事节奏、境界体系等通用信息
    2. 中间(volumes): 每卷的具体描述
    3. 尾部(footer): 伏笔布局、人物周期等通用信息
    
    Args:
        framework_content: AI生成的框架内容
        total_volumes: 总卷数
    
    Returns:
        新结构的字典，包含 framework_header, framework_footer, volumes
    """
    merged_outline_result = _parse_merged_outline_to_volumes(framework_content, total_volumes)
    if merged_outline_result and merged_outline_result.get("volumes"):
        logger.info(
            "✅ 识别到拼接后的分卷概要格式，已恢复 %s 卷数据",
            len(merged_outline_result.get("volumes") or {}),
        )
        return merged_outline_result

    volumes = {}
    framework_header = ""
    framework_footer = ""
    lines = framework_content.split('\n')
    
    # 📝 调试日志
    logger.info(f"🔍 解析框架内容，长度: {len(framework_content)} 字符")
    
    # 🌟 卷标题匹配模式
    volume_title_patterns = [
        # 【第1卷】《标题》 或 【第1卷】标题
        re.compile(r'^\s*(?:#{1,6}\s*)?【第\s*(\d+)\s*卷】\s*[《》]?([^《》\n]*)', re.MULTILINE),
        # ## 第1卷：标题 或 ## 第1卷:标题
        re.compile(r'^(#+)\s*第\s*(\d+)\s*卷\s*[：:](.*)', re.MULTILINE),
        # ## 第1卷 标题
        re.compile(r'^(#+)\s*第\s*(\d+)\s*卷\s+(.+)', re.MULTILINE),
        # **第1卷：标题**
        re.compile(r'^\*\*第\s*(\d+)\s*卷\s*[：:](.*)\*\*', re.MULTILINE),
        # 第1卷：标题 或 第1卷:标题
        re.compile(r'^第\s*(\d+)\s*卷\s*[：:](.*)', re.MULTILINE),
        # 第1卷 标题
        re.compile(r'^第\s*(\d+)\s*卷\s+(.+)', re.MULTILINE),
    ]
    
    # 🌟 尾部标题匹配模式（伏笔、人物等通用信息）
    footer_title_patterns = [
        re.compile(r'^#+\s*[四五六七八九十][\u3001\.\uff0c,]?\s*(关键伏笔|伏笔布局|核心人物|人物生命周期|人物关系|\w+周期)', re.MULTILINE),
        re.compile(r'^[四五六七八九十][\u3001\.\uff0c,]?\s*(关键伏笔|伏笔布局|核心人物|人物生命周期)', re.MULTILINE),
    ]
    
    # 中文数字映射
    cn_num_map = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20
    }
    cn_volume_patterns = [
        re.compile(r'^\s*(?:#{1,6}\s*)?【第([\u4e00-\u9fa5]+)卷】\s*[《》]?([^《》\n]*)', re.MULTILINE),
        re.compile(r'^(#+)?\s*第([\u4e00-\u9fa5]+)卷\s*[：:](.*)', re.MULTILINE),
        re.compile(r'^(#+)?\s*第([\u4e00-\u9fa5]+)卷\s+(.+)', re.MULTILINE),
    ]
    
    # 找到所有卷的位置
    volume_positions = []  # [(vol_num, title, line_index), ...]
    footer_start_idx = None  # 尾部开始位置
    
    for i, line in enumerate(lines):
        vol_num = None
        title = ""
        matched = False
        
        # 检查是否是尾部标题
        for pattern in footer_title_patterns:
            if pattern.match(line):
                if footer_start_idx is None:
                    footer_start_idx = i
                    logger.info(f"📌 检测到尾部开始位置: 第{i}行")
                break
        
        # 如果已经进入尾部，不再匹配卷标题
        if footer_start_idx is not None:
            continue
        
        # 尝试匹配阿拉伯数字格式
        for pattern in volume_title_patterns:
            match = pattern.match(line)
            if match:
                groups = match.groups()
                for g in groups:
                    if g and g.strip().isdigit():
                        vol_num = int(g.strip())
                    elif g and not g.startswith('#') and len(g.strip()) > 0:
                        clean_title = g.strip().strip('《》|').strip()
                        if clean_title and not clean_title.isdigit():
                            title = clean_title
                
                if vol_num:
                    volume_positions.append((vol_num, title, i))
                    matched = True
                break
        
        # 尝试匹配中文数字格式
        if not matched:
            for pattern in cn_volume_patterns:
                match = pattern.match(line)
                if match:
                    groups = match.groups()
                    for g in groups:
                        if g and g in cn_num_map:
                            vol_num = cn_num_map[g]
                        elif g and not g.startswith('#') and len(g.strip()) > 0:
                            title = g.strip().strip('《》').strip()
                    
                    if vol_num:
                        volume_positions.append((vol_num, title, i))
                    break
    
    logger.info(f"📊 匹配到 {len(volume_positions)} 个卷标题")
    
    # 🌟 提取头部内容（第一个卷之前的内容）
    if volume_positions:
        first_vol_line = volume_positions[0][2]
        if first_vol_line > 0:
            header_lines = lines[:first_vol_line]
            framework_header = '\n'.join(header_lines).strip()
            logger.info(f"📦 提取头部内容: {len(framework_header)} 字符")
    
    # 🌟 提取尾部内容（最后一个卷之后的通用信息）
    if footer_start_idx is not None:
        footer_lines = lines[footer_start_idx:]
        framework_footer = '\n'.join(footer_lines).strip()
        logger.info(f"📦 提取尾部内容: {len(framework_footer)} 字符")
    
    # 🌟 提取每卷的概要内容
    for idx, (vol_num, title, line_idx) in enumerate(volume_positions):
        # 确定该卷内容的结束位置
        if idx + 1 < len(volume_positions):
            end_idx = volume_positions[idx + 1][2]
        elif footer_start_idx is not None:
            end_idx = footer_start_idx
        else:
            end_idx = len(lines)
        
        # 提取概要内容（卷标题下一行到下一卷之前）
        summary_lines = lines[line_idx + 1:end_idx]
        summary = '\n'.join(summary_lines).strip()
        
        # 清理概要（去掉尾部的分隔符等）
        summary = re.sub(r'\n---\s*$', '', summary)
        summary = re.sub(r'^---\s*\n', '', summary)
        
        volumes[str(vol_num)] = create_volume_entry(
            volume_num=vol_num,
            title=title or f"第{vol_num}卷",
            summary=summary if summary else f"（第{vol_num}卷概要待填充）",
            chapters_range=[0, 0],
            detail=None,
            expanded_at=None
        )
    
    # 🌟 回退机制：如果解析失败，保留原始框架
    if not volumes and total_volumes > 0:
        logger.warning(f"⚠️ 未能解析卷结构，使用回退机制")
        
        # 将完整内容放入头部
        framework_header = framework_content.strip()
        
        # 创建空卷条目
        for i in range(1, total_volumes + 1):
            volumes[str(i)] = create_volume_entry(
                volume_num=i,
                title=f"第{i}卷",
                summary=f"（第{i}卷待填充）",
                chapters_range=[0, 0],
                detail=None,
                expanded_at=None
            )
        
        logger.info("📦 回退机制：将完整框架内容放入header")
    
    result = {
        "total_volumes": total_volumes or len(volumes),
        "framework_generated_at": datetime.now().isoformat(),
        "framework_header": framework_header,
        "framework_footer": framework_footer,
        "volumes": volumes
    }
    
    logger.info(f"✅ 框架解析完成：共 {len(volumes)} 卷，头部 {len(framework_header)} 字符，尾部 {len(framework_footer)} 字符")
    return result


def update_volume_detail(
    volumes_data: Dict[str, any],
    volume_num: int,
    detail_content: str,
    chapters_range: List[int]
) -> Dict[str, any]:
    """
    🌟 更新指定卷的细纲内容
    
    Args:
        volumes_data: 当前的volumes数据
        volume_num: 要更新的卷号
        detail_content: 细纲内容
        chapters_range: 章节范围 [start, end]
    
    Returns:
        更新后的volumes数据
    """
    vol_key = str(volume_num)
    chapter_count = max(0, _safe_int(chapters_range[1], 0) - _safe_int(chapters_range[0], 0) + 1)
    
    if vol_key in volumes_data["volumes"]:
        # 更新现有卷
        volumes_data["volumes"][vol_key]["type"] = "detail"
        volumes_data["volumes"][vol_key]["detail"] = detail_content
        volumes_data["volumes"][vol_key]["chapters_range"] = chapters_range
        volumes_data["volumes"][vol_key]["chapter_count"] = chapter_count
        volumes_data["volumes"][vol_key]["expanded_at"] = datetime.now().isoformat()
        logger.info(f"✅ 已更新第{volume_num}卷细纲（第{chapters_range[0]}-{chapters_range[1]}章）")
    else:
        # 新增卷（异常情况）
        volumes_data["volumes"][vol_key] = create_volume_entry(
            volume_num=volume_num,
            title=f"第{volume_num}卷",
            summary="",
            chapters_range=chapters_range,
            chapter_count=chapter_count,
            detail=detail_content,
            expanded_at=datetime.now().isoformat()
        )
        logger.warning(f"⚠️ 第{volume_num}卷不存在，已新增")
    
    return normalize_volume_detail_layout(volumes_data, rewrite_detail_content=True)


def get_volume_state(volumes_data: Dict[str, any]) -> Dict[str, any]:
    """
    🌟 获取卷状态概览
    
    Returns:
        {
            "hasFramework": bool,
            "totalVolumes": int,
            "expandedVolumes": [1, 3, 5],
            "frameworkGeneratedAt": str or None
        }
    """
    normalized_data = normalize_volume_detail_layout(volumes_data)
    if not normalized_data or not normalized_data.get("volumes"):
        return {
            "hasFramework": False,
            "totalVolumes": 0,
            "expandedVolumes": [],
            "frameworkGeneratedAt": None
        }
    
    expanded = []
    for vol_key, vol_data in normalized_data["volumes"].items():
        if vol_data.get("type") == "detail":
            try:
                expanded.append(int(vol_key))
            except ValueError:
                pass
    
    return {
        "hasFramework": len(normalized_data["volumes"]) > 0,
        "totalVolumes": normalized_data.get("total_volumes", len(normalized_data["volumes"])),
        "expandedVolumes": sorted(expanded),
        "frameworkGeneratedAt": normalized_data.get("framework_generated_at")
    }


def merge_volumes_to_outline(volumes_data: Dict[str, any]) -> str:
    """
    🌟 新架构拼接函数：拼接头部 + 各卷内容 + 尾部
    
    拼接顺序：
    1. framework_header（整体叙事节奏、境界体系等）
    2. 各卷内容（未展开显示summary，已展开显示detail）
    3. framework_footer（伏笔布局、人物周期等）
    
    Args:
        volumes_data: 完整的volumes数据
    
    Returns:
        拼接后的大纲内容
    """
    normalized_data = normalize_volume_detail_layout(volumes_data, rewrite_detail_content=True)
    if not normalized_data or not normalized_data.get("volumes"):
        return ""
    
    result = []
    expanded_list = []
    
    # 🌟 1. 添加头部内容（整体叙事节奏、境界体系等）
    framework_header = normalized_data.get("framework_header", "")
    if framework_header:
        result.append(framework_header)
        result.append('')
        result.append('---')
        result.append('')
    
    # 🌟 2. 添加分卷内容标题
    result.append('## 📚 分卷概要')
    result.append('')
    
    # 按卷号排序
    sorted_volumes = sorted(
        normalized_data["volumes"].items(),
        key=lambda x: int(x[0])
    )
    
    for vol_key, vol_data in sorted_volumes:
        vol_num = int(vol_key)
        title = vol_data.get("title", f"第{vol_num}卷")
        vol_type = vol_data.get("type", "framework")
        
        # 添加卷标题
        result.append(f"### 【第{vol_num}卷】《{title}》")
        result.append("")
        
        if vol_type == "detail" and vol_data.get("detail"):
            # 已展开：显示细纲（可折叠）
            chapters_range = vol_data.get("chapters_range", [0, 0])
            result.append(f'<details>')
            result.append(f'<summary>📖 第{vol_num}卷详细章节（第{chapters_range[0]}-{chapters_range[1]}章，点击收起/展开）</summary>')
            result.append('')
            result.append(vol_data["detail"])
            result.append('')
            result.append('</details>')
            expanded_list.append(vol_num)
        else:
            # 未展开：显示概要
            summary = vol_data.get("summary", "（无概要）")
            result.append(summary)
        
        result.append('')
    
    # 🌟 3. 添加尾部内容（伏笔布局、人物周期等）
    framework_footer = normalized_data.get("framework_footer", "")
    if framework_footer:
        result.append('---')
        result.append('')
        result.append(framework_footer)
        result.append('')
    
    # 添加拼接统计
    result.append('---')
    result.append(f'_✅ 共{normalized_data.get("total_volumes", len(sorted_volumes))}卷 | 已展开：{expanded_list if expanded_list else "无"} | 拼接时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}_')
    
    logger.info(f"✅ 大纲拼接完成：{len(expanded_list)}/{len(sorted_volumes)} 卷已展开")
    return '\n'.join(result)


# =====================================
# 📦 旧版兼容函数（保留以支持过渡）
# =====================================

def parse_volumes_detail_json(json_str: str) -> Dict[int, Dict[str, any]]:
    """
    [旧版兼容] 解析存储在数据库中的 epic_volumes_detail JSON字符串
    
    Args:
        json_str: JSON字符串，格式如：
        {
            "1": {"chapters_start": 1, "chapters_end": 80, "outline": "...", "generated_at": "..."},
            "2": {"chapters_start": 81, "chapters_end": 152, "outline": "..."}
        }
    
    Returns:
        解析后的字典，键为整数
    """
    if not json_str:
        return {}
    
    try:
        raw_dict = json.loads(json_str)
        
        # 检测新结构
        if "volumes" in raw_dict:
            raw_dict = normalize_volume_detail_layout(raw_dict, rewrite_detail_content=True)
            # 新结构：转换为旧格式返回
            result = {}
            for vol_key, vol_data in raw_dict["volumes"].items():
                try:
                    vol_num = int(vol_key)
                    if vol_data.get("type") == "detail" and vol_data.get("detail"):
                        result[vol_num] = {
                            "chapters_start": vol_data.get("chapters_range", [0, 0])[0],
                            "chapters_end": vol_data.get("chapters_range", [0, 0])[1],
                            "outline": vol_data.get("detail", ""),
                            "generated_at": vol_data.get("expanded_at")
                        }
                except (ValueError, TypeError, IndexError):
                    pass
            return result
        
        # 旧结构：将字符串键转换为整数键
        return {int(k): v for k, v in raw_dict.items()}
    except json.JSONDecodeError as e:
        logger.error(f"❌ 解析 epic_volumes_detail JSON 失败: {e}")
        return {}


def build_volumes_detail_json(volumes_detail: Dict[int, Dict[str, any]]) -> str:
    """
    [旧版兼容] 构建用于存储到数据库的 epic_volumes_detail JSON字符串
    
    Args:
        volumes_detail: {
            1: {"chapters_start": 1, "chapters_end": 80, "outline": "...", "generated_at": "..."},
            2: {"chapters_start": 81, "chapters_end": 152, "outline": "..."}
        }
    
    Returns:
        JSON字符串
    """
    # 将整数键转换为字符串键（JSON标准）
    json_dict = {str(k): v for k, v in volumes_detail.items()}
    return json.dumps(json_dict, ensure_ascii=False, indent=2)
