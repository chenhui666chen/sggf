# 本地优先资产架构方案

日期：`2026-04-19`

## 1. 背景

当前项目并不是单一的媒体生成小工具，而是一个完整的小说创作平台，包含：

- 用户、项目、章节、角色、知识图谱、记忆系统等核心创作数据
- Asset Studio 图片 / 视频 / 音频生成
- DreamWeaver 短剧生成与素材资产沉淀
- Audiobook 有声书生成
- 积分、订单、权限、审核、诊断等平台能力

因此，项目不适合整体改造成“纯前端本地存储 + 后端只做代理”的极端模式。

更合理的方向是：

- 核心业务数据继续以服务端数据库为权威
- 大体积媒体结果尽量不做长期服务端持久化
- 用户侧优先持有生成资产本地副本
- 后端继续持有 API Key、鉴权、限流、风控、业务编排能力

这是一套**混合架构**，而不是纯粹的“全本地”或“全云端”。

## 2. 最终结论

本项目的最优方案不是“完全改成纯云端代理模式”，而是：

**核心业务服务端权威 + 媒体资产 local-first + 后端代理与临时资产层**

具体原则如下：

1. 用户、项目、章节、积分、订单、审核、RAG、Agent 编排保留服务端权威。
2. 图片、视频、音频这类大文件结果不再作为长期服务端资产保存。
3. 后端仍然负责：
   - API Key 管理
   - 第三方模型调用
   - 鉴权、限流、风控
   - 临时结果物化与对外受控暴露
4. 前端负责：
   - 将可收录资产下载到本地 IndexedDB
   - 优先展示本地副本
   - 仅将轻量元数据登记到服务端

这套方案兼顾了：

- Key 安全
- 成本控制
- 用户本地掌控资产
- 现有平台能力可持续演进

## 3. 架构定位

本方案本质上属于：

- `BFF (Backend For Frontend)`
- `受控代理网关`
- `本地优先资产存储`
- `服务端权威业务模型`

### 3.1 浏览器侧职责

- 展示和交互
- 本地资产库（IndexedDB）
- 本地优先预览
- 临时草稿与缓存

### 3.2 服务端职责

- 登录态与用户鉴权
- 项目、章节、角色、积分、订单等业务模型
- 第三方媒体模型调用
- 将第三方结果物化为平台内部临时资产
- 资产元数据登记
- 限流、风控、审核、日志、诊断

### 3.3 第三方 AI 服务职责

- 实际的图片 / 视频 / 音频生成能力
- 外部模型推理成本承担方

## 4. 为什么不是纯“云端代理模式”

纯“云端代理模式”对本项目只有一部分适用。

适合纯代理化的部分：

- Asset Studio 的图片 / 视频 / 音频结果
- DreamWeaver 的部分成片和素材收录
- 后续可扩展到 Audiobook 的音频成品

不适合纯本地化的部分：

- 用户账号和权限
- 小说项目、章节正文、角色设定
- 知识图谱和向量检索
- 多智能体任务状态和运行上下文
- 积分、订单、结算
- 审核记录和风控记录

原因很明确：

1. 这些数据需要多设备同步。
2. 这些数据需要服务端可信。
3. 这些数据本身体积很小，节省不了多少存储成本。
4. 这些数据是平台能力的核心，不适合下放到浏览器作为唯一真相源。

## 5. 目标架构

### 5.1 总体结构

```text
┌─────────────────────────────────────────────────────┐
│                   用户浏览器                         │
│                                                     │
│  IndexedDB / Local Asset Vault                      │
│  - 已收录图片                                       │
│  - 已收录视频                                       │
│  - 已收录音频                                       │
│  - 本地 object URL 预览                             │
│                                                     │
│  前端应用状态                                       │
│  - 编辑器 / 用户中心 / Asset Studio                 │
│  - 本地优先读取资产                                 │
└─────────────────────────┬───────────────────────────┘
                          │ HTTPS
                          ▼
┌─────────────────────────────────────────────────────┐
│                平台服务端（FastAPI）                 │
│                                                     │
│  核心业务层                                         │
│  - 用户 / 项目 / 章节 / 角色 / 积分 / 订单          │
│  - DreamWeaver / Audiobook / RAG / Agents           │
│                                                     │
│  媒体代理层                                         │
│  - Asset Studio 生成调用                            │
│  - 第三方结果物化为内部临时资产                     │
│  - /api/v1/asset-studio/files/...                   │
│                                                     │
│  资产元数据层                                       │
│  - user_asset_records 仅存轻量元数据                │
│  - 不长期保存大文件                                 │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                第三方 AI 服务提供商                  │
│  - 百炼 / 豆包 / Vidu / Mureka / 其他媒体模型       │
└─────────────────────────────────────────────────────┘
```

