"""场景音频产物根（``SCENE_ARTIFACT_ROOT``）的落盘卫生守卫。

背景：``backend/data/scene_audio_artifacts/`` 是运行时产物存储根，正式产物由
``_scene_render_mixin`` 以 ``art_{40位hex}.{音频后缀}`` 平铺写入（**没有分片，
分片只是设计文档里的规划**）。2026-10-11 发现一份 pytest 测试模块被误提交进该
目录（``art_6798aca87b3fc42b3f93620fc3484c710d3b0101.py``），因其名字与产物命名
同形、且该根未被 ``.gitignore`` 覆盖，肉眼盘点与按扩展名清理都发现不了，
在 2026-08-27、2026-10-11 反复"处理"过两轮才清除。

覆盖：
- 检测逻辑对真实事故样本有效（种入同名 ``.py`` 必须被报出）；
- 合法音频产物不得误报（平铺 ``art_*.wav`` / ``.mp3`` 及分片子目录形式）；
- 根目录不存在或为空时视为通过（新克隆环境）；
- 现网真实产物根不得含任何源码文件（``.py`` / ``.pyc``）。
"""

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.services.audiobook.chapter_output_publish import SCENE_ARTIFACT_ROOT

# 事故样本的真实文件名（commit d7f9353 误提交进产物目录）
INCIDENT_ARTIFACT_NAME = "art_6798aca87b3fc42b3f93620fc3484c710d3b0101.py"

_SOURCE_SUFFIXES = {".py", ".pyc"}


def _find_source_files(root: Path) -> list[Path]:
    """列出数据目录内混入的源码文件（产物目录只允许 art_*.{音频后缀}）。"""
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
    )


def test_detects_incident_python_file(tmp_path: Path):
    (tmp_path / INCIDENT_ARTIFACT_NAME).write_text("def test_x():\n    pass\n", encoding="utf-8")

    violations = _find_source_files(tmp_path)

    assert [p.name for p in violations] == [INCIDENT_ARTIFACT_NAME]


def test_ignores_legit_audio_artifacts(tmp_path: Path):
    # 生产实际写法：平铺 art_{40hex}.{音频后缀}
    (tmp_path / "art_6798aca87b3fc42b3f93620fc3484c710d3b0101.mp3").write_bytes(b"ID3")
    (tmp_path / "art_1111111111111111111111111111111111111111.wav").write_bytes(b"RIFF")
    # 设计文档规划的分片写法，同样不应误报
    shard = tmp_path / "ar" / "t6"
    shard.mkdir(parents=True)
    (shard / "art_2222222222222222222222222222222222222222.m4a").write_bytes(b"ftyp")

    assert _find_source_files(tmp_path) == []


def test_flags_pyc_and_nested_source(tmp_path: Path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / f"{INCIDENT_ARTIFACT_NAME}c").write_bytes(b"\x00")
    nested = tmp_path / "ar" / "t6"
    nested.mkdir(parents=True)
    (nested / "leaked_helper.py").write_text("", encoding="utf-8")

    names = sorted(p.name for p in _find_source_files(tmp_path))

    assert names == sorted([f"{INCIDENT_ARTIFACT_NAME}c", "leaked_helper.py"])


def test_missing_root_is_clean(tmp_path: Path):
    assert _find_source_files(tmp_path / "not_created_yet") == []


def test_real_scene_artifact_root_has_no_source_files():
    if not SCENE_ARTIFACT_ROOT.exists():
        pytest.skip("场景产物根尚不存在")

    violations = _find_source_files(SCENE_ARTIFACT_ROOT)

    assert not violations, (
        f"场景音频产物目录混入源码文件：{[str(p) for p in violations]}。"
        f"该目录只允许 art_*.{{音频后缀}} 产物；测试与源码请放 backend/tests/。"
        "注意：源码文件在此会被 pytest 收集，ROOT_DIR 推导也跟着错位。"
    )
