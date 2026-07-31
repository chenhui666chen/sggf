---
kind: external_dependency
name: Mureka纯音乐生成服务
slug: mureka-music
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
---

资产工作台的纯音乐与氛围配乐生成服务，适合为镜头、预告片和有声内容快速生成可试听配乐。通过MUREKA_API_KEY鉴权，基础URL为https://api.mureka.ai。当前接入mureka-o1-instrumental模型，专注于背景音乐生成，不适合对白或歌词演唱。后端通过独立的服务入口调用，输出文件保存到资产目录。