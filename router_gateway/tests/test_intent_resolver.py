# -*- coding: utf-8 -*-
"""意图模式三级仲裁测试：显式 mode → 素材结构规则 → 歧义时分类器（保守兜底）。

六类不可互换的输入模式（docs/VIDEO_API_SMART_ROUTING_GUIDE.md）：
text / first_last_frame / multi_image / video_reference /
image_audio_lipsync / mixed_multimodal
"""
import pytest

from router_gateway.catalog import Mode
from router_gateway.catalog.intent import (
    IntentError,
    ModeDecision,
    ResolvedIntent,
    resolve_mode,
)


class _ScriptedClassifier:
    """按调用顺序返回预设结果的假分类器；记录调用参数。"""

    def __init__(self, *results, raises=False):
        self._results = list(results)
        self._raises = raises
        self.calls = []

    def classify_mode(self, prompt, *, image_count, candidates):
        self.calls.append({"prompt": prompt, "image_count": image_count,
                           "candidates": candidates})
        if self._raises:
            raise RuntimeError("decision model unavailable")
        return self._results.pop(0)


def _resolve(**over):
    base = dict(prompt="一段测试提示词", image_count=0, video_count=0,
                audio_count=0, explicit=None, classifier=None,
                confidence_threshold=0.6)
    base.update(over)
    return resolve_mode(**base)


# ---------- 第二顺位：素材结构确定性规则 ----------

def test_无素材确定性判文生():
    out = _resolve()
    assert out == ResolvedIntent(mode=Mode.TEXT, source="rule", confidence=None)


def test_单张图按多图参考处理():
    # 事实收紧：三家上游均无"单首帧"工作流（AutoDL 首尾帧必须两张），
    # 1 图不存在模式歧义，直接归多图参考，不调用分类器。
    out = _resolve(image_count=1)
    assert out.mode == Mode.MULTI_IMAGE and out.source == "rule"


def test_三张及以上判多图参考():
    assert _resolve(image_count=3).mode == Mode.MULTI_IMAGE
    assert _resolve(image_count=9).mode == Mode.MULTI_IMAGE


def test_图加音频判对口型():
    # 唯一保留的对口型结构：恰好 1 图 1 音、无视频
    out = _resolve(image_count=1, audio_count=1)
    assert out.mode == Mode.IMAGE_AUDIO_LIPSYNC and out.source == "rule"


def test_多图多音叙事混轨判混合多模态_而非对口型():
    # wan3 实测场景：10图+5音（三宝 once / 004 按次）是叙事混轨，不是对口型
    out = _resolve(image_count=10, audio_count=5)
    assert out.mode == Mode.MIXED_MULTIMODAL and out.source == "rule"


def test_两图加音频判混合多模态():
    out = _resolve(image_count=2, audio_count=1)
    assert out.mode == Mode.MIXED_MULTIMODAL and out.source == "rule"


def test_单图多音频判混合多模态():
    out = _resolve(image_count=1, audio_count=2)
    assert out.mode == Mode.MIXED_MULTIMODAL and out.source == "rule"


def test_图视音全槽位判混合多模态():
    # J3/J5/J14 实证：10图+3参考视频+3音频一单
    out = _resolve(image_count=10, video_count=3, audio_count=3)
    assert out.mode == Mode.MIXED_MULTIMODAL and out.source == "rule"


def test_视频加音频无图判混合多模态():
    # 贰春目录明确 audio_requires_image_or_video=false，音频可只配参考视频
    out = _resolve(video_count=1, audio_count=1)
    assert out.mode == Mode.MIXED_MULTIMODAL and out.source == "rule"


def test_参考视频判视频参考生():
    out = _resolve(video_count=1)
    assert out.mode == Mode.VIDEO_REFERENCE and out.source == "rule"


def test_图加视频无音频仍判视频参考():
    out = _resolve(image_count=3, video_count=2)
    assert out.mode == Mode.VIDEO_REFERENCE and out.source == "rule"


def test_有音频无图且无视频属矛盾请求():
    with pytest.raises(IntentError, match="audio"):
        _resolve(audio_count=1)


# ---------- 唯一歧义点：2 张图（首尾帧 vs 双图参考） ----------

