import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource
from app.services.model_catalog_sync import (
    CatalogSeed,
    ModelCatalogSyncService,
    SourceVerification,
    serialize_model_catalog_entry,
)


def build_seed(**overrides):
    payload = {
        "model_key": "demo-model",
        "name": "Demo Model",
        "provider": "demo",
        "category": "llm",
        "subcategory": "创作写作",
        "model_family": "Demo",
        "config_source": "llm_models.yaml",
        "status": "active",
        "summary": "用于测试的模型。",
        "recommended_scenarios": ["测试场景"],
        "limitations": ["测试限制"],
        "integration_notes": ["测试说明"],
        "documentation_url": "https://example.com/doc",
        "source_urls": ["https://example.com/doc", "https://example.com/price"],
        "tags": ["demo"],
        "modalities": ["text_generation"],
        "capabilities": [{"name": "creative", "level": "native"}],
        "constraints": {"max_context_tokens": 8192},
        "performance": {"quality_score": 8.5},
        "routing": {"task_types": ["chapter"]},
        "default_params": {"temperature": 0.7},
        "raw_config": {"id": "demo-model"},
    }
    payload.update(overrides)
    return CatalogSeed(**payload)


class StubClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    def get(self, url: str) -> httpx.Response:
        return self._response


def build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ModelCatalogEntry.__table__, ModelCatalogSource.__table__])
    return TestingSession


def test_model_catalog_loads_all_seed_models():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")

    seeds = service.load_catalog_seeds()
    seed_map = {seed.model_key: seed for seed in seeds}

    assert len(seeds) >= 18
    assert seed_map["qwen3-max"].category == "llm"
    assert seed_map["qwen3-vl-plus"].category == "multimodal"
    assert seed_map["wan2.6-t2i"].category == "image"
    assert seed_map["mureka-o1-instrumental"].category == "audio"
    assert seed_map["vidu-timing2audio"].subcategory == "可控时序音效"
    assert seed_map["qwen3-max"].raw_config["catalog_profile"]["system_role"].startswith("你是中文长篇小说创作")
    assert "创作主力" in seed_map["qwen3-max"].raw_config["catalog_profile"]["tooling_badges"]


def test_model_catalog_sync_persists_entries_and_sources(monkeypatch):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed()

    verification_time = datetime.now(timezone.utc)
    verifications = [
        SourceVerification(
            url="https://example.com/doc",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Demo Model 官方文档",
            page_excerpt="Demo Model supports text generation.",
            matched_keywords=["alias:demo model", "modality:text generation"],
            verification_note="校验通过",
            raw_metadata={"final_url": "https://example.com/doc"},
            fetched_at=verification_time,
            score=0.9,
        ),
        SourceVerification(
            url="https://example.com/price",
            source_type="reference",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=False,
            page_title="Demo Pricing",
            page_excerpt="Pricing page",
            matched_keywords=["provider:demo"],
            verification_note="可达但弱匹配",
            raw_metadata={"final_url": "https://example.com/price"},
            fetched_at=verification_time,
            score=0.5,
        ),
    ]

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed])
    monkeypatch.setattr(service, "_verify_seed", lambda _seed: verifications)

    result = service.sync_catalog(db, force_refresh=True)

    entry = db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == "demo-model").first()
    sources = db.query(ModelCatalogSource).filter(ModelCatalogSource.entry_id == entry.id).all()

    assert result["processed"] == 1
    assert result["verified"] == 1
    assert entry is not None
    assert entry.verification_status == "verified"
    assert entry.reachable_source_count == 2
    assert entry.verified_source_count == 1
    assert len(sources) == 2

    db.close()


