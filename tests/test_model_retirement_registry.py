"""已退役模型的反向断言登记表。

退役策略（用户 2026-10-08 决定）：模型退役即从配置、注册中心、适配器与目录卡片里物理删除，
不保留 deprecated 兼容位，也不留 original_model_id 审计副本——目标是"就像没接过老模型"。
因此本文件不测旧模型还能用，只测旧模型**彻底不在**，防止后续改动把它们悄悄加回来。

一个必须区分的例外：``wan2.7-i2v`` / ``wan2.7-t2v`` 这两个字符串同时是 DreamWeaver 的
**引擎模式标识**（pipeline/media_presets.py 的 DREAMWEAVER_I2V_ENGINE / DREAMWEAVER_T2V_ENGINE），
决定提示词分支与是否走首帧桥接，并被写进项目配置与计费单价表的 key。它们不是模型 ID，
不在退役范围内，末位用例专门锁住这一点。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR, ROOT_DIR / "backend"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

MODELS_YAML = ROOT_DIR / "config" / "models.yaml"
LLM_MODELS_YAML = ROOT_DIR / "config" / "llm_models.yaml"

# 退役 ID → 承接它的现行 ID。wan2.6-t2v 从未进过 models.yaml，
# 它只是 MODEL_ALIASES 里 wan2.6-t2v-fast 的归一目标，属于悬空引用。
RETIRED_MEDIA_MODELS = {
    "qwen-image-2.0": "qwen-image-3.0",
    "qwen-image-2.0-pro": "qwen-image-3.0-pro",
    "wan2.6-t2i": "qwen-image-3.0",
    "wan2.7-image": "wan2.7-image-pro",
    "wan2.6-t2v": "wan3.0-video",
    "wan2.6-t2v-fast": "wan3.0-video",
    "wan2.7-i2v": "wan3.0-video",
    "wan2.7-t2v": "wan3.0-video",
    "wan2.7-r2v": "wan3.0-video",
    "wan2.7-videoedit": "wan3.0-video",
    "doubao-seedream-4-5": "doubao-seedream-5-0-pro",
    "doubao-seed-2-0-pro": "doubao-seed-2-1-pro",
    "doubao-seed-2-0-lite": "doubao-seed-2-1-lite",
    "doubao-seedance-1-5-pro": "doubao-seedance-2-5",
    # 2026-10-09 换代：StepAudio 3 TTS 协议全兼容（36 音色/instruction/inline 语境实测通过），
    # 单价 5.8→2.5 元/万字符；2.5 代官方虽未下线，本项目按物理退役统一切到 3 代
    "stepaudio-2.5-tts": "stepaudio-3-tts",
    # 2026-10-10 换代：上游 multimodal-generation 端点返回 404 Model not exist，
    # 有声书 TTS 全链路改指 qwen-audio-3.1-tts-flash（音色空间换成 _v3.1，不互通）
    "qwen3-tts-instruct-flash": "qwen-audio-3.1-tts-flash",
    # 2026-10-12 视觉评审换代：三档盲评实测后 omni-plus 成本最高、无维度胜出，
    # 与轻量的 qwen3.8-omni-flash 能力重复，产品入口与运行时白名单一并摘除
    "qwen3.5-omni-plus": "qwen3.8-omni-flash",
    # 2026-10-12 短剧 QC 线迁到 qwen3.8-omni-flash 后物理退役：它曾是本项目唯一的统一
    # 多模态理解入口，adapter 模块、legacy 适配器、runtime 包装器与两份档案卡同批删除
    "qwen3-vl-plus": "qwen3.8-omni-flash",
}

RETIRED_LLM_MODELS = {
    "deepseek-v4-flash": "deepseek-flash",
    "kimi/kimi-k2.6": "kimi-preview",
    "mimo-v2.5": "mimo-flash",
    "mimo-v2.5-pro": "mimo-pro",
    "step-3.7-flash": "step-preview",
    # 2026-10-09 原地换代：内部 ID glm 不变，上游线名由 glm-5.2 升到 glm-5.3，旧线名必须彻底消失
    "glm-5.2": "glm",
}

# 存量 LLM 线改用不含版本号的中性内部 ID（升级换代不换 ID，上游线名由 request_model 固定）。
# 改名与退役同样要求旧 ID 彻底消失，所以走同一套反向断言。
# 注意：一个内部 ID 在本表只能有一个 key——test_wire_name_is_pinned_by_request_model 会把
# key 当作 request_model 的期望值，换代时必须替换 key 而不是并列表述。
RENAMED_LLM_MODELS = {
    "qwen3.7-plus": "qwen-plus",
    "qwen3.7-flash": "qwen-flash",
    "kimi/kimi-k2.8-preview": "kimi-preview",
    "glm-5.3": "glm",
    "MiniMax/MiniMax-M3": "minimax-m",
    "step-5-preview": "step-preview",
    "mimo-v2.6-pro": "mimo-pro",
    "mimo-v2.6-flash": "mimo-flash",
    "deepseek-v4-pro": "deepseek-pro",
}

# 有声书客观层/字幕 ASR 换代（2026-10-11）：fun-asr-flash → qwen-audio-3.1-asr-flash。
# 这条链路的线名不进两份 YAML、也不进媒体注册中心，事实源是 backend 服务模块与
# backend/.env.example，所以单列一张表，由 TestAudiobookAsrRetirement 逐处反向断言。
RETIRED_AUDIOBOOK_ASR_MODELS = {
    "fun-asr-flash-2026-06-15": "qwen-audio-3.1-asr-flash",
}
RETIRED_AUDIOBOOK_ASR_PROVIDERS = {"fun_asr_flash", "funasr", "funasr_flash"}

# 改名 + 退役后仍必须彻底消失的全部旧 ID
LEGACY_LLM_IDS = set(RETIRED_LLM_MODELS) | set(RENAMED_LLM_MODELS)

# 退役/改名产生的兼容别名已于 2026-10-09 随数据库历史 ID 改写整批删除。
# 归一表现在只剩拼写形态归一，下列旧 ID 必须一律查不到别名。
LEGACY_ALIAS_KEYS = (
    {mid.lower() for mid in set(RETIRED_MEDIA_MODELS) | LEGACY_LLM_IDS}
    # MiniMax M3 的历史短横线写法
    | {"minimax-m3"}
    # 短剧 QC 线曾把退役档以下划线形态写进 .env 的 *_VLM_ADAPTER 与分支配置，
    # 归一别名跟着退役 ID 一起删，留任何一条都等于给它续命
    | {"qwen3_vl_plus"}
)

REGISTER_DECORATOR_RE = re.compile(
    r"""@(?:register_model|register_llm_model)\(\s*["']([^"']+)["']"""
)


def _yaml_ids(path: Path, key: str) -> set[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {entry["id"] for entry in payload[key]}


@pytest.fixture(scope="module")
def media_registry():
    import adapters  # noqa: F401  触发适配器注册
    from adapters.registry import registry

    registry._ensure_builtin_registration()
    return registry


@pytest.fixture(scope="module")
def llm_registry():
    from core.model_hub import model_hub
    from model_registry_reset import reload_llm_registry

    # 上游模块可能已 clear() 过共享单例且只留下桩模型，必须整目录重装再断言
    reload_llm_registry()
    return model_hub.registry


@pytest.fixture(scope="module")
def catalog_keys() -> set[str]:
    from app.services.model_catalog_bootstrap import build_model_catalog_card_payloads

    return {payload["model_key"] for payload in build_model_catalog_card_payloads()}


class TestMediaRetirement:
    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_registry(self, media_registry, retired):
        assert media_registry.get_spec(retired) is None
        assert media_registry.get_adapter(retired) is None

    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_models_yaml(self, retired):
        assert retired not in _yaml_ids(MODELS_YAML, "models")

    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_media_runtime_allowlist(self, retired):
        """自动路由白名单是第三处事实源：档案和 adapter 都删了、白名单还留着，
        运行期就变成 adapter_missing 响亮失败，比选不到更糟。"""
        from core.unified_media_runtime import _OPERATION_MODEL_IDS

        for operation, model_ids in _OPERATION_MODEL_IDS.items():
            assert retired not in set(model_ids), f"{operation} 白名单仍保留已退役 {retired}"

    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_asset_studio_groups(self, retired):
        """资产工作台的分组是产品入口：档案删了、卡片删了但分组还列着，
        页面就会把用户选中的档位发给后端换 400，属于最容易被漏的一层。"""
        from app.services.asset_studio_model_catalog import get_asset_studio_model_sets

        hit = [name for name, ids in get_asset_studio_model_sets().items() if retired in set(ids)]
        assert hit == [], f"{retired} 仍出现在产品分组 {hit}"

    def test_no_asset_studio_default_is_retired(self):
        """默认档指向已删除的模型比分组里多留一档更糟：没做选择的请求会直接失败。"""
        from app.services.asset_studio_model_catalog import _DEFAULT_MODEL_IDS

        hit = [key for key, mid in _DEFAULT_MODEL_IDS.items() if mid in RETIRED_MEDIA_MODELS]
        assert hit == [], f"工作台默认档仍指向退役模型: {sorted(hit)}"

    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_catalog_cards(self, catalog_keys, retired):
        assert retired not in catalog_keys

    @pytest.mark.parametrize("retired", sorted(RETIRED_MEDIA_MODELS))
    def test_absent_from_legacy_compatibility_tables(self, retired):
        """兼容层是档案/注册中心/白名单之外的第四处事实源。

        `create_runtime_wrapper` 未命中时返回 None 而不是报错，`_resolve_runtime_model_id`
        又会在拿不到档案时把 QC 开关静默置 False：包装器表或工厂 env 映射里残留旧 ID，
        退役就退成了"档案没了、对象还能建出来"，而调用方看不到任何异常。
        """
        from adapters.legacy_runtime_wrappers import (
            _RUNTIME_WRAPPER_ALIASES,
            _RUNTIME_WRAPPER_CLASSES,
        )
        from adapters.model_adapters import ModelAdapterFactory

        forms = {retired.lower(), retired.lower().replace("-", "_"), retired.lower().replace(".", "_")}
        wrapper_keys = {key.lower() for key in _RUNTIME_WRAPPER_CLASSES} | {
            key.lower() for key in _RUNTIME_WRAPPER_ALIASES
        }
        assert forms & wrapper_keys == set(), f"{retired} 仍有 runtime 包装器条目: {sorted(forms & wrapper_keys)}"
        factory_keys = {key.lower() for key in ModelAdapterFactory._ENV_PREFIX_MAP}
        assert forms & factory_keys == set(), f"{retired} 仍在工厂 env 映射里: {sorted(forms & factory_keys)}"
        assert retired not in set(ModelAdapterFactory._DEFAULT_MODEL_NAME_BY_ENV.values())

    @pytest.mark.parametrize(("retired", "successor"), sorted(RETIRED_MEDIA_MODELS.items()))
    def test_successor_is_registered_and_active(self, media_registry, retired, successor):
        from schemas.common import ModelStatus

        spec = media_registry.get_spec(successor)
        assert spec is not None, f"{retired} 的承接模型 {successor} 未注册"
        assert spec.status is ModelStatus.ACTIVE


class TestLLMRetirement:
    @pytest.mark.parametrize("retired", sorted(RETIRED_LLM_MODELS))
    def test_absent_from_registry(self, llm_registry, retired):
        assert llm_registry.get_spec(retired) is None

    @pytest.mark.parametrize("retired", sorted(RETIRED_LLM_MODELS))
    def test_absent_from_llm_models_yaml(self, retired):
        assert retired not in _yaml_ids(LLM_MODELS_YAML, "llm_models")

    @pytest.mark.parametrize(("retired", "successor"), sorted(RETIRED_LLM_MODELS.items()))
    def test_successor_is_available(self, llm_registry, retired, successor):
        spec = llm_registry.get_spec(successor)
        assert spec is not None, f"{retired} 的承接模型 {successor} 未注册"
        assert llm_registry.get_adapter(successor) is not None


class TestLLMRename:
    """中性 ID 改名与退役同等严格：旧 ID 不许以任何形式留在目录里。"""

    @pytest.mark.parametrize("old", sorted(RENAMED_LLM_MODELS))
    def test_absent_from_registry(self, llm_registry, old):
        assert llm_registry.get_spec(old) is None
        assert llm_registry.get_adapter(old) is None

    @pytest.mark.parametrize("old", sorted(RENAMED_LLM_MODELS))
    def test_absent_from_llm_models_yaml(self, old):
        assert old not in _yaml_ids(LLM_MODELS_YAML, "llm_models")

    @pytest.mark.parametrize(("old", "new"), sorted(RENAMED_LLM_MODELS.items()))
    def test_new_id_is_available(self, llm_registry, old, new):
        spec = llm_registry.get_spec(new)
        assert spec is not None, f"{old} 改名后的 {new} 未注册"
        assert llm_registry.get_adapter(new) is not None

    @pytest.mark.parametrize(("old", "new"), sorted(RENAMED_LLM_MODELS.items()))
    def test_wire_name_is_pinned_by_request_model(self, llm_registry, old, new):
        """ID 去掉版本号后，发给上游的模型名必须显式钉死，否则会拿内部 ID 去调 API。"""
        from core.model_resolution import normalize_model_id

        spec = llm_registry.get_spec(new)
        assert spec is not None
        assert (spec.default_params or {}).get("request_model") == old
        # 过渡期别名已删除：旧线名不再是可解析的内部 ID
        assert normalize_model_id(old) != new


class TestNoRegistrationPointSurvives:
    """装饰器注册点必须与 YAML 条目同步删除。

    只删 YAML 会让装饰器注册的 spec 把旧模型复活成 ACTIVE，这是退役时最容易漏的一步。
    """

    def test_no_decorator_registers_a_retired_id(self):
        retired = set(RETIRED_MEDIA_MODELS) | LEGACY_LLM_IDS
        found: list[str] = []
        for path in list((ROOT_DIR / "adapters").rglob("*.py")) + list((ROOT_DIR / "core").rglob("*.py")):
            for model_id in REGISTER_DECORATOR_RE.findall(path.read_text(encoding="utf-8")):
                if model_id in retired:
                    found.append(f"{path.relative_to(ROOT_DIR)}:{model_id}")
        assert found == []


class TestAudiobookAsrRetirement:
    """有声书客观层 ASR 换代：旧线名在 provider 工厂、价目表、env 模板三处都不许再被认识。

    这条链路只有 HTTP 契约，没有注册中心条目，所以 `TestMediaRetirement` 那套断言覆盖不到它；
    漏掉任何一处的后果都不同——工厂仍认识旧键＝调用方能静默切回旧模型；价目表仍留旧键＝
    成本闸门按已退役刊例估算；env 仍写旧线名＝下次部署直接发到不存在的模型。
    """

    def test_successor_is_the_code_default(self):
        from app.services.audiobook.prompt_audio_asr_provider import (
            DEFAULT_PROMPT_AUDIO_ASR_PROVIDER,
        )

        assert DEFAULT_PROMPT_AUDIO_ASR_PROVIDER == "qwen_audio_asr_flash"

    @pytest.mark.parametrize("retired", sorted(RETIRED_AUDIOBOOK_ASR_PROVIDERS))
    def test_retired_provider_key_fails_loudly(self, retired, monkeypatch):
        """旧 provider 键必须直接报错，不能被静默改写成新模型。"""
        from app.services.audiobook.prompt_audio_asr_provider import (
            PromptAudioAsrProviderError,
            create_prompt_audio_asr_provider,
        )

        monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-key")
        with pytest.raises(PromptAudioAsrProviderError) as error:
            create_prompt_audio_asr_provider(retired)
        assert error.value.code == "asr_provider_unsupported"

    @pytest.mark.parametrize(("retired", "successor"), sorted(RETIRED_AUDIOBOOK_ASR_MODELS.items()))
    def test_retired_line_name_has_no_price_entry(self, retired, successor):
        from app.services.audiobook.prompt_audio_asr_pricing import (
            get_prompt_audio_asr_pricing,
        )

        for provider in sorted(RETIRED_AUDIOBOOK_ASR_PROVIDERS):
            assert get_prompt_audio_asr_pricing(provider, retired) is None
        assert get_prompt_audio_asr_pricing("qwen_audio_asr_flash", successor) is not None

    def test_env_template_points_at_the_successor(self):
        text = (ROOT_DIR / "backend" / ".env.example").read_text(encoding="utf-8")
        values = dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", text, re.MULTILINE))

        assert values["PROMPT_AUDIO_ASR_PROVIDER"] == "qwen_audio_asr_flash"
        assert values["QWEN_AUDIO_ASR_MODEL"] == "qwen-audio-3.1-asr-flash"
        for retired in RETIRED_AUDIOBOOK_ASR_MODELS:
            assert not any(retired in value for value in values.values())

    def test_retired_line_names_enter_the_reference_gate(self):
        auditor = _load_reference_auditor()
        assert set(auditor.retired_ledger_ids()) >= set(RETIRED_AUDIOBOOK_ASR_MODELS)


class TestAliasTable:
    @pytest.mark.parametrize("alias", sorted(LEGACY_ALIAS_KEYS))
    def test_legacy_id_has_no_alias(self, alias):
        """旧 ID 不得再被静默改写：调用方用错名字应当直接失败并被看见，而不是拿到另一个模型。"""
        from core.model_resolution import MODEL_ALIASES

        assert alias not in MODEL_ALIASES

    def test_every_alias_target_resolves_to_a_registered_model(self, media_registry, llm_registry):
        """归一目标悬空比不归一更糟：调用方拿到的是一个任何注册中心都不认识的 ID。"""
        from core.model_resolution import MODEL_ALIASES

        dangling = [
            f"{alias} -> {target}"
            for alias, target in sorted(MODEL_ALIASES.items())
            if media_registry.get_spec(target) is None
            and llm_registry.get_spec(target) is None
        ]
        assert dangling == []


class TestEngineConstantsAreNotModelIds:
    def test_dreamweaver_engine_strings_survive_video_line_retirement(self):
        from pipeline.media_presets import (
            DREAMWEAVER_I2V_ENGINE,
            DREAMWEAVER_T2V_ENGINE,
            DREAMWEAVER_WAN_MODEL_ID,
        )

        assert DREAMWEAVER_I2V_ENGINE == "wan2.7-i2v"
        assert DREAMWEAVER_T2V_ENGINE == "wan2.7-t2v"
        assert DREAMWEAVER_WAN_MODEL_ID == "wan3.0-video"

    def test_engine_strings_are_not_registered_as_models(self, media_registry):
        from pipeline.media_presets import DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_T2V_ENGINE

        for engine in (DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_T2V_ENGINE):
            assert media_registry.get_spec(engine) is None

    def test_billing_table_keys_match_engine_constants(self):
        source = (ROOT_DIR / "backend/app/services/user_center_task_billing.py").read_text(encoding="utf-8")
        assert '"wan2.7-i2v"' in source
        assert '"wan2.7-t2v"' in source


def _load_reference_auditor():
    """按文件路径加载引用审计脚本：scripts/ 不在导入路径上，只能按文件加载。"""
    import importlib.util

    path = ROOT_DIR / "scripts" / "audit_model_references.py"
    spec = importlib.util.spec_from_file_location("_audit_model_references", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReferenceAuditGate:
    """引用审计工具的命中分类必须"窄"。

    `--all-retired --expect-zero` 是物理退役的常设门禁。它靠上下文把"合法保留"与
    "残留待改"分开：上游真名（wire name）与 DreamWeaver 引擎标识符算合法保留，
    其余一律待改。豁免面一旦被放宽成"整文件跳过"，门禁就会变成永远绿灯的摆设，
    所以这里用正反两组用例把它钉住。
    """

    @staticmethod
    def _load_auditor():
        return _load_reference_auditor()

    @pytest.mark.parametrize(
        ("path", "line", "model_id"),
        [
            # 上游真名：内部 ID 换成中性名后，这些行出现旧线名是设计使然
            ("config/llm_models.yaml", "request_model: deepseek-v4-pro", "deepseek-v4-pro"),
            (
                "tests/test_unified_model_system.py",
                'assert default_params["request_model"] == "deepseek-v4-pro"',
                "deepseek-v4-pro",
            ),
            ("config/models.yaml", 'model="glm-5.2[1m]",', "glm-5.2"),
            ("config/llm_models.yaml", "- 通过 DashScope 接口接入，模型名为 qwen3.7-flash", "qwen3.7-flash"),
            ("core/llm_adapters.py", "上游模型名 kimi/kimi-k2.8-preview（无日期后缀）。", "kimi/kimi-k2.8-preview"),
            ("tests/test_unified_model_system.py", 'assert captured["model"] == "deepseek-v4-pro"', "deepseek-v4-pro"),
            # 无后缀变体：内部 ID 从不带方括号，出现 [1m] 只可能是上游写法
            ("config/llm_models.yaml", "description: 支持长上下文（glm-5.2[1m]）", "glm-5.2"),
            # 引擎标识符：与已退役模型 ID 同名，但不是模型 ID
            ("pipeline/media_presets.py", 'DREAMWEAVER_I2V_ENGINE = "wan2.7-i2v"', "wan2.7-i2v"),
            (
                "backend/app/services/user_center_task_billing.py",
                '"wan2.7-t2v": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_WAN_T2V", 0.15),',
                "wan2.7-t2v",
            ),
            ("tests/test_phase4_hooks.py", 'video_config={"engine": "wan2.7-i2v"},', "wan2.7-i2v"),
            # 记录性文件
            ("tests/test_model_retirement_registry.py", 'RETIRED_MEDIA_MODELS = {"wan2.7-i2v": "wan3.0-video"}', "wan2.7-i2v"),
            ("docs/MODEL_INTEGRATION_REFERENCE.md", "换代台账：wan2.7-r2v 已物理删除", "wan2.7-r2v"),
            # 反向断言必须写出旧 ID 本身，否则"不许复活"无从断言
            (
                "frontend/src/components/home/__tests__/assetStudioVisionModelSource.test.ts",
                "expect(source).not.toContain('qwen3.5-omni-plus')",
                "qwen3.5-omni-plus",
            ),
            # 当日报价调研快照：内容是从旧配置原样粘贴的取证材料
            ("调研API价格_2026-10-11_18-49.md", "- id: wan2.7-r2v", "wan2.7-r2v"),
        ],
    )
    def test_legitimate_kept_references_are_not_counted(self, path, line, model_id):
        auditor = self._load_auditor()
        assert auditor._is_allowed_hit(path, line, model_id) is True

    @pytest.mark.parametrize(
        ("path", "line", "model_id"),
        [
            # 这些才是必须拦下的残留：旧 ID 仍被当作模型 ID 使用
            (
                "backend/app/services/asset_studio_model_catalog.py",
                '_DEFAULT_MODEL_IDS = {"image": "wan2.7-i2v"}',
                "wan2.7-i2v",
            ),
            ("backend/app/services/streaming_service.py", 'DEFAULT_MODEL = "deepseek-v4-pro"', "deepseek-v4-pro"),
            ("config/models.yaml", "- id: qwen-image-2.0", "qwen-image-2.0"),
            ("core/model_resolution.py", 'MODEL_ALIASES = {"wan2.6-t2v": "wan3.0-video"}', "wan2.6-t2v"),
            (
                "frontend/src/pages/DreamWeaverRunPage.tsx",
                '{ value: "wan2.7-t2v", label: "万相 2.7" }',
                "wan2.7-t2v",
            ),
            ("backend/app/services/audiobook/voice_manager.py", 'tts_model_id = "qwen3-tts-flash"', "qwen3-tts-flash"),
        ],
    )
    def test_real_residues_are_still_flagged(self, path, line, model_id):
        auditor = self._load_auditor()
        assert auditor._is_allowed_hit(path, line, model_id) is False

    def test_retired_ledger_is_non_empty(self):
        """--all-retired 的事实源若为空集，门禁会假绿，因此登记表本身要有内容。"""
        auditor = self._load_auditor()
        ids = auditor.retired_ledger_ids()
        assert ids
        assert set(ids) >= (set(RETIRED_MEDIA_MODELS) | set(RETIRED_LLM_MODELS) | set(RENAMED_LLM_MODELS))

    def test_every_scanned_path_resolves_to_a_readable_file(self):
        """清单里的每个路径都必须真能读到内容，否则门禁对读不到的文件静默绿灯。

        git 默认 `core.quotepath=true` 会把非 ASCII 路径转义成 `\350\220\275`，Windows 下
        `text=True` 又按本地编码解码，两者叠加后中文命名的文档"出现在清单里、却拼不出文件"，
        `_read` 返回 None 就等于这些文件从未被审计过。
        """
        auditor = self._load_auditor()
        files = auditor.tracked_text_files()
        assert files

        unreadable = [rel for rel in files if not (ROOT_DIR / rel).is_file()]
        # 物理退役会真删文件：索引还跟踪、工作区已不在，这类路径按定义没有可扫内容。
        # 不放行就变成"每退役一次门禁假红一次"。git 的删除判定用内部文件名 stat，
        # 不受输出转义影响，因此"存在但名字被转义"的文件不会被误归到这里。
        deleted = {
            line.strip().strip('"')
            for line in (auditor._git_ls_files("-d") or "").splitlines()
            if line.strip()
        }
        assert sorted(set(unreadable) - deleted) == []
        assert any(any(ord(ch) > 127 for ch in rel) for rel in files), (
            "扫描范围应覆盖非 ASCII 命名文件；一条都没有说明本用例的保护对象已消失"
        )


class TestEnvModelValueScan:
    """env 文件必须进门禁视野，且永远不能把密钥带进报告。

    `.env` 在 `.gitignore` 里，`git ls-files` 取不到它，曾出现过"门禁归零而 .env 仍指向
    已退役 ID"的盲区。把它补进扫描范围的代价是：解析器只能读模型类键的取值，命中项一律
    重建为 `KEY=值` 而不复制整行——同一行的注释与相邻行都可能是真实密钥。因此这里两头都要锁：
    漏检要红，泄漏密钥也要红。
    """

    def test_env_files_enter_scan_scope(self):
        auditor = _load_reference_auditor()
        present = auditor.env_files_present()
        assert present, "本仓库至少应有 .env / .env.example"
        assert set(present) <= set(auditor.tracked_text_files())

    def test_env_paths_are_labelled_as_env_layer(self):
        auditor = _load_reference_auditor()
        assert auditor._layer_of(".env") == auditor.ENV_LAYER
        assert auditor._layer_of("backend/.env.example") == auditor.ENV_LAYER
        assert auditor._layer_of("config/models.yaml") == "config"

    @pytest.mark.parametrize(
        ("raw_line", "expected"),
        [
            ("WAN_T2I_MODEL_NAME=wan2.7-image-pro", "WAN_T2I_MODEL_NAME=wan2.7-image-pro"),
            ('export WAN_T2I_MODEL_NAME="wan2.7-image-pro"', "WAN_T2I_MODEL_NAME=wan2.7-image-pro"),
            (
                "QWEN3_TTS_MODEL_NAME='qwen3-tts-instruct-flash'  # 现役线",
                "QWEN3_TTS_MODEL_NAME=qwen3-tts-instruct-flash",
            ),
            (
                "MINIMAX_MODEL_NAME=MiniMax/MiniMax-M3  # 上游线名，直发供应商",
                "MINIMAX_MODEL_NAME=MiniMax/MiniMax-M3  # 上游线名",
            ),
            # 密钥键、非模型键、纯数字平台资源 ID、空值、间接引用、注释行都不参与
            ("DASHSCOPE_API_KEY=sk-should-never-appear", None),
            ("QWEN3_TTS_TOKEN_SECRET=hunter2", None),
            ("WAN_T2I_MODEL_ID=2862677", None),
            ("LOG_LEVEL=DEBUG", None),
            ("MODEL_NAME=", None),
            ("MODEL_NAME=${OTHER_MODEL}", None),
            ("# WAN_T2I_MODEL_NAME=wan2.6-t2i", None),
        ],
    )
    def test_env_safe_line_rebuilds_only_key_and_value(self, raw_line, expected):
        auditor = _load_reference_auditor()
        assert auditor.env_safe_line(raw_line) == expected

    def test_bare_retired_env_value_counts_as_residue(self):
        auditor = _load_reference_auditor()
        line = auditor.env_safe_line("WAN_T2I_MODEL_NAME=wan2.6-t2i")
        assert auditor.must_fix_count("wan2.6-t2i", [(".env", 42, line)]) == 1

    def test_annotated_upstream_wire_name_is_exempted(self):
        """env 取值确实是发给供应商的上游真名时，靠行尾"上游线名"标注放行。"""
        auditor = _load_reference_auditor()
        line = auditor.env_safe_line("QWEN3_TTS_FLASH_MODEL_ID=qwen3-tts-flash  # 上游线名")
        assert auditor.must_fix_count("qwen3-tts-flash", [(".env", 42, line)]) == 0

    def test_dated_snapshot_value_cannot_be_a_hit(self):
        """带日期的上游快照名（qwen3-tts-flash-2025-11-27）被词边界天然排除，无需额外放行规则。"""
        auditor = _load_reference_auditor()
        line = auditor.env_safe_line("QWEN3_TTS_FLASH_MODEL_ID=qwen3-tts-flash-2025-11-27")
        assert auditor.boundary_pattern("qwen3-tts-flash").search(line) is None

    def test_planted_residue_is_found_without_leaking_secrets(self, tmp_path, monkeypatch):
        auditor = _load_reference_auditor()
        (tmp_path / ".env").write_text(
            "DASHSCOPE_API_KEY=sk-secret-token-must-not-appear\n"
            "QWEN3_TTS_API_KEY=sk-another-secret\n"
            "WAN_T2I_MODEL_NAME=wan2.6-t2i  # sk-third-secret\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(auditor, "PROJECT_ROOT", tmp_path)

        files = auditor.env_files_present()
        hits = auditor.scan_references(["wan2.6-t2i"], files)
        assert auditor.must_fix_count("wan2.6-t2i", hits["wan2.6-t2i"]) == 1
        assert auditor.summarize(hits["wan2.6-t2i"])[auditor.ENV_LAYER] == 1
        for _rel, _lineno, text in hits["wan2.6-t2i"]:
            assert "sk-" not in text
            assert "secret" not in text.lower()

    def test_repo_env_files_hold_no_retired_values(self):
        auditor = _load_reference_auditor()
        hits = auditor.scan_references(auditor.retired_ledger_ids(), auditor.env_files_present())
        assert sum(auditor.must_fix_count(mid, entries) for mid, entries in hits.items()) == 0
