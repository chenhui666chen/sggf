"""阶段 0 固定广告时间轴样例与四合同探针。

样例一经冻结不得改动（改样例 = 换输入版本，必须提升版本并重新验证）。
语法合同待实测确认，因此 canonical 之外的写法全部作为语法探针存在；
``TIMELINE_SYNTAX_CANONICAL`` 是当前假设的合法写法，实测结论可推翻它，
推翻时按进度文档记录决策变更并更新 canonical 指向。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

AD_SAMPLE_ID = "ad_timeline_fixed_v1"
AD_TOTAL_DURATION_S = 30.0

# 目标事件窗口（秒）。speech 事件参与台词对齐与 start/end 误差；
# event 事件参与 event_alignment_error_ms（以字幕/音频可观测区间为准）。
AD_TARGET_EVENTS: Tuple[Dict[str, Any], ...] = (
    {"id": "sfx_open", "kind": "event", "label": "键盘敲击与办公室环境声", "start_s": 0.0, "end_s": 2.0},
    {"id": "line_1", "kind": "speech", "speaker": "旁白", "text": "深夜加班，胃在抗议。", "start_s": 2.0, "end_s": 6.0},
    {"id": "sfx_pour", "kind": "event", "label": "热水冲泡声", "start_s": 6.0, "end_s": 8.0},
    {"id": "line_2", "kind": "speech", "speaker": "旁白", "text": "一杯温热，三分钟回到状态。", "start_s": 8.0, "end_s": 13.0},
    {"id": "music_lift", "kind": "event", "label": "背景音乐情绪上扬", "start_s": 13.0, "end_s": 16.0},
    {"id": "line_3", "kind": "speech", "speaker": "旁白", "text": "现在下单，第二件半价。", "start_s": 16.0, "end_s": 21.0},
    {"id": "music_out", "kind": "event", "label": "品牌音效收尾", "start_s": 21.0, "end_s": 30.0},
)

AD_EXPECTED_TEXTS = [
    event["text"] for event in AD_TARGET_EVENTS if event["kind"] == "speech"
]


def _fmt_seconds(value: float) -> str:
    return f"{value:.1f}"


def _fmt_ms(value: float) -> str:
    return str(int(round(value * 1000)))


def _fmt_cn(value: float) -> str:
    return f"{value:.1f}秒"


# 语法变体：start/end 数值格式化函数 + 分隔符 + 括号内外写法。
# canonical：官方示例中出现的 [2.7s:5.7s] 写法。
TIMELINE_SYNTAX_CANONICAL = "seconds_s"
TIMELINE_SYNTAX_VARIANTS: Dict[str, Dict[str, Any]] = {
    "seconds_s": {
        "description": "[2.0s:6.0s] 秒数带 s 后缀，半角冒号",
        "window": lambda start, end: f"[{_fmt_seconds(start)}s:{_fmt_seconds(end)}s]",
    },
    "milliseconds": {
        "description": "[2000ms:6000ms] 毫秒单位",
        "window": lambda start, end: f"[{_fmt_ms(start)}ms:{_fmt_ms(end)}ms]",
    },
    "seconds_cn": {
        "description": "[2.0秒:6.0秒] 中文单位",
        "window": lambda start, end: f"[{_fmt_cn(start)}:{_fmt_cn(end)}]",
    },
    "fullwidth_colon": {
        "description": "[2.0s：6.0s] 全角冒号（中文标点干扰）",
        "window": lambda start, end: f"[{_fmt_seconds(start)}s：{_fmt_seconds(end)}s]",
    },
    "spaced": {
        "description": "[ 2.0s : 6.0s ] 括号内含空格",
        "window": lambda start, end: f"[ {_fmt_seconds(start)}s : {_fmt_seconds(end)}s ]",
    },
}


def render_window(start_s: float, end_s: float, syntax: str = TIMELINE_SYNTAX_CANONICAL) -> str:
    try:
        variant = TIMELINE_SYNTAX_VARIANTS[syntax]
    except KeyError:
        raise ValueError(f"unknown timeline syntax variant: {syntax}") from None
    renderer: Callable[[float, float], str] = variant["window"]
    return renderer(start_s, end_s)


def _event_line(event: Dict[str, Any], syntax: str) -> str:
    window = render_window(event["start_s"], event["end_s"], syntax)
    if event["kind"] == "speech":
        return f'{window} {event["speaker"]}平静自然地说：“{event["text"]}”'
    return f'{window} {event["label"]}'


def build_timeline_prompt(
    syntax: str = TIMELINE_SYNTAX_CANONICAL,
    *,
    events: Tuple[Dict[str, Any], ...] = AD_TARGET_EVENTS,
    total_duration_s: float = AD_TOTAL_DURATION_S,
) -> str:
    """渲染固定广告样例 Prompt；事件与总时长可被边界/失败探针替换。"""
    header = (
        "一支30秒的养生冲饮广告。旁白 是温和、干净的中年女性声音。"
        "严格朗读引号中的原文，不新增、删减或改写台词。"
        f"整段音频总时长约 {_fmt_seconds(total_duration_s)} 秒。"
        "以下时间标记规定每个声音事件的出现区间，请严格遵守。"
    )
    lines = [header, ""]
    lines.extend(_event_line(event, syntax) for event in events)
    return "\n".join(lines) + "\n"


def _speech_event(start_s: float, end_s: float, text: str) -> Dict[str, Any]:
    return {
        "id": f"probe_{start_s}_{end_s}",
        "kind": "speech",
        "speaker": "旁白",
        "text": text,
        "start_s": start_s,
        "end_s": end_s,
    }


def build_syntax_probes() -> List[Dict[str, Any]]:
    """语法合同探针：同一广告样例按不同时间轴写法各生成一次。"""
    return [
        {
            "probe_id": f"syntax_{syntax}",
            "contract": "syntax",
            "description": variant["description"],
            "prompt": build_timeline_prompt(syntax),
            "expected_behavior": "记录请求是否被拒绝、时间轴是否被遵循或被忽略",
        }
        for syntax, variant in TIMELINE_SYNTAX_VARIANTS.items()
    ]


def build_boundary_probes() -> List[Dict[str, Any]]:
    """边界合同探针：最小窗、超总时长、越界、重叠。"""
    probes: List[Dict[str, Any]] = []

    narrow = (_speech_event(2.0, 2.4, "深夜加班，胃在抗议。"),)
    probes.append({
        "probe_id": "boundary_min_window",
        "contract": "boundary",
        "description": "0.4 秒极小时间窗朗读完整句子",
        "prompt": build_timeline_prompt(events=narrow),
        "expected_behavior": "记录是否拒绝、扩窗、忽略窗口或截断台词",
    })

    overflow = (
        _speech_event(100.0, 150.0, "深夜加班，胃在抗议。"),
    )
    probes.append({
        "probe_id": "boundary_over_120s_window",
        "contract": "boundary",
        "description": "单事件窗口跨越 120 秒输出上限",
        "prompt": build_timeline_prompt(events=overflow, total_duration_s=150.0),
        "expected_behavior": "记录是否拒绝或按 120 秒上限截断",
    })

    out_of_range = (
        _speech_event(45.0, 52.0, "深夜加班，胃在抗议。"),
    )
    probes.append({
        "probe_id": "boundary_window_beyond_total",
        "contract": "boundary",
        "description": "事件窗口超出声明总时长（声明 30 秒，窗口 45-52 秒）",
        "prompt": build_timeline_prompt(events=out_of_range),
        "expected_behavior": "记录是否拒绝、顺延、忽略或生成异常音频",
    })

    overlapping = (
        _speech_event(2.0, 10.0, "深夜加班，胃在抗议。"),
        _speech_event(6.0, 14.0, "一杯温热，三分钟回到状态。"),
    )
    probes.append({
        "probe_id": "boundary_overlapping_windows",
        "contract": "boundary",
        "description": "两个台词窗口重叠 4 秒",
        "prompt": build_timeline_prompt(events=overlapping),
        "expected_behavior": "记录是否拒绝、自动避让、重叠朗读或丢弃事件",
    })
    return probes


def build_failure_probes() -> List[Dict[str, Any]]:
    """失败行为探针：非法时间轴输入。"""

    def _inverted_prompt() -> str:
        header = (
            "一支30秒的养生冲饮广告。旁白 是温和、干净的中年女性声音。"
            "严格朗读引号中的原文，不新增、删减或改写台词。"
            f"整段音频总时长约 {_fmt_seconds(AD_TOTAL_DURATION_S)} 秒。"
            "以下时间标记规定每个声音事件的出现区间，请严格遵守。"
        )
        return (
            f"{header}\n\n"
            "[10.0s:4.0s] 热水冲泡声\n"
            "[15.0s:20.0s] 旁白平静自然地说：“深夜加班，胃在抗议。”\n"
        )

    def _non_numeric_prompt() -> str:
        header = (
            "一支30秒的养生冲饮广告。旁白 是温和、干净的中年女性声音。"
            "严格朗读引号中的原文，不新增、删减或改写台词。"
            f"整段音频总时长约 {_fmt_seconds(AD_TOTAL_DURATION_S)} 秒。"
            "以下时间标记规定每个声音事件的出现区间，请严格遵守。"
        )
        return (
            f"{header}\n\n"
            "[快开始:慢结束] 旁白平静自然地说：“深夜加班，胃在抗议。”\n"
        )

    return [
        {
            "probe_id": "failure_inverted_window",
            "contract": "failure",
            "description": "窗口起止颠倒（end < start）",
            "prompt": _inverted_prompt(),
            "expected_behavior": "区分请求失败 / 模型忽略 / 自动修正 / 生成异常音频",
        },
        {
            "probe_id": "failure_non_numeric_window",
            "contract": "failure",
            "description": "窗口为非数值文本",
            "prompt": _non_numeric_prompt(),
            "expected_behavior": "区分请求失败 / 模型忽略 / 自动修正 / 生成异常音频",
        },
        {
            "probe_id": "failure_empty_events",
            "contract": "failure",
            "description": "只有时间轴声明、没有任何事件",
            "prompt": build_timeline_prompt(events=()),
            "expected_behavior": "记录是否拒绝或生成无内容音频",
        },
    ]


def ad_compliance_target() -> Dict[str, Any]:
    """遵循精度主样例：固定广告 + canonical 语法 + 目标窗口。"""
    return {
        "sample_id": AD_SAMPLE_ID,
        "contract": "compliance",
        "prompt": build_timeline_prompt(TIMELINE_SYNTAX_CANONICAL),
        "events": AD_TARGET_EVENTS,
        "expected_texts": list(AD_EXPECTED_TEXTS),
        "total_duration_s": AD_TOTAL_DURATION_S,
    }
