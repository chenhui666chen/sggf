# -*- coding: utf-8 -*-
"""剧本引擎（Phase 2.2 · AI Director OS）

原地重写自旧 agents/scripter.py 的 Markdown 剧本生成逻辑。新流程：
冻结章节(只读) → Story Graph 摄取 → 结构化剧本 JSON（场→beat 数组，七族路由）
→ CCV 协作环 + 闭合动作词典校验 → 3E 完整性门 → 人工审核门。

知识来源：config/director_knowledge/（SSOT 派生，Phase 2.1 产物）。
资源复用遵循 adaptation_resource_protocol（唯一文本源=冻结章节，只读复用+provenance）。
"""
from agents.scripter_pkg._compat import AudioMarker, CharacterProfile
from agents.scripter_pkg._run import run

__all__ = ["run", "CharacterProfile", "AudioMarker"]
