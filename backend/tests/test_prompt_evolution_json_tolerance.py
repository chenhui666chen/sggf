# -*- coding: utf-8 -*-
"""P17-3 守卫：语义评审 JSON 解析必须容忍三类真实失败。

## 取证（本轮 80 个真实样本，非构造）

失败率 4/80 = 5%，三类成因逐字摘自日志：

1. `语义评审返回无效: semantic_fidelity不是对象`
   —— 模型把 `{"score":92,...}` 写成了裸数字 92（或漏了外层对象）。
2. `语义评审返回无效: Expecting ',' delimiter: line 65 column 32 (char 2336)`
   —— 输出很长（65 行），某处少了逗号。这是深层语法错误。
3. `语义评审返回无效: Invalid control character at: line 4 column 242 (char 285)`
   —— 正文里混入了裸控制字符（模型把换行/制表直接写进 JSON 字符串）。

## 为什么必须修

这三种失败的共同后果不是「评审略过一个样本」，而是
`_unavailable()` ⇒ `available=False` ⇒ evaluator 判 `success=False`
⇒ 计入版本失格数 ⇒ P15 的质量层键被基础设施噪声推高。

P16 真实轮次即受影响：4 个版本里 3 个失格率 50%，而其中确有评审解析
失败导致的失格（failure_kind=`review_unavailable`，实测 1 次）。

**这属于「用基础设施故障冒充质量缺陷」**，与 P17-1、P17-2 同源。

## 修法边界

只增强**解析容错**，不改评分口径、不放宽任何阈值：
- 控制字符 → 清洗后重试（JSON 规范不允许裸控制字符，属可无损修复）
- 缺逗号等浅层语法错 → 有限重试（模型偶发，少量重试即可）
- 维度值是裸数字 → 规范化成 `{"score": n}`（模型漏外层对象的常见写法）
- 仍失败 → 保持原有 `_unavailable` 路径，不得静默给高分
"""
import json

from app.services.prompt_evolution.semantic_judge import SemanticJudge


FULL = {
    "semantic_fidelity": {"score": 92, "reason": "断言等价", "issues": []},
    "fact_consistency": {"score": 94, "reason": "事实一致", "issues": []},
    "information_completeness": {"score": 90, "reason": "", "issues": []},
    "readability": {"score": 91, "reason": "", "issues": []},
    "writing_naturalness": {"score": 90, "reason": "", "issues": []},
    "genre_consistency": {"score": 93, "reason": "", "issues": []},
    "over_rewrite_risk": {"level": "low", "reason": "", "issues": []},
    "confidence": 0.9,
}


def _json(**overrides):
    d = json.loads(json.dumps(FULL))
    d.update(overrides)
    return json.dumps(d, ensure_ascii=False)


class TestControlCharacterTolerance:
    """成因 3：JSON 字符串里混入裸控制字符。"""

    def test_raw_newline_in_string_is_recovered(self):
        bad = _json().replace("断言等价", "断言\n等价")
        out = SemanticJudge._parse_json(bad)
        assert out["semantic_fidelity"]["score"] == 92

    def test_raw_tab_is_recovered(self):
        bad = _json().replace("事实一致", "事实\t一致")
        out = SemanticJudge._parse_json(bad)
        assert out["fact_consistency"]["score"] == 94

    def test_control_chars_inside_issues_array(self):
        d = json.loads(_json())
        d["fact_consistency"]["issues"] = ["原文A\n候选B\rc"]
        bad = json.dumps(d, ensure_ascii=False)  # ensure_ascii 不转义这些
        out = SemanticJudge._parse_json(bad)
        assert out["fact_consistency"]["issues"]


class TestBareScoreNormalization:
    """成因 1：维度值写成裸数字而非 {"score": n}。"""

    def test_bare_int_becomes_score_object(self):
        payload = {
            "semantic_fidelity": 92,
            "fact_consistency": 94,
            "information_completeness": 90,
            "readability": 91,
            "writing_naturalness": 90,
            "genre_consistency": 93,
            "over_rewrite_risk": "low",
            "confidence": 0.9,
        }
        out = SemanticJudge._parse_json(json.dumps(payload, ensure_ascii=False))
        # 规范化后的形状：裸数字被补成 {"score": n}
        assert out["semantic_fidelity"] == {"score": 92, "reason": "", "issues": []}
        # 规范化后必须能被 _normalize 直接消费
        norm = SemanticJudge._normalize(out)
        assert norm["available"] is True
        assert norm["fact_consistency"]["score"] == 94

    def test_bare_float_becomes_score_object(self):
        payload = dict(FULL)
        payload["fact_consistency"] = 88.5
        out = SemanticJudge._parse_json(json.dumps(payload, ensure_ascii=False))
        assert out["fact_consistency"] == {"score": 88.5, "reason": "", "issues": []}
        norm = SemanticJudge._normalize(out)
        assert norm["fact_consistency"]["score"] == 88.5

    def test_risk_bare_string_becomes_object(self):
        payload = dict(FULL)
        payload["over_rewrite_risk"] = "low"
        norm = SemanticJudge._normalize(SemanticJudge._parse_json(
            json.dumps(payload, ensure_ascii=False)))
        assert norm["over_rewrite_risk"] == "low"


