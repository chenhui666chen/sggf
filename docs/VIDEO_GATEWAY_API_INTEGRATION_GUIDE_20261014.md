# 视频生成网关 API 接入文档

> Base URL：`https://api.sggf.net`
> 成片域名：`https://video.sggf.net`
> 协议风格：OpenAI Videos 风格子集（HTTPS + JSON + Bearer Token，异步任务）
> 文档版本：v1.4（2026-10-14，W8 新增快乐马 1.1 单图 i2v 质量组 `happyhorse-1.1`：480p/16:9/3–15s/按条 ¥1.45，task 82115 付费实证强采纳；Grsai H3 图生付费单挂起失败，`minimax-h3` 经 Grsai 路线暂不支持图生）
> v1.3（2026-10-14，按最新代码复核；W7 纯参考视频付费实证：贰春 wan3 + 算力 7 条 wan3 共 8 条路线全部补入 §5/§6.1，含算力参考片按时长计费说明）
> 适用接口版本：gateway g5 商用版（API Key 鉴权、应用限流、内部管理端点）

---

## 1. 服务简介

视频生成网关在多家视频生成供应商之上提供**统一的异步 HTTP 接口**，调用方无需关心供应商差异：

- **统一契约**：一套请求结构覆盖文生视频、图生视频、首尾帧、参考视频、对口型、图/视/音多素材混合六种模式。
- **自动选路**：按"模型质量组 + 分辨率 + 画幅 + 时长 + 素材结构"自动选择可用路线，并按滚动成功率与期望成本排序。
- **故障切换**：某条路线明确失败后自动切换备选路线重试（可用 `allow_switch` 关闭）；支持可选的并发对冲（`allow_hedge`）。
- **永久成片地址**：生成成功的视频自动转存到自有对象存储，通过 `https://video.sggf.net/...` 返回**永久有效的 HTTPS 直链**；上游的临时签名地址不会暴露给调用方。
- **安全**：Key 鉴权、内容风险前置拦截、任务按调用方隔离、错误响应不回传任何供应商细节。

### 1.1 两个域名的分工

| 域名 | 用途 | 调用方是否需要访问 |
|---|---|---|
| `https://api.sggf.net` | 下单、轮询等全部 API 调用 | 是 |
| `https://video.sggf.net` | 成片静态分发（GET 下载/播放，公有读） | 是（最终用户播放） |

---

## 2. 接入准备

### 2.1 获取 API Key

联系服务方开通调用账号，获得一对凭证：

- `client_id`：调用方唯一标识（UUID，用于对账，不作为密钥使用）；
- `api_key`：随机字符串，**仅在开通时展示一次，请妥善保存**；服务端只保存不可逆哈希，遗失后只能重新发卡/轮换。

Key 可由服务方随时吊销；吊销后所有请求立即返回 401。

### 2.2 鉴权方式

所有 `/v1/*` 接口必须携带请求头：

```http
Authorization: Bearer <你的 api_key>
```

- 缺失、错误或已禁用的 Key 统一返回 `401`，响应不区分"Key 不存在"与"任务不属于该 Key"，以防枚举探测。
- 请使用 HTTPS；不要把 Key 放在 URL query 中。

可选请求头 `x-client-key`：透传你侧的终端用户标识（字符串），仅用于对账与风控，不参与鉴权。

### 2.3 最小成本联调建议

最便宜的联调单：`model="minimax-h3-light"`、`resolution="480p"`、`duration_seconds=1`，
闲时单条约 ¥0.02–0.03（实际以提交时报价与上游账单为准）。

---

## 3. 快速开始

### 3.1 流程总览

```
POST /v1/videos          → 202 + 任务 id（受理，不代表成片）
GET  /v1/tasks/{id}      → 轮询，直到 status = succeeded / failed / unsupported
成功后取 content_url     → https://video.sggf.net/... 永久直链
```

