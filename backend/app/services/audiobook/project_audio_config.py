from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL, normalize_audiobook_tts_model

logger = logging.getLogger(__name__)

_LEGACY_MODEL_KEYS = {
    "cosyvoice-v3.5-plus": ("cosyvoice-v3-plus",),
    "minimax-speech-2.8-hd": ("MiniMax/speech-2.8-hd", "minimax-speech-2.8"),
    "minimax-speech-2.8-turbo": ("MiniMax/speech-2.8-turbo",),
}
DEFAULT_AUDIO_ENGINE_MODE = "legacy_stems"
AUDIO_ENGINE_MODES = frozenset({"legacy_stems", "seed_scene", "auto"})
DEFAULT_SEED_AUDIO_MODEL = "seed-audio-1.0-multilingual"
SEED_AUDIO_MODEL_STANDARD = "seed-audio-1.0"
SEED_AUDIO_MODEL_MULTILINGUAL = "seed-audio-1.0-multilingual"
KNOWN_SEED_AUDIO_MODELS = frozenset(
    {SEED_AUDIO_MODEL_STANDARD, SEED_AUDIO_MODEL_MULTILINGUAL}
)
SEED_AUDIO_MODELS = frozenset(KNOWN_SEED_AUDIO_MODELS)

# 历史顶层 seed 键→新分支位置映射（GUIDE §2.2 表）
_SEED_KEY_MIGRATION_MAP: Dict[str, tuple[str, str]] = {
    "seed_timeline_mode": ("scene_generation_preferences", "timeline_mode"),
    "seed_terminal_policy": ("scene_generation_preferences", "terminal_policy"),
    "semantic_review_enabled": ("scene_generation_preferences", "semantic_review_enabled"),
    "semantic_review_mode": ("scene_generation_preferences", "semantic_review_mode"),
}

# 分支内允许的顶层键
ENGINE_BRANCH_KEYS = frozenset({"tts_models", "audio_fx", "scene_generation_preferences", "characters"})


