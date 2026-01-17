from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s:
            continue
        if s in out:
            continue
        out.append(s)
        if len(out) >= 200:
            break
    return out


def build_camera_states(
    storyboard: List[Dict[str, Any]],
    camera_tree: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    将 storyboard 聚合为“相机轨迹 State”：
    - 每个 State 对应一个镜头（shot），按 storyboard 顺序进入相机轨迹；
    - 可选吸收 camera_tree 的 parent_cam_idx/parent_shot_id，便于后续“首 state 生成场景 + 依赖定位”。
    """
    if not isinstance(storyboard, list) or not storyboard:
        return []

    parent_by_cam: Dict[int, Dict[str, Any]] = {}
    tree_order: List[int] = []
    if isinstance(camera_tree, list) and camera_tree:
        for node in camera_tree:
            if not isinstance(node, dict) or not isinstance(node.get("cam_idx"), int):
                continue
            cam_idx = int(node["cam_idx"])
            if cam_idx in parent_by_cam:
                continue
            parent_by_cam[cam_idx] = node
            tree_order.append(cam_idx)

    parent_cam_idx_by_cam: Dict[int, Optional[int]] = {}
    tree_parent_shot_id_by_cam: Dict[int, Optional[str]] = {}
    tree_missing_info_by_cam: Dict[int, Optional[str]] = {}
    for cam_idx, node in parent_by_cam.items():
        parent_cam_idx = node.get("parent_cam_idx")
        parent_cam_idx_by_cam[cam_idx] = int(parent_cam_idx) if isinstance(parent_cam_idx, int) else None
        parent_shot_id = node.get("parent_shot_id")
        tree_parent_shot_id_by_cam[cam_idx] = (
            str(parent_shot_id).strip() if isinstance(parent_shot_id, str) and parent_shot_id.strip() else None
        )
        missing_info = node.get("missing_info")
        tree_missing_info_by_cam[cam_idx] = (
            str(missing_info).replace("\n", " ").strip() if isinstance(missing_info, str) and missing_info.strip() else None
        )

    shot_pos_by_id: Dict[str, int] = {}
    shot_cam_idx_by_id: Dict[str, int] = {}
    for pos, shot in enumerate(storyboard):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id or shot_id in shot_pos_by_id:
            continue
        shot_pos_by_id[shot_id] = int(pos)
        shot_cam_idx_by_id[shot_id] = _safe_int(shot.get("cam_idx") or shot.get("camera_index") or 0, default=0)

    order: List[int] = []
    states_by_cam: Dict[int, List[Dict[str, Any]]] = {}
    last_shot_by_cam: Dict[int, str] = {}
    prev_shot_id: Optional[str] = None
    for pos, shot in enumerate(storyboard):
        if not isinstance(shot, dict):
            continue
        cam_idx = _safe_int(shot.get("cam_idx") or shot.get("camera_index") or 0, default=0)
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            continue

        if cam_idx not in states_by_cam:
            states_by_cam[cam_idx] = []
            order.append(cam_idx)

        camera_anchor = last_shot_by_cam.get(int(cam_idx))
        parent_cam_idx = parent_cam_idx_by_cam.get(int(cam_idx))
        parent_anchor = last_shot_by_cam.get(int(parent_cam_idx)) if isinstance(parent_cam_idx, int) else None
        tree_parent_shot_id = tree_parent_shot_id_by_cam.get(int(cam_idx))
        tree_parent_pos = shot_pos_by_id.get(tree_parent_shot_id) if isinstance(tree_parent_shot_id, str) else None
        anchor_shot_id: Optional[str] = None
        anchor_source = "none"
        if isinstance(camera_anchor, str) and camera_anchor.strip():
            anchor_shot_id = camera_anchor.strip()
            anchor_source = "camera_last_tail"
        elif (
            isinstance(parent_cam_idx, int)
            and isinstance(tree_parent_shot_id, str)
            and tree_parent_shot_id.strip()
            and isinstance(tree_parent_pos, int)
            and int(tree_parent_pos) < int(pos)
            and shot_cam_idx_by_id.get(tree_parent_shot_id.strip()) == int(parent_cam_idx)
        ):
            anchor_shot_id = tree_parent_shot_id.strip()
            anchor_source = "camera_tree_parent_shot"
        elif isinstance(parent_anchor, str) and parent_anchor.strip():
            anchor_shot_id = parent_anchor.strip()
            anchor_source = "parent_camera_tail"
        elif isinstance(prev_shot_id, str) and prev_shot_id.strip():
            anchor_shot_id = prev_shot_id.strip()
            anchor_source = "previous_shot_tail"

        depends_on: List[str] = []
        if isinstance(anchor_shot_id, str) and anchor_shot_id.strip():
            depends_on.append(anchor_shot_id.strip())

        state: Dict[str, Any] = {
            "state_id": shot_id,
            "shot_id": shot_id,
            "shot_pos": int(pos),
            "cam_idx": int(cam_idx),
            "anchor_shot_id": anchor_shot_id,
            "anchor_source": anchor_source,
            "depends_on_state_ids": depends_on,
            "missing_info": tree_missing_info_by_cam.get(int(cam_idx)),
        }
        scene_id = shot.get("scene_id")
        if isinstance(scene_id, str) and scene_id.strip():
            state["scene_id"] = scene_id.strip()
        for key in ("desc", "visual_desc", "ff_desc", "lf_desc", "state_before", "state_after"):
            val = shot.get(key)
            if isinstance(val, str) and val.strip():
                state[key] = val.strip()

        ff_vis = _as_str_list(shot.get("ff_vis_char_ids"))
        lf_vis = _as_str_list(shot.get("lf_vis_char_ids"))
        if ff_vis:
            state["ff_vis_char_ids"] = ff_vis
        if lf_vis:
            state["lf_vis_char_ids"] = lf_vis

        variation_type = str(shot.get("variation_type") or "").strip().lower()
        if variation_type in {"small", "medium", "large"}:
            state["variation_type"] = variation_type
            reason = str(shot.get("variation_reason") or "").replace("\n", " ").strip()
            if reason:
                state["variation_reason"] = reason

        states_by_cam[cam_idx].append(state)
        last_shot_by_cam[int(cam_idx)] = shot_id
        prev_shot_id = shot_id

    if not states_by_cam:
        return []

    out: List[Dict[str, Any]] = []
    out_order = list(tree_order) if tree_order else []
    if order:
        seen = set(out_order)
        out_order.extend([c for c in order if c not in seen])
    if not out_order:
        out_order = list(order)

    for cam_idx in out_order:
        states = states_by_cam.get(int(cam_idx))
        if not isinstance(states, list) or not states:
            continue
        track: Dict[str, Any] = {
            "cam_idx": int(cam_idx),
            "states": list(states),
            "first_state_id": str(states[0]["state_id"]),
            "parent_cam_idx": None,
            "parent_shot_id": None,
        }
        node = parent_by_cam.get(int(cam_idx))
        if isinstance(node, dict):
            parent_cam_idx = node.get("parent_cam_idx")
            track["parent_cam_idx"] = int(parent_cam_idx) if isinstance(parent_cam_idx, int) else None
            parent_shot_id = node.get("parent_shot_id")
            track["parent_shot_id"] = str(parent_shot_id).strip() if isinstance(parent_shot_id, str) and parent_shot_id.strip() else None
        out.append(track)

    return out