视频渲染通常需要 **1–5 分钟**（视模型与排队情况而定）。建议轮询间隔 **5–10 秒**；查询接口是只读快照，不会触发上游请求。注意共享 GPU 类档位高峰期排队可能超过 **15 分钟**（实测有排队约 16 分钟才开始渲染的案例），总超时设置与 `deadline_seconds` 请参考第 8 章建议。

### 3.2 curl 示例：文生视频

```bash
# 1) 下单
curl -X POST https://api.sggf.net/v1/videos \
  -H "Authorization: Bearer f-your-api-key" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-20261014-0001" \
  -d '{
    "model": "minimax-h3-light",
    "prompt": "海浪轻拍沙滩，一只白色海鸥低空掠过镜头，远处日出金光铺在水面",
    "duration_seconds": 5,
    "resolution": "480p",
    "aspect_ratio": "16:9"
  }'
```

响应：

```json
{
  "id": "5804090c3f374e5e84e9eb05d415cb7e",
  "status": "running",
  "quality_group": "minimax-h3-light",
  "content_url": null,
  "error": null
}
```

```bash
# 2) 轮询
curl https://api.sggf.net/v1/tasks/5804090c3f374e5e84e9eb05d415cb7e \
  -H "Authorization: Bearer f-your-api-key"
```

成功响应：

```json
{
  "id": "5804090c3f374e5e84e9eb05d415cb7e",
  "status": "succeeded",
  "quality_group": "minimax-h3-light",
  "content_url": "https://video.sggf.net/router_gateway/videos/2026/10/5804090c3f374e5e84e9eb05d415cb7e.mp4",
  "error": null
}
```

### 3.3 Python 示例（下单 + 自动轮询）

```python
import time
import requests

BASE = "https://api.sggf.net"
HEADERS = {
    "Authorization": "Bearer f-your-api-key",
    "Content-Type": "application/json",
    "Idempotency-Key": "order-20261014-0001",
}

def create_video(payload: dict, idem_key: str) -> dict:
    r = requests.post(
        f"{BASE}/v1/videos",
        headers={**HEADERS, "Idempotency-Key": idem_key},
        json=payload, timeout=30,
    )
    r.raise_for_status()          # 4xx 请按第 7 章错误码处理
    return r.json()

def wait_task(task_id: str, interval: float = 8, timeout: float = 900) -> dict:
    url = f"{BASE}/v1/tasks/{task_id}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        body = r.json()
        if body["status"] in ("succeeded", "failed", "unsupported"):
            return body
        time.sleep(interval)
    raise TimeoutError(f"task {task_id} not finished in {timeout}s")

task = create_video(
    {
        "model": "minimax-h3-light",
        "prompt": "海浪轻拍沙滩，一只白色海鸥低空掠过镜头",
        "duration_seconds": 5,
        "resolution": "480p",
        "aspect_ratio": "16:9",
    },
    idem_key="order-20261014-0001",
)
result = wait_task(task["id"])
if result["status"] == "succeeded":
    print("成片：", result["content_url"])
else:
    print("失败：", result["error"])
```

---

## 4. 接口详情

### 4.1 创建视频任务

```
POST /v1/videos
```

**请求头**

| 头部 | 必填 | 说明 |
|---|---|---|
| `Authorization` | 是 | `Bearer <api_key>` |
| `Content-Type` | 是 | `application/json` |
| `Idempotency-Key` | 是 | 客户端订单号/去重键；1–64 位，**首字符必须是字母或数字**，其余字符允许字母、数字、`.`、`_`、`:`、`-`，相同 Key 的重复提交返回同一任务；同 Key 不同请求返回 `409 idempotency_key_reused` |
| `x-client-key` | 否 | 终端用户标识，仅透传对账 |

