# -*- coding: utf-8 -*-
"""Shot Contract 引擎（storyboarder_pkg v2）冒烟测试：确定性引擎，无 LLM 依赖。

覆盖：知识加载 → Contract 生成（12 字段/七族路由/景别选型/运镜灯光映射/呼吸等待/R-pre）
→ T3 预检（光学一致性修复/技巧干涉/EMOTION_STALL trim）→ 兼容 storyboard item
→ 容器模式时长阶梯 + rebalance + subshots → camera_states → script_text 降级路径。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _make_document() -> dict:
    """两场六 beat：覆盖七族路由的关键族。"""
    return {
        "schema_version": "2.0",
        "scenes": [
            {
                "scene_id": "S1", "number": 1, "title": "夜班",
                "interior": "内景", "location": "急诊室", "time_of_day": "夜",
                "characters": ["林晚", "陈默"], "summary": "匿名化验单出现",
                "beats": [
                    {"beat_id": "S1-B1", "family": "开场建置族", "type": "action",
                     "description": "急诊室夜景全貌，抢救声不断",
                     "action": "看", "shot_purpose": "建立空间",
                     "dialogue": [], "visual_anchor": "急诊室走廊与闪烁的灯",
                     "hook": True, "duration_hint_s": 4.0},
                    {"beat_id": "S1-B2", "family": "信息揭示族", "type": "reveal",
                     "description": "林晚拆开信封，化验单滑出",
                     "action": "伸手→接→拿起", "shot_purpose": "揭示变化",
                     "dialogue": [], "visual_anchor": "化验单滑落在地",
                     "hook": False, "duration_hint_s": 3.0},
                    {"beat_id": "S1-B3", "family": "情绪爆发族", "type": "dialogue",
                     "description": "林晚认出签名，崩溃质问",
                     "action": "看→皱眉→流泪", "shot_purpose": "强调情绪",
                     "dialogue": [{"speaker": "林晚", "line": "你到底瞒了我什么", "emotion": "sad"}],
                     "visual_anchor": "颤抖的手与攥皱的化验单",
                     "hook": False, "duration_hint_s": 4.0},
                ],
            },
            {
                "scene_id": "S2", "number": 2, "title": "对峙",
                "interior": "内景", "location": "天台", "time_of_day": "夜",
                "characters": ["林晚", "陈默"], "summary": "天台摊牌",
                "beats": [
                    {"beat_id": "S2-B1", "family": "冲突动作族", "type": "action",
                     "description": "陈默上前抢夺化验单，两人拉扯",
                     "action": "上前一步→伸手→握→拉", "shot_purpose": "强调情绪",
                     "dialogue": [], "visual_anchor": "两双手争夺一张纸",
                     "hook": False, "duration_hint_s": 3.0},
                    {"beat_id": "S2-B2", "family": "关系状态族", "type": "dialogue",
                     "description": "沉默对峙后林晚松手转身",
                     "action": "松开→转身→后退", "shot_purpose": "建立关系",
                     "dialogue": [{"speaker": "陈默", "line": "对不起", "emotion": "sad"}],
                     "visual_anchor": "背对背的两个剪影",
                     "hook": False, "duration_hint_s": 5.0},
                    {"beat_id": "S2-B3", "family": "收尾定格族", "type": "transition",
                     "description": "林晚独自走向天台边缘，城市灯光铺开",
                     "action": "走", "shot_purpose": "建立空间",
                     "dialogue": [], "visual_anchor": "孤独背影与城市灯海",
                     "hook": False, "duration_hint_s": 6.0},
                ],
            },
        ],
    }


def _make_ctx(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


# ---------------------------------------------------------------- 知识层
def test_knowledge_loads():
    from agents.storyboarder_pkg._knowledge import load_storyboard_knowledge
    k = load_storyboard_knowledge()
    assert len(k["beat_families"]) == 7
    assert "DC-035" in k["dc_by_id"] and "DC-036" in k["dc_by_id"] and "DC-037" in k["dc_by_id"]
    assert len(k["cf_triggers"]) == 16


# ---------------------------------------------------------------- 全流程（非容器引擎）
def test_run_contract_engine_non_container(monkeypatch):
    monkeypatch.delenv("DREAMWEAVER_STORYBOARD_MAX_SHOTS", raising=False)
    payload = {
        "run_id": "run-sb-1",
        "script_document": _make_document(),
        "script_text": "## 概要\n- x\n## 分场\n### 场1 | 内景 | 急诊室 | 夜\n节拍：\n- a\n对白：\n- 林晚：谁",
        "script_entities": {
            "characters": [{"name": "林晚", "descriptor": "医生", "importance": "main"}],
            "scenes": [{"name": "急诊室", "descriptor": ""}],
            "props": [{"name": "化验单", "descriptor": ""}],
        },
        "character_profiles": [{"name": "林晚", "character_id": "char_001"}],
        "quality_mode": "fast",
        "video_config": {"engine": "ffmpeg_slideshow"},
        "image_config": {"ratio": "9:16"},
    }
    ctx = _make_ctx(payload)
    from agents.storyboarder_pkg import run
    run(ctx)

    # Contract 层
    contracts = ctx.payload["shot_contracts"]
    assert len(contracts) == 6
    c2 = contracts[1]  # S1-B2 信息揭示族 reveal
    assert c2["shot_size"] == "ECU"  # Information Reveal → ECU
    assert c2["dispatch_dc_ids"], "信息揭示族应有 T2 dispatch DC"
    assert c2["r_pre_eligible"] is True
    assert c2["duration_s"] >= 3.0 + 2.0, "揭示后呼吸等待 ≥2s（3+2）"
    c1 = contracts[0]  # 开场建置 → LS
    assert c1["shot_size"] == "LS"
    assert c1["r_pre_eligible"] is False
    c4 = contracts[3]  # 冲突动作族 + 接触动作链 → 两阶段法
    assert c4["keyframe_source"] == "i2v_trajectory"
    assert c4["shot_size"] == "CU"  # DC-033 动作用近景
    # 状态链衔接
    assert contracts[1]["state_before"], "beat 有动作链应有 state_before"

    # 兼容 storyboard item 层（ShotSchemaV2 全字段）
    sb = ctx.payload["storyboard"]
    assert len(sb) == 6
    item = sb[1]
    for key in ("scene_id", "shot_id", "desc", "duration_s", "head_frame", "tail_frame",
                "ff_desc", "lf_desc", "motion_desc", "visual_desc", "variation_type",
                "state_before", "state_after", "subshots", "ff_vis_char_ids"):
        assert key in item, f"兼容字段缺失：{key}"
    assert item["head_frame"]["prompt"] and item["tail_frame"]["prompt"]
    assert item["head_frame"]["prompt"] != item["tail_frame"]["prompt"], "head/tail 应有 state 差异"
    assert item["head_frame"]["ratio"] == "9:16"
    assert 0.0 <= item["head_frame"]["subject_pos"]["x"] <= 1.0
    assert item["shot_type"] in ("远景", "全景", "中景", "近景", "特写")
    # 对白 beat → 音画同步
    assert sb[2]["audio_sync"] is True and sb[2]["audio_desc"]

    # 生成报告
    gen = ctx.payload["storyboard_generation"]
    assert gen["engine"] == "director_os_contract_v2"
    assert gen["input_mode"] == "script_document"
    assert gen["contract_report"]["r_pre_eligible"] >= 3
    assert "precheck" in gen

    # camera 链保留
    assert ctx.payload.get("camera_states")
    assert ctx.payload.get("camera_tree")


# ---------------------------------------------------------------- 容器模式（Wan [2,30] 整数秒 + subshots）
def test_run_contract_engine_container(monkeypatch):
    monkeypatch.setenv("DREAMWEAVER_STORYBOARD_MAX_SHOTS", "6")
    payload = {
        "script_document": _make_document(),
        "script_text": "（容器模式测试）",
        "quality_mode": "fast",
        "video_config": {"engine": "wan2.7-i2v"},
        "image_config": {"ratio": "16:9"},
    }
    ctx = _make_ctx(payload)
    from agents.storyboarder_pkg import run
    run(ctx)

    sb = ctx.payload["storyboard"]
    assert sb, "容器模式也应有 storyboard"
    for item in sb:
        # wan3.0-video 官方区间为 [2, 30] 整数秒：容器时长取整并落在区间内，不再吸附 5/10/15 离散档
        duration_s = float(item["duration_s"])
        assert duration_s == int(duration_s), f"容器时长应为整数秒，实际 {duration_s}"
        assert 2.0 <= duration_s <= 30.0, f"容器时长应落在官方区间，实际 {duration_s}"
        assert isinstance(item.get("subshots"), list)
        if item.get("subshots"):
            assert float(item["subshots"][0]["start_s"]) == 0.0
            assert abs(float(item["subshots"][-1]["end_s"]) - duration_s) < 1e-6, "子分镜必须覆盖整段容器"
    gen = ctx.payload["storyboard_generation"]
    assert gen["duration_rebalance"]


# ---------------------------------------------------------------- T3 预检：构造违规并验证自动修复
def test_precheck_fixes_optical_and_interference():
    from agents.storyboarder_pkg._precheck import precheck_contracts
    contracts = [
        {  # 显式覆盖广角 lens × 特写矛盾 + 快切×复杂运镜
            "shot_id": "shot_001", "scene_id": "S1", "beat_id": "S1-B1",
            "shot_size": "ECU", "lens": "24mm", "camera_movement": "establishing sweep 缓慢横移",
            "movement_model_lang": "slow lateral sweep", "movement_compliance": "中",
            "lighting": "侧向硬光", "lighting_compliance": "中",
            "duration_s": 1.2, "action": "伸手", "dialogue": [],
            "technique": "camera_movement", "family": "冲突动作族",
            "emotion": "angry", "visual_anchor": "x",
        },
        {  # EMOTION_STALL：>6s 情绪场景无增量
            "shot_id": "shot_002", "scene_id": "S1", "beat_id": "S1-B2",
            "shot_size": "MS", "camera_movement": "locked-off 固定机位",
            "movement_model_lang": "", "movement_compliance": "高",
            "lighting": "动机窗光", "lighting_compliance": "高",
            "duration_s": 8.0, "action": "", "dialogue": [],
            "technique": "performance", "family": "关系状态族",
            "emotion": "neutral", "visual_anchor": "y",
        },
    ]
    fixed, report = precheck_contracts(contracts)
    assert fixed[0]["lens"] == "100mm" or fixed[0]["lens"] == "85mm", "ECU 广角应修正焦距"
    assert fixed[0]["camera_movement"] == "locked-off 固定机位", "快切×复杂运镜应降级"
    assert fixed[1]["duration_s"] == 6.0, "EMOTION_STALL 应 trim 到 6s"
    assert report["auto_fixed"] >= 3
    assert "optical_consistency" in report["issue_types"]
    assert "emotion_stall" in report["issue_types"]


# ---------------------------------------------------------------- script_text 降级路径
def test_run_fallback_from_script_text():
    payload = {
        "script_text": (
            "## 概要\n- 测试\n## 分场\n### 场1 | 内景 | 客厅 | 日\n人物：\n- 甲\n节拍：\n- 甲走进客厅\n"
            "对白：\n- 甲：你来了\n视觉锚点：\n- 门口的光\n### 场2 | 外景 | 街道 | 夜\n节拍：\n- 甲离开"
        ),
        "quality_mode": "fast",
        "video_config": {"engine": "ffmpeg_slideshow"},
    }
    ctx = _make_ctx(payload)
    from agents.storyboarder_pkg import run
    run(ctx)
    gen = ctx.payload["storyboard_generation"]
    assert gen["input_mode"] == "script_text_fallback"
    assert ctx.payload["storyboard"], "降级路径也应有 storyboard"
    assert ctx.payload["shot_contracts"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
