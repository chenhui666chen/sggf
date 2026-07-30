"""Independent Seed Audio scene test catalog and render-plan builder."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.audiobook.scene_engine.models import SceneRenderPlan


SEED_SCENE_TEST_MODEL = "seed-audio-1.0"
SEED_SCENE_TEST_VARIANTS = ("described_voices", "reference_voices")
SEED_SCENE_TEST_REPEAT_COUNT = 3

_GLOBAL_CONSTRAINTS = (
    "对白始终清晰位于前景，音乐、环境声和动作音效不得遮挡人声。"
    "严格朗读引号中的原文，不新增、删减或改写台词，不产生未声明的可辨识人声。"
)
_REFERENCE_IDENTITY_CONSTRAINT = (
    "所有绑定参考的角色，其音色、口音、年龄感和发声特征均以对应参考为准；"
    "文字只控制当前情绪和表演，不重新设计声音身份。"
)


def _variant(
    variant_id: str,
    blind_label: str,
    prompt: str,
) -> dict[str, Any]:
    return {
        "id": variant_id,
        "blind_label": blind_label,
        "prompt": prompt.strip(),
    }


_SEED_SCENE_TEST_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "multi_character_pressure",
        "name": "试药与挣扎",
        "category": "多人压迫动作",
        "purpose": "验证多人声线区分、恐惧升级、动作拟音和紧张音乐动态。",
        "model": SEED_SCENE_TEST_MODEL,
        "expected_duration_s": 28.0,
        "expected_texts": [
            "不要啊！",
            "把头抬起来。",
            "御医，诊断她的身体状况。",
            "遵旨。",
            "我不要做试验品！",
        ],
        "reference_slots": [
            {"id": "captive", "speaker": "俘虏", "description": "朴素、略带沙哑、亲和的中年女性"},
            {"id": "empress", "speaker": "太后", "description": "端庄优雅、威严冷酷的中年女性"},
            {"id": "doctor", "speaker": "御医", "description": "浑厚、略微沙哑、恭敬的中年男性"},
        ],
        "variants": [
            _variant(
                "described_voices",
                "样本 A",
                f"""
俘虏 是朴素的中年女性，略带沙哑，嗓音亲和；太后 是55岁左右的中年女性，嗓音端庄优雅、威严冷酷；御医 是中年男性，浑厚、略微沙哑、恭敬。
{_GLOBAL_CONSTRAINTS}
音乐开头由铜管低音和定音鼓引入，整体沉闷紧张；对白出现时音乐降低。
俘虏用极其惊恐和绝望的语气尖叫：“不要啊！” 句尾伴随一声短促的金属破空声。
太后缓慢、冷酷且充满命令地说：“把头抬起来。”
太后继续清晰地下令：“御医，诊断她的身体状况。” 伴随两声轻微布鞋踏上木台阶。
御医恭敬、正式地回应：“遵旨。”
俘虏挣扎并绝望地大喊：“我不要做试验品！” 期间传来抓住衣服的摩擦声，音乐和音效不得压住喊声。
场景在一声沉闷鼓点和压抑的短暂停顿中结束。
""",
            ),
            _variant(
                "reference_voices",
                "样本 B",
                f"""
俘虏 的声音参考 @音频1，当前仅表演极度惊恐和绝望；太后 的声音参考 @音频2，当前仅表演威严、冷酷和命令；御医 的声音参考 @音频3，当前仅表演恭敬和正式。
{_REFERENCE_IDENTITY_CONSTRAINT}
{_GLOBAL_CONSTRAINTS}
音乐开头由铜管低音和定音鼓引入，整体沉闷紧张；对白出现时音乐降低。
俘虏用极其惊恐和绝望的语气尖叫：“不要啊！” 句尾伴随一声短促的金属破空声。
太后缓慢、冷酷且充满命令地说：“把头抬起来。”
太后继续清晰地下令：“御医，诊断她的身体状况。” 伴随两声轻微布鞋踏上木台阶。
御医恭敬、正式地回应：“遵旨。”
俘虏挣扎并绝望地大喊：“我不要做试验品！” 期间传来抓住衣服的摩擦声，音乐和音效不得压住喊声。
场景在一声沉闷鼓点和压抑的短暂停顿中结束。
""",
            ),
        ],
    },
    {
        "id": "phone_confrontation",
        "name": "电话中的质问",
        "category": "电话悬疑对话",
        "purpose": "验证台湾口音、电话远端失真、质问与无奈的情绪递进。",
        "model": SEED_SCENE_TEST_MODEL,
        "expected_duration_s": 32.0,
        "expected_texts": [
            "钟sir，你是什么时候被收买的？",
            "既然你都知道了，我也没有什么好隐瞒的。",
            "你现在说这些，是要我继续相信你？",
            "有些事，不是我能选择的。保护好自己。",
        ],
        "reference_slots": [
            {"id": "male_1", "speaker": "男子1", "description": "低沉浑厚、成熟的中青年男性"},
            {"id": "male_2", "speaker": "男子2", "description": "沉稳沙哑、无奈的中年男性"},
        ],
        "variants": [
            _variant(
                "described_voices",
                "样本 A",
                f"""
