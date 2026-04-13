from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from sqlalchemy import text

from app.api.v1.workflow import (
    ExpandStoryRequest,
    _build_story_expansion_analysis,
    _prepare_story_execution_request,
)
from app.db.base import SessionLocal


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行协同扩展不落库压测，并将结果写入 JSON 文件。")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--target-chapters", type=int, required=True)
    parser.add_argument("--target-characters", type=int, default=0)
    parser.add_argument("--strategy", default="auto")
    parser.add_argument("--intent", default="auto")
    parser.add_argument("--expansion-mode", default="total")
    parser.add_argument("--preserve-written-mode", default="extract_extend")
    parser.add_argument("--disable-auto-supplement", action="store_true")
    parser.add_argument("--output", required=True)
    return parser


def _serialize_round(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": item.get("round"),
        "strategy": item.get("strategy"),
        "before_chapter_count": item.get("before_chapter_count"),
        "after_chapter_count": item.get("after_chapter_count"),
        "before_character_count": item.get("before_character_count"),
        "after_character_count": item.get("after_character_count"),
        "plot_increment": (item.get("plot") or {}).get("increment_requested"),
        "character_increment": (item.get("character") or {}).get("increment_requested"),
        "plot_continue_reason": (item.get("plot") or {}).get("continue_reason"),
        "character_continue_reason": (item.get("character") or {}).get("continue_reason"),
    }


async def _run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    db = SessionLocal()
    started = time.time()
    try:
        row = db.execute(
            text(
                """
                SELECT world_setting, plot_outline, characters
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": args.project_id},
        ).fetchone()
        if not row:
            raise RuntimeError(f"未找到 project_id={args.project_id} 的项目设定")

        request = ExpandStoryRequest(
            project_id=args.project_id,
            current_outline=row[1] or "",
            world_setting=row[0] or "",
            characters=row[2] or "",
            current_chapter_count=0,
            current_character_count=0,
            target_total_chapters=args.target_chapters,
            target_total_characters=(args.target_characters or None),
            strategy=args.strategy,
            intent=args.intent,
            enable_auto_supplement=not args.disable_auto_supplement,
            expansion_mode=args.expansion_mode,
            preserve_written_mode=args.preserve_written_mode,
        )
        prepared = await _prepare_story_execution_request(request, db)
        analysis_bundle = _build_story_expansion_analysis(request=prepared["request"], db=db)
        analysis = analysis_bundle["analysis"]
        coordinator = analysis_bundle["coordinator"]
        result = coordinator.execute(
            current_outline=prepared["request"].current_outline,
            characters=prepared["request"].characters,
            world_setting=analysis_bundle["combined_world_setting"],
            target_total_chapters=analysis.get("effective_target_chapter_count"),
            target_total_characters=analysis.get("effective_target_character_count"),
            strategy=analysis.get("effective_strategy") or args.strategy,
            expansion_mode=analysis.get("effective_expansion_mode") or args.expansion_mode,
            epic_config=analysis.get("epic_config"),
            volume_detail_config=analysis_bundle.get("volume_detail_config"),
        )
        rounds = result.get("execution_rounds") or []
        return {
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(time.time() - started, 2),
            "project_id": args.project_id,
            "requested_target_chapters": args.target_chapters,
            "requested_target_characters": args.target_characters or None,
            "prepared_request": {
                "current_chapter_count": prepared["request"].current_chapter_count,
                "current_character_count": prepared["request"].current_character_count,
                "warnings": prepared.get("warnings") or [],
            },
            "analysis": {
                "execution_mode": analysis.get("execution_mode"),
                "effective_expansion_mode": analysis.get("effective_expansion_mode"),
                "effective_target_chapter_count": analysis.get("effective_target_chapter_count"),
                "effective_target_character_count": analysis.get("effective_target_character_count"),
                "model_plan": analysis.get("model_plan"),
                "mode_suitability": analysis.get("mode_suitability"),
            },
            "result": {
                "execution_mode": result.get("execution_mode"),
                "current_chapter_count": result.get("current_chapter_count"),
                "current_character_count": result.get("current_character_count"),
                "stop_reasons": result.get("stop_reasons") or [],
                "round_count": len(rounds),
                "rounds": [_serialize_round(item) for item in rounds],
            },
        }
    finally:
        db.close()


def main() -> None:
    args = _build_parser().parse_args()
    payload = asyncio.run(_run_benchmark(args))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