### 5.2 关键数据原则

- **核心业务数据**：服务端权威
- **媒体大文件**：本地优先
- **临时生成结果**：服务端短期存在，作为受控中转层
- **长期可见资产目录**：服务端只保留元数据，不保留大文件本体

## 6. 数据模型设计

本轮将 `user_asset_records` 从旧结构：

- `file_url`
- `preview_url`

升级为统一资产元数据结构。

### 6.1 新字段

`user_asset_records` 关键字段：

- `asset_uuid`
- `storage_mode`
- `source_uri`
- `preview_uri`
- `download_uri`
- `mime_type`
- `file_size`
- `checksum`
- `expires_at`

保留并继续使用的字段：

- `source_module`
- `asset_kind`
- `asset_class`
- `title`
- `description`
- `model_id`
- `generation_mode`
- `tags`
- `metadata_json`
- `source_payload_json`
- `is_favorite`
- `archived_at`

### 6.2 storage_mode 语义

- `temp_cloud`
  - 资产当前只在平台临时资产层存在，适合刚生成未本地镜像的结果。
- `durable_cloud`
  - 资产来源于平台其他长期可访问链路，例如 DreamWeaver 受控下载端点。
- `local_mirror`
  - 资产已在用户浏览器完成本地镜像，同时仍保留服务端或临时端点兜底。
- `local_only`
  - 资产仅存在于本地，服务端只保留登记元数据。

### 6.3 当前采用策略

本轮优先采用：

- Asset Studio 收录结果：`local_mirror`
- DreamWeaver 合成视频 / 素材库收录：`durable_cloud`

## 7. API Contract 设计

### 7.1 Asset Studio 生成返回结构

旧结构的问题：

- 只返回 `outputs[]`
- 前端没有稳定资产主键
- 前端无法区分来源、介质类型、生命周期

新结构：

```ts
interface AssetStudioMediaAsset {
  asset_uuid: string
  media_kind: 'image' | 'video' | 'audio' | string
  storage_mode: 'temp_cloud' | 'durable_cloud' | 'local_mirror' | 'local_only'
  source_uri: string
  preview_uri: string
  download_uri: string
  file_name: string
  mime_type?: string | null
  file_size?: number | null
  expires_at?: string | null
}

interface AssetStudioGenerateResponse {
  kind: string
  mode: string
  model_id: string
  assets: AssetStudioMediaAsset[]
  primary_asset?: AssetStudioMediaAsset | null
  metadata?: Record<string, any>
}
```

收益：

- 前端可以直接按 `asset_uuid` 写入本地资产库
- 用户中心与收录逻辑不再依赖脆弱 URL
- 可以明确区分“临时云端结果”和“本地镜像结果”

### 7.2 User Asset 收录结构

收录接口现在不再接受旧的 `file_url / preview_url`，而是统一接受：

- `asset_uuid`
- `storage_mode`
- `source_uri`
- `preview_uri`
- `download_uri`
- `mime_type`
- `file_size`
- `expires_at`

这样服务端保存的就是**资产描述**，而不是“某个历史链接”。

## 8. 生成与收录链路

### 8.1 Asset Studio 生成链路

1. 前端提交生成请求。
2. 后端调用第三方模型。
3. 如果第三方返回远端 URL，后端先拉取并物化到内部临时目录。
4. 后端向前端返回内部资产描述对象 `assets / primary_asset`。
5. 前端在用户点击“收录”时下载该资产 blob。
6. 前端将 blob 存入 IndexedDB。
7. 前端调用 `/api/v1/user-assets` 仅登记元数据。

### 8.2 用户中心预览链路