def parse_project_audio_config(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("项目音频配置 JSON 损坏，已忽略: error=%s", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("项目音频配置 JSON 不是对象，已忽略: payload_type=%s", type(data).__name__)
        return {}
    return data


def get_audio_engine_mode(config: Dict[str, Any]) -> str:
    value = str(config.get("audio_engine_mode") or "").strip().lower()
    return value if value in AUDIO_ENGINE_MODES else DEFAULT_AUDIO_ENGINE_MODE


def set_audio_engine_mode(config: Dict[str, Any], mode: str) -> Dict[str, Any]:
    normalized = str(mode or "").strip().lower()
    if normalized not in AUDIO_ENGINE_MODES:
        raise ValueError(f"unsupported audio_engine_mode: {mode}")
    config["audio_engine_mode"] = normalized
    return config


def get_seed_audio_model(config: Dict[str, Any]) -> str:
    value = str(config.get("seed_audio_model") or "").strip().lower()
    return value if value in SEED_AUDIO_MODELS else DEFAULT_SEED_AUDIO_MODEL


def set_seed_audio_model(config: Dict[str, Any], model: str) -> Dict[str, Any]:
    normalized = str(model or "").strip().lower()
    if normalized not in SEED_AUDIO_MODELS:
        raise ValueError(f"unsupported seed_audio_model: {model}")
    config["seed_audio_model"] = normalized
    return config


# ——— Engine Branch API ———


def get_engine_branch(config: Dict[str, Any], engine_mode: str) -> Dict[str, Any]:
    """读取 engines.{mode} 分支；不存在时从旧顶层归一化为 legacy_stems 分支（只读回退，不就地改写）。"""
    engines = config.get("engines")
    if isinstance(engines, dict):
        branch = engines.get(engine_mode)
        if isinstance(branch, dict):
            return dict(branch)

    # 回退只读归一化：仅 legacy_stems 支持从旧顶层构造分支
    if engine_mode == "legacy_stems":
        branch: Dict[str, Any] = {}
        tts_models = config.get("tts_models")
        if isinstance(tts_models, dict):
            branch["tts_models"] = deepcopy(tts_models)
        audio_fx = config.get("audio_fx")
        if isinstance(audio_fx, dict):
            branch["audio_fx"] = deepcopy(audio_fx)
        chars = config.get("characters")
        if isinstance(chars, list):
            branch["characters"] = deepcopy(chars)
        return branch

    # seed_scene 无回退时返回空分支
    return {}


def set_engine_branch(config: Dict[str, Any], engine_mode: str, branch: Dict[str, Any]) -> Dict[str, Any]:
    """写入 engines.{mode} 分支，停止写旧顶层 characters/audio_fx。"""
    if engine_mode not in ("legacy_stems", "seed_scene"):
        raise ValueError(f"cannot set branch for engine_mode: {engine_mode}")
    engines = config.get("engines")
    if not isinstance(engines, dict):
        engines = {}
        config["engines"] = engines
    engines[engine_mode] = deepcopy(branch) if branch else {}
    return config


def resolve_engine_mode(config: Dict[str, Any]) -> str:
    """归一化 engine_mode：auto 时根据证据判定 seed_scene 或 legacy_stems。

    GUIDE §2.4 归一化规则：
    - engines.seed_scene 分支非空 或 旧顶层存在任一 seed 键 → seed_scene
    - 否则 legacy_stems
    """
    raw = str(config.get("audio_engine_mode") or "").strip().lower()
    if raw not in AUDIO_ENGINE_MODES:
        return DEFAULT_AUDIO_ENGINE_MODE
    if raw != "auto":
        return raw

    # auto 判定
    engines = config.get("engines")
    if isinstance(engines, dict):
        seed_branch = engines.get("seed_scene")
        if isinstance(seed_branch, dict) and seed_branch:
            return "seed_scene"

    # 旧顶层 seed 键判定
    for old_key in _SEED_KEY_MIGRATION_MAP:
        if old_key in config:
            return "seed_scene"

    return "legacy_stems"


# ——— Characters API ———


def _read_branch_tts_models_characters(branch: Dict[str, Any], requested_model: str) -> Optional[List[dict]]:
    """从分支内按 tts_models.{model}.characters 优先级读取角色列表。"""
    tts_models = branch.get("tts_models")
    if isinstance(tts_models, dict):
        candidate_keys = (requested_model, *_LEGACY_MODEL_KEYS.get(requested_model, ()))
        for candidate_key in candidate_keys:
            model_cfg = tts_models.get(candidate_key)
            if isinstance(model_cfg, dict):
                chars = model_cfg.get("characters") or []
                if isinstance(chars, list):
                    return list(chars)
    return None


def get_characters_for_model(config: Dict[str, Any], tts_model: str, engine_mode: Optional[str] = None) -> List[dict]:
    """按 §2.2 读写优先级表读取角色配置。

    优先级（engine_mode 非 None 时）：
    1. engines.{mode}.tts_models.{requested_model}.characters
    2. engines.{mode}.tts_models.{legacy_key}.characters
    3. engines.{mode}.characters
    4. 旧顶层 tts_models.{model}.characters（仅 mode==legacy_stems）
    5. 旧顶层 characters（仅 mode==legacy_stems）

    engine_mode 为 None 时保持旧行为（从顶层读取）。
    """
    requested_model = normalize_audiobook_tts_model(tts_model)

    if engine_mode is not None:
        branch = get_engine_branch(config, engine_mode)
        # 优先级 1-2：tts_models.{model}.characters
        result = _read_branch_tts_models_characters(branch, requested_model)
        if result is not None:
            return result
        # 优先级 3：branch.characters（旧分支形态，无 tts_models 归组）
        branch_chars = branch.get("characters")
        if isinstance(branch_chars, list):
            return list(branch_chars)
        # 优先级 4-5：仅 legacy_stems 回退旧顶层
        if engine_mode == "legacy_stems":
            # 旧顶层 tts_models.{model}.characters
            tts_models = config.get("tts_models")
            if isinstance(tts_models, dict):
                candidate_keys = (requested_model, *_LEGACY_MODEL_KEYS.get(requested_model, ()))
                for candidate_key in candidate_keys:
                    model_cfg = tts_models.get(candidate_key)
                    if isinstance(model_cfg, dict):
                        chars = model_cfg.get("characters") or []
                        if isinstance(chars, list):
                            return list(chars)
            # 旧顶层 characters
            chars = config.get("characters") or []
            return list(chars) if isinstance(chars, list) else []
        return []

    # engine_mode 为 None 时保持旧行为
    tts_models = config.get("tts_models")
    if isinstance(tts_models, dict):
        candidate_keys = (requested_model, *_LEGACY_MODEL_KEYS.get(requested_model, ()))
        for candidate_key in candidate_keys:
            model_cfg = tts_models.get(candidate_key)
            if isinstance(model_cfg, dict):
                chars = model_cfg.get("characters") or []
                return list(chars) if isinstance(chars, list) else []
    chars = config.get("characters") or []
    return list(chars) if isinstance(chars, list) else []


def set_characters_for_model(config: Dict[str, Any], tts_model: str, characters: List[dict], engine_mode: Optional[str] = None) -> Dict[str, Any]:
    """按 §2.2 写入角色配置。

    engine_mode 非 None 时写入 engines.{mode}.tts_models.{model}.characters；
    仅当 mode==legacy_stems 且模型为默认模型时镜像顶层（向后兼容）。
    engine_mode 为 None 时保持旧行为（写顶层 tts_models + 默认模型镜像 characters）。
    """
    tts_model = normalize_audiobook_tts_model(tts_model)
    cleaned = list(characters or [])

    if engine_mode is not None:
        branch = get_engine_branch(config, engine_mode)
        tts_models = branch.get("tts_models")
        if not isinstance(tts_models, dict):
            tts_models = {}
            branch["tts_models"] = tts_models
        model_cfg = tts_models.get(tts_model)
        if not isinstance(model_cfg, dict):
            model_cfg = {}
            tts_models[tts_model] = model_cfg
        model_cfg["characters"] = list(cleaned)
        set_engine_branch(config, engine_mode, branch)

        # backward-compat: 仅 legacy_stems 且默认模型时镜像顶层
        if engine_mode == "legacy_stems" and tts_model == DEFAULT_AUDIOBOOK_TTS_MODEL:
            config["characters"] = list(cleaned)
        return config

    # engine_mode 为 None 时保持旧行为
    tts_models = config.get("tts_models")
    if not isinstance(tts_models, dict):
        tts_models = {}
        config["tts_models"] = tts_models
    model_cfg = tts_models.get(tts_model)
    if not isinstance(model_cfg, dict):
        model_cfg = {}
        tts_models[tts_model] = model_cfg
    model_cfg["characters"] = list(cleaned)
    if tts_model == DEFAULT_AUDIOBOOK_TTS_MODEL:
        config["characters"] = list(cleaned)
    return config


# ——— AudioFX API ———


def get_audio_fx(config: Dict[str, Any], engine_mode: Optional[str] = None) -> Optional[dict]:
    """按引擎分支读取 audio_fx。

    engine_mode 非 None 时：从 engines.{mode}.audio_fx 读取，回退旧顶层（仅 legacy_stems）。
    engine_mode 为 None 时保持旧行为（从顶层读取）。
    """
    if engine_mode is not None:
        branch = get_engine_branch(config, engine_mode)
        fx = branch.get("audio_fx")
        if isinstance(fx, dict):
            return dict(fx)
        # 回退旧顶层（仅 legacy_stems）
        if engine_mode == "legacy_stems":
            fx = config.get("audio_fx")
            return dict(fx) if isinstance(fx, dict) else None
        return None
    audio_fx = config.get("audio_fx")
    return dict(audio_fx) if isinstance(audio_fx, dict) else None


def set_audio_fx(config: Dict[str, Any], audio_fx: Optional[dict], engine_mode: Optional[str] = None) -> Dict[str, Any]:
    """按引擎分支写入 audio_fx，停止写旧顶层。

    engine_mode 非 None 时写入 engines.{mode}.audio_fx；
    engine_mode 为 None 时保持旧行为（写顶层 audio_fx）。
    """
    if engine_mode is not None:
        branch = get_engine_branch(config, engine_mode)
        if audio_fx is None:
            branch.pop("audio_fx", None)
        else:
            branch["audio_fx"] = dict(audio_fx)
        set_engine_branch(config, engine_mode, branch)
        # 不再写旧顶层
        return config

    # engine_mode 为 None 时保持旧行为
    if audio_fx is None:
        config.pop("audio_fx", None)
        return config
    config["audio_fx"] = dict(audio_fx)
    return config


# ——— Scene Generation Preferences API ———


def get_scene_generation_preferences(config: Dict[str, Any], engine_mode: str) -> Dict[str, Any]:
    """读取场景生成创作偏好。

    仅 seed_scene 分支有效；读取时兼容旧顶层 seed 键迁移映射。
    """
    branch = get_engine_branch(config, engine_mode)
    prefs = branch.get("scene_generation_preferences")
    if isinstance(prefs, dict):
        result = dict(prefs)
    else:
        result = {}

    # 历史旧顶层 seed 键迁移映射（只读回退，不就地改写）
    if engine_mode == "seed_scene":
        for old_key, (section, field) in _SEED_KEY_MIGRATION_MAP.items():
            if old_key in config:
                result.setdefault(section, {})
                if field not in result[section]:
                    result[section][field] = config[old_key]

    return result


def set_scene_generation_preferences(config: Dict[str, Any], engine_mode: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
    """写入场景生成创作偏好（仅 seed_scene 分支）。"""
    if engine_mode != "seed_scene":
        raise ValueError("scene_generation_preferences is only valid for seed_scene mode")
    branch = get_engine_branch(config, engine_mode)
    branch["scene_generation_preferences"] = dict(preferences or {})
    set_engine_branch(config, engine_mode, branch)
    return config


# ——— Snapshot Builders ———


def _canonical_json(data: Dict[str, Any]) -> str:
    """确定性 JSON 序列化：按键名排序，无多余空格。"""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_engine_config_snapshot(config: Dict[str, Any], engine_mode: str) -> Dict[str, Any]:
    """构建 engine_config_snapshot （GUIDE §2.1 结构）。

    返回直接可序列化为 JSON 的字典，含业务标识字段与审计元数据。
    """
    branch = get_engine_branch(config, engine_mode)

    engine_branch_config: Dict[str, Any] = {
        "seed_audio_model": get_seed_audio_model(config),
        "providers": {
            "seed_provider": "dashscope_seed",
            "asr_provider": "dashscope_asr",
            "fallback_tts_model": "qwen3-tts-instruct-flash",
            "fallback_tts_provider": "dashscope",
        },
    }
    tts_models = branch.get("tts_models")
    if isinstance(tts_models, dict):
        engine_branch_config["tts_models"] = deepcopy(tts_models)
    audio_fx = branch.get("audio_fx")
    if isinstance(audio_fx, dict):
        engine_branch_config["audio_fx"] = deepcopy(audio_fx)

    # 业务标识字段 hash
    business_payload = {
        "snapshot_version": 1,
        "engine_mode": engine_mode,
        "engine_branch_config": engine_branch_config,
    }
    fingerprint = hashlib.sha256(
        _canonical_json(business_payload).encode("utf-8")
    ).hexdigest()

    import datetime
    return {
        "snapshot_version": 1,
        "engine_mode": engine_mode,
        "engine_config_fingerprint": fingerprint,
        "engine_branch_config": engine_branch_config,
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_audio_config_hash": hashlib.sha256(
            _canonical_json(config).encode("utf-8")
        ).hexdigest(),
        "migrated_at": None,
    }


def parse_engine_config_snapshot(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """解析/校验 engine_config_snapshot JSON。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("engine_config_snapshot JSON 损坏，已忽略")
        return None
    if not isinstance(data, dict):
        return None
    # 最小校验
    if "engine_mode" not in data or "engine_branch_config" not in data:
        logger.warning("engine_config_snapshot 缺少必须字段")
        return None
    return data


def build_run_input_snapshot(
    batch_snapshot: Dict[str, Any],
    run_params: Dict[str, Any],
    revision_heads: Optional[Dict[str, Any]] = None,
    script_facts: Optional[Any] = None,
) -> Dict[str, Any]:
    """构建 run_input_snapshot （GUIDE §2.1 方案 A 自包含正文）。

    batch_snapshot: engine_config_snapshot 输出
    run_params: 运行参数（tts_model/output_format/narration_style/等）
    revision_heads: 编辑基线投影（可空）
    script_facts: 剧本事实正文（audio_from_scripts/场景重渲染在创建运行同一事务
      内读已审批 script_json；full/script_only 为 None，冻结 source_chapter_content）
    """
    import datetime

    engine_payload = deepcopy(batch_snapshot.get("engine_branch_config", {}))
    signed: Dict[str, Any] = {
        "signed_payload_version": 1,
        "engine_config_payload": engine_payload,
        "script_facts": script_facts,
        "source_chapter_content": run_params.get("source_chapter_content"),
        "voice_resolution": None,
        "run_options": {
            "tts_model": run_params.get("tts_model"),
            "output_format": run_params.get("output_format", "mp3"),
            "narration_style": run_params.get("narration_style"),
            "narration_style_prompt": run_params.get("narration_style_prompt"),
            "generate_subtitle": run_params.get("generate_subtitle", True),
            "timeline_edits": run_params.get("timeline_edits"),
        },
        "billing_context": {
            "provider": run_params.get("provider"),
            "seed_provider": run_params.get("seed_provider"),
            "asr_provider": run_params.get("asr_provider"),
            "fallback_tts_model": run_params.get("fallback_tts_model"),
            "fallback_tts_provider": run_params.get("fallback_tts_provider"),
            "fallback_policy": run_params.get("fallback_policy"),
            "billing_rules_version": run_params.get("billing_rules_version"),
            "billing_account_user_id": run_params.get("billing_account_user_id"),
            "billing_snapshot": run_params.get("billing_snapshot"),
        },
        "revision_set_hash": (revision_heads or {}).get("revision_set_hash"),
        "revision_heads": (
            {
                "dialogue": (revision_heads or {}).get("dialogue"),
                "director_override": (revision_heads or {}).get("director_override"),
                "voice_binding": (revision_heads or {}).get("voice_binding"),
            }
            if revision_heads
            else None
        ),
        "revision_projection": (revision_heads or {}).get("projection"),
    }

    input_signature = hashlib.sha256(
        _canonical_json(signed).encode("utf-8")
    ).hexdigest()

    return {
        "input_signature": input_signature,
        "signed_payload": signed,
        "base_fingerprint": batch_snapshot.get("engine_config_fingerprint"),
        "batch_snapshot_version": batch_snapshot.get("snapshot_version"),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
