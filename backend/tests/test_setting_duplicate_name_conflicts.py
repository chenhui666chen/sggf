"""?????????????????????"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.setting_consistency import SettingConsistencyService


def _item(item_id: int, collection: str, content: str):
    return {"id": item_id, "collection": collection, "content": content}


def test_complementary_cross_collection_same_name_is_not_conflict():
    conflicts = SettingConsistencyService.collect_duplicate_name_conflicts(
        {
            "问心侦探社": [
                _item(1, "地图体系", "顾沉舟经营的侦探社，位于老城厢。"),
                _item(2, "组织势力体系", "类型：势力\n\n问心侦探社是顾沉舟继承的侦探社。"),
            ],
            "巡捕房": [
                _item(3, "地图体系", "当地官方治安机构。"),
                _item(4, "组织势力体系", "类型：势力\n\n巡捕房是老城厢的治安机构。"),
            ],
            "回响": [
                _item(5, "角色体系", "类型：异能\n\n顾沉舟的特殊能力。"),
                _item(6, "异能体系", "顾沉舟的特殊能力，触碰遗物感知声音。"),
            ],
            "戏妆": [
                _item(7, "道具遗物体系", "死者脸上的戏妆。"),
                _item(8, "民生风俗体系", "类型：风俗\n\n死者脸上的戏妆。"),
            ],
        }
    )
    assert conflicts == []


def test_same_facet_or_contradictory_duplicate_still_conflicts():
    same_facet = SettingConsistencyService.collect_duplicate_name_conflicts(
        {
            "巡捕房": [
                _item(1, "组织势力体系", "老城厢治安机构。"),
                _item(2, "组织势力体系", "租界私军力量，与官府无关。"),
            ]
        }
    )
    assert len(same_facet) == 1
    assert same_facet[0]["name"] == "巡捕房"

    contradictory = SettingConsistencyService.collect_duplicate_name_conflicts(
        {
            "回响": [
                _item(3, "角色体系", "顾沉舟的异能，触碰死者即可发动。"),
                _item(4, "异能体系", "回响已被废弃，顾沉舟从未拥有该能力。"),
            ]
        }
    )
    assert len(contradictory) == 1
    assert contradictory[0]["name"] == "回响"


def test_same_collection_conflict_not_hidden_by_complementary_item():
    conflicts = SettingConsistencyService.collect_duplicate_name_conflicts(
        {
            "\u5de1\u6355\u623f": [
                {"id": 1, "collection": "\u7ec4\u7ec7\u52bf\u529b\u4f53\u7cfb", "content": "\u8001\u57ce\u53a2\u6cbb\u5b89\u673a\u6784\u3002"},
                {"id": 2, "collection": "\u7ec4\u7ec7\u52bf\u529b\u4f53\u7cfb", "content": "\u79df\u754c\u79c1\u519b\u529b\u91cf\uff0c\u4e0e\u5b98\u5e9c\u65e0\u5173\u3002"},
                {"id": 3, "collection": "\u5730\u56fe\u4f53\u7cfb", "content": "\u5de1\u6355\u623f\u5ea7\u843d\u5728\u6cb3\u53e3\u3002"},
            ]
        }
    )
    assert len(conflicts) == 1
    assert conflicts[0]["name"] == "\u5de1\u6355\u623f"
