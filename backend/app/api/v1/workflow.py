"""
工作流程API路由
支持流式输出 (Streaming) 功能
"""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel, ConfigDict
from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import (
    coordinator,
    StageType,
    AgentStatus,
)
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.schemas.story_expansion import (
    StoryExpansionAnalysisPayload,
    StoryExpansionAnalysisRouteResponse,
    StoryExpansionStartResponse,
    StoryExpansionTaskResultResponse,
)
from app.websocket.manager import ws_manager
from app.services.character_runtime_context import build_character_prompt_context_from_text
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.utils.datetime_utils import parse_datetime_utc, utc_now
import uuid
from datetime import datetime
import json
import re
from sqlalchemy import inspect, text
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task
from app.services.prompts.stages.world_building import (
    CharacterDesignPrompts,
    get_genre_character_fields,
)

# 🎉 导入体系自动检测服务
from app.services.auto_system_detector import auto_create_system_collections

# 🔧 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_workflow_execution_locks: dict[int, asyncio.Lock] = {}


def _get_workflow_execution_lock(project_id: int) -> asyncio.Lock:
    lock = _workflow_execution_locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _workflow_execution_locks[project_id] = lock
    return lock


async def _run_execute_stage_background_serialized(
    task_id: str,
    project_id: int,
    stage_enum: StageType,
    user_id: int,
    db: Session,
    regenerate: bool = False,
    targets: Optional[list[str]] = None,
    feedback: Optional[str] = None,
):
    async with _get_workflow_execution_lock(project_id):
        await execute_stage_background(
            task_id,
            project_id,
            stage_enum,
            user_id,
            db,
            regenerate,
            targets,
            feedback,
        )


async def _run_execute_stage_with_streaming_serialized(
    task_id: str,
    project_id: int,
    stage_enum: StageType,
    user_id: int,
    db: Session,
):
    async with _get_workflow_execution_lock(project_id):
        await execute_stage_with_streaming(task_id, project_id, stage_enum, user_id, db)


def _estimate_tokens_by_chars(text: str) -> int:
    """估算文本 token 数，中文场景按 1.3 倍字符数近似。"""
    return int(len(text or "") * 1.3)


def _get_safe_input_token_budget(
    model_name: str,
    *,
    usage_ratio: float = 0.72,
    prompt_overhead_tokens: int = 500,
) -> int:
    """从统一模型配置读取上下文限制，计算较保守的输入预算。"""
    normalized_model = normalize_model_id(model_name) or model_name
    context_limit = 32000
    output_limit = 8192

    try:
        ensure_model_hub_initialized()
        from core.model_hub import model_hub

        spec = model_hub.registry.get_spec(normalized_model)
        if spec and spec.constraints:
            context_limit = int(spec.constraints.max_context_tokens or context_limit)
            output_limit = int(spec.constraints.max_output_tokens or output_limit)
    except Exception as exc:
        logger.warning("读取模型 %s 配置失败，回退默认预算: %s", normalized_model, exc)

    reserve_output_tokens = max(1200, min(output_limit, max(1200, int(context_limit * 0.25))))
    return max(1500, int(context_limit * usage_ratio) - reserve_output_tokens - prompt_overhead_tokens)


def _select_text_model_by_input_tokens(
    total_tokens: int,
    *,
    primary_model: str = "qwen3-max",
    fallback_model: str = "qwen-long",
) -> tuple[str, int]:
    """按统一模型配置选择主模型或长上下文回退模型。"""
    safe_budget = _get_safe_input_token_budget(primary_model)
    selected = primary_model if total_tokens < safe_budget else fallback_model
    return selected, safe_budget


def _shrink_prompt_text(value: Any, max_length: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."


def _join_prompt_items(value: Any, *, max_items: int = 4, max_length: int = 60) -> str:
    if not isinstance(value, list):
        return ""

    items = []
    for item in value[:max_items]:
        if isinstance(item, dict):
            text = ""
            for key in ("content", "description", "summary", "name", "term", "title", "result"):
                candidate = _shrink_prompt_text(item.get(key, ""), max_length=max_length)
                if candidate:
                    text = candidate
                    break
        else:
            text = _shrink_prompt_text(item, max_length=max_length)

        if text:
            items.append(text)

    return "；".join(items)


_PROJECT_TITLE_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+\.\s*)?(?:\*\*\s*)?(?:\d+\.\s*)?"
    r"(?:日志标题(?:（[^）]+）)?|项目标题|项目题目|书名)"
    r"\s*(?:\*\*)?\s*(?:[：:]\s*(?P<inline>.*))?\s*$"
)


def _looks_like_field_label(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:[-*]\s*)?(?:\d+\.\s*)?(?:\*\*\s*)?(?:\d+\.\s*)?[^《》\n]{1,30}(?:\s*\*\*)?\s*[：:]\s*$",
            line,
        )
    )


def _normalize_project_title_candidate(raw_value: str) -> Optional[str]:
    candidate = (raw_value or "").strip()
    if not candidate:
        return None

    candidate = re.sub(r"^\s*(?:[-*]\s+|\d+\.\s+)", "", candidate).strip()

    quoted_match = re.search(r"《([^》\n]+)》", candidate)
    if quoted_match:
        candidate = quoted_match.group(1).strip()
    else:
        wrapped_quote_match = re.search(r"[“\"]([^”\"\n]+)[”\"]", candidate)
        if wrapped_quote_match:
            candidate = wrapped_quote_match.group(1).strip()
        else:
            candidate = re.sub(r"^\*\*(.*?)\*\*$", r"\1", candidate).strip()
            candidate = candidate.strip("《》“”\"'` ")

    candidate = re.sub(r"\s+", " ", candidate).strip().rstrip("。；;")
    if len(candidate) < 2:
        return None
    if _PROJECT_TITLE_LABEL_RE.match(candidate):
        return None

    return candidate


def _extract_project_title_from_concept(concept_text: str) -> Optional[str]:
    if not isinstance(concept_text, str):
        return None

    lines = concept_text.splitlines()
    for index, line in enumerate(lines):
        match = _PROJECT_TITLE_LABEL_RE.match(line)
        if not match:
            continue

        inline_title = _normalize_project_title_candidate(match.group("inline") or "")
        if inline_title:
            return inline_title

        for next_line in lines[index + 1 : index + 4]:
            stripped_line = next_line.strip()
            if not stripped_line:
                continue
            if _PROJECT_TITLE_LABEL_RE.match(stripped_line) or _looks_like_field_label(stripped_line):
                break

            multiline_title = _normalize_project_title_candidate(stripped_line)
            if multiline_title:
                return multiline_title
            break

    return None


def _sync_project_title_from_concept(
    db: Session,
    project_id: int,
    concept_text: Any,
    *,
    mode_label: str = "",
) -> Optional[str]:
    if not isinstance(concept_text, str):
        return None

    project_title = _extract_project_title_from_concept(concept_text)
    if not project_title:
        return None

    update_title_query = text("""
        UPDATE projects SET title = :title, updated_at = :updated_at
        WHERE id = :project_id
    """)
    db.execute(update_title_query, {
        "title": project_title,
        "updated_at": utc_now().isoformat(),
        "project_id": project_id,
    })
    db.commit()

    mode_suffix = f"（{mode_label}）" if mode_label else ""
    logger.info(f"   📝 已从故事概念更新项目title{mode_suffix}: {project_title}")
    return project_title


def _format_conflict_arc(conflict_arc: Any) -> str:
    if not isinstance(conflict_arc, dict):
        return ""

    parts = []
    mapping = (
        ("trigger", "触发"),
        ("escalation", "升级"),
        ("resolution", "结果"),
        ("result", "结果"),
        ("description", "描述"),
    )
    for key, label in mapping:
        text = _shrink_prompt_text(conflict_arc.get(key, ""), max_length=50)
        if text:
            parts.append(f"{label}:{text}")

    deduplicated = []
    seen = set()
    for item in parts:
        if item not in seen:
            deduplicated.append(item)
            seen.add(item)

    return "；".join(deduplicated[:3])


def _format_chapter_gains(gains: Any) -> str:
    if not isinstance(gains, dict):
        return ""

    parts = []
    for key, label in (
        ("character_gains", "人物收获"),
        ("plot_progress", "剧情推进"),
    ):
        text = _shrink_prompt_text(gains.get(key, ""), max_length=50)
        if text:
            parts.append(f"{label}:{text}")

    return "；".join(parts)


def _format_ending_hook(ending_hook: Any, hooks: Any = None) -> str:
    if isinstance(ending_hook, dict):
        for key in ("content", "hook", "summary", "description", "type"):
            text = _shrink_prompt_text(ending_hook.get(key, ""), max_length=60)
            if text:
                return text

    text = _shrink_prompt_text(ending_hook, max_length=60)
    if text:
        return text

    return _join_prompt_items(hooks, max_items=2, max_length=60)


def _has_structured_chapter_assets(summary_data: Any) -> bool:
    if not isinstance(summary_data, dict):
        return False

    interesting_keys = (
        "scene_goal",
        "key_events",
        "appearing_characters",
        "key_characters",
        "conflict_arc",
        "highlight",
        "gains",
        "ending_hook",
        "hooks",
        "foreshadowing",
    )
    return any(summary_data.get(key) for key in interesting_keys)


def _format_recent_chapter_asset(chapter_payload: Dict[str, Any]) -> str:
    summary_data = chapter_payload.get("summary_data") or {}
    if not isinstance(summary_data, dict):
        return ""

    chapter_number = chapter_payload.get("chapter_number", "?")
    title = (chapter_payload.get("title") or "").strip()
    chapter_label = f"第{chapter_number}章《{title}》" if title else f"第{chapter_number}章"
    lines = [chapter_label]

    core_summary = _shrink_prompt_text(
        summary_data.get("core_summary") or chapter_payload.get("summary", ""),
        max_length=120,
    )
    if core_summary:
        lines.append(f"- 核心摘要: {core_summary}")

    scene_goal = _shrink_prompt_text(summary_data.get("scene_goal", ""), max_length=60)
    if scene_goal:
        lines.append(f"- 场景目标: {scene_goal}")

    key_events = _join_prompt_items(summary_data.get("key_events"), max_items=4, max_length=40)
    if key_events:
        lines.append(f"- 关键事件: {key_events}")

    characters = _join_prompt_items(
        summary_data.get("appearing_characters") or summary_data.get("key_characters"),
        max_items=5,
        max_length=20,
    )
    if characters:
        lines.append(f"- 相关人物: {characters}")

    conflict_arc = _format_conflict_arc(summary_data.get("conflict_arc"))
    if conflict_arc:
        lines.append(f"- 冲突推进: {conflict_arc}")

    highlight = summary_data.get("highlight")
    if isinstance(highlight, dict):
        highlight_type = _shrink_prompt_text(highlight.get("type", ""), max_length=20)
        highlight_desc = _shrink_prompt_text(highlight.get("description", ""), max_length=50)
        highlight_text = "：".join(part for part in (highlight_type, highlight_desc) if part)
        if highlight_text:
            lines.append(f"- 高光设计: {highlight_text}")

    gains = _format_chapter_gains(summary_data.get("gains"))
    if gains:
        lines.append(f"- 本章收获: {gains}")

    ending_hook = _format_ending_hook(
        summary_data.get("ending_hook"),
        summary_data.get("hooks"),
    )
    if ending_hook:
        lines.append(f"- 结尾钩子: {ending_hook}")

    foreshadowing = _join_prompt_items(summary_data.get("foreshadowing"), max_items=3, max_length=50)
    if foreshadowing:
        lines.append(f"- 伏笔事项: {foreshadowing}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_recent_chapter_assets_summary(
    previous_chapters_payload: list[Dict[str, Any]],
    *,
    limit: int = 4,
) -> str:
    structured_payloads = [
        payload
        for payload in previous_chapters_payload
        if _has_structured_chapter_assets(payload.get("summary_data"))
    ]

    if not structured_payloads:
        return ""

    formatted_parts = []
    for payload in structured_payloads[-limit:]:
        formatted = _format_recent_chapter_asset(payload)
        if formatted:
            formatted_parts.append(formatted)

    return "\n\n".join(formatted_parts)


def _build_iteration_revision_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    review_text: str,
    recent_chapter_assets_summary: str = "",
    include_history_hint: bool = False,
) -> str:
    review_section_title = "【必须执行的所有评审意见（包含历史轮次）】" if include_history_hint else "【评审意见】"
    intro = (
        f"【重要提示】请严格按照以下所有评审意见逐条修改第{chapter_number}章内容，不要遗漏或忽略任何一条建议。"
        if include_history_hint
        else f"请根据以下评审意见优化第{chapter_number}章："
    )

    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )

    return f"""{intro}

【当前章节内容】
{chapter_content}

【最近章节连续性资产】（必须承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

{review_section_title}
{review_text}

【修改要求】
1. 必须逐条落实上述评审意见中的修改建议
2. 优先延续最近章节连续性资产中的未完成冲突、人物状态变化、结尾钩子与伏笔
3. 不得删改会影响后续章节衔接的关键细节
4. 保持原章节的完整情节和篇幅（不少于原稿80%字数）
5. 直接输出优化后的完整章节内容（第一行为章节标题）
6. 不要附加任何修改说明、优化要点等额外内容

请立即输出优化后的章节："""


def _build_iteration_review_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str,
    recent_chapter_assets_summary: str = "",
) -> str:
    continuity_block = (
        recent_chapter_assets_summary
        if recent_chapter_assets_summary
        else "（最近章节没有可用的结构化连续性资产）"
    )

    return f"""请评审以下第{chapter_number}章：

【章节规划】
{chapter_plan}

【最近章节连续性资产】（重点检查是否承接场景目标、冲突推进、人物状态、钩子与伏笔）
{continuity_block}

【章节内容】
{chapter_content}
"""


# 🆕 导入流式输出服务
try:
    from app.services.streaming_service import get_streaming_service
    STREAMING_AVAILABLE = True
except ImportError:
    STREAMING_AVAILABLE = False
    get_streaming_service = None  # type: ignore

# 请求模型
class StartWorkflowRequest(BaseModel):
    project_id: int
    requirement: str
    # 🆕 可选的目标章节数配置，用于长篇规划（默认100章）
    target_chapter_count: Optional[int] = 100
    # 🆕 是否清空现有内容（重新开始时使用）
    clear_existing: bool = False

class ExecuteStageRequest(BaseModel):
    project_id: int
    stage: str
    requirement: Optional[str] = None
    # 🆕 是否启用流式输出（默认启用）
    enable_streaming: bool = True
    # 🆕 概念阶段评审/重生支持的可选参数
    regenerate: bool = False
    targets: Optional[list[str]] = None
    feedback: Optional[str] = None

class RegenerateStageRequest(BaseModel):
    project_id: int
    stage: str

class SaveStageContentRequest(BaseModel):
    content: str
    continue_workflow: bool = False

class ExpandStoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    current_outline: str
    world_setting: str
    characters: str
    current_chapter_count: int = 0
    current_character_count: int = 0
    target_total_chapters: Optional[int] = None
    target_total_characters: Optional[int] = None
    strategy: str = "auto"
    intent: str = "auto"
    enable_auto_supplement: bool = True
    expansion_mode: str = "auto"
    total_volumes: Optional[int] = None
    total_chapters_min: Optional[int] = None
    total_chapters_max: Optional[int] = None
    target_volume_index: Optional[int] = None
    volume_chapters_min: Optional[int] = None
    volume_chapters_max: Optional[int] = None
    volume_character_increment: Optional[int] = None
    preserve_written_mode: str = "extract_extend"
    lock_existing_chapters: bool = True
    preserve_existing_characters: bool = True
    reset_epic_framework: bool = False


router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

VALID_STORY_EXPANSION_STRATEGIES = {"auto", "balanced", "plot_first", "character_first"}
VALID_STORY_EXPANSION_INTENTS = {"auto", "outline_led", "character_led", "balanced"}
VALID_STORY_EXPANSION_MODES = {"auto", "total", "epic_framework", "volume_detail"}
VALID_PRESERVE_WRITTEN_MODES = {"extract_extend", "preserve_written", "regenerate_all"}
VOLUME_DETAIL_MIN_CHAPTERS = 20
VOLUME_DETAIL_MAX_CHAPTERS = 100


def _get_conventional_collaboration_max_target_chapters(current_chapter_count: int) -> int:
    from app.services.story_expansion_coordinator import StoryExpansionCoordinator

    return StoryExpansionCoordinator.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS


def _get_project_expansion_profile(project_id: int, db: Session) -> Dict[str, Any]:
    """统一获取扩展阶段所需的项目画像，避免不同入口的参数传递漂移。"""
    project_profile = WorkflowContextBuilder(db).get_project_profile(project_id)
    return {
        "genre": project_profile.genre,
        "planned_chapters_max": project_profile.planned_chapters_max,
    }


def _create_project_outline_expander(project_id: int, db: Session) -> Dict[str, Any]:
    from app.services.agents.outline_expander import create_outline_expander

    project_profile = _get_project_expansion_profile(project_id, db)
    project_genre = project_profile["genre"] or ""
    project_planned_chapters = project_profile["planned_chapters_max"] or 0

    return {
        "expander": create_outline_expander(
            genre=project_genre,
            planned_chapters_max=project_planned_chapters,
            project_id=project_id,
        ),
        "genre": project_genre,
        "planned_chapters_max": project_planned_chapters,
    }


def _build_project_world_setting_context(project_id: int, world_setting: str, db: Session) -> str:
    context_builder = WorkflowContextBuilder(db)
    return context_builder.build_world_setting_context(
        project_id,
        world_setting,
    ).combined_world_setting


def _sync_real_coordinator_project_context(
    project_id: int,
    context_builder: WorkflowContextBuilder,
    project_profile: Any = None,
) -> tuple[Any, Any]:
    project_profile = project_profile or context_builder.get_project_profile(project_id)
    real_coord = coordinator.get_real_coordinator(project_id)
    if real_coord and hasattr(real_coord, "project_context"):
        real_coord.project_context.update(project_profile.to_project_context_payload())
        logger.info(
            "   ✅ 已注入项目基本信息：title=%s, genre=%s",
            project_profile.title or "未命名项目",
            project_profile.genre or "通用",
        )
    return project_profile, real_coord


def _ensure_project_owned(project_id: int, user_id: int, db: Session) -> Project:
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == user_id)
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _build_task_start_response(
    *,
    task_id: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "success": True,
        "task_id": task_id,
        "message": message,
    }


CONCEPT_SIMILARITY_PATTERN_GROUPS: Dict[str, list[str]] = {
    "高频主角名": ["林尘", "苏辰", "叶凡", "萧凡", "秦风", "楚天", "陈长生"],
    "高频开局身份": ["宗门杂役", "杂役弟子", "废灵根", "无灵根", "外门弟子", "底层弟子", "濒死觉醒"],
    "高频金手指": ["系统流", "逆修系统", "反向修炼系统", "吞噬灵根", "悖论灵根", "掠夺他人修为", "越被看不起修为越暴涨", "扮猪吃虎"],
    "高频世界命名": ["九寰界", "九寰界域", "九大仙域", "九大仙宗", "七大仙宗", "上三界", "中三界", "下三界"],
    "高频终局真相": ["高维存在", "天外之眼", "监察者", "飞升骗局", "养蛊游戏", "轮回骗局", "历史被循环重置"],
}


def _safe_prompt_context_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    if not isinstance(value, str):
        return str(value or "")

    stripped = value.strip()
    if not stripped:
        return ""

    should_try_json = stripped.startswith(("{", "[")) or (
        stripped.startswith('"') and stripped.endswith('"')
    )
    if not should_try_json:
        return value

    try:
        parsed = json.loads(stripped)
    except Exception:
        return value

    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False)
    return str(parsed or "")


def _normalize_story_request_text_fields(request: ExpandStoryRequest) -> ExpandStoryRequest:
    from app.services.story_text_utils import normalize_story_text

    return request.model_copy(
        update={
            "current_outline": normalize_story_text(request.current_outline),
            "world_setting": normalize_story_text(request.world_setting),
            "characters": normalize_story_text(request.characters),
        }
    )


