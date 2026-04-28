import pytest
import requests

from app.services.agents.aliyun_embeddings import AliyunEmbeddings, EmbeddingRequestError


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        return self._payload


def test_aliyun_embeddings_raise_when_http_request_fails(monkeypatch):
    def _fake_post(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr("app.services.agents.aliyun_embeddings.requests.post", _fake_post)

    embeddings = AliyunEmbeddings(api_key="test-key", api_base="https://example.com", model="text-embedding-v4")

    with pytest.raises(EmbeddingRequestError):
        embeddings.embed_query("测试文本")


def test_aliyun_embeddings_raise_when_response_has_no_data(monkeypatch):
    monkeypatch.setattr(
        "app.services.agents.aliyun_embeddings.requests.post",
        lambda *args, **kwargs: _FakeResponse(payload={"data": []}),
    )

    embeddings = AliyunEmbeddings(api_key="test-key", api_base="https://example.com", model="text-embedding-v4")

    with pytest.raises(EmbeddingRequestError):
        embeddings.embed_query("测试文本")
