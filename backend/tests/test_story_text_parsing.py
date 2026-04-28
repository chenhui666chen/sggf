import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.models.character import Character
from app.services.character_runtime_context import (
    build_character_prompt_context_from_text,
    build_character_relations_payload,
    build_current_mainline_summary,
    build_current_relationship_summary,
    normalize_character_relations_payload,
)
from app.services.character_parser import CharacterTextParser, infer_story_stance_from_text_evidence
from app.services.character_text_generator import CharacterTextGenerator
from app.services.story_expansion_coordinator import (
    extract_character_names,
    normalize_outline_text,
    parse_outline_blocks,
)


def test_character_text_parser_supports_dreamweaver_heading_cards() -> None:
    characters = json.dumps(
        """# 《情绪猎人》人物设定详案

## 一、主角阵营：挣扎的变量与同路人

### **陈骁（主角）**
- **基本信息**：26岁，前大学生。

### **“回声” / 沈墨（关键配角·情报贩子）**
- **基本信息**：28岁，前数据分析师。

### **“莫比乌斯” / 未知（黑市商人）**
- **基本信息**：年龄、性别、外貌皆不详。
""",
        ensure_ascii=False,
    )

    parsed = CharacterTextParser().parse_all_characters(characters)

    assert [item.name for item in parsed] == ["陈骁", "沈墨", "莫比乌斯"]
    assert parsed[0].importance_level == "主角"


def test_extract_character_names_supports_dreamweaver_alias_lines() -> None:
    characters = """
### **“缝合手” / 老吴（关键配角·地下医生）**
- **基本信息**：55岁，地下医生。

### **老王（次要配角·外卖站长）**
- **基本信息**：48岁，外卖站长。
"""

    assert extract_character_names(characters) == ["老吴", "老王"]


def test_character_text_parser_separates_story_stance_and_role_position() -> None:
    characters = """
### 【姓名】：苏晚
【年龄/性别】：19岁/女
【故事立场】：主角方
【角色定位】：核心盟友
【所属势力】：灰烬坊市
【重要性】：重要角色
【性格特点】：冷静克制，但对弱者有强烈保护欲。
【核心动机】：查清自身血脉真相，并守住来之不易的同伴。
"""

    parsed = CharacterTextParser().parse_all_characters(characters)

    assert len(parsed) == 1
    assert parsed[0].role == "主角方"
    assert parsed[0].role_position == "核心盟友"
    assert "【故事立场】\n主角方" in parsed[0].build_profile()
    assert "【角色定位】\n核心盟友" in parsed[0].build_profile()


def test_character_text_parser_infers_story_stance_from_role_position_when_missing() -> None:
    characters = """
### 【姓名】：叶凌霄
【年龄/性别】：28岁/男
【角色定位】：初期对手
【所属势力】：天枢剑宗
【性格特点】：冷厉克制，执行意志极强。
"""

    parsed = CharacterTextParser().parse_all_characters(characters)

    assert len(parsed) == 1
    assert parsed[0].role == "反派方"
    assert parsed[0].role_position == "初期对手"
    assert parsed[0].importance_level == "次要角色"


def test_character_text_generator_maps_legacy_role_values_to_story_stance() -> None:
    character = Character(
        project_id=1,
        name="林澈",
        role="protagonist",
        role_position="主角",
        importance_level="主角",
        summary="失序世界中的破局者，承担主线抉择。",
        profile="""
【性格特点】
冷静谨慎，但在关键抉择面前会主动承担代价。

【核心动机】
查清灾变真相，保住仍愿意同行的人。
""",
    )

    text = CharacterTextGenerator.generate_single_character_text(
        character,
        db=None,
        include_relations=False,
        include_techniques=False,
    )

    assert text.startswith("### 【姓名】：林澈")
    assert "【故事立场】：主角方" in text
    assert "【角色定位】：主角" in text
    assert "【外貌锚点】" not in text
    assert "【性格锚点】：性格：冷静谨慎，但在关键抉择面前会主动承担代价。" in text
    assert "【核心动机】：查清灾变真相，保住仍愿意同行的人。" in text
    assert "【能力与限制】" not in text
    assert "【主线绑定】：剧情职责：失序世界中的破局者，承担主线抉择。" in text

    parsed = CharacterTextParser().parse_all_characters(text)

    assert len(parsed) == 1
    assert parsed[0].name == "林澈"
    assert parsed[0].role == "主角方"
    assert parsed[0].role_position == "主角"
    assert parsed[0].importance_level == "主角"
    assert parsed[0].personality == "冷静谨慎，但在关键抉择面前会主动承担代价。"
    assert parsed[0].motivation == "查清灾变真相，保住仍愿意同行的人。"
    assert parsed[0].mainline_role == "失序世界中的破局者，承担主线抉择。"


def test_infer_story_stance_from_text_evidence_supports_explicit_story_stance() -> None:
    profile = """
简介: 神秘引导者，掌握关键芯片与Z层线索。
故事立场: 亦正亦邪
与主角关系: 外部权力介入者，破晓行动国际变量
"""

    assert infer_story_stance_from_text_evidence(profile) == "亦正亦邪"


def test_infer_story_stance_from_text_evidence_supports_relation_and_conflict_descriptions() -> None:
    ally_profile = """
与主角关系：从敌对到生死相托的战友。
作用：帮助主角建立稳定据点。
"""
    enemy_profile = """
与主角冲突：视林寒的契约之道为软弱和妥协，欲夺取契印。
作用：前期主要追捕者与武力对抗符号。
"""

    assert infer_story_stance_from_text_evidence(ally_profile) == "主角方"
    assert infer_story_stance_from_text_evidence(enemy_profile) == "反派方"


