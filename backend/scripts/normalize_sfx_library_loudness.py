# -*- coding: utf-8 -*-
"""存量音效响度归一化维护脚本

背景：响度归一化修复（_normalize_effect_loudness）上线前入库的豆包音效
电平普遍低于 -35dBFS，混音叠加基准衰减后几乎不可闻，且质量评估被误判。

处理逻辑（与 register_new_effect 入库流程对齐）：
1. 遍历 sound_effects_index.json，找出可解析且低于 -35dBFS 的音频文件；
2. 调用 SoundEffectDesigner._normalize_effect_loudness 归一化到 -23dBFS；
3. 用 _assess_audio_quality 刷新 quality_score/grade/status；
4. 非 rejected 的重新上传云端（覆盖旧对象或补传之前被 rejected 拦截的）；
5. 同步共享数据库索引，写回本地索引文件；
6. 兜底扫描 SOUND_EFFECTS_DIR 下不在索引里的低电平 mp3（stem 兜底解析仍可能用到），仅做归一化。

用法（backend 目录下）：
    python scripts/normalize_sfx_library_loudness.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

QUIET_THRESHOLD_DBFS = -35.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只报告不修改")
    args = parser.parse_args()

    from pydub import AudioSegment
    from app.services.audiobook.agents import sound_effect_designer as sfx_module

    designer = sfx_module.SoundEffectDesigner()
    index_path = designer.index_path
    if not index_path.exists():
        print(f"[skip] 索引不存在: {index_path}")
        return 0

    data = json.loads(index_path.read_text(encoding="utf-8"))
    records = list(data.values()) if isinstance(data, dict) else list(data)

    changed = 0
    processed_paths = set()
    for record in records:
        file_path = record.get("file_path") or record.get("file", "")
        resolved = designer._resolve_effect_audio_path(file_path)
        if not resolved:
            continue
        resolved_path = Path(resolved)
        processed_paths.add(resolved_path.resolve())
        try:
            dbfs = AudioSegment.from_file(str(resolved_path)).dBFS
        except Exception as exc:
            print(f"[warn] 读取失败 {record.get('id')}: {exc}")
            continue
        if dbfs == float("-inf") or dbfs >= QUIET_THRESHOLD_DBFS:
            continue

        print(f"[quiet] {record.get('id')}: {dbfs:.1f}dBFS "
              f"(当前 {record.get('quality_grade')}/{record.get('quality_status')})")
        if args.dry_run:
            continue

        designer._normalize_effect_loudness(resolved_path)
        quality = designer._assess_audio_quality(file_path)
        record["quality_score"] = quality["quality_score"]
        record["quality_grade"] = quality["quality_grade"]
        record["quality_status"] = quality["quality_status"]
        if quality["quality_status"] != "rejected":
            try:
                record.update(
                    sfx_module.upload_audio_library_asset(
                        local_path=resolved_path,
                        relative_path=str(file_path),
                        library_type="sfx",
                    )
                )
            except Exception as exc:
                print(f"[warn] 云端上传失败 {record.get('id')}: {exc}")
        designer._upsert_generated_effect_to_db_index(record)
        changed += 1
        print(f"[fixed] {record.get('id')}: -> {quality['quality_grade']}/{quality['quality_status']} "
              f"(score {quality['quality_score']})")

    if changed and not args.dry_run:
        index_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[done] 索引已写回: {index_path}")

    # 兜底：索引之外的低电平 mp3（rglob stem 兜底解析仍可能引用）
    orphan = 0
    for mp3 in sorted(sfx_module.SOUND_EFFECTS_DIR.rglob("*.mp3")):
        if mp3.resolve() in processed_paths:
            continue
        try:
            dbfs = AudioSegment.from_file(str(mp3)).dBFS
        except Exception:
            continue
        if dbfs == float("-inf") or dbfs >= QUIET_THRESHOLD_DBFS:
            continue
        print(f"[quiet-orphan] {mp3.name}: {dbfs:.1f}dBFS")
        if not args.dry_run:
            designer._normalize_effect_loudness(mp3)
            orphan += 1

    print(f"[summary] 索引记录归一化 {changed} 条，孤儿文件归一化 {orphan} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