**请求体字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | string | 是 | 提示词，1–8000 字符 |
| `duration_seconds` | int | 是 | 时长（秒），正整数；合法范围取决于 model 与路线，见第 5 章，台账范围 1–30 |
| `resolution` | string | 是 | 分辨率档位：`480p` / `720p` / `768p` / `1080p` / `2k`（须与 model 支持的组合匹配，大小写不敏感） |
| `aspect_ratio` | string | 是 | 画幅：`16:9` / `9:16` / `1:1` / `4:3` / `3:4` / `21:9` / `adaptive`（须与 model 支持的组合匹配） |
| `model` | string \| null | 否 | 质量组名（见第 5 章）。**不传表示不限质量组**，由网关在全部满足硬条件的路线中按成本/成功率全局选路 |
| `mode` | string \| null | 否 | 输入模式（见第 6 章）。不传时按素材结构自动仲裁 |
| `allow_switch` | bool | 否 | 默认 `true`。某路线明确失败后是否自动切换备选路线；`false` 时最多只尝试一条路线 |
| `allow_hedge` | bool | 否 | 默认 `false`。是否允许在等待过久时并发派发第二路线"对冲"（会增加费用，谨慎开启） |
| `deadline_seconds` | int \| null | 否 | 等待时限（秒）。超时后对外返回 `deadline_exceeded` 失败；在途供应商仍由后台对账，晚到成片只归档不改写对外失败结果 |
| `reference_images` | array | 否 | 参考图，元素为 `{"url": "..."}`，仅收公网 HTTP(S) URL |
| `reference_videos` | array | 否 | 参考视频，元素为 `{"url": "...", "duration_seconds": 10.5}`；`duration_seconds` 用于 ≤15s 前置校验 |
| `reference_audios` | array | 否 | 参考音频，元素为 `{"url": "..."}` |

素材数量上限：任一单组最多 **30** 个，图/视/音合计最多 **40** 个；单个 URL 长度 ≤ 2048；
参考视频时长硬上限 **15 秒**。超限或 URL 非法在提交前以 `422` 拒绝，**不产生费用**。

**响应**

- `202 Accepted`：任务已受理。响应头 `Location: /v1/tasks/{id}`，响应体为任务快照（见 4.2）。
- `422`：参数不合法、模式与素材矛盾、当前组合无可用路线、内容风险拦截（见第 7 章）。
- `502`：提交阶段所有候选路线即耗尽（罕见），可更换参数或稍后重试。

### 4.2 查询任务

```
GET /v1/tasks/{task_id}
```

只读快照，不回源供应商、不推进状态机。任务只能由创建它的 api_key 查询；查询他人或不存在的任务统一返回 `404 task_not_found`。

**响应字段**

| 字段 | 说明 |
|---|---|
| `id` | 任务 id（32 位 hex） |
| `status` | 任务状态，见第 7.1 节 |
| `quality_group` | 实际选路命中的质量组（可能与请求的 model 不同，例如备选路线属于同组另一档位；跨质量组不会串档） |
| `content_url` | 成片地址，仅 `succeeded` 时非空；`https://video.sggf.net/...` 永久直链 |
| `error` | `null` 或 `{"code": "...", "message": "..."}`，固定中文文案，不含供应商信息 |

### 4.3 健康检查

```
GET https://api.sggf.net/health
```

无需鉴权，正常时返回 `200` 与纯文本 `gateway healthy`。该探针由网关进程**真实应答**（边缘节点只做转发）：网关进程宕机时返回 `502/504`，因此可直接用于存活监控与告警。

---

## 5. 模型（质量组）与能力矩阵

`model` 字段填写**质量组**而非具体供应商模型；同一质量组内可能有多条供应商路线互为备份。