男子1 是中青年男性，台湾口音，嗓音低沉浑厚、成熟；男子2 是中年男性，台湾口音，嗓音沉稳沙哑、成熟稳重。
{_GLOBAL_CONSTRAINTS}
先是一声手机震动，环境中持续轻微鸟鸣；马林巴、合成器和电贝斯形成紧张悬疑的低音配乐。
男子1 严肃并带质问地说：“钟sir，你是什么时候被收买的？”
男子2 的声音经过电话处理，略远且轻微失真，平静而无奈地说：“既然你都知道了，我也没有什么好隐瞒的。”
男子1 怀疑、困惑地追问：“你现在说这些，是要我继续相信你？”
短暂停顿后，男子2 充满无力感和宿命感，缓慢地说：“有些事，不是我能选择的。保护好自己。”
随后出现轻微汽车行驶声、一声刹车声和两声高跟鞋脚步声，音乐收束。
""",
            ),
            _variant(
                "reference_voices",
                "样本 B",
                f"""
男子1 的声音参考 @音频1，当前仅表演严肃和质问；男子2 的声音参考 @音频2，当前仅表演平静和无奈。
{_REFERENCE_IDENTITY_CONSTRAINT}
{_GLOBAL_CONSTRAINTS}
先是一声手机震动，环境中持续轻微鸟鸣；马林巴、合成器和电贝斯形成紧张悬疑的低音配乐。
男子1 严肃并带质问地说：“钟sir，你是什么时候被收买的？”
男子2 的声音经过电话处理，略远且轻微失真，平静而无奈地说：“既然你都知道了，我也没有什么好隐瞒的。”
男子1 怀疑、困惑地追问：“你现在说这些，是要我继续相信你？”
短暂停顿后，男子2 充满无力感和宿命感，缓慢地说：“有些事，不是我能选择的。保护好自己。”
随后出现轻微汽车行驶声、一声刹车声和两声高跟鞋脚步声，音乐收束。
""",
            ),
        ],
    },
    {
        "id": "three_voice_argument",
        "name": "警察争吵",
        "category": "三参考音色争吵",
        "purpose": "验证三人声纹绑定、抢话、脚步远近和击打碰撞时序。",
        "model": SEED_SCENE_TEST_MODEL,
        "expected_duration_s": 30.0,
        "expected_texts": [
            "你配合我，还是我配合你啊？",
            "现在是在内地发生的命案，就是我的事！",
            "你说我什么？有本事自己查啊！",
            "我打你！",
            "别动，别动！",
        ],
        "reference_slots": [
            {"id": "male_lead", "speaker": "男主", "description": "中年男性，港式普通话，情绪急躁"},
            {"id": "female_officer", "speaker": "女警察", "description": "青年女性，音调较高，略带沙哑"},
            {"id": "male_partner", "speaker": "同伴男声", "description": "温和的中青年男性，轻微港式普通话"},
        ],
        "variants": [
            _variant(
                "described_voices",
                "样本 A",
                f"""
男主 是中年男性，港式普通话，嗓音有力、急躁；女警察 是青年女性，音调较高、略带沙哑、攻击性强；同伴男声 是中青年男性，嗓音温和，轻微港式普通话。
{_GLOBAL_CONSTRAINTS}
室内木地板空间，近距离争吵，没有持续配乐。
男主情绪激动、质问且不耐烦地说：“你配合我，还是我配合你啊？”
女警察语速较快，愤怒和声量逐渐加重地反驳：“现在是在内地发生的命案，就是我的事！”
男主声音因愤怒拔高，大声回击：“你说我什么？有本事自己查啊！” 随后是快速离开的木地板脚步声。
一阵运动鞋由远到近的急促脚步后，女警察突然尖锐地喊：“我打你！” 紧接着出现一声击打身体的声音。
背景中的同伴男声惊慌阻止：“别动，别动！” 三人的声音层次必须清楚，不能生成其它台词。
""",
            ),
            _variant(
                "reference_voices",
                "样本 B",
                f"""
