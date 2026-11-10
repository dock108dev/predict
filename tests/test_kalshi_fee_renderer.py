import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
from hashlib import sha256
from pathlib import Path
from shutil import which

from aiohttp.test_utils import TestClient, TestServer
import httpx
import pytest

from app.collection.kalshi_fee_refresh import FORMAT, SOURCE
from app.collection.kalshi_fee_renderer import ROUTE, application

NONCE = 'a' * 32


def test_receipts_bind_nonce_and_failed_official_origin():
    calls = []

    def origin(request):
        assert str(request.url) == SOURCE
        calls.append(request.method)
        return httpx.Response(429)

    async def scenario():
        async with TestClient(TestServer(application(transport=httpx.MockTransport(origin)))) as client:
            assert (await client.get(ROUTE, params={'request_id': NONCE, 'url': 'https://example.org'})).status == 400
            assert (await client.get(ROUTE, params=[('request_id', NONCE), ('request_id', NONCE)])).status == 400
            assert (await client.post(ROUTE, params={'request_id': NONCE})).status == 405
            response = await client.get(ROUTE, params={'request_id': NONCE})
            body = await response.json()
            assert response.status == 200 and response.headers['cache-control'] == 'no-store'
            assert body['format'] == FORMAT and body['request_id'] == NONCE
            assert body['source_url'] == SOURCE and body['origin_http_status'] == 429
            assert not body['complete'] and 'origin_sha256' not in body
            assert (await client.get(ROUTE, params={'request_id': 'b'*32})).status == 429
        assert calls == ['GET']

    asyncio.run(scenario())


@pytest.mark.skipif(not which('pdftotext'), reason='Poppler is a renderer deployment dependency')
def test_renderer_extracts_real_pdf_and_hashes_original_bytes():
    # A packaged PDF tests extraction only. It never becomes a fee approval.
    pdf = (Path(__file__).resolve().parents[1] /
           'app/fixtures/native-scoring-scope/source-type-kalshi-basketballtotals.pdf').read_bytes()

    def origin(request):
        assert str(request.url) == SOURCE and request.headers['cache-control'] == 'no-cache'
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)
        return httpx.Response(200, headers={'date': date}, stream=httpx.ByteStream(pdf))

    async def scenario():
        async with TestClient(TestServer(application(transport=httpx.MockTransport(origin)))) as client:
            response = await client.get(ROUTE, params={'request_id': NONCE})
            assert response.status == 200
            body = await response.json()
            assert body['origin_sha256'] == sha256(pdf).hexdigest()
            assert body['origin_http_status'] == 200 and body['complete']
            assert body['page_count'] == body['text'].count('\f') > 0
            assert body['text'].strip()

    asyncio.run(scenario())