class TestShallowSyntaxTolerance:
    def test_markdown_fence_still_supported(self):
        """既有能力不得回退。"""
        fenced = "```json\n" + _json() + "\n```"
        assert SemanticJudge._parse_json(fenced)["confidence"] == 0.9

    def test_leading_prose_is_stripped(self):
        noisy = "好的，我的评价如下：\n" + _json()
        assert SemanticJudge._parse_json(noisy)["confidence"] == 0.9

    def test_trailing_prose_is_stripped(self):
        noisy = _json() + "\n以上就是我的分析。"
        assert SemanticJudge._parse_json(noisy)["confidence"] == 0.9


class TestExtraDataTolerance:
    """🔧 2026-10-17 真实轮次补充：P18 实测出现 `Extra data` 失败（P17-3 首版漏判）。

    真实日志：`提示词进化语义评审返回无效: Extra data: line 9 column 1 (char 329)`
    出现在 72 个样本的第 57、73 个上。

    根因：P17-3 首版用 `find("{") ... rfind("}")` 剥离前后杂文。
    但当响应是**连续两个 JSON 对象**（模型重复输出）时，
    `rfind("}")` 取到第二个对象的结尾 ⇒ 切片把两个对象都圈进来
    ⇒ 拼接后仍是 `Extra data`，比原来更糟（原来至少还能靠首段解析成功）。

    正确做法：从第一个 `{` 起逐字符做**花括号配对扫描**，
    取到配对闭合的那一段，而不是取最后一个 `}`。
    """

    def test_doubled_json_object_uses_first_complete_object(self):
        obj = json.dumps(FULL, ensure_ascii=False)
        out = SemanticJudge._parse_json(obj + "\n" + obj)
        assert out["confidence"] == 0.9

    def test_trailing_brace_does_not_swallow_previous_object(self):
        """对象后跟一个残缺花括号片段时，必须只取第一个完整对象。"""
        obj = json.dumps(FULL, ensure_ascii=False)
        out = SemanticJudge._parse_json(obj + " {备注")
        assert out["fact_consistency"]["score"] == 94

    def test_normal_single_object_still_works(self):
        """不能因新增扫描而破坏既有单对象路径。"""
        out = SemanticJudge._parse_json(json.dumps(FULL, ensure_ascii=False))
        assert out["genre_consistency"]["score"] == 93

    def test_extra_data_inside_string_is_not_mistaken_for_end(self):
        """字符串里的花括号不得被当成对象结束。"""
        payload = dict(FULL)
        payload["fact_consistency"] = {"score": 90, "reason": "出现了{大括号}但属正文", "issues": []}
        out = SemanticJudge._parse_json(json.dumps(payload, ensure_ascii=False))
        assert out["fact_consistency"]["score"] == 90


class TestStillFailsWhenItShould:
    """容错不得变成「什么都能过」——真正无效的响应必须仍被拒。

    注：`SemanticJudge._normalize` 保持「抛错」契约不变，由 `evaluate`
    的 try/except 统一转成 `_unavailable`（既有设计，见 evaluate:42-58）。
    因此这里断言的是「仍抛错」，而不是「返回 available=False」。
    """

    def test_non_string_raises(self):
        try:
            SemanticJudge._parse_json(123)
        except TypeError:
            return
        raise AssertionError("非字符串响应必须仍被拒")

    def test_root_not_object_raises(self):
        try:
            SemanticJudge._parse_json("[1, 2, 3]")
        except TypeError:
            return
        raise AssertionError("根节点非对象必须仍被拒")

    def test_missing_dimensions_still_raises(self):
        """结构完全不匹配时必须仍抛错（由 evaluate 转成不可用），
        不得凭空补满分 —— 那是把故障伪装成通过。"""
        try:
            SemanticJudge._normalize({"foo": "bar"})
        except (KeyError, TypeError):
            return
        raise AssertionError("缺维度必须仍抛错，不得静默补分")

    def test_out_of_range_score_still_rejected(self):
        """清洗后仍越界的分数必须仍被拒，不得被静默接受。"""
        payload = dict(FULL)
        payload["fact_consistency"] = {"score": 500, "reason": "", "issues": []}
        try:
            SemanticJudge._normalize(payload)
        except ValueError:
            return
        raise AssertionError("越界分数必须仍被拒")

    def test_broken_syntax_still_raises(self):
        """浅层语法错（如缺逗号）不在解析层容错范围，仍须抛错。"""
        broken = '{"semantic_fidelity": {"score": 92} "reason": "x"}'
        try:
            SemanticJudge._parse_json(broken)
        except json.JSONDecodeError:
            return
        raise AssertionError("缺逗号等语法错必须仍抛错")

    def test_unavailable_path_produces_no_scores(self):
        """_unavailable 不得携带任何维度分数（否则会被下游当成低分真值）。"""
        out = SemanticJudge._unavailable("测试")
        assert out["available"] is False
        assert not any(k in out for k in (
            "semantic_fidelity", "fact_consistency", "information_completeness"))
