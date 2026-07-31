---
kind: external_dependency
name: MiMo语音合成服务
slug: mimo-tts
category: external_dependency
category_hints:
    - vendor_identity
    - auth_protocol
scope:
    - '**'
---

预置音色、音色设计和音色克隆的TTS服务，支持音频标签控制和自然语言指令。通过MIMO_API_KEY鉴权。适配器的tts.py实现了完整的语音合成功能，包括批量合成和简单合成接口。支持多种音色类型，适合有声书旁白和角色配音场景。