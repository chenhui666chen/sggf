---
kind: external_dependency
name: Vidu可控音效生成服务
slug: vidu-sound-effects
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

可控文生音效模型，支持通过时间轴控制多个音效事件，适合视频音效和有声小说音效生成。通过VIDU_API_KEY鉴权，基础URL为https://api.vidu.cn/ent/v2。当前接入vidu-timing2audio模型，支持多事件重叠合成，每个事件的时间区间需明确指定from和to参数。时长建议10秒左右，适合大多数音效场景。