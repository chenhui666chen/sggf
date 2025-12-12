"""
史诗框架与卷细纲智能拼接模块

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


def add_volume_anchors(framework: str, total_volumes: int) -> str:
    """
    为史诗框架添加锚点标记
    
    Args:
        framework: 原始框架内容
        total_volumes: 总卷数
    
    Returns:
        添加了锚点的框架内容
    """
    lines = framework.split('\n')
    result = []
    
    # 匹配卷标题的模式
    volume_pattern = re.compile(r'^(#+)\s*第([0-9]+)卷[：:]')
    
    for line in lines:
        match = volume_pattern.match(line)
        if match:
            vol_num = int(match.group(2))
            # 在卷标题前插入起始锚点
            result.append(f'<!-- VOLUME_{vol_num}_ANCHOR_START -->')
            result.append(line)
            result.append(f'<!-- VOLUME_{vol_num}_ANCHOR_END -->')
        else:
            result.append(line)
    
    logger.info(f"✅ 已为 {total_volumes} 卷框架添加锚点标记")
    return '\n'.join(result)


def merge_framework_with_volumes(
    framework: str,
    volumes_detail: Dict[int, str]
) -> str:
    """
    智能拼接框架与卷细纲
    
    Args:
        framework: 史诗框架内容（包含锚点）
        volumes_detail: 已扩展的卷细纲 {1: "第1卷细纲", 3: "第3卷细纲"}
    
    Returns:
        拼接后的完整大纲（已移除锚点标记和已扩展卷的概要）
    """
    if not framework:
        return ""
    
    if not volumes_detail:
        # 如果没有扩展的卷，返回框架（移除锚点）
        return _remove_anchor_marks(framework)
    
    lines = framework.split('\n')
    result = []
    
    i = 0
    in_expanded_volume = False  # 标记是否在已扩展卷的概要区域内
    current_volume_num = None
    
    while i < len(lines):
        line = lines[i]
        
        # 检测卷锚点起始标记
        anchor_start_match = re.match(r'<!-- VOLUME_(\d+)_ANCHOR_START -->', line)
        if anchor_start_match:
            current_volume_num = int(anchor_start_match.group(1))
            in_expanded_volume = current_volume_num in volumes_detail
            i += 1
            continue  # 跳过锚点标记，不添加到结果
        
        # 检测卷锚点结束标记
        anchor_end_match = re.match(r'<!-- VOLUME_(\d+)_ANCHOR_END -->', line)
        if anchor_end_match:
            vol_num = int(anchor_end_match.group(1))
            
            # 如果该卷有细纲，插入可折叠区块
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
            continue  # 跳过锚点标记，不添加到结果
        
        # 如果在已扩展卷的概要区域内，跳过内容（直到遇到下一个锚点结束或下一卷开始）
        if in_expanded_volume:
            # 检查是否已到达概要结束（下一卷开始或空行后的分隔符）
            next_volume_match = re.match(r'^(#+)\s*第([0-9]+)卷[：:]', line) if i + 1 < len(lines) else None
            if next_volume_match:
                # 即将进入下一卷，当前行（卷标题）保留，但概要部分已跳过
                in_expanded_volume = False
            else:
                # 仍在概要区域，跳过
                i += 1
                continue
        
        # 正常添加行（非锚点、非已扩展卷概要）
        result.append(line)
        i += 1
    
    # 添加拼接统计信息
    result.append('')
    result.append('---')
    result.append(f'_✅ 已生成完整框架 | 已扩展卷：{sorted(volumes_detail.keys())} | 拼接时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}_')
    
    logger.info(f"✅ 框架拼接完成：{len(volumes_detail)} 个卷的细纲已插入")
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
    
    # 检测是否有锚点标记（说明有框架）
    has_anchors = 'VOLUME_' in outline_content and 'ANCHOR_' in outline_content
    
    # 提取总卷数
    volume_pattern = re.compile(r'<!-- VOLUME_(\d+)_ANCHOR_START -->')
    volume_numbers = set()
    for match in volume_pattern.finditer(outline_content):
        volume_numbers.add(int(match.group(1)))
    
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
    
    return {
        "hasFramework": has_anchors or total_volumes > 0,
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
        elif chapters_count > 200:
            issues.append({
                "type": "volume_too_long",
                "volume": vol_num,
                "message": f"第{vol_num}卷有{chapters_count}章，可能过长"
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


def parse_volumes_detail_json(json_str: str) -> Dict[int, Dict[str, any]]:
    """
    解析存储在数据库中的 epic_volumes_detail JSON字符串
    
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
        # 将字符串键转换为整数键
        return {int(k): v for k, v in raw_dict.items()}
    except json.JSONDecodeError as e:
        logger.error(f"❌ 解析 epic_volumes_detail JSON 失败: {e}")
        return {}


def build_volumes_detail_json(volumes_detail: Dict[int, Dict[str, any]]) -> str:
    """
    构建用于存储到数据库的 epic_volumes_detail JSON字符串
    
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
