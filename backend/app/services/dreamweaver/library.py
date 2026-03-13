from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.dreamweaver import DreamweaverAsset, DreamweaverProject
from app.models.setting import SettingCollection, SettingItem

from pipeline.media_presets import normalize_frame_ratio, normalize_image_resolution, resolve_frame_size
from pipeline.style_presets import normalize_style_preset, style_prompt_for_preset


LIB_ROLE_PREFIX = "lib_"
LIBRARY_ANCHOR_STATUS = "library"
CHARACTER_VIEW_ORDER_DEFAULT = ["front", "bust_front", "side", "bust_three_quarter", "bust_side", "back"]
CHARACTER_VIEW_ROLE_PREFIX = {
    "front": "lib_character_portrait",
    "side": "lib_character_portrait_side",
    "back": "lib_character_portrait_back",
    "bust_front": "lib_character_portrait_bust",
    "bust_three_quarter": "lib_character_portrait_bust_three_quarter",
    "bust_side": "lib_character_portrait_bust_side",
}
CHARACTER_ROLE_PREFIX_TO_VIEW = {value: key for key, value in CHARACTER_VIEW_ROLE_PREFIX.items()}


def _backend_root_dir() -> Path:
    # library.py -> dreamweaver -> services -> app -> backend_root
    return Path(__file__).resolve().parents[3]


def _normalize_local_asset_uri(uri: str) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text
    return text.replace("\\", "/")


def runs_root_path() -> Path:
    return (_backend_root_dir() / "runs").resolve()


def build_library_role(*, entity_type: str, entity_id: int) -> str:
    t = (entity_type or "").strip().lower()
    if t == "character":
        return f"lib_character_portrait:{int(entity_id)}"
    if t == "scene":
        return f"lib_scene_card:{int(entity_id)}"
    if t == "prop":
        return f"lib_prop_card:{int(entity_id)}"
    raise ValueError(f"unsupported entity_type: {entity_type!r}")


def build_character_view_roles(entity_id: int) -> List[str]:
    roles: List[str] = []
    for view in CHARACTER_VIEW_ORDER_DEFAULT:
        prefix = CHARACTER_VIEW_ROLE_PREFIX.get(view)
        if not prefix:
            continue
        roles.append(f"{prefix}:{int(entity_id)}")
    return roles


def empty_library_spec(*, project_id: int) -> Dict[str, Any]:
    return {
        "project_id": int(project_id),
        "characters": [],
        "scenes": [],
        "props": [],
    }


def has_any_library_entities(spec: Dict[str, Any]) -> bool:
    return any(
        isinstance(spec.get(key), list) and len(spec.get(key) or []) > 0
        for key in ("characters", "scenes", "props")
    )


def is_library_role(role: str) -> bool:
    return isinstance(role, str) and role.startswith(LIB_ROLE_PREFIX)


def build_library_prompt(
    *,
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str],
    ratio: Optional[str],
) -> str:
    style = (style_prompt or "").strip() or style_prompt_for_preset(None)
    ratio_norm = normalize_frame_ratio(ratio)
    name = (name or "").strip()
    descriptor = (descriptor or "").strip()

    if entity_type == "character":
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Character: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            "Composition: front-view full-body single-character sheet.\\n"
            "Background: solid color, clean frame, no scene elements, no clutter, no text, no extra people.\\n"
            "Consistency: keep identity anchors stable across views.\\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    if entity_type == "scene":
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Scene: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            "Requirements: environment concept only, no characters, clean composition.\\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    if entity_type == "prop":
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Prop: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            "Requirements: single-object closeup, clean background, clear material details.\\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    return f"Style: {style}\\nRatio: {ratio_norm}\\n{name}\\n{descriptor}\\nConstraints: no text, no watermark, no logo, no border, no collage."


def _importance_rank(raw: Optional[str]) -> int:
    if not raw:
        return 0
    text = str(raw or "").strip()
    lowered = text.lower()

    # Higher rank first: main > important > secondary > crowd/extra.
    if any(token in text for token in ("涓昏", "鏍稿績", "绗竴涓昏")) or any(token in lowered for token in ("main", "lead")):
        return 3
    if any(token in text for token in ("閲嶈", "涓昏", "鍏抽敭")) or "important" in lowered:
        return 2
    if any(token in text for token in ("娆¤", "閰嶈")) or any(token in lowered for token in ("secondary", "support")):
        return 1
    return 0


