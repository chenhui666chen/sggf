from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from types import SimpleNamespace

import pytest

from router_gateway.assets import delivery, safe_fetch
from router_gateway.assets.oss_client import OssClient, OssConfig


def test_fetch_to_file_uses_validated_connection_and_bounded_reads(tmp_path, monkeypatch):
    payload = b"video" * 300000
    headers = Message()
    headers["Content-Type"] = "video/mp4"
    headers["Content-Length"] = str(len(payload))
    response = SimpleNamespace(status=200, headers=headers)
    stream = BytesIO(payload)
    reads = []

    def read(amount):
        reads.append(amount)
        return stream.read(amount)

    response.read1 = read
    connection = SimpleNamespace(sock=SimpleNamespace(settimeout=lambda timeout: None),
        request=lambda *args, **kwargs: None, getresponse=lambda: response, close=lambda: None)
    monkeypatch.setattr(safe_fetch, "_open_public_connection", lambda parts, timeout: connection, raising=False)
    target = tmp_path / "video.mp4"
    safe_fetch.fetch_to_file("https://video.example/output", target,
        max_bytes=len(payload), expected_content_types=("video/mp4",))
    assert target.read_bytes() == payload
    assert max(reads) <= 1024 * 1024


def test_public_connection_pins_dns_and_preserves_tls_hostname(monkeypatch):
    dns_calls = []
    connected = []
    server_names = []
    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", lambda *args, **kwargs:
        dns_calls.append(args[0]) or [(2, 1, 6, "", ("8.8.8.8", 443))])
    fake_socket = SimpleNamespace(settimeout=lambda timeout: None,
        connect=lambda address: connected.append(address), close=lambda: None)
    monkeypatch.setattr(safe_fetch.socket, "socket", lambda *args: fake_socket)
    monkeypatch.setattr(safe_fetch, "_tls_context", lambda: SimpleNamespace(
        wrap_socket=lambda sock, server_hostname: server_names.append(server_hostname) or sock), raising=False)
    connection = safe_fetch._open_public_connection(
        safe_fetch.validate_public_url("https://video.example/output", resolve_dns=False), 10)
    connection.connect()
    assert dns_calls == ["video.example"]
    assert connected == [("8.8.8.8", 443)]
    assert server_names == ["video.example"]


def test_oss_put_file_passes_open_stream_and_exact_length(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"large-file-test")
    seen = []

    def send(method, url, headers, body, timeout):
        assert hasattr(body, "read")
        assert headers["Content-Length"] == str(source.stat().st_size)
        seen.append(body.read())
        return 200, {}, b""

    client = OssClient(OssConfig("test", "oss.example", "test", "test"),
        transport=SimpleNamespace(send=send))
    client.put_file("test.mp4", source, "video/mp4")
    assert seen == [b"large-file-test"]


def test_file_delivery_uploads_file_and_removes_temporary_outputs(monkeypatch):
    paths = []

    def download(url, path, **kwargs):
        path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"content")

    def sanitize(source, target, **kwargs):
        target.write_bytes(source.read_bytes())

    def upload(key, path, content_type):
        assert path.exists()
        paths.append(path)
        return "https://own.example/video.mp4"

    deliverer = delivery.FileContentDeliverer(SimpleNamespace(put_file=upload),
        own_hosts=(), downloader=download, sanitizer=sanitize, probe=lambda path: {})
    assert deliverer.deliver("job", datetime.now(timezone.utc), "https://source.example/video") == "https://own.example/video.mp4"
    assert paths and not paths[0].exists()


@pytest.mark.parametrize("status,length,content_type,payload", [
    (302, "4", "video/mp4", b"body"),
    (200, "100", "video/mp4", b"short"),
    (200, "4", "text/html", b"body"),
    (200, "", "video/mp4", b"too-large"),
])
def test_streaming_download_rejects_redirect_truncation_wrong_type_and_overflow(
        tmp_path, monkeypatch, status, length, content_type, payload):
    headers = Message()
    headers["Content-Type"] = content_type
    if length:
        headers["Content-Length"] = length
    response = SimpleNamespace(status=status, headers=headers, read1=BytesIO(payload).read)
    closed = []
    connection = SimpleNamespace(sock=None, request=lambda *args, **kwargs: None,
        getresponse=lambda: response, close=lambda: closed.append(True))
    monkeypatch.setattr(safe_fetch, "_open_public_connection", lambda parts, timeout: connection)
    with pytest.raises(safe_fetch.SafeFetchError):
        safe_fetch.fetch_to_file("https://video.example/output", tmp_path / "output",
            max_bytes=5, expected_content_types=("video/mp4",))
    assert closed == [True]


@pytest.mark.parametrize("streams,duration", [([], "1"), ([{"codec_type": "audio"}], "1"),
    ([{"codec_type": "video", "width": 160, "height": 120}], "nan"),
    ([{"codec_type": "video", "width": 0, "height": 120}], "1")])
def test_technical_probe_rejects_missing_video_invalid_dimensions_and_duration(tmp_path, monkeypatch, streams, duration):
    import json

    monkeypatch.setattr(delivery.shutil, "which", lambda name: "ffprobe")
    monkeypatch.setattr(delivery.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=0, stdout=json.dumps({"streams": streams, "format": {"duration": duration}}).encode()))
    with pytest.raises(delivery.DeliveryError):
        delivery.probe_video_file(tmp_path / "fake.mp4")