男主 的声音参考 @音频1，当前仅表演急躁、愤怒和质问；女警察 的声音参考 @音频2，当前仅表演快速、尖锐和愤怒；同伴男声 的声音参考 @音频3，当前仅表演惊慌和劝阻。
{_REFERENCE_IDENTITY_CONSTRAINT}
{_GLOBAL_CONSTRAINTS}
室内木地板空间，近距离争吵，没有持续配乐。
男主情绪激动、质问且不耐烦地说：“你配合我，还是我配合你啊？”
女警察语速较快，愤怒和声量逐渐加重地反驳：“现在是在内地发生的命案，就是我的事！”
男主声音因愤怒拔高，大声回击：“你说我什么？有本事自己查啊！” 随后是快速离开的木地板脚步声。
一阵运动鞋由远到近的急促脚步后，女警察突然尖锐地喊：“我打你！” 紧接着出现一声击打身体的声音。
背景中的同伴男声惊慌阻止：“别动，别动！” 三人的声音层次必须清楚，不能生成其它台词。
""",
            ),
        ],
    },
    {
        "id": "single_voice_memory",
        "name": "雨声里的回忆",
        "category": "单人伤感回忆",
        "purpose": "验证单参考音色、轻笑、吸气、哽咽、长短停顿和音乐停止。",
        "model": SEED_SCENE_TEST_MODEL,
        "expected_duration_s": 34.0,
        "expected_texts": [
            "我们上中学的时候相爱，后来一直在一起。",
            "我们都不起眼，没有人在乎我们。",
            "明晃晃的太阳下，他第一次哭了。",
            "遇上我，是他那么大最开心的一件事。",
        ],
        "reference_slots": [
            {"id": "female_lead", "speaker": "女主", "description": "音调偏低、略带沙哑的青年女性"},
        ],
        "variants": [
            _variant(
                "described_voices",
                "样本 A",
                f"""
女主 是青年女性，普通话，音调偏低、略带沙哑，叙述克制而真诚。
{_GLOBAL_CONSTRAINTS}
音乐开头由手碟演奏主旋律，合成弦乐铺底，营造忧伤怀旧氛围；环境中持续有远处公路车辆声。
女主温柔平静，在一声很轻的笑后说：“我们上中学的时候相爱，后来一直在一起。”
此时音乐停止。女主落寞、伤感并在句中明显停顿地说：“我们都不起眼，没有人在乎我们。”
女主吸一口气，用更轻柔的声音说：“明晃晃的太阳下，他第一次哭了。”
经过较长停顿，女主略带哽咽和颤抖地说：“遇上我，是他那么大最开心的一件事。”
结尾出现一声由远到近的汽车刹车，随后留出明显静默。
""",
            ),
            _variant(
                "reference_voices",
                "样本 B",
                f"""
女主 的声音参考 @音频1，当前仅表演克制、真诚和逐渐伤感。
{_REFERENCE_IDENTITY_CONSTRAINT}
{_GLOBAL_CONSTRAINTS}
音乐开头由手碟演奏主旋律，合成弦乐铺底，营造忧伤怀旧氛围；环境中持续有远处公路车辆声。
女主温柔平静，在一声很轻的笑后说：“我们上中学的时候相爱，后来一直在一起。”
此时音乐停止。女主落寞、伤感并在句中明显停顿地说：“我们都不起眼，没有人在乎我们。”
女主吸一口气，用更轻柔的声音说：“明晃晃的太阳下，他第一次哭了。”
经过较长停顿，女主略带哽咽和颤抖地说：“遇上我，是他那么大最开心的一件事。”
结尾出现一声由远到近的汽车刹车，随后留出明显静默。
""",
            ),
        ],
    },
    {
        "id": "pure_narration",
        "name": "旧宅中的线索",
        "category": "纯旁白基线",
        "purpose": "验证无对白切换时的旁白可懂度、悬疑节奏和低强度环境控制。",
        "model": SEED_SCENE_TEST_MODEL,
        "expected_duration_s": 24.0,
        "expected_texts": [
            "雨停以后，旧宅里只剩下屋檐滴水的声音。",
            "他推开书房的门，在积灰的桌面上看见一枚新鲜的指纹。",
            "那个人刚刚来过，而且还没有走远。",
        ],
        "reference_slots": [
            {"id": "narrator", "speaker": "旁白", "description": "沉稳克制、清晰、有悬疑感的中青年男性"},
        ],
        "variants": [
            _variant(
                "described_voices",
                "样本 A",
                f"""
旁白 是中青年男性，普通话，嗓音沉稳克制、清晰，具有悬疑叙述感。
{_GLOBAL_CONSTRAINTS}
雨刚停的旧宅室内，屋檐滴水声持续，房间空旷且有轻微木质反射；不使用旋律明显的配乐。
旁白平静、缓慢地说：“雨停以后，旧宅里只剩下屋檐滴水的声音。”
伴随一声老旧木门缓慢开启，旁白稍微压低声音说：“他推开书房的门，在积灰的桌面上看见一枚新鲜的指纹。”
短暂停顿后，旁白在“没有走远”上轻微加重，克制地说：“那个人刚刚来过，而且还没有走远。”
屋檐滴水声继续两秒后自然结束。
""",
            ),
            _variant(
                "reference_voices",
                "样本 B",
                f"""
