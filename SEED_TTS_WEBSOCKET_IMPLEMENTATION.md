# Seed-TTS 2.0 WebSocket 实现总结

## 问题发现

通过验证脚本发现，Seed-TTS 2.0 Expressive 的 HTTP API (`/api/v3/tts/unidirectional`) 虽然返回 HTTP 200，但实际响应中 `data` 字段为 `null`，没有返回有效的音频数据。

根据官方文档《豆包语音_双向流式语音合成WebSocket》，**Seed-TTS 2.0 必须使用 WebSocket 协议**进行调用。

## 解决方案

### 1. 实现了 `_call_seed_tts_websocket` 方法

在 [`backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py#L1367-L1573) 中添加了完整的 WebSocket 实现：

#### 关键特性：
- **WebSocket URL**: `wss://openspeech.bytedance.com/api/v3/tts/bidirection`
- **认证方式**: 通过 Header 传递 `X-Api-Key` 和 `X-Api-Resource-Id`
- **事件流程**:
  1. `StartConnection` - 建立连接
  2. `StartSession` - 创建会话（包含音色、音频参数等）
  3. `TaskRequest` - 发送待合成文本
  4. `FinishSession` - 结束会话
  5. `FinishConnection` - 关闭连接

#### 支持的功能：
- ✅ 所有 99 个音色
- ✅ 多种音频格式（mp3, pcm, ogg_opus, wav）
- ✅ 采样率配置（8000-48000 Hz）
- ✅ 语速、音量调节
- ✅ 音调调节（pitch: -12 到 12）
- ✅ 语音指令（context_texts）
- ✅ 语音标签解析（use_tag_parser）
- ✅ 流式音频接收（二进制数据）

### 2. 修改了调用逻辑

将 [`_synthesize_seedtts`](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py#L401) 方法中的调用从 `_call_seed_tts_http` 改为 `_call_seed_tts_websocket`。

### 3. 创建了测试脚本

[`backend/test_seed_tts_ws.py`](file:///c:/Users/cuigu/novel_writing_agent/backend/test_seed_tts_ws.py) - 用于测试 WebSocket 连接和音频合成。

## 下一步操作

### 需要完成的任务：

1. **重启后端服务**以加载新的 WebSocket 实现
2. **测试 WebSocket 功能**：
   ```bash
   cd backend
   python test_seed_tts_ws.py
   ```
3. **验证所有 99 个音色**是否都能正常合成音频
4. **更新验证脚本** [`scripts/verify_seed_tts_voices.py`](file:///c:/Users/cuigu/novel_writing_agent/scripts/verify_seed_tts_voices.py) 使用 WebSocket 而不是 HTTP

### 注意事项：

- WebSocket 是同步阻塞的（使用 `websocket-client` 库），需要在异步环境中通过线程池执行
- 音频数据以二进制形式接收，需要累积所有 chunks 后合并
- 错误处理包括：连接失败、会话失败、无音频数据等情况

## 参考文档

- 豆包语音双向流式语音合成 WebSocket 文档
- WebSocket URL: `wss://openspeech.bytedance.com/api/v3/tts/bidirection`
- Resource ID: `seed-tts-2.0`
