from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 让测试可以 import backend/app 下的包（app.*）
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from app.db.base import Base
from app.models.project import Project
from app.models.user import User
from app.models.dreamweaver import DreamweaverAsset, DreamweaverEpisode, DreamweaverProject, DreamweaverShot
from app.services.dreamweaver.persistence import build_contract_from_payload, persist_contract


def test_contract_build_and_persist_to_db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(username="u1", email="u1@example.com", password_hash="x")
    session.add(user)
    session.flush()

    project = Project(user_id=user.id, title="p1")
    session.add(project)
    session.flush()

    payload = {
        "storyboard": [
            {
                "scene_id": "S1",
                "shot_id": "S1-1",
                "desc": "shot 1",
                "duration_s": 3.0,
                "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
                "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
            }
        ],
        "keyframes": [{"path": "runs/run1/S1-1_head.png", "ratio": "16:9", "spec": {"prompt": "head"}}],
        "midframes": [{"path": "runs/run1/S1-1_mid.png", "ratio": "16:9", "spec": {"prompt": "mid"}}],
        "video_clips": [{"path": "runs/run1/S1-1.mp4", "duration": 3.0}],
        "merged_video": "runs/run1/merged.mp4",
        "plan": {"text": "plan"},
    }

    contract = build_contract_from_payload(
        run_id="run1",
        source_project_id=project.id,
        user_id=user.id,
        payload=payload,
        schema_version="0.2.0",
    )

    dw_project_id = persist_contract(
        session,
        contract=contract,
        status="completed",
        state="DONE",
        stage="done",
        progress=100,
    )

    assert session.query(DreamweaverProject).filter(DreamweaverProject.id == dw_project_id).count() == 1
    assert session.query(DreamweaverEpisode).count() == 1
    assert session.query(DreamweaverShot).count() == 1
    # head + mid + clip + merged
    assert session.query(DreamweaverAsset).count() >= 3

    row = session.query(DreamweaverProject).filter(DreamweaverProject.id == dw_project_id).first()
    assert row is not None
    assert row.contract_json is not None
    assert row.contract_json["run_id"] == "run1"
    assert row.schema_version == "0.2.0"
    assert row.contract_json["schema_version"] == "0.2.0"

    shot_row = session.query(DreamweaverShot).first()
    assert shot_row is not None
    assert shot_row.schema_version == "0.2.0"
    assert shot_row.constraints_json is not None
    assert shot_row.constraints_json["schema_version"] == "0.2.0"

    asset_row = session.query(DreamweaverAsset).first()
    assert asset_row is not None
    assert asset_row.schema_version == "0.2.0"
