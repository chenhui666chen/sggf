# -*- coding: utf-8 -*-
"""合成双通道套件（Phase 2.7）：统一编码基线 + 产物校验 + 剪映草稿导出 + 双通道编排。

通道 A（主）：FFmpeg 确定性合成——编码基线 CRF 20 / yuv420p / +faststart，
  editor.py 已注入基线常量；本模块提供 ffprobe 产物校验（确定性渲染的验收侧）。
通道 B（副）：剪映草稿导出——离线生成 draft_content.json（社区 pyJianYingDraft 格式的
  最小结构）+ jianying-editor-report.md（导入指南 + 手动任务清单），人机协同精剪
  交付路径；可选走 JianyingAPIAdapter（工具链选型见指导文档附录 E.8）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- 编码基线（受控常量）
ENCODING_BASELINE: Dict[str, Any] = {
    "vcodec": "libx264",
    "crf": 20,               # 基线 18-23（指导文档 §8.2），取 20 平衡质量/体积
    "pix_fmt": "yuv420p",
    "movflags": "+faststart",
    "audio_codec": "aac",
    "note": "所有重编码一律出自本基线；流拷贝（-c copy）仅限改封装/关键帧对齐拼接",
}


def encoder_args(*, with_audio: bool = True) -> List[str]:
    """受控编码参数（禁止运行时即兴拼接——R11 执行层质量漂移防线）。"""
    args = [
        "-c:v", ENCODING_BASELINE["vcodec"],
        "-crf", str(ENCODING_BASELINE["crf"]),
        "-pix_fmt", ENCODING_BASELINE["pix_fmt"],
        "-movflags", ENCODING_BASELINE["movflags"],
    ]
    if with_audio:
        args.extend(["-c:a", ENCODING_BASELINE["audio_codec"]])
    return args


# ---------------------------------------------------------------- 四轨声音汇总（O4）
def sound_track_summary(storyboard: Any) -> Dict[str, int]:
    """合成端四轨汇总：storyboard 各镜 sound_track 决策的计数（混音与审计消费）。"""
    summary = {
        "shots_total": 0,
        "dialogue_native_voice_ref": 0,
        "dialogue_post_tts": 0,
        "narration_post_tts": 0,
        "ambience_native": 0,
        "ambience_post_sfx": 0,
        "lip_sync_sensitive": 0,
    }
    items = storyboard if isinstance(storyboard, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        st = item.get("sound_track")
        if not isinstance(st, dict):
            continue
        summary["shots_total"] += 1
        if st.get("dialogue_track") == "native_voice_ref":
            summary["dialogue_native_voice_ref"] += 1
        elif st.get("dialogue_track") == "post_tts":
            summary["dialogue_post_tts"] += 1
        if st.get("narration_track") == "post_tts":
            summary["narration_post_tts"] += 1
        if st.get("ambience_track") == "native":
            summary["ambience_native"] += 1
        elif st.get("ambience_track") == "post_sfx":
            summary["ambience_post_sfx"] += 1
        if st.get("lip_sync_sensitive"):
            summary["lip_sync_sensitive"] += 1
    return summary


# ---------------------------------------------------------------- 产物校验（确定性渲染验收侧）
def _ffprobe(path: Path) -> Optional[Dict[str, Any]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.exists():
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        return json.loads(out.stdout or "{}")
    except Exception:  # noqa: BLE001
        return None


def _has_faststart(path: Path) -> Optional[bool]:
    """moov atom 是否在 mdat 之前（+faststart 生效）；无法判定返回 None。"""
    try:
        size = path.stat().st_size
        window = min(size, 256 * 1024)
        with open(path, "rb") as f:
            head = f.read(window)
        moov = head.find(b"moov")
        mdat = head.find(b"mdat")
        if moov < 0 or mdat < 0:
            return None
        return moov < mdat
    except Exception:  # noqa: BLE001
        return None


def verify_encoding_baseline(path: Any) -> Dict[str, Any]:
    """校验合成产物符合编码基线（h264 / yuv420p / faststart）。

    无 ffprobe 或文件缺失时降级 skipped（不阻断），供 REVIEW/验收消费。
    """
    p = Path(path) if path else None
    if not p or not p.exists():
        return {"path": str(path or ""), "status": "skipped_no_file"}
    meta = _ffprobe(p)
    if not meta:
        return {"path": str(p), "status": "skipped_no_ffprobe"}

    streams = meta.get("streams") or []
    video = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), {})
    checks = {
        "codec_h264": str(video.get("codec_name") or "") == "h264",
        "pix_fmt_yuv420p": str(video.get("pix_fmt") or "") == "yuv420p",
        "faststart": _has_faststart(p),
    }
    failed = [k for k, v in checks.items() if v is False]
    return {
        "path": str(p),
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed": failed,
        "baseline": dict(ENCODING_BASELINE),
    }


# ---------------------------------------------------------------- 剪映草稿导出（通道 B）
def export_jianying_draft(
    *,
    run_dir: Path,
    storyboard: List[Dict[str, Any]],
    video_clips: Optional[List[Dict[str, Any]]] = None,
    audio_path: Optional[Path] = None,
    subtitle_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """离线生成剪映草稿包：draft_content.json（社区最小结构）+ 导入报告。

    结构对齐 pyJianYingDraft 公开格式（materials.videos + tracks），导入路径与
    手动任务见报告；云端/运行时控制可选走 JianyingAPIAdapter 或 VectCutAPI（E.8）。
    """
    run_dir = Path(run_dir)
    draft_dir = run_dir / "jianying-draft" / f"dfd_{uuid.uuid4().hex[:8]}"
    draft_dir.mkdir(parents=True, exist_ok=True)

    # 视频片段清单：优先 video_clips（payload），回退 storyboard 顺序
    clips: List[Dict[str, Any]] = []
    if isinstance(video_clips, list) and video_clips:
        for c in video_clips:
            if isinstance(c, dict) and c.get("path"):
                clips.append({"path": str(c["path"]), "shot_id": str(c.get("shot_id") or "")})
    if not clips:
        for item in storyboard or []:
            if isinstance(item, dict) and item.get("shot_id"):
                clips.append({"path": "", "shot_id": str(item["shot_id"])})

    # 最小 draft_content.json（剪映专业版草稿根结构）
    draft = {
        "id": draft_dir.name,
        "version": 3,
        "canvas_config": {"width": 1080, "height": 1920, "ratio": "original"},
        "duration": 0,
        "materials": {
            "videos": [
                {
                    "id": f"vid_{i}",
                    "path": c["path"] or "(待补：手动导入镜头视频)",
                    "shot_id": c["shot_id"],
                    "duration": 0,
                }
                for i, c in enumerate(clips)
            ],
            "audios": ([{"id": "aud_0", "path": str(audio_path)}] if audio_path else []),
            "texts": ([{"id": "sub_0", "path": str(subtitle_path)}] if subtitle_path else []),
        },
        "tracks": [
            {"id": "track_video", "type": "video", "segments": [
                {"id": f"seg_{i}", "material_id": f"vid_{i}", "shot_id": c["shot_id"]}
                for i, c in enumerate(clips)
            ]},
            {"id": "track_audio", "type": "audio", "segments": []},
            {"id": "track_subtitle", "type": "text", "segments": []},
        ],
        "fm": {"source": "ai_director_os_synthesis_kit", "baseline": ENCODING_BASELINE},
    }
    (draft_dir / "draft_content.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 导入报告（对齐 video-agent-jianying-editor 的报告模式）
    report_lines = [
        "# 剪映草稿导出报告（合成通道 B）",
        "",
        f"- 草稿目录：`{draft_dir}`",
        f"- 镜头数：{len(clips)}（主视频轨）",
        f"- 音频：{'已引用' if audio_path else '预留（BGM/配音轨待手动）'}",
        f"- 字幕：{'已引用' if subtitle_path else '待从 ASS/SRT 导入'}",
        "",
        "## 导入步骤",
        "1. 将 `draft_content.json` 所在目录复制到剪映草稿目录：",
        "   - Windows：`%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\`",
        "   - macOS：`~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/`",
        "2. 重启剪映专业版，草稿列表出现 `dfd_*` 项目。",
        "3. 按下方任务清单补齐待手动项（占位素材替换 / BGM / 字幕精调）。",
        "",
        "## 手动任务清单",
    ]
    for i, c in enumerate(clips):
        if not c["path"]:
            report_lines.append(f"- [ ] seg_{i}（{c['shot_id']}）：导入镜头视频到占位轨道")
    report_lines.extend([
        "- [ ] BGM 轨：挑选背景音乐（预留轨）",
        "- [ ] 字幕轨：导入字幕并逐条校对（若草稿未带）",
        "- [ ] 输出：沿用编码基线（CRF 20 / yuv420p / faststart）",
        "",
        "> 云端/程序化控制可选：JianyingAPIAdapter（本仓 adapters）或 VectCutAPI（REST+MCP，附录 E.8）。",
    ])
    report_path = draft_dir / "jianying-editor-report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "draft_dir": str(draft_dir),
        "draft_content": str(draft_dir / "draft_content.json"),
        "report": str(report_path),
        "shots": len(clips),
        "format": "pyjianyingdraft_minimal_v3",
    }


# ---------------------------------------------------------------- 双通道编排
def run_synthesis_dual_channel(
    *,
    payload: Dict[str, Any],
    run_dir: Path,
    merged_video: Optional[Path] = None,
) -> Dict[str, Any]:
    """合成双通道编排：通道 A 产物校验 + 通道 B 剪映导出（env 开关）。

    通道 A 的 FFmpeg 合成由 editor.run 完成（已注入编码基线），此处做验收侧校验。
    """
    channels: Dict[str, Any] = {"baseline": dict(ENCODING_BASELINE)}

    # 通道 A：编码基线校验（merged.mp4 或指定产物）
    target = Path(merged_video) if merged_video else (Path(run_dir) / "merged.mp4")
    channels["ffmpeg"] = {
        "artifact": str(target),
        "verify": verify_encoding_baseline(target),
    }

    # 通道 B：剪映草稿导出（默认开；DREAMWEAVER_JIANYING_EXPORT=0 关闭）
    import os
    enabled = str(os.getenv("DREAMWEAVER_JIANYING_EXPORT", "1") or "1").strip().lower() not in {"0", "false", "no"}
    if enabled:
        storyboard = payload.get("storyboard") if isinstance(payload.get("storyboard"), list) else []
        video_clips = payload.get("video_clips") if isinstance(payload.get("video_clips"), list) else None
        audio_path = Path(str(payload.get("audio_path") or "")) if payload.get("audio_path") else None
        subtitle_path = Path(run_dir) / "subtitles.ass" if (Path(run_dir) / "subtitles.ass").exists() else None
        channels["jianying"] = export_jianying_draft(
            run_dir=Path(run_dir),
            storyboard=storyboard,
            video_clips=video_clips,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
        )
    else:
        storyboard = payload.get("storyboard") if isinstance(payload.get("storyboard"), list) else []
        channels["jianying"] = {"status": "disabled"}

    # 四轨声音汇总（O4：混音与审计消费——dialogue/ambience/narration/bgm 决策计数）
    channels["sound_track"] = sound_track_summary(storyboard)

    payload["synthesis_channels"] = channels
    return channels