def test_model_catalog_sync_writes_runtime_snapshot(monkeypatch, tmp_path):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=tmp_path)
    seed = build_seed(
        model_key="snapshot-model",
        source_urls=["https://example.com/doc", "https://example.com/price"],
    )

    verification_time = datetime.now(timezone.utc)
    verifications = [
        SourceVerification(
            url="https://example.com/doc",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Snapshot Model 官方文档",
            page_excerpt="Snapshot Model supports text generation.",
            matched_keywords=["alias:snapshot model"],
            verification_note="校验通过",
            raw_metadata={"final_url": "https://example.com/doc"},
            fetched_at=verification_time,
            score=0.9,
        ),
        SourceVerification(
            url="https://example.com/price",
            source_type="reference",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=False,
            page_title="Snapshot Pricing",
            page_excerpt="Pricing page",
            matched_keywords=["provider:demo"],
            verification_note="可达但弱匹配",
            raw_metadata={"final_url": "https://example.com/price"},
            fetched_at=verification_time,
            score=0.5,
        ),
    ]

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed])
    monkeypatch.setattr(service, "_verify_seed", lambda _seed: verifications)

    result = service.sync_catalog(db, force_refresh=True)

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["runtime_snapshot_updated"] is True
    assert result["runtime_snapshot_path"] == str(snapshot_path)
    assert payload["entry_count"] == 1
    assert payload["entries"]["snapshot-model"]["verification_status"] == "verified"
    assert payload["entries"]["snapshot-model"]["verified_source_count"] == 1
    assert payload["entries"]["snapshot-model"]["reachable_source_count"] == 2
    assert payload["entries"]["snapshot-model"]["capability_hints"]["supports_reference_images"] is False

    db.close()


def test_model_catalog_runtime_snapshot_includes_task_constraints(monkeypatch, tmp_path):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=tmp_path)
    seed = build_seed(
        model_key="runtime-video-model",
        name="Runtime Video Model",
        category="video",
        subcategory="视频生成",
        modalities=["image_to_video"],
        constraints={
            "duration": [3.0, 5.0, 10.0],
            "ratios": ["16:9"],
            "min_width": 480,
            "max_width": 1920,
            "min_height": 480,
            "max_height": 1080,
            "max_batch_size": 1,
        },
        raw_config={
            "id": "runtime-video-model",
            "detailed_specs": {
                "video_generation": {
                    "camera_control": {
                        "enabled": True,
                    },
                    "basic_params": {
                        "duration": {
                            "supported_values": [3.0, 5.0, 15.0],
                        },
                        "resolution": {
                            "options": ["720P", "1080P"],
                            "specs": [
                                {"value": "720P", "width": 1280, "height": 720},
                                {"value": "1080P", "width": 1920, "height": 1080},
                            ],
                        },
                        "aspect_ratio": {
                            "supported": ["16:9", "1:1"],
                        },
                    }
                }
            },
        },
    )

    verification_time = datetime.now(timezone.utc)
    verifications = [
        SourceVerification(
            url="https://example.com/doc",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Runtime Video Model",
            page_excerpt="Runtime Video Model supports image to video.",
            matched_keywords=["alias:runtime video model"],
            verification_note="校验通过",
            raw_metadata={"final_url": "https://example.com/doc"},
            fetched_at=verification_time,
            score=0.9,
        ),
    ]

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed])
    monkeypatch.setattr(service, "_verify_seed", lambda _seed: verifications)

    result = service.sync_catalog(db, force_refresh=True)

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    capability_hints = payload["entries"]["runtime-video-model"]["capability_hints"]
    task_constraints = payload["entries"]["runtime-video-model"]["task_constraints"]

    assert result["runtime_snapshot_updated"] is True
    assert capability_hints["supports_camera_control"] is True
    assert task_constraints["duration_values"] == [3.0, 5.0, 15.0]
    assert task_constraints["ratio_values"] == ["16:9", "1:1"]
    assert task_constraints["min_width"] == 480
    assert task_constraints["max_width"] == 1920
    assert task_constraints["resolution_options"] == ["720P", "1080P"]

    db.close()


def test_model_catalog_verification_matches_model_from_page_body():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed(
        model_key="qwen3-max",
        name="Qwen3 Max",
        provider="alibaba",
        category="llm",
        subcategory="创作写作",
        model_family="Qwen3",
        documentation_url="https://help.aliyun.com/zh/model-studio/models",
        source_urls=["https://help.aliyun.com/zh/model-studio/models"],
        tags=["creative", "alibaba"],
    )

    html = """
    <html>
      <head>
        <title>模型大全</title>
        <meta name="description" content="阿里云百炼模型列表" />
      </head>
      <body>
        <div>{padding}</div>
        <section>旗舰模型 qwen3-max 适合复杂任务和文本生成。</section>
      </body>
    </html>
    """.format(padding="占位内容 " * 600)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://help.aliyun.com/zh/model-studio/models"),
        text=html,
        headers={"content-type": "text/html"},
    )

    verification = service._verify_single_source(
        StubClient(response),
        seed,
        ("documentation", "https://help.aliyun.com/zh/model-studio/models"),
    )

    assert verification.reachable is True
    assert verification.verified is True
    assert "alias:qwen3-max" in verification.matched_keywords
    assert any(keyword.startswith("provider:") for keyword in verification.matched_keywords)


