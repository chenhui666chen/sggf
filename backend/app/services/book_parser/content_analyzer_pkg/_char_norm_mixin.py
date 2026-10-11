from __future__ import annotations

import os
import json
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from core.unified_llm_client import get_llm_client, UnifiedLLMClient
from core.model_resolution import TaskType
from ..chapter_splitter import ChapterInfo, ChapterType
from ._base import AnalysisResult

logger = logging.getLogger(__name__)

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class AnalysisType(str, Enum):
    """分析类型"""
    CHARACTERS = "characters"
    WORLDVIEW = "worldview"
    PLOT = "plot"
    STYLE = "style"
    CONCEPTS = "concepts"
    THEMES = "themes"
    CHAPTER_SUMMARY = "chapter_summary"


@dataclass
class ChapterSummary:
    chapter_index: int
    title: str
    summary: str
    characters: List[str]
    key_events: List[str]



class CharNormMixin:
    @classmethod
    def _normalize_character_entries(cls, parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将人物分析结果统一整理为单一 characters 列表。"""
        if not isinstance(parsed, dict):
            return []

        raw_characters = parsed.get("characters")
        if not isinstance(raw_characters, list):
            raw_characters = []
            for bucket_name in ("main_characters", "supporting_characters"):
                bucket = parsed.get(bucket_name) or []
                if isinstance(bucket, list):
                    raw_characters.extend(bucket)

        deduped: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for raw_item in raw_characters:
            if not isinstance(raw_item, dict):
                continue
            normalized_item = cls._canonicalize_character_entry(raw_item)
            name = str(normalized_item.get("name") or "").strip()
            if not name:
                continue
            if name in deduped:
                deduped[name] = cls._merge_character_payload(deduped[name], normalized_item)
                continue
            deduped[name] = normalized_item
            order.append(name)

        return [deduped[name] for name in order]

    @classmethod
    def _replace_character_entries(cls, parsed: Dict[str, Any], characters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """回写标准化后的单一人物列表，并移除旧桶字段。"""
        normalized = dict(parsed or {})
        normalized["characters"] = characters
        normalized.pop("main_characters", None)
        normalized.pop("supporting_characters", None)
        normalized.pop("minor_characters", None)
        return normalized

    @staticmethod
    def _is_likely_character_name(name: str) -> bool:
        """基于简单规则过滤明显不是人物的词。"""
        text = str(name or "").strip()
        if len(text) < 2 or len(text) > 4:
            return False
        if re.search(r'[^\u4e00-\u9fff]', text):
            return False

        stopwords = {
            "灰烬区", "水晶区", "记忆", "数据", "系统", "接口", "诊所", "技术员",
            "技术人", "人员", "局长", "母亲", "妹妹", "年轻人", "控制台", "界面",
            "传送带", "扫描仪", "日志", "样本", "设备", "空气", "晨光", "街区",
            "诊疗室", "忆晶", "信号", "代码", "光芒", "波动", "照片", "中心",
        }
        if text in stopwords:
            return False

        common_surnames = set(
            "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
            "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方"
            "俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮"
            "卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计"
            "伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江"
            "童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经"
            "房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁"
            "荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车"
            "侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶"
            "司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴鬱胥能苍"
            "双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀郏"
            "浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居"
            "衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖"
            "融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯"
            "盖益桓公"
        )
        prefix_titles = {"小", "老", "阿"}
        invalid_name_chars = set("说道问答喊看想知在的了着呢吗吧呀么得将于与及并向从给被把让喃")

        if text[0] in prefix_titles:
            if len(text) < 2 or text[1] not in common_surnames:
                return False
        elif text[0] not in common_surnames:
            return False

        if any(ch in invalid_name_chars for ch in text[1:]):
            return False

        invalid_suffixes = (
            "区", "街", "城", "市", "镇", "村", "国", "州", "界", "门", "派", "宗",
            "会", "院", "局", "室", "楼", "站", "厂", "组", "队", "节", "器", "码",
        )
        if text.endswith(invalid_suffixes):
            return False

        return True

    def _extract_character_names_from_text(self, text: str, limit: int = 8) -> List[str]:
        """在无模型时，从正文里粗提人物名。"""
        if not text:
            return []

        patterns = [
            r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?=的(?:指尖|声音|目光|手指|眼神|袖口|肩膀|档案|神经接口|照片))',
            r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?=(?:说|道|问|答|喊|念着|喃喃|低声|提醒|皱眉|起身|走近|转身|离开|看向|看着|想起|调取|穿过|见到|监测到|重新校准))',
            r'档案显示[:：]\s*([\u4e00-\u9fff]{2,4})',
            r'编号[\dA-Za-z]+批次[^。！？\n]{0,40}?([\u4e00-\u9fff]{2,4})',
        ]

        counters: Dict[str, int] = {}
        for pattern in patterns:
            for raw_name in re.findall(pattern, text):
                name = str(raw_name or "").strip()
                if not self._is_likely_character_name(name):
                    continue
                counters[name] = counters.get(name, 0) + 1

        ordered = sorted(counters.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
        return [name for name, _ in ordered[:limit]]