| model（质量组） | 定位 | 分辨率 | 画幅 | 时长（秒） | 支持模式 |
|---|---|---|---|---|---|
| `minimax-h3-light` | 加速轻量版，最便宜，适合走量/预览 | 480p, 768p | 16:9, 9:16, 1:1 | 1–15 | text, multi_image, mixed_multimodal |
| `minimax-h3` | 满血 H3，画质与一致性更强 | 480p, 768p, 1080p, 2k | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9 | 1–15 | text, multi_image, first_last_frame, mixed_multimodal |
| `seedance-2.5` | Seedance 2.5，长时长与叙事表现 | 480p, 720p, 1080p | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9 | 2–30 | text, multi_image |
| `wan3.0` | 万相 3.0，多素材/参考视频能力最全 | 480p, 720p, 1080p | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, adaptive | 2–30 | text, multi_image, video_reference, mixed_multimodal |
| `happyhorse-1.1` | 快乐马 1.1 参考生视频，极速按条（实测约 47s 出片） | 480p | 16:9 | 3–15（仅 5s 付费实证） | multi_image（1–9 张参考图，仅 1 图完成付费实证） |

注意：

1. 矩阵是**质量组的并集**，具体某条供应商路线支持的子集可能更小；提交不被任何路线支持的组合时返回 `422 unsupported_capability`，不扣费。
2. 部分档位有最短时长（如 seedance/wan 多为 4–5s 起），短于路线最小值同样返回 `422`。
3. 不传 `model` 时，满足其余硬条件的**任意质量组**路线都会进入候选，按期望成本排序，可能返回任何质量组的成片——对画质有要求的业务请显式指定 `model`。
4. 各档实际价格、成功率与像素名实差异以服务方台账/报价为准；提交后可通过服务方对账系统按 `client_id` 查询。
5. 矩阵是台账**声明能力**的并集，部分组合仅有单一路线或付费实证覆盖有限：非 16:9 画幅、2K、720p/1080p 的多素材档位实测样本较少；`video_reference`（纯参考视频、无音频）8 条声明路线（贰春 wan3 + 算力 7 条 wan3）已全部完成付费实证（2026-10-14，均轨迹复现验片通过，含 480p 与算力 1080p 档），但需注意算力 480p 档按「输出时长+参考视频时长」同单价计费，调用方成本预估须计入参考片时长；`image_audio_lipsync` 当前台账内**无任何供应商路线**，显式提交或被自动仲裁到该模式都会返回 `422 unsupported_capability`。`happyhorse-1.1` 为 W8（2026-10-14）新接线质量组，单图 480p/5s 已付费实证（task 82115，848x480/24fps/含默认 AAC，按条 ¥1.45，约 47s 出片，参考图强采纳），3–15s 其余时长、2–9 图与非 16:9 画幅上游支持但网关尚未实证、暂不开放；Grsai 提供的 `minimax-h3` 路线图生在 W8 付费实测中长时间挂起失败，该路线当前仅开放 text（同质量组另有其他供应商路线支持图生，自动选路不受影响）。具体开放情况以服务方最新台账确认为准。

---

## 6. 输入模式与参考素材

### 6.1 六种模式

| mode | 含义 | 素材结构要求 |
|---|---|---|
| `text` | 纯文生视频 | 不带任何素材 |
| `multi_image` | 参考图生成 | ≥1 张图；无视频、无音频 |
| `first_last_frame` | 首尾帧强约束 | **恰好 2 张图**（首帧+尾帧）；无视频、无音频 |
| `video_reference` | 参考视频 | ≥1 个视频；**无音频素材**（参考视频本身建议无音轨、≤15s）；8 条声明路线（贰春 wan3、算力 7 条 wan3）均已付费实证（2026-10-14，运动轨迹复现，480p 与算力 1080p 档）；算力 480p 档参考片按时长同单价另计（输出+参考时长）；注意即使不传任何音频，成片仍可能带平台默认 AAC 音轨 |
| `image_audio_lipsync` | 单图+单音对口型 | **恰好 1 图且恰好 1 音**，无视频；自动仲裁仅在该结构时归入此模式；**当前台账无供应商路线支持，提交返回 422 unsupported_capability** |
| `mixed_multimodal` | 图/视/音任意混合的叙事融合 | 至少 1 个任意素材 |

