# -*- coding: utf-8 -*-
"""W2 调用方管理 CLI 测试：在一次性 sqlite 库上跑发卡/吊销全流程并验证鉴权即时联动。"""
import pytest

from router_gateway.admin import client as client_cli
from router_gateway.api.auth import InvalidApiKey, authenticate
from router_gateway.db import JobRepository, get_engine, make_session_factory
from router_gateway.db.init_db import init_schema


def _parse_create(output: str):
    """从 create 的 key=value 输出解析 id 与 api_key。"""
    fields = dict(part.split("=", 1) for part in output.strip().split(" ")
                  if "=" in part)
    return fields["id"], fields["api_key"]


@pytest.fixture()
def repo(monkeypatch, tmp_path):
    db_path = tmp_path / "admin.db"
    monkeypatch.setenv("ROUTER_GATEWAY_DATABASE_URL", f"sqlite:///{db_path}")
    engine = get_engine(f"sqlite:///{db_path}")
    init_schema(engine)
    yield JobRepository(make_session_factory(engine))
    engine.dispose()


def test_生成器两次发卡产生不同的无空格随机key():
    k1 = client_cli.generate_api_key()
    k2 = client_cli.generate_api_key()
    assert k1 != k2 and len(k1) >= 32
    assert " " not in k1 and " " not in k2


def test_create发卡后该key立即可通过鉴权(capsys, repo):
    rc = client_cli.main(["create", "--name", "合作方甲"])
    assert rc == 0
    client_id, api_key = _parse_create(capsys.readouterr().out)

    client = authenticate(repo.get_client_by_api_key, f"Bearer {api_key}")
    assert client.id == client_id and client.enabled is True


def test_两次create生成不同key且互不影响(capsys, repo):
    client_cli.main(["create", "--name", "甲"])
    _, key1 = _parse_create(capsys.readouterr().out)
    client_cli.main(["create", "--name", "乙"])
    _, key2 = _parse_create(capsys.readouterr().out)
    assert key1 != key2

    assert authenticate(repo.get_client_by_api_key,
                        f"Bearer {key1}").enabled is True
    assert authenticate(repo.get_client_by_api_key,
                        f"Bearer {key2}").enabled is True


def test_disable按client_id吊销后该key立即401另一key仍可用(capsys, repo):
    client_cli.main(["create", "--name", "甲"])
    _, key1 = _parse_create(capsys.readouterr().out)
    client_cli.main(["create", "--name", "乙"])
    _, key2 = _parse_create(capsys.readouterr().out)

    client1 = repo.get_client_by_api_key(key1)
    rc = client_cli.main(["disable", "--id", client1.id])
    assert rc == 0
    assert "已吊销" in capsys.readouterr().out

    with pytest.raises(InvalidApiKey):
        authenticate(repo.get_client_by_api_key, f"Bearer {key1}")
    assert authenticate(repo.get_client_by_api_key,
                        f"Bearer {key2}").enabled is True


def test_disable按id吊销即时生效(capsys, repo):
    client_cli.main(["create", "--name", "甲"])
    client_id, api_key = _parse_create(capsys.readouterr().out)

    assert client_cli.main(["disable", "--id", client_id]) == 0
    with pytest.raises(InvalidApiKey):
        authenticate(repo.get_client_by_api_key, f"Bearer {api_key}")


def test_disable不接受命令行api_key避免秘密进入进程参数(repo):
    with pytest.raises(SystemExit):
        client_cli.main(["disable", "--api-key", "secret"])


def test_disable不存在的client返回1且输出到stderr(capsys, repo):
    rc = client_cli.main(["disable", "--id", "no-such-client"])
    assert rc == 1
    assert "未找到" in capsys.readouterr().err


def test_cli在未初始化的空库上可直接发卡(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "fresh.db"
    monkeypatch.setenv("ROUTER_GATEWAY_DATABASE_URL", f"sqlite:///{db_path}")

    assert client_cli.main(["create", "--name", "首名调用方"]) == 0
    _, api_key = _parse_create(capsys.readouterr().out)

    engine = get_engine(f"sqlite:///{db_path}")
    try:
        got = JobRepository(make_session_factory(engine)) \
            .get_client_by_api_key(api_key)
        assert got is not None and got.enabled is True
    finally:
        engine.dispose()