def _clip_prompt_context(text_value: str, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text_value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _build_recent_project_avoidance_context(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    genre: Optional[str],
    limit: int = 4,
) -> tuple[str, str]:
    recent_query = text(
        """
        SELECT p.id, p.title, p.genre, ps.concept, ps.world_setting, ps.characters
        FROM projects p
        LEFT JOIN project_settings ps ON ps.project_id = p.id
        WHERE p.user_id = :user_id
          AND p.id <> :project_id
          AND (
            COALESCE(ps.concept, '') <> ''
            OR COALESCE(ps.world_setting, '') <> ''
            OR COALESCE(ps.characters, '') <> ''
          )
        ORDER BY COALESCE(p.updated_at, p.created_at) DESC
        LIMIT 8
        """
    )
    rows = db.execute(
        recent_query,
        {"user_id": user_id, "project_id": project_id},
    ).fetchall()

    if not rows:
        return "", ""

    selected_rows = sorted(
        rows,
        key=lambda row: (
            0 if genre and row[2] and str(row[2]) == str(genre) else 1,
        ),
    )[:limit]

    signature_sections: list[str] = []
    combined_text_parts: list[str] = []

    for idx, row in enumerate(selected_rows, start=1):
        recent_title = row[1] or f"项目{row[0]}"
        recent_genre = row[2] or "未标注"
        concept_txt = _safe_prompt_context_text(row[3])
        world_txt = _safe_prompt_context_text(row[4])
        characters_txt = _safe_prompt_context_text(row[5])
        combined_text_parts.extend([concept_txt, world_txt, characters_txt])

        signature_sections.append(
            "\n".join(
                [
                    f"{idx}. 《{recent_title}》",
                    f"- 题材：{recent_genre}",
                    f"- 故事概念摘要：{_clip_prompt_context(concept_txt, 180) or '暂无'}",
                    f"- 世界观摘要：{_clip_prompt_context(world_txt, 120) or '暂无'}",
                ]
            )
        )

    combined_text = "\n".join(part for part in combined_text_parts if part)
    detected_groups: Dict[str, list[str]] = {}
    for group_name, patterns in CONCEPT_SIMILARITY_PATTERN_GROUPS.items():
        hits: list[str] = []
        for pattern in patterns:
            if pattern in combined_text and pattern not in hits:
                hits.append(pattern)
        if hits:
            detected_groups[group_name] = hits[:4]

    extracted_world_names = []
    for match in re.findall(r"(?:此界名为|世界名为)[“\"《]?([\u4e00-\u9fffA-Za-z0-9]{2,12})", combined_text):
        if match not in extracted_world_names:
            extracted_world_names.append(match)
    if extracted_world_names:
        detected_groups["已用世界名"] = extracted_world_names[:4]

    recent_signatures = "【近期项目摘要（仅供避重，不可复写）】\n" + "\n".join(signature_sections)
    recent_avoidance = ""
    if detected_groups:
        avoidance_lines = [
            f"- {group_name}：{'、'.join(items)}"
            for group_name, items in detected_groups.items()
            if items
        ]
        recent_avoidance = (
            "【近期项目避重清单】\n"
            "- 以下元素在你最近生成的项目中已经出现，除非用户明确要求，否则默认禁止复用。\n"
            + "\n".join(avoidance_lines)
        )

    return recent_signatures, recent_avoidance


def _inject_recent_project_novelty_context(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    real_coord: Any,
    genre: Optional[str],
) -> None:
    if not real_coord or not hasattr(real_coord, "project_context"):
        return

    recent_signatures, recent_avoidance = _build_recent_project_avoidance_context(
        db,
        project_id=project_id,
        user_id=user_id,
        genre=genre,
    )
    real_coord.project_context.update(
        {
            "recent_project_signatures": recent_signatures,
            "recent_project_avoidance": recent_avoidance,
        }
    )


def _build_story_execution_task_kwargs(
    *,
    task_id: str,
    request: ExpandStoryRequest,
    user_id: int,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "project_id": request.project_id,
        "user_id": user_id,
        "current_outline": request.current_outline,
        "world_setting": request.world_setting,
        "characters": request.characters,
        "current_chapter_count": request.current_chapter_count,
        "current_character_count": request.current_character_count,
        "target_total_chapters": request.target_total_chapters,
        "target_total_characters": request.target_total_characters,
        "strategy": request.strategy,
        "intent": request.intent,
        "enable_auto_supplement": request.enable_auto_supplement,
        "expansion_mode": request.expansion_mode,
        "total_volumes": request.total_volumes,
        "total_chapters_min": request.total_chapters_min,
        "total_chapters_max": request.total_chapters_max,
        "target_volume_index": request.target_volume_index,
        "volume_chapters_min": request.volume_chapters_min,
        "volume_chapters_max": request.volume_chapters_max,
        "volume_character_increment": request.volume_character_increment,
        "preserve_written_mode": request.preserve_written_mode,
        "reset_epic_framework": request.reset_epic_framework,
    }


def _enqueue_story_expansion_task(
    *,
    task_id: str,
    request: ExpandStoryRequest,
    user_id: int,
) -> None:
    asyncio.create_task(
        execute_expand_story_task(
            **_build_story_execution_task_kwargs(
                task_id=task_id,
                request=request,
                user_id=user_id,
            )
        )
    )


def _create_story_expansion_history_record(
    db: Session,
    *,
    project_id: int,
    task_id: str,
) -> None:
    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """
    )

    db.execute(
        insert_query,
        {
            "project_id": project_id,
            "task_type": "expand_story",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat(),
        },
    )
    db.commit()


def _update_story_expansion_history_record(
    db: Session,
    *,
    task_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    update_query = text(
        """
        UPDATE generation_history
        SET status = :status,
            result = :result,
            error = :error,
            completed_at = :completed_at
        WHERE task_id = :task_id
        """
    )

    try:
        db.execute(
            update_query,
            {
                "task_id": task_id,
                "status": status,
                "result": json.dumps(result, ensure_ascii=False) if result is not None else None,
                "error": error,
                "completed_at": utc_now().isoformat(),
            },
        )
        db.commit()
    except Exception as history_error:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("更新协同扩展任务记录失败: task_id=%s, error=%s", task_id, history_error)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_story_result_outline_ops(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    normalized_ops: list[Dict[str, Any]] = []
    raw_ops = result.get("outline_ops")
    if not isinstance(raw_ops, list):
        return normalized_ops

    for item in raw_ops:
        if not isinstance(item, dict):
            continue

        action = str(item.get("action") or "").strip()
        if action in {"append", "insert_after"} or "generated_count" in item or "requested_count" in item:
            normalized_ops.append(
                {
                    "action": action or "append",
                    "after_chapter": item.get("after_chapter"),
                    "requested_count": item.get("requested_count"),
                    "generated_count": item.get("generated_count"),
                    "goal": item.get("goal"),
                    "generated_titles": list(item.get("generated_titles") or []),
                }
            )
            continue

        stage = str(item.get("stage") or item.get("mode") or "").strip()

        if stage in {"delta", "iterative"} or item.get("round") is not None:
            before_chapter_count = _safe_int(item.get("before_chapter_count"))
            after_chapter_count = _safe_int(item.get("after_chapter_count"))
            requested_count = _safe_int((item.get("plot") or {}).get("increment_requested"))
            generated_count = max(0, after_chapter_count - before_chapter_count)
            if requested_count <= 0:
                requested_count = _safe_int(item.get("chapters_generated"), generated_count)

            round_label = f"第{_safe_int(item.get('round'), 1)}轮协同"
            strategy = str(item.get("strategy") or "").strip()
            goal = f"{round_label}推进章节补强"
            if strategy:
                goal += f"（策略：{strategy}）"

            normalized_ops.append(
                {
                    "action": "insert_after" if before_chapter_count > 0 else "append",
                    "after_chapter": before_chapter_count if before_chapter_count > 0 else None,
                    "requested_count": requested_count if requested_count > 0 else None,
                    "generated_count": generated_count if generated_count > 0 else None,
                    "goal": goal,
                    "generated_titles": [],
                }
            )
            continue

        if stage == "epic_framework":
            target_chapter_range = item.get("target_chapter_range") or []
            estimated_chapters = _safe_int(item.get("estimated_chapters"))
            total_volumes = _safe_int(item.get("volumes"))
            if estimated_chapters <= 0 and isinstance(target_chapter_range, list) and len(target_chapter_range) >= 2:
                estimated_chapters = _safe_int(target_chapter_range[1])

            goal_parts = []
            if total_volumes > 0:
                goal_parts.append(f"生成 {total_volumes} 卷长篇框架")
            else:
                goal_parts.append("生成长篇框架")
            if isinstance(target_chapter_range, list) and len(target_chapter_range) >= 2:
                goal_parts.append(
                    f"规划 { _safe_int(target_chapter_range[0]) }-{ _safe_int(target_chapter_range[1]) } 章"
                )

            normalized_ops.append(
                {
                    "action": "append",
                    "after_chapter": None,
                    "requested_count": estimated_chapters if estimated_chapters > 0 else None,
                    "generated_count": estimated_chapters if estimated_chapters > 0 else None,
                    "goal": "，".join(part for part in goal_parts if part),
                    "generated_titles": [],
                }
            )
            continue

        if stage == "volume_detail":
            chapter_range = item.get("chapter_range") or []
            start_chapter = _safe_int(chapter_range[0]) if isinstance(chapter_range, list) and len(chapter_range) >= 1 else 0
            end_chapter = _safe_int(chapter_range[1]) if isinstance(chapter_range, list) and len(chapter_range) >= 2 else 0
            generated_count = max(0, end_chapter - start_chapter + 1) if start_chapter > 0 and end_chapter >= start_chapter else 0
            volume_index = _safe_int(item.get("volume_index"))
            goal = (
                f"细化第{volume_index}卷，第{start_chapter}-{end_chapter}章"
                if volume_index > 0 and generated_count > 0
                else "执行单卷细化协同"
            )

            normalized_ops.append(
                {
                    "action": "insert_after" if start_chapter > 1 else "append",
                    "after_chapter": start_chapter - 1 if start_chapter > 1 else None,
                    "requested_count": generated_count if generated_count > 0 else None,
                    "generated_count": generated_count if generated_count > 0 else None,
                    "goal": goal,
                    "generated_titles": [],
                }
            )

    return normalized_ops


def _normalize_story_character_sync_result(sync_result: Any) -> tuple[Optional[Dict[str, Any]], list[str]]:
    if not isinstance(sync_result, dict):
        return None, []

    warnings: list[str] = []
    raw_errors = sync_result.get("errors")
    if isinstance(raw_errors, list):
        warnings.extend(str(item).strip() for item in raw_errors if str(item).strip())
    elif raw_errors:
        warning_text = str(raw_errors).strip()
        if warning_text:
            warnings.append(warning_text)

    parsed_value = sync_result.get("parsed")
    if parsed_value is None and sync_result.get("total") is not None:
        parsed_value = sync_result.get("total")

    normalized: Dict[str, Any] = {
        "parsed": _safe_int(parsed_value, 0),
        "created": _safe_int(sync_result.get("created"), 0),
        "updated": _safe_int(sync_result.get("updated"), 0),
        "skipped": _safe_int(sync_result.get("skipped"), 0),
    }

    relationships = sync_result.get("relationships")
    if isinstance(relationships, dict):
        normalized["relationships"] = {
            "parsed": _safe_int(relationships.get("parsed"), 0),
            "saved": _safe_int(relationships.get("saved"), 0),
            "characters_updated": _safe_int(relationships.get("characters_updated"), 0),
        }

    return normalized, list(dict.fromkeys(item for item in warnings if item))


def _has_structured_character_cards(characters_text: Any) -> bool:
    if not isinstance(characters_text, str):
        return False

    if not characters_text.strip():
        return False

    try:
        from app.services.character_parser import has_parseable_character_cards

        return has_parseable_character_cards(characters_text)
    except Exception:
        return bool(
            re.search(
                r"(?:^|\n)\s*(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:]\s*\S+",
                characters_text,
            )
        )


def _normalize_concept_stage_characters_for_storage(
    project_id: int,
    characters_text: Any,
    *,
    concept_text: str = "",
    world_setting_text: str = "",
) -> str:
    if not isinstance(characters_text, str):
        return ""

    normalized = characters_text.strip()
    if not normalized:
        return ""

    workflow_state: Dict[str, Any] = {}
    try:
        workflow_state = coordinator.get_workflow_state(project_id) or {}
    except Exception:
        logger.warning("⚠️ 读取工作流状态失败，人物存储预处理将使用默认上下文")

    requirement = str(workflow_state.get("requirement") or "")

    try:
        real_coordinator = coordinator.get_real_coordinator(project_id)
    except Exception:
        real_coordinator = None
        logger.warning("⚠️ 获取真实协调器失败，人物存储预处理将跳过重排")

    normalize_fn = getattr(real_coordinator, "_normalize_character_cards_if_needed", None)
    if callable(normalize_fn):
        try:
            normalized = normalize_fn(
                normalized,
                requirement=requirement,
                concept=str(concept_text or ""),
                world_setting=str(world_setting_text or ""),
            )
        except Exception as exc:
            logger.warning("⚠️ 概念阶段人物重排失败，准备执行落库拦截: %s", exc)

    if not _has_structured_character_cards(normalized):
        try:
            from app.services.character_parser import convert_legacy_grouped_characters_to_cards

            converted = convert_legacy_grouped_characters_to_cards(normalized)
            if _has_structured_character_cards(converted):
                normalized = converted
        except Exception as exc:
            logger.warning("⚠️ 概念阶段人物规则转换失败，准备执行落库拦截: %s", exc)

    if _has_structured_character_cards(normalized):
        return normalized

    logger.warning(
        "⚠️ 概念阶段人物文本未通过结构化校验，跳过写入 project_settings.characters: project_id=%s",
        project_id,
    )
    return ""


def _build_concept_stage_character_prompts(
    project_genre: str,
    requirement: str,
    concept_text: str,
    world_setting_text: str,
) -> tuple[str, str]:
    genre_extra_fields = get_genre_character_fields(project_genre or "")
    system_prompt = CharacterDesignPrompts.get_system_prompt(project_genre or "")
    base_user_prompt = CharacterDesignPrompts.get_character_prompt(
        requirement=requirement or "暂无特别要求",
        genre_extra_fields=genre_extra_fields,
    )
    user_prompt = f"""{base_user_prompt}

【故事概念】
{concept_text}

【世界观设定】
{world_setting_text}"""
    return system_prompt, user_prompt


def _select_story_character_sync_source(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "", ""

    for source_name in ("character_delta", "characters"):
        characters_text = result.get(source_name)
        if _has_structured_character_cards(characters_text):
            return str(characters_text), source_name

    return "", ""


def _estimate_character_count_from_text(characters_text: str) -> int:
    if not (characters_text or "").strip():
        return 0

    normalized_text = characters_text or ""
    try:
        from app.services.story_expansion_coordinator import extract_character_names
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(characters_text)
        detected_names = extract_character_names(normalized_text)
        if detected_names:
            return len(detected_names)
    except Exception:
        logger.warning("⚠️ 人物识别降级为正则统计")

    return len(re.findall(r"【姓名】：", normalized_text))


def _estimate_chapter_count_from_text(outline_text: str) -> int:
    if not (outline_text or "").strip():
        return 0

    normalized_text = outline_text or ""
    try:
        from app.services.story_expansion_coordinator import parse_outline_blocks
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(outline_text)
        _, blocks = parse_outline_blocks(normalized_text)
        if blocks:
            return len(blocks)
    except Exception:
        logger.warning("⚠️ 章节识别降级为正则统计")

    return len(
        re.findall(
            r"(?m)^(?:#{1,6}\s*)?(?:[一二三四五六七八九十百千万零两〇]+[、.．]\s*)?第\s*[0-9一二三四五六七八九十百千万零两〇]+\s*章(?:\s*$|[：:、\-\s])",
            normalized_text,
        )
    )


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _resolve_story_result_count(
    *,
    reported_count: Any,
    parsed_count: int,
    validation_count: Any,
    fallback_count: Any,
) -> int:
    return max(
        _coerce_non_negative_int(reported_count),
        _coerce_non_negative_int(parsed_count),
        _coerce_non_negative_int(validation_count),
        _coerce_non_negative_int(fallback_count),
    )


def _resolve_story_epic_config(request: ExpandStoryRequest) -> Optional[Dict[str, Any]]:
    if request.expansion_mode != "epic_framework":
        return None
    if (
        request.total_volumes is None
        or request.total_chapters_min is None
        or request.total_chapters_max is None
    ):
        return None
    return {
        "total_volumes": int(request.total_volumes),
        "chapter_range": (
            int(request.total_chapters_min),
            int(request.total_chapters_max),
        ),
    }


def _detect_total_volumes_from_framework(framework_text: str) -> int:
    if not framework_text:
        return 10

    yaml_match = re.search(r"总卷数:\s*(\d+)", framework_text)
    if yaml_match:
        try:
            return max(1, int(yaml_match.group(1)))
        except Exception:
            pass

    volume_matches = re.findall(r"第\s*(\d+)\s*卷", framework_text)
    if volume_matches:
        try:
            return max(int(item) for item in volume_matches)
        except Exception:
            pass

    return 10


def _extract_story_volume_chapter_bounds_from_text(content: str) -> Optional[Tuple[int, int]]:
    text_content = str(content or "")
    if not text_content.strip():
        return None

    try:
        from app.services.story_expansion_coordinator import parse_outline_blocks
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(text_content)
        _, blocks = parse_outline_blocks(normalized_text)
        chapter_numbers = [
            int(block.original_number)
            for block in blocks
            if int(getattr(block, "original_number", 0) or 0) > 0
        ]
        if chapter_numbers:
            return min(chapter_numbers), max(chapter_numbers)
    except Exception:
        pass

    chapter_number_matches = [
        int(match)
        for match in re.findall(r"(?m)^(?:#{1,6}\s*)?(?:\*\*)?\s*第\s*(\d+)\s*章", text_content)
        if str(match).isdigit()
    ]
    if chapter_number_matches:
        return min(chapter_number_matches), max(chapter_number_matches)

    return None


def _estimate_story_volume_chapter_count_from_text(content: str) -> int:
    text_content = str(content or "")
    if not text_content.strip():
        return 0

    coverage_match = re.search(r"覆盖章节[：:]\s*(\d+)\s*[-~—至到]+\s*(\d+)\s*章?", text_content)
    if coverage_match:
        try:
            start = int(coverage_match.group(1))
            end = int(coverage_match.group(2))
            if end >= start > 0:
                return end - start + 1
        except Exception:
            pass

    range_span_match = re.search(r"章节规模[：:]\s*(\d+)\s*[-~—至到]+\s*(\d+)\s*章?", text_content)
    if range_span_match:
        try:
            lower = int(range_span_match.group(1))
            upper = int(range_span_match.group(2))
            return max(lower, upper, 0)
        except Exception:
            pass

    exact_span_match = re.search(r"章节规模[：:]\s*(\d+)\s*章?", text_content)
    if exact_span_match:
        try:
            return max(0, int(exact_span_match.group(1)))
        except Exception:
            pass

    estimated_match = re.search(r"预计\s*(\d+)(?:\s*[-~—至到]+\s*(\d+))?\s*章", text_content)
    if estimated_match:
        try:
            lower = int(estimated_match.group(1))
            upper = int(estimated_match.group(2) or lower)
            return max(lower, upper, 0)
        except Exception:
            pass

    chapter_bounds = _extract_story_volume_chapter_bounds_from_text(text_content)
    if chapter_bounds:
        start, end = chapter_bounds
        if end >= start > 0:
            return end - start + 1

    return 0


def _estimate_story_volume_chapter_count(vol_data: Dict[str, Any]) -> int:
    if not isinstance(vol_data, dict):
        return 0

    chapter_count = int(vol_data.get("chapter_count") or 0)
    if chapter_count > 0:
        return chapter_count

    chapter_range = vol_data.get("chapters_range") or [0, 0]
    if isinstance(chapter_range, (list, tuple)) and len(chapter_range) >= 2:
        try:
            start = int(chapter_range[0] or 0)
            end = int(chapter_range[1] or 0)
            if start > 0 and end >= start:
                return end - start + 1
        except Exception:
            pass

    for field in ("summary", "detail"):
        estimated = _estimate_story_volume_chapter_count_from_text(str(vol_data.get(field) or ""))
        if estimated > 0:
            return estimated

    return 0


def _resolve_story_volume_detail_config(
    request: ExpandStoryRequest,
    db: Session,
) -> Optional[Dict[str, Any]]:
    if request.expansion_mode != "volume_detail":
        return None

    from app.services.outline_merger import (
        normalize_volume_detail_layout,
        parse_epic_volumes_json,
        parse_framework_to_volumes,
    )

    epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(request.project_id)

    if not epic_framework_state.epic_framework:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="单卷细化协同需要先生成长篇框架",
        )

    framework_content = epic_framework_state.epic_framework
    stored_volumes_json = epic_framework_state.epic_volumes_detail or "{}"
    volumes_data = parse_epic_volumes_json(stored_volumes_json)
    if not volumes_data.get("volumes"):
        detected_total_volumes = _detect_total_volumes_from_framework(framework_content)
        volumes_data = parse_framework_to_volumes(framework_content, detected_total_volumes)
    volumes_data = normalize_volume_detail_layout(volumes_data, rewrite_detail_content=True)

    volumes_dict = volumes_data.get("volumes", {})
    target_volume_index = int(request.target_volume_index or 0)
    chapters_min = int(request.volume_chapters_min or 0)
    chapters_max = int(request.volume_chapters_max or 0)
    total_volumes = int(volumes_data.get("total_volumes") or len(volumes_dict) or 0)

    if total_volumes > 0 and target_volume_index > total_volumes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"目标卷编号超出范围 (1-{total_volumes})",
        )

    accumulated_chapters = 0
    current_total_chapter_count = 0
    previous_volume_detail = None
    existing_volume_detail = None

    for vol_key, vol_data in volumes_dict.items():
        if vol_data.get("type") == "detail":
            chapter_range = vol_data.get("chapters_range") or [0, 0]
            detected_end = 0
            try:
                detected_end = int(chapter_range[1] or 0)
            except Exception:
                detected_end = 0
            if detected_end <= 0:
                chapter_bounds = _extract_story_volume_chapter_bounds_from_text(str(vol_data.get("detail") or ""))
                if chapter_bounds:
                    detected_end = int(chapter_bounds[1])
            current_total_chapter_count = max(current_total_chapter_count, detected_end)

    for vol_num in range(1, target_volume_index):
        vol_data = volumes_dict.get(str(vol_num)) or {}
        accumulated_chapters += _estimate_story_volume_chapter_count(vol_data)
        if vol_num == target_volume_index - 1 and vol_data.get("type") == "detail":
            previous_volume_detail = vol_data.get("detail")

    target_volume = volumes_dict.get(str(target_volume_index)) or {}
    if target_volume.get("type") == "detail":
        existing_volume_detail = target_volume.get("detail")

    start_chapter_num = accumulated_chapters + 1
    expected_chapter_range = (
        start_chapter_num,
        start_chapter_num + chapters_max - 1,
    )
    expected_total_chapter_count = max(current_total_chapter_count, expected_chapter_range[1])

    return {
        "framework_content": framework_content,
        "target_volume_index": target_volume_index,
        "chapters_count_range": (chapters_min, chapters_max),
        "start_chapter_num": start_chapter_num,
        "framework_header": volumes_data.get("framework_header", ""),
        "framework_footer": volumes_data.get("framework_footer", ""),
        "volumes_data": volumes_data,
        "previous_volume_detail": previous_volume_detail,
        "existing_volume_detail": existing_volume_detail,
        "expected_chapter_range": expected_chapter_range,
        "expected_total_chapter_count": expected_total_chapter_count,
        "current_total_chapter_count": current_total_chapter_count,
        "total_volumes": total_volumes,
    }


def _validate_story_framework_mode_switch(
    request: ExpandStoryRequest,
    db: Session,
) -> None:
    normalized_mode = str(request.expansion_mode or "auto").strip()
    if normalized_mode in {"epic_framework", "volume_detail"}:
        return

    if _resolve_story_target_chapters(request) is None:
        return

    epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(request.project_id)
    has_framework = bool((epic_framework_state.epic_framework or "").strip()) or bool(
        epic_framework_state.framework_generated_at
    )
    if not has_framework:
        return

    if request.reset_epic_framework:
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "当前项目已存在长篇框架。若要继续长篇路线，请使用单卷细化协同；"
            "若要切回常规协同，请确认清空旧框架后再执行。"
        ),
    )


def _resolve_story_target_chapters(request: ExpandStoryRequest) -> Optional[int]:
    if request.expansion_mode == "epic_framework":
        candidates = [
            int(value)
            for value in [request.target_total_chapters, request.total_chapters_max]
            if value is not None
        ]
        return max(candidates) if candidates else None
    return request.target_total_chapters


def _resolve_story_target_characters(request: ExpandStoryRequest) -> Optional[int]:
    if request.expansion_mode == "volume_detail" and request.volume_character_increment is not None:
        increment = max(0, int(request.volume_character_increment))
        current_count = max(0, int(request.current_character_count or 0))
        parsed_count = _estimate_character_count_from_text(request.characters or "")
        current_count = max(current_count, parsed_count)
        return current_count + increment
    return request.target_total_characters


def _build_story_written_chapter_preview(
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    result = {
        "effective_outline": request.current_outline or "",
        "effective_current_chapter_count": int(request.current_chapter_count or 0),
        "written_chapter_count": 0,
        "warnings": [],
        "applied": False,
    }

    if request.expansion_mode == "volume_detail":
        return result
    if getattr(request, "preserve_written_mode", "extract_extend") == "regenerate_all":
        return result

    chapter_query = text(
        """
        SELECT chapter_number, title, content, summary, summary_data
        FROM chapters
        WHERE project_id = :project_id
          AND content IS NOT NULL
          AND content != ''
        ORDER BY chapter_number ASC
        """
    )
    chapter_rows_result = db.execute(chapter_query, {"project_id": request.project_id})
    chapter_rows = chapter_rows_result.fetchall() if hasattr(chapter_rows_result, "fetchall") else []
    written_count = len(chapter_rows)
    result["written_chapter_count"] = written_count

    if written_count <= 0:
        return result

    from app.services.agents.written_chapters_handler import build_written_chapter_summary_preview

    preview_sections = []
    for row in chapter_rows:
        chapter_number = row[0]
        chapter_title = row[1] or f"第{chapter_number}章"
        chapter_content = row[2] or ""
        chapter_summary = row[3] or ""
        chapter_summary_data = row[4]
        preview_text = build_written_chapter_summary_preview(
            chapter_number=chapter_number,
            title=chapter_title,
            content=chapter_content,
            summary=chapter_summary,
            summary_data=chapter_summary_data,
        )
        preview_sections.append(
            f"第{chapter_number}章：{chapter_title}\n- 已写摘要：{preview_text}"
        )

    result["effective_outline"] = "\n\n".join(preview_sections)
    result["effective_current_chapter_count"] = max(
        int(request.current_chapter_count or 0),
        written_count,
    )
    result["applied"] = True

    if request.preserve_written_mode == "extract_extend":
        result["warnings"].append("检测到已写正文，预检阶段先按摘要预览，实际执行前会先提取已写章节细纲。")
    elif request.preserve_written_mode == "preserve_written":
        result["warnings"].append("检测到已写正文，预检阶段会按章节摘要保护已写内容。")

    return result


async def _prepare_story_execution_request(
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    request = _normalize_story_request_text_fields(request)
    preview = _build_story_written_chapter_preview(request, db)
    if not preview.get("applied"):
        return {
            "request": request,
            "written_chapter_count": int(preview.get("written_chapter_count") or 0),
            "warnings": list(preview.get("warnings") or []),
            "applied": False,
        }

    combined_world_setting = _build_project_world_setting_context(
        request.project_id,
        request.world_setting,
        db,
    )

    from app.services.agents.written_chapters_handler import process_written_chapters

    expander_bundle = _create_project_outline_expander(request.project_id, db)
    expander = expander_bundle["expander"]
    project_genre = expander_bundle["genre"]

    written_count, extracted_outline_text = await process_written_chapters(
        project_id=request.project_id,
        preserve_written_mode=request.preserve_written_mode,
        project_genre=project_genre,
        combined_world_setting=combined_world_setting,
        db=db,
        extractor_llm=expander.llm,
    )

    effective_outline = extracted_outline_text or preview["effective_outline"] or request.current_outline
    effective_chapter_count = int(preview["effective_current_chapter_count"] or request.current_chapter_count or 0)
    if written_count > 0 and request.preserve_written_mode in {"extract_extend", "preserve_written"}:
        effective_chapter_count = written_count

    warnings = list(preview.get("warnings") or [])
    if written_count > 0 and request.preserve_written_mode == "extract_extend":
        warnings.append("执行前已根据已写正文提取章节细纲，并据此重新计算协同缺口。")
    elif written_count > 0 and request.preserve_written_mode == "preserve_written":
        warnings.append("执行前已按已写章节摘要保护正文内容，并据此重新计算协同缺口。")

    return {
        "request": request.model_copy(
            update={
                "current_outline": effective_outline,
                "current_chapter_count": effective_chapter_count,
            }
        ),
        "written_chapter_count": written_count,
        "warnings": warnings,
        "applied": True,
    }


def _validate_expand_story_request(
    request: ExpandStoryRequest,
    *,
    allow_empty_targets_for_analysis: bool = False,
) -> None:
    if request.target_total_chapters is None and request.target_total_characters is None:
        if request.expansion_mode not in {"epic_framework", "volume_detail"} and not allow_empty_targets_for_analysis:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要提供目标章节数或目标人物数之一",
            )

    if request.target_total_chapters is not None and request.target_total_chapters <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目标章节数必须大于 0",
        )

    if request.target_total_characters is not None and request.target_total_characters <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目标人物数必须大于 0",
        )

    if request.volume_character_increment is not None:
        if request.volume_character_increment < 0 or request.volume_character_increment > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="单卷细化的人物新增上限必须在 0-30 之间",
            )

    if request.strategy not in VALID_STORY_EXPANSION_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同策略",
        )

    if request.intent not in VALID_STORY_EXPANSION_INTENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同意图",
        )

    if request.expansion_mode not in VALID_STORY_EXPANSION_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同扩展模式",
        )

    if request.preserve_written_mode not in VALID_PRESERVE_WRITTEN_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的已写章节处理模式",
        )

    if request.expansion_mode == "total":
        max_target_chapters = _get_conventional_collaboration_max_target_chapters(request.current_chapter_count)
        effective_total_chapters = max(
            int(request.current_chapter_count or 0),
            int(request.target_total_chapters or request.current_chapter_count or 0),
        )
        if effective_total_chapters > max_target_chapters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="常规协同仅支持总规模不超过 300 个细化章节；超过 300 章后必须改用长篇框架协同",
            )

    if request.expansion_mode == "epic_framework":
        if request.total_volumes is None or request.total_volumes < 3 or request.total_volumes > 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="长篇框架协同需要有效的总卷数 (3-50)",
            )
        if (
            request.total_chapters_min is None
            or request.total_chapters_max is None
            or request.total_chapters_min < 300
            or request.total_chapters_max > 5000
            or request.total_chapters_min > request.total_chapters_max
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="长篇框架协同需要有效的总章节范围 (300-5000)",
            )

    if request.expansion_mode == "volume_detail":
        if request.target_volume_index is None or request.target_volume_index < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="单卷细化协同需要指定有效的卷编号",
            )
        if (
            request.volume_chapters_min is None
            or request.volume_chapters_max is None
            or request.volume_chapters_min < VOLUME_DETAIL_MIN_CHAPTERS
            or request.volume_chapters_max > VOLUME_DETAIL_MAX_CHAPTERS
            or request.volume_chapters_min > request.volume_chapters_max
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"单卷细化协同需要有效的本卷章节范围 ({VOLUME_DETAIL_MIN_CHAPTERS}-{VOLUME_DETAIL_MAX_CHAPTERS})",
            )


def _build_story_expansion_analysis(
    *,
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    from app.services.story_expansion_coordinator import StoryExpansionCoordinator

    combined_world_setting = _build_project_world_setting_context(
        request.project_id,
        request.world_setting,
        db,
    )

    project_profile = _get_project_expansion_profile(request.project_id, db)
    project_genre = project_profile["genre"]
    project_planned_chapters = project_profile["planned_chapters_max"]

    coordinator = StoryExpansionCoordinator(
        project_id=request.project_id,
        genre=project_genre or "",
        planned_chapters_max=project_planned_chapters or 0,
    )
    target_total_chapters = _resolve_story_target_chapters(request)
    target_total_characters = _resolve_story_target_characters(request)
    epic_config = _resolve_story_epic_config(request)
    volume_detail_config = _resolve_story_volume_detail_config(request, db)
    if volume_detail_config is not None:
        expected_total = int(volume_detail_config.get("expected_total_chapter_count") or 0)
        if expected_total > 0:
            target_total_chapters = max(target_total_chapters or 0, expected_total)
    analysis = coordinator.analyze_expansion_request(
        current_outline=request.current_outline,
        characters=request.characters,
        world_setting=combined_world_setting,
        target_total_chapters=target_total_chapters,
        target_total_characters=target_total_characters,
        strategy=request.strategy,
        intent=request.intent,
        enable_auto_supplement=request.enable_auto_supplement,
        expansion_mode=request.expansion_mode,
        volume_character_increment=request.volume_character_increment,
        epic_config=epic_config,
        volume_detail_config=volume_detail_config,
    )
    return {
        "coordinator": coordinator,
        "combined_world_setting": combined_world_setting,
        "analysis": analysis,
        "volume_detail_config": volume_detail_config,
    }


def _get_workflow_session_columns(db: Session) -> set[str]:
    """获取 workflow_sessions 当前实际存在的列，兼容不同数据库版本。"""
    try:
        inspector = inspect(db.get_bind())
        return {column["name"] for column in inspector.get_columns("workflow_sessions")}
    except Exception as exc:
        logger.warning(f"⚠️  获取 workflow_sessions 列信息失败: {exc}")
        return set()


def _extract_requirement_from_workflow_data(raw_value: Any) -> Optional[str]:
    """从 workflow_sessions.data 或旧版 requirement 字段中提取用户需求。"""
    if raw_value is None:
        return None

    if isinstance(raw_value, str):
        text_value = raw_value.strip()
        if not text_value:
            return None
        try:
            raw_value = json.loads(text_value)
        except json.JSONDecodeError:
            return text_value

    if isinstance(raw_value, dict):
        for key in ("requirement", "description", "user_requirement", "prompt", "initial_idea"):
            value = raw_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(raw_value, ensure_ascii=False)

    if isinstance(raw_value, list):
        return json.dumps(raw_value, ensure_ascii=False)

    value = str(raw_value).strip()
    return value or None


def _save_workflow_requirement(db: Session, project_id: int, user_id: int, requirement: str) -> str:
    """保存最新工作流需求，兼容旧版 requirement 列和新版 data 列。"""
    columns = _get_workflow_session_columns(db)

    db.execute(
        text("DELETE FROM workflow_sessions WHERE project_id = :project_id"),
        {"project_id": project_id},
    )

    timestamp = utc_now().isoformat()

    if {"requirement", "created_at"}.issubset(columns):
        db.execute(
            text(
                """INSERT INTO workflow_sessions
                   (project_id, user_id, requirement, created_at)
                   VALUES (:project_id, :user_id, :requirement, :created_at)"""
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "requirement": requirement,
                "created_at": timestamp,
            },
        )
        return "legacy_requirement"

    payload = json.dumps({"requirement": requirement}, ensure_ascii=False)
    insert_columns = ["project_id", "user_id"]
    insert_values = [":project_id", ":user_id"]
    params: Dict[str, Any] = {
        "project_id": project_id,
        "user_id": user_id,
    }

    if "session_type" in columns:
        insert_columns.append("session_type")
        insert_values.append(":session_type")
        params["session_type"] = "workflow"

    if "status" in columns:
        insert_columns.append("status")
        insert_values.append(":status")
        params["status"] = "active"

    if "current_stage" in columns:
        insert_columns.append("current_stage")
        insert_values.append(":current_stage")
        params["current_stage"] = "concept"

    if "data" in columns:
        insert_columns.append("data")
        insert_values.append(":data")
        params["data"] = payload
    elif "requirement" in columns:
        insert_columns.append("requirement")
        insert_values.append(":requirement")
        params["requirement"] = requirement
    else:
        raise RuntimeError("workflow_sessions 缺少可用于保存需求的字段（data/requirement）")

    if "started_at" in columns:
        insert_columns.append("started_at")
        insert_values.append(":started_at")
        params["started_at"] = timestamp
    elif "created_at" in columns:
        insert_columns.append("created_at")
        insert_values.append(":created_at")
        params["created_at"] = timestamp

    db.execute(
        text(
            f"""INSERT INTO workflow_sessions
               ({", ".join(insert_columns)})
               VALUES ({", ".join(insert_values)})"""
        ),
        params,
    )
    return "data_json" if "data" in columns else "requirement_only"


def _resolve_workflow_requirement(db: Session, project_id: int) -> tuple[str, str]:
    """解析工作流需求，优先 workflow_sessions，其次 projects.description。"""
    columns = _get_workflow_session_columns(db)

    if "requirement" in columns:
        order_column = "created_at" if "created_at" in columns else "id"
        order_clause = f"{order_column} DESC, id DESC" if order_column != "id" else "id DESC"
        result = db.execute(
            text(
                f"""SELECT requirement FROM workflow_sessions
                    WHERE project_id = :project_id
                    ORDER BY {order_clause}
                    LIMIT 1"""
            ),
            {"project_id": project_id},
        ).fetchone()
        requirement = _extract_requirement_from_workflow_data(result[0] if result else None)
        if requirement:
            return requirement, "workflow_sessions.requirement"

    if "data" in columns:
        order_column = "started_at" if "started_at" in columns else ("created_at" if "created_at" in columns else "id")
        order_clause = f"{order_column} DESC, id DESC" if order_column != "id" else "id DESC"
        result = db.execute(
            text(
                f"""SELECT data FROM workflow_sessions
                    WHERE project_id = :project_id
                    ORDER BY {order_clause}
                    LIMIT 1"""
            ),
            {"project_id": project_id},
        ).fetchone()
        requirement = _extract_requirement_from_workflow_data(result[0] if result else None)
        if requirement:
            return requirement, "workflow_sessions.data"

    project_result = db.execute(
        text("SELECT description FROM projects WHERE id = :project_id"),
        {"project_id": project_id},
    ).fetchone()
    if project_result and project_result[0]:
        return project_result[0], "projects.description"

    return "根据项目设定进行创作", "default"


@router.post("/start")
async def start_workflow(
    request: StartWorkflowRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    启动工作流程

    请求体:
    {
        "project_id": 1,
        "requirement": "创作需求描述"
    }
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info("🚀 开始启动工作流程...")
        logger.info(f"   用户ID: {current_user.id}")
        logger.info(f"   项目ID: {request.project_id}")
        logger.info(f"   需求: {request.requirement[:50]}...")
        
        project_id = request.project_id
        requirement = request.requirement
        # 目标章节数配置（可选）
        target_chapter_count = request.target_chapter_count
        if target_chapter_count is None or target_chapter_count <= 0:
            target_chapter_count = 100

        if not project_id or not requirement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or requirement",
            )

        # 初始化Agent
        logger.info("   正在初始化Agent...")
        await coordinator.initialize_agents()
        logger.info("   ✅ Agent初始化完成")
        logger.info(f"   目标章节数: {target_chapter_count}")

        # 🔧 关键修复：保存requirement到数据库
        from sqlalchemy import text
        from datetime import datetime

        # 🆕 如果是重新开始模式，清空所有旧数据
        cleared_data = {"chapters": 0, "settings": False}
        if request.clear_existing:
            logger.info("🗑️  重新开始模式：开始清空现有内容...")
            try:
                # 1. 删除所有章节
                delete_chapters_query = text("DELETE FROM chapters WHERE project_id = :project_id")
                result = db.execute(delete_chapters_query, {"project_id": project_id})
                cleared_data["chapters"] = result.rowcount
                logger.info(f"   ✅ 已删除 {cleared_data['chapters']} 个章节")

                # 2. 清空 project_settings 中的旧内容
                WorkflowContextBuilder(db).update_project_settings_fields(
                    project_id,
                    concept=None,
                    world_setting=None,
                    characters=None,
                    plot_outline=None,
                    chapter_draft=None,
                    review_report=None,
                    final_version=None,
                    epic_framework=None,
                    epic_volumes_detail=None,
                    epic_framework_generated_at=None,
                    stage_one_status="pending",
                    stage_two_status="pending",
                    stage_three_status="pending",
                    stage_four_status="pending",
                    stage_five_status="pending",
                )
                cleared_data["settings"] = True
                logger.info(f"   ✅ 已清空项目设定与阶段状态（概念、大纲、世界观、人物、长篇框架等）")

                # 4. 清理记忆管理
                try:
                    clear_memory_query = text("""
                        UPDATE memory SET current_chapter = NULL
                        WHERE project_id = :project_id
                    """)
                    db.execute(clear_memory_query, {"project_id": project_id})
                    logger.info(f"   ✅ 已清理记忆管理")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命）: {e}")

                db.commit()
                logger.info("✅ 重新开始模式：所有旧内容已清空")

            except Exception as e:
                logger.error(f"❌ 清空旧内容失败: {e}")
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"清空旧内容失败: {str(e)}"
                )

        try:
            storage_mode = _save_workflow_requirement(
                db=db,
                project_id=project_id,
                user_id=current_user.id,
                requirement=requirement,
            )

            # 🆕 同时更新 projects 表的 description 字段（关键修复！）
            update_project_query = text(
                "UPDATE projects SET description = :description WHERE id = :project_id"
            )
            db.execute(update_project_query, {
                "description": requirement,
                "project_id": project_id
            })

            db.commit()
            logger.info(f"   ✅ 工作流会话已保存到数据库（模式: {storage_mode}）")
            logger.info(f"   ✅ 项目描述已更新为用户需求")
        except Exception as e:
            logger.error(f"   ⚠️  保存工作流会话失败: {e}")
            db.rollback()
            # 不抛出异常，继续执行工作流

        # 保存工作流程状态（内存中）
        coordinator.set_workflow_state(project_id, {
            "project_id": project_id,
            "user_id": current_user.id,
            "requirement": requirement,
            "status": "running",
            "target_chapter_count": target_chapter_count,
        })

        # 返回初始化的阶段信息
        stages = {
            "concept": {
                "id": "concept",
                "name": "概念开发",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.CONCEPT),
            },
            "structure": {
                "id": "structure",
                "name": "结构设计",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.STRUCTURE),
            },
            "content": {
                "id": "content",
                "name": "内容创作",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.CONTENT),
            },
            "review": {
                "id": "review",
                "name": "质量评审",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.REVIEW),
            },
            "iteration": {
                "id": "iteration",
                "name": "迭代优化",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.ITERATION),
            },
        }

        return {"status": "success", "stages": stages}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/execute-stage")
async def execute_stage(
    request: ExecuteStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    执行阶段（同步）

    请求体:
    {
        "project_id": 1,
        "stage": "concept"
    }
    """
    # 先提取参数，确保在异常处理中可访问
    project_id = request.project_id
    stage = request.stage
    
    try:
        if not project_id or not stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or stage",
            )

        # 执行阶段
        stage_enum = StageType(stage)
        
        # 🔔 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage,
            status='active',
            progress=0
        )
        
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {"project_id": project_id, "user_id": current_user.id},
        )
        
        # 🔔 推送阶段完成状态
        output_str = str(stage_output.output) if stage_output.output else None
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage,
            status='completed',
            output=output_str,
            progress=100
        )

        return {
            "status": "success",
            "stage": stage,
            "output": stage_output.output,
            "agents": [
                coordinator.get_agents(project_id)[agent_id]
                for agent_id in stage_output.agents_involved
            ],
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/execute-stage-async")
async def execute_stage_async(
    request: ExecuteStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    异步执行阶段（立即返回task_id，后台执行）
    🆕 支持流式输出：content/review/iteration 阶段可实时推送生成内容

    请求体:
    {
        "project_id": 1,
        "stage": "concept",
        "enable_streaming": true  // 🆕 是否启用流式输出
    }

    响应:
    {
        "task_id": "uuid-string",
        "status": "running",
        "streaming_enabled": true  // 🆕 是否启用了流式输出
    }
    """
    import asyncio
    from sqlalchemy import text

    project_id = request.project_id
    stage = request.stage
    requirement = (request.requirement or "").strip()
    enable_streaming = request.enable_streaming

    # 🔧 添加请求日志
    logger.info(f"📥 收到异步执行请求: project_id={project_id}, stage={stage}, streaming={enable_streaming}")

    # 🆕 判断是否支持流式输出（concept/structure/content/review/iteration 阶段都支持）
    streaming_stages = ["concept", "structure", "content", "review", "iteration"]
    streaming_enabled = (
        enable_streaming and
        stage in streaming_stages and
        STREAMING_AVAILABLE
    )

    try:
        if not project_id or not stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or stage",
            )

        # 验证stage值
        stage_enum = StageType(stage)

        if requirement:
            storage_mode = _save_workflow_requirement(
                db=db,
                project_id=project_id,
                user_id=current_user.id,
                requirement=requirement,
            )
            db.execute(
                text("UPDATE projects SET description = :description WHERE id = :project_id"),
                {
                    "description": requirement,
                    "project_id": project_id,
                },
            )
            db.commit()
            logger.info(f"   ✅ 已保存异步执行需求（模式: {storage_mode}）")

        # 生成task_id
        task_id = str(uuid.uuid4())
        logger.info(f"🎯 创建异步任务: {task_id} (stage={stage}, project_id={project_id}, streaming={streaming_enabled})")

        # 创建任务记录
        insert_query = text("""
            INSERT INTO generation_history
            (project_id, task_type, task_id, status, created_at)
            VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """)

        db.execute(insert_query, {
            "project_id": project_id,
            "task_type": f"workflow_stage_{stage}",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        # 🆕 根据是否启用流式输出选择执行方式
        if streaming_enabled:
            # 使用流式输出执行
            asyncio.create_task(
                _run_execute_stage_with_streaming_serialized(
                    task_id,
                    project_id,
                    stage_enum,
                    current_user.id,
                    db,
                )
            )
            logger.info(f"   🌊 流式后台任务已启动")
        else:
    # 使用传统方式执行
            asyncio.create_task(
                _run_execute_stage_background_serialized(
                    task_id,
                    project_id,
                    stage_enum,
                    current_user.id,
                    db,
                    getattr(request, "regenerate", False),
                    getattr(request, "targets", None),
                    getattr(request, "feedback", None),
                )
            )
            logger.info(f"   🚀 后台任务已启动")

        return {
            "task_id": task_id,
            "status": "running",
            "streaming_enabled": streaming_enabled  # 🆕 返回是否启用了流式输出
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        logger.error(f"❌ 异步任务创建失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def trigger_auto_system_detection(
    project_id: int,
    content: str,
    content_type: str,
    db: Session
):
    """
    触发体系自动检测（异步后台执行，不阻塞主流程）
    
    Args:
        project_id: 项目ID
        content: 待分析的内容
        content_type: 内容类型（outline 或 chapter）
        db: 数据库会话
    """
    try:
        logger.info(f"🎉 触发体系自动检测: {content_type}, 项目ID={project_id}")
        
        # 调用检测服务
        result = await auto_create_system_collections(
            project_id=project_id,
            content=content,
            db=db,
            content_type=content_type
        )
        
        # 如果有创建的集合，通过WebSocket通知前端
        if result.get("created_collections"):
            created_names = result["created_collections"]
            message = f"✨ 已自动添加 {len(created_names)} 个体系：{', '.join(created_names)}"
            
            await ws_manager.send_notification(
                project_id=project_id,
                message=message,
                type="system_collections_created",
                data=result
            )
            
            logger.info(f"✅ {message}")
        else:
            logger.info("ℹ️ 未检测到需要添加的新体系")
            
    except Exception as e:
        logger.error(f"❌ 体系自动检测失败（不影响主流程）: {e}")
        import traceback
        traceback.print_exc()


async def execute_stage_background(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session, regenerate: bool = False, targets: Optional[list[str]] = None, feedback: Optional[str] = None):
    """后台执行阶段任务"""
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔥 开始执行后台任务: {task_id}")
        workflow_context_builder = WorkflowContextBuilder(db)
        project_profile = workflow_context_builder.get_project_profile(project_id)
        real_coord = coordinator.get_real_coordinator(project_id)
        
        # 🆕 关键修复：确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 检测到协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")
        
        # 🔧 关键修复：设置当前项目上下文，避免项目间数据污染
        coordinator.set_project_context(project_id)
        logger.info(f"   ✅ 已设置项目上下文：project_id={project_id}")
        
        # 🔧 关键修复：立即从数据库加载当前项目的基本信息，注入到 project_context
        try:
            project_profile, real_coord = _sync_real_coordinator_project_context(
                project_id,
                workflow_context_builder,
                project_profile,
            )
        except Exception as e:
            logger.warning(f"⚠️ 项目基本信息注入失败：{e}")

        if stage_enum == StageType.CONCEPT:
            try:
                _inject_recent_project_novelty_context(
                    db,
                    project_id=project_id,
                    user_id=user_id,
                    real_coord=real_coord,
                    genre=project_profile.genre or None,
                )
                logger.info("   ✅ 已注入近期项目避重约束")
            except Exception as e:
                logger.warning(f"⚠️ 近期项目避重约束注入失败：{e}")

        # 🆕 确保 project_settings 记录存在（关键修复！）
        if workflow_context_builder.ensure_project_settings_record(project_id):
            logger.info(f"   📝 初始化 project_settings 记录")
            logger.info(f"   ✅ project_settings 记录已创建")
        
        requirement, requirement_source = _resolve_workflow_requirement(db, project_id)
        logger.info(f"   ✅ 用户需求来源: {requirement_source}")
        logger.info(f"   ✅ 当前用户需求: {requirement[:50]}...")
        
        # 🆕 题材与篇幅规划注入（概念阶段首次启动时）
        if stage_enum == StageType.CONCEPT and not regenerate:
            try:
                genre = project_profile.genre
                sub_genre = project_profile.sub_genre
                planned_length_type = project_profile.planned_length_type
                planned_chapters_min = project_profile.planned_chapters_min
                planned_chapters_max = project_profile.planned_chapters_max
                user_outline_plan = project_profile.user_outline_plan

                # 🆕 如果有自定义大纲规划，先解析
                if user_outline_plan and user_outline_plan.strip():
                    logger.info("📝 检测到用户自定义大纲规划，开始解析...")

                    # 调用规划解析Agent
                    if real_coord and hasattr(real_coord, 'parse_outline_plan'):
                        parsed_plan = real_coord.parse_outline_plan(
                            user_outline_plan=user_outline_plan,
                            genre=genre or "",
                            planned_length_type=planned_length_type or ""
                        )

                        if parsed_plan:
                            logger.info(f"✅ 大纲规划解析完成: {list(parsed_plan.keys())}")

                            # 将解析结果注入到项目上下文
                            real_coord.project_context.update({
                                "genre": genre,
                                "sub_genre": sub_genre,
                                "planned_length_type": planned_length_type,
                                "planned_chapters_min": planned_chapters_min,
                                "planned_chapters_max": planned_chapters_max,
                                "parsed_outline_plan": parsed_plan
                            })
                        else:
                            logger.warning("⚠️ 大纲规划解析返回空结果")

                # 将题材篇幅信息添加到需求文本（供prompt使用）
                if genre or planned_length_type:
                    genre_info = f"\n\n【题材与篇幅信息】\n"
                    if genre:
                        genre_info += f"- 题材类型：{genre}"
                        if sub_genre:
                            genre_info += f" / {sub_genre}"
                        genre_info += "\n"
                    if planned_length_type:
                        length_labels = {"short": "短篇", "mid": "中篇", "long": "长篇", "epic": "超长篇"}
                        genre_info += f"- 篇幅规划：{length_labels.get(planned_length_type, planned_length_type)}"
                        if planned_chapters_min and planned_chapters_max:
                            genre_info += f"（{planned_chapters_min}-{planned_chapters_max}章）"
                        genre_info += "\n"
                    
                    requirement += genre_info
                    logger.info(f"✅ 已注入题材与篇幅信息到需求文本")
                        
            except Exception as e:
                logger.warning(f"⚠️ 题材与篇幅信息注入失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 📝 概念阶段附加评审反馈到需求（仅影响生成，不会直接写库）
        if stage_enum == StageType.CONCEPT and feedback:
            requirement = f"{requirement}\n用户评审反馈：{feedback}"

        # 🆕 相互参考约束注入（仅重生时）
        if stage_enum == StageType.CONCEPT and regenerate:
            try:
                existing_context = workflow_context_builder.load_stage_text_context(project_id)
                concept_txt = existing_context.concept
                world_txt = existing_context.world_setting
                char_txt = existing_context.characters

                def clip(s, n=1200):
                    return s[:n] if isinstance(s, str) else ""

                targets_set = set(targets or ['story', 'world'])
                # 重生story：参考世界观+人物
                if 'story' in targets_set and 'world' not in targets_set:
                    requirement += f"\n\n【一致性约束】需与既有世界观与人物设定保持一致。\n【世界观摘要】\n{clip(world_txt)}\n【人物设定摘要】\n{clip(char_txt)}"
                # 重生world：参考故事概念+人物
                elif 'world' in targets_set and 'story' not in targets_set:
                    requirement += f"\n\n【一致性约束】需与既有故事概念与人物设定保持一致。\n【故事概念摘要】\n{clip(concept_txt)}\n【人物设定摘要】\n{clip(char_txt)}"
                # 重生story+world：参考人物
                else:
                    requirement += f"\n\n【一致性约束】需与既有人物设定保持一致。\n【人物设定摘要】\n{clip(char_txt)}"

                logger.info(f"✅ 已注入相互参考约束（targets={list(targets_set) if targets_set else []}，长度={len(requirement)}）")
            except Exception as e:
                logger.warning(f"⚠️ 相互参考约束注入失败: {e}")

        # 🔔 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='active',
            progress=0
        )

        # 🆕 推送任务开始进度
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message=f"开始执行{stage_enum.value}阶段"
        )
        logger.info(f"   📡 已发送任务开始进度: {task_id}")

        # 🆕 定义每个阶段的 Agent 配置（使用 snake_case 命名规范）
        STAGE_AGENTS = {
            'concept': [
                {'id': 'creative_director', 'name': '创意总监'},
                {'id': 'worldview_architect', 'name': '世界观架构师'},
                {'id': 'character_designer', 'name': '人物设计师'},
            ],
            'structure': [
                {'id': 'plot_architect', 'name': '情节架构师'},
                {'id': 'event_validator', 'name': '事件验证官'},
            ],
            'content': [
                {'id': 'content_creator', 'name': '内容创作师'},
                {'id': 'style_optimizer', 'name': '文风优化师'},
            ],
            'review': [
                {'id': 'quality_reviewer', 'name': '质量评审官'},
            ],
            'iteration': [
                {'id': 'iteration_coordinator', 'name': '迭代协调官'},
                {'id': 'content_reviser', 'name': '内容修订师'},
                {'id': 'final_reviewer', 'name': '最终审核官'},
            ],
        }

        # 🆕 推送 Agent 开始工作状态
        stage_agents = STAGE_AGENTS.get(stage_enum.value, [])
        # 🔧 概念阶段的重生：仅按目标推送相关Agent（默认 story+world，不包含人物）
        if stage_enum.value == 'concept' and regenerate:
            target_set = set(targets or ['story', 'world'])
            selected_ids = []
            if 'story' in target_set:
                selected_ids.append('creative_director')
            if 'world' in target_set:
                selected_ids.append('worldview_architect')
            stage_agents = [a for a in stage_agents if a['id'] in selected_ids]
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在工作中...'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 开始状态")

        # 🆕 设置进度回调（用于任务分块执行）
        async def progress_callback(proj_id: int, t_id: str, progress: int, message: str):
            """进度回调函数，通过WebSocket发送进度更新"""
            try:
                await ws_manager.send_task_progress(
                    project_id=proj_id,
                    task_id=t_id,
                    progress=progress,
                    message=message
                )
                # 🆕 同步更新所有 Agent 进度
                for agent in stage_agents:
                    await ws_manager.send_agent_status(
                        project_id=proj_id,
                        stage=stage_enum.value,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        status='working',
                        progress=progress,
                        message=message
                    )
                logger.info(f"   📡 进度推送: {progress}% - {message}")
            except Exception as e:
                logger.error(f"   ⚠️  进度推送失败: {e}")

        # 🆕 为 coordinator 设置进度回调（如果支持）
        if hasattr(coordinator, 'set_progress_callback'):
            coordinator.set_progress_callback(progress_callback, task_id, project_id)  # type: ignore
            logger.info(f"   ✅ 已启用任务分块执行模式")

        # 🔧 将重生信息注入到真实协调器的 project_context（供概念阶段条件执行使用）
        if stage_enum == StageType.CONCEPT:
            real_coord = coordinator.get_real_coordinator(project_id)
            if real_coord and hasattr(real_coord, 'project_context'):
                real_coord.project_context["regenerate"] = regenerate
                real_coord.project_context["regenerate_targets"] = targets or []
                logger.info(f"   🎯 概念阶段重生信息已注入: regenerate={regenerate}, targets={targets}")

        # 🔧 关键修复：将 requirement 传递给 execute_stage
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {
                "project_id": project_id, 
                "user_id": user_id,
                "requirement": requirement,  # ✅ 传递真实的用户需求
                "regenerate": regenerate,
                "targets": targets,
                "feedback": feedback,
            },
        )
        
        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, result = :result, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        # 🔥 关键修复：根据阶段类型提取正确的内容字段
        output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
        if stage_enum == StageType.ITERATION:
            # 迭代优化阶段：提取 revised_content
            result_str = output_data.get("revised_content", "") or output_data.get("final_review", "")
            logger.info(f"   📝 迭代优化结果字数: {len(result_str) if result_str else 0}")
        elif stage_enum == StageType.CONTENT:
            # 内容创作阶段：提取 content 或 chapters
            result_str = output_data.get("content", "") or output_data.get("chapters", "")
            logger.info(f"   📝 章节内容字数: {len(result_str) if isinstance(result_str, str) else 0}")
        elif stage_enum == StageType.REVIEW:
            # 质量评审阶段：提取 review
            result_str = output_data.get("review", "")
            logger.info(f"   📝 评审报告字数: {len(result_str) if result_str else 0}")
        else:
            # 其他阶段：使用整个输出的字符串表示
            result_str = str(stage_output.output) if stage_output.output else ""

        db.execute(update_query, {
            "status": "completed",
            "result": result_str,
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 任务完成: {task_id}")
        
        # 🆕 保存阶段输出到 project_settings（关键修复！）
        try:
            if stage_enum == StageType.CONCEPT:
                # 保存概念开发结果（支持评审/重生的目标字段选择）
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                existing_storage_state = workflow_context_builder.load_concept_storage_state(project_id)
                existing_concept_val = existing_storage_state.concept_value
                existing_world_val = existing_storage_state.world_setting_value
                existing_characters_val = existing_storage_state.characters_value

                targets_set = set(targets or [])
                is_regen = bool(regenerate)

                # 计算要保存的字段：非重生则全部覆盖；重生则按目标覆盖
                concept_to_save = output_data.get("concept", "") if not is_regen or ("story" in targets_set) else existing_concept_val
                world_to_save = output_data.get("worldview", output_data.get("world_setting", "")) if not is_regen or ("world" in targets_set) else existing_world_val
                characters_to_save = output_data.get("characters", []) if not is_regen else existing_characters_val
                if not is_regen:
                    characters_to_save = _normalize_concept_stage_characters_for_storage(
                        project_id,
                        characters_to_save,
                        concept_text=str(concept_to_save or ""),
                        world_setting_text=str(world_to_save or ""),
                    )

                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    concept=json.dumps(concept_to_save, ensure_ascii=False),
                    world_setting=json.dumps(world_to_save, ensure_ascii=False),
                    characters=json.dumps(characters_to_save, ensure_ascii=False),
                    stage_one_status="completed",
                )
                logger.info(f"   💾 已保存概念开发结果到 project_settings（重生={is_regen}, targets={list(targets_set) if targets_set else []}）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title
                if concept_to_save and isinstance(concept_to_save, str):
                    try:
                        _sync_project_title_from_concept(db, project_id, concept_to_save)
                    except Exception as e:
                        logger.warning(f"   ⚠️  提取日志标题失败: {e}")
                
                # 🆕 自动解析人物卡并同步到结构化characters表
                if characters_to_save and isinstance(characters_to_save, str):
                    await ws_manager.send_task_progress(
                        project_id=project_id,
                        task_id=task_id,
                        progress=85,
                        message="🔄 正在同步人物卡..."
                    )
                    
                    sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
                    try:
                        from app.services.character_parser import parse_and_sync_characters
                        
                        sync_result = parse_and_sync_characters(
                            project_id=project_id,
                            characters_text=characters_to_save,
                            db_session=db
                        )
                        logger.info(f"   🔄 人物卡同步完成: 解析 {sync_result['parsed']} 个, "
                                   f"创建 {sync_result['created']} 个, 更新 {sync_result['updated']} 个")
                    except Exception as e:
                        logger.warning(f"   ⚠️  自动同步人物卡失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 🆕 同步概念开发结果到向量库
                try:
                    from app.services.vector_sync import sync_to_vector_db, upsert_character_to_vector_db, upsert_setting_to_vector_db
                    from app.models.character import Character
                    from app.models.setting import SettingItem
                    
                    logger.info(f"   🔄 开始同步概念开发结果到向量库...")
                    
                    # 同步世界观设定
                    if world_to_save and isinstance(world_to_save, str) and world_to_save.strip():
                        sync_to_vector_db(
                            kb_type="world",
                            name="世界观设定",
                            content=world_to_save,
                            metadata={
                                "project_id": str(project_id),
                                "title": "世界观设定",
                                "category": "world_setting"
                            }
                        )
                        logger.info(f"   ✅ 已同步世界观设定到向量库")
                    
                    # 同步人物设定(从数据库中查询已解析的人物)
                    characters_in_db = db.query(Character).filter(Character.project_id == project_id).all()
                    if characters_in_db:
                        for char in characters_in_db:
                            # 使用Character模型的实际字段
                            char_content = f"""
人物名称: {char.name}
故事立场: {char.role or '未设定'}
角色定位: {getattr(char, 'role_position', None) or '未设定'}
所属势力: {char.faction or '未设定'}
状态: {char.life_status or '未知'}
简介: {char.summary or ''}
详细信息: {char.profile or ''}
""".strip()
                            
                            upsert_character_to_vector_db(
                                character_id=char.id,
                                character_name=char.name,
                                content=char_content,
                                project_id=project_id,
                                metadata={
                                    "character_id": str(char.id),
                                    "name": char.name,
                                    "role": char.role or '',
                                    "role_position": getattr(char, "role_position", None) or "",
                                }
                            )
                        logger.info(f"   ✅ 已同步 {len(characters_in_db)} 个人物到向量库")
                    
                    # 同步已识别的设定项（通过 SettingCollection 关联查询）
                    from app.models.setting import SettingCollection
                    collections_in_db = db.query(SettingCollection).filter(SettingCollection.project_id == project_id).all()
                    settings_count = 0
                    for collection in collections_in_db:
                        for setting in collection.items:
                            # 构建设定完整描述
                            setting_content = f"""
**设定名称**: {setting.name}
**类别**: {collection.category or ''}
**详细描述**: {setting.content or ''}
""".strip()
                            
                            upsert_setting_to_vector_db(
                                setting_id=setting.id,
                                setting_name=setting.name,
                                content=setting_content,
                                project_id=project_id,
                                category=collection.category or 'unknown',
                                metadata={
                                    "setting_id": str(setting.id),
                                    "name": setting.name,
                                    "category": collection.category or ''
                                }
                            )
                            settings_count += 1
                    if settings_count > 0:
                        logger.info(f"   ✅ 已同步 {settings_count} 个设定项到向量库")
                        
                except Exception as vector_error:
                    logger.warning(f"   ⚠️  同步到向量库失败: {vector_error}")
                    import traceback
                    traceback.print_exc()
            
            elif stage_enum == StageType.STRUCTURE:
                # 保存结构设计结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                plot_outline_content = output_data.get("plot_outline", "")
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    plot_outline=json.dumps(plot_outline_content, ensure_ascii=False),
                    stage_two_status="completed",
                )
                logger.info(f"   💾 已保存结构设计结果到 project_settings")
                
                # 🆕 同步情节大纲到向量库
                try:
                    from app.services.vector_sync import sync_to_vector_db
                    
                    if plot_outline_content and isinstance(plot_outline_content, str) and plot_outline_content.strip():
                        sync_to_vector_db(
                            kb_type="plot",
                            name="情节大纲",
                            content=plot_outline_content,
                            metadata={
                                "project_id": str(project_id),
                                "title": "情节大纲",
                                "type": "plot_outline"
                            }
                        )
                        logger.info(f"   ✅ 已同步情节大纲到向量库")
                except Exception as vector_error:
                    logger.warning(f"   ⚠️  同步情节大纲到向量库失败: {vector_error}")
                
                # 🎉 异步触发体系自动检测（不阻塞主流程）
                asyncio.create_task(
                    trigger_auto_system_detection(
                        project_id=project_id,
                        content=plot_outline_content if isinstance(plot_outline_content, str) else json.dumps(plot_outline_content),
                        content_type="outline",
                        db=db
                    )
                )
            
            elif stage_enum == StageType.CONTENT:
                # 保存内容创作结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    chapter_draft=json.dumps(output_data.get("content", output_data.get("chapters", "")), ensure_ascii=False),
                    stage_three_status="completed",
                )
                logger.info(f"   💾 已保存内容创作结果到 project_settings")
            
            elif stage_enum == StageType.REVIEW:
                # 保存质量评审结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    review_report=json.dumps(output_data.get("review", ""), ensure_ascii=False),
                    stage_four_status="completed",
                )
                logger.info(f"   💾 已保存质量评审结果到 project_settings")
            
            elif stage_enum == StageType.ITERATION:
                # 保存迭代优化结果
                # 🔥 关键修复：直接使用已经解析好的 result_str，而不是重新解析
                final_version_content = result_str  # result_str 已经是正确的 revised_content
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    final_version=json.dumps(final_version_content, ensure_ascii=False),
                    stage_five_status="completed",
                )
                logger.info(f"   💾 已保存迭代优化结果到 project_settings，内容字数: {len(final_version_content) if final_version_content else 0}")
        
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")
            # 不影响主流程，继续执行
        
        # 🆕 推送任务完成通知（关键！前端依赖此事件停止轮询）
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={"output": result_str}
        )
        logger.info(f"   📡 已发送任务完成通知: {task_id}")

        # 🆕 推送 Agent 完成状态
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 完成状态")

        # 🔔 推送阶段完成状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='completed',
            output=result_str,
            progress=100
        )

        # 🆕 保存记忆到数据库（统一存储方案）
        try:
            from app.models.memory import Memory

            # 🆕 消息数量上限
            MAX_MESSAGES = 50

            # 查找或创建记忆记录
            memory = db.query(Memory).filter(
                Memory.project_id == project_id
            ).order_by(Memory.updated_at.desc()).first()

            # 构建新的消息记录
            new_message = {
                "role": "assistant",
                "content": result_str[:2000] if result_str else "",  # 限制长度
                "stage": stage_enum.value,
                "timestamp": utc_now().isoformat()
            }

            if memory:
                # 更新现有记忆
                messages = memory.messages or []
                messages.append(new_message)

                # 🆕 限制消息数量（保留最近 MAX_MESSAGES 条）
                if len(messages) > MAX_MESSAGES:
                    messages = messages[-MAX_MESSAGES:]

                memory.messages = messages
                memory.current_scene = stage_enum.value
                db.add(memory)
            else:
                # 创建新记忆
                # 获取用户ID
                project = db.query(Project).filter(Project.id == project_id).first()
                if project:
                    memory = Memory(
                        project_id=project_id,
                        user_id=project.user_id,
                        messages=[new_message],
                        current_scene=stage_enum.value
                    )
                    db.add(memory)

            db.commit()
            logger.info(f"   💾 已保存阶段记忆到数据库: {stage_enum.value}")
        except Exception as mem_error:
            logger.error(f"   ⚠️  保存记忆失败: {mem_error}")
            # 不影响主流程

    except Exception as e:
        logger.error(f"❌ 后台任务失败: {task_id}, 错误: {str(e)}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.warning(f"⚠️  后台任务失败后回滚事务失败: {rollback_error}")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status, error = :error, completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        db.execute(update_query, {
            "status": "failed",
            "error": str(e),
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()
        
        # 🆕 推送任务失败通知（关键！前端依赖此事件停止轮询）
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
        logger.info(f"   📡 已发送任务失败通知: {task_id}")
        
        # 🔔 推送错误状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='error',
            progress=0
        )


async def execute_stage_with_streaming(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session):
    """
    🆕 使用流式输出执行阶段任务

    支持 content/review/iteration 阶段的实时内容推送
    """
    import logging
    from sqlalchemy import text
    from app.db.base import SessionLocal  # 🔧 导入 SessionLocal

    logger = logging.getLogger("uvicorn.error")

    # 🔧 关键修复：创建新的独立 db session（避免使用请求级别的 session）
    db = SessionLocal()
    workflow_context_builder = WorkflowContextBuilder(db)
    
    try:
        logger.info(f"🌊 开始流式执行后台任务: {task_id}")
        project_profile = workflow_context_builder.get_project_profile(project_id)
        real_coord = coordinator.get_real_coordinator(project_id)

        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 检测到协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")

        # 🔧 关键修复：设置当前项目上下文，避免项目间数据污染
        coordinator.set_project_context(project_id)
        logger.info(f"   ✅ 已设置项目上下文：project_id={project_id}")
        
        # 🔧 关键修复：立即从数据库加载当前项目的基本信息，注入到 project_context
        try:
            project_profile, real_coord = _sync_real_coordinator_project_context(
                project_id,
                workflow_context_builder,
                project_profile,
            )
        except Exception as e:
            logger.warning(f"⚠️ 项目基本信息注入失败：{e}")

        if stage_enum == StageType.CONCEPT:
            try:
                _inject_recent_project_novelty_context(
                    db,
                    project_id=project_id,
                    user_id=user_id,
                    real_coord=real_coord,
                    genre=project_profile.genre or None,
                )
                logger.info("   ✅ 已注入近期项目避重约束（流式）")
            except Exception as e:
                logger.warning(f"⚠️ 近期项目避重约束注入失败（流式）：{e}")
        
        # 确保 project_settings 记录存在
        if workflow_context_builder.ensure_project_settings_record(project_id):
            logger.info(f"   📝 初始化 project_settings 记录")
            logger.info("   ✅ project_settings 记录已创建")

        requirement, requirement_source = _resolve_workflow_requirement(db, project_id)
        logger.info(f"   ✅ 用户需求来源: {requirement_source}")

        # 🆕 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='active',
            progress=0
        )

        # 🆕 广播本阶段选用的模型，便于前端调试
        try:
            from app.core.config import settings
            default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3-max")
        except Exception:
            default_content_model = "qwen3-max"
        stage_task_type = None
        stage_model_override = None
        if stage_enum == StageType.CONTENT:
            stage_task_type = "chapter"
            stage_model_override = default_content_model
        elif stage_enum == StageType.REVIEW:
            stage_task_type = "review"
        elif stage_enum == StageType.ITERATION:
            stage_task_type = "review"
        stage_model = resolve_model_for_task(stage_task_type, stage_model_override) if stage_task_type else None
        if stage_model:
            await ws_manager.send_model_used(
                project_id=project_id,
                stage=stage_enum.value,
                model=stage_model,
                extra={
                    "source": "execute_stage_with_streaming",
                    "task_type": stage_task_type,
                }
            )

        # 🌊 发送流式输出开始通知
        await ws_manager.send_stream_start(project_id, stage_enum.value)

        STAGE_AGENTS_STREAMING = {
            'concept': [
                {'id': 'creative-director', 'name': '创意总监'},
                {'id': 'worldview-architect', 'name': '世界观架构师'},
                {'id': 'character-designer', 'name': '人物设计师'},
            ],
            'structure': [
                {'id': 'plot-architect', 'name': '情节架构师'},
                {'id': 'event-validator', 'name': '事件验证官'},
            ],
            'content': [
                {'id': 'content-creator', 'name': '内容创作师'},
                {'id': 'style-optimizer', 'name': '文风优化师'},
            ],
            'review': [
                {'id': 'quality-reviewer', 'name': '质量评审官'},
            ],
            'iteration': [
                {'id': 'iteration-coordinator', 'name': '迭代协调官'},
                {'id': 'content-reviser', 'name': '内容修订师'},
                {'id': 'final-reviewer', 'name': '最终审核官'},
            ],
        }

        # 🆕 推送 Agent 开始工作状态
        stage_agents = STAGE_AGENTS_STREAMING.get(stage_enum.value, [])
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在工作中...'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 开始状态（流式模式）")

        # 🌊 创建流式输出回调
        chunk_index = [0]  # 使用列表以便在闭包中修改
        total_chars = [0]  # 总字符数

        async def on_stream_chunk(chunk: str, idx: int):
            """流式输出回调：推送每个文本块到前端"""
            chunk_index[0] = idx
            total_chars[0] += len(chunk)
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage=stage_enum.value,
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )
            # 🆕 每 50 个 chunk 更新一次 Agent 进度（避免太频繁）
            if idx % 50 == 0:
                estimated_progress = min(90, idx // 5)  # 估算进度
                for agent in stage_agents:
                    await ws_manager.send_agent_status(
                        project_id=project_id,
                        stage=stage_enum.value,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        status='working',
                        progress=estimated_progress,
                        message=f'已生成 {total_chars[0]} 字...'
                    )

        # 🔥 尝试使用流式 LLM 调用
        result_str = ""
        use_streaming_llm = STREAMING_AVAILABLE and get_streaming_service is not None

        if use_streaming_llm:
            try:
                # 🌊 使用流式服务进行真正的流式 LLM 调用
                streaming_service = get_streaming_service()

                # 获取项目上下文（用于构建提示词）
                stage_context = workflow_context_builder.load_stage_text_context(project_id)

                # 构建流式调用的提示词
                if stage_enum == StageType.CONTENT:
                    # 内容创作阶段
                    plot_outline = stage_context.plot_outline
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    world_context = workflow_context_builder.build_world_setting_context(
                        project_id,
                        world_setting,
                    )
                    world_setting = world_context.combined_world_setting
                    # 🆕 开头/结尾方式定义（从头创作共享模块）
                    opening_styles = {
                        "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
                        "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
                        "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
                        "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
                        "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
                        "内心独白开头": ("内心独白开头", "从人物内心思绪入手，展现心理冲突或决策过程", ""),
                        "回忆插入开头": ("回忆插入开头", "通过回忆或闪回提供关键背景，丰富当前情节", ""),
                        "疯狂开头": ("疯狂开头", "从激烈冲突或混乱场面开始，立即抽住读者注意力", ""),
                        "对比开头": ("对比开头", "通过前后对比或境遇差异，强化情绪冲击", ""),
                        "时间跳跃开头": ("时间跳跃开头", "直接跳转到事件后的关键时刻，略过过程增加节奏", ""),
                    }
                    ending_styles = {
                        "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
                        "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
                        "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
                        "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撑效果", ""),
                        "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
                        "情感升华式": ("情感升华式", "通过情感浓度提升结束，留下余韵", ""),
                        "环境渲染式": ("环境渲染式", "以环境气氛变化暗示危机或转机", ""),
                        "对话留白式": ("对话留白式", "关键对话说一半留一半，制造疑问", ""),
                        "时间压力式": ("时间压力式", "引入倒计时或期限，增加紧迫感", ""),
                        "身份揭露式": ("身份揭露式", "暗示或半揭露人物真实身份，激发好奇", ""),
                    }

                    # 第一章使用固定的开头/结尾方式（适合开篇）
                    selected_opening = opening_styles["悬念开头"]
                    selected_ending = ending_styles["悬念式"]

                    system_prompt = """你是一位经验丰富的网络小说作家。请根据提供的情节大纲、世界观设定和人物设定，创作精彩的第一章内容。

创作要求：
1. 语言生动，描写细腻，符合网文风格
2. 对话自然，符合人物性格
3. 情节紧凑，引人入胜，注意爽点节奏
4. 场景描写要有画面感
5. 注意段落分隔，便于阅读
6. 第一章要快速建立世界观和主角形象
7. 使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 人物性格和行为符合设定
- ✅ 遵循已建立的世界观规则
- ✅ 注重细节的合理性和真实感
- ✅ 开头要有吸引力，结尾要有悬念

【输出格式要求】⚠️
请直接输出章节内容，格式必须如下：

第一章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第一章 标题名称"
- 章节标题要简洁有力，能概括本章核心内容或悬念
- 不要包含任何额外的说明文字、作者话语等"""

                    user_prompt = f"""请创作第一章内容：

【情节大纲】
{plot_outline}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【用户需求】
{requirement}

【目标字数】约3000字

【本章开头方式 - 建议】
建议使用【{selected_opening[0]}】方式开头，快速抓住读者注意力
- 技巧说明：{selected_opening[1]}

❌ 禁止使用：用"XXX醒来/睁开眼睛/阳光照进房间"开头

【本章结尾方式 - 建议】
建议使用【{selected_ending[0]}】结尾，让读者想点下一章
- 技巧说明：{selected_ending[1]}

❌ 禁止使用：总结式内心独白 + 对未来的展望（如"她知道，从这一刻起...")）

请开始创作第一章内容："""

                    from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
                    from app.services.agents.intelligent_truncator import smart_truncate_for_context

                    content_plan_parts = []
                    if stage_context.concept:
                        content_plan_parts.append(f"【故事概念】\n{stage_context.concept}")
                    if plot_outline:
                        content_plan_parts.append(f"【第一章结构大纲】\n{plot_outline}")
                    if requirement:
                        content_plan_parts.append(f"【补充要求】\n{requirement}")
                    content_plan = "\n\n".join(
                        part for part in content_plan_parts if part.strip()
                    ) or plot_outline

                    first_chapter_rag = workflow_context_builder.build_typed_rag_context(
                        project_id,
                        content_plan or requirement or world_setting,
                        fallback_max_content_length=180,
                    )
                    rag_character_context = first_chapter_rag.rag_character_context
                    rag_world_context = first_chapter_rag.rag_world_context
                    if not rag_character_context and characters:
                        rag_character_context = build_character_prompt_context_from_text(
                            characters,
                            detail_limit=560,
                            summary_limit=240,
                        )
                    if not rag_character_context and characters:
                        rag_character_context = smart_truncate_for_context(
                            characters,
                            max_tokens=220,
                            content_type="prompt_context",
                            preserve_ratio=0.9,
                        )
                    if not rag_world_context:
                        rag_world_context = smart_truncate_for_context(
                            world_setting,
                            max_tokens=260,
                            content_type="prompt_context",
                            preserve_ratio=0.9,
                        )

                    real_coord = coordinator.get_real_coordinator(project_id)
                    project_context = getattr(real_coord, "project_context", {}) if real_coord else {}
                    project_genre = (
                        project_context.get("genre")
                        or project_context.get("project_genre")
                        or ""
                    )
                    prompt_builder = ChapterPromptBuilder(genre=project_genre)
                    system_prompt = prompt_builder.build_system_prompt()
                    user_prompt = prompt_builder.build_user_prompt(
                        next_chapter_number=1,
                        chapter_plan=content_plan,
                        previous_ending="",
                        recent_chapter_assets_summary="",
                        rag_character_context=rag_character_context,
                        rag_world_context=rag_world_context,
                        selected_opening=selected_opening,
                        selected_ending=selected_ending,
                    )

                elif stage_enum == StageType.CONCEPT:
                    # 概念开发阶段 - 分三个子阶段流式输出
                    logger.info(f"   🌊 概念开发阶段开始流式输出...")
                    
                    # 1. 故事概念生成
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成故事概念...")

                    real_coord = coordinator.get_real_coordinator(project_id)
                    project_context = getattr(real_coord, "project_context", {}) if real_coord else {}
                    project_title = project_context.get("title") or project_context.get("project_title") or "未命名项目"
                    project_genre = project_context.get("genre") or project_context.get("project_genre") or "通用题材"
                    recent_project_signatures = project_context.get("recent_project_signatures") or ""
                    recent_project_avoidance = project_context.get("recent_project_avoidance") or ""
                    
                    concept_system_prompt = f"""你是一名擅长网文结构设计的\"创意总监\"，需要为一个新项目生成【故事概念】和初步【世界观设定】。

【已知信息】
- 项目题目：{project_title}
- 题材类型：{project_genre}

【强避重约束】
{recent_project_avoidance or "（暂无近期项目避重清单，但仍需主动回避高频修仙模板。）"}
- 除非用户明确要求，否则不要使用“林尘”作为主角名。
- 除非用户明确要求，不要以“宗门杂役 / 杂役弟子 / 废灵根 / 无灵根少年濒死觉醒”作为标准开局。
- 除非用户明确要求，不要使用“吞噬灵根 / 逆修系统 / 反向修炼系统 / 越被羞辱越变强”作为核心机制。
- 除非用户明确要求，不要把世界命名为“九寰界 / 九寰界域”，也不要直接使用“九大仙宗 / 九大仙域 / 上中下三界”作为世界骨架。
- 除非用户明确要求，不要直接复用“飞升骗局 / 高维收割 / 天外监察者 / 养蛊游戏”作为终局真相模板。
- 如果你的方案与近期项目在“主角名、起点身份、核心能力、世界名称、势力骨架、终局真相”中重合达到 3 项及以上，视为不合格，必须先推翻再重想。

{recent_project_signatures}

【总体要求】
1. 先完成\"故事概念\"六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。

——————————
一、请先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：

1. **一句话卖点（Logline）**：
- 用一句极具吸引力的网文式概括，包含主角类型、核心能力/优势、主要对手/系统，以及最具爽感的长期目标或爆点。
- 优先使用“主角行动 + 意外结果”句式，例如：“档案修补员篡改禁城时序，反成帝国唯一合法继承人”，而不是单纯罗列设定。

2. **日志标题（短标题）**：
- 用 4–10 个字给出一个便于读者记忆的项目名，偏网文风格。

3. **概念摘要（80–150字）**：
- 简要交代主角身份、初始困境、长期目标、主要阻力，以及世界观的一个独特钩子。

4. **题材与流派（主题材/子流派）**：
- 主题材例如：玄幻修真 / 反乌托邦科幻 / 历史权谋 / 都市奇能 等；

5. **核心标签（3–6个）**：
- 用 3–6 个标签概括作品的核心气质，例如：#系统流 #无敌流 #热血 #成长 #复仇 #智斗

6. **核心冲突与情感基调**：
- 用 100–200 字说明主角面临的长期核心冲突（如：弱小时被欺压 vs 强大后遭围剿），以及全文的整体情绪氛围（如：前期压抑但充满希望，后期高燃且快节奏）。

二、接着生成【世界观设定】（简略版）
- 用 100–200 字给出最核心的世界观设定，包括世界背景、基本规则、主要势力等。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。"""
                    
                    concept_user_prompt = f"""请为以下项目生成故事概念：

【项目题目】：{project_title}
【题材类型】：{project_genre}
【用户初始想法】：{requirement or "暂无"}"""
                    
                    # 执行故事概念生成的流式调用
                    concept_result = ""
                    async def on_concept_chunk(chunk: str, idx: int):
                        nonlocal concept_result
                        concept_result += chunk
                        # 发送到前端的conceptContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'concept'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=concept_user_prompt,
                        system_prompt=concept_system_prompt,
                        on_chunk=on_concept_chunk,
                        temperature=0.9,
                        task_type="concept",
                    )
                    
                    # 2. 世界观设定生成
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成世界观设定...")
                    
                    world_system_prompt = """你是一名\"世界观架构师\"，需要基于已有的故事概念，生成详细的世界观设定。

【要求】
1. 基于故事概念中的设定线索进行扩展
2. 保持与故事概念的一致性
3. 输出详细的世界观设定，包括世界背景、基本规则、主要势力等"""
                    
                    world_user_prompt = f"""请基于以下故事概念生成世界观设定：

{concept_result}"""
                    
                    # 执行世界观设定生成的流式调用
                    world_result = ""
                    async def on_world_chunk(chunk: str, idx: int):
                        nonlocal world_result
                        world_result += chunk
                        # 发送到前端的worldContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'world'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=world_user_prompt,
                        system_prompt=world_system_prompt,
                        on_chunk=on_world_chunk,
                        temperature=0.7,
                        task_type="worldview",
                    )
                    
                    # 3. 人物设定生成
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成人物设定...")
                    
                    character_system_prompt, character_user_prompt = _build_concept_stage_character_prompts(
                        project_genre=project_genre,
                        requirement=requirement or "",
                        concept_text=concept_result,
                        world_setting_text=world_result,
                    )
                    
                    # 执行人物设定生成的流式调用
                    character_result = ""
                    async def on_character_chunk(chunk: str, idx: int):
                        nonlocal character_result
                        character_result += chunk
                        # 发送到前端的characterContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'character'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=character_user_prompt,
                        system_prompt=character_system_prompt,
                        on_chunk=on_character_chunk,
                        temperature=0.7,
                        task_type="character",
                    )
                    
                    # 组合结果
                    result_str = f"{concept_result}\n\n{world_result}\n\n{character_result}"
                    logger.info(f"   ✅ 概念开发阶段流式输出完成，总长度: {len(result_str)} 字符")
                    
                    # 🔧 将概念阶段的三个部分数据存储到output_data，用于后续保存
                    output_data = {
                        "concept": concept_result,
                        "world_setting": world_result,
                        "characters": character_result
                    }

                elif stage_enum == StageType.STRUCTURE:
                    # 结构设计阶段 - 流式输出大纲
                    logger.info(f"   🌊 结构设计阶段开始流式输出...")
                    
                    # 获取概念开发阶段的成果
                    concept_data = stage_context.concept
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成情节大纲...")
                    
                    structure_system_prompt = """你是一名"情节架构师"，需要基于故事概念、世界观和人物设定，设计详细的情节大纲。

【要求】
1. 基于已有的概念、世界观和人物设定进行大纲设计
2. 保持与前期设定的一致性
3. 设计清晰的情节线索和冲突发展
4. 为第一章提供具体的情节指导
5. 输出详细的情节大纲，包括主线情节、支线情节、关键节点等

【输出格式】
请按以下结构输出情节大纲：

## 一、主线情节
- 描述主要情节线索和发展脉络

## 二、第一章大纲
- 章节标题建议
- 开场设定
- 主要情节
- 关键冲突
- 章节结尾

## 三、后续章节规划（可选）
- 概述后续几章的大致发展方向"""
                    
                    structure_user_prompt = f"""请基于以下设定生成情节大纲：

【故事概念】
{concept_data}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【用户需求】
{requirement}"""
                    
                    # 执行结构设计的流式调用
                    world_setting = _build_project_world_setting_context(
                        project_id,
                        world_setting,
                        db,
                    )
                    structure_result = ""
                    async def on_structure_chunk(chunk: str, idx: int):
                        nonlocal structure_result
                        structure_result += chunk
                        # 发送到前端
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=structure_user_prompt,
                        system_prompt=structure_system_prompt,
                        on_chunk=on_structure_chunk,
                        temperature=0.7,
                        task_type="structure_plot",
                    )
                    
                    result_str = structure_result
                    logger.info(f"   ✅ 结构设计阶段流式输出完成，总长度: {len(result_str)} 字符")
                    
                    # 🔧 将结构设计结果存储到output_data，用于后续保存
                    output_data = {
                        "plot_outline": structure_result
                    }

                elif stage_enum == StageType.REVIEW:
                    # 质量评审阶段
                    chapter_draft = stage_context.chapter_draft

                    # 🆕 网文6维度评审体系（从头创作版本）
                    system_prompt = """你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对第一章内容进行评审。

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点或为后续爽点做了铺垫？
- 第一章作为开篇，是否成功吸引读者？

### 2. 节奏把控（权重20%）
- 信息密度是否适中（不过载也不空洞）？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？（是否避免了\"醒来/阳光照进\"的套路开头）
- 章节结尾是否有悬念/钩子？
- 读者是否有\"想点下一章\"的冲动？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 读者能否代入主角的处境和情感？
- 世界观建立是否自然、不突兀？

### 5. 文笔流畅度（权重10%）
- 是否有明显的AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 人物设定是否与提供的设定一致？
- 世界观规则是否与提供的设定一致？"""

                    user_prompt = f"""请评审以下第一章内容：

【章节内容】
{chapter_draft}

---

【输出格式】
请使用以下格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果 ⭐⭐⭐
- 评价：...
- 问题：...

### 2. 节奏把控 ⭐⭐⭐
- 评价：...
- 问题：...

### 3. 钩子效果 ⭐⭐⭐
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感 ⭐⭐⭐
- 评价：...
- 问题：...

### 5. 文笔流畅度 ⭐⭐⭐
- 评价：...
- 问题：...

### 6. 内容一致性 ⭐⭐⭐
- 评价：...
- 问题：...

### 🔧 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】...

### ✨ 亮点
- ..."""

                elif stage_enum == StageType.ITERATION:
                    # 迭代优化阶段
                    chapter_draft = stage_context.chapter_draft
                    review_report = stage_context.review_report

                    # 🆕 增强版迭代优化提示词
                    system_prompt = """你是一位资深的网络小说编辑。请根据评审意见对第一章内容进行优化修改。

优化要求：
1. 保持原有故事框架和情节发展
2. 改进语言表达，增强网文风格
3. 增强细节描写，让场景更有画面感
4. 优化对话内容，使其更自然、更符合人物性格
5. 提升整体可读性和代入感
6. 针对评审中标注【必改】的问题必须修改
7. 标注【建议】的问题尽量修改

【输出格式要求】⚠️
请直接输出优化后的章节内容，格式必须如下：

第一章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第一章 标题名称"
- 不要包含任何优化说明、修改说明等额外内容
- 只输出优化后的纯净章节内容"""

                    user_prompt = f"""请根据评审意见优化以下第一章：

【原始章节】
{chapter_draft}

【评审意见】
{review_report}

请直接输出优化后的完整章节内容（第一行为章节标题）："""
                else:
                    # 其他阶段不使用流式输出，回退到原有逻辑
                    raise ValueError(f"阶段 {stage_enum.value} 不支持流式输出")

                # 🔥 执行流式 LLM 调用
                logger.info(f"   🌊 开始流式 LLM 调用...")
                # 🆕 按阶段选择模型，避免使用默认deepseek-chat
                stage_model = None
                stage_task_type = None
                stage_model_override = None
                try:
                    from app.core.config import settings
                    default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3-max")
                except Exception:
                    default_content_model = "qwen3-max"
                
                if stage_enum == StageType.CONTENT:
                    stage_task_type = "chapter"
                    stage_model_override = default_content_model
                elif stage_enum == StageType.REVIEW:
                    stage_task_type = "review"
                elif stage_enum == StageType.ITERATION:
                    stage_task_type = "review"
                stage_model = (
                    resolve_model_for_task(stage_task_type, stage_model_override)
                    if stage_task_type
                    else None
                )
                
                # 对于非CONCEPT阶段，执行流式调用
                if stage_enum in {StageType.CONTENT, StageType.REVIEW, StageType.ITERATION}:
                    result_str = await streaming_service.generate_chapter_streaming(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        on_chunk=on_stream_chunk,
                        temperature=0.7,
                        model=stage_model_override,
                        task_type=stage_task_type,
                    )
                    logger.info(f"   ✅ 流式 LLM 调用完成，生成 {len(result_str)} 字符")

                # 🆕 迭代优化阶段：清理输出内容 + 摘要压缩保护
                if stage_enum == StageType.ITERATION and result_str:
                    # 清理输出内容，移除额外的评审话语
                    def clean_final_output(content: str) -> str:
                        if not content:
                            return content
                        lines = content.split('\n')
                        cleaned_lines = []
                        skip_section = False
                        for line in lines:
                            line_lower = line.lower().strip()
                            if any(keyword in line_lower for keyword in [
                                '优化说明', '修改说明', '评审', '改进建议', '优化要点',
                                '以下是优化后', '根据评审意见', '主要修改', '优化内容'
                            ]):
                                skip_section = True
                                continue
                            if skip_section and line.strip() == '':
                                skip_section = False
                                continue
                            if not skip_section:
                                cleaned_lines.append(line)
                        return '\n'.join(cleaned_lines).strip()

                    result_str = clean_final_output(result_str)

                    # 安全保护：如果优化后字数远小于原稿，回退为原始内容
                    original_len = len(chapter_draft or "")
                    optimized_len = len(result_str or "")
                    if original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
                        logger.warning(
                            f"   ⚠️ 优化后长度({optimized_len}) 远小于原稿({original_len})，保留原始内容"
                        )
                        result_str = chapter_draft

            except Exception as streaming_error:
                logger.warning(f"   ⚠️  流式 LLM 调用失败，回退到原有逻辑: {streaming_error}")
                use_streaming_llm = False

        # 如果流式调用失败或不可用，回退到原有逻辑
        if not use_streaming_llm or not result_str:
            logger.info(f"   📝 使用原有逻辑执行阶段...")
            stage_output = await coordinator.execute_stage(
                stage_enum,
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "requirement": requirement,
                    "enable_streaming": False,
                },
            )

            # 提取结果内容
            output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
            if stage_enum == StageType.ITERATION:
                result_str = output_data.get("revised_content", "") or output_data.get("final_review", "")
            elif stage_enum == StageType.CONTENT:
                result_str = output_data.get("content", "") or output_data.get("chapters", "")
            elif stage_enum == StageType.REVIEW:
                result_str = output_data.get("review", "")
            # 🔧 修复：CONCEPT 和 STRUCTURE 阶段需要提取正确的字段
            elif stage_enum == StageType.CONCEPT:
                result_str = output_data.get("concept", "") or str(output_data) if output_data else ""
                logger.info(f"   🔍 CONCEPT 阶段提取结果: {len(result_str)} 字符")
            elif stage_enum == StageType.STRUCTURE:
                result_str = output_data.get("plot_outline", "") or output_data.get("structure", "") or str(output_data) if output_data else ""
                logger.info(f"   🔍 STRUCTURE 阶段提取结果: {len(result_str)} 字符")
            else:
                result_str = str(stage_output.output) if stage_output.output else ""

        # 🌊 发送流式输出结束通知
        await ws_manager.send_stream_end(
            project_id=project_id,
            stage=stage_enum.value,
            total_chars=len(result_str) if result_str else 0
        )

        # 🔧 确保 output_data 存在（防止未定义错误）
        if 'output_data' not in locals():
            # 🆕 如果是流式模式，需要从 result_str 中提取结构化数据
            if stage_enum == StageType.CONCEPT and result_str:
                # 尝试从 result_str 中提取三个部分：故事概念、世界观、人物
                logger.info(f"   🔍 流式模式，开始解析 CONCEPT 结果...")
                import re
                
                # 提取世界观部分
                world_pattern = r'(?:###?\s*二、世界观设定|###?\s*2\.\s*世界观设定|###\s*世界观设定)(.*?)(?=###?\s*三、人物设定|###?\s*3\.\s*人物设定|$)'
                world_match = re.search(world_pattern, result_str, re.DOTALL | re.IGNORECASE)
                world_setting = world_match.group(1).strip() if world_match else ""
                
                # 提取人物部分
                char_pattern = r'(?:###?\s*三、人物设定|###?\s*3\.\s*人物设定|###\s*人物设定)(.*?)$'
                char_match = re.search(char_pattern, result_str, re.DOTALL | re.IGNORECASE)
                characters = char_match.group(1).strip() if char_match else ""
                
                # 故事概念是从开头到世界观之前的部分
                concept_pattern = r'^(.*?)(?=###?\s*二、世界观设定|###?\s*2\.\s*世界观设定|###\s*世界观设定)'
                concept_match = re.search(concept_pattern, result_str, re.DOTALL | re.IGNORECASE)
                concept = concept_match.group(1).strip() if concept_match else result_str
                
                logger.info(f"   🔍 提取结果: concept={len(concept)}字, world={len(world_setting)}字, characters={len(characters)}字")
                
                output_data = {
                    "concept": concept,
                    "worldview": world_setting,
                    "world_setting": world_setting,
                    "characters": characters
                }
            else:
                output_data = {}

        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, result = :result, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        db.execute(update_query, {
            "status": "completed",
            "result": result_str,
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 流式任务完成: {task_id}")

        # 保存阶段输出到 project_settings
        logger.debug(f"\n{'='*50}")
        logger.debug(f"🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        logger.debug(f"{'='*50}\n")
        logger.info(f"   🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        try:
            # 🔧 添加 CONCEPT 阶段的保存（同时保存 concept, world_setting, characters）
            if stage_enum == StageType.CONCEPT:
                logger.info(f"   🔍 匹配到 CONCEPT 阶段，开始保存...")
                # 🔧 直接使用已定义的 output_data 变量
                concept_data = output_data.get("concept", result_str) if isinstance(output_data, dict) and output_data else result_str
                worldview_data = output_data.get("worldview", "") or output_data.get("world_setting", "") if isinstance(output_data, dict) and output_data else ""
                characters_data = output_data.get("characters", "") if isinstance(output_data, dict) and output_data else ""
                characters_data = _normalize_concept_stage_characters_for_storage(
                    project_id,
                    characters_data,
                    concept_text=str(concept_data or ""),
                    world_setting_text=str(worldview_data or ""),
                )
                
                logger.info(f"   🔍 CONCEPT 数据: concept={len(str(concept_data))}字, worldview={len(str(worldview_data))}字, characters={len(str(characters_data))}字")

                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    concept=json.dumps(concept_data, ensure_ascii=False) if concept_data else None,
                    world_setting=json.dumps(worldview_data, ensure_ascii=False) if worldview_data else None,
                    characters=json.dumps(characters_data, ensure_ascii=False) if characters_data else None,
                    stage_one_status="completed",
                )
                logger.info("   🔍 UPDATE 执行完成，字段已通过统一 helper 写入")
                logger.info(f"   💾 已保存概念/世界观/人物到 project_settings（流式模式）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title（流式模式）
                if concept_data and isinstance(concept_data, str):
                    try:
                        _sync_project_title_from_concept(
                            db,
                            project_id,
                            concept_data,
                            mode_label="流式模式",
                        )
                    except Exception as e:
                        logger.warning(f"   ⚠️  提取日志标题失败（流式模式）: {e}")
            # 🔧 添加 STRUCTURE 阶段的保存
            elif stage_enum == StageType.STRUCTURE:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    plot_outline=json.dumps(result_str, ensure_ascii=False),
                    stage_two_status="completed",
                )
                logger.info(f"   💾 已保存结构大纲到 project_settings（流式模式）")
            elif stage_enum == StageType.CONTENT:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    chapter_draft=json.dumps(result_str, ensure_ascii=False),
                    stage_three_status="completed",
                )
            elif stage_enum == StageType.REVIEW:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    review_report=json.dumps(result_str, ensure_ascii=False),
                    stage_four_status="completed",
                )
            elif stage_enum == StageType.ITERATION:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    final_version=json.dumps(result_str, ensure_ascii=False),
                    stage_five_status="completed",
                )
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")
            # 🆕 添加详细堆栈跟踪
            import traceback
            logger.error(f"   🔍 堆栈跟踪:\n{traceback.format_exc()}")
            # 🆕 打印关键变量
            logger.error(f"   🔍 stage_enum={stage_enum}, project_id={project_id}, result_str_len={len(result_str) if result_str else 0}")
            logger.error(f"   🔍 output_data={type(output_data)}, output_data_keys={output_data.keys() if isinstance(output_data, dict) else 'not dict'}")

        # 推送任务完成通知
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={"output": result_str}
        )

        # 🆕 推送 Agent 完成状态（流式模式）
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 完成状态（流式模式）")

        # 推送阶段完成状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='completed',
            output=result_str,
            progress=100
        )

        # 🆕 保存记忆到数据库（统一存储方案 - 流式模式）
        try:
            from app.models.memory import Memory

            # 🆕 消息数量上限
            MAX_MESSAGES = 50

            # 查找或创建记忆记录
            memory = db.query(Memory).filter(
                Memory.project_id == project_id
            ).order_by(Memory.updated_at.desc()).first()

            # 构建新的消息记录
            new_message = {
                "role": "assistant",
                "content": result_str[:2000] if result_str else "",  # 限制长度
                "stage": stage_enum.value,
                "timestamp": utc_now().isoformat()
            }

            if memory:
                # 更新现有记忆
                messages = memory.messages or []
                messages.append(new_message)

                # 🆕 限制消息数量（保留最近 MAX_MESSAGES 条）
                if len(messages) > MAX_MESSAGES:
                    messages = messages[-MAX_MESSAGES:]

                memory.messages = messages
                memory.current_scene = stage_enum.value
                db.add(memory)
            else:
                # 创建新记忆
                project = db.query(Project).filter(Project.id == project_id).first()
                if project:
                    memory = Memory(
                        project_id=project_id,
                        user_id=project.user_id,
                        messages=[new_message],
                        current_scene=stage_enum.value
                    )
                    db.add(memory)

            db.commit()
            logger.info(f"   💾 已保存阶段记忆到数据库（流式模式）: {stage_enum.value}")
        except Exception as mem_error:
            logger.error(f"   ⚠️  保存记忆失败（流式模式）: {mem_error}")
            # 不影响主流程

    except Exception as e:
        logger.error(f"❌ 流式后台任务失败: {task_id}, 错误: {str(e)}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.warning(f"⚠️  流式后台任务失败后回滚事务失败: {rollback_error}")

        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status, error = :error, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        db.execute(update_query, {
            "status": "failed",
            "error": str(e),
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        # 推送任务失败通知
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )

        # 推送错误状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='error',
            progress=0
        )
    finally:
        # 🔧 关键修复：关闭独立创建的 db session
        db.close()
        logger.info(f"   📝 db session 已关闭")


@router.post("/regenerate-stage")
async def regenerate_stage(
    request: RegenerateStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    重新生成阶段

    请求体:
    {
        "project_id": 1,
        "stage": "concept"
    }
    """
    # 先提取参数，确保在异常处理中可访问
    project_id = request.project_id
    stage = request.stage
    
    try:
        if not project_id or not stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or stage",
            )

        # 重新执行阶段
        stage_enum = StageType(stage)
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {"project_id": project_id, "user_id": current_user.id},
        )

        return {
            "status": "success",
            "stage": stage,
            "output": stage_output.output,
            "agents": [
                coordinator.get_agents(project_id)[agent_id]
                for agent_id in stage_output.agents_involved
            ],
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/status/{project_id}")
async def get_workflow_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取工作流程状态"""
    try:
        # ✅ 验证项目所有权
        from app.models.project import Project
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == current_user.id
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or access denied"
            )

        status_data = await coordinator.get_workflow_status(project_id)
        return {
            "status": "success",
            "project_id": project_id,
            "workflow": status_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{project_id}/stage/{stage}/content")
async def get_stage_content(
    project_id: int,
    stage: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取阶段内容

    响应:
    {
        "content": "内容文本",
        "stage": "iteration"
    }
    """
    try:
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )

        # 2. 从统一工作流上下文读取内容
        workflow_context_builder = WorkflowContextBuilder(db)
        if not workflow_context_builder.get_stage_field_name(stage):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        content = workflow_context_builder.read_stage_content(
            project_id,
            stage,
            pretty_json=True,
        )
        return {
            "content": content,
            "stage": stage
        }

        # 🔧 修复JSON解码错误：如果内容是JSON字符串，先解析
        import json
        try:
            if content and (content.startswith('{') or content.startswith('[') or content.startswith('"')):
                parsed_content = json.loads(content)
                # 如果是字符串，直接使用；如果是对象/数组，转回字符串
                if isinstance(parsed_content, str):
                    content = parsed_content
                elif isinstance(parsed_content, (dict, list)):
                    # 如果是对象或数组，转回格式化的字符串
                    content = json.dumps(parsed_content, ensure_ascii=False, indent=2)
                else:
                    content = str(parsed_content)
        except json.JSONDecodeError:
            # 如枟解析失败，直接使用原内容
            pass

        return {
            "content": content,
            "stage": stage
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.put("/{project_id}/stage/{stage}/content")
async def save_stage_content(
    project_id: int,
    stage: str,
    request: SaveStageContentRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    保存阶段内容并可选继续工作流

    请求体:
    {
        "content": "内容文本",
        "continue_workflow": true
    }

    响应:
    {
        "success": true,
        "message": "内容已保存",
        "stage": "content",
        "task_id": "uuid-string",  // 如果continue_workflow为true
        "continue_workflow": true,
        "deleted_chapter": {...}  // 如果删除了已保存章节
    }
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    
    try:
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )

        # 🆕 2. 智能章节覆盖：如果是内容创作阶段或质量评审阶段
        deleted_chapter = None
        deleted_chapters_count = 0

        # 质量评审阶段：用户修改评审报告后继续，需要删除所有现有章节重新生成
        if stage == 'review' and request.continue_workflow:
            logger.info(f"🔍 检测到质量评审阶段继续工作流，检查是否需要清理现有章节...")

            from sqlalchemy import text
            # 获取当前已保存的所有章节
            chapters_query = text("""
                SELECT id, chapter_number, title, word_count
                FROM chapters
                WHERE project_id = :project_id
                ORDER BY chapter_number
            """)
            chapters_result = db.execute(chapters_query, {"project_id": project_id}).fetchall()
            chapters = [{"id": r[0], "chapter_number": r[1], "title": r[2], "word_count": r[3]} for r in chapters_result]

            if chapters:
                logger.info(f"   📊 发现 {len(chapters)} 个已保存章节，准备清理...")

                # 清理记忆管理中的章节引用
                try:
                    from app.models.memory import Memory
                    db.query(Memory).filter(
                        Memory.project_id == project_id
                    ).update({Memory.current_chapter: None}, synchronize_session=False)
                    logger.info(f"      ✅ 已清理记忆管理中的章节引用")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命错误）: {e}")

                # 删除所有章节记录
                delete_chapters_query = text("""
                    DELETE FROM chapters
                    WHERE project_id = :project_id
                """)
                db.execute(delete_chapters_query, {"project_id": project_id})
                db.commit()

                deleted_chapters_count = len(chapters)
                logger.info(f"   ✅ 已删除 {deleted_chapters_count} 个章节，准备重新生成")
            else:
                logger.info(f"   ✅ 未发现已保存章节，无需清理")

        # 内容创作阶段：智能覆盖最后一章
        elif stage == 'content':
            logger.info(f"🔍 检测到内容创作阶段，检查是否需要更新现有章节...")
            
            # 获取当前已保存的章节列表
            from sqlalchemy import text
            # 使用原生SQL替代ORM查询
            chapters_query = text("""
                SELECT id, chapter_number, title, word_count 
                FROM chapters 
                WHERE project_id = :project_id 
                ORDER BY chapter_number DESC
            """)
            chapters_result = db.execute(chapters_query, {"project_id": project_id}).fetchall()
            chapters = [{"id": r[0], "chapter_number": r[1], "title": r[2], "word_count": r[3]} for r in chapters_result]
            
            # 目标章节号应该是当前最大章节号（用户想更新这一章）
            if chapters:
                # 如果已有章节，检查最后一章（用户可能想更新）
                target_chapter_number = chapters[0]["chapter_number"]
            else:
                # 如果没有章节，说明这是第一章
                target_chapter_number = 1
            
            logger.info(f"   📊 已有章节数: {len(chapters)}，目标章节编号: {target_chapter_number}")
            
            # 检查是否已存在目标章节
            # 使用原生SQL替代ORM查询
            existing_chapter_query = text("""
                SELECT id, chapter_number, title, word_count 
                FROM chapters 
                WHERE project_id = :project_id AND chapter_number = :chapter_number
            """)
            existing_chapter_result = db.execute(existing_chapter_query, {
                "project_id": project_id,
                "chapter_number": target_chapter_number
            }).fetchone()
            
            if existing_chapter_result:
                existing_chapter = {
                    "id": existing_chapter_result[0],
                    "chapter_number": existing_chapter_result[1],
                    "title": existing_chapter_result[2],
                    "word_count": existing_chapter_result[3]
                }
                
                logger.info(f"   ⚠️  发现已存在第{target_chapter_number}章（ID={existing_chapter['id']}），准备更新...")
                
                # 更新现有章节信息
                deleted_chapter_info = {
                    "id": existing_chapter["id"],
                    "chapter_number": existing_chapter["chapter_number"],
                    "title": existing_chapter["title"],
                    "word_count": existing_chapter["word_count"]
                }
                
                # 🧹 1) 清理 ChromaDB 向量数据
                try:
                    logger.info(f"   🗂️  清理ChromaDB中的章节向量...")
                    from app.services.agents.knowledge_base import NovelKnowledgeBase
                    kb = NovelKnowledgeBase()
                    deleted_count = kb.delete_chapter(
                        chapter_number=target_chapter_number,
                        project_id=project_id
                    )
                    if deleted_count > 0:
                        logger.info(f"      ✅ 已删除 {deleted_count} 个向量文档")
                except Exception as e:
                    logger.warning(f"   ⚠️  ChromaDB清理失败（非致命错误）: {e}")

                # 🧹 2) 清理记忆管理中的章节引用
                try:
                    logger.info(f"   🧠 清理记忆管理中的章节引用...")
                    
                    from app.models.memory import Memory
                    db.query(Memory).filter(
                        (Memory.project_id == project_id) &
                        (Memory.current_chapter == target_chapter_number)
                    ).update({Memory.current_chapter: None})
                    
                    logger.info(f"      ✅ 已清理记忆管理中的章节引用")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命错误）: {e}")
                
                # 🗑️ 删除章节记录（会自动级联删除评审记录）
                logger.info(f"   🗑️  删除旧章节记录...")
                # 使用原生SQL删除章节
                delete_chapter_query = text("""
                    DELETE FROM chapters 
                    WHERE id = :chapter_id
                """)
                db.execute(delete_chapter_query, {"chapter_id": existing_chapter["id"]})
                db.commit()
                
                deleted_chapter = deleted_chapter_info
                logger.info(f"   ✅ 已删除第{target_chapter_number}章，准备更新为新内容")
            else:
                logger.info(f"   ✅ 未发现重复章节，将创建新章节")

        # 3. 保存内容到 project_settings 表
        workflow_context_builder = WorkflowContextBuilder(db)
        if not workflow_context_builder.get_stage_field_name(stage):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        workflow_context_builder.write_stage_content(project_id, stage, request.content)

        # 4. 如果continue_workflow为true，创建任务记录并启动后台任务
        task_id = None
        if request.continue_workflow:
            task_id = str(uuid.uuid4())

            # 创建任务记录到generation_history表
            insert_query = text("""
                INSERT INTO generation_history
                (project_id, task_type, task_id, status, created_at)
                VALUES (:project_id, :task_type, :task_id, :status, :created_at)
            """)

            db.execute(insert_query, {
                "project_id": project_id,
                "task_type": f"workflow_stage_{stage}",
                "task_id": task_id,
                "status": "running",
                "created_at": utc_now().isoformat()
            })
            db.commit()

            # 🔥 关键修复：启动后台任务执行下一阶段
            logger.info(f"🚀 启动后台任务执行下一阶段，task_id={task_id}")
            
            # 确定下一阶段
            stage_sequence = ['concept', 'structure', 'content', 'review', 'iteration']
            try:
                current_index = stage_sequence.index(stage)
                if current_index < len(stage_sequence) - 1:
                    next_stage_name = stage_sequence[current_index + 1]
                    next_stage_enum = StageType(next_stage_name)
                    
                    logger.info(f"   📍 下一阶段: {next_stage_name}")
                    
                    # 🆕 根据阶段判断是否启用流式输出
                    streaming_stages = [StageType.CONCEPT, StageType.STRUCTURE, StageType.CONTENT, StageType.REVIEW, StageType.ITERATION]
                    streaming_enabled = next_stage_enum in streaming_stages
                    
                    # 启动后台任务
                    if streaming_enabled:
                        asyncio.create_task(
                            _run_execute_stage_with_streaming_serialized(
                                task_id, project_id, next_stage_enum, current_user.id, db
                            )
                        )
                        logger.info(f"   🌊 流式后台任务已启动: {next_stage_name}")
                    else:
                        asyncio.create_task(
                            _run_execute_stage_background_serialized(
                                task_id, project_id, next_stage_enum, current_user.id, db, False, None, None
                            )
                        )
                        logger.info(f"   🚀 后台任务已启动: {next_stage_name}")
                else:
                    logger.info(f"   ✅ 已完成所有阶段，无需继续")
            except ValueError:
                logger.error(f"   ❌ 无效的阶段名称: {stage}")

        response = {
            "success": True,
            "message": "内容已保存",
            "stage": stage,
            "task_id": task_id,
            "continue_workflow": request.continue_workflow
        }

        # 🆕 如果删除了章节，包含在响应中
        if deleted_chapter:
            response["deleted_chapter"] = deleted_chapter
            response["message"] = f"已删除第{deleted_chapter['chapter_number']}章并保存新内容"

        # 🆕 如果是评审阶段删除了多个章节
        if deleted_chapters_count > 0:
            response["deleted_chapters_count"] = deleted_chapters_count
            response["message"] = f"已删除 {deleted_chapters_count} 个章节，准备重新生成"

        return response

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取任务状态

    响应:
    {
        "task_id": "uuid-string",
        "status": "running|completed|failed",
        "progress": 0-100,
        "result": "任务结果",
        "error": "错误信息（如果有）"
    }
    """
    try:
        from sqlalchemy import text

        # ✅ 查询任务状态并验证项目所有权
        query = text("""
            SELECT gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
            FROM generation_history gh
            INNER JOIN projects p ON gh.project_id = p.id
            WHERE gh.task_id = :task_id AND p.user_id = :user_id
        """)

        result = db.execute(query, {
            "task_id": task_id,
            "user_id": current_user.id
        }).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found or access denied"
            )

        # 计算进度
        progress = 0
        if result[1] == "completed":
            progress = 100
        elif result[1] == "running":
            progress = 50
        elif result[1] == "failed":
            progress = 0

        return {
            "task_id": result[0],
            "status": result[1],
            "progress": progress,
            "result": result[2],
            "error": result[3],
            "created_at": result[4],
            "completed_at": result[5]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/project/{project_id}/running-tasks")
async def get_running_tasks(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 获取项目的正在运行的任务

    用于页面重新加载时恢复工作流状态

    🔧 新增：自动检测并标记超时任务（超过30分钟的任务自动标记为 timeout）

    响应:
    {
        "running_tasks": [
            {
                "task_id": "uuid",
                "task_type": "workflow_stage_concept",
                "status": "running",
                "created_at": "2024-01-01T00:00:00"
            }
        ],
        "timeout_tasks": [...]  // 被标记为超时的任务
    }
    """
    import logging
    from sqlalchemy import text
    logger = logging.getLogger("uvicorn.error")

    # 🔧 超时阈值：30分钟
    DEFAULT_TASK_TIMEOUT_MINUTES = 30
    EXPAND_STORY_TASK_TIMEOUT_MINUTES = 180

    def resolve_task_timeout_minutes(task_type: Any) -> int:
        normalized_task_type = str(task_type or "").strip().lower()
        if normalized_task_type == "expand_story":
            return EXPAND_STORY_TASK_TIMEOUT_MINUTES
        return DEFAULT_TASK_TIMEOUT_MINUTES

    try:
        logger.info(f"🔍 查询项目 {project_id} 的正在运行任务...")

        # 🆕 首先检查 project_settings 中的 stage 状态
        # 如果所有 stage 都已完成，则将 running 任务标记为 completed（状态不一致修复）
        stage_result = None
        try:
            stage_statuses = WorkflowContextBuilder(db).load_stage_status_snapshot(project_id)
            stage_result = tuple(stage_statuses.values())
        except Exception as exc:
            err_text = str(exc)
            if "project_settings" in err_text and "does not exist" in err_text:
                logger.warning("   ⚠️ project_settings 表不存在，跳过 stage 状态检查")
            else:
                raise

        all_stages_completed = False
        if stage_result:
            statuses = [stage_result[i] for i in range(5)]
            all_stages_completed = all(s == 'completed' for s in statuses if s)
            logger.debug(f"   Stage 状态: {statuses}, 全部完成: {all_stages_completed}")

        # 查询status='running'的任务
        query = text("""
            SELECT task_id, task_type, status, created_at
            FROM generation_history
            WHERE project_id = :project_id AND status = 'running'
            ORDER BY created_at DESC
        """)

        results = db.execute(query, {"project_id": project_id}).fetchall()

        running_tasks = []
        timeout_tasks = []
        stale_tasks = []  # 🆕 已过时的任务（stage 已完成但任务状态仍为 running）
        now = utc_now()

        for row in results:
            task_id = row[0]
            task_type = row[1]
            status = row[2]
            created_at_str = row[3]
            task_timeout_minutes = resolve_task_timeout_minutes(task_type)

            # 解析创建时间
            created_at = parse_datetime_utc(created_at_str, default=now) or now

            # 🔧 检测超时：如果任务运行超过30分钟，标记为超时
            task_age_minutes = max(0.0, (now - created_at).total_seconds() / 60)

            # 🆕 优先检查：如果所有 stage 都已完成，将 running 任务标记为 completed（状态不一致修复）
            if all_stages_completed:
                logger.warning(f"🔄 检测到过时任务: {task_id}（所有阶段已完成，但任务仍为 running）")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'completed',
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                stale_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "completed",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1),
                    "reason": "所有阶段已完成，自动同步任务状态"
                })

                logger.info(f"   ✅ 已将过时任务 {task_id} 标记为 completed")

            elif task_age_minutes > task_timeout_minutes:
                # 标记为超时
                logger.warning(f"⏰ 检测到超时任务: {task_id}, 运行时间: {task_age_minutes:.1f}分钟")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'timeout',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "error": f"任务超时（运行超过{task_timeout_minutes}分钟）",
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                timeout_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "timeout",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1)
                })

                logger.info(f"   ✅ 已将任务 {task_id} 标记为超时")
            else:
                running_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": status,
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1)
                })

        logger.info(f"   ✅ 找到 {len(running_tasks)} 个正在运行的任务, {len(timeout_tasks)} 个超时任务, {len(stale_tasks)} 个已同步的过时任务")

        return {
            "running_tasks": running_tasks,
            "timeout_tasks": timeout_tasks,
            "stale_tasks": stale_tasks  # 🆕 已同步的过时任务
        }

    except Exception as e:
        logger.error(f"❌ 查询运行中任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{project_id}/all-stages-content")
