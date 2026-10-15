# -*- coding: utf-8 -*-
import pytest

from router_gateway.assets.safe_fetch import SafeFetchError, validate_public_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/file.mp4",
    "http://10.0.0.1/file.mp4",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/file.mp4",
    "http://localhost/file.mp4",
])
def test_素材地址拒绝内网回环和元数据地址(url):
    with pytest.raises(SafeFetchError):
        validate_public_url(url, resolve_dns=False)


def test_素材地址拒绝用户凭证和非法端口():
    for url in ("https://user:pass@example.com/a", "https://example.com:99999/a"):
        with pytest.raises(SafeFetchError):
            validate_public_url(url, resolve_dns=False)
