"""场景驱动的设定按需召回服务。

根据章节细纲的场景类型（战斗/炼制/探索/突破）与焦点人物，
从结构化设定库确定性召回该场景所需的设定细节
（人物功法/武器法宝/丹药/境界），注入正文生成上下文。

与 Typed-RAG 的语义检索互补：
- Typed-RAG 召回"文本相似"的全局设定，不保证出场人物的设定在场；
- 本服务保证"出场人物当前可用的设定一定在场"，
  且通过 learned_at_chapter 实现时间一致性（未习得的功法不提前出现）。

数据来源（按优先级）：
1. CharacterTechnique 中间表：人物功法（含熟练度、习得章节、施展代价）
2. Character.current_realm / artifacts_json：境界、法宝ID列表
3. SettingItem.related_characters：与人物关联的武器/丹药等（auto_tracking 自动维护）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.models.character import Character, CharacterTechnique
from app.models.setting import SettingCollection, SettingItem

logger = logging.getLogger(__name__)

# 场景类型 → 触发关键词（子串匹配，零成本）
SCENE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "combat": (
        "打斗", "交手", "激战", "战斗", "对峙", "出手", "厮杀", "比武", "切磋",
        "斗法", "大战", "围攻", "偷袭", "追杀", "交战", "动手", "攻击", "过招", "搏杀",
    ),
    "alchemy": ("炼丹", "炼制", "丹炉", "炼器", "锻造", "炼化", "淬炼"),
    "exploration": ("秘境", "探险", "遗迹", "探查", "寻宝", "历练", "禁地", "闯荡"),
    "breakthrough": ("突破", "晋阶", "渡劫", "冲击境界", "冲击瓶颈", "瓶颈", "闭关"),
}

# 场景类型 → 需要召回的设定类别
SCENE_CATEGORY_MAP: Dict[str, Tuple[str, ...]] = {
    "combat": (
        "technique_system", "weapon_system", "cultivation_realm_system",
        "martial_realm_system", "ability_system", "magic_system", "talisman_system",
    ),
    "alchemy": ("pill_system", "resource_system", "technique_system"),
    "exploration": ("map_system", "formation_system", "special_artifact_relic_system"),
    "breakthrough": ("cultivation_realm_system", "pill_system", "technique_system"),
}

SCENE_LABELS: Dict[str, str] = {
    "combat": "战斗",
    "alchemy": "炼制",
    "exploration": "探索",
    "breakthrough": "突破",
}

# 预算控制
MAX_CHARACTERS = 4
MAX_ITEMS_PER_CHARACTER = 5
MAX_ITEM_CONTENT_LENGTH = 150
MAX_PACK_LENGTH = 1200

# 类别 → 条目前缀（fallback 用类别中文名去"体系"后缀）
CATEGORY_PREFIX: Dict[str, str] = {
    "technique_system": "功法",
    "weapon_system": "武器",
    "talisman_system": "符箓",
    "pill_system": "丹药",
    "formation_system": "阵法",
    "special_artifact_relic_system": "道具",
    "map_system": "地点",
    "cultivation_realm_system": "境界",
    "martial_realm_system": "境界",
    "magic_system": "法术",
    "ability_system": "异能",
    "resource_system": "资源",
}


@dataclass
class SceneSettingPack:
    """场景设定包：注入文本 + 已注入的设定项ID集合（供 RAG 去重）"""

    text: str = ""
    setting_ids: Set[int] = field(default_factory=set)
    scene_types: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text)


def detect_scenes(text: Optional[str]) -> List[str]:
    """从细纲/章节规划文本识别场景类型（按 SCENE_KEYWORDS 定义顺序去重返回）"""
    if not text or not text.strip():
        return []
    scenes: List[str] = []
    for scene_type, keywords in SCENE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            scenes.append(scene_type)
    return scenes


# 规划点名设定提取的预算控制
MAX_PLANNED_SETTINGS = 10
MIN_SETTING_NAME_LENGTH = 2


def extract_planned_settings(
    db: Session,
    project_id: int,
    plan_text: Optional[str],
) -> List[SettingItem]:
    """从章节规划文本中提取被点名的设定项（精确名称匹配）。

    章节规划的"设定调用"字段（或其他段落）中提到的设定名称，
    在设定中心内精确匹配命中的项，供正文生成确定性注入详情。

    匹配策略为子串包含（不依赖规划输出格式稳定性）；名称过短（<2字）
    的设定项跳过以避免误命中。

    Args:
        db: 数据库会话
        project_id: 项目ID
        plan_text: 章节规划全文

    Returns:
        命中的设定项列表（按名称长度降序，最长优先），最多 MAX_PLANNED_SETTINGS 项
    """
    if not plan_text or not plan_text.strip():
        return []

    rows = (
        db.query(SettingItem, SettingCollection.category)
        .join(SettingCollection, SettingItem.collection_id == SettingCollection.id)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category != "candidate",
        )
        .all()
    )

    matched: List[SettingItem] = []
    for item, _category in rows:
        name = (item.name or "").strip()
        if len(name) < MIN_SETTING_NAME_LENGTH:
            continue
        if name in plan_text:
            matched.append(item)

    # 长名称优先（避免"青锋"与"青锋剑"嵌套时短名占位），并限制总量
    matched.sort(key=lambda it: len(it.name or ""), reverse=True)
    return matched[:MAX_PLANNED_SETTINGS]


def _category_prefix(category: Optional[str]) -> str:
    if not category:
        return "设定"
    if category in CATEGORY_PREFIX:
        return CATEGORY_PREFIX[category]
    from app.services.setting_categories import SYSTEM_CATEGORIES

    label = SYSTEM_CATEGORIES.get(category, category)
    return label[:-2] if label.endswith("体系") else label


def _truncate_content(item: SettingItem) -> str:
    content = (item.content or item.summary or "").strip().replace("\n", " ")
    if len(content) > MAX_ITEM_CONTENT_LENGTH:
        content = content[:MAX_ITEM_CONTENT_LENGTH] + "…"
    return content


def _parse_json_ids(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [int(v) for v in parsed if isinstance(v, (int, float, str)) and str(v).isdigit()]


def _collect_scene_categories(scene_types: Sequence[str]) -> Tuple[str, ...]:
    categories: List[str] = []
    for scene_type in scene_types:
        for category in SCENE_CATEGORY_MAP.get(scene_type, ()):
            if category not in categories:
                categories.append(category)
    return tuple(categories)


def build_scene_setting_pack(
    db: Session,
    project_id: int,
    focus_character_names: Optional[Sequence[str]],
    *,
    current_chapter_number: Optional[int] = None,
    source_text: Optional[str] = None,
    scene_types: Optional[Sequence[str]] = None,
) -> SceneSettingPack:
    """构场景设定包。

    Args:
        db: 数据库会话
        project_id: 项目ID
        focus_character_names: 本章焦点人物名（来自章节生成上下文）
        current_chapter_number: 当前章节号（用于过滤未习得功法）
        source_text: 细纲/章节规划文本（scene_types 未提供时用于自动识别场景）
        scene_types: 显式指定的场景类型（优先于 source_text 自动识别）

    Returns:
        SceneSettingPack：text 为注入文本，setting_ids 供 RAG 结果去重
    """
    names = [n.strip() for n in (focus_character_names or []) if n and n.strip()][:MAX_CHARACTERS]
    if not names:
        return SceneSettingPack()

    resolved_scenes = list(scene_types or [])
    if not resolved_scenes:
        resolved_scenes = detect_scenes(source_text or "")
    if not resolved_scenes:
        return SceneSettingPack()

    categories = _collect_scene_categories(resolved_scenes)
    if not categories:
        return SceneSettingPack()

    characters = (
        db.query(Character)
        .filter(
            Character.project_id == project_id,
            Character.name.in_(names),
        )
        .all()
    )
    if not characters:
        return SceneSettingPack()
    # 按传入的焦点人物顺序输出（焦点人物应排在段落前面）
    name_order = {name: idx for idx, name in enumerate(names)}
    characters.sort(key=lambda c: name_order.get(c.name, len(names)))

    # 类别下所有设定项（一次查询，供 related_characters 关联过滤复用）
    category_items: List[Tuple[SettingItem, Optional[str]]] = (
        db.query(SettingItem, SettingCollection.category)
        .join(SettingCollection, SettingItem.collection_id == SettingCollection.id)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category.in_(categories),
        )
        .all()
    )
    if not category_items:
        return SceneSettingPack()

    injected_ids: Set[int] = set()
    character_blocks: List[str] = []

    for character in characters:
        entries: List[str] = []

        # 1. 当前境界（战斗/突破场景必带）
        if character.current_realm_item_id:
            realm_item = next(
                (item for item, _ in category_items if item.id == character.current_realm_item_id),
                None,
            )
            if realm_item:
                entries.append(f"· 境界 {realm_item.name}")
                injected_ids.add(realm_item.id)

        # 2. 功法（CharacterTechnique，含熟练度/习得章节/施展代价）
        technique_rows = (
            db.query(CharacterTechnique, SettingItem, SettingCollection.category)
            .join(SettingItem, CharacterTechnique.technique_item_id == SettingItem.id)
            .join(SettingCollection, SettingItem.collection_id == SettingCollection.id)
            .filter(
                CharacterTechnique.character_id == character.id,
                SettingCollection.category.in_(categories),
            )
            .all()
        )
        for ct, item, ct_category in technique_rows:
            if (
                current_chapter_number
                and ct.learned_at_chapter
                and ct.learned_at_chapter > current_chapter_number
            ):
                continue  # 尚未习得，防止剧情穿越
            proficiency = f"[{ct.proficiency}]" if ct.proficiency else ""
            note = f"（{ct.notes}）" if ct.notes else ""
            prefix = _category_prefix(ct_category)
            entries.append(f"· {prefix}{proficiency} {item.name}: {_truncate_content(item)}{note}")
            injected_ids.add(item.id)

        # 3. 法宝ID列表（Character.artifacts_json）
        artifact_ids = [
            aid for aid in _parse_json_ids(character.artifacts_json) if aid not in injected_ids
        ]
        if artifact_ids:
            for item, item_category in category_items:
                if item.id not in artifact_ids or item.id in injected_ids:
                    continue
                entries.append(f"· {_category_prefix(item_category)} {item.name}: {_truncate_content(item)}")
                injected_ids.add(item.id)

        # 4. related_characters 关联的武器/丹药等（auto_tracking 自动维护）
        for item, item_category in category_items:
            if item.id in injected_ids:
                continue
            related = _parse_json_ids(item.related_characters)
            if character.id not in related:
                continue
            entries.append(f"· {_category_prefix(item_category)} {item.name}: {_truncate_content(item)}")
            injected_ids.add(item.id)

        if entries:
            block = f"- {character.name}：\n" + "\n".join(entries[:MAX_ITEMS_PER_CHARACTER])
            character_blocks.append(block)

    if not character_blocks:
        return SceneSettingPack(scene_types=resolved_scenes)

    scene_label = "/".join(SCENE_LABELS.get(s, s) for s in resolved_scenes)
    header = (
        f"【本章场景设定包·{scene_label}】"
        "（以下为出场人物当前可用的设定资源，正文写作必须严格遵守其规则与限制）"
    )
    text = header + "\n" + "\n".join(character_blocks)
    if len(text) > MAX_PACK_LENGTH:
        text = text[:MAX_PACK_LENGTH] + "…"

    return SceneSettingPack(text=text, setting_ids=injected_ids, scene_types=resolved_scenes)