async def get_all_stages_content(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量获取所有阶段内容（性能优化）

    响应:
    {
        "project_id": 1,
        "stages": {
            "concept": "故事概念内容...",
            "world_setting": "世界观设定...",
            "characters": "人物设定...",
            "plot_outline": "情节大纲...",
            "chapter_draft": "章节初稿...",
            "review_report": "评审报告...",
            "final_version": "最终版本..."
        }
    }
    """
    try:
        from sqlalchemy import text

        # 验证项目存在且属于用户
        query = text("""
            SELECT id FROM projects 
            WHERE id = :project_id AND user_id = :user_id
        """)
        result = db.execute(query, {"project_id": project_id, "user_id": current_user.id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )

        workflow_context_builder = WorkflowContextBuilder(db)
        response = {
            "project_id": project_id,
            "stages": workflow_context_builder.load_stage_contents_snapshot(
                project_id,
                pretty_json=True,
            ),
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{project_id}/stage-status")
async def get_stage_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有阶段状态

    响应:
    {
        "project_id": 1,
        "stage_one_status": "pending",
        "stage_two_status": "completed",
        ...
    }
    """
    try:
        from sqlalchemy import text

        # 验证项目存在且属于用户
        query = text("""
            SELECT id FROM projects 
            WHERE id = :project_id AND user_id = :user_id
        """)
        result = db.execute(query, {"project_id": project_id, "user_id": current_user.id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )

        workflow_context_builder = WorkflowContextBuilder(db)
        response = {
            "project_id": project_id,
            **workflow_context_builder.load_stage_status_snapshot(project_id),
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )





@router.post("/{project_id}/generate-next-chapter")
async def generate_next_chapter(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    生成下一章（异步模式）

    立即返回 task_id，后台执行四个步骤：
    1. 章节规划（0-25%）- 不保存，仅内存传递
    2. 内容创作（25-50%）- 保存到 chapter_draft
    3. 质量评审（50-75%）- 保存到 review_report
    4. 迭代优化（75-100%）- 保存到 final_version + chapters 表

    响应:
    {
        "task_id": "uuid-string",
        "status": "running",
        "message": "已开始生成第X章",
        "next_chapter_number": X
    }
    """
    import asyncio
    from sqlalchemy import text

    logger = logging.getLogger("uvicorn.error")

    try:
        logger.info(f"📍 开始生成下一章（异步模式），项目ID: {project_id}")
        workflow_context_builder = WorkflowContextBuilder(db)
        
        # 1. 验证项目存在且属于用户
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )
        
        logger.info(f"   ✓ 项目验证通过: {project.title}")
        
        # 2. 获取项目设定
        settings_context = workflow_context_builder.load_stage_text_context(project_id)
        
        if not any(
            [
                settings_context.concept,
                settings_context.world_setting,
                settings_context.characters,
                settings_context.plot_outline,
            ]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目设定不存在，请先完成工作流程初始化"
            )
        
        concept = settings_context.concept
        world_setting = settings_context.world_setting
        characters = settings_context.characters
        plot_outline = settings_context.plot_outline
        logger.info(f"   ✓ 项目设定已加载")
        
        # 3. 获取已生成章节
        query = text("""
            SELECT id, chapter_number, title, content, summary
            FROM chapters
            WHERE project_id = :project_id
            ORDER BY chapter_number ASC
        """)
        chapters_result = db.execute(query, {"project_id": project_id}).fetchall()
        existing_chapters = [(r[0], r[1], r[2], r[3], r[4]) for r in chapters_result]

        # 计算下一章编号
        next_chapter_number = len(existing_chapters) + 1
        logger.info(f"   ✓ 当前已有 {len(existing_chapters)} 章，即将生成第 {next_chapter_number} 章")
        
        # 4. 提取前一章结尾（用于衔接）
        previous_ending = ""
        if existing_chapters:
            previous_chapter = existing_chapters[-1]
            if previous_chapter[3]:  # 有内容
                # 提取最后500个字符
                content = previous_chapter[3]
                previous_ending = content[-500:] if len(content) > 500 else content
        
        # 5. 生成已完成章节摘要，并为内容创作准备结构化的上一章信息
        def summarize_chapters(chapters):
            """生成已完成章节的摘要，并构造供内容生成使用的高层摘要列表。
            
            策略：2章最近章节全文 + 8章更靠前章节的摘要
            - 最近2章：使用完整内容（保证衔接自然）
            - 往前8章：使用结构化摘要（覆盖更长历史）
            - 更早章节：使用简要摘要（节省token）
            """
            if not chapters:
                return "这是第一章，之前没有章节。", [], ""

            # 局部导入，避免潜在的循环依赖
            from app.services.agents.chapter_summarizer import create_chapter_summarizer

            summaries = []
            previous_chapters_payload = []

            summarizer = None
            try:
                summarizer = create_chapter_summarizer(db_session=db)
            except Exception as e:
                logger.error(f"   ⚠️ 创建章节摘要生成器失败，将回退到内容前200字: {e}")

            total = len(chapters)
            RECENT_FULL_COUNT = 2  # 最近2章使用全文
            SUMMARY_COUNT = 8      # 往前8章使用详细摘要
            RECENT_ASSET_COUNT = 4  # 最近4章优先提取结构化连续性资产

            for idx, chapter in enumerate(chapters):
                chapter_id, chapter_num, title, content, existing_summary = chapter
                content = content or ""
                title = title or ""
                summary_text = (existing_summary or "").strip()
                summary_data = {}

                # 计算当前章节距离最后一章的距离
                distance_from_end = total - idx

                # 判断是否需要生成详细摘要（最近2章之后的8章）
                needs_detailed_summary = (distance_from_end > RECENT_FULL_COUNT and 
                                        distance_from_end <= RECENT_FULL_COUNT + SUMMARY_COUNT)
                needs_recent_assets = distance_from_end <= RECENT_ASSET_COUNT

                if summarizer and (needs_detailed_summary or needs_recent_assets):
                    try:
                        cached_summary = summarizer.load_summary_from_db(chapter_id)
                        if isinstance(cached_summary, dict):
                            summary_data = cached_summary
                            summary_text = summary_data.get("core_summary", "").strip() or summary_text
                    except Exception as e:
                        logger.warning(f"   ⚠️ 读取第{chapter_num}章缓存摘要失败，将继续使用已有内容: {e}")

                if summarizer and needs_detailed_summary and not summary_data:
                    # 对需要详细摘要的章节，生成200字结构化摘要
                    try:
                        summary_data = summarizer.get_or_generate_summary(
                            chapter_id=chapter_id,
                            chapter_number=chapter_num,
                            chapter_title=title or f"第{chapter_num}章",
                            chapter_content=content,
                            summary_length=200,
                        )
                        summary_text = summary_data.get("core_summary", "").strip() or summary_text
                        logger.info(f"   ✅ 第{chapter_num}章使用详细摘要（距离末尾{distance_from_end}章）")
                    except Exception as e:
                        logger.error(f"   ⚠️ 生成第{chapter_num}章摘要失败，将回退简要摘要: {e}")

                # 如果没有摘要，使用前200字作为简要摘要
                if not summary_text:
                    summary_text = content[:200] if content and len(content) > 200 else content

                summaries.append(f"第{chapter_num}章 《{title}》: {summary_text}...")
                previous_chapters_payload.append(
                    {
                        "chapter_number": chapter_num,
                        "title": title,
                        "content": content,
                        "summary": summary_text,
                        "summary_data": summary_data,
                    }
                )

            # 输出策略统计
            if total > 0:
                recent_full_range = f"第{max(1, total-RECENT_FULL_COUNT+1)}-{total}章" if total > RECENT_FULL_COUNT else f"第1-{total}章"
                summary_range_start = max(1, total - RECENT_FULL_COUNT - SUMMARY_COUNT + 1)
                summary_range_end = max(0, total - RECENT_FULL_COUNT)
                
                logger.info(f"   📊 上下文策略：")
                logger.info(f"      - 最近{min(RECENT_FULL_COUNT, total)}章全文: {recent_full_range}")
                if summary_range_end > 0:
                    logger.info(f"      - 往前{min(SUMMARY_COUNT, summary_range_end)}章摘要: 第{summary_range_start}-{summary_range_end}章")
                if total > RECENT_FULL_COUNT + SUMMARY_COUNT:
                    logger.info(f"      - 更早{total - RECENT_FULL_COUNT - SUMMARY_COUNT}章简要摘要: 第1-{total-RECENT_FULL_COUNT-SUMMARY_COUNT}章")

            recent_chapter_assets_summary = _build_recent_chapter_assets_summary(previous_chapters_payload)
            return "\n\n".join(summaries), previous_chapters_payload, recent_chapter_assets_summary

        previous_chapters_summary, previous_chapters_payload, recent_chapter_assets_summary = summarize_chapters(existing_chapters)

        # 6. 生成任务ID并创建任务记录
        task_id = str(uuid.uuid4())
        logger.info(f"   🎯 创建异步任务: {task_id}")

        # 创建任务记录
        insert_query = text("""
            INSERT INTO generation_history
            (project_id, task_type, task_id, status, created_at)
            VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """)

        db.execute(insert_query, {
            "project_id": project_id,
            "task_type": "generate_next_chapter",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        world_context = workflow_context_builder.build_world_setting_context(
            project_id,
            world_setting,
        )
        merged_world_setting = world_context.combined_world_setting
        if world_context.settings_summary:
            logger.info(
                "   ✓ 已统一装配工作流世界观上下文（设定摘要%s）",
                "去重复用" if world_context.summary_already_embedded else "实时注入",
            )

        # 7. 启动后台任务
        asyncio.create_task(
            execute_generate_next_chapter_task(
                task_id=task_id,
                project_id=project_id,
                user_id=current_user.id,
                next_chapter_number=next_chapter_number,
                concept=concept or '',
                world_setting=merged_world_setting,
                characters=characters or '',
                plot_outline=plot_outline or '',
                previous_ending=previous_ending,
                previous_chapters_summary=previous_chapters_summary,
                previous_chapters_payload=previous_chapters_payload,
                recent_chapter_assets_summary=recent_chapter_assets_summary,
            )
        )
        logger.info(f"   🚀 后台任务已启动")

        # 8. 立即返回响应
        return {
            "task_id": task_id,
            "status": "running",
            "message": f"已开始生成第{next_chapter_number}章",
            "next_chapter_number": next_chapter_number
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建生成下一章任务失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def execute_generate_next_chapter_task(
    task_id: str,
    project_id: int,
    user_id: int,
    next_chapter_number: int,
    concept: str,
    world_setting: str,
    characters: str,
    plot_outline: str,
    previous_ending: str,
    previous_chapters_summary: str,
    previous_chapters_payload: list,
    recent_chapter_assets_summary: str,
):
    """
    后台执行生成下一章任务（真流式版本）

    执行四个步骤：
    1. 章节规划（0-25%）- 使用 asyncio.to_thread 避免阻塞
    2. 内容创作（25-50%）- 使用真流式 LLM 调用
    3. 质量评审（50-75%）- 使用真流式 LLM 调用
    4. 迭代优化（75-100%）- 使用真流式 LLM 调用
    """
    from sqlalchemy import text
    from app.db.base import SessionLocal

    logger = logging.getLogger("uvicorn.error")
    logger.info(f"🚀 开始执行后台任务: {task_id}, 生成第{next_chapter_number}章")

    # 获取流式服务
    streaming_service = get_streaming_service()

    # 创建独立的数据库会话
    db = SessionLocal()

    # 🆕 定义四个步骤对应的 Agent 列表
    STEP_AGENTS = {
        'structure': [  # 步骤1：章节规划
            {'id': 'plot_architect', 'name': '情节架构师', 'stage': 'structure'},
            {'id': 'event_validator', 'name': '事件验证官', 'stage': 'structure'},
        ],
        'content': [  # 步骤2：内容创作
            {'id': 'content_creator', 'name': '内容创作师', 'stage': 'content'},
            {'id': 'style_optimizer', 'name': '文风优化师', 'stage': 'content'},
        ],
        'review': [  # 步骤3：质量评审
            {'id': 'quality_reviewer', 'name': '质量评审官', 'stage': 'review'},
        ],
        'iteration': [  # 步骤4：迭代优化
            {'id': 'iteration_coordinator', 'name': '迭代协调官', 'stage': 'iteration'},
            {'id': 'content_reviser', 'name': '内容修订师', 'stage': 'iteration'},
            {'id': 'final_reviewer', 'name': '最终审核官', 'stage': 'iteration'},
        ],
    }

    try:
        workflow_context_builder = WorkflowContextBuilder(db)
        project_profile = workflow_context_builder.get_project_profile(project_id)
        # ==================== 步骤1：章节规划（真流式） ====================
        # 🆕 推送步骤1的 Agent 开始工作状态
        step1_agents = STEP_AGENTS['structure']
        for agent in step1_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在规划章节结构...'
            )
        logger.info(f"   📡 已发送 {len(step1_agents)} 个 Agent 开始状态（步骤1）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=5,
            message=f"步骤 1/4: 正在规划第{next_chapter_number}章结构..."
        )
        logger.info(f"   → 步骤1: 生成章节规划（真流式）...")

        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")

        coordinator.set_project_context(project_id)
        project_profile, real_coordinator = _sync_real_coordinator_project_context(
            project_id,
            workflow_context_builder,
            project_profile,
        )
        if not real_coordinator:
            raise Exception("Agent协调器未初始化")

        # 🆕 发送流式开始通知
        await ws_manager.send_stream_start(project_id, 'structure', f"第{next_chapter_number}章规划开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤1）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='structure',
            status='active',
            progress=0
        )

        # 🆕 创建流式输出回调
        plan_chunk_index = [0]

        async def on_plan_chunk(chunk: str, idx: int):
            """章节规划流式回调"""
            plan_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='structure',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        # 🎆 第一步：为章节规划使用分层摘要策略
        from app.services.agents.layered_summarizer import LayeredSummarizer
        from app.services.agents.agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE
        from app.services.prompts.stages.chapter_planning import (
            ChapterPlanningPrompts, 
            get_genre_chapter_plan_guide,
            get_climax_instruction
        )

        # 🆕 获取高潮章节指示（使用模块化函数）
        climax_instruction = get_climax_instruction(next_chapter_number)
        
        # 🆕 获取项目题材
        plan_project_genre = project_profile.genre or ""
        logger.info(f"   🎯 项目题材: {plan_project_genre or '通用'}")
        
        # 🆕 获取题材专属章节规划指导
        plan_genre_module = GENRE_PROMPT_MODULES.get(plan_project_genre, DEFAULT_GENRE_MODULE)
        chapter_plan_guide = plan_genre_module.get('chapter_plan_guide', '')
        
        # 🎆 使用分层摘要策略优化上下文
        layered_summarizer = LayeredSummarizer()
        plan_context_result = layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline or "",
            characters=characters or "",
            worldview=world_setting or "",
            scenario="chapter_generation",
            current_count=next_chapter_number,  # 使用当前章节数选择模型
            focus_range=(max(1, next_chapter_number - 5), next_chapter_number + 5),  # 聚焦当前章节前后5章
            project_id=project_id,
        )
        
        # 🔥 使用智能选择的模型和优化后的上下文
        selected_plan_model = plan_context_result["selected_model"]
        plan_optimized_context_text = plan_context_result["context"]
        plan_memory_text = plan_context_result.get("memory_text", "")
        plan_structured_memory = plan_context_result.get("structured_memory", {})
        plan_stats = plan_context_result["stats"]
        
        logger.info(f"   📊 上下文优化（章节规划 - 分层摘要）:")
        logger.info(f"      - 选择模型: {selected_plan_model}")
        logger.info(f"      - 原始总长: {len(plot_outline or '') + len(characters or '') + len(world_setting or ''):,}字符")
        logger.info(f"      - 优化后: {len(plan_optimized_context_text):,}字符 (压缩{(1-plan_stats['compression_ratio'])*100:.1f}%)")
        logger.info(f"      - 结构化记忆: {len(plan_memory_text):,}字符 / {len(plan_structured_memory)}类")
        logger.info(f"      - Token使用: {plan_stats['total_tokens']:,} / {plan_stats['target_tokens']:,}")
        logger.info(f"      - 聚焦范围: 第{max(1, next_chapter_number - 5)}-{next_chapter_number + 5}章")
        resolved_plan_model = resolve_model_for_task(None, selected_plan_model) or selected_plan_model
        
        # 构建包含各部分的上下文字典（用于后续提示词构建）
        plan_optimized_context = {
            'project_concept': concept or '',
            'plot_outline': plan_optimized_context_text,  # 使用优化后的完整上下文
            'structured_memory_text': plan_memory_text,
            'structured_memory': plan_structured_memory,
            'world_setting': '',  # 已包含在优化上下文中
            'characters': '',  # 已包含在优化上下文中
            'previous_chapters_analysis': previous_chapters_summary or '',
            'recent_chapter_assets_summary': recent_chapter_assets_summary or '',
            'previous_ending': previous_ending or ''
        }
        # 🆕 广播步骤1模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='structure',
            model=resolved_plan_model,
            extra={
                "step": "chapter_plan",
                "chapter_number": next_chapter_number,
                "requested_model": selected_plan_model,
            }
        )

        # 🆕 构建章节规划提示词（使用模块化系统）
        plan_system_prompt = ChapterPlanningPrompts.get_system_prompt(plan_project_genre)

        plan_user_prompt = f"""请为第{next_chapter_number}章制定创作计划。

【整本书信息 - 智能优化上下文】
- 故事概念：{plan_optimized_context.get('project_concept', concept)}

【优化后的核心上下文】（已通过分层摘要策略压缩，聚焦第{max(1, next_chapter_number - 5)}-{next_chapter_number + 5}章）
{plan_optimized_context.get('plot_outline', plot_outline)}

【结构化记忆约束】（优先遵循）
{plan_optimized_context.get('structured_memory_text', '') or '（无可用结构化记忆）'}

【已完成章节摘要】
{plan_optimized_context.get('previous_chapters_analysis', previous_chapters_summary) if previous_chapters_summary else '（这是第一章）'}

【最近章节连续性资产】（优先承接拆书细纲、未完成冲突、人物状态、伏笔与钩子）
{plan_optimized_context.get('recent_chapter_assets_summary', recent_chapter_assets_summary) or '（最近章节没有可用的结构化连续性资产）'}

【前一章结尾】
{plan_optimized_context.get('previous_ending', previous_ending) if previous_ending else '（这是第一章，没有前一章）'}
{climax_instruction}

---

请为第{next_chapter_number}章制定创作计划，必须包含以下内容：

## 1. 本章定位
- 在整体情节中的位置（起承转合哪个阶段）
- 本章类型：【日常/过渡/冲突/高潮/转折】

## 2. 核心事件
- 推进主线情节的关键事件
- 事件的起因-经过-结果

## 3. 爽点设计 ⚡
- 本章爽点类型：【打脸/升级/获得/反转/装逼/无（铺垫章）】
- 爽点具体内容描述
- 铺垫方式（如何让爽点更有冲击力）

## 4. 人物推进
- 主角本章的成长或变化
- 重要配角的表现
- 人物关系推进

## 5. 结尾钩子设计 🎣
- 钩子类型：【悬念式/危机式/反转式/信息炸弹式/选择困境式】
- 钩子具体内容
- 确保读者有"想点下一章"的冲动

## 6. 场景安排
- 时间、地点、氛围
- 场景转换节点

---

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 优先遵循结构化记忆中的人物状态、关系边、伏笔和世界规则
- 如果最近章节连续性资产中已经明确了场景目标、冲突推进、人物出场、结尾钩子或伏笔，必须优先承接，不要丢失
- 推进故事发展，不能原地踏步
- 爽点和钩子必须具体、可执行"""

        # 使用题材专属细化
        genre_specific = f"""
Genre-specific refinement (specific implementation of general planning requirements, please use in combination)
{chapter_plan_guide}""" if chapter_plan_guide else ''

        # 将题材专属细化添加到提示词
        if genre_specific:
            plan_user_prompt += genre_specific

        # 🆕 使用真流式 LLM 调用（智能选择模型）
        try:
            chapter_plan = await streaming_service.generate_chapter_streaming(
                prompt=plan_user_prompt,
                system_prompt=plan_system_prompt,
                on_chunk=on_plan_chunk,
                temperature=0.7,
                model=selected_plan_model,  # 🔥 使用智能选择的模型
            )
            logger.info(f"   ✓ 章节规划已完成（真流式 + {selected_plan_model}），长度: {len(chapter_plan)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'generate_chapter_plan'):
                chapter_plan = await asyncio.to_thread(
                    real_coordinator.generate_chapter_plan,
                    chapter_number=next_chapter_number,
                    project_concept=concept,
                    plot_outline=plot_outline,
                    world_setting=world_setting,
                    characters=characters,
                    previous_chapters_summary=previous_chapters_summary,
                    previous_ending=previous_ending
                )
            else:
                chapter_plan = f"第{next_chapter_number}章创作规划\n\n根据情节大纲和前序章节，本章将继续推进故事发展..."

        await ws_manager.send_stream_end(project_id, 'structure', len(chapter_plan), f"第{next_chapter_number}章规划完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤1）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='structure',
            status='completed',
            output=chapter_plan,
            progress=25
        )

        # 🆕 推送步骤1的 Agent 完成状态
        for agent in step1_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step1_agents)} 个 Agent 完成状态（步骤1）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=25,
            message=f"步骤 1/4: 章节规划完成 ✓"
        )

        # ==================== 步骤2：内容创作（真流式） ====================
        logger.info(f"   🔴 开始步骤2：内容创作")
        
        # 🆕 推送步骤2的 Agent 开始工作状态
        step2_agents = STEP_AGENTS['content']
        logger.info(f"   📄 已获取步骤2 Agents: {[a['name'] for a in step2_agents]}")
        
        for agent in step2_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在创作章节内容...'
            )
        logger.info(f"   📡 已发送 {len(step2_agents)} 个 Agent 开始状态（步骤2）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=30,
            message=f"步骤 2/4: 正在创作第{next_chapter_number}章内容..."
        )
        logger.info(f"   → 步骤2: 生成章节内容（真流式）...")
        logger.info(f"   📊 章节规划长度: {len(chapter_plan)} 字")

        # 🆕 发送流式开始通知
        logger.info(f"   🌊 发送流式开始通知...")
        await ws_manager.send_stream_start(project_id, 'content', f"第{next_chapter_number}章内容创作开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤2）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='content',
            status='active',
            progress=25
        )

        # 🆕 创建流式输出回调
        content_chunk_index = [0]
        logger.info(f"   🔧 已创建流式回调函数")

        async def on_content_chunk(chunk: str, idx: int):
            """内容创作流式回调"""
            content_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='content',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        logger.info(f"   📐 开始匹配场景类型...")

        # 🆕 开头/结尾方式定义（与 agent_coordinator 保持同步）
        opening_styles = {
            "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
            "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
            "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
            "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
            "内心独白开头": ("内心独白开头", "从人物内心思绪入手，展现心理冲突或决策过程", ""),
            "回忆插入开头": ("回忆插入开头", "通过回忆或闪回提供关键背景，丰富当前情节", ""),
            "疯狂开头": ("疯狂开头", "从激烈冲突或混乱场面开始，立即抽住读者注意力", ""),
            "对比开头": ("对比开头", "通过前后对比或境遇差异，强化情绪冲击", ""),
            "时间跳跃开头": ("时间跳跃开头", "直接跳转到事件后的关键时刻，略过过程增加节奏", ""),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
            "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
            "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
            "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撑效果", ""),
            "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
            "情感升华式": ("情感升华式", "通过情感浓度提升结束，留下余韵", ""),
            "环境渲染式": ("环境渲染式", "以环境气氛变化暗示危机或转机", ""),
            "对话留白式": ("对话留白式", "关键对话说一半留一半，制造疑问", ""),
            "时间压力式": ("时间压力式", "引入倒计时或期限，增加紧迫感", ""),
            "身份揭露式": ("身份揭露式", "暗示或半揭露人物真实身份，激发好奇", ""),
        }

        # 🆕 情节类型 → 推荐的开头/结尾方式
        scene_style_rules = {
            "战斗": {"keywords": ["战斗", "打斗", "厮杀", "对决", "交手", "出招", "攻击", "防御", "刀剑", "拳脚"],
                    "opening": "动作开头", "ending": "动作中断式"},
            "悬疑": {"keywords": ["悬疑", "推理", "谜团", "线索", "真相", "秘密", "调查", "疑点", "隐情", "身世"],
                    "opening": "悬念开头", "ending": "悬念式"},
            "转折": {"keywords": ["转折", "揭秘", "真相大白", "身份", "背叛", "反转", "意外", "惊人", "原来", "竟然"],
                    "opening": "反转开头", "ending": "信息炸弹式"},
            "情感": {"keywords": ["告别", "离别", "重逢", "表白", "感情", "思念", "回忆", "温情", "感动", "眼泪"],
                    "opening": "场景开头", "ending": "选择困境式"},
            "危机": {"keywords": ["危机", "危险", "生死", "逃亡", "追杀", "困境", "绝境", "险境", "紧急", "千钧一发"],
                    "opening": "动作开头", "ending": "动作中断式"},
            "对话": {"keywords": ["谈判", "对话", "交涉", "质问", "争执", "辩论", "说服", "威胁", "警告", "摊牌"],
                    "opening": "对话开头", "ending": "转折式"},
            "日常": {"keywords": ["日常", "休息", "准备", "旅途", "修炼", "学习", "训练", "恢复", "整顿", "计划"],
                    "opening": "场景开头", "ending": "悬念式"},
            "升级": {"keywords": ["突破", "升级", "进阶", "觉醒", "获得", "传承", "机缘", "宝物", "功法", "神通"],
                    "opening": "悬念开头", "ending": "信息炸弹式"},
        }

        # 🆕 分析章节规划，匹配情节类型
        matched_scene_type = None
        max_keyword_count = 0
        for scene_type, rule in scene_style_rules.items():
            keyword_count = sum(1 for kw in rule["keywords"] if kw in chapter_plan)
            if keyword_count > max_keyword_count:
                max_keyword_count = keyword_count
                matched_scene_type = scene_type

        # 🆕 根据匹配结果选择开头/结尾方式
        if matched_scene_type and max_keyword_count >= 1:
            rule = scene_style_rules[matched_scene_type]
            selected_opening = opening_styles[rule["opening"]]
            selected_ending = ending_styles[rule["ending"]]
            match_method = f"关键词匹配({matched_scene_type}场景, 命中{max_keyword_count}个关键词)"
        else:
            # 回退到章节编号轮换
            opening_list = list(opening_styles.values())
            ending_list = list(ending_styles.values())
            opening_index = (next_chapter_number - 1) % len(opening_list)
            ending_index = (next_chapter_number + 2) % len(ending_list)
            selected_opening = opening_list[opening_index]
            selected_ending = ending_list[ending_index]
            match_method = "章节编号轮换(未匹配到关键词)"

        logger.info(f"   📝 第{next_chapter_number}章 - 开头: {selected_opening[0]}, 结尾: {selected_ending[0]} [{match_method}]")
        logger.info(f"   💬 构建内容创作提示词...")

        # 🆕 上下文优化：获取智能模型选择
        from app.services.agents.context_optimizer import get_context_optimizer
        context_optimizer = get_context_optimizer(
            current_chapter=next_chapter_number,
            stage='content_creation'
        )
        
        # 🆕 获取优化器选择的模型（不再需要 optimize_for_chapter_generation，因为章节规划已消化上下文）
        selected_content_model = context_optimizer.selected_model
        resolved_content_model = resolve_model_for_task(None, selected_content_model) or selected_content_model
        logger.info(f"   🤖 内容创作使用模型: {resolved_content_model} (requested={selected_content_model})")
        # 🆕 广播步骤2模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='content',
            model=resolved_content_model,
            extra={
                "step": "chapter_content",
                "chapter_number": next_chapter_number,
                "requested_model": selected_content_model,
            }
        )

        # 🆕 Typed-RAG（按类型检索并注入提示）
        rag_character_context = ""
        rag_world_context = ""
        rag_bundle = workflow_context_builder.build_typed_rag_context(
            project_id,
            chapter_plan,
            fallback_max_content_length=200,
        )
        rag_character_context = rag_bundle.rag_character_context
        rag_world_context = rag_bundle.rag_world_context
        if rag_bundle.relevant_categories:
            logger.info(f"   📆 章节规划涉及体系: {rag_bundle.relevant_categories}")
        if rag_bundle.used_vector_search:
            logger.info(
                "   📚 RAG注入：人物%s条，设定%s条",
                rag_bundle.character_hits,
                rag_bundle.world_hits,
            )
        if rag_bundle.used_summary_fallback:
            logger.info(
                "   📚 RAG fallback: 从设定中心直接查询%s个相关体系",
                len(rag_bundle.relevant_categories),
            )

        # 🆕 构建内容创作提示词（精简版 - 章节规划已消化大部分上下文）
        from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
        
        # 获取项目题材
        project_genre = project_profile.genre or ""
        
        builder = ChapterPromptBuilder(genre=project_genre)
        content_system_prompt = builder.build_system_prompt()
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            previous_ending=previous_ending or "",
            recent_chapter_assets_summary=recent_chapter_assets_summary or "",
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            selected_opening=selected_opening,
            selected_ending=selected_ending,
        )
        
        # 📊 输出精简版 prompt 统计
        logger.info(f"   📉 Prompt优化（精简版）：")
        logger.info(f"      - 章节规划: {len(chapter_plan)} 字")
        logger.info(f"      - 前一章结尾: {len(previous_ending or '')} 字")
        logger.info(f"      - 最近章节连续性资产: {len(recent_chapter_assets_summary or '')} 字")
        logger.info(f"      - RAG人物: {len(rag_character_context)} 字")
        logger.info(f"      - RAG设定: {len(rag_world_context)} 字")
        logger.info(f"      - 总共: {len(content_user_prompt)} 字（移除冗余情节大纲/世界观/人物/前序章节）")

        # 🆕 使用真流式 LLM 调用（智能选择模型）
        logger.info(f"   🚀 开始调用流式 LLM 服务生成章节内容...")
        try:
            chapter_draft = await streaming_service.generate_chapter_streaming(
                prompt=content_user_prompt,
                system_prompt=content_system_prompt,
                on_chunk=on_content_chunk,
                temperature=0.7,
                model=selected_content_model,  # 🔥 使用智能选择的模型
            )
            logger.info(f"   ✓ 章节初稿已完成（真流式 + {selected_content_model}），字数: {len(chapter_draft)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            import traceback
            traceback.print_exc()  # 🔧 打印完整的异常堆栈
            # 回退到同步调用
            if hasattr(real_coordinator, 'generate_chapter_content'):
                try:
                    chapter_draft = await asyncio.to_thread(
                        real_coordinator.generate_chapter_content,
                        chapter_number=next_chapter_number,
                        chapter_plan=chapter_plan,
                        world_setting=world_setting,
                        characters=characters,
                        previous_ending=previous_ending,
                        target_word_count=3000,
                        previous_chapters=previous_chapters_payload,
                    )
                    logger.info(f"   ✓ 使用同步方式生成章节成功，字数: {len(chapter_draft)}")
                except Exception as sync_error:
                    logger.error(f"   ❌ 同步调用也失败: {sync_error}")
                    traceback.print_exc()
                    chapter_draft = f"第{next_chapter_number}章内容\n\n{chapter_plan}\n\n（此处为生成的章节内容）"
            else:
                logger.warning("   ⚠️ 协调器没有 generate_chapter_content 方法，使用默认模板")
                chapter_draft = f"第{next_chapter_number}章内容\n\n{chapter_plan}\n\n（此处为生成的章节内容）"

        logger.info(f"   🌊 发送流式结束通知...")
        await ws_manager.send_stream_end(project_id, 'content', len(chapter_draft), f"第{next_chapter_number}章内容创作完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤2）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='content',
            status='completed',
            output=chapter_draft,
            progress=50
        )
        logger.info(f"   ✓ 流式结束通知已发送")

        # 🆕 推送步骤2的 Agent 完成状态
        for agent in step2_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step2_agents)} 个 Agent 完成状态（步骤2）")

        # 保存章节初稿到 project_settings
        logger.info(f"   💾 开始保存章节初稿到数据库...")
        workflow_context_builder.update_project_settings_fields(
            project_id,
            chapter_draft=chapter_draft,
        )
        logger.info(f"   ✓ 章节初稿已同步到数据库")

        logger.info(f"   📡 发送步骤2完成进度通知...")
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=50,
            message=f"步骤 2/4: 章节内容创作完成 ✓"
        )
        logger.info(f"   ✅ 步骤2完全完成！")

        # ==================== 步骤3：质量评审（真流式） ====================
        # 🆕 推送步骤3的 Agent 开始工作状态
        step3_agents = STEP_AGENTS['review']
        for agent in step3_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在评审章节质量...'
            )
        logger.info(f"   📡 已发送 {len(step3_agents)} 个 Agent 开始状态（步骤3）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=55,
            message=f"步骤 3/4: 正在进行质量评审..."
        )
        logger.info(f"   → 步骤3: 质量评审（真流式）...")

        # 🆕 发送流式开始通知
        await ws_manager.send_stream_start(project_id, 'review', f"第{next_chapter_number}章质量评审开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤3）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='review',
            status='active',
            progress=50
        )

        # 🆕 创建流式输出回调
        review_chunk_index = [0]

        async def on_review_chunk(chunk: str, idx: int):
            """评审流式回调"""
            review_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='review',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

         # 🆕 获取项目题材（用于题材自适应评审）
        review_project_genre = project_profile.genre or ""
        logger.info(f"   🎯 评审使用题材: {review_project_genre or '通用'}")
        
        # 🆕 使用题材自适应评审提示词
        from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts
        
        review_system_prompt = GenreAdaptiveReviewPrompts.get_review_system_prompt(
            genre=review_project_genre
        )
        
        review_user_prompt = GenreAdaptiveReviewPrompts.get_review_user_prompt(
            chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            chapter_content=chapter_draft,
            plot_outline=plot_outline,
            genre=review_project_genre,
            recent_chapter_assets_summary=recent_chapter_assets_summary,
        )

        # 🆕 使用真流式 LLM 调用（按 review 任务路由）
        try:
            review_report = await streaming_service.generate_chapter_streaming(
                prompt=review_user_prompt,
                system_prompt=review_system_prompt,
                on_chunk=on_review_chunk,
                temperature=0.7,
                task_type="review",
            )
            logger.info(f"   ✓ 评审完成（真流式 + review任务路由），报告长度: {len(review_report)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'review_chapter'):
                review_report = await asyncio.to_thread(
                    real_coordinator.review_chapter,
                    chapter_draft=chapter_draft,
                    chapter_plan=chapter_plan,
                    plot_outline=plot_outline
                )
            else:
                review_report = "质量评审：章节符合要求，可以继续优化。"

        await ws_manager.send_stream_end(project_id, 'review', len(review_report), f"第{next_chapter_number}章质量评审完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤3）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='review',
            status='completed',
            output=review_report,
            progress=75
        )

        # 🆕 推送步骤3的 Agent 完成状态
        for agent in step3_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step3_agents)} 个 Agent 完成状态（步骤3）")

        # 保存评审报告到 project_settings
        workflow_context_builder.update_project_settings_fields(
            project_id,
            review_report=review_report,
        )
        logger.info(f"   ✓ 评审报告已同步到数据库")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=75,
            message=f"步骤 3/4: 质量评审完成 ✓"
        )

        # ==================== 步骤4：迭代优化（真流式） ====================
        # 🆕 推送步骤4的 Agent 开始工作状态
        step4_agents = STEP_AGENTS['iteration']
        try:
            from app.core.config import settings
            pass_score_threshold = float(getattr(settings, 'ITERATION_PASS_SCORE', 9.0))
            max_rounds = int(getattr(settings, 'ITERATION_MAX_ROUNDS', 2))
        except Exception:
            pass_score_threshold = 8.5
            max_rounds = 2

        initial_review_score = _extract_iteration_review_score(review_report)
        skip_iteration_optimization = initial_review_score >= pass_score_threshold
        logger.info(
            f"   🎯 迭代优化目标分值: {pass_score_threshold} | 最大轮次: {max_rounds} | "
            f"初始评审分值: {initial_review_score:.1f}/10"
        )
        for agent in step4_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed' if skip_iteration_optimization else 'working',
                progress=100 if skip_iteration_optimization else 0,
                message=(
                    f'{agent["name"]}检测到初始评审已达标，已跳过迭代优化'
                    if skip_iteration_optimization
                    else f'{agent["name"]}正在迭代章节内容...'
                )
            )
        logger.info(
            f"   📡 已发送 {len(step4_agents)} 个 Agent "
            f"{'完成状态（步骤4-跳过优化）' if skip_iteration_optimization else '开始状态（步骤4）'}"
        )

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=80,
            message=(
                f"步骤 4/4: 初始评审已达标（{initial_review_score:.1f}/10），跳过迭代优化"
                if skip_iteration_optimization
                else "步骤 4/4: 正在迭代中，请等待..."
            )
        )
        logger.info(
            f"   → 步骤4: {'初始评审已达标，跳过迭代优化' if skip_iteration_optimization else '迭代优化（真流式）...'}"
        )

        # 🆕 发送流式开始通知
        if not skip_iteration_optimization:
            await ws_manager.send_stream_start(project_id, 'iteration', f"第{next_chapter_number}章迭代优化开始...")
            # 🔔 推送阶段开始状态（生成下一章 - 步骤4）
            await ws_manager.send_stage_update(
                project_id=project_id,
                stage='iteration',
                status='active',
                progress=75
            )

        # 🆕 创建流式输出回调
        iteration_chunk_index = [0]

        async def on_iteration_chunk(chunk: str, idx: int):
            """迭代优化流式回调"""
            iteration_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='iteration',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        # 🆕 构建迭代优化提示词
        iteration_system_prompt = """你是一位资深的网络小说编辑。请根据评审意见对章节内容进行优化修改。

优化要求：
1. 保持原有故事框架和主要情节不变
2. 改进语言表达，使文笔更加流畅
3. 增强细节描写，提升画面感
4. 优化对话内容，使其更符合人物性格
5. 提升整体可读性和爽感
6. 修正任何语病或不连贯之处
7. 优化后的章节应完整保留原有情节发展，篇幅不应少于原稿字数的80%
8. 如果提供了最近章节连续性资产，必须优先承接其中的场景目标、冲突推进、人物状态、结尾钩子与伏笔

【输出格式要求】⚠️
请直接输出优化后的章节内容，格式必须如下：

第X章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第X章 标题名称"（X为章节数字）
- 如果原稿有章节标题则保留或优化，如果没有则根据内容新增一个
- 不要包含任何评论、解释、优化说明等额外文字
- 只输出：章节标题 + 章节正文内容"""

        iteration_user_prompt = _build_iteration_revision_prompt(
            chapter_number=next_chapter_number,
            chapter_content=chapter_draft,
            review_text=review_report,
            recent_chapter_assets_summary=recent_chapter_assets_summary,
        )

        # 🆕 使用迭代优化（max改稿 + R1打分循环,达到阈值后再输出）
        try:
            # 🎯 根据实际输入长度动态选择改稿模型
            def estimate_tokens(text: str) -> int:
                """估算文本的 token 数（中文按1.3倍字符数估算）"""
                return _estimate_tokens_by_chars(text)
            
            def select_model_by_length(chapter_content: str, reviews: str) -> str:
                """根据输入长度智能选择模型
                
                Args:
                    chapter_content: 当前章节内容
                    reviews: 累积的评审意见
                
                Returns:
                    选择的模型名称
                """
                # 估算总输入长度（章节 + 评审 + 系统提示词 + 用户提示词模板）
                chapter_tokens = estimate_tokens(chapter_content)
                reviews_tokens = estimate_tokens(reviews)
                prompt_overhead = 500  # 系统提示词和用户提示词模板的开销
                
                total_tokens = chapter_tokens + reviews_tokens + prompt_overhead
                selected_model, _ = _select_text_model_by_input_tokens(total_tokens)
                return selected_model
            
            # 初始评审意见
            initial_reviews = review_report or ""
            
            # 选择初始模型
            selected_revision_model = select_model_by_length(chapter_draft, initial_reviews)
            resolved_revision_model = resolve_model_for_task(None, selected_revision_model) or selected_revision_model
            logger.info(f"   🤖 迭代优化改稿模型: {resolved_revision_model} (requested={selected_revision_model})")
            logger.info(f"      - 章节长度: {len(chapter_draft)} 字 ≈ {estimate_tokens(chapter_draft)} tokens")
            logger.info(f"      - 初始评审: {len(initial_reviews)} 字 ≈ {estimate_tokens(initial_reviews)} tokens")
            logger.info(f"      - 预估总计: ≈ {estimate_tokens(chapter_draft) + estimate_tokens(initial_reviews) + 500} tokens")
            logger.info(f"      - qwen3-max 安全输入预算: ≈ {_get_safe_input_token_budget('qwen3-max')} tokens")
            
            # 🆕 广播步骤4改稿模型（首轮改稿前广播一次）
            if not skip_iteration_optimization:
                await ws_manager.send_model_used(
                    project_id=project_id,
                    stage='iteration',
                    model=resolved_revision_model,
                    extra={
                        "step": "iteration_revision",
                        "chapter_number": next_chapter_number,
                        "requested_model": selected_revision_model,
                    }
                )

            effective_rounds = 0 if skip_iteration_optimization else max_rounds

            # 初始版本与评审
            current_version = chapter_draft
            current_review = review_report
            final_version = current_version
            reached_pass = skip_iteration_optimization
            best_version = current_version
            # 初始化最佳分数为已有评审的分数（若无法提取则为0）
            best_score = _extract_iteration_review_score(current_review)
            # 🆕 累积所有轮次的评审意见，作为改稿参考
            all_reviews = [f"【第0轮评审（初稿）】\n{current_review}"]

            if skip_iteration_optimization:
                logger.info(
                    f"   🎉 初始评审已达标（{initial_review_score:.1f}/10 >= {pass_score_threshold:.1f}/10），"
                    f"跳过后续迭代优化"
                )

            # 不透出中间稿的流式回调（前端只看最终稿）
            async def noop_chunk(chunk: str, idx: int):
                return

            for round_idx in range(1, effective_rounds + 1):
                logger.info(f"   🔄 迭代优化第{round_idx}/{max_rounds}轮：开始改稿")
                # 🆕 推送迭代轮次信息到前端
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 70 + round_idx * 5),
                    message=f"步骤 4/4: 正在迭代中（第{round_idx}/{effective_rounds}轮），请等待..."
                )
                # 第N轮：根据所有历史评审意见进行改稿
                # 🆕 将所有评审意见汇总，按轮次展示
                all_reviews_text = "\n\n".join(all_reviews)
                
                # 🎯 每轮动态选择模型（因为评审意见在累积）
                current_model = select_model_by_length(current_version, all_reviews_text)
                if current_model != selected_revision_model:
                    selected_revision_model = current_model
                    resolved_revision_model = (
                        resolve_model_for_task(None, selected_revision_model) or selected_revision_model
                    )
                    logger.info(
                        f"   🔄 第{round_idx}轮模型切换: {resolved_revision_model} "
                        f"(requested={selected_revision_model})"
                    )
                    logger.info(f"      - 当前章节: {len(current_version)} 字 ≈ {estimate_tokens(current_version)} tokens")
                    logger.info(f"      - 累积评审: {len(all_reviews_text)} 字 ≈ {estimate_tokens(all_reviews_text)} tokens")
                    logger.info(f"      - 预估总计: ≈ {estimate_tokens(current_version) + estimate_tokens(all_reviews_text) + 500} tokens")
                    # 广播模型切换
                    await ws_manager.send_model_used(
                        project_id=project_id,
                        stage='iteration',
                        model=resolved_revision_model,
                        extra={
                            "step": f"iteration_round_{round_idx}",
                            "reason": "context_length_increase",
                            "requested_model": selected_revision_model,
                        }
                    )
                iteration_user_prompt_round = _build_iteration_revision_prompt(
                    chapter_number=next_chapter_number,
                    chapter_content=current_version,
                    review_text=all_reviews_text,
                    recent_chapter_assets_summary=recent_chapter_assets_summary,
                    include_history_hint=True,
                )

                # 仅在最后一轮向前端流式输出正文；前几轮不推送正文
                on_chunk_cb = on_iteration_chunk if round_idx == max_rounds else noop_chunk
                revised_version = await streaming_service.generate_chapter_streaming(
                    prompt=iteration_user_prompt_round,
                    system_prompt=iteration_system_prompt,
                    on_chunk=on_chunk_cb,
                    temperature=0.7,
                    model=selected_revision_model,
                )
                logger.info(f"   ✓ 第{round_idx}轮改稿完成（{selected_revision_model}），字数: {len(revised_version)}")
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 72 + round_idx * 5),
                    message=f"步骤 4/4: 第{round_idx}轮改稿完成，正在复评..."
                )

                # 评审打分（R1）
                review_system_prompt_loop = """你是一位专业的网络小说质量评审官。请使用网文6维度对上面的章节进行评审，并特别检查它是否承接了最近章节连续性资产中的场景目标、冲突推进、人物状态、结尾钩子与伏笔。\n1) 综合评分：X/10分\n2) 最重要的3条修改建议。\n请严格包含“综合评分：X/10分”这一行。"""
                review_user_prompt_loop = _build_iteration_review_prompt(
                    chapter_number=next_chapter_number,
                    chapter_content=revised_version,
                    chapter_plan=chapter_plan,
                    recent_chapter_assets_summary=recent_chapter_assets_summary,
                )
                new_review_report = await streaming_service.generate_chapter_streaming(
                    prompt=review_user_prompt_loop,
                    system_prompt=review_system_prompt_loop,
                    on_chunk=noop_chunk,  # 评分不流式推送正文
                    temperature=0.3,
                    task_type="review",
                )
                score = _extract_iteration_review_score(new_review_report)
                logger.info(f"   🧮 第{round_idx}轮评分：{score:.1f}/10")
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 80 + round_idx * 3),
                    message=f"步骤 4/4: 正在迭代中（第{round_idx}轮评分 {score:.1f}/10）..."
                )
                
                # 🆕 将本轮评审意见加入历史记录
                all_reviews.append(f"【第{round_idx}轮评审】\n{new_review_report}")

                # 🆕 记录最高评分版本
                if score > best_score:
                    best_score = score
                    best_version = revised_version

                # 判定是否达标
                if score >= pass_score_threshold:
                    final_version = revised_version
                    current_review = new_review_report
                    reached_pass = True
                    logger.info(f"   🎉 达到目标分值 {pass_score_threshold}，停止迭代")
                    break
                else:
                    # 继续下一轮
                    current_version = revised_version
                    current_review = new_review_report
                    final_version = revised_version

            if not reached_pass:
                logger.info(f"   ⚠️ 未达标，输出最高评分版本：{best_score:.1f}/10")
                final_version = best_version
            logger.info(f"   ✅ 迭代优化结束，输出最终版本，长度: {len(final_version)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式迭代优化失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'optimize_chapter'):
                final_version = await asyncio.to_thread(
                    real_coordinator.optimize_chapter,
                    chapter_draft=chapter_draft,
                    review_report=review_report
                )
            else:
                final_version = chapter_draft
        # 🆕 清理输出内容，移除额外的评审话语
        def clean_final_output(content: str) -> str:
            """清理最终输出，移除可能的额外评审话语"""
            if not content:
                return content
            lines = content.split('\n')
            cleaned_lines = []
            skip_section = False
            for line in lines:
                line_lower = line.lower().strip()
                # 跳过评审相关的段落
                if any(keyword in line_lower for keyword in [
                    '优化说明', '修改说明', '评审', '改进建议', '优化要点',
                    '以下是优化后', '根据评审意见', '主要修改', '优化内容'
                ]):
                    skip_section = True
                    continue
                if skip_section and line.strip() == '':
                    skip_section = False
                    continue
                if not skip_section:
                    cleaned_lines.append(line)
            return '\n'.join(cleaned_lines).strip()

        final_version = clean_final_output(final_version)

        # 🆕 安全保护：如果优化后字数远小于原稿，则认为可能被压缩成摘要，回退为原始章节内容
        original_len = len(chapter_draft or "")
        optimized_len = len(final_version or "")
        if original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
            logger.warning(
                f"   ⚠️ 优化后长度({optimized_len}) 远小于原稿({original_len})，疑似被压缩为摘要，本次将保留原始章节内容"
            )
            final_version = chapter_draft

        if not skip_iteration_optimization:
            await ws_manager.send_stream_end(project_id, 'iteration', len(final_version), f"第{next_chapter_number}章迭代优化完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤4）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='iteration',
            status='completed',
            output=final_version,
            progress=100
        )

        # 🆕 推送步骤4的 Agent 完成状态
        for agent in step4_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step4_agents)} 个 Agent 完成状态（步骤4）")

        # 保存最终版本到 project_settings
        workflow_context_builder.update_project_settings_fields(
            project_id,
            final_version=final_version,
        )
        logger.info(f"   ✓ 最终版本已同步到数据库")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=90,
            message=f"步骤 4/4: 正在保存章节..."
        )

        # ==================== 保存章节 ====================
        # 生成章节标题
        def convert_number_to_chinese(num: int) -> str:
            chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
            if num <= 10:
                return chinese_nums[num]
            elif num < 20:
                return '十' + chinese_nums[num - 10]
            elif num < 100:
                tens = num // 10
                ones = num % 10
                return chinese_nums[tens] + '十' + (chinese_nums[ones] if ones > 0 else '')
            else:
                return str(num)

        try:
            lines = final_version.split('\n')
            potential_title = None
            for line in lines[:5]:
                line = line.strip()
                if line and ('第' in line or '章' in line) and len(line) < 30:
                    potential_title = line
                    break

            if potential_title:
                chapter_title = potential_title
            else:
                chinese_num = convert_number_to_chinese(next_chapter_number)
                chapter_title = f"第{chinese_num}章 未命名"
        except Exception:
            chinese_num = convert_number_to_chinese(next_chapter_number)
            chapter_title = f"第{chinese_num}章 未命名"

        logger.info(f"   ✓ 章节标题: {chapter_title}")

        new_chapter = _create_generated_chapter(
            db,
            project_id=project_id,
            chapter_number=next_chapter_number,
            title=chapter_title,
            content=final_version,
        )
        new_chapter_id = new_chapter.id

        logger.info(f"   ✅ 章节已保存: id={new_chapter_id}")
        
        # 🆕 内容进化器：记录生成数据（5%采样 + 隐式反馈收集）
        try:
            from app.services.content_evolution import get_engine, GenerationStage
            
            evolution_engine = get_engine()
            await evolution_engine.on_generation_complete(
                project_id=project_id,
                chapter_id=new_chapter_id,
                genre=plan_project_genre or "通用",
                stage=GenerationStage.CONTENT,
                module_name="chapter_content",
                version_id="default",  # 暂用默认版本，后续可扩展为变体检测
                is_variant=False,
                content=final_version,
                ai_score=None,  # AI评分在评审阶段已完成
            )
            logger.info(f"   📊 内容进化器：已记录生成数据")
        except Exception as evo_err:
            logger.debug(f"   ⚠️ 内容进化器记录失败（不影响主流程）: {evo_err}")
        
        # 🚨 已移除正则快速提取，统一使用后台AI提取服务
        # 见: start_chapter_post_save_task -> chapter_post_save.py -> unified_extraction.py
        # 所有设定提取现在都经过AI处理，生成高质量描述

        # 🆕 阶段3：自动合并高置信度设定项到正式集合
        try:
            from app.services.setting_auto_merge import SettingAutoMergeService
            
            # 获取候选集合
            candidate_collection = db.query(SettingCollection).filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "candidate"
            ).first()
            
            if candidate_collection:
                merge_result = SettingAutoMergeService.auto_merge_high_confidence_items(
                    db=db,
                    project_id=project_id,
                    candidate_collection_id=candidate_collection.id,
                    chapter_plan=chapter_plan or "",
                    chapter_content=final_version or "",
                )
                
                if merge_result["merged_count"] > 0:
                    logger.info(
                        f"   ✓ 自动合并高置信度设定: "
                        f"成功 {merge_result['merged_count']} 项, "
                        f"跳过 {merge_result['skipped_count']} 项"
                    )
        except Exception as e:
            logger.warning(f"   ⚠️ 自动合并设定失败: {e}")

        # ✅ 章节保存完成，立即更新任务状态并推送完成事件
        # 注意：摘要生成和统一提取将在后台异步执行，不阻塞主流程
        update_query = text("""
            UPDATE generation_history
            SET status = :status, completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "status": "completed",
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        # 发送完成事件（章节已保存）
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={
                "chapter": {
                    "id": new_chapter_id,
                    "chapter_number": next_chapter_number,
                    "title": chapter_title,
                    "word_count": len(final_version),
                }
            }
        )

        logger.info(f"✅ 章节生成任务完成: {task_id}, 第{next_chapter_number}章已保存")
        
        # 🚀 启动后台任务（统一提取 + 摘要生成）- 异步执行，不等待结果
        try:
            from app.services.chapter_post_save import start_chapter_post_save_task
            
            logger.info(f"🚀 启动后台任务：统一提取 + 摘要生成（异步）...")
            
            # 启动后台异步任务（不等待完成）
            # 🆕 注意：generate_summary=True，仅工作流场景生成摘要
            start_chapter_post_save_task(
                chapter_id=new_chapter_id,
                chapter_title=chapter_title,
                chapter_content=final_version,
                chapter_number=next_chapter_number,
                project_id=project_id,
                generate_summary=True  # 🆕 工作流场景需要生成摘要
            )
            
            logger.info(f"✅ 后台任务已启动，将在后台异步执行")
            
        except Exception as e:
            logger.warning(f"⚠️ 启动后台任务失败（不影响章节保存）: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        logger.error(f"❌ 后台任务失败: {task_id}, 错误: {e}")
        import traceback
        traceback.print_exc()

        # 更新任务状态为失败
        try:
            update_query = text("""
                UPDATE generation_history
                SET status = :status, error_message = :error_message, completed_at = :completed_at
                WHERE task_id = :task_id
            """)
            db.execute(update_query, {
                "status": "failed",
                "error_message": str(e),
                "completed_at": utc_now().isoformat(),
                "task_id": task_id
            })
            db.commit()
        except Exception:
            pass

        # 发送错误事件
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
    finally:
        db.close()


@router.get("/epic-framework-state/{project_id}")
async def get_epic_framework_state(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🔍 检测长篇框架状态
    
    返回:
    {
        "has_framework": true/false,
        "total_volumes": 17,
        "expanded_volumes": [1, 3, 5],
        "framework_generated_at": "2025-12-12T10:00:00"
    }
    """
    import logging
    from app.services.outline_merger import detect_framework_state
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔍 检测长篇框架状态，项目ID: {project_id}")
        
        # 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 读取框架数据
        epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(project_id)
        
        if not (
            epic_framework_state.epic_framework
            or epic_framework_state.framework_generated_at
            or epic_framework_state.plot_outline
            or epic_framework_state.epic_volumes_detail
        ):
            logger.info(f"   ✅ 未找到项目设置，返回空状态")
            return {
                "has_framework": False,
                "total_volumes": 0,
                "expanded_volumes": [],
                "framework_generated_at": None
            }
        
        epic_framework = epic_framework_state.epic_framework
        framework_generated_at = epic_framework_state.framework_generated_at
        plot_outline = epic_framework_state.plot_outline or ""
        epic_volumes_detail_json = epic_framework_state.epic_volumes_detail or ""
        
        # 🌟 新架构：使用 parse_epic_volumes_json 和 get_volume_state
        from app.services.outline_merger import parse_epic_volumes_json, get_volume_state
        
        # 解析卷数据
        volumes_data = parse_epic_volumes_json(epic_volumes_detail_json)
        
        # 如果新架构有数据，直接使用
        if volumes_data.get("volumes"):
            state = get_volume_state(volumes_data)
            logger.info(f"   ✅ 新架构状态: has_framework={state['hasFramework']}, total_volumes={state['totalVolumes']}, expanded_volumes={state['expandedVolumes']}")
            return {
                "has_framework": state["hasFramework"],
                "total_volumes": state["totalVolumes"],
                "expanded_volumes": state["expandedVolumes"],
                "framework_generated_at": state["frameworkGeneratedAt"] or framework_generated_at
            }
        
        # 🔄 回退：老结构或空数据，使用原有逻辑
        import re
        has_framework = bool(framework_generated_at) or bool(epic_framework and len(epic_framework) > 100)
        
        total_volumes = 0
        yaml_match = re.search(r'总卷数:\s*(\d+)', plot_outline)
        if yaml_match:
            total_volumes = int(yaml_match.group(1))
        else:
            vol_matches = re.findall(r'第\s*(\d+)\s*卷', plot_outline or epic_framework or '')
            if vol_matches:
                total_volumes = max(int(v) for v in vol_matches)
        
        # 老格式兼容：从旧JSON读取已扩展卷
        from app.services.outline_merger import parse_volumes_detail_json
        expanded_volumes = []
        if epic_volumes_detail_json:
            try:
                volumes_dict = parse_volumes_detail_json(epic_volumes_detail_json)
                expanded_volumes = sorted(volumes_dict.keys())
            except Exception as e:
                logger.warning(f"   ⚠️  解析 epic_volumes_detail 失败: {e}")
        
        logger.info(f"   ✅ 框架状态(回退): has_framework={has_framework}, total_volumes={total_volumes}, expanded_volumes={expanded_volumes}")
        
        return {
            "has_framework": has_framework,
            "total_volumes": total_volumes,
            "expanded_volumes": expanded_volumes,
            "framework_generated_at": framework_generated_at
        }
        
    except Exception as e:
        logger.error(f"❌ 检测框架状态失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/expand-story/analysis", response_model=StoryExpansionAnalysisRouteResponse)
async def analyze_expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分析协同扩展请求，返回推荐方向、模式和模型适配信息。"""
    try:
        _validate_expand_story_request(request, allow_empty_targets_for_analysis=True)

        _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        request = _normalize_story_request_text_fields(request)
        preview = _build_story_written_chapter_preview(request, db)
        analysis_request = request.model_copy(
            update={
                "current_outline": preview["effective_outline"],
                "current_chapter_count": preview["effective_current_chapter_count"],
            }
        )
        analysis_bundle = _build_story_expansion_analysis(
            request=analysis_request,
            db=db,
        )
        analysis = dict(analysis_bundle["analysis"])
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(preview.get("warnings") or [])
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = {
            "applied": bool(preview.get("applied")),
            "written_chapter_count": int(preview.get("written_chapter_count") or 0),
            "preserve_written_mode": request.preserve_written_mode,
        }

        response_payload = StoryExpansionAnalysisRouteResponse.model_validate(
            {
                "success": True,
                "analysis": StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
                    mode="python",
                    exclude_none=True,
                ),
            }
        )
        return response_payload.model_dump(mode="python", exclude_none=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 协同扩展预检分析失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/expand-story", response_model=StoryExpansionStartResponse)
async def expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """协同拓展大纲与人物，采用真正的 delta 策略异步执行。"""
    try:
        _validate_expand_story_request(request)

        _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        task_id = f"expand-story-{uuid.uuid4()}"

        _create_story_expansion_history_record(
            db,
            project_id=request.project_id,
            task_id=task_id,
        )

        _enqueue_story_expansion_task(
            task_id=task_id,
            request=request,
            user_id=current_user.id,
        )

        response_payload = StoryExpansionStartResponse.model_validate(
            _build_task_start_response(
                task_id=task_id,
                message="协同拓展任务已启动，正在后台分析人物与大纲的增量缺口...",
            )
        )
        return response_payload.model_dump(mode="python", exclude_none=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 启动协同拓展任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def execute_expand_story_task(
    task_id: str,
    project_id: int,
    user_id: int,
    current_outline: str,
    world_setting: str,
    characters: str,
    current_chapter_count: int,
    current_character_count: int,
    target_total_chapters: Optional[int],
    target_total_characters: Optional[int],
    strategy: str,
    intent: str,
    enable_auto_supplement: bool,
    expansion_mode: str,
    total_volumes: Optional[int],
    total_chapters_min: Optional[int],
    total_chapters_max: Optional[int],
    target_volume_index: Optional[int],
    volume_chapters_min: Optional[int],
    volume_chapters_max: Optional[int],
    preserve_written_mode: str,
    volume_character_increment: Optional[int] = None,
    reset_epic_framework: bool = False,
):
    """后台执行协同拓展任务。"""
    from app.db.base import SessionLocal

    logger.info(f"🚀 开始执行后台任务: {task_id}, 协同拓展")
    db = SessionLocal()

    try:
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message="🧭 开始分析大纲与人物的协同缺口...",
        )

        prepared_request_bundle = await _prepare_story_execution_request(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
                reset_epic_framework=reset_epic_framework,
            ),
            db,
        )
        prepared_request = prepared_request_bundle["request"]
        _validate_story_framework_mode_switch(prepared_request, db)
        execution_context_warnings = list(prepared_request_bundle.get("warnings") or [])
        written_chapter_context = {
            "applied": bool(prepared_request_bundle.get("applied")),
            "written_chapter_count": int(prepared_request_bundle.get("written_chapter_count") or 0),
            "preserve_written_mode": preserve_written_mode,
        }

        analysis_bundle = _build_story_expansion_analysis(
            request=prepared_request,
            db=db,
        )
        coordinator = analysis_bundle["coordinator"]
        combined_world_setting = analysis_bundle["combined_world_setting"]
        analysis = analysis_bundle["analysis"]
        volume_detail_config = analysis_bundle.get("volume_detail_config")
        effective_target_total_chapters = analysis.get("effective_target_chapter_count")
        effective_target_total_characters = analysis.get("effective_target_character_count")
        effective_strategy = analysis.get("effective_strategy") or strategy
        effective_intent = analysis.get("effective_intent") or intent
        effective_expansion_mode = analysis.get("effective_expansion_mode") or expansion_mode
        epic_config = analysis.get("epic_config") or _resolve_story_epic_config(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
            )
        )
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(execution_context_warnings)
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = written_chapter_context
        analysis = StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
            mode="python",
            exclude_none=True,
        )
        auto_supplement_plan = (
            analysis.get("auto_supplement")
            if enable_auto_supplement and prepared_request.target_total_characters is None
            else None
        )

        mode_info = {
            "mode": analysis.get("execution_mode", "delta"),
            "reason": analysis.get("execution_mode_reason", ""),
        }
        mode_messages = {
            "delta": "🧠 正在生成单轮协同 delta 计划...",
            "iterative": "🧠 正在编排分轮协同扩展计划...",
            "epic": "🧠 正在规划长篇框架优先的协同扩展...",
            "volume_detail": "🧠 正在编排单卷细化协同计划...",
        }

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=18,
            message=mode_messages.get(mode_info.get("mode", "delta"), "🧠 正在生成协同扩展计划..."),
        )

        result = await asyncio.to_thread(
            coordinator.execute,
            current_outline=prepared_request.current_outline,
            characters=characters,
            world_setting=combined_world_setting,
            target_total_chapters=effective_target_total_chapters,
            target_total_characters=effective_target_total_characters,
            strategy=effective_strategy,
            expansion_mode=effective_expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
            auto_supplement_plan=auto_supplement_plan,
        )

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=72,
            message="💾 正在保存协同拓展结果...",
        )

        workflow_context_builder = WorkflowContextBuilder(db)
        update_fields = {
            "plot_outline": result["plot_outline"],
            "characters": result["characters"],
        }
        if result.get("execution_mode") == "epic" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                    "epic_framework_generated_at": utc_now().isoformat(),
                }
            )
        elif result.get("execution_mode") == "volume_detail" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                }
            )
        elif reset_epic_framework:
            update_fields.update(
                {
                    "epic_framework": None,
                    "epic_volumes_detail": None,
                    "epic_framework_generated_at": None,
                }
            )

        workflow_context_builder.update_project_settings_fields(project_id, **update_fields)

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=84,
            message="👥 正在同步人物卡与关系...",
        )

        sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
        relationship_result = {"parsed": 0, "saved": 0, "characters_updated": 0}

        try:
            from app.services.character_parser import (
                parse_and_sync_characters,
                parse_and_sync_relationships,
            )

            character_sync_text, character_sync_source = _select_story_character_sync_source(result)
            if character_sync_text:
                sync_result = parse_and_sync_characters(
                    project_id=project_id,
                    characters_text=character_sync_text,
                    db_session=db,
                )
                logger.info(
                    "✅ 协同拓展人物卡同步完成：project_id=%s, source=%s, parsed=%s, created=%s, updated=%s",
                    project_id,
                    character_sync_source,
                    sync_result.get("parsed", 0),
                    sync_result.get("created", 0),
                    sync_result.get("updated", 0),
                )
            else:
                logger.info(
                    "ℹ️ 协同拓展未检测到可解析人物卡，跳过同步：project_id=%s",
                    project_id,
                )

            if result.get("character_relationships"):
                relationship_result = parse_and_sync_relationships(
                    project_id=project_id,
                    relationships_text=result["character_relationships"],
                    db_session=db,
                )
                sync_result["relationships"] = relationship_result
        except Exception as sync_error:
            logger.warning(f"⚠️ 协同拓展后同步人物失败: {sync_error}")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=92,
            message="📚 正在同步向量库...",
        )

        try:
            from app.models.character import Character
            from app.services.vector_sync import sync_to_vector_db, upsert_character_to_vector_db

            if result["plot_outline"]:
                sync_to_vector_db(
                    kb_type="plot",
                    name=f"project_{project_id}_plot_outline",
                    content=result["plot_outline"],
                    metadata={
                        "project_id": str(project_id),
                        "type": "plot_outline",
                    },
                )

            characters_in_db = db.query(Character).filter(Character.project_id == project_id).all()
            for char in characters_in_db:
                char_content = f"""
人物名称: {char.name}
故事立场: {char.role or '未设定'}
角色定位: {getattr(char, 'role_position', None) or '未设定'}
所属势力: {char.faction or '未设定'}
状态: {char.life_status or '未知'}
简介: {char.summary or ''}
详细信息: {char.profile or ''}
""".strip()
                upsert_character_to_vector_db(
                    character_id=char.id,
                    character_name=char.name,
                    content=char_content,
                    project_id=project_id,
                    metadata={
                        "character_id": str(char.id),
                        "name": char.name,
                        "role": char.role or "",
                        "role_position": getattr(char, "role_position", None) or "",
                    },
                )
        except Exception as vector_error:
            logger.warning(f"⚠️ 协同拓展后同步向量库失败: {vector_error}")

        before_stats = result.get("validation_before") or {}
        after_stats = result.get("validation_after") or {}
        final_chapter_count = _resolve_story_result_count(
            reported_count=result.get("current_chapter_count"),
            parsed_count=_estimate_chapter_count_from_text(result.get("plot_outline", "")),
            validation_count=after_stats.get("chapter_count"),
            fallback_count=prepared_request.current_chapter_count,
        )
        final_character_count = _resolve_story_result_count(
            reported_count=result.get("current_character_count"),
            parsed_count=_estimate_character_count_from_text(result.get("characters", "")),
            validation_count=after_stats.get("character_count"),
            fallback_count=current_character_count,
        )
        normalized_character_sync, character_sync_warnings = _normalize_story_character_sync_result(sync_result)
        alignment_warnings = list(result.get("alignment_warnings", []))
        alignment_warnings.extend(character_sync_warnings)
        alignment_warnings = list(dict.fromkeys(str(item).strip() for item in alignment_warnings if str(item).strip()))
        result_plan = result.get("plan") or {}

        task_result_payload = StoryExpansionTaskResultResponse.model_validate(
            {
                "expanded_outline": result["plot_outline"],
                "all_characters": result["characters"],
                "outline_delta": result.get("outline_delta", ""),
                "character_delta": result.get("character_delta", ""),
                "character_relationships": result.get("character_relationships", ""),
                "outline_ops": _normalize_story_result_outline_ops(result),
                "execution_mode": result.get("execution_mode", mode_info.get("mode", "delta")),
                "execution_mode_reason": result.get("execution_mode_reason", mode_info.get("reason", "")),
                "execution_rounds": result.get("execution_rounds", []),
                "new_characters": result.get("new_characters", []),
                "alignment_repairs": result.get("alignment_repairs", []),
                "story_strategy": result.get("strategy", effective_strategy),
                "story_intent": effective_intent,
                "story_expansion_mode": effective_expansion_mode,
                "story_preserve_written_mode": preserve_written_mode,
                "written_chapter_context": written_chapter_context,
                "volume_index": result.get("volume_index"),
                "volume_chapter_range": result.get("volume_chapter_range"),
                "coordination_summary": result.get("coordination_summary", ""),
                "current_chapter_count": final_chapter_count,
                "target_chapter_count": (
                    result_plan.get("target_chapter_count")
                    or effective_target_total_chapters
                    or target_total_chapters
                    or final_chapter_count
                ),
                "current_character_count": final_character_count,
                "target_character_count": (
                    result_plan.get("target_character_count")
                    or effective_target_total_characters
                    or target_total_characters
                    or final_character_count
                ),
                "validation_before": before_stats,
                "validation_after": after_stats,
                "alignment_warnings": alignment_warnings,
                "character_sync": normalized_character_sync,
                "stop_reasons": result.get("stop_reasons", []),
                "expansion_analysis": analysis,
                "epic_total_volumes": result.get("epic_total_volumes"),
                "epic_chapter_range": result.get("epic_chapter_range"),
                "message": (
                    f"✅ 协同拓展完成！章节 {before_stats.get('chapter_count', prepared_request.current_chapter_count)}"
                    f" → {final_chapter_count}，人物 {before_stats.get('character_count', current_character_count)}"
                    f" → {final_character_count}"
                ),
            }
        ).model_dump(mode="python", exclude_none=True)

        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="completed",
            result=task_result_payload,
        )
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result=task_result_payload,
        )

    except Exception as e:
        logger.error(f"❌ 后台协同拓展失败: {str(e)}")
        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="failed",
            error=str(e),
        )
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e),
        )
    finally:
        db.close()


