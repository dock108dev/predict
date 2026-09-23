import json
import logging
from pathlib import Path
import tempfile
import unittest
import httpx
from app.reference.pinnacle_sample import capture,LIMIT

class BoundedSample(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # The one-shot executable disables logging; restore it for later tests.
        self.addCleanup(logging.disable, logging.root.manager.disable)

    async def test_one_call_original_bytes_and_exclusive_attempt(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);calls=[];body=b'[]'
            async def handler(req):
                calls.append(req)
                self.assertTrue((root/'attempt.json').exists())
                self.assertEqual(req.url.params['bookmakers'],'pinnacle');self.assertEqual(req.url.params['markets'],'h2h')
                return httpx.Response(200,content=body,headers={'x-requests-last':'1','x-requests-remaining':'499'})
            result=await capture(root,'synthetic-placeholder',transport=httpx.MockTransport(handler))
            self.assertEqual(result['outcome'],'received');self.assertEqual((root/'response.bin').read_bytes(),body)
            with self.assertRaises(FileExistsError):await capture(root,'synthetic-placeholder',transport=httpx.MockTransport(handler))
            self.assertEqual(len(calls),1)
            self.assertNotIn('synthetic-placeholder',''.join(p.read_text() for p in root.iterdir()))

    async def test_failures_never_retry_and_do_not_leak(self):
        for status,body,headers,expected in [(429,b'limit',{},'http_failure'),(302,b'',{},'http_failure'),(200,b'[]',{'x-requests-last':'2'},'unexpected_or_unknown_cost'),(200,b'x'*(LIMIT+1),{'x-requests-last':'1'},'oversize'),(403,b'synthetic-placeholder',{},'credential_echo_not_retained')]:
            with tempfile.TemporaryDirectory() as t:
                calls=[]
                async def handler(req):calls.append(req);return httpx.Response(status,content=body,headers=headers)
                result=await capture(Path(t),'synthetic-placeholder',transport=httpx.MockTransport(handler))
                self.assertEqual(result['outcome'],expected);self.assertEqual(len(calls),1)
                self.assertLessEqual(result['body_bytes'],LIMIT)
                self.assertNotIn('synthetic-placeholder',''.join(p.read_text() for p in Path(t).iterdir()))
        with tempfile.TemporaryDirectory() as t:
            async def failed(req):raise httpx.ConnectError('sensitive synthetic-placeholder URL')
            result=await capture(Path(t),'synthetic-placeholder',transport=httpx.MockTransport(failed))
            self.assertEqual(result['outcome'],'transport_failure');self.assertEqual(result['error_type'],'ConnectError')
            self.assertNotIn('synthetic-placeholder',''.join(p.read_text() for p in Path(t).iterdir()))
