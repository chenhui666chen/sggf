# TTS 调试指南 - 验证"尾部丢字"问题

## 问题背景

在有声书生成过程中，发现除了最后一段，每个 TTS 片段都会少读大约 12 个字符的声音，但传给 TTS 的文本长度是正确的。

## 调试功能说明

已在 TTS 引擎中添加了调试模式，可以自动保存每个 TTS 片段的原始音频和对应文本，方便逐个对照检查。

## 使用方法

### 1. 启用调试模式

在启动后端服务前，设置环境变量：

**Windows (PowerShell)**:
```powershell
$env:TTS_DEBUG_SAVE_SEGMENTS="true"
```

**Linux/Mac (Bash)**:
```bash
export TTS_DEBUG_SAVE_SEGMENTS="true"
```

或者在 `.env` 文件中添加：
```
TTS_DEBUG_SAVE_SEGMENTS=true
```

### 2. 运行有声书生成

启用调试模式后，正常运行有声书生成流程（例如第 74 章）。

### 3. 查看调试输出

生成完成后，在以下目录查看保存的文件：
```
backend/data/tts_debug/chapter_74/
├── segment_001.mp3  # 第1个片段的原始音频
├── segment_001.txt  # 第1个片段的文本和元数据
├── segment_002.mp3
├── segment_002.txt
├── ...
└── segment_027.txt
```

### 4. 对照检查

对每个片段：

1. **打开 `segment_XXX.txt`** 查看：
   - 文本长度（字符数）
   - 音频大小（字节数）
   - 完整文本内容

2. **播放 `segment_XXX.mp3`**：
   - 听完整段音频
   - 对照文本，检查是否所有字都被读出来了

3. **重点关注**：
   - 前 26 个片段（非最后一段）是否尾部缺字？
   - 第 27 个片段（最后一段）是否完整？

## 预期结果分析

### 情况 A：单个 MP3 本身就缺字

如果单独播放 `segment_001.mp3` ~ `segment_026.mp3` 时，自己就少读了大约 12 个字：

**结论**：问题在阿里云 TTS 返回的音频上
**下一步**：
- 用 `diagnose_aliyun_tts.py` 单独测试有问题的文本
- 尝试更换不同的音色、模型
- 联系阿里云技术支持提交工单

### 情况 B：单个 MP3 是完整的

如果单独播放每个片段都是完整的，但最终拼接后的整章文件缺字：

**结论**：问题在音频拼接/后处理阶段
**下一步**：
- 检查 `audio_mixer.py` 的拼接逻辑
- 检查是否有音频后处理步骤在裁剪音频

## 关闭调试模式

调试完成后，记得关闭调试模式以节省磁盘空间：

**Windows (PowerShell)**:
```powershell
$env:TTS_DEBUG_SAVE_SEGMENTS="false"
```

**Linux/Mac (Bash)**:
```bash
export TTS_DEBUG_SAVE_SEGMENTS="false"
```

或者从 `.env` 文件中删除或注释该行。

## 示例：segment_001.txt 内容格式

```
片段 1
长度: 125 字符
音频大小: 458234 字节
音色: Ethan
情感: neutral

文本内容:
新长安的雨夜，霓虹在湿漉漉的街道上流淌成河。在'时之狭间'实验室深处，刺耳的过载警报刚刚停歇，只剩下...
```

## 注意事项

1. 调试模式会为每个章节创建单独的子目录
2. 每个片段会保存两个文件（.mp3 和 .txt）
3. 大章节可能产生较多文件，注意磁盘空间
4. 调试文件不会自动清理，需要手动删除 `backend/data/tts_debug` 目录
