---
kind: external_dependency
name: StepAudio Contextual TTS
slug: stepaudio-tts
category: external_dependency
category_hints:
    - vendor_identity
    - auth_protocol
scope:
    - '**'
---

Contextual TTS和Zero-shot音色复刻服务，通过STEP_API_KEY或STEPFUN_API_KEY鉴权。基础URL为https://api.stepfun.com/v1。支持上下文感知的语音合成和零样本音色克隆，适合需要高度个性化语音的场景。代码会自动按STEP_API_KEY -> STEPFUN_API_KEY顺序查找密钥。