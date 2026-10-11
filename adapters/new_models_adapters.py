# -*- coding: utf-8 -*-
"""
Backward-compatible re-export hub.
All adapters have been split into per-platform modules:
  - adapters.dashscope.*    (百炼: Wan, Qwen, Kling, PixVerse, MiniMax, CosyVoice)
  - adapters.volcengine.*   (火山方舟: Doubao Seedream, Seedance, Seed)
  - adapters.vidu_platform.* (Vidu: video)
  - adapters.mureka.*       (Mureka: o1-instrumental)

Import from this module for backward compatibility,
or import directly from the specific platform module.
"""

from adapters.dashscope import *
from adapters.volcengine import *
from adapters.vidu_platform import *
from adapters.mureka import *
