"""LLM 输出上限对账探测（只读上游，不改任何配置）。

用途：`config/llm_models.yaml` 的 `constraints.max_output_tokens` / `max_thinking_tokens`
很容易在换代时停留在上一代的取值（中性内部 ID 让这件事没有任何提醒）。本脚本用
**越界探测**拿上游回显的真实上限，与档案对账：

    python scripts/probe_llm_output_limits.py            # 人读表格
    python scripts/probe_llm_output_limits.py --json     # 给门禁/脚本消费
    python scripts/probe_llm_output_limits.py --id glm   # 只测一个

退出码：漂移=1（档案与实测不符，必须改档案）；无漂移但存在"未探到"=2（这些条目根本没验证过，
不算通过，要么补 SKIP_REASONS 登记并说明理由，要么修档案）；全部一致=0。
因此可以挂进接入流程当证据门禁。

安全：只引用环境变量名，绝不打印 key 值；探测请求刻意让上游在**参数校验阶段**拒绝，
不产生任何生成开销。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_MODELS_YAML = PROJECT_ROOT / "config" / "llm_models.yaml"

# 越界值：高于本项目所有文本模型的真实上限，且在各家 int 范围内
OVER_LIMIT = 999_999

# 刻意跳过的条目 -> 原因（这些条目「无法用越界探测拿回显」，不是漏测）
SKIP_REASONS = {
    # 2026-10-08 实测：网关对 max_tokens 完全不校验（262145/1048577 都返回 200），
    # 且思考不可关闭，越界请求会真的跑满预算产生费用；档案值是有意的保守值。
    "kimi-preview": "上游不校验 max_tokens，无法探测；档案为有意保守值",
    # 2026-10-08 已由越界探测确认 393216 / 384000，无需重复付费
    "deepseek-flash": "2026-10-08 已实测确认",
    "deepseek-pro": "2026-10-08 已实测确认",
    # 2026-10-09 实测：StepFun 网关对 max_tokens=999999 返回 200（不校验），本法定不了界
    "step-preview": "上游不校验 max_tokens，越界请求不被拒，无法用本法定位；档案值取官方文档",
}

# 各家报错文案里的上限数字（按精确度排序，越具体的写法越靠前）
LIMIT_PATTERNS = (
    # 阿里百炼：Range of max_tokens should be [1, 131072]
    r"Range of max_tokens should be \[1,\s*(\d+)\]",
    # 火山方舟：integer above maximum value, expected a value <= 262144
    r"expected a value <=\s*(\d+)",
    # 小米 MiMo：max_tokens is too large: 999999. This model supports at most 131072 completion tokens
    r"supports at most (\d+) completion tokens",
    # MiniMax（经百炼网关）：model[...] does not support max tokens > 524288
    r"max[\s_]?tokens\s*>\s*(\d+)",
    # 阿里百炼思考预算：The thinking_budget parameter must be a positive integer and not greater than 131072
    r"thinking_budget[^\d]{0,80}?(\d+)",
    r"must be less than or equal to (\d+)",
    r"maximum[^\d]{0,20}(\d{3,})",
)

# 上游把参数组合本身判非法（而非 max_tokens 越界），需要换一种发法重试
PARAM_COMBINATION_PATTERNS = (
    r"enable_thinking",
    r"reasoning_effort",
    r"thinking_budget",
)


@dataclass
class ProbeResult:
    model_id: str
    request_model: str
    channel: str
    archived_output: Optional[int]
    probed_output: Optional[int] = None
    archived_thinking: Optional[int] = None
    probed_thinking: Optional[int] = None
    raw_output: str = ""
    raw_thinking: str = ""
    notes: list[str] = field(default_factory=list)
    intentional_skip: bool = False

    @property
    def output_drift(self) -> bool:
        return self.probed_output is not None and self.archived_output != self.probed_output

    @property
    def thinking_drift(self) -> bool:
        return self.probed_thinking is not None and self.archived_thinking != self.probed_thinking

    @property
    def unprobed(self) -> bool:
        """没拿到实测值、又不属于登记过的"不可探测"，即真实漏测（缺 key、文案没解析出来等）。"""
        return self.probed_output is None and not self.intentional_skip


def _parse_limit(message: str) -> Optional[int]:
    for pattern in LIMIT_PATTERNS:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            # 上游会把我们传的越界值原样回显，抓到它等于没抓到真上限
            if value == OVER_LIMIT:
                continue
            return value
    return None


def _is_param_combination_error(message: str) -> bool:
    """判断这次 400 是在拒参数组合，而不是在报 max_tokens 越界。"""
    if _parse_limit(message) is not None:
        return False
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in PARAM_COMBINATION_PATTERNS)


def _entries() -> list[dict[str, Any]]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return payload["llm_models"]


def _thinking_disabled(model_id: str) -> dict[str, Any]:
    from core.model_resolution import build_thinking_disabled_extra_body

    return build_thinking_disabled_extra_body(model_id)


def _over_limit_message(client, request_model: str, extra_body: dict[str, Any], kind: str,
                        *, send_extra_body: bool = True) -> str:
    """发一个越界请求，把上游回显文本原样拿回来（越界被拒时不产生生成费用）。

    send_extra_body=False 用于强制思考的模型（如 glm 线：enable_thinking 只允许 True），
    这类模型收到关思考参数会在 max_tokens 校验之前就报错。
    """
    kwargs: dict[str, Any] = {
        "model": request_model,
        "messages": [{"role": "user", "content": "只回复：OK"}],
        "timeout": 60,
    }
    if send_extra_body:
        kwargs["extra_body"] = extra_body
    if kind == "output":
        kwargs["max_tokens"] = OVER_LIMIT
    else:
        # thinking_budget 在思考关闭时会被上游直接忽略（实测：关思考 + 越界 budget 返回 200），
        # 因此探测思考上限必须显式开启思考；各家开关字段不同，这里并存由各家用自己认的那个
        kwargs["max_tokens"] = 64
        kwargs["extra_body"] = {
            "enable_thinking": True,
            "thinking": {"type": "enabled"},
            "thinking_budget": OVER_LIMIT,
        }
    try:
        client.chat.completions.create(**kwargs)
        return ""
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _probe_with_fallback(client, request_model: str, extra_body: dict[str, Any],
                         kind: str, result: ProbeResult) -> str:
    """优先带关思考参数探测输出上限；被拒在参数组合上时，去掉关思考参数再探一次。

    仅对 output 探测做兜底：thinking 探测本身就要求开启思考，重试同一种发法没有意义。
    """
    message = _over_limit_message(client, request_model, extra_body, kind)
    if kind == "output" and message and _is_param_combination_error(message):
        result.notes.append("output: 上游拒收关思考参数，改按默认思考配置重探")
        message = _over_limit_message(client, request_model, extra_body, kind, send_extra_body=False)
    return message


def probe_entry(entry: dict[str, Any]) -> ProbeResult:
    api_config = entry["api_config"]
    constraints = entry["constraints"]
    request_model = (entry.get("default_params") or {}).get("request_model") or entry["id"]
    key_env = api_config["api_key_env"]
    result = ProbeResult(
        model_id=entry["id"],
        request_model=str(request_model),
        channel=key_env,
        archived_output=constraints.get("max_output_tokens"),
        archived_thinking=constraints.get("max_thinking_tokens"),
    )

    api_key = os.getenv(key_env, "").strip()
    if not api_key:
        result.notes.append(f"未配置 {key_env}，跳过")
        return result

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=api_config["base_url"], max_retries=0)
    extra_body = _thinking_disabled(entry["id"])

    result.raw_output = _probe_with_fallback(client, result.request_model, extra_body, "output", result)
    if result.raw_output:
        result.probed_output = _parse_limit(result.raw_output)
    else:
        result.notes.append("越界请求未被拒（上游不校验该参数）")

    # 仅对档案声明了思考预算上限的条目探测，避免给不支持思考的通道发无效参数
    if constraints.get("max_thinking_tokens"):
        result.raw_thinking = _probe_with_fallback(client, result.request_model, extra_body, "thinking", result)
        if result.raw_thinking:
            result.probed_thinking = _parse_limit(result.raw_thinking)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM 输出上限对账探测")
    parser.add_argument("--id", action="append", dest="ids", help="只探测指定 model_id，可重复")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--include-skipped", action="store_true", help="连刻意跳过的条目一起报状态")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    sys.path.insert(0, str(PROJECT_ROOT))

    rows: list[ProbeResult] = []
    for entry in _entries():
        model_id = entry["id"]
        if args.ids and model_id not in args.ids:
            continue
        if model_id in SKIP_REASONS and not args.include_skipped:
            continue
        if model_id in SKIP_REASONS and args.include_skipped:
            rows.append(ProbeResult(
                model_id=model_id,
                request_model=str((entry.get("default_params") or {}).get("request_model") or model_id),
                channel=entry["api_config"]["api_key_env"],
                archived_output=entry["constraints"].get("max_output_tokens"),
                archived_thinking=entry["constraints"].get("max_thinking_tokens"),
                notes=[f"跳过：{SKIP_REASONS[model_id]}"],
                intentional_skip=True,
            ))
            continue
        rows.append(probe_entry(entry))

    drift = [r for r in rows if r.output_drift or r.thinking_drift]
    unprobed = [r for r in rows if r.unprobed]
    exit_code = 1 if drift else (2 if unprobed else 0)

    if args.json:
        print(json.dumps([
            {
                "model_id": r.model_id,
                "request_model": r.request_model,
                "archived_max_output_tokens": r.archived_output,
                "probed_max_output_tokens": r.probed_output,
                "archived_max_thinking_tokens": r.archived_thinking,
                "probed_max_thinking_tokens": r.probed_thinking,
                "intentional_skip": r.intentional_skip,
                "notes": r.notes,
                "echo_output": r.raw_output[:240],
                "echo_thinking": r.raw_thinking[:240],
            }
            for r in rows
        ], ensure_ascii=False, indent=2))
        return exit_code

    print(f"{'id':22} {'上游名':26} {'档案out':>9} {'实测out':>9} {'档案think':>10} {'实测think':>10}  结论")
    for r in rows:
        verdict = "漂移" if (r.output_drift or r.thinking_drift) else ("未探到" if not r.probed_output else "一致")
        if r.notes and not r.probed_output:
            verdict = f"{verdict}（{r.notes[0]}）"
        print(f"{r.model_id:22} {r.request_model:26} {str(r.archived_output):>9} {str(r.probed_output):>9} "
              f"{str(r.archived_thinking):>10} {str(r.probed_thinking):>10}  {verdict}")
        if r.output_drift or r.thinking_drift:
            print(f"    回显: {(r.raw_output or r.raw_thinking)[:200]}")
    print(f"\n合计 {len(rows)} 条，漂移 {len(drift)} 条，未探到 {len(unprobed)} 条")
    if unprobed:
        print("未探到即视为未验证，不计入通过：" + ", ".join(r.model_id for r in unprobed))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
