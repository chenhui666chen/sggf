# Seed-TTS 2.0 Expressive WebSocket 批量验证报告

> ⚠️ 2026-10-11 更正：本报告是 2026-06-25 的历史快照，以下四点已被后续事实推翻，请勿当作现状引用。
> 1. 「**必须**使用 WebSocket，不支持 HTTP API」不成立。HTTP 单向端点 `/api/v3/tts/unidirectional` 真实可出音频：2026-10-10 实测官方头形状 11/11 出音频，带上 `X-Api-App-Key` 时返回 200 但响应体无音频（`docs/TTS_PROMPT_EVIDENCE_20261010.md` §12.2）。
> 2. 下方两次批量验证 0 成功，是二进制帧协议尚未修好时的记录。2026-10-11 生产 `TTSEngine.synthesize` 链路单次 WS 调用已真实返回 25965 字节 ID3 头 MP3（端到端 1630ms、音频 3240ms），未触发 HTTP 兜底；WS 是合成主路径，HTTP 是无音频兜底。
> 3. 音色数量：目录 `shared/seed_tts_2_0_voices.json` 当前为 **277 条**，本报告的 99 条是当时快照。
> 4. 同日还有一次 HTTP 单向端点逐音色批量（`backend/tests/seed_tts_voice_verification_results.json`，7 成功 / 92 失败），失败全是 `200 + text/plain` 无音频。**这份结果已作废**：生成脚本发送了 `X-Api-App-Key`（`scripts/verify_seed_tts_voices.py`，已于 2026-10-11 删除），而 2026-10-10 已实测该头会让单向端点返回 200 但无音频；2026-10-11 音色画像批量用生产链路逐条真实合成，那 92 个 speaker **全部通过**客观闸门（`shared/seed_tts_2_0_voice_profiles.json`，277 条 `objective.passed` 全为 true）。所以那 92 条是脚本侧假失败，不能读成「92 个音色无效」。
>
> 现行事实以 `docs/MODEL_INTEGRATION_REFERENCE.md` §11.4 与 `config/models.yaml` 的 `seed-tts-2.0-expressive` 卡片为准。

## 执行时间
2026-06-25

## 验证目标
对99个Seed-TTS 2.0 Expressive音色进行WebSocket批量验证

## 技术背景

### 协议要求
Seed-TTS 2.0 Expressive **必须**使用WebSocket双向流式协议,不支持HTTP API。

- **WebSocket URL**: `wss://openspeech.bytedance.com/api/v3/tts/bidirection`
- **认证方式**: Header传递
  - `X-Api-Key`: API密钥
  - `X-Api-Resource-Id`: `seed-tts-2.0`
  - `X-Api-Connect-Id`: UUID (每次连接唯一)
  - `X-Control-Require-Usage-Tokens-Return`: `*`

### 协议格式
火山引擎使用**自定义二进制帧协议**,不是纯JSON:

#### 二进制帧结构
```
+--------+--------+--------+--------+
| Header (4 bytes)                    |
+--------+--------+--------+--------+
| Event Type (4 bytes, big-endian)   |
+--------+--------+--------+--------+
| Session ID Length (4 bytes)        |
+--------+--------+--------+--------+
| Session ID (variable length)       |
+--------+--------+--------+--------+
| Payload Length (4 bytes)           |
+--------+--------+--------+--------+
| Payload (variable length)          |
+--------+--------+--------+--------+
```

#### Header格式(4字节)
- Byte 1: version(4 bits) + header_size(4 bits)
- Byte 2: has_event_type(4 bits) + serialization_method(4 bits)
- Byte 3: flags(4 bits) + compression(4 bits)
- Byte 4: reserved(8 bits)

#### 关键事件类型
- START_CONNECTION = 1
- CONNECTION_STARTED = 50
- START_SESSION = 100
- SESSION_STARTED = 150
- TASK_REQUEST = 200
- TTS_RESPONSE = 352 (音频数据)
- SESSION_FINISHED = 152
- FINISH_CONNECTION = 2

## 当前进展

### ✅ 已完成
1. 识别出需要使用二进制帧协议(不是纯JSON)
2. 成功实现StartConnection帧的构建
3. 能够建立WebSocket连接并收到CONNECTION_STARTED响应
4. 创建了批量验证脚本框架

### ❌ 待解决
1. **StartSession帧格式问题**: 
   - 错误: "autoAssignedSequence mismatch"
   - 原因: 序列号字段配置不正确
   