def _coalesce_text(*parts: Optional[str], limit: int = 200) -> str:
    buf: List[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            buf.append(part.strip())
    joined = "; ".join(buf)
    return joined[:limit]


def _normalize_match_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


_CROWD_TOKENS = (
    "crowd",
    "extra",
    "extras",
    "group",
    "people",
    "bystander",
    "background people",
    "npc",
)
_CROWD_MULTI_PERSON_PATTERN = re.compile(
    r"(?:[2-9]\\d*|[0-9]+)\s*(?:people|persons)|multi(?:-| )person|group|crowd|bystander[s]?|background people|npc[s]?|extra[s]?"
)


def _is_crowd_character(*, name: Any, importance: Any, descriptor: Any = None) -> bool:
    compact = "|".join(
        [
            _normalize_match_token(name),
            _normalize_match_token(importance),
            _normalize_match_token(descriptor),
        ]
    )
    if not compact or compact == "|":
        return False
    if any(token in compact for token in _CROWD_TOKENS):
        return True
    return bool(_CROWD_MULTI_PERSON_PATTERN.search(compact))


@dataclass(frozen=True)
class LibraryEntity:
    entity_type: str  # character|scene|prop
    entity_id: int
    name: str
    descriptor: str

    @property
    def role(self) -> str:
        return build_library_role(entity_type=self.entity_type, entity_id=self.entity_id)


def build_library_spec(
    db: Session,
    *,
    project_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .all()
    )
    characters_sorted_all = sorted(
        characters,
        key=lambda c: (-_importance_rank(getattr(c, "importance_level", None)), int(getattr(c, "id", 0))),
    )
    try:
        char_limit = int(max_characters)
    except Exception:  # noqa: BLE001
        char_limit = 0
    if char_limit > 0:
        characters_sorted = characters_sorted_all[:char_limit]
    else:
        characters_sorted = characters_sorted_all

    character_entities: List[LibraryEntity] = []
    for c in characters_sorted:
        name = str(getattr(c, "name", "") or "").strip()
        if not name:
            continue
        importance = str(getattr(c, "importance_level", "") or "").strip()
        descriptor = _coalesce_text(getattr(c, "summary", None), getattr(c, "profile", None), limit=640)
        if _is_crowd_character(name=name, importance=importance, descriptor=descriptor):
            continue
        if not descriptor:
            descriptor = _coalesce_text(getattr(c, "gender", None), str(getattr(c, "age", "") or ""), limit=120)
        character_entities.append(
            LibraryEntity(entity_type="character", entity_id=int(c.id), name=name, descriptor=descriptor)
        )

    def _items_by_category(category: str, limit: int) -> List[SettingItem]:
        col_ids = [
            int(c.id)
            for c in (
                db.query(SettingCollection)
                .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
                .all()
            )
        ]
        if not col_ids:
            return []
        q = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(col_ids))
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.usage_count.desc(), SettingItem.updated_at.desc(), SettingItem.id.asc())
        )
        try:
            safe_limit = int(limit)
        except Exception:  # noqa: BLE001
            safe_limit = 0
        if safe_limit > 0:
            return q.limit(safe_limit).all()
        return q.all()

    scene_items = _items_by_category("map_system", max_scenes)
    prop_items = _items_by_category("artifact_system", max_props)

    scene_entities: List[LibraryEntity] = []
    for item in scene_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        scene_entities.append(
            LibraryEntity(entity_type="scene", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    prop_entities: List[LibraryEntity] = []
    for item in prop_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        prop_entities.append(
            LibraryEntity(entity_type="prop", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def build_library_spec_from_script_entities(
    db: Session,
    *,
    project_id: int,
    entities: Dict[str, Any],
) -> Dict[str, Any]:
    """
    闂傚倸鍊搁崐鎼佸磹閻戣姤鍤勯柛鎾茬劍閸忔粓鏌涢锝嗙闁汇倝绠栭弻锝夊箛椤掍讲鏋欏┑鐐茬摠閻楃娀寮婚弴鐔虹鐟滃秴螞濡も偓閻剙鈹戦敍鍕杭闁稿﹥鐗滈弫顕€骞掗弬鍝勪壕婵鍘ф晶鐗堢箾閹寸姵鏆柛鈹惧亾濡炪倖甯掔€氼參鍩涢幋锔界厱婵犻潧妫楅顏嗏偓鐟版啞缁诲牓寮诲☉銏℃櫜闁告劑鍔屾慨锕傛倵鐟欏嫭绀冮柛銊ャ偢钘濈憸鐗堝笚閻撴盯鎮橀悙鎻掆挃婵炴彃鐡ㄩ〃銉╂倷閻ゆ浜ｉ悘鍐⒑闁偛鑻晶浼存煃瑜滈崜姘跺礄瑜版帒鐭楅柛鎰靛枤瀹撲線鐓崶銊р姇闁绘帟鍋愰埀顒€绠嶉崕鍗炍涘☉銏犲偍闁汇垹鎲￠埛鎴︽偣閸ワ絺鍋撳畷鍥﹀寲濠电姭鎷冮崟鍨杹闁芥鍠庨…璺ㄦ崉閻戞ɑ鎷遍梺鍝ュУ閸旀瑩寮婚埄鍐ㄧ窞閻庯綆浜堕崵瀣⒑閸濄儱校闁挎洏鍨藉?script_entities 闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜缂佹ɑ娅堥梻浣告啞娓氭宕归鍫濈；闁圭偓鍓氬鈺呮煟閹炬娊顎楁い顐亞缁辨挻鎷呮禒瀣懙闂佸湱鎳撳ú顓㈡偘椤斿槈鐔煎礂閻撳海褰撮梻浣藉亹閳峰牓宕楀☉姘潟婵犲﹤瀚弧鈧梺姹囧灲濞佳冪摥闂備焦瀵уú蹇涘磹濡ゅ懎鐒垫い鎺嶇閸ゎ剟鏌涘▎蹇撴殻闁绘侗鍠涚粻娑㈠籍閳ь剛绱為崶顒佺厓闁告繂瀚弳鐔兼煥濞戞瑧鐭掓慨濠冩そ瀹曨偊宕熼锝嗩唲闂備胶顭堥敃銉╁箖閸岀偞鍊电€瑰嫭澹嬮弨浠嬫煟濡椿鍟忛柡鍡╁灡娣囧﹪骞撻幒鎾虫畻閻庤娲╃紞浣哥暦濮椻偓椤㈡瑩鎳栭埡鍐╂瘒婵犵數鍋涢顓熸叏閹绢噮鏁勯柛娑卞枛閸旀棃姊婚崒娆戠獢婵炰匠鍥佸洭顢橀姀鐘碉紵闂佽鍎煎Λ鍕磼閵娾晜鐓欓柣鎴烇供濞堟洟鏌嶉柨瀣仸闁逛究鍔戦幃鐑芥偋閸喐鍊峰┑鐘殿暯閳ь剛鍋ㄩ崑銏ゆ煙椤旂瓔娈旀い顐ｇ箞閸┾偓妞ゆ帒瀚悙濠勬喐韫囨稑绀夐柨鏇楀亾妞ゎ亜鍟存俊鍫曞幢濡ゅ啰鎲梻浣哄帶閸熸寧鏅舵惔锝呭灊閻犲洤寮悢鍏煎殐闁冲搫鍠涚槐鏌ユ⒒娓氣偓閳ь剛鍋涢懟顖涙櫠椤曗偓閺岋綁鏁愰崱娆戠杽閻庤娲滈崰鏍€侀弴銏犖у璺鸿嫰缁€鍫ユ⒒閸屾艾鈧绮堟担铏圭濠电姴娲ょ壕璇测攽閻樺弶鎼愮紒鈧崼鐔虹闁瑰鍎戞笟娑欑箾?spec闂?    - 闂傚倸鍊搁崐宄懊归崶褏鏆﹂柣銏㈩焾缁愭鏌熼幍顔碱暭闁稿绻濋弻銊╁籍閸屾矮澹曢梺鍝勬缁捇寮婚敐澶婃闁圭瀛╅崰鎰版⒑缂佹绠氭繛澶嬬洴閸╃偤骞嬮敂钘変汗闂佸憡鐟ラˇ顖炈囬埡鍛拺闁告繂瀚刊濂告煕閹惧瓨鐨戦柟骞垮灩閳藉濮€閻樿尪鈧灝鈹戦悙鍙夘棡闁搞劎鏁昏棢闁告鏁僡cter闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲櫧闁活厽鐟╅弻鐔衡偓娑欘焽缁犮儵鏌ｉ幒鏃€娅曠紒杈ㄥ笧娴狅箓宕滆閹虫獚ect_id + name闂?    - 闂傚倸鍊搁崐鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掔晫绱撴担濮戣偐鎹㈤崱娑欑厱闁靛鍠栨晶顔剧棯閹勫仴闁哄本娲熷畷鐓庘攽閸パ勭彺闂備礁鎼鍛矓閻㈠灚宕叉繛鎴欏灩楠炪垺淇婇婵愬殭闂傚绉瑰娲传閸曨剙顎涢梺鍛婃尰瀹€鎼佺嵁閸儱惟闁靛鍨洪弬鈧梻浣虹《閸撴繈鎮烽妷銉富缂佽尙骞慽ngItem闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲櫧闁活厽鐟╅弻鐔衡偓娑欘焽缁犮儵鏌ｉ幒鏃€娅曢柍褜鍓涢崑锝夊磹濡も偓閳绘捇鎮楀畡鐖媟y=map_system闂?    - 闂傚倸鍊搁崐鎼佸磹閹间礁纾瑰瀣椤愪粙鏌ㄩ悢鍝勑㈢紒鈧崼鐔稿弿婵☆垱瀵х涵鍓х磼閻樺崬宓嗛柡宀€鍠栧鑽も偓闈涘濡差噣姊哄ú璇插箺妞ゃ劌锕璇测槈濠婂孩歇婵＄偑鍊戦崝灞轿涘┑鍡╁殨闁哄被鍎洪弫鍡椕归敐鍥ㄥ殌鐎殿喖鐏濋埞鎴︽偐缂佹ɑ閿┑鈽嗗亝缁嬫垿鎮鹃悜鑺ュ仏缂佸崬宕╪gItem闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲櫧闁活厽鐟╅弻鐔衡偓娑欘焽缁犮儵鏌ｉ幒鏃€娅曢柍褜鍓涢崑锝夊磹濡も偓閳绘捇鎮楀畡鐖媟y=artifact_system闂?
    闂傚倸鍊搁崐宄懊归崶褏鏆﹂柛顭戝亝閸欏繘鏌℃径瀣婵炲樊浜滃洿婵犮垼娉涢鍛闁秵鈷戦梻鍫熶緱閻掗箖鏌涙惔銏㈡噰闁轰焦鍔栧鍕節閸曢潧鎮堥梻鍌欑劍鐎笛兾涙担瑙勫弿闁靛牆鎳夐弸宥夋煛瀹擃喒鍋撻柡鈧懞銉ｄ簻闁哄啫鍊瑰▍鏇犵磼閻樼鑰块柡灞界Ч閺屻劎鈧綆鍋呴柨鐠眕t_entities 濠?name 濠电姷鏁告慨鐑藉极閹间礁纾婚柣鎰惈閸ㄥ倿鏌涢锝嗙缂佺姵褰冮湁闁挎繂鎳庨ˉ蹇旂箾鐎涙澧甸柡灞炬礃缁绘稖顦柛瀣崌閺屾稓鈧綆鍋呭畷灞句繆椤愩垹鏆欓柍钘夘槸椤繈宕￠悙娈嬬喖姊婚崒娆戭槮闁圭⒈鍋嗛幃顕€顢曢敃鈧粈澶愭煙鏉堟崘绀嬮柍褜鍏涚粈渚€鍩㈡惔銊ョ缂侇喛顫夌€氫粙姊虹拠鏌ヮ€楅柣蹇斿哺楠炲啴宕掗悙鑼幋闂婎偄娲︾粙鎺楀煕閹达附鍋ｉ柛銉ｅ妿閸欌偓闂佸憡鐟ョ€氼厾鎹㈠☉娆愬闁告劕寮堕崳鐣岀磼閳ь剚绻濋崒妤佹杸闂佺粯蓱瑜板啴顢旈銈囩＜闁逞屽墯缁绘繈宕堕妸褍骞堟俊鐐€栭崝妤佹叏閹绢喖绀夋繝濠傜墛閻撴盯鏌涘鈧粈浣规櫠椤栨粎纾肩紓浣诡焽濞插瓨顨ラ悙宸剶闁诡喗鐟╅幃浠嬫偨闂堟稑绗屾繝纰夌磿閸嬫垿宕愰弴鐘冲床闁圭儤顨呯粣妤呮煛瀹ュ骸骞栭柦鍐枛閺屻劑鎮㈤崫鍕戙垽姊洪崡鐐村闁靛洤瀚伴獮鍥Ω閵夈儮鎷ら梻浣告贡濞呫垻绱炴担鍓叉綎闁惧繐婀遍惌娆撴偣閹帒濡挎い鏂款樀濮婃椽骞愭惔銏紭闂佹悶鍔岀紞濠囧箖妤ｅ啯鍊婚柤鎭掑劚閳ь剙顭烽弻锕€螣閻氬绀嗛梺鍐叉惈閹冲繘鎮￠崘顔界厽闁绘梻顭堥ˉ瀣叏濡濮傞柡灞剧〒閳ь剨缍嗛崑鍛焊椤撶喆浜滈柟鎯у暱閹垹鈧灚婢樼€氼噣鍩€椤掑﹦绉靛ù婊勭矋缁旂喖宕卞Ο鍦畾闂佺粯鍔︽禍婊堝焵椤掍胶澧摶鐐层€掑锝呬壕閻庤娲橀崹鍧楃嵁閸ヮ剦鏁嗗璺侯儏閸忓﹪姊绘笟鈧褔鈥﹂崼銉ョ？妞ゆ柨妲堥敐澶婇唶闁靛濡囬崢鐢告⒑閸撹尙鍘涢柛鐘崇墵瀵啿鈻庨幇鍨啍闂佺粯鍔曢顓熸櫠閻㈠憡鐓涚€光偓閳ь剟宕伴弽褜鍤曟い鎺戝鍞梺闈涱槶閸庮噣骞忛妶鍥╃＝闁稿本鐟чˇ锔姐亜閹存繃鍤囬挊婵嬫煟閵忊剝鍋犻柍褜鍏涚粈渚€锝炲鍫濈劦妞ゆ帊妞掔换鍡樻叏濠靛棛鐒炬俊鍙夊劤椤啴濡惰箛鎾舵В闂侀潻缍囩徊浠嬶綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愭繝姘仭闁哄被鍎查埛鎴︽煠婵劕鈧洟寮搁崒鐐寸厱闁哄啠鍋撻柛銊ユ健婵″瓨鎷呴崜鍙夊兊濡炪倖甯掗ˇ浼村磽閻㈠憡鈷戦柣鐔告緲閹胶绱掗埀顒佹媴閸︻収娲告俊銈忕到閸燁垶鎮￠弴銏＄叆闁哄啫娴傞崵娆愵殽閻愬澧棁澶愭煟濡搫鏆辩紒妞﹀懐纾奸弶鍫涘妽鐏忣厽銇勯幘鐐藉仮鐎规洦浜濋幏鍛矙閸噮妫婇梻鍌欐祰椤曆兠归悜钘夋瀬闁归棿绀侀崒銊ф喐閺冨牊鏅查柣鎰ゴ閺€浠嬫倵閿濆簼绨介柣銈傚亾婵犵數鍋犻幓顏嗗緤閸фぜ鈧焦绻濋崶褏鏌ч悷婊勬煥椤繐煤椤忓懎娈ラ梺闈涚墕閹叉盯濮€閵堝棛鍘电紒鐐緲瀹曨剚绂嶆导瀛樼厵妞ゆ柨鍚嬮崑銉р偓瑙勬礀閻栧ジ宕洪敓鐘茬＜婵﹩鍓涢崫搴ㄦ⒒閸屾瑧顦﹂柟璇х節瀹曟繈鏁冮崒姘辩崶闂佸搫绋侀崜娑氱不?    """
    if not isinstance(entities, dict):
        entities = {}

    def _pick_named_items(raw: Any) -> List[Tuple[str, str, str]]:
        items = raw if isinstance(raw, list) else []
        seen: set[str] = set()
        out: List[Tuple[str, str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            descriptor = str(item.get("descriptor") or "").strip()
            importance = str(item.get("importance") or item.get("importance_level") or "").strip()
            out.append((name, descriptor, importance))
        return out

    # 1) Characters
    character_pairs_raw = _pick_named_items(entities.get("characters"))
    character_pairs = [
        (name, descriptor, importance)
        for name, descriptor, importance in character_pairs_raw
        if not _is_crowd_character(name=name, importance=importance, descriptor=descriptor)
    ]
    character_names = [name for name, _, _ in character_pairs]
    characters_by_name: Dict[str, Character] = {}
    if character_names:
        rows = db.query(Character).filter(Character.project_id == project_id, Character.name.in_(character_names)).all()
        characters_by_name = {str(getattr(c, "name", "") or ""): c for c in rows if str(getattr(c, "name", "") or "").strip()}

    character_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in character_pairs:
        row = characters_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "profile", None), limit=640)
        if not resolved:
            resolved = _coalesce_text(getattr(row, "gender", None), str(getattr(row, "age", "") or ""), limit=120)
        character_entities.append(LibraryEntity(entity_type="character", entity_id=int(row.id), name=name, descriptor=resolved))

    def _setting_items_by_name(category: str, names: List[str]) -> Dict[str, SettingItem]:
        if not names:
            return {}
        col_ids = [
            int(c.id)
            for c in (
                db.query(SettingCollection)
                .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
                .all()
            )
            if getattr(c, "id", None) is not None
        ]
        if not col_ids:
            return {}
        rows = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(col_ids), SettingItem.name.in_(names))
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.id.asc())
            .all()
        )
        return {str(getattr(r, "name", "") or ""): r for r in rows if str(getattr(r, "name", "") or "").strip()}

    # 2) Scenes
    scene_pairs = _pick_named_items(entities.get("scenes"))
    scene_names = [name for name, _, _ in scene_pairs]
    scenes_by_name = _setting_items_by_name("map_system", scene_names)

    scene_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in scene_pairs:
        row = scenes_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        scene_entities.append(LibraryEntity(entity_type="scene", entity_id=int(row.id), name=name, descriptor=resolved))

    # 3) Props
    prop_pairs = _pick_named_items(entities.get("props"))
    prop_names = [name for name, _, _ in prop_pairs]
    props_by_name = _setting_items_by_name("artifact_system", prop_names)

    prop_entities: List[LibraryEntity] = []
    for name, descriptor, _importance in prop_pairs:
        row = props_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        prop_entities.append(LibraryEntity(entity_type="prop", entity_id=int(row.id), name=name, descriptor=resolved))

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def strip_crowd_characters_from_spec(
    db: Session,
    *,
    project_id: int,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ensure crowd / extra characters are excluded even if they slipped into a scoped spec.
    """
    if not isinstance(spec, dict):
        return {"project_id": int(project_id), "characters": [], "scenes": [], "props": []}

    raw_characters = spec.get("characters")
    characters = raw_characters if isinstance(raw_characters, list) else []
    if not characters:
        out = dict(spec)
        out["project_id"] = int(project_id)
        out["characters"] = []
        if not isinstance(out.get("scenes"), list):
            out["scenes"] = []
        if not isinstance(out.get("props"), list):
            out["props"] = []
        return out

    character_ids: List[int] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        try:
            entity_id = int(item.get("entity_id"))
        except Exception:  # noqa: BLE001
            continue
        if entity_id > 0:
            character_ids.append(entity_id)

    row_by_id: Dict[int, Character] = {}
    if character_ids:
        rows = (
            db.query(Character)
            .filter(Character.project_id == project_id, Character.id.in_(sorted(set(character_ids))))
            .all()
        )
        row_by_id = {int(getattr(row, "id", 0)): row for row in rows if getattr(row, "id", None) is not None}

    filtered_characters: List[Dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        descriptor = str(item.get("descriptor") or "").strip()
        importance = str(item.get("importance") or item.get("importance_level") or "").strip()
        entity_id: Optional[int] = None
        try:
            entity_id = int(item.get("entity_id"))
        except Exception:  # noqa: BLE001
            entity_id = None

        row = row_by_id.get(int(entity_id)) if isinstance(entity_id, int) and entity_id > 0 else None
        row_name = str(getattr(row, "name", "") or "").strip() if row is not None else ""
        row_importance = str(getattr(row, "importance_level", "") or "").strip() if row is not None else ""
        row_descriptor = _coalesce_text(getattr(row, "summary", None), getattr(row, "profile", None), limit=640) if row is not None else ""

        if _is_crowd_character(
            name=name or row_name,
            importance=importance or row_importance,
            descriptor=descriptor or row_descriptor,
        ):
            continue

        next_item = dict(item)
        if not str(next_item.get("name") or "").strip() and row_name:
            next_item["name"] = row_name
        if not str(next_item.get("descriptor") or "").strip() and row_descriptor:
            next_item["descriptor"] = row_descriptor
        filtered_characters.append(next_item)

    out = dict(spec)
    out["project_id"] = int(project_id)
    out["characters"] = filtered_characters
    if not isinstance(out.get("scenes"), list):
        out["scenes"] = []
    if not isinstance(out.get("props"), list):
        out["props"] = []
    return out


def load_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
) -> Dict[str, Dict[str, Any]]:
    """
    闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曚綅閸ヮ剦鏁冮柨鏇楀亾闁汇倗鍋撶换婵囩節閸屾粌顣洪梺钘夊暟閸犳牠寮婚弴鐔虹闁割煈鍠栨竟鍕攽閻愬弶鈻曞ù婊勭矒瀹曟﹢鍩€椤掆偓椤啴濡堕崱妯烘殫闂佺顑囬崰鏍€?role 闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閾忣偅鐝ㄦ繝纰夌磿閸嬫垿宕愰妶澶婂偍濡わ絽鍟粈鍌涗繆椤栨繃顏犻柡鍡畵閺岀喖骞嗛悧鍫缂備胶濮烽幊鎾绘箒闂佹寧绻傚ú锕傚吹閳ь剟姊洪崨濠冩儎闁告瑥鍟～蹇撁洪鍕獩婵犵數濮撮崯顐λ囬埡鍛拺闁告稑锕ョ亸鎵棯閺夎法肖缂侇喖顑夐獮鎺楀箣椤撶喎缂撻梻渚€鈧偛鑻晶瀵糕偓娈垮枛椤兘寮幘缁樺亹闁肩⒈鍓ㄧ槐鍙夌節閻㈤潧浠﹂柛銊ョ埣閺佸啴鍩℃担鍕洴瀹曞崬鈻庨幋鐙呯闯濠电偠鎻徊鎹愩亹閸愨晝顩插Δ锝呭暞閸婄敻鏌涜箛鎿冩Ц濞存粓绠栧娲川婵犲啫顦╅梺绋款儏濡瑩銆冮妷鈺佺倞妞ゆ帊璁查幏娲偡濠婂懎顣奸悽顖涘笚缁傚秵瀵肩€涙鍘遍梺瑙勫劤椤曨參鍩ユ径瀣ㄤ簻妞ゆ劧绲跨粻鐐测攽閳╁啯鍊愰柛鈺嬬節瀹曟帒顫濋銏狀嚙闂備浇宕甸崰鎰垝瀹€鈧划鏃堝醇閺囩偟鍔﹀銈嗗笂缁€渚€宕甸鈧湁婵犲﹤瀚粻鐐烘煏閸℃鏆ｅ┑锛勫厴閸┾剝鎷呴崫鍕ㄥ亾閻愬樊娓婚柕鍫濇缁楀倿鏌ｉ幒鐐电暠闁宠绉瑰浠嬵敇閻斿弶瀚奸梻浣告啞閹告槒銇愰崘鈺冾洸闁告挆鍛紲闂佸湱绮敮鎺楀煕閺冣偓缁?run闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲櫧闁活厽鐟╅弻鐔告綇妤ｅ啯顎嶉梺鎼炲€栭崝鏍Φ閸曨垰鍐€闁靛ě鍛獥濠?updated_at 闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜閽樺缃曢梻浣告啞閸旓箓宕伴弽顐㈩棜濠电姵纰嶉悡娆撴煕閹炬鎳庣粭锟犳⒑缂佹ɑ灏伴柣鈺婂灦瀵鈽夊顐ｅ媰闂佸憡鎸嗛埀顒€危閸繍娓婚柕鍫濆暙閸旀碍銇勯幋婵囶棤闁瑰箍鍨归埥澶愬閻樿鏁归梻浣虹帛濡啴藟閹惧顩烽柛婵勫劤绾捐棄霉閿濆懎顥忛柛搴＄箲閵囧嫰鏁傞悙顒佹瘓閻庤娲樺浠嬪春閳ь剚銇勯幒宥夋濞存粍绮撻弻鐔兼倻濡櫣浠村銈呯箚閺呮繄妲愰幒妤佸亼婵炲棗绻戞径鍕煟閹惧啿鏆ｉ柡宀嬬畱铻ｅ〒姘煎灡鏁堥梻渚€娼荤徊鍧楀疾椤愩倖顫曢柟鐑橆殔閻掑灚銇勯幒鎴濐仼妤犵偑鍨虹换娑㈠箣閻愬灚鍣梺?    """
    rows = (
        db.query(DreamweaverAsset, DreamweaverProject)
        .join(DreamweaverProject, DreamweaverAsset.dreamweaver_project_id == DreamweaverProject.id)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .filter(DreamweaverAsset.asset_type == "image")
        .all()
    )

    def _uri_available(uri: str) -> bool:
        text = _normalize_local_asset_uri(uri)
        if not text:
            return False
        if "://" in text:
            return True
        try:
            p = resolve_asset_path(text).resolve()
            base = runs_root_path()
            if (p != base and base not in p.parents) or (not p.exists()):
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    latest: Dict[str, Tuple[bool, datetime, DreamweaverAsset, DreamweaverProject]] = {}
    for asset, project in rows:
        role = str(getattr(asset, "role", "") or "")
        if not is_library_role(role):
            continue
        updated_at = getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)
        if not isinstance(updated_at, datetime):
            continue
        uri_ok = _uri_available(str(getattr(asset, "uri", "") or ""))
        prev = latest.get(role)
        if prev is None:
            latest[role] = (uri_ok, updated_at, asset, project)
            continue

        prev_uri_ok, prev_updated_at, _prev_asset, _prev_project = prev
        # Prefer assets whose underlying file actually exists; within same availability, pick latest.
        if (uri_ok and not prev_uri_ok) or (uri_ok == prev_uri_ok and updated_at > prev_updated_at):
            latest[role] = (uri_ok, updated_at, asset, project)

    result: Dict[str, Dict[str, Any]] = {}
    for role, (uri_ok, _ts, asset, project) in latest.items():
        meta = asset.meta_json if isinstance(asset.meta_json, dict) else {}
        approved = bool(meta.get("approved")) if isinstance(meta, dict) else False

        # Backfill style metadata for legacy assets from runtime_config.
        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0
        try:
            contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
            runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
            if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
                inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
            if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
                inferred_prompt = runtime_cfg.get("style_prompt").strip()
            elif inferred_preset:
                inferred_prompt = style_prompt_for_preset(inferred_preset)
            image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
            if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
                inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
            else:
                inferred_ratio = normalize_frame_ratio(None)
            if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
                inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
            else:
                inferred_resolution = normalize_image_resolution(None)

            image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
            if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
                image_cfg_for_size["ratio"] = inferred_ratio
            if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
                image_cfg_for_size["resolution"] = inferred_resolution
            inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
        except Exception:  # noqa: BLE001
            inferred_preset = ""
            inferred_prompt = ""
            inferred_ratio = ""
            inferred_resolution = ""
            inferred_width = 0
            inferred_height = 0

        merged_meta = dict(meta) if isinstance(meta, dict) else {}
        if inferred_preset and not str(merged_meta.get("style_preset") or "").strip():
            merged_meta["style_preset"] = inferred_preset
        if inferred_prompt and not str(merged_meta.get("style_prompt") or "").strip():
            merged_meta["style_prompt"] = inferred_prompt
        if inferred_ratio and not str(merged_meta.get("ratio") or "").strip():
            merged_meta["ratio"] = inferred_ratio
        if inferred_resolution and not str(merged_meta.get("resolution") or "").strip():
            merged_meta["resolution"] = inferred_resolution
        try:
            existing_width = int(merged_meta.get("width") or 0)
        except Exception:  # noqa: BLE001
            existing_width = 0
        try:
            existing_height = int(merged_meta.get("height") or 0)
        except Exception:  # noqa: BLE001
            existing_height = 0
        if inferred_width > 0 and existing_width <= 0:
            merged_meta["width"] = int(inferred_width)
        if inferred_height > 0 and existing_height <= 0:
            merged_meta["height"] = int(inferred_height)
        merged_meta["file_available"] = bool(uri_ok)

        result[role] = {
            "id": int(asset.id),
            "asset_type": str(asset.asset_type),
            "role": str(asset.role),
            "uri": str(asset.uri),
            "meta": {**merged_meta, "approved": approved},
            "updated_at": (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)).isoformat()
            if (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None))
            else None,
        }
    return result


def required_library_roles(spec: Dict[str, Any]) -> List[str]:
    def _character_view_roles(entity_id: int) -> List[str]:
        return build_character_view_roles(int(entity_id))

    required_roles: List[str] = []
    section_defaults = {"characters": "character", "scenes": "scene", "props": "prop"}
    for key, default_entity_type in section_defaults.items():
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, int):
                try:
                    entity_id = int(entity_id)
                except Exception:  # noqa: BLE001
                    continue
            try:
                if str(entity_type or "").strip().lower() == "character":
                    # Final safeguard: crowd/extra characters must never produce library roles.
                    if _is_crowd_character(
                        name=item.get("name"),
                        importance=item.get("importance") or item.get("importance_level"),
                        descriptor=item.get("descriptor"),
                    ):
                        continue
                    required_roles.extend(_character_view_roles(int(entity_id)))
                else:
                    required_roles.append(build_library_role(entity_type=entity_type, entity_id=int(entity_id)))
            except Exception:  # noqa: BLE001
                continue
    return required_roles


def parse_library_role(role: str) -> Tuple[str, int]:
    text = str(role or "").strip()
    for prefix in CHARACTER_ROLE_PREFIX_TO_VIEW:
        if text.startswith(f"{prefix}:"):
            return "character", int(text.split(":", 1)[1])
    if text.startswith("lib_scene_card:"):
        return "scene", int(text.split(":", 1)[1])
    if text.startswith("lib_prop_card:"):
        return "prop", int(text.split(":", 1)[1])
    raise ValueError(f"invalid library role: {role!r}")


def default_library_asset_uri(*, project_id: int, role: str) -> str:
    entity_type, entity_id = parse_library_role(role)
    sub = "misc"
    if entity_type == "character":
        sub = "characters"
    elif entity_type == "scene":
        sub = "scenes"
    elif entity_type == "prop":
        sub = "props"
    filename = f"{int(entity_id)}.png"
    if entity_type == "character":
        role_text = str(role)
        if role_text.startswith("lib_character_portrait_side:"):
            filename = f"{int(entity_id)}_side.png"
        elif role_text.startswith("lib_character_portrait_back:"):
            filename = f"{int(entity_id)}_back.png"
        elif role_text.startswith("lib_character_portrait_bust:"):
            filename = f"{int(entity_id)}_bust.png"
        elif role_text.startswith("lib_character_portrait_bust_three_quarter:"):
            filename = f"{int(entity_id)}_bust_34.png"
        elif role_text.startswith("lib_character_portrait_bust_side:"):
            filename = f"{int(entity_id)}_bust_side.png"
    return (Path("runs") / "library" / f"project_{int(project_id)}" / sub / filename).as_posix()


def _infer_latest_runtime_meta(project: DreamweaverProject) -> Dict[str, Any]:
    inferred_preset = ""
    inferred_prompt = ""
    inferred_ratio = ""
    inferred_resolution = ""
    inferred_width = 0
    inferred_height = 0
    try:
        contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
            inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
        if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
            inferred_prompt = runtime_cfg.get("style_prompt").strip()
        elif inferred_preset:
            inferred_prompt = style_prompt_for_preset(inferred_preset)
        image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
        if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
            inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
        else:
            inferred_ratio = normalize_frame_ratio(None)
        if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
            inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
        else:
            inferred_resolution = normalize_image_resolution(None)

        image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
        if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
            image_cfg_for_size["ratio"] = inferred_ratio
        if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
            image_cfg_for_size["resolution"] = inferred_resolution
        inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
    except Exception:  # noqa: BLE001
        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0

    meta: Dict[str, Any] = {"approved": False}
    if inferred_preset:
        meta["style_preset"] = inferred_preset
    if inferred_prompt:
        meta["style_prompt"] = inferred_prompt
    if inferred_ratio:
        meta["ratio"] = inferred_ratio
    if inferred_resolution:
        meta["resolution"] = inferred_resolution
    if inferred_width > 0:
        meta["width"] = int(inferred_width)
    if inferred_height > 0:
        meta["height"] = int(inferred_height)
    return meta


def _library_anchor_run_id(*, project_id: int, user_id: int) -> str:
    return f"library_anchor:project:{int(project_id)}:user:{int(user_id)}"


def _ensure_library_anchor_project(db: Session, *, project_id: int, user_id: int) -> DreamweaverProject:
    anchor = (
        db.query(DreamweaverProject)
        .filter(
            DreamweaverProject.source_project_id == project_id,
            DreamweaverProject.user_id == user_id,
            DreamweaverProject.status == LIBRARY_ANCHOR_STATUS,
        )
        .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
        .first()
    )
    if anchor is not None:
        return anchor

    anchor_run_id = _library_anchor_run_id(project_id=project_id, user_id=user_id)
    preset = normalize_style_preset(None)
    style = style_prompt_for_preset(preset)
    ratio = normalize_frame_ratio(None)
    resolution = normalize_image_resolution(None)
    width, height, _ratio = resolve_frame_size({"ratio": ratio, "resolution": resolution})

    anchor = DreamweaverProject(
        run_id=anchor_run_id,
        source_project_id=project_id,
        user_id=user_id,
        schema_version="0.1.0",
        status=LIBRARY_ANCHOR_STATUS,
        state=None,
        stage=None,
        progress=0,
        error_type=None,
        error_message=None,
        contract_json={
            "runtime_config": {
                "style_preset": preset,
                "style_prompt": style,
                "image_config": {
                    "ratio": ratio,
                    "resolution": resolution,
                    "width": int(width),
                    "height": int(height),
                },
            }
        },
    )
    db.add(anchor)
    db.flush()
    return anchor


def ensure_required_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    spec: Dict[str, Any],
) -> int:
    """
    缂傚倸鍊搁崐鎼佸磹閻戣姤鍤勯柛顐ｆ礃閹偤骞栧ǎ顒€濡奸柣顓燁殜楠炴牕菐椤掆偓婵¤偐绱掗幇顓ф疁闁哄矉绻濆畷鍫曞煛娴ｅ浄绲块埀顒冾潐濞叉牕顕ｉ崼鏇炵疄闁靛鍎哄銊╂煕閳╁喚娈斿┑顔诲嵆濮婃椽宕烽鐐插濠电偛寮剁划鎾诲箖閸ф鐒垫い鎺戝閻撴瑩鏌涜箛姘汗闁哄棙锕㈤弻娑㈠棘閼愁垰顏梺?required role 闂?DB 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸婂潡鏌ㄩ弴姘舵濞存粌缍婇弻娑㈠箛闂堟稒鐏嶉梺绋垮椤ㄥ懘濡撮幒鎴僵闁挎繂鎳嶆竟鏇㈡煟鎼淬値娼愭繛鍙夌矒瀵偅绻濆顒佺€梺绋跨灱閸嬫盯鎯屽Δ鍛厪濠㈣鍨伴崯顐﹀煕閺囥垺鈷掗柛灞剧懆閸忓矂鏌熼搹顐ｅ磳妞ゃ垺宀搁、姗€濮€閻樼绱遍梻浣虹帛閸旀寮崨濠勨枖鐎广儱顦伴悡娆撴煟閹寸伝顏堟倶瀹ュ棔绻嗛柟缁樺笧婢э箓鏌″畝鈧崰鎾舵閹烘顫呴柣妯哄悁閸濇鈹戦悙鑼憼缂侇喗鎸剧划濠氬冀瑜滃?DreamweaverAsset 闂傚倸鍊搁崐宄懊归崶褏鏆﹂柛顭戝亝閸欏繘鏌熼幆鏉啃撻柛濠傛健閺屻劑寮村Δ鈧禍鎯ь渻閵堝骸骞栭柣蹇旂箚閻忔帡姊洪崗鑲┿偞闁哄懏绻堣棟妞ゆ牜鍋為崐鍨殽閻愯尙浠㈤柛鏃€纰嶉妵鍕晜閸喖绁悗?    - 闂傚倸鍊搁崐宄懊归崶褏鏆﹂柣銏㈩焾缁愭鏌熼幍顔碱暭闁稿绻濆鍫曞醇濮橆厽鐝旂紓浣界堪閸婃洟婀侀梺缁樏Ο濠囧磿韫囨洜纾奸柟閭﹀弾濞堟粓鏌＄仦鍓р槈闁宠棄顦埢搴ㄥ箛椤旈敮鏋忛梻鍌欐祰椤曆呮崲濡も偓閳诲秹寮撮悩鍐插簥濠电娀娼уú銊у姬閳ь剟姊虹粙鎸庢拱缂佸鍨块、鎾斥槈濡攱鏂€濡炪倖姊婚妴瀣啅閵夛妇绠剧痪顓㈩棑缁♀偓閻庢鍠栭…鐑藉极閹邦厼绶炲┑鐘插楠炴劙姊绘担渚劸妞ゆ垵鎳橀幃妯侯潩鐠哄搫鐎梺鍓茬厛閸ｎ噣宕甸弴銏＄厵闂傚倸顕ˇ锔剧磼閳ь剟宕橀鐣屽帗闂佸憡绻傜€氼剟寮搁妶鍡欑闁哄鍨甸顓㈡煛瀹€瀣М闁诡喒鏅犲畷锝嗗緞鐎ｎ亜澹嶉梻鍌欑濠€閬嶅煕閸儱纾诲┑鐘插€婚弳锕傛煟閵忋埄鐒剧紒鐘烘珪娣囧﹪濡堕崟顓фМ闂侀€炲苯澧柣蹇旀皑閹广垹鈽夐姀鐘殿吅闂佺粯鍨靛Λ鏃堟儉椤忓嫷娓婚柕鍫濇噽缁犱即鎮楀顓熷€愰柟铏崌楠炴劖鎯斿☉妤冪泿闂傚鍋勫ú锕傚箰婵犳艾闂柛婵嗗閺€?DB 缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇幃褰掑箒閹烘垵顬嬬紒鐐礃婵倝骞堥妸銉建闁逞屽墴璺柛宀€鍋涢弸浣糕攽閻樺弶澶勯柣鎾存礋閺屾洘寰勫Ο鐑樼亞缂備降鍔戝褔婀佸┑鐘诧工閸熸壆绮斿ú顏呯厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧吋淇婇幖浣规櫜闁告洦鍘藉畷鐔兼⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸綊妫跨粈渚€鎮″鈧弻鐔告綇閸撗呮殸濡ょ姷鍋戦崹浠嬪蓟瀹ュ棙濮滈柟娈垮枛婵¤棄顪冮妶鍡樷拹闁圭懓娲ら～蹇曠磼濡顎撻梺鍛婄箓鐎氼剚绂掑鈧娲箹閻愯尙浠鹃梺缁樻惈缁绘繈濡存担鍓叉僵濡増绻冮弲锝夋⒑缂佹ê濮€闁哄懏绮撻幃妯荤瑹閳ь剙顫忓ú顏呭仭闂侇叏绠戝▓鑸电節濞堝灝娅嶆い銉︽尰缁旂喖寮撮悢渚祫闁诲函缍嗛崑鍡涘储閸楃偐鏀介柣妯肩帛濞懷勪繆椤愶綆娈滄い銏℃婵＄兘濡?闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晝閳ь剟鎮块鈧弻锝呂旈埀顒勬偋婵犲洤鐭楅煫鍥ㄧ⊕閻撶喖鏌曡箛鏇炐ュù鐘崇洴閺屾稖绠涢弮鍌滅厜闂佸搫鏈惄顖炵嵁濮椻偓閹崇姵锛愬┑鍡樻毉闂傚倷鑳堕…鍫ヮ敄閸℃稑绠查柛銉戝懏娈惧┑掳鍊撶粈浣烘閻愭祴鏀介柣妯诲絻閳ь剛鏁婚獮蹇涘Χ閸涱亝鏂€?闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晝閳ь剟鎮块鈧弻锝呂旈埀顒勬偋婵犲洤鐭楅煫鍥ㄧ⊕閻撶喖鏌曡箛鏇炐ュù鐘崇洴閺屾稖绠涢弮鍌滅厜闂佸搫鏈惄顖炪€侀弴銏℃櫜闁糕剝鐟Σ浼存⒒娴ｈ櫣甯涢柟鍛婃倐瀹曟劖绻濆顒傚姦濡炪倖宸婚崑鎾剁磼閻樿尙效鐎规洘娲熷畷锟犳倶缂佹ɑ銇濋柡浣稿暣瀹曟帒顫濇潏銊у弰闂傚倷绀佺紞濠偽涢崸妤佸€块柨鏇炲€归崑鍌涚箾閸℃ɑ灏伴柛濠傜仛缁绘盯骞嬮悜鍡曠棯濡炪倕绻愰幊蹇涘矗韫囨稒鐓曢柕澶嬪灍閸嬫捇鏌￠埀顒勬嚍閵夛絼绨婚梺鍝勫暙閸婄懓鈻嶉弴鐔虹闁告瑥顦扮亸锕傛煛瀹€鈧崰鏍箹瑜版帩鏁冩い鎰剁悼閺嗭箓姊绘笟鈧埀顒佺〒閳规帡鏌涢弮鈧崹鍧楁偘椤曗偓瀹曞爼顢楅埀顒佸劔闂備線娼чˇ顓㈠磹閺団懞?    - 闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾鐎规洏鍎抽埀顒婄秵閸犳宕曢幋鐘冲枑闁绘鐗嗙粭鎺旂棯閹勫仴闁哄矉绱曟禒锔炬嫚閹绘帒顫撻梻浣告啞閸ㄨ绻涢埀顒勬煛鐏炲墽娲存鐐叉喘婵℃悂鏁傞悾灞界悼濠碉紕鍋戦崐鎰板疾濠靛绀傛慨妞诲亾鐎殿喛顕ч埥澶愬閻樻鍟嬮梻浣藉亹閳峰牓宕滈敃鈧嵄妞ゆ柨澧界壕钘壝归敐鍥╂憘闁哥偠娅ｇ槐鎺楀焵椤掍胶鐟归柍褜鍓熼崹楣冩晝閸屾岸鏁滃┑掳鍊撶粈浣糕枔濠靛鈷掗柛灞炬皑婢ф稓绱掔€ｎ偄娴€殿喗濞婇獮宥夘敊閸撗嶇闯濠电偠鎻徊鑲╁垝濞嗘挸浼犳繛宸簼閻撴洘淇婇妶鍛殶濠⒀咁仸iew 濠电姷鏁告慨鐑藉极閹间礁纾绘繛鎴欏焺閺佸銇勯幘璺烘瀾闁告瑥绻橀幃妤呮濞戞瑦鍠愰梺娲诲幗閹搁箖鍩€椤掑喚娼愭繛鍙夌墪鐓ら柨鏇炲亰缂嶆牠鏌￠崶鈺€绱崇憸鐗堝笒缁€鍌炴煕韫囨艾浜圭紒瀣川缁辨挻鎷呴幓鎺嶅闂備胶纭堕崜婵堢矙閹烘鍋傞煫鍥ㄧ⊕閻撴洘銇勯幇鍓佹偧缂佺姵鐗犻弻娑㈡晲閸曨厾鐓撻梺鍝勭焿缁绘繂鐣烽崡鐐嶇喖鎳￠妶鍛闂?missing闂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯诲櫧闁活厽鐟╅弻鐔告綇妤ｅ啯顎嶉梺绋款儏椤戝鎮￠锕€鐐婇柕濞р偓濡插牓姊?compute_library_review 闂傚倸鍊搁崐宄懊归崶褏鏆﹂柛顭戝亝閸欏繘鏌ｉ姀銏╃劸缂佲偓婢跺绻嗛柕鍫濇噺閸ｅ湱绱掗幇顓ф疁闁哄矉绻濆畷鍫曞Ψ閵壯傜棯闂備胶顭堢€涒晠銆冮崱妯尖攳濠电姴娲ゅ洿闂佸憡渚楅崰鏍р枍閵堝鈷戦柛婵嗗婵ジ鏌涢幘瀵告噰闁炽儻濡囬幑鍕Ω閿曗偓绾绢垶姊洪幆褏绠抽柟铏崌閵嗗倿鎮介崨濞炬嫼?    """
    required_roles = required_library_roles(spec)
    if not required_roles:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    missing_roles = [r for r in required_roles if r not in assets_by_role]
    if not missing_roles:
        return 0

    latest_project = (
        db.query(DreamweaverProject)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .order_by(DreamweaverProject.updated_at.desc())
        .first()
    )
    if not latest_project:
        # Allow creating/upserting library assets even before any DreamWeaver run exists.
        latest_project = _ensure_library_anchor_project(db, project_id=project_id, user_id=user_id)

    runtime_meta = _infer_latest_runtime_meta(latest_project)
    entity_by_role: Dict[str, Dict[str, Any]] = {}
    for key in ("characters", "scenes", "props"):
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        default_entity_type = "character" if key == "characters" else "scene" if key == "scenes" else "prop"
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            name = str(item.get("name") or "").strip()
            descriptor = str(item.get("descriptor") or "").strip()
            normalized_entity_type = str(entity_type or "").strip().lower()
            role_meta = {
                "entity_type": entity_type,
                "entity_id": int(entity_id),
                "entity_name": name,
                "descriptor": descriptor,
            }
            if normalized_entity_type == "character":
                for role in build_character_view_roles(int(entity_id)):
                    entity_by_role[role] = dict(role_meta)
                continue
            try:
                role = build_library_role(entity_type=entity_type, entity_id=entity_id)
            except Exception:  # noqa: BLE001
                continue
            entity_by_role[role] = role_meta

    created = 0
    for role in missing_roles:
        entity_meta = entity_by_role.get(role) or {}
        meta = {**runtime_meta, **entity_meta}
        if not str(meta.get("prompt") or "").strip():
            entity_type = str(entity_meta.get("entity_type") or "").strip()
            entity_name = str(entity_meta.get("entity_name") or "").strip()
            descriptor = str(entity_meta.get("descriptor") or "").strip()
            if entity_type and entity_name and descriptor:
                preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
                style = str(meta.get("style_prompt") or "").strip() or style_prompt_for_preset(preset)
                ratio = normalize_frame_ratio(meta.get("ratio") if isinstance(meta.get("ratio"), str) else None)
                prompt = build_library_prompt(
                    entity_type=entity_type,
                    name=entity_name,
                    descriptor=descriptor,
                    style_prompt=style,
                    ratio=ratio,
                )
                meta["prompt"] = prompt
                meta["suggested_prompt"] = prompt
        uri = default_library_asset_uri(project_id=project_id, role=role)
        db.add(
            DreamweaverAsset(
                dreamweaver_project_id=int(latest_project.id),
                episode_id=None,
                shot_id=None,
                asset_type="image",
                role=str(role),
                uri=str(uri),
                schema_version=str(getattr(latest_project, "schema_version", "") or "0.1.0"),
                meta_json=meta,
            )
        )
        created += 1

    if created:
        db.commit()
    return created


def compute_library_review(
    *,
    spec: Dict[str, Any],
    assets_by_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    required_roles = required_library_roles(spec)

    missing: List[str] = []
    unapproved: List[str] = []
    for role in required_roles:
        asset = assets_by_role.get(role)
        if not isinstance(asset, dict):
            missing.append(role)
            continue
        uri = asset.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            missing.append(role)
            continue
        if "://" not in uri:
            p = resolve_asset_path(uri)
            base = runs_root_path()
            resolved = p.resolve()
            if (resolved != base and base not in resolved.parents) or not resolved.exists():
                missing.append(role)
                continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        if not bool(meta.get("approved")):
            unapproved.append(role)

    return {
        "required_roles": required_roles,
        "missing_roles": missing,
        "unapproved_roles": unapproved,
        "approved": len(missing) == 0 and len(unapproved) == 0,
    }


def approve_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    roles: Iterable[str],
    approved: bool = True,
) -> int:
    roles_set = {str(r) for r in roles if isinstance(r, str) and is_library_role(r)}
    if not roles_set:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    ids = []
    for role in roles_set:
        asset = assets_by_role.get(role)
        if isinstance(asset, dict) and isinstance(asset.get("id"), int):
            ids.append(int(asset["id"]))

    if not ids:
        return 0

    rows = db.query(DreamweaverAsset).filter(DreamweaverAsset.id.in_(ids)).all()
    updated = 0
    for row in rows:
        # SQLAlchemy JSON fields need dict copy to persist meta updates.
        meta = dict(row.meta_json) if isinstance(row.meta_json, dict) else {}
        meta["approved"] = bool(approved)
        row.meta_json = meta
        updated += 1

    db.commit()
    return updated


def resolve_asset_path(uri: str) -> Path:
    normalized = _normalize_local_asset_uri(uri)
    p = Path(str(normalized)).expanduser()
    if p.is_absolute():
        return p
    return _backend_root_dir() / p


def enrich_payload_with_library(
    db: Session,
    payload: Dict[str, Any],
    *,
    project_id: int,
    user_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    chapter_ids = payload.get("chapter_ids") if isinstance(payload.get("chapter_ids"), list) else []
    script_entities = payload.get("script_entities") if isinstance(payload.get("script_entities"), dict) else None
    existing_spec = payload.get("asset_library_spec") if isinstance(payload.get("asset_library_spec"), dict) else None
    run_scoped = bool(chapter_ids)

    if run_scoped:
        if isinstance(script_entities, dict):
            spec_candidate = build_library_spec_from_script_entities(
                db,
                project_id=project_id,
                entities=script_entities,
            )
            spec = spec_candidate if has_any_library_entities(spec_candidate) else empty_library_spec(project_id=project_id)
        elif isinstance(existing_spec, dict) and has_any_library_entities(existing_spec):
            spec = existing_spec
        else:
            # Run-scoped payload must not fall back to full-project spec.
            spec = empty_library_spec(project_id=project_id)
    else:
        spec = build_library_spec(
            db,
            project_id=project_id,
            max_characters=max_characters,
            max_scenes=max_scenes,
            max_props=max_props,
        )
    spec = strip_crowd_characters_from_spec(db, project_id=project_id, spec=spec)
    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role)

    payload["asset_library_spec"] = spec
    payload["project_assets"] = list(assets_by_role.values())
    payload["asset_library_review"] = review
    scope_chapter_ids: List[int] = []
    for raw_id in chapter_ids:
        try:
            scope_chapter_ids.append(int(raw_id))
        except Exception:  # noqa: BLE001
            continue
    payload["asset_library_scope"] = {
        "mode": "run_scoped" if run_scoped else "project_scoped",
        "run_scoped": bool(run_scoped),
        "has_script_entities": bool(isinstance(script_entities, dict)),
        "chapter_ids": scope_chapter_ids,
    }
    payload.setdefault(
        "asset_library_config",
        {"max_characters": max_characters, "max_scenes": max_scenes, "max_props": max_props},
    )
    return review