def test_infer_story_stance_from_text_evidence_avoids_antagonist_false_positive_on_long_biography() -> None:
    protagonist_profile = """
【姓名】：林寒
【身份】：前宗门天才制符师，上古契印唯一传人，兽盟缔造者。
【背景故事】：曾被宗门逐出，在流亡中被多方追杀。
【核心目标】：重建共生之道，带领兽盟活下去。
"""

    assert infer_story_stance_from_text_evidence(protagonist_profile) is None


def test_parse_outline_blocks_supports_chapter_outline_sections() -> None:
    outline = json.dumps(
        """# 《情绪猎人》情节大纲

## 一、主线情节

**第一阶段：觉醒与追猎（第1-30章）**
- **关键节点**：
  - 第3章：第一次生死战

## 二、第一章大纲

**章节标题建议**：《第一滴恐惧》

**主要情节**：
1. 意外订单
2. 初次吸收
""",
        ensure_ascii=False,
    )

    prefix, blocks = parse_outline_blocks(outline)

    assert "《情绪猎人》情节大纲" in prefix
    assert len(blocks) == 1
    assert blocks[0].original_number == 1
    assert blocks[0].title == "第一滴恐惧"


def test_build_character_relations_payload_prioritizes_current_relations() -> None:
    raw_relations = (
        "苏晚晴：雇主/庇护者与潜在的背叛风险；"
        "云无月：监视者/追捕者与理念冲突下的奇异吸引；"
        "影舞：直接威胁/持续观察的猎手；"
        "石磊：实际恩主与战略领袖/获得其无条件忠诚；"
        "黑风煞：已击杀的敌对首领/其死亡揭示的龙怨警告被验证；"
        "墨渊：间接的知识提供者/通过云无月或白鹤真人接触"
    )

    payload = build_character_relations_payload(raw_relations, max_current_items=4, max_current_chars=160)

    assert payload["version"] == 2
    assert len(payload["items"]) >= 5
    assert "苏晚晴" in payload["current_summary"]
    assert "影舞" in payload["current_summary"]
    assert "石磊" in payload["current_summary"]
    assert "黑风煞" not in payload["current_summary"]


def test_normalize_character_relations_payload_supports_legacy_target_type_mapping() -> None:
    payload = normalize_character_relations_payload({
        "顾晚": "盟友",
        "影舞": "威胁",
    })

    assert payload is not None
    assert payload["version"] == 2
    assert payload["current_summary"] == "顾晚：盟友；影舞：威胁"
    assert [item["target"] for item in payload["items"]] == ["顾晚", "影舞"]
    assert [item["type"] for item in payload["items"]] == ["盟友", "威胁"]
    assert all(int(item["priority"]) > 0 for item in payload["items"])


def test_build_current_mainline_summary_filters_resolved_total_ledger_text() -> None:
    mainline_role = (
        "剧情职责：需承担导师职责，整合并领导新附庸势力；"
        "作为寻龙堂创立者与领导者，需统筹研究方向并亲自带队执行首次高危勘探；"
        "黑风煞死亡引发的连锁反应已被处理"
    )
    mainline_clues = (
        "关联线索：通过墨渊获取上古风水师被天律盟抹杀的历史；"
        "黑风煞遗留的裂缝隐患成为首个长期监控对象；"
        "赤岩尊者勾结葬骨城的证据已被处理"
    )

    summary = build_current_mainline_summary(mainline_role, mainline_clues, max_chars=200)

    assert "寻龙堂" in summary
    assert "墨渊" in summary or "上古风水师" in summary
    assert "已被处理" not in summary


def test_character_text_generator_supports_relation_payload_dict() -> None:
    relations = build_character_relations_payload("顾晚：盟友/互相信任；影舞：直接威胁/持续观察")
    character = Character(
        project_id=1,
        name="林澈",
        role="主角方",
        role_position="主角",
        importance_level="主角",
        relations=json.dumps(relations, ensure_ascii=False),
    )

    text = CharacterTextGenerator.generate_single_character_text(
        character,
        db=None,
        include_relations=True,
        include_techniques=False,
    )

    assert "【关键关系】" in text
    assert "顾晚：盟友/互相信任" in text
    assert "影舞：直接威胁/持续观察" in text


def test_build_character_prompt_context_from_text_uses_runtime_summary_instead_of_raw_cards() -> None:
    characters = "\n\n".join(
        [
            (
                "### 【姓名】：顾长歌\n"
                "【故事立场】：主角方\n"
                "【角色定位】：主角\n"
                "【关键关系】：苏晚晴：雇主/庇护者与潜在的背叛风险；影舞：直接威胁/持续观察的猎手；"
                "黑风煞：已击杀的敌对首领/其死亡揭示的龙怨警告被验证\n"
                "【主线绑定】：剧情职责：整合并领导新附庸势力；关联线索：通过墨渊获取上古风水师历史\n"
                f"【背景/当前处境】：{'背景信息' * 20}"
            ),
            (
                "### 【姓名】：苏晚晴\n"
                "【故事立场】：亦正亦邪\n"
                "【角色定位】：危险盟友\n"
                "【关键关系】：顾长歌：雇主/依赖与试探并存\n"
                "【主线绑定】：剧情职责：左右主角资源入口"
            ),
        ]
    )

    context = build_character_prompt_context_from_text(
        characters,
        detail_limit=180,
        summary_limit=120,
        max_characters=2,
    )

    assert "【角色名单摘要】" in context
    assert "【人物运行摘要】" in context
    assert "当前关系" in context
    assert "黑风煞" not in context
    assert "背景信息背景信息背景信息" not in context