2. **消息解析问题**:
   - 错误: "unpack requires a buffer of 4 bytes"
   - 原因: 收到的消息长度不足,或解析逻辑有误
   
3. **连接稳定性问题**:
   - 错误: "no close frame received or sent"
   - 原因: WebSocket异常关闭,可能是协议错误或超时

## 参考实现

基于用户提供的官方Python示例代码:

```python
import asyncio
import websockets

URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

headers = {
    "X-Api-Key": "your_api_key",
    "X-Api-Resource-Id": "seed-tts-2.0",
    "X-Api-Connect-Id": str(uuid.uuid4()),
    "X-Control-Require-Usage-Tokens-Return": "*",
}

websocket = await websockets.connect(
    URL, additional_headers=headers, max_size=10 * 1024 * 1024
)

# 使用专门的协议模块处理二进制帧
from protocols import (
    start_connection,
    start_session,
    task_request,
    finish_session,
    finish_connection,
    receive_message,
    wait_for_event,
    EventType,
    MsgType,
)

await start_connection(websocket)
await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)

# ... 继续会话流程
```

## 下一步行动

### 方案A: 获取完整的protocols.py模块
1. 从火山引擎官方SDK或示例代码中获取`protocols.py`
2. 该模块包含所有二进制帧构建和解析的正确实现
3. 基于此模块完成批量验证脚本

### 方案B: 深入研究官方文档
1. 访问 https://www.volcengine.com/docs/6561/1329505
2. 详细阅读V3 WebSocket双向流式协议文档
3. 对照Go语言示例代码,完善Python实现

### 方案C: 联系火山引擎技术支持
1. 询问是否有Python SDK可用
2. 请求提供完整的Python示例代码
3. 确认协议细节和常见问题

## 临时建议

鉴于WebSocket协议实现的复杂性,建议:

1. **短期**: 使用HTTP API验证音色ID的有效性(虽然不返回音频数据,但可以确认音色是否存在)
2. **中期**: 等待获取正确的协议实现后,再进行WebSocket批量验证
3. **长期**: 考虑封装成可复用的TTS客户端类,供项目其他模块使用

## 相关文件

- 批量验证脚本：本报告用到的 5 个 2026-06-25 探针（`scripts/verify_seed_tts_websocket{,_standalone,_v2,_v3}.py` 与 HTTP 探针 `scripts/verify_seed_tts_voices.py`）已于 2026-10-11 删除——它们发送被禁的 `X-Api-App-Key`、按当时还没修对的帧协议解析，产出的是假失败；同族调试脚本 `scripts/test_binary_frame.py` 仍保留
- 现行实现: `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py` 的 `_call_seed_tts_websocket`（生产主路径），二进制帧编解码在 `scripts/protocols.py`（官方模块，**生产依赖，勿删**）
- 同期实现记录: `docs/SEED_TTS_WEBSOCKET_IMPLEMENTATION.md`（2026-10-11 从仓库根目录迁入，已挂更正横幅）
- 音色配置: `shared/seed_tts_2_0_voices.json`（现 277 条）
- 逐音色真值: `shared/seed_tts_2_0_voice_profiles.json`（2026-10-11 画像批量，277 条客观闸门全通过）
- 验证结果: `backend/tests/seed_tts_websocket_verification_results.json`（历史快照，0 成功已作废）

## 附录: 已知的正确交互流程

根据用户提供的示例,完整的事件序列应该是:

```json
[
  {"MsgType": "FullServerResponse", "EventType": "ConnectionStarted"},
  {"MsgType": "FullServerResponse", "EventType": "SessionStarted"},
  {"MsgType": "FullServerResponse", "EventType": "TTSSentenceStart"},
  {"MsgType": "AudioOnlyServer", "EventType": "TTSResponse", "PayloadSize": 2349},
  {"MsgType": "AudioOnlyServer", "EventType": "TTSResponse", "PayloadSize": 3264},
  {"MsgType": "FullServerResponse", "EventType": "TTSSentenceEnd"},
  {"MsgType": "FullServerResponse", "EventType": "SessionFinished"},
  {"MsgType": "FullServerResponse", "EventType": "ConnectionFinished"}
]
```

关键要点:
- ConnectionStarted/SessionStarted等控制消息使用`FullServerResponse`类型
- 音频数据使用`AudioOnlyServer`类型
- 需要正确处理两种消息类型的区分