1. 用户中心拉取 `user_asset_records`。
2. 前端尝试按 `asset_uuid` 从本地资产库读取 blob。
3. 若本地存在，则生成 object URL 预览。
4. 若本地不存在，则退回：
   - 受保护 DreamWeaver 文件接口
   - `preview_uri`
   - `source_uri`
   - `download_uri`

这保证了：

- 有本地副本时，优先本地展示
- 没有本地副本时，仍能从服务端链路兜底

## 9. 当前已落地内容

本轮已经完成的代码级改造如下：

### 9.1 后端

- `user_asset_records` 模型升级为新资产字段结构
- `user-assets` schema 与 API 升级为新 contract
- 新增开发期迁移：
  - 直接重建 `user_asset_records` 表
  - 不兼容旧结构
- `Asset Studio` 返回结构升级为 `assets / primary_asset`
- `Asset Studio` 对第三方远端结果先做内部物化，再对前端暴露平台内地址

### 9.2 前端

- API 类型定义切到新 contract
- 新增 `localAssetVault`，基于 IndexedDB 保存本地资产 blob
- `Asset Studio` 收录流程改为：
  - 下载 blob
  - 写本地资产库
  - 再写服务端资产元数据
- 用户中心预览改为：
  - 本地副本优先
  - 云端受控地址兜底
- DreamWeaver 资产收录 payload 已同步新字段

## 10. 当前未落地内容

以下内容尚未纳入本轮：

### 10.1 Audiobook 主链路

暂未把 Audiobook 成品音频统一接入本地优先资产抽象。

原因：

- 涉及异步任务、状态恢复、计费与运行期持久化
- 改造风险高于本轮目标

### 10.2 PWA / OPFS

当前本地资产层先基于 IndexedDB。

尚未做：

- PWA 安装态
- Service Worker
- OPFS 文件级存储
- 离线包策略

### 10.3 真正的纯流式代理

本轮 `Asset Studio` 对第三方远端 URL 的处理仍然是：

- 先由后端下载到临时内部资产目录
- 再返回内部链接

这比“直接暴露第三方 URL”更安全、更稳，也更适合作为第一阶段。

但它还不是最终形态的“全程内存流式 pipe”。

### 10.4 真实环境迁移执行与联调

本轮完成的是：

- 代码
- schema
- contract
- 迁移文件

还没有在本地开发库上执行真实迁移，也还没有跑完整的手工联调回归。

## 11. 为什么这版方案是当前最优解

### 11.1 相比纯服务端存储

优势：

- 降低媒体长期存储成本
- 降低大文件长期治理成本
- 用户更容易形成“资产在自己手里”的心理预期

### 11.2 相比纯浏览器本地化

优势：

- 保留多设备同步与平台权威业务能力
- 保留积分、订单、审核、风控可信性
- 不破坏现有项目型产品架构

### 11.3 相比一步到位的大重构

优势：

- 改造边界清晰
- 风险可控
- 已有平台模块不必一起重写
- 可以先从媒体资产层拿到最大收益

## 12. 推荐推进顺序

### 阶段 1：当前已完成

- Asset Studio local-first 收录闭环
- 用户资产新模型
- 用户中心本地优先预览
- DreamWeaver 收录字段切换

### 阶段 2：建议下一步

1. 执行数据库迁移并完成联调
2. 为 Asset Studio 增加更明确的资产生命周期管理
3. 将 Audiobook 成品音频接入同一套资产抽象

### 阶段 3：中期增强

1. 引入 PWA
2. 评估 IndexedDB -> OPFS 的演进
3. 增加本地资产导出 / 备份提示
4. 增加本地资产缺失检测与重建策略

### 阶段 4：长期优化

1. 将临时资产层从“下载落临时目录”演进为真正的流式代理
2. 完善媒体清理策略与 TTL
3. 将更多媒体产物纳入统一资产生命周期管理

## 13. 一句话结论

本项目当前最优方案不是“全量改成纯云端代理模式”，而是：

**让核心业务继续服务端权威，让媒体资产转向 local-first，并由后端承担受控代理与临时资产层。**

这套方案既符合当前平台型产品的实际结构，也能以最小风险逐步逼近“用户持有数据、平台掌控密钥、整体成本更低”的目标。