def test_model_catalog_verification_marks_soft_404_as_unreachable():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed(
        model_key="qwen-long",
        name="Qwen Long",
        provider="alibaba",
        subcategory="长上下文",
    )
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://help.aliyun.com/zh/model-studio/long-context"),
        text="""
        <html>
          <head><title>404错误页-阿里云帮助中心</title></head>
          <body>页面不存在，请检查链接。</body>
        </html>
        """,
        headers={"content-type": "text/html"},
    )

    verification = service._verify_single_source(
        StubClient(response),
        seed,
        ("documentation", "https://help.aliyun.com/zh/model-studio/long-context"),
    )

    assert verification.http_status == 200
    assert verification.reachable is False
    assert verification.verified is False
    assert verification.score == 0.0
    assert "错误页" in verification.verification_note


def test_model_catalog_verification_accepts_wan26_canonical_keywords():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed(
        model_key="wan2.6-t2i",
        name="Wan 2.6 Text-to-Image",
        provider="alibaba",
        category="image",
        subcategory="文生图",
        model_family="Wan 2.6",
        documentation_url="https://help.aliyun.com/zh/model-studio/text-to-image-api-reference",
        source_urls=["https://help.aliyun.com/zh/model-studio/text-to-image-api-reference"],
        modalities=["text_to_image"],
    )
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://help.aliyun.com/zh/model-studio/text-to-image-api-reference"),
        text="""
        <html>
          <head>
            <title>文生图 API</title>
            <meta name="description" content="阿里云百炼图像生成接口，支持 wan2.6-t2i 文生图模式。" />
          </head>
          <body>wan2.6-t2i 支持高质量文生图与风格化图像生成。</body>
        </html>
        """,
        headers={"content-type": "text/html"},
    )

    verification = service._verify_single_source(
        StubClient(response),
        seed,
        ("documentation", "https://help.aliyun.com/zh/model-studio/text-to-image-api-reference"),
    )

    assert verification.reachable is True
    assert verification.verified is True
    assert "alias:wan2.6-t2i" in verification.matched_keywords


def test_model_catalog_verification_uses_vidu_url_hint_when_page_lacks_alias():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed(
        model_key="vidu-timing2audio",
        name="Vidu Timing2Audio",
        provider="vidu",
        category="audio",
        subcategory="可控时序音效",
        model_family="Vidu Audio",
        documentation_url="https://www.vidu.cn/",
        source_urls=["https://www.vidu.cn/"],
        modalities=["text_to_audio", "timing_audio"],
        tags=["vidu", "audio", "timing-control"],
    )
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://www.vidu.cn/"),
        text="""
        <html>
          <head><title>Vidu Platform</title></head>
          <body>Generate timing-controlled audio with Vidu APIs.</body>
        </html>
        """,
        headers={"content-type": "text/html"},
    )

    verification = service._verify_single_source(
        StubClient(response),
        seed,
        ("documentation", "https://www.vidu.cn/"),
    )

    assert verification.reachable is True
    assert verification.verified is True
    assert "alias:vidu-timing2audio" in verification.matched_keywords
    assert "modality:text to audio" in verification.matched_keywords


def test_model_catalog_sync_reuses_cached_responses_for_duplicate_urls(monkeypatch):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed_a = build_seed(
        model_key="demo-model-a",
        name="Demo Model A",
        documentation_url="https://example.com/shared",
        source_urls=["https://example.com/shared"],
        raw_config={"id": "demo-model-a"},
    )
    seed_b = build_seed(
        model_key="demo-model-b",
        name="Demo Model B",
        documentation_url="https://example.com/shared",
        source_urls=["https://example.com/shared"],
        raw_config={"id": "demo-model-b"},
    )

    request_count = 0

    def fake_get(self, url: str):
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="""
            <html>
              <head><title>Shared Demo Models</title></head>
              <body>demo-model-a demo-model-b text generation</body>
            </html>
            """,
            headers={"content-type": "text/html"},
        )

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed_a, seed_b])
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = service.sync_catalog(db, force_refresh=True)

    assert request_count == 1
    assert result["processed"] == 2
    assert result["network_requests"] == 1
    assert result["cache_hits"] >= 1
    assert result["cached_response_count"] >= 1

    db.close()


