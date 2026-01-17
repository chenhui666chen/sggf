# 本地 FFmpeg 视频剪辑方案（替代剪映/Jianying）

本项目已内置“纯 FFmpeg”剪辑链路，用于 **音视频合并** 与 **字幕烧录**，不依赖剪映/Jianying 或 MoviePy。

## 依赖

- 已安装 `ffmpeg`（并确保包含 `libx264`、`aac`）
- 如需字幕烧录：`ffmpeg` 需支持 `subtitles` filter（通常依赖 `libass`）

## 配置

- `FFMPEG_PATH`：ffmpeg 可执行文件路径（默认 `ffmpeg`）
  - 例：`FFMPEG_PATH=ffmpeg`

## 用法：织梦映心（短剧生成状态机）

织梦映心状态机：`pipeline/state_machine.py`，剪辑阶段调用：`agents/editor.py`（纯 FFmpeg）。

可通过 `ctx.payload` 控制：
- `video_clips`：镜头片段列表（每项含 `path`）
- `audio_path`：存在且文件可读时，会在合成时合入并转 AAC
- `enable_subtitles`：布尔值，控制是否烧录字幕（默认由 `DREAMWEAVER_ENABLE_SUBTITLES` 环境变量决定）

产物与落盘：
- `runs/{run_id}/merged.mp4`：最终合成视频，并写回 `ctx.payload["merged_video"]`
- `runs/{run_id}/subtitles.ass`：字幕文件（启用字幕且有文本时生成）

## 备注

- 若你仍需剪映/Jianying 的高级剪辑能力（模板、转场、素材库等），可继续使用 `JIANYING_MCP_GUIDE.md` 的配置方案；本地 FFmpeg 更适合“自动化合成/批处理/无外部依赖”的生产链路。