旁白 的声音参考 @音频1，当前仅表演克制、清晰和逐渐加重的悬疑感。
{_REFERENCE_IDENTITY_CONSTRAINT}
{_GLOBAL_CONSTRAINTS}
雨刚停的旧宅室内，屋檐滴水声持续，房间空旷且有轻微木质反射；不使用旋律明显的配乐。
旁白平静、缓慢地说：“雨停以后，旧宅里只剩下屋檐滴水的声音。”
伴随一声老旧木门缓慢开启，旁白稍微压低声音说：“他推开书房的门，在积灰的桌面上看见一枚新鲜的指纹。”
短暂停顿后，旁白在“没有走远”上轻微加重，克制地说：“那个人刚刚来过，而且还没有走远。”
屋檐滴水声继续两秒后自然结束。
""",
            ),
        ],
    },
)


@dataclass(frozen=True)
class SeedSceneResolvedReference:
    slot_id: str
    reference: Mapping[str, str]
    sha256: str


def build_seed_scene_test_catalog() -> list[dict[str, Any]]:
    catalog = deepcopy(list(_SEED_SCENE_TEST_CASES))
    for case in catalog:
        case["repeat_count"] = SEED_SCENE_TEST_REPEAT_COUNT
    return catalog


def get_seed_scene_test_case(case_id: str) -> dict[str, Any]:
    resolved_id = str(case_id or "").strip()
    case = next((item for item in _SEED_SCENE_TEST_CASES if item["id"] == resolved_id), None)
    if case is None:
        raise ValueError(f"unknown Seed Audio scene test case: {resolved_id}")
    return deepcopy(case)


def build_seed_scene_test_plan(
    case_id: str,
    variant_id: str,
    resolved_references: Sequence[SeedSceneResolvedReference] = (),
    *,
    sample_index: int = 1,
) -> SceneRenderPlan:
    if not 1 <= sample_index <= SEED_SCENE_TEST_REPEAT_COUNT:
        raise ValueError(
            f"sample_index must be between 1 and {SEED_SCENE_TEST_REPEAT_COUNT}"
        )
    case = get_seed_scene_test_case(case_id)
    variant_key = str(variant_id or "").strip()
    variant = next(
        (item for item in case["variants"] if item["id"] == variant_key),
        None,
    )
    if variant is None:
        raise ValueError(f"unknown Seed Audio scene test variant: {variant_key}")

    references = tuple(resolved_references)
    if variant_key == "described_voices":
        if references:
            raise ValueError("described_voices does not accept references")
        ordered_references: tuple[SeedSceneResolvedReference, ...] = ()
        speaker_names = tuple(slot["speaker"] for slot in case["reference_slots"])
    else:
        expected_slots = tuple(slot["id"] for slot in case["reference_slots"])
        by_slot: dict[str, SeedSceneResolvedReference] = {}
        for reference in references:
            if reference.slot_id not in expected_slots:
                raise ValueError(f"unknown reference slot: {reference.slot_id}")
            if reference.slot_id in by_slot:
                raise ValueError(f"duplicate reference slot: {reference.slot_id}")
            by_slot[reference.slot_id] = reference
        missing = tuple(slot_id for slot_id in expected_slots if slot_id not in by_slot)
        if missing:
            raise ValueError(f"missing reference slots: {', '.join(missing)}")
        ordered_references = tuple(by_slot[slot_id] for slot_id in expected_slots)
        speaker_names = tuple(slot["speaker"] for slot in case["reference_slots"])

    prompt = str(variant["prompt"])
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return SceneRenderPlan(
        scene_id=f"seed-test-{case['id']}-{variant_key}-r{sample_index}",
        source_segment_indices=tuple(range(len(case["expected_texts"]))),
        expected_text="\n".join(case["expected_texts"]),
        expected_duration_s=float(case["expected_duration_s"]),
        speaker_names=speaker_names,
        references=tuple(dict(reference.reference) for reference in ordered_references),
        prompt=prompt,
        prompt_hash=prompt_hash,
        reference_hashes=tuple(reference.sha256 for reference in ordered_references),
        boundary_before="test_start",
        boundary_after="test_end",
    )


__all__ = [
    "SEED_SCENE_TEST_MODEL",
    "SEED_SCENE_TEST_REPEAT_COUNT",
    "SEED_SCENE_TEST_VARIANTS",
    "SeedSceneResolvedReference",
    "build_seed_scene_test_catalog",
    "build_seed_scene_test_plan",
    "get_seed_scene_test_case",
]