def test_model_catalog_sync_skips_recent_entries_when_ttl_is_set(monkeypatch):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed()

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)
    entry.last_verified_at = datetime.now(timezone.utc)
    db.add(entry)
    db.commit()

    verify_called = False

    def fake_verify(_seed):
        nonlocal verify_called
        verify_called = True
        return []

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed])
    monkeypatch.setattr(service, "_verify_seed", fake_verify)

    result = service.sync_catalog(
        db,
        force_refresh=False,
        max_verification_age_hours=24,
    )

    assert verify_called is False
    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert result["skipped_recent"] == 1

    db.close()


def test_model_catalog_sync_refreshes_stale_entries_when_ttl_has_expired(monkeypatch):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = build_seed()

    stale_time = datetime.now(timezone.utc).replace(microsecond=0)
    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)
    entry.last_verified_at = stale_time - timedelta(hours=2)
    db.add(entry)
    db.commit()

    verification_time = datetime.now(timezone.utc)
    verifications = [
        SourceVerification(
            url="https://example.com/doc",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Demo Model Official",
            page_excerpt="Demo Model supports text generation.",
            matched_keywords=["alias:demo-model"],
            verification_note="verified",
            raw_metadata={"final_url": "https://example.com/doc"},
            fetched_at=verification_time,
            score=0.9,
        )
    ]

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [seed])
    monkeypatch.setattr(service, "_verify_seed", lambda _seed: verifications)

    result = service.sync_catalog(
        db,
        force_refresh=False,
        max_verification_age_hours=1,
    )

    assert result["processed"] == 1
    assert result["skipped"] == 0
    assert result["skipped_recent"] == 0

    db.close()


def test_model_catalog_sync_prunes_obsolete_entries_and_runtime_snapshot(monkeypatch, tmp_path):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=tmp_path)
    active_seed = build_seed(
        model_key="demo-model",
        source_urls=["https://example.com/doc"],
        raw_config={"id": "demo-model"},
    )
    obsolete_seed = build_seed(
        model_key="obsolete-image-model",
        name="Obsolete Image Model",
        provider="example",
        category="image",
        subcategory="文生图",
        model_family="Obsolete",
        source_urls=["https://example.com/obsolete"],
        modalities=["text_to_image"],
        raw_config={"id": "obsolete-image-model"},
    )

    obsolete_entry = ModelCatalogEntry(model_key=obsolete_seed.model_key)
    service._apply_seed_to_entry(obsolete_entry, obsolete_seed)
    db.add(obsolete_entry)
    db.flush()
    db.add(
        ModelCatalogSource(
            entry_id=obsolete_entry.id,
            url="https://example.com/obsolete",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Obsolete Model",
            page_excerpt="obsolete",
            matched_keywords=["alias:obsolete-image-model"],
            verification_note="obsolete",
            raw_metadata_json={"final_url": "https://example.com/obsolete"},
            fetched_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.expunge_all()

    verification_time = datetime.now(timezone.utc)
    verifications = [
        SourceVerification(
            url="https://example.com/doc",
            source_type="documentation",
            source_domain="example.com",
            http_status=200,
            reachable=True,
            verified=True,
            page_title="Demo Model Official",
            page_excerpt="Demo Model supports text generation.",
            matched_keywords=["alias:demo-model"],
            verification_note="verified",
            raw_metadata={"final_url": "https://example.com/doc"},
            fetched_at=verification_time,
            score=0.9,
        )
    ]

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [active_seed])
    monkeypatch.setattr(service, "_verify_seed", lambda _seed: verifications)

    result = service.sync_catalog(db, force_refresh=True)
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result["deleted_obsolete_entries"] == 1
    assert result["deleted_model_keys"] == ["obsolete-image-model"]
    assert (
        db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == "obsolete-image-model").first()
        is None
    )
    assert "obsolete-image-model" not in payload["entries"]
    assert "demo-model" in payload["entries"]

    db.close()


def test_model_catalog_get_entry_queryset_hides_obsolete_entries(monkeypatch):
    session_factory = build_session()
    db = session_factory()

    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    active_seed = build_seed(model_key="demo-model", raw_config={"id": "demo-model"})
    obsolete_seed = build_seed(
        model_key="obsolete-image-preview-model",
        name="Obsolete Image Preview Model",
        provider="example",
        category="image",
        subcategory="文生图",
        model_family="Obsolete",
        modalities=["text_to_image"],
        raw_config={"id": "obsolete-image-preview-model"},
    )

    active_entry = ModelCatalogEntry(model_key=active_seed.model_key)
    service._apply_seed_to_entry(active_entry, active_seed)
    obsolete_entry = ModelCatalogEntry(model_key=obsolete_seed.model_key)
    service._apply_seed_to_entry(obsolete_entry, obsolete_seed)
    db.add_all([active_entry, obsolete_entry])
    db.commit()

    monkeypatch.setattr(service, "load_catalog_seeds", lambda: [active_seed])

    entries = service.get_entry_queryset(db).order_by(ModelCatalogEntry.model_key).all()

    assert [entry.model_key for entry in entries] == ["demo-model"]

    db.close()


