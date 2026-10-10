"""Controlled HTTP wire limits/redaction; no DNS, credential or provider I/O."""
import unittest
import asyncio
from multidict import CIMultiDict
from unittest.mock import patch
from app.collection.current_aggregate import CurrentOddsTransport
from app.collection.current_quota import QuotaStop

class Content:
    def __init__(self,body):self.body=body
    async def iter_chunked(self,size):
        for i in range(0,len(self.body),size):yield self.body[i:i+size]
class Response:
    def __init__(self,body=b'[]',status=200,headers=None):
        self.status=status;self.headers=headers or {'x-requests-used':'20','x-requests-remaining':'480','x-requests-last':'0'};self.content=Content(body)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
class Client:
    def __init__(self,response):self.response=response;self.calls=[];self.closed=False
    def get(self,url,**kwargs):self.calls.append((url,kwargs));return self.response
    async def close(self):self.closed=True

class WireSafety(unittest.IsolatedAsyncioTestCase):
    async def wire(self,response):
        transport=CurrentOddsTransport();client=Client(response)
        with patch('app.collection.current_aggregate.aiohttp.ClientSession',return_value=client):
            try:
                result=await transport.request(dict(path='/v4/sports',params={}), 'CONTROLLED-dummy-key')
                return result,client
            finally:await transport.close()
    async def test_fixed_destination_no_redirect_retry_or_proxy_and_sanitized_headers(self):
        result,client=await self.wire(Response(headers={'x-requests-used':'not-a-number','x-requests-remaining':'480','x-requests-last':'0'}))
        self.assertEqual(client.calls[0][0],'https://api.the-odds-api.com/v4/sports')
        self.assertFalse(client.calls[0][1]['allow_redirects']);self.assertFalse(client._retry_connection)
        self.assertEqual(result['headers'][0][1],'invalid');self.assertTrue(client.closed)
    async def test_secret_echo_raw_and_base64_are_suppressed(self):
        import base64
        for body in (b'CONTROLLED-dummy-key',base64.b64encode(b'CONTROLLED-dummy-key')):
            with self.assertRaisesRegex(QuotaStop,'secret_echo'):await self.wire(Response(body=body))
    async def test_no_error_body_retention_and_rate_limit_no_retry(self):
        result,client=await self.wire(Response(body=b'provider error content',status=429))
        self.assertEqual(result['body'],b'');self.assertEqual(result['status'],429);self.assertEqual(len(client.calls),1)
    async def test_body_and_compression_bounds(self):
        with self.assertRaisesRegex(QuotaStop,'byte_cap'):await self.wire(Response(body=b'x'*(2*1024*1024+1)))
        with self.assertRaisesRegex(QuotaStop,'encoding'):await self.wire(Response(headers={'Content-Encoding':'gzip'}))

    async def test_headers_survive_cancelled_body_and_duplicates_are_not_collapsed(self):
        response=Response(headers=CIMultiDict([('X-Requests-Used','23'),('X-Requests-Remaining','477'),('X-Requests-Last','3'),('x-requests-last','3')]))
        class CancelledContent:
            async def iter_chunked(self,size):
                raise asyncio.CancelledError()
                yield b''
        response.content=CancelledContent();transport=CurrentOddsTransport();client=Client(response)
        with patch('app.collection.current_aggregate.aiohttp.ClientSession',return_value=client):
            with self.assertRaises(asyncio.CancelledError):await transport.request(dict(path='/v4/sports',params={}), 'CONTROLLED-dummy-key')
        self.assertEqual(transport.response_receipt['status'],200)
        from app.collection.current_quota import headers,QuotaStop
        with self.assertRaisesRegex(QuotaStop,'missing_duplicate'):headers(transport.response_receipt['headers'])
        self.assertEqual(len(client.calls),1);await transport.close()
