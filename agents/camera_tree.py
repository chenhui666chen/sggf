from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


_SHOT_SIZE_KEYWORDS: List[Tuple[str, int]] = [
    ("extreme close-up", 0),
    ("extreme close up", 0),
    ("close-up", 1),
    ("close up", 1),
    ("medium shot", 3),
    ("wide shot", 4),
    ("long shot", 5),
    ("大特写", 0),
    ("特写", 1),
    ("近景", 2),
    ("中景", 3),
    ("大全景", 5),
    ("远景", 5),
    ("全景", 4),
]


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _extract_shot_size(text: str) -> Tuple[Optional[str], Optional[int]]:
    haystack = (text or "").lower()
    if not haystack:
        return None, None
    for keyword, rank in _SHOT_SIZE_KEYWORDS:
        if keyword.lower() in haystack:
            return keyword, rank
    return None, None


def build_camera_tree(storyboard: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    轻量 camera tree（最小可用版本）：
    - 从 storyboard 的 cam_idx/camera_index 分组，按首次出现顺序得到 camera 节点。
    - parent_cam_idx 采用启发式：优先选择更“宽景”的上一节点（景别 rank 更大），同时尽量靠近时间位置。
    - 保证无环：只允许选择“更早出现”的 camera 作为 parent。
    """
    if not isinstance(storyboard, list) or not storyboard:
        return []

    cameras: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for pos, shot in enumerate(storyboard):
        if not isinstance(shot, dict):
            continue
        cam_idx = _safe_int(shot.get("cam_idx") or shot.get("camera_index") or 0, default=0)
        shot_id = str(shot.get("shot_id") or "").strip()
        if cam_idx in cameras:
            cameras[cam_idx]["shot_positions"].append(pos)
            cameras[cam_idx]["shots"].append({"shot_pos": pos, "shot_id": shot_id})
            continue

        text = " ".join(
            [
                str(shot.get("visual_desc") or ""),
                str(shot.get("ff_desc") or ""),
                str(((shot.get("head_frame") or {}) if isinstance(shot.get("head_frame"), dict) else {}).get("prompt") or ""),
            ]
        ).strip()
        size_label, size_rank = _extract_shot_size(text)
        cameras[cam_idx] = {
            "cam_idx": cam_idx,
            "first_shot_pos": pos,
            "first_shot_id": shot_id,
            "shot_size": size_label,
            "shot_size_rank": size_rank,
            "shot_positions": [pos],
            "shots": [{"shot_pos": pos, "shot_id": shot_id}],
            "parent_cam_idx": None,
            "parent_shot_pos": None,
            "parent_shot_id": None,
            "reason": "",
            "is_parent_fully_covers_child": None,
            "missing_info": None,
        }
        order.append(cam_idx)

    if not order:
        return []

    root_cam_idx = order[0]
    cameras[root_cam_idx]["parent_cam_idx"] = None
    cameras[root_cam_idx]["reason"] = "root"

    def _parent_score(parent: Dict[str, Any], child: Dict[str, Any]) -> Tuple[int, int, int]:
        parent_rank = parent.get("shot_size_rank")
        child_rank = child.get("shot_size_rank")
        if isinstance(parent_rank, int) and isinstance(child_rank, int):
            if parent_rank < child_rank:
                rank_penalty = 1000
            else:
                rank_penalty = int(parent_rank) - int(child_rank)
        else:
            rank_penalty = 50
        time_penalty = abs(int(child["first_shot_pos"]) - int(parent["first_shot_pos"]))
        return rank_penalty, time_penalty, int(parent["first_shot_pos"])

    for cam_idx in order[1:]:
        child = cameras[cam_idx]
        candidates = [cameras[c] for c in order if cameras[c]["first_shot_pos"] < child["first_shot_pos"]]
        if not candidates:
            child["parent_cam_idx"] = root_cam_idx
            child["reason"] = "fallback_root(no_candidates)"
            continue

        best = min(candidates, key=lambda p: _parent_score(p, child))
        penalty, time_delta, _pos = _parent_score(best, child)
        if penalty >= 1000:
            # 没有“更宽景”的可用 parent：退化为“时间上最近的上一 camera”
            prev = max(candidates, key=lambda p: int(p["first_shot_pos"]))
            child["parent_cam_idx"] = int(prev["cam_idx"])
            child["reason"] = "fallback_prev_camera(no_wider_parent)"
            continue

        child["parent_cam_idx"] = int(best["cam_idx"])
        child["reason"] = f"heuristic(rank_penalty={penalty},time_delta={time_delta})"

    # parent_shot_id：选择 parent camera 中“最接近 child 首次出现”的那一条 shot（且必须早于 child）
    for cam_idx in order[1:]:
        child = cameras[cam_idx]
        parent_cam_idx = child.get("parent_cam_idx")
        if not isinstance(parent_cam_idx, int):
            continue
        parent = cameras.get(int(parent_cam_idx))
        if not isinstance(parent, dict):
            continue
        child_pos = int(child.get("first_shot_pos") or 0)
        parent_shots = parent.get("shots") if isinstance(parent.get("shots"), list) else []
        eligible: List[Dict[str, Any]] = []
        for item in parent_shots:
            if not isinstance(item, dict):
                continue
            try:
                ppos = int(item.get("shot_pos"))
            except Exception:  # noqa: BLE001
                continue
            if ppos >= child_pos:
                continue
            eligible.append(item)
        if not eligible:
            continue
        best_shot = max(eligible, key=lambda it: int(it.get("shot_pos") or 0))
        parent_shot_id = str(best_shot.get("shot_id") or "").strip()
        if parent_shot_id:
            child["parent_shot_pos"] = int(best_shot.get("shot_pos") or 0)
            child["parent_shot_id"] = parent_shot_id

    for cam_idx in order:
        cam = cameras[cam_idx]
        shots = cam.get("shots") if isinstance(cam.get("shots"), list) else []
        cam["active_shot_ids"] = [
            str(s.get("shot_id") or "").strip()
            for s in shots
            if isinstance(s, dict) and str(s.get("shot_id") or "").strip()
        ]

    return [cameras[c] for c in order]


def build_camera_tree_llm(
    storyboard: List[Dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int = 90,
    max_shots_per_camera: int = 6,
) -> List[Dict[str, Any]]:
    """
    使用 text-only LLM 生成 camera tree：
    - 仅依赖分镜文本描述（visual_desc/ff_desc/head_frame.prompt），不做图像推理
    - 输出结构会合并到启发式 camera_tree 的节点上（保留 shot_size/shot_positions 等诊断信息）

    说明：
    - 为避免引入额外依赖，LLM 调用复用 `agents.llm_client.chat_completions`（OpenAI-compatible）。
    - 若 LLM 不可用或解析失败，返回空列表（由调用方回退到启发式版本）。
    """
    if not isinstance(storyboard, list) or not storyboard:
        return []
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip()
    model = (model or "").strip()
    if not api_key or not base_url or not model:
        return []

    try:
        max_shots_per_camera = int(max_shots_per_camera)
    except Exception:  # noqa: BLE001
        max_shots_per_camera = 6
    max_shots_per_camera = max(1, min(max_shots_per_camera, 12))

    from agents.llm_client import chat_completions, extract_json_object  # local import: optional dependency

    base_tree = build_camera_tree(storyboard)
    if not base_tree:
        return []

    # shot_id -> shot summary
    shot_by_id: Dict[str, Dict[str, Any]] = {}
    for pos, shot in enumerate(storyboard):
        if not isinstance(shot, dict):
            continue
        sid = str(shot.get("shot_id") or "").strip()
        if not sid:
            continue
        shot_by_id.setdefault(sid, {"shot_pos": pos, "shot": shot})

    def _shot_line(shot_id: str) -> str:
        meta = shot_by_id.get(shot_id) if isinstance(shot_by_id.get(shot_id), dict) else None
        shot_pos = int(meta.get("shot_pos") or 0) if meta else 0
        shot = meta.get("shot") if meta else None
        if not isinstance(shot, dict):
            return f"Shot {shot_id} (pos={shot_pos}): (missing)"
        text = str(shot.get("visual_desc") or shot.get("desc") or "").strip()
        if not text:
            text = str(shot.get("ff_desc") or "").strip()
        if not text and isinstance(shot.get("head_frame"), dict):
            text = str((shot.get("head_frame") or {}).get("prompt") or "").strip()
        text = text.replace("\n", " ").strip()
        if len(text) > 200:
            text = text[:200].rstrip()
        shot_type = str(shot.get("shot_type") or "").strip()
        if shot_type:
            return f"Shot {shot_id} (pos={shot_pos}, type={shot_type}): {text}"
        return f"Shot {shot_id} (pos={shot_pos}): {text}"

    # camera sequence string（按首次出现顺序）
    blocks: List[str] = []
    for cam in base_tree:
        if not isinstance(cam, dict) or not isinstance(cam.get("cam_idx"), int):
            continue
        cam_idx = int(cam["cam_idx"])
        shot_ids = cam.get("active_shot_ids") if isinstance(cam.get("active_shot_ids"), list) else []
        shot_ids = [str(s).strip() for s in shot_ids if isinstance(s, str) and s.strip()]
        lines: List[str] = []
        for sid in shot_ids[:max_shots_per_camera]:
            lines.append(_shot_line(sid))
        if not lines and isinstance(cam.get("first_shot_id"), str) and str(cam.get("first_shot_id") or "").strip():
            lines.append(_shot_line(str(cam.get("first_shot_id"))))
        payload = "\n".join(lines).strip() if lines else "(empty)"
        blocks.append(f"<CAMERA_{cam_idx}>\n{payload}\n</CAMERA_{cam_idx}>")

    camera_seq_str = "\n".join(blocks)

    system = (
        "你是专业的多机位镜头分析助手。\n"
        "任务：基于每个相机对应的镜头描述，构建“相机树”(camera tree)。\n"
        "相机树表示包含关系：parent camera 的某个镜头应尽量覆盖 child camera 的内容（如：全景/中景涵盖近景）。\n"
        "要求：只输出严格 JSON（不要 Markdown/解释）。\n"
        "输出格式：\n"
        "{\n"
        "  \"camera_tree\": [\n"
        "    {\n"
        "      \"cam_idx\": 0,\n"
        "      \"parent_cam_idx\": null,\n"
        "      \"parent_shot_id\": null,\n"
        "      \"reason\": \"root\",\n"
        "      \"is_parent_fully_covers_child\": null,\n"
        "      \"missing_info\": null\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "约束：\n"
        "1) 第一台相机必须是 root（parent_cam_idx=null）；且只能有一个 root。\n"
        "2) parent_cam_idx 必须指向在序列中更早出现的相机，避免循环依赖。\n"
        "3) parent_shot_id 必须属于 parent camera 的镜头列表，并尽量选择“时间上最接近 child 首镜头”的那一条（且必须早于 child 的首镜头）。\n"
        "4) reason 用简短中文说明选择依据；missing_info 如无可填 null。\n"
    )
    user = (
        "<CAMERA_SEQ>\n"
        f"{camera_seq_str}\n"
        "</CAMERA_SEQ>\n\n"
        "仅输出 JSON。"
    )

    content = chat_completions(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout_s=max(10, int(timeout_s)),
    )
    obj = extract_json_object(content)
    items = obj.get("camera_tree") if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        return []

    llm_by_cam: Dict[int, Dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        cam_idx = raw.get("cam_idx")
        if not isinstance(cam_idx, int):
            continue
        llm_by_cam[int(cam_idx)] = raw

    seen: List[int] = []
    out: List[Dict[str, Any]] = []
    for node in base_tree:
        if not isinstance(node, dict) or not isinstance(node.get("cam_idx"), int):
            continue
        cam_idx = int(node["cam_idx"])
        merged = dict(node)
        raw = llm_by_cam.get(cam_idx)
        if isinstance(raw, dict):
            parent_cam = raw.get("parent_cam_idx")
            if parent_cam is None:
                parent_cam_idx = None
            elif isinstance(parent_cam, int):
                parent_cam_idx = int(parent_cam)
            else:
                parent_cam_idx = None

            if not seen:
                merged["parent_cam_idx"] = None
                merged["reason"] = "llm(root)"
            else:
                if isinstance(parent_cam_idx, int) and parent_cam_idx in seen:
                    merged["parent_cam_idx"] = parent_cam_idx
                    merged["reason"] = str(raw.get("reason") or "").strip() or "llm"
                # 否则保持启发式 parent（避免无效/循环依赖）

            # 允许补充覆盖关系信息（可为空）
            if isinstance(raw.get("is_parent_fully_covers_child"), bool):
                merged["is_parent_fully_covers_child"] = bool(raw.get("is_parent_fully_covers_child"))
            missing_info = raw.get("missing_info")
            if isinstance(missing_info, str) and missing_info.strip():
                merged["missing_info"] = missing_info.strip()

            # parent_shot_id：若 LLM 给出且合法则采用，否则由启发式补齐
            parent_shot_id = raw.get("parent_shot_id")
            if isinstance(parent_shot_id, str) and parent_shot_id.strip():
                merged["parent_shot_id"] = parent_shot_id.strip()

        seen.append(cam_idx)
        out.append(merged)

    def _resolve_parent_shot_id(
        parent: Dict[str, Any],
        *,
        child_pos: int,
        preferred_shot_id: Optional[str],
    ) -> Tuple[Optional[int], Optional[str]]:
        parent_shots = parent.get("shots") if isinstance(parent.get("shots"), list) else []
        eligible: List[Tuple[int, str]] = []
        preferred: Optional[Tuple[int, str]] = None
        for item in parent_shots:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("shot_id") or "").strip()
            if not sid:
                continue
            try:
                ppos = int(item.get("shot_pos"))
            except Exception:  # noqa: BLE001
                continue
            if ppos >= int(child_pos):
                continue
            eligible.append((ppos, sid))
            if preferred is None and preferred_shot_id and sid == preferred_shot_id:
                preferred = (ppos, sid)
        if preferred is not None:
            return preferred
        if not eligible:
            return None, None
        return max(eligible, key=lambda it: it[0])

    # 兜底：确保 parent_shot_id 与 parent_cam_idx 一致；若缺失/无效则按启发式补齐（取 parent 中最接近 child 的前序镜头）
    camera_map: Dict[int, Dict[str, Any]] = {int(c.get("cam_idx")): c for c in out if isinstance(c, dict) and isinstance(c.get("cam_idx"), int)}
    for cam_idx in seen[1:]:
        cam = camera_map.get(int(cam_idx))
        if not isinstance(cam, dict):
            continue
        parent_cam_idx = cam.get("parent_cam_idx")
        if not isinstance(parent_cam_idx, int):
            cam["parent_shot_pos"] = None
            cam["parent_shot_id"] = None
            continue
        parent = camera_map.get(int(parent_cam_idx))
        if not isinstance(parent, dict):
            continue
        child_pos = int(cam.get("first_shot_pos") or 0)
        preferred_shot_id = str(cam.get("parent_shot_id") or "").strip() if isinstance(cam.get("parent_shot_id"), str) else None
        ppos, psid = _resolve_parent_shot_id(parent, child_pos=child_pos, preferred_shot_id=preferred_shot_id)
        cam["parent_shot_pos"] = int(ppos) if isinstance(ppos, int) else None
        cam["parent_shot_id"] = psid if isinstance(psid, str) and psid.strip() else None

    return out


def build_camera_parent_map(camera_tree: List[Dict[str, Any]]) -> Dict[int, Optional[int]]:
    parent_map: Dict[int, Optional[int]] = {}
    for node in camera_tree or []:
        if not isinstance(node, dict):
            continue
        cam_idx = node.get("cam_idx")
        if not isinstance(cam_idx, int):
            continue
        parent = node.get("parent_cam_idx")
        parent_map[int(cam_idx)] = int(parent) if isinstance(parent, int) else None
    return parent_map
