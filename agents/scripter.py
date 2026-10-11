# -*- coding: utf-8 -*-
"""剧本引擎入口（Phase 2.2 · AI Director OS · 2026-10-07 原地重写）。

旧版 Markdown 剧本生成逻辑已删除（v1.5 重建决策），
实现迁移至 agents/scripter_pkg/：
  冻结章节(只读) → Story Graph → 结构化剧本 JSON（beat 七族）
  → CCV 协作环 + 闭合动作词典 → 3E 完整性门 → 人工审核门

对外契约不变：run(ctx) -> None，产物写 ctx.payload；
script_requires_review=True 时状态机转 WAITING_SCRIPT_APPROVAL。

历史版本备份见 git（本文件为 v2 重写，旧实现约 1300 行）。
"""
from agents.scripter_pkg import AudioMarker, CharacterProfile, run  # noqa: F401

__all__ = ["run", "CharacterProfile", "AudioMarker"]
