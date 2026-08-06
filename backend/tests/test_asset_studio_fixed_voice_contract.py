import ast
from pathlib import Path


ROUTE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "api"
    / "v1"
    / "asset_studio_api"
    / "routes_audio.py"
)


def test_asset_studio_speech_accepts_legacy_pitch_without_using_it() -> None:
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"), filename=str(ROUTE_PATH))
    route = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_audio_asset"
    )

    argument_names = {argument.arg for argument in route.args.args}
    pitch_reads = [
        node
        for statement in route.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == "pitch"
    ]

    assert "pitch" in argument_names
    assert pitch_reads == []


def test_asset_studio_speech_applies_model_aware_numeric_speed_policy() -> None:
    source = ROUTE_PATH.read_text(encoding="utf-8")

    assert "stabilize_instruct_model_speed(voice_params, resolved_model_id)" in source
    assert '"pace_control": "numeric" if "rate" in voice_params else "semantic"' in source
    assert '**({"rate": float(voice_params["rate"])} if "rate" in voice_params else {})' in source