### 6.2 自动仲裁规则（不传 mode 时）

- 无素材 → `text`；
- 仅图片：1 张 → `multi_image`；恰好 2 张 → 经结构判定在 `first_last_frame` / `multi_image` 间选择，低置信度保守按 `multi_image` 处理（保证两张图都用上）；≥3 张 → `multi_image`；
- 含视频、无音频 → `video_reference`；
- 恰好 1 图 + 1 音、无视频 → `image_audio_lipsync`；其他含音频组合 → `mixed_multimodal`；
- 纯音频（无图无视频）非法，返回 `422 invalid_intent`。

显式传 `mode` 时优先级最高，但**必须与素材结构一致**，矛盾请求（如 `mode=text` 却带图）返回 `422 invalid_intent`。业务侧能确定意图时建议显式传 `mode`，避免歧义。

### 6.3 素材 URL 要求

- 必须是**公网可直接 GET 的 HTTP(S) 地址**（网关服务器不经手文件字节，只收 URL）；需要鉴权/防盗链的临时地址请先转为公网可读地址。
- 建议在提交前自行确认 URL 可访问、Content-Type 正确（image/*、video/*、audio/*）。
- 参考视频必须 ≤15s；建议使用无音轨参考视频（`video_reference` 模式）。
- 参考素材仅用于当次生成；成片转存后调用方提供的素材不会被网关二次分发。

### 6.4 多素材请求示例

```json
{
  "model": "wan3.0",
  "prompt": "让参考图中的人物沿着参考视频的镜头轨迹走过街道，背景音乐用参考音频的节奏",
  "duration_seconds": 5,
  "resolution": "720p",
  "aspect_ratio": "16:9",
  "reference_images": [{"url": "https://example.com/char.png"}],
  "reference_videos": [{"url": "https://example.com/motion.mp4", "duration_seconds": 10.0}],
  "reference_audios": [{"url": "https://example.com/beat.mp3"}]
}
```

---

## 7. 状态机与错误码

### 7.1 任务状态

| status | 含义 | 调用方动作 |
|---|---|---|
| `accepted` | 已落库受理，派发中 | 继续轮询 |
| `running` | 已提交上游，渲染/排队中 | 继续轮询（建议 5–10s） |
| `succeeded` | 成片已转存，`content_url` 可用 | 下载/播放 |
| `failed` | 确定失败，`error.code` 给出原因 | 按错误码处理；重试需使用**新的** Idempotency-Key |
| `unsupported` | 该组合无可用能力（`failed` 的独立呈现） | 更换 model/分辨率/时长/比例，不必原样重试 |

### 7.2 错误响应格式

```json
{ "error": { "code": "invalid_api_key", "message": "无效或已禁用的 API Key" } }
```

HTTP 状态码：

| HTTP | 场景 |
|---|---|
| 401 | 缺失/错误/禁用 Key |
| 404 | 任务不存在（或不属于该 Key） |
| 409 | 同一 `Idempotency-Key` 携带了不同的请求内容 |
| 422 | 请求参数/结构错误、模式矛盾、能力不支持、内容风险拦截 |
| 429 | 应用请求速率超限或活动任务达套餐上限（响应带 `Retry-After`） |
| 502 | 提交阶段候选路线全部失败 |
| 503 | 网关限流依赖暂不可用（`rate_limiter_unavailable`，按 `Retry-After` 退避） |
| 500 | 未预期的服务端错误（可稍后重试） |

错误码（`error.code`，稳定可枚举）：

| code | 典型 HTTP | 含义与建议 |
|---|---|---|
| `invalid_api_key` | 401 | 检查 Authorization 头与 Key 状态 |
| `idempotency_key_reused` | 409 | 同一 Idempotency-Key 提交了不同请求内容；检查请求体或更换新键 |
| `client_rate_limit_exceeded` | 429 | 应用请求速率超出套餐限额，按 `Retry-After` 退避，勿立即重试 |
| `client_concurrency_limit_exceeded` | 429 | 活动任务数达套餐上限，响应含当前值/上限；等已有任务终态后再提交 |
| `rate_limiter_unavailable` | 503 | 网关限流组件暂不可用，按 `Retry-After` 有限次退避重试 |
| `invalid_request` | 422 | 字段缺失、越界、素材 URL 非法/超量/参考视频超 15s |
| `invalid_intent` | 422 | mode 与素材结构矛盾，或纯音频等非法素材组合 |
| `unsupported_capability` | 422 | 无支持该组合的路线（也可能在任务终态呈现为 `status=unsupported`） |
| `content_risk_blocked` | 422 | prompt 未通过安全审核，任务被前置拒绝，不产生费用 |
| `all_candidates_failed` | 502 / 任务 failed | 候选路线均明确失败；可稍后用新 Idempotency-Key 重试，或更换参数 |
| `upstream_unknown` | 500 / 任务 failed | 上游结果异常/提交结果未知 |
| `deadline_exceeded` | 任务 failed | 超过 `deadline_seconds` 仍未成片 |
| `task_not_found` | 404 | 任务 id 不存在或不属于当前 Key |

---

## 8. 幂等、重试与超时最佳实践

1. **务必携带 `Idempotency-Key`**：网络超时后可用同一 Key 安全重放，返回的是同一任务，绝不重复下单、重复扣费。
2. **终态任务重放返回现状**：同一 Key 对已 `succeeded`/`failed` 的任务永远返回当时的结果；因此**失败后重试必须换新 Key**（如追加 `-retry1`）。
3. **轮询要宽容**：视频生成耗时以分钟计，建议间隔 5–10s；平峰总超时按 ≥10 分钟预估，高峰或使用共享 GPU 档位时建议 ≥20 分钟（实测排队约 16 分钟后才开始渲染），也可直接设置 `deadline_seconds` 明确截止；不要高频轮询。
4. **成本控制组合拳**：
   - 固定单一路线测试：`model` 钉死 + `allow_switch=false` + `allow_hedge=false`（最多一次尝试）；
   - 要时效可设 `deadline_seconds`；愿意付双倍费用换延迟才开 `allow_hedge=true`。
5. **只信 `content_url`**：成片只从 `video.sggf.net` 取，不要尝试猜测或保存任何上游地址（上游临时地址通常 24h 失效，且网关从不对外返回）。
6. **Worker 重启/发布不丢任务**：任务状态以数据库为唯一事实源，服务重启后会自动接管所有 `accepted/running` 任务继续对账，已提交上游的渲染不会被重复派发；轮询期间遇到 502 可稍后继续查询原任务 id。

---

## 9. 安全与合规

- API Key 等同于账户密码，请勿写入前端代码、App 包或公开仓库；建议在服务端代理调用。
- Prompt 与素材内容须遵守适用法律法规；网关在提交前进行内容风险评估，高风险请求直接拒绝且不产生上游费用。
- 成片直链为公有读（知道完整 URL 即可访问），请勿在 URL 中放置敏感信息；需要访问控制的业务请在自有服务端下载后再分发。
- 服务端日志不记录 Key 与供应商凭证；错误响应不包含供应商名称、上游任务 id、堆栈等内部信息。

---

## 10. FAQ

**Q：不传 model 会选到什么？**
A：在满足分辨率/画幅/时长/模式全部硬条件的路线中，按滚动成功率与期望成本全局排序选路，可能命中任意质量组。生产业务建议显式指定 `model`。

**Q：提交返回 202 后立刻查还是 running？**
A：正常。202 只表示受理成功，渲染在后台进行（通常 1–5 分钟）。请按 5–10s 间隔继续轮询。

**Q：收到 422 unsupported_capability 但确认参数没错？**
A：422 表示当前台账中没有任何启用路线支持该"质量组+分辨率+画幅+时长+模式"组合（或该组合下路线全部不可用）。可放宽条件（如降到 720p/480p、改画幅）、不传 model 走全局选路，或联系服务方确认该档位开放情况。

**Q：失败了会扣费吗？**
A：前置拒绝（参数/模式/能力/内容风险）一律不产生上游费用；供应商秒拒类失败按上游规则通常不计费；已渲染成功的路线按上游账单计费。对账数据按 `client_id` 与任务 id 可查。

**Q：content_url 有效期多久？**
A：`video.sggf.net` 上的成片为永久存储直链，可直接用于分发；如不再需要可联系服务方按任务 id 清理。

**Q：可以提交自己的 OSS/内网素材 URL 吗？**
A：不行。素材 URL 必须从公网无需鉴权即可访问，否则网关无法转交给上游。

---

## 附录 A：请求字段速查

```text
POST https://api.sggf.net/v1/videos
Headers:
  Authorization: Bearer <api_key>        # 必填
  Content-Type: application/json         # 必填
  Idempotency-Key: <业务唯一单号>         # 必填，1..64 位，字母/数字开头
  x-client-key: <终端用户标识>            # 可选

Body:
  model                 string?   质量组，null=全局选路
  prompt                string    1..8000
  duration_seconds     int       >0（各档 1..30）
  resolution           string    480p|720p|768p|1080p|2k
  aspect_ratio         string    16:9|9:16|1:1|4:3|3:4|21:9|adaptive
  mode                 string?   text|multi_image|first_last_frame|
                                  video_reference|image_audio_lipsync|mixed_multimodal
  allow_switch         bool      默认 true
  allow_hedge          bool      默认 false
  deadline_seconds     int?      >0
  reference_images[]   {url}
  reference_videos[]   {url, duration_seconds?}
  reference_audios[]   {url}

GET  https://api.sggf.net/v1/tasks/{id}
GET  https://api.sggf.net/health
```

## 补充：API 应用与配额管理

API Key 由模型中心「视频 API 申请与管理」入口跳转主站用户中心申请。申请创建后为 `pending`，对应网关 Client 默认禁用；超级管理员批准后才变为 `active`。完整 Key 只在创建或轮换成功响应中返回一次，请立即保存，响应使用 `Cache-Control: no-store`。平台只保存 Key 的哈希和前缀；Key 遗失后必须轮换，旧 Key 会立即失效。

默认套餐申请额度如下，超级管理员批准前应检查供应商容量与商务条件；可以在管理控制台按应用调整。选择企业套餐不会自动开通企业额度。

| 套餐 | 请求速率 | 突发容量 | 活动任务 | 最大并行尝试 | 累计任务额度 |
|---|---:|---:|---:|---:|---:|
| standard | 1/秒 | 5 | 5 | 2 | 100 |
| professional | 5/秒 | 20 | 20 | 2 | 100 |
| enterprise | 20/秒 | 100 | 100 | 2 | 100 |

`429 client_rate_limit_exceeded` 表示应用请求速率超限，响应包含 `Retry-After`；`429 client_concurrency_limit_exceeded` 表示活动任务已达上限。Redis 限流依赖不可用时返回 `503 rate_limiter_unavailable`，客户端应按 `Retry-After` 退避。`GET /v1/tasks/{id}` 使用独立查询令牌桶，查询速率为 `max(20, max_active_jobs * 2)` 次/秒，突发容量为其两倍，不占用创建额度。

活动任务包含已对外超时但仍有上游运行、审核或待交付尝试的任务，直到相关尝试结算后才释放。`max_parallel_attempts` 是单个视频任务内部的并行尝试上限，受总尝试次数限制，不是整个应用的 HTTP 并发数。新额度对新建任务生效，已经创建的任务保留创建时的并行尝试策略；同一个幂等键不会因额度调整而变成新订单。

## 补充：第三方平台接入注意事项

同一个 API Key 可以被二次封装平台使用，但平台应按自己的租户或终端用户维护幂等键，并控制本地并发；套餐额度是该 Key 的总额度，不会因为下游平台增加进程而自动扩大。大流量接入应为不同业务或租户申请不同 API 应用，并由平台侧做队列、重试和账单隔离。

超级管理员入口位于主站 `/admin/video-gateway`，可批准申请、暂停/恢复、永久吊销、调整配额，查看供应商凭据是否配置、目录路由启用状态以及最近 24 小时聚合监控。监控包括尝试成功率、P50/P95 延迟、活动任务、待派发任务和客户任务数；成功率和延迟最多采用窗口内最近 10000 条结果事件。凭据已配置不表示供应商实时健康，没有结果事件的路由显示「暂无样本」。

成本仅汇总已保存的 `Attempt.cost`，缺失账单显示「暂无账单」并显示成本未知的尝试数量；报价不作为实际支出。监控不返回供应商 Token、完整 API Key 或原始 Prompt。

Nginx 的每 IP 保护阈值已调整为 500 请求/秒、突发 500、同时请求上限 500，入口超限返回 429；业务配额以应用的 Redis 令牌桶和数据库活动任务额度为准。这些数值是保护阈值，吞吐能力仍需用独立压测和供应商额度验证，不能理解为 SLA。

本地模拟压测已验证共享限流、100 个活动任务边界和同键并发重试，但高 HTTP 并发下出现延迟上升及连接中断。建议将活动任务额度与客户端 HTTP 并发分别控制，轮询采用间隔和随机抖动；生产容量需另行验证。具体环境与结果见 [容量测试报告](VIDEO_GATEWAY_LOADTEST_20261014.md)。

## 当前发布边界

截至本次本地发布准备，生产尚未执行新的数据库迁移、镜像更新或质量抽评部署。生产与预发若未配置内容安全服务、服务故障或返回非法分数，新的视频创建请求返回 `503 content_safety_unavailable`，不会触发生成；已有任务的后续交付不受该故障阻断。质量评价由独立后台执行，同一模型每成功十次抽评一次，不改变任务状态、不重新生成、不向普通用户展示，也不能替代内容安全审核。

发布操作限定为 `scripts/video_gateway_release.ps1` 的只读 `preflight`、显式目录 `backup`、`migrate`、指定镜像 `deploy` 和指定镜像加备份目录的 `rollback`。该脚本不会同步仓库中的其他未完成改动，也不会调用付费生成接口。执行生产写入前仍需单独确认。

## 补充：错误处理建议

客户端应对 `401` 停止重试并检查 Key，对 `409 idempotency_key_reused` 检查请求内容，对应用层 `429` 按 `Retry-After` 退避；入口层 429 没有该头时采用指数退避，对 `502/503` 使用有限次数的指数退避。不要无限重试视频创建请求；同一订单的传输重试必须复用同一 `Idempotency-Key`。确认终态失败后决定发起一笔新订单才使用新键。

## 附录 B：一次完整调用的时序

```text
客户端                    api.sggf.net                 供应商/存储
  │  POST /v1/videos ───────►│ 意图校验→选路→报价→风控
  │◄─── 202 + task id ───────│── 提交渲染 ──────────────►│
  │                           │                           │
  │  GET /v1/tasks/{id} ─────►│ 只读快照（5-10s 轮询）
  │◄─── accepted/running ─────│◄─ 后台 worker 持续对账 ──│
  │   ...（worker 重启不影响）│                           │
  │  GET /v1/tasks/{id} ─────►│ 成片转存自有 OSS
  │◄─── succeeded + url ──────│                    ◄──────│ 成片
  │                           │        video.sggf.net 永久直链
  │  GET/播放 content_url ───────────────────────────────►│
```