def test_两图无分类器保守按多图参考():
    out = _resolve(image_count=2)
    assert out == ResolvedIntent(mode=Mode.MULTI_IMAGE, source="fallback",
                                 confidence=None)


def test_两图分类器高置信采纳首尾帧():
    clf = _ScriptedClassifier(ModeDecision(Mode.FIRST_LAST_FRAME, 0.91))
    out = _resolve(image_count=2, classifier=clf)
    assert out.mode == Mode.FIRST_LAST_FRAME
    assert out.source == "classifier" and out.confidence == pytest.approx(0.91)
    assert clf.calls[0]["candidates"] == (Mode.FIRST_LAST_FRAME, Mode.MULTI_IMAGE)


def test_两图分类器低置信走保守默认():
    clf = _ScriptedClassifier(ModeDecision(Mode.FIRST_LAST_FRAME, 0.55))
    out = _resolve(image_count=2, classifier=clf)
    assert out.mode == Mode.MULTI_IMAGE and out.source == "fallback"
    assert out.confidence == pytest.approx(0.55)


def test_两图分类器返回候选集外模式不采纳():
    clf = _ScriptedClassifier(ModeDecision(Mode.TEXT, 0.99))
    out = _resolve(image_count=2, classifier=clf)
    assert out.mode == Mode.MULTI_IMAGE and out.source == "fallback"


def test_两图分类器故障不阻断主链路():
    clf = _ScriptedClassifier(raises=True)
    out = _resolve(image_count=2, classifier=clf)
    assert out.mode == Mode.MULTI_IMAGE and out.source == "fallback"


def test_非歧义请求不调用分类器():
    clf = _ScriptedClassifier(ModeDecision(Mode.FIRST_LAST_FRAME, 0.99))
    _resolve(image_count=3, classifier=clf)
    _resolve(classifier=clf)
    assert clf.calls == []


# ---------- 第一顺位：显式 mode（含与素材的矛盾校验） ----------

def test_显式首尾帧且素材一致():
    out = _resolve(image_count=2, explicit="first_last_frame")
    assert out.mode == Mode.FIRST_LAST_FRAME and out.source == "explicit"


def test_显式模式直接接受枚举():
    out = _resolve(image_count=2, explicit=Mode.FIRST_LAST_FRAME)
    assert out.source == "explicit"


def test_显式文生却带素材直接拒绝():
    with pytest.raises(IntentError, match="text"):
        _resolve(image_count=1, explicit="text")


def test_显式首尾帧但图数不是两张拒绝():
    with pytest.raises(IntentError, match="first_last_frame"):
        _resolve(image_count=1, explicit="first_last_frame")


def test_显式多图但无图拒绝():
    with pytest.raises(IntentError, match="multi_image"):
        _resolve(explicit="multi_image")


def test_显式视频参考但无视频拒绝():
    with pytest.raises(IntentError, match="video_reference"):
        _resolve(explicit="video_reference")


def test_显式对口型但缺音频或缺图拒绝():
    with pytest.raises(IntentError):
        _resolve(image_count=1, explicit="image_audio_lipsync")
    with pytest.raises(IntentError):
        _resolve(audio_count=1, explicit="image_audio_lipsync")


def test_显式非法模式名拒绝():
    with pytest.raises(IntentError, match="unknown_mode"):
        _resolve(explicit="img2video")


# ---------- 第六模式：mixed_multimodal 多素材混合叙事 ----------

def test_显式混合模式带任意素材组合接受():
    assert _resolve(image_count=10, video_count=3, audio_count=3,
                    explicit="mixed_multimodal").source == "explicit"
    assert _resolve(image_count=6, audio_count=3,
                    explicit="mixed_multimodal").mode == Mode.MIXED_MULTIMODAL
    assert _resolve(video_count=2, audio_count=1,
                    explicit="mixed_multimodal").mode == Mode.MIXED_MULTIMODAL


def test_显式混合模式但无任何素材拒绝():
    with pytest.raises(IntentError, match="mixed_multimodal"):
        _resolve(explicit="mixed_multimodal")


def test_显式对口型仍接受多图多音_显式意图优先():
    # 显式 mode 代表调用方明确意图，结构合法即接受，不强制走自动仲裁
    with pytest.raises(IntentError, match="image_audio_lipsync"):
        _resolve(image_count=10, audio_count=5,
                 explicit="image_audio_lipsync")
