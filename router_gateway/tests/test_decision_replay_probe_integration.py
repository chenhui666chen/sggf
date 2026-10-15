# -*- coding: utf-8 -*-
"""decision-model-preview 真云离线回放探针（默认 skip，不扣费风险但依赖凭证）。

开启方式（PowerShell）：
  $env:ROUTER_GATEWAY_RUN_DECISION_PROBE="1"
  $env:ROUTER_GATEWAY_DECISION_BASE_URL="https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode"
  $env:DASHSCOPE_API_KEY="..."
  python -m pytest router_gateway/tests/test_decision_replay_probe_integration.py -q -s

说明：
- 预览期输入 0 元/百万 token；探针只打印准确率报告，不修改任何主链路配置；
- 门槛见 docs 路由指南 §7.3：歧义分类 accuracy ≥ 0.95 才允许注入编排器，
  否则维持 resolve_mode 保守回退（multi_image）。
- 标注为人工判断，样本可继续扩充；断言只要求探针跑完，不强制门槛（取证而非卡 CI）。
"""
import os

import pytest

from router_gateway.catalog import Mode
from router_gateway.decision import DecisionModelClient
from router_gateway.decision.replay import ReplayCase, evaluate_classifier, evaluate_risk

pytestmark = pytest.mark.integration

# 2 图歧义标注集：明确的首尾帧指令 vs 多图参考指令
_CLASSIFIER_CASES = [
    ReplayCase("用第一张图作为视频开头画面，第二张图作为结尾画面，补全中间的运动过程",
               Mode.FIRST_LAST_FRAME),
    ReplayCase("首帧和尾帧已经给好，生成两张图之间的过渡视频", Mode.FIRST_LAST_FRAME),
    ReplayCase("从第一张图的场景平滑演变到第二张图的场景", Mode.FIRST_LAST_FRAME),
    ReplayCase("参考这两张图的画风和色调生成一段视频，不要限定开头结尾", Mode.MULTI_IMAGE),
    ReplayCase("根据这两张参考图里的角色形象生成角色走动的视频", Mode.MULTI_IMAGE),
    ReplayCase("融合两张图中的场景元素做一个氛围镜头", Mode.MULTI_IMAGE),
    ReplayCase("以图一为起点图二为终点做运镜", Mode.FIRST_LAST_FRAME),
    ReplayCase("这两张图是造型参考，生成同款角色在街道上奔跑的画面", Mode.MULTI_IMAGE),
]

_RISK_CASES = [
    ReplayCase("雪山日出航拍，电影级画质，镜头缓慢推进", False),
    ReplayCase("咖啡馆窗边，女孩安静看书，暖色调", False),
    ReplayCase("赛博朋克城市夜景，霓虹灯下雨后的街道", False),
]


def _client() -> DecisionModelClient:
    if os.getenv("ROUTER_GATEWAY_RUN_DECISION_PROBE") != "1":
        pytest.skip("未设置 ROUTER_GATEWAY_RUN_DECISION_PROBE=1")
    base_url = os.getenv("ROUTER_GATEWAY_DECISION_BASE_URL", "").strip()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not base_url or not api_key:
        pytest.skip("缺少 ROUTER_GATEWAY_DECISION_BASE_URL / DASHSCOPE_API_KEY")
    return DecisionModelClient(base_url=base_url, api_key=api_key)


def test_歧义分类真云回放报告():
    report = evaluate_classifier(_client(), _CLASSIFIER_CASES)
    print(f"\n[歧义分类] accuracy={report['accuracy']:.2%} "
          f"({report['correct']}/{report['total']}) gate=0.95 "
          f"passed={report['threshold_passed']}")
    for item in report["items"]:
        flag = "OK " if item["correct"] else "ERR"
        print(f"  {flag} exp={item['expected']:<18} pred={item['predicted']} "
              f"conf={item['confidence']} | {item['name']}"
              + (f" | {item['error']}" if item["error"] else ""))
    assert report["total"] == len(_CLASSIFIER_CASES)


def test_违规风险真云回放报告():
    report = evaluate_risk(_client(), _RISK_CASES)
    print(f"\n[违规风险] accuracy={report['accuracy']:.2%} "
          f"({report['correct']}/{report['total']})")
    for item in report["items"]:
        print(f"  score={item['score']} exp_risky={item['expected']} | {item['name']}"
              + (f" | {item['error']}" if item["error"] else ""))
    assert report["total"] == len(_RISK_CASES)