@router.post("/optimize-chapter")
async def optimize_chapter(
    request: dict,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    再次优化章节：对当前章节再进行一轮迭代优化
    
    请求体：
    {
        "project_id": 1,
        "chapter_id": 10,
        "current_content": "当前章节内容..."
    }
    
    返回：
    {
        "task_id": "optimize_xxx",
        "message": "优化任务已提交"
    }
    """
    import uuid
    import logging
    
    logger = logging.getLogger(__name__)
    
    project_id = request.get("project_id")
    chapter_id = request.get("chapter_id")
    current_content = request.get("current_content", "")
    user_feedback = request.get("user_feedback", "")  # 🆕 用户额外意见
    
    if not project_id or not chapter_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 project_id 或 chapter_id"
        )
    
    # 验证项目所有权
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    
    # 验证章节存在
    chapter = db.query(Chapter).filter(
        (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )
    
    # 生成任务ID
    task_id = f"optimize_{uuid.uuid4().hex[:8]}"
    
    # 创建任务记录（使用 generation_history 表）
    insert_query = text("""
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
    """)
    
    db.execute(insert_query, {
        "project_id": project_id,
        "task_type": "optimize_chapter",
        "task_id": task_id,
        "status": "running",
        "created_at": utc_now().isoformat()
    })
    db.commit()
    logger.info(f"✅ 任务记录已创建: {task_id}")
    
    # 使用线程异步执行优化（FastAPI的BackgroundTasks不支持async函数）
    import threading
    thread = threading.Thread(
        target=lambda: asyncio.run(
            _optimize_chapter_task(
                task_id=task_id,
                project_id=project_id,
                chapter_id=chapter_id,
                current_content=current_content,
                user_feedback=user_feedback,
            )
        ),
        daemon=True
    )
    thread.start()
    logger.info(f"🚀 [{task_id}] 优化线程已启动")
    
    return {
        "task_id": task_id,
        "message": "优化任务已提交"
    }

def _safe_db_rollback(db: Session, reason: Optional[str] = None) -> None:
    try:
        db.rollback()
    except Exception as rollback_error:
        if reason:
            logger.warning(f"⚠️ 数据库回滚失败（{reason}）: {rollback_error}")
        else:
            logger.warning(f"⚠️ 数据库回滚失败: {rollback_error}")


def _create_generated_chapter(
    db: Session,
    *,
    project_id: int,
    chapter_number: int,
    title: str,
    content: str,
) -> Chapter:
    chapter = Chapter(
        project_id=project_id,
        chapter_number=chapter_number,
        title=title,
        content=content,
        status="draft",
        word_count=len(content or ""),
    )

    try:
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter
    except Exception:
        _safe_db_rollback(db, "保存生成章节失败")
        raise


def _extract_iteration_review_score(text: str) -> float:
    if not text:
        return 0.0

    patterns = [
        r"综合评分(?:\*\*)?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10",
        r"\*\*?\s*综合评分\s*\*\*?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10",
        r"综合评分[^0-9\n]{0,12}([0-9]+(?:\.[0-9]+)?)\s*分",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            continue

    return 0.0


def _load_latest_chapter_plan(db: Session, *, project_id: int, chapter_id: int) -> str:
    query = text("""
        SELECT content
        FROM chapter_plans
        WHERE project_id = :project_id AND chapter_id = :chapter_id
        ORDER BY id DESC
        LIMIT 1
    """)
    plan_result = db.execute(query, {
        "project_id": project_id,
        "chapter_id": chapter_id,
    }).fetchone()

    if not plan_result or not plan_result[0]:
        return ""

    return plan_result[0]


def _load_project_chapter_context(db: Session, *, project_id: int) -> Dict[str, str]:
    workflow_context_builder = WorkflowContextBuilder(db)
    project_profile = workflow_context_builder.get_project_profile(project_id)
    stage_context = workflow_context_builder.load_stage_text_context(project_id)
    outline = (stage_context.plot_outline or "").strip() or (project_profile.user_outline_plan or "").strip()

    return {
        "genre": project_profile.genre or "",
        "outline": outline,
        "world_setting": stage_context.world_setting or "",
        "characters": stage_context.characters or "",
    }


async def _optimize_chapter_task(
    task_id: str,
    project_id: int,
    chapter_id: int,
    current_content: str,
    user_feedback: str = "",  # 🆕 用户额外意见
):
    """
    异步执行章节优化任务
    """
    from app.services.agents.agents import QualityReviewerAgent, ContentCreatorAgent
    from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts
    from sqlalchemy import text
    import logging
    
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    
    try:
        # 更新任务状态：开始优化
        update_query = text("""
            UPDATE generation_history
            SET status = :status, progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "message": "🔄 开始优化章节...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"🔄 [{task_id}] 开始优化章节...")
        
        # 获取项目信息
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise Exception("项目不存在")
        
        # 获取章节信息
        chapter = db.query(Chapter).filter(
            (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
        ).first()
        if not chapter:
            raise Exception("章节不存在")
        
        # 获取章节计划（可选）
        chapter_plan = ""
        try:
            chapter_plan = _load_latest_chapter_plan(
                db,
                project_id=project_id,
                chapter_id=chapter.id,
            )
        except Exception as e:
            _safe_db_rollback(db, "加载章节计划失败")
            logger.warning(f"获取章节计划失败: {e}，将继续执行")
        
        # 获取项目题材
        genre = ""
        try:
            project_context = _load_project_chapter_context(db, project_id=project_id)
            genre = project_context["genre"]
        except Exception as e:
            _safe_db_rollback(db, "加载项目上下文失败")
            logger.warning(f"获取项目题材失败: {e}")
        
        # 📝 步骤1：质量评审
        update_query = text("""
            UPDATE generation_history
            SET progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 20,
            "message": "📝 正在评审章节质量...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"📝 [{task_id}] 开始评审章节质量...")
        
        # 使用QualityReviewerAgent进行评审
        review_agent = QualityReviewerAgent()
        
        # 构造评审提示词
        review_prompt = f"""请对以下章节内容进行详细的质量评审：

【章节信息】
- 章节号：第{chapter.chapter_number}章
- 题材：{genre or '通用'}

【章节计划】
{chapter_plan}

【章节内容】
{current_content}

---

请按照以下维度进行评估，每个维度给出1-10分的评分：
1. 故事性：情节紧凑度、冲突设置、节奏把控
2. 人物塑造：人物立体度、性格一致性、成长弧光
3. 语言表达：语言流畅度、修辞手法、风格独特性、画面感
4. 结构完整性：情节连贯性、逻辑合理性、章节衔接
5. 创新性：设定新颖性、情节原创性、视角独特性

请提供：
1. 每个维度的评分和反馈
2. 主要优点（至少3个）
3. 主要缺点（至少3个）
4. 改进建议（至少5个）
5. 综合评分（加权平均）
"""
        
        review_report = review_agent.process(review_prompt)
        
        # 解析评分
        import re
        score_match = re.search(r'综合评分[:\uff1a]\s*(\d+(?:\.\d+)?)', review_report)
        current_score = float(score_match.group(1)) if score_match else 0.0
        
        logger.info(f"📊 当前章节评分: {current_score}")
        
        # 🔧 步骤2：迭代优化
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 50,
            "message": f"🔧 正在优化章节（当前评分: {current_score}）...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"🔧 [{task_id}] 开始优化章节...")
        
        # 使用ContentCreatorAgent进行改稿（但需要明确指示修改而非重写）
        content_agent = ContentCreatorAgent()
        
        # 构造改稿提示词（强调修改而非重写）
        user_feedback_section = ""
        if user_feedback and user_feedback.strip():
            user_feedback_section = f"""

【用户额外意见】
{user_feedback.strip()}
"""
        
        revision_prompt = f"""你是一位网络小说修改专家，请根据评审意见**修改**以下章节内容。

⚠️ **重要：你的任务是修改和优化现有内容，而不是重新创作或编写全新的章节。**

修改原则：
1. 保持原有故事线和主要情节不变
2. 保留原文中的精彩描写和对话
3. 根据评审意见针对性地修改问题部分
4. 不要添加新的人物、地点或大型情节

【章节信息】
- 章节号：第{chapter.chapter_number}章
- 题材：{genre or '通用'}

【系统评审意见】
{review_report}{user_feedback_section}

【当前章节内容（需要修改的原文）】
{current_content}

---

请仔细阅读以上原文和评审意见，然后：
1. 找出需要改进的具体位置
2. 在保持整体结构和故事线的基础上，针对性地修改这些问题
3. 直接输出修改后的完整章节内容

注意：不要输出任何解释性文字，直接输出修改后的章节正文。
"""
        
        # 选择模型（根据内容长度）
        def estimate_tokens(text: str) -> int:
            return _estimate_tokens_by_chars(text)
        
        total_tokens = estimate_tokens(current_content) + estimate_tokens(review_report) + 500
        model_name, max_safe_limit = _select_text_model_by_input_tokens(total_tokens)
        
        logger.info(f"🤖 使用模型: {model_name} (预计tokens: {total_tokens}, qwen3-max安全预算: {max_safe_limit})")
        
        # 执行改稿（使用较低temperature保持原文结构）
        optimized_content = content_agent.process(
            revision_prompt,
            temperature=0.3  # 使用低temperature保持忠于原文，避免过度创作
        )
        
        if not optimized_content:
            raise Exception("优化结果为空")
        
        # 完成 - 更新进度
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 100,
            "message": "✅ 章节优化完成",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"✅ [{task_id}] 章节优化完成")
        
        # 更新任务状态为完成，并存储结果
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                result = :result,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        import json
        db.execute(update_query, {
            "task_id": task_id,
            "status": "completed",
            "result": json.dumps({
                "optimized_content": optimized_content,
                "original_score": current_score,
                "review_report": review_report,
            }, ensure_ascii=False),
            "completed_at": utc_now().isoformat()
        })
        db.commit()
        
        logger.info(f"✅ 章节优化任务完成: {task_id}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"❌ 章节优化任务失败: {e}")
        _safe_db_rollback(db, "章节优化任务异常")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                error = :error,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        try:
            db.execute(update_query, {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat()
            })
            db.commit()
        except Exception as status_error:
            _safe_db_rollback(db, "写入章节优化失败状态")
            logger.error(f"❌ 写入章节优化失败状态失败: {status_error}")
    finally:
        db.close()


@router.post("/regenerate-chapter")
async def regenerate_chapter(
    request: dict,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    重新生成章节：完全重新创作指定章节的内容
    
    请求体：
    {
        "project_id": 1,
        "chapter_id": 10,
        "user_feedback": "用户反馈意见（可选）"
    }
    
    返回：
    {
        "task_id": "regenerate_xxx",
        "message": "重新生成任务已提交"
    }
    """
    import uuid
    import logging
    
    logger = logging.getLogger(__name__)
    
    project_id = request.get("project_id")
    chapter_id = request.get("chapter_id")
    user_feedback = request.get("user_feedback", "")
    
    if not project_id or not chapter_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 project_id 或 chapter_id"
        )
    
    # 验证项目所有权
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    
    # 验证章节存在
    chapter = db.query(Chapter).filter(
        (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )
    
    # 生成任务ID
    task_id = f"regenerate_{uuid.uuid4().hex[:8]}"
    
    # 创建任务记录
    insert_query = text("""
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
    """)
    
    db.execute(insert_query, {
        "project_id": project_id,
        "task_type": "regenerate_chapter",
        "task_id": task_id,
        "status": "running",
        "created_at": utc_now().isoformat()
    })
    db.commit()
    logger.info(f"✅ 重新生成任务记录已创建: {task_id}")
    
    # 使用线程异步执行重新生成
    import threading
    thread = threading.Thread(
        target=lambda: asyncio.run(
            _regenerate_chapter_task(
                task_id=task_id,
                project_id=project_id,
                chapter_id=chapter_id,
                user_feedback=user_feedback,
            )
        ),
        daemon=True
    )
    thread.start()
    logger.info(f"🚀 [{task_id}] 重新生成线程已启动")
    
    return {
        "task_id": task_id,
        "message": "重新生成任务已提交"
    }


async def _regenerate_chapter_task(
    task_id: str,
    project_id: int,
    chapter_id: int,
    user_feedback: str = "",
):
    """
    异步执行章节重新生成任务
    """
    from app.services.agents.agents import ContentCreatorAgent
    from sqlalchemy import text
    import logging
    
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    
    try:
        # 更新任务状态：开始生成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "message": "🔄 开始重新生成章节...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"🔄 [{task_id}] 开始重新生成章节...")
        
        # 获取项目信息
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise Exception("项目不存在")
        
        # 获取章节信息
        chapter = db.query(Chapter).filter(
            (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
        ).first()
        if not chapter:
            raise Exception("章节不存在")
        
        # 获取章节计划
        chapter_plan = ""
        try:
            chapter_plan = _load_latest_chapter_plan(
                db,
                project_id=project_id,
                chapter_id=chapter.id,
            )
        except Exception as e:
            _safe_db_rollback(db, "加载章节计划失败")
            logger.warning(f"获取章节计划失败: {e}，将继续执行")
        
        outline = ""
        genre = ""
        world_setting = ""
        characters = ""
        try:
            project_context = _load_project_chapter_context(db, project_id=project_id)
            outline = project_context["outline"]
            genre = project_context["genre"]
            world_setting = project_context["world_setting"]
            characters = project_context["characters"]
        except Exception as e:
            _safe_db_rollback(db, "加载项目上下文失败")
            logger.warning(f"获取项目设定失败: {e}")
        
        # 更新进度：准备生成
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 20,
            "message": "📝 正在准备生成章节...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        
        # 构建章节信息
        chapter_info = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "outline": chapter_plan or outline,
            "main_characters": [],  # 可以从character_designer中解析
            "setting": world_setting,
            "project_genre": genre,
            "world_builder": world_setting,
            "character_designer": characters,
            "characters": characters,
            "user_feedback": user_feedback
        }
        
        # 更新进度：生成中
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 50,
            "message": "✍️ 正在生成章节内容...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        
        # 使用ContentCreatorAgent重新生成章节
        content_agent = ContentCreatorAgent()
        content_agent.set_project_context(project_id)
        
        result = content_agent.create_chapter(chapter_info)
        new_content = result.get("content", "")
        
        if not new_content:
            raise Exception("生成内容为空")
        
        # 更新进度：保存中
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 80,
            "message": "💾 正在保存章节内容...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        
        # 更新章节内容
        chapter.content = new_content
        chapter.updated_at = utc_now()
        db.commit()
        
        # 完成 - 更新进度
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 100,
            "message": "✅ 章节重新生成完成",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"✅ [{task_id}] 章节重新生成完成")
        
        # 更新任务状态为完成，并存储结果
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                result = :result,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        import json
        db.execute(update_query, {
            "task_id": task_id,
            "status": "completed",
            "result": json.dumps({
                "regenerated_content": new_content,
                "consistency_analysis": result.get("consistency_analysis", {}),
                "optimization_info": result.get("optimization_info", {}),
            }, ensure_ascii=False),
            "completed_at": utc_now().isoformat()
        })
        db.commit()
        
        logger.info(f"✅ 章节重新生成任务完成: {task_id}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"❌ 章节重新生成任务失败: {e}")
        _safe_db_rollback(db, "章节重新生成任务异常")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                error = :error,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        try:
            db.execute(update_query, {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat()
            })
            db.commit()
        except Exception as status_error:
            _safe_db_rollback(db, "写入章节重生成失败状态")
            logger.error(f"❌ 写入章节重生成失败状态失败: {status_error}")
    finally:
        db.close()
