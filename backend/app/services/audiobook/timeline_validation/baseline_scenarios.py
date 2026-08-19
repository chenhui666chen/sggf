"""阶段 0 五类固定场景集（基线冻结）。

场景集一经冻结，Prompt 文本与结构不得改动；如需演进必须提升
``BASELINE_CATALOG_VERSION`` 并在进度文档记录决策变更。

- ``phone_distortion_dialogue`` / ``narrative_monologue`` 直接复用 V1 测试单元
  （``seed_scene_test_unit``）中的既有场景，保证与 V1 基线逐字一致；
- ``lingshan_battle`` / ``live_commerce`` / ``ad_timeline`` 为 V2 新增固定场景，
  Prompt 在本文件内冻结；
- ``ad_timeline`` 的具体时间轴样例与目标窗口定义在 ``ad_timeline_sample`` 模块。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from app.services.audiobook.seed_scene_test_unit import get_seed_scene_test_case

BASELINE_CATALOG_ID = "seed-audio-v2-phase0-scenarios"
BASELINE_CATALOG_VERSION = "1.0.0"

# V1 复用场景：variant 固定取 described_voices（不依赖参考音频，可直接复现）。
_V1_REUSED_VARIANT = "described_voices"


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _reused_v1_scenario(
    scenario_id: str,
    v1_case_id: str,
    capability: str,
) -> Dict[str, Any]:
    case = get_seed_scene_test_case(v1_case_id)
    variant = next(
        item for item in case["variants"] if item["id"] == _V1_REUSED_VARIANT
    )
    prompt = str(variant["prompt"])
    return {
        "id": scenario_id,
        "name": case["name"],
        "capability": capability,
        "source": f"seed_scene_test_unit:{v1_case_id}#{_V1_REUSED_VARIANT}",
        "expected_texts": list(case["expected_texts"]),
        "expected_duration_s": float(case["expected_duration_s"]),
        "prompt": prompt,
        "prompt_sha256": prompt_sha256(prompt),
    }


_LINGSHAN_BATTLE_PROMPT = """弟子 是青年男性，嗓音清亮、倔强；师兄 是成年男性，嗓音沉稳、有力；魔王 是低沉浑厚、带压迫感的男性声音。
对白始终清晰位于前景，音乐、环境声和动作音效不得遮挡人声。严格朗读引号中的原文，不新增、删减或改写台词，不产生未声明的可辨识人声。
灵山山门前的开阔石台，远处风声持续，石壁带来明显混响。
低沉的法号声由远及近，弟子拔剑冲出，坚定而急切地喊：“师兄，护住山门！”
师兄沉声应和，声音稳定有力：“结阵，莫乱！” 伴随数声金属碰撞与脚步腾挪。
一声炸雷般的轰鸣后，魔王低沉、缓慢而压迫地大笑说：“就凭你们，也想挡我？” 笑声在石壁间产生明显回声。
弟子被震退半步，咬牙再度冲上，嘶声大喊：“灵山不容践踏！” 紧接着是一连串密集的法术爆鸣与碎石崩落声。
场景在一声悠远的钟鸣和渐弱的混响尾音中结束。
"""

_LIVE_COMMERCE_PROMPT = """主播 是青年女性，声音明亮、语速快、有感染力；助播 是背景中的青年男性，声音略远、热情。
对白始终清晰位于前景，音乐、环境声和动作音效不得遮挡人声。严格朗读引号中的原文，不新增、删减或改写台词，不产生未声明的可辨识人声。
直播间室内，轻快的背景音乐持续但音量较低，偶尔有轻微的提示音。
主播兴奋、语速较快地说：“家人们，三号链接马上开抢，只有五百单！”
背景中助播隔着一定距离插话喊：“库存已经不到一半了！” 声音与主播尾音轻微重叠，但主播台词必须完整清晰。
主播提高音量、带笑意地回应：“没抢到的扣一，下一波马上补货！”
随后响起一声清脆的上架提示音，主播恢复平稳语速说：“来，我们看下一个品。”
"""

_AD_TIMELINE_PROMPT_NOTE = (
    "ad_timeline 场景的可重复实测样例以 timeline_validation.ad_timeline_sample "
    "模块为准：Prompt 由 build_timeline_prompt 按语法变体渲染，目标窗口为 "
    "AD_TARGET_EVENTS；本目录中的 prompt_sha256 冻结的是 canonical 语法变体。"
)


def _new_scenario(
    scenario_id: str,
    name: str,
    capability: str,
    prompt: str,
    expected_texts: List[str],
    expected_duration_s: float,
    note: str = "",
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "id": scenario_id,
        "name": name,
        "capability": capability,
        "source": "timeline_validation:baseline_scenarios",
        "expected_texts": list(expected_texts),
        "expected_duration_s": float(expected_duration_s),
        "prompt": prompt.strip() + "\n",
        "prompt_sha256": prompt_sha256(prompt.strip() + "\n"),
    }
    if note:
        entry["note"] = note
    return entry


def build_baseline_catalog() -> Dict[str, Any]:
    """构造版本化的五类固定场景清单（确定性输出，可整体哈希）。"""
    from .ad_timeline_sample import (
        TIMELINE_SYNTAX_CANONICAL,
        build_timeline_prompt,
    )

    canonical_prompt = build_timeline_prompt(TIMELINE_SYNTAX_CANONICAL)
    scenarios = [
        _reused_v1_scenario(
            "phone_distortion_dialogue",
            "phone_confrontation",
            "多角色、电话空间",
        ),
        _new_scenario(
            "lingshan_battle",
            "灵山战斗",
            "多人、音效蒙太奇、混响",
            _LINGSHAN_BATTLE_PROMPT,
            [
                "师兄，护住山门！",
                "结阵，莫乱！",
                "就凭你们，也想挡我？",
                "灵山不容践踏！",
            ],
            36.0,
        ),
        _reused_v1_scenario(
            "narrative_monologue",
            "single_voice_memory",
            "环境声、情绪表演",
        ),
        _new_scenario(
            "live_commerce",
            "直播带货",
            "背景插话、口音、重叠",
            _LIVE_COMMERCE_PROMPT,
            [
                "家人们，三号链接马上开抢，只有五百单！",
                "库存已经不到一半了！",
                "没抢到的扣一，下一波马上补货！",
                "来，我们看下一个品。",
            ],
            26.0,
        ),
        _new_scenario(
            "ad_timeline",
            "广告时间轴",
            "timeline",
            canonical_prompt,
            [
                "深夜加班，胃在抗议。",
                "一杯温热，三分钟回到状态。",
                "现在下单，第二件半价。",
            ],
            30.0,
            note=_AD_TIMELINE_PROMPT_NOTE,
        ),
    ]
    return {
        "catalog_id": BASELINE_CATALOG_ID,
        "catalog_version": BASELINE_CATALOG_VERSION,
        "scenarios": scenarios,
    }


def get_baseline_scenario(scenario_id: str) -> Dict[str, Any]:
    catalog = build_baseline_catalog()
    for scenario in catalog["scenarios"]:
        if scenario["id"] == scenario_id:
            return scenario
    raise ValueError(f"unknown baseline scenario: {scenario_id}")


def catalog_canonical_hash(catalog: Dict[str, Any] | None = None) -> str:
    """对整个基线目录做确定性规范化哈希，用作输入版本身份。"""
    payload = catalog or build_baseline_catalog()
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
