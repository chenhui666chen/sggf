import asyncio

import httpx
import pytest

from app.services.video_gateway_client import VideoGatewayClient, VideoGatewayUnavailable


@pytest.mark.parametrize("body", ['invalid-json', '[]'])
def test_invalid_gateway_response_becomes_service_unavailable(monkeypatch, body):
    response = httpx.Response(200, text=body)

    class TransportClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return response

    monkeypatch.setattr(httpx, 'AsyncClient', TransportClient)
    client = VideoGatewayClient(base_url='http://gateway', token='test')
    with pytest.raises(VideoGatewayUnavailable):
        asyncio.run(client.metrics_overview())


def test_decimal_limits_are_serialized_for_internal_json(monkeypatch):
    from decimal import Decimal
    calls = []

    class TransportClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            import json
            json.dumps(kwargs['json'])
            calls.append(kwargs)
            return httpx.Response(200, json={'id': 'client'})

    monkeypatch.setattr(httpx, 'AsyncClient', TransportClient)
    client = VideoGatewayClient(base_url='http://gateway', token='test')
    asyncio.run(client.update_limits('client', {'daily_budget': Decimal('1.20')}))
    assert calls[0]['headers'] == {'X-Gateway-Internal-Token': 'test'}
