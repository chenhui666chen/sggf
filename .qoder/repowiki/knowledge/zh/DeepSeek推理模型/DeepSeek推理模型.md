---
kind: external_dependency
name: DeepSeek推理模型
slug: deepseek
category: external_dependency
category_hints:
    - vendor_identity
    - auth_protocol
scope:
    - '**'
---

项目中的严谨推理与复审入口，主要承担逻辑审校、结构检查、世界观约束和高难度判断任务。通过DEEPSEEK_API_KEY鉴权，基础URL为https://api.deepseek.com。当前项目配置deepseek-v4-flash为默认模型，deepseek-v4-pro用于高质量审校场景。不支持embedding功能，会回退到其他实现。