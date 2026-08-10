"""恢复进化路径导入守卫：禁止依赖不存在的 app.api.v1.models 模块。

历史缺陷：resume 路径内 `from .models import PromptVersion` 相对导入解析到
app.api.v1.models（不存在），导致恢复进化在运行时才报 No module named。
PromptVersion 必须从 app.services.prompt_evolution 导入。
"""
from pathlib import Path

API_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "prompt_evolution.py"


def test_api_module_does_not_relative_import_models():
    source = API_MODULE_PATH.read_text(encoding="utf-8")
    assert "from .models import" not in source, (
        "app/api/v1 下不存在 models 模块，相对导入会在恢复进化时抛 ModuleNotFoundError"
    )


def test_api_module_imports_prompt_version_from_service_package():
    source = API_MODULE_PATH.read_text(encoding="utf-8")
    assert "PromptVersion" in source
    # 顶部应从服务包导入（与 PromptEvolutionEngine 同一导入块或等价路径）
    assert "app.services.prompt_evolution" in source

    # 服务包确实导出 PromptVersion
    from app.services.prompt_evolution import PromptVersion  # noqa: F401


def test_resume_path_initializes_experience_library():
    """恢复路径必须与正常进化一致：预置经验初始化 + 历史经验传承。

    历史缺陷：_run_resumed 未调用 reset_experience/load_historical_experience，
    导致恢复进化从空经验库起步，预置降分杠杆与历史批次经验全部失效。
    """
    source = API_MODULE_PATH.read_text(encoding="utf-8")
    assert "reset_experience()" in source, "恢复路径未初始化预置经验库"
    assert "load_historical_experience(" in source, "恢复路径未传承历史批次经验"
