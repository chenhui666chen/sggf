"""人物运行态验收测试（P0）。

覆盖文档第 3 节验收要求：
- 性格/价值倾向/限制/成长方向/说话风格均进入运行态摘要，且不同角色可区分
- 字段缺失时保持旧输出兼容（不报错、不出现空字段占位）
- 三个调用点全部传完整参数（静态回归，防止后续新增旁路时漏传字段）
"""
from pathlib import Path
import re
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.character_runtime_context import build_character_runtime_brief

_RUNTIME_FIELDS = (
    "personality",
    "worldview",
    "limitation",
    "growth_direction",
    "speech_style",
)


def test_distinct_personalities_produce_distinct_briefs():
    """性格不同的角色摘要必须可区分（防角色扁平化/同质化）。"""
    common = dict(
        role="主角",
        role_position="青云宗外门弟子",
        motivation="寻找失踪的师父",
    )
    brief_a = build_character_runtime_brief(
        name="林晚",
        personality="冷静克制，习惯用逻辑压制情绪",
        worldview="规则即秩序，秩序即正义",
        speech_style="短句，少用语气词",
        **common,
    )
    brief_b = build_character_runtime_brief(
        name="林晚",
        personality="冲动炽烈，凭直觉行事",
        worldview="强者为尊，弱肉强食",
        speech_style="长句，语气词多",
        **common,
    )
    assert brief_a != brief_b
    assert "冷静克制" in brief_a and "冲动炽烈" in brief_b
    assert "价值倾向" in brief_a and "价值倾向" in brief_b


def test_all_stable_baseline_fields_rendered():
    """性格/价值倾向/限制/成长方向/说话风格全部进入摘要。"""
    brief = build_character_runtime_brief(
        name="沈决",
        role_position="捕头",
        personality="外冷内热",
        worldview="律法之下无人例外",
        limitation="旧伤未愈，不能久战",
        growth_direction="学会信任同伴",
        speech_style="公文体措辞",
    )
    assert "性格：外冷内热" in brief
    assert "价值倾向：律法之下无人例外" in brief
    assert "限制：旧伤未愈" in brief
    assert "成长方向：学会信任同伴" in brief
    assert "说话风格：公文体措辞" in brief


def test_missing_fields_keep_legacy_output_compatible():
    """新字段缺失时不报错、不输出空占位，与旧格式兼容。"""
    brief = build_character_runtime_brief(
        name="顾长青",
        role="配角",
        motivation="守护家族",
    )
    assert brief.startswith("顾长青")
    assert "动机：守护家族" in brief
    for label in ("性格：", "价值倾向：", "限制：", "成长方向：", "说话风格："):
        assert label not in brief


def test_empty_name_returns_empty_string():
    assert build_character_runtime_brief(name="") == ""
    assert build_character_runtime_brief(name="   ") == ""


def test_all_call_sites_pass_full_runtime_fields():
    """回归：character_runtime_context.py 内所有调用点必须传齐运行态字段，
    防止后续新增旁路时漏传。"""
    source_path = ROOT_DIR / "app" / "services" / "character_runtime_context.py"
    source = source_path.read_text(encoding="utf-8")
    call_sites = [
        match.group(0)
        for match in re.finditer(
            r"build_character_runtime_brief\((?:[^()]|\([^()]*\))*\)",
            source,
            re.DOTALL,
        )
        # 排除函数定义行本身（前面紧跟 "def "）
        if not source[max(0, match.start() - 4):match.start()].endswith("def ")
    ]
    # 除函数定义本身外至少存在三个调用点（运行态元数据/核心角色锚点/提示词上下文）
    assert len(call_sites) >= 3
    for call in call_sites:
        for field in _RUNTIME_FIELDS:
            assert f"{field}=" in call, f"调用点缺少字段 {field}: {call[:120]}"