def test_model_catalog_serializer_exposes_layered_archives():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = next(item for item in service.load_catalog_seeds() if item.model_key == "qwen3-max")

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)

    light_payload = serialize_model_catalog_entry(entry)
    full_payload = serialize_model_catalog_entry(entry, include_archives=True)

    assert "project_modules" in light_payload
    assert "tooling_badges" in light_payload
    assert "identity_profile" not in light_payload

    assert full_payload["identity_profile"]["project_fit"]["modules"]
    assert full_payload["integration_profile"]["calling_stack"][0]["value"] == "ModelHub 统一调度"
    assert any(item["label"] == "Temperature" for item in full_payload["integration_profile"]["native_parameters"])
    assert full_payload["prompt_router_profile"]["system_role"]
    assert full_payload["deployment_profile"]["proxy_snippet"].startswith("location /proxy/llm/alibaba/qwen3-max")
    assert full_payload["resource_navigation"]["selection_hubs"][0]["url"] == "https://arena.ai"


def test_model_catalog_serializer_exposes_runtime_routing_signal(monkeypatch, tmp_path):
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = next(item for item in service.load_catalog_seeds() if item.model_key == "qwen3-max")

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "qwen3-max": {
                        "verification_status": "verified",
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)

    payload = serialize_model_catalog_entry(entry)

    assert payload["runtime_routing_signal"]["verification_status"] == "verified"
    assert payload["runtime_routing_signal"]["blocked"] is False


def test_model_catalog_serializer_exposes_runtime_constraints_and_hints(monkeypatch, tmp_path):
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = next(item for item in service.load_catalog_seeds() if item.model_key == "wan2.7-t2v")

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "verification_status": "verified",
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                        "capability_hints": {
                            "supports_camera_control": True,
                            "supports_reference_images": True,
                        },
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0, 15.0],
                            "ratio_values": ["16:9", "9:16", "1:1"],
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)

    payload = serialize_model_catalog_entry(entry)

    assert payload["runtime_capability_hints"]["supports_camera_control"] is True
    assert payload["runtime_task_constraints"]["duration_values"] == [3.0, 5.0, 10.0, 15.0]


def test_model_catalog_serializer_prefers_catalog_profile_overrides():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = next(item for item in service.load_catalog_seeds() if item.model_key == "qwen3-max")

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)

    payload = serialize_model_catalog_entry(entry, include_archives=True)

    assert payload["identity_profile"]["project_fit"]["role_summary"].startswith("当前模型是项目里的中文正文创作主力")
    assert payload["prompt_router_profile"]["system_role"].startswith("你是中文长篇小说创作与角色对话专家")
    assert any(
        item["title"] == "AI 编程工具识别模板"
        for item in payload["prompt_router_profile"]["prompt_patterns"]
    )
    assert "创作主力" in payload["integration_profile"]["tooling_badges"]
    assert payload["deployment_profile"]["project_entrypoints"][0]["value"] == "create_task_llm(task_type=\"chapter\")"


def test_model_catalog_serializer_exposes_generated_audio_archives():
    service = ModelCatalogSyncService(config_dir=ROOT_DIR.parent / "config")
    seed = next(item for item in service.load_catalog_seeds() if item.model_key == "mureka-o1-instrumental")

    entry = ModelCatalogEntry(model_key=seed.model_key)
    service._apply_seed_to_entry(entry, seed)

    payload = serialize_model_catalog_entry(entry, include_archives=True)
    native_parameters = payload["integration_profile"]["native_parameters"]
    parameter_labels = [item["label"] for item in native_parameters]

    assert payload["integration_profile"]["calling_stack"][1]["value"] == "POST /api/v1/asset-studio/audio"
    assert "Prompt" in parameter_labels
    assert "Duration" in parameter_labels
    assert "Voice / Speaker" not in parameter_labels
    assert payload["prompt_router_profile"]["system_role"].startswith("你是音乐提示词与配乐策略助手")
    assert any(item["title"] == "背景音乐模板" for item in payload["prompt_router_profile"]["prompt_patterns"])
