"""生成后人物行为一致性校验（P3）

职责（可解释、不阻断）：
- 从角色卡说话风格中提取"回避/禁用"表达，检查是否出现在该角色对白中；
- 检查同章多角色对白语气特征是否高度同质（句长/感叹/疑问比例）；
- 每个问题定位到角色、章节、证据片段和严重等级，供质量评分与修订提示使用。

首期为纯文本规则（离线确定性，不依赖 LLM）；
历史项目角色卡缺少说话风格字段时返回空报告，不阻断章节生成。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger("uvicorn.error")

# 角色对白归属：角色名 + 可选修饰 + 言说动词 + 引号内容
# 名字用非贪婪并让动词长词优先，避免“林昭答道”被切成名字“林昭答”
_DIALOGUE_PATTERN = re.compile(
    r"(?P<name>[\u4e00-\u9fa5]{1,6}?)"
    r"(?:冷冷地|淡淡地|沉声|低声|轻声|朗声|急声)?"
    r"(?:开口道|说道|问道|答道|笑道|喝道|叹道|喊道|道|说)"
    r"(?:[：:]?\s*)"
    r'["\u201c「『](?P<content>[^"\u201d」』]+)["\u201d」』]'
)

# 说话风格中的回避/禁用子字段
_FORBIDDEN_PATTERN = re.compile(r"(?:回避|禁用|避免)\s*[：:]\s*(?P<items>[^；;\n]+)")

_FORBIDDEN_ITEM_SPLIT = re.compile(r"[、，,]")


@dataclass
class BehaviorConsistencyIssue:
    """行为一致性问题（可定位到角色、章节、证据片段）。"""

    character_name: str
    chapter_number: Optional[int]
    check_type: str  # forbidden_expression / dialogue_homogenization
    severity: str  # high / medium / low
    reason: str
    evidence_text: str


def extract_character_dialogues(chapter_text: Any, name: str) -> List[str]:
    """按“角色名+言说动词+引号”模式提取某角色在章节中的对白。"""
    text = str(chapter_text or "")
    target = str(name or "").strip()
    if not text or not target:
        return []

    dialogues: List[str] = []
    for match in _DIALOGUE_PATTERN.finditer(text):
        if match.group("name") == target:
            content = match.group("content").strip()
            if content:
                dialogues.append(content)
    return dialogues


def _extract_forbidden_expressions(speech_style: Any) -> List[str]:
    """从说话风格文本中提取回避/禁用表达列表。

    例：'回避：感叹号、口头禅"其实"' -> ['感叹号', '其实']
    项内含引号时取引号内内容作为检测标记（如 口头禅"其实" -> 其实）。
    """
    style_text = str(speech_style or "").strip()
    if not style_text:
        return []

    items: List[str] = []
    for match in _FORBIDDEN_PATTERN.finditer(style_text):
        raw_items = match.group("items")
        for raw in _FORBIDDEN_ITEM_SPLIT.split(raw_items):
            cleaned = raw.strip()
            if not cleaned:
                continue
            # 先在原始片段上取引号内内容（strip 会破坏引号配对）
            quoted = re.findall(r'["\u201c“]([^"\u201d”]+)["\u201d”]', cleaned)
            item = quoted[-1].strip() if quoted else cleaned.strip('"“”').strip()
            if item:
                items.append(item)
    return items


def _forbidden_marker(expression: str) -> str:
    """禁用项到正文中检测标记的映射（如“感叹号”→“！”）。"""
    markers = {
        "感叹号": "！",
        "叹号": "！",
        "问号": "？",
        "省略号": "……",
    }
    return markers.get(expression, expression)


def _dialogue_style_features(dialogues: List[str]) -> Optional[tuple[float, float, float]]:
    """计算对白语气特征：(平均句长, 感叹比例, 疑问比例)。"""
    if not dialogues:
        return None
    lengths = [len(line) for line in dialogues]
    avg_len = sum(lengths) / len(lengths)
    excl = sum(1 for line in dialogues if "！" in line) / len(dialogues)
    quest = sum(1 for line in dialogues if "？" in line) / len(dialogues)
    return (avg_len, excl, quest)


def check_character_behavior_consistency(
    chapter_text: Any,
    characters_text: Any,
    *,
    chapter_number: Optional[int] = None,
) -> List[BehaviorConsistencyIssue]:
    """章节生成后的人物行为一致性检查。

    只产出报告（角色/章节/证据/严重等级），不阻断生成；
    角色卡缺少说话风格字段的历史项目返回空报告。
    """
    from app.services.character_parser import CharacterTextParser

    text = str(chapter_text or "")
    content = str(characters_text or "").strip()
    if not text or not content:
        return []

    try:
        parsed_characters = CharacterTextParser().parse_all_characters(content) or []
    except Exception as exc:  # 历史格式解析失败：不阻断
        logger.warning("行为一致性校验解析角色卡失败，跳过: %s", exc)
        return []

    issues: List[BehaviorConsistencyIssue] = []
    name_to_dialogues: dict[str, List[str]] = {}

    for character in parsed_characters:
        name = str(getattr(character, "name", "") or "").strip()
        if not name:
            continue
        dialogues = extract_character_dialogues(text, name)
        if not dialogues:
            continue
        name_to_dialogues[name] = dialogues

        # 检查1：禁用/回避表达出现在该角色对白（high）
        forbidden_items = _extract_forbidden_expressions(
            getattr(character, "speech_style", None)
        )
        for expression in forbidden_items:
            marker = _forbidden_marker(expression)
            hit_dialogue = next(
                (line for line in dialogues if marker in line), None
            )
            if hit_dialogue is not None:
                issues.append(
                    BehaviorConsistencyIssue(
                        character_name=name,
                        chapter_number=chapter_number,
                        check_type="forbidden_expression",
                        severity="high",
                        reason=f'对白出现说话风格中回避的表达“{expression}”',
                        evidence_text=f"{name}：“{hit_dialogue}”",
                    )
                )

    # 检查2：同章多角色对白语气特征高度同质（medium）
    styled = [
        (name, features)
        for name, dialogues in name_to_dialogues.items()
        if len(dialogues) >= 2
        and (features := _dialogue_style_features(dialogues)) is not None
    ]
    reported = False
    for i in range(len(styled)):
        for j in range(i + 1, len(styled)):
            name_a, feat_a = styled[i]
            name_b, feat_b = styled[j]
            if (
                abs(feat_a[0] - feat_b[0]) < 1.5
                and abs(feat_a[1] - feat_b[1]) < 0.05
                and abs(feat_a[2] - feat_b[2]) < 0.05
            ):
                issues.append(
                    BehaviorConsistencyIssue(
                        character_name=f"{name_a}/{name_b}",
                        chapter_number=chapter_number,
                        check_type="dialogue_homogenization",
                        severity="medium",
                        reason=(
                            "同场角色对白句长与标点习惯高度一致，"
                            "存在对白同质化风险，请核对各自说话风格"
                        ),
                        evidence_text="\n".join(
                            f"{name_a}：“{line}”" for line in name_to_dialogues[name_a][:2]
                        )
                        + "\n"
                        + "\n".join(
                            f"{name_b}：“{line}”" for line in name_to_dialogues[name_b][:2]
                        ),
                    )
                )
                reported = True
                break
        if reported:
            break

    return issues
