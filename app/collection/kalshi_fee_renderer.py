"""Fixed-origin rendering endpoint for a restricted, trusted HTTPS ingress.

Run behind TLS on a host with legitimate access to the official Kalshi PDF.
The loopback listener accepts only the installed worker's nonce and has no
caller-controlled fetch target. Use the normalized output for explicit review.
"""
import argparse
import asyncio
import re
from time import monotonic

from aiohttp import web
import httpx

from .kalshi_fee_refresh import FORMAT, SOURCE
from .public_fee_refresh import INDEX_BYTES, RetrievalFailed, fetch

ROUTE = '/kalshi-fee-rendering'
ATTEMPT_SECONDS = 4


async def render(pdf):
    if not pdf.startswith(b'%PDF-'):
        raise ValueError('invalid PDF')
    process = await asyncio.create_subprocess_exec(
        'pdftotext', '-enc', 'UTF-8', '-', '-', stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        async def send():
            process.stdin.write(pdf)
            await process.stdin.drain()
            process.stdin.close()

        async def read():
            result = bytearray()
            async for block in _chunks(process.stdout):
                result.extend(block)
                if len(result) > INDEX_BYTES // 2:
                    raise ValueError('PDF text too large')
            return result

        async with asyncio.TaskGroup() as group:
            group.create_task(send())
            received = group.create_task(read())
        if await process.wait() != 0:
            raise ValueError('PDF rendering failed')
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.stdout.read()
            await process.wait()
    raw = received.result().decode()
    pages = raw.split('\f')
    if not 2 <= len(pages) <= 101 or pages[-1].strip() or not all(page.strip() for page in pages[:-1]):
        raise ValueError('PDF pages incomplete')
    return raw, len(pages)-1


async def _chunks(reader):
    while block := await reader.read(32768):
        yield block


def application(*, transport=None, minimum_spacing=30):
    app = web.Application()
    lock = asyncio.Lock()
    last_started = float('-inf')
    no_cache = {'Cache-Control': 'no-store'}

    async def receipt(request):
        nonlocal last_started
        nonce = request.query.get('request_id', '')
        if list(request.query) != ['request_id'] or not re.fullmatch('[0-9a-f]{32}', nonce):
            raise web.HTTPBadRequest(headers=no_cache)
        if lock.locked() or monotonic()-last_started < minimum_spacing:
            raise web.HTTPTooManyRequests(headers=dict(no_cache, **{'Retry-After': str(minimum_spacing)}))
        async with lock:
            last_started = monotonic()
            result = dict(format=FORMAT, request_id=nonce, source_url=SOURCE, complete=False)
            try:
                async with asyncio.timeout(ATTEMPT_SECONDS), httpx.AsyncClient(
                        transport=transport, trust_env=False, follow_redirects=False) as client:
                    pdf, origin = await fetch(client, SOURCE, INDEX_BYTES, fresh=True)
                    text, pages = await render(pdf)
                result.update(origin_http_status=200, origin_retrieved_at=origin['retrieved_at'],
                              origin_sha256=origin['sha256'], text=text, page_count=pages, complete=True)
            except RetrievalFailed as exc:
                origin = exc.receipt
                # Failed origin status is evidence for the worker, but a
                # malformed or stale origin 200 is no qualifying rendering.
                if type(origin.get('http_status')) is not int or origin['http_status'] == 200:
                    raise web.HTTPBadGateway(headers=no_cache) from None
                result.update(origin_http_status=origin['http_status'], origin_retrieved_at=origin['retrieved_at'])
            except (OSError, ValueError, ExceptionGroup, httpx.HTTPError, TimeoutError):
                raise web.HTTPBadGateway(headers=no_cache) from None
            return web.json_response(result, headers=no_cache)

    app.router.add_get(ROUTE, receipt, allow_head=False)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    web.run_app(application(), host='127.0.0.1', port=args.port, access_log=None)


if __name__ == '__main__':
    main()
