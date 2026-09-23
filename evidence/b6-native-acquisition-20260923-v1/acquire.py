"""One authorized public-document attempt. No credentials, retries or discovery."""
import asyncio, hashlib, json, os, resource, select, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import aiohttp
ROOT=Path(__file__).resolve().parent
PROPOSAL=ROOT.parent/'b6-native-review-20260923-v1/acquisition-proposal.md'
EVENT='KXNFLGAME-26SEP24ATLGB'
SERIES='https://api.elections.kalshi.com/trade-api/v2/series/KXNFLGAME'
FEES='https://api.elections.kalshi.com/trade-api/v2/events/fee_changes?event_ticker='+EVENT+'&limit=100'
DOCS=['https://kalshi.com/docs/kalshi-fee-schedule.pdf','https://docs.kalshi.com/getting_started/fee_rounding.md','https://docs.polymarket.us/fees.md']
MIB=1024*1024
class Stop(Exception): pass
def utc(): return datetime.now(timezone.utc).isoformat()
def sha(data): return hashlib.sha256(data).hexdigest()
def save(name,value):
    path=ROOT/name
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
class Attempt:
    def __init__(self):
        # Atomic marker before the first request. A consumed attempt cannot be resumed.
        with (ROOT/'consumed.json').open('x') as f:
            json.dump(dict(start=utc(),authorization='User approved this exact proposal once on demand',proposal_sha256=sha(PROPOSAL.read_bytes()),script_sha256=sha(Path(__file__).read_bytes()),max_attempts=8,total_seconds=90,credentials=False),f,indent=2)
        self.start=time.monotonic();self.log=[];self.total=0;self.allowed={SERIES,FEES,*DOCS};self.stop='';self.pending=[]
    def check(self):
        if time.monotonic()-self.start>=90: raise Stop('90-second hard deadline')
        if rss()>256*MIB: raise Stop('256 MiB process RSS limit')
        if sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())>64*MIB:raise Stop('64 MiB total output limit')
    def ledger(self):save('requests.json',self.log)
    async def get(self,url):
        self.check()
        if url not in self.allowed or urlsplit(url).scheme!='https':raise Stop('URL outside reviewed exact allowlist')
        if len(self.log)>=8 or any(r['url']==url for r in self.log):raise Stop('Attempt limit or duplicate request')
        number=len(self.log)+1
        record=dict(attempt=number,url=url,method='GET',start_utc=utc(),start_elapsed=time.monotonic()-self.start,request_headers={'Accept-Encoding':'identity'},credentials=False,redirect_followed=False)
        self.log.append(record);self.ledger()
        body=ROOT/f'{number:02d}-response.bin';hasher=hashlib.sha256();size=0
        try:
            # Separate connection/session per GET; no implicit keepalive retry.
            timeout=aiohttp.ClientTimeout(total=min(10,90-(time.monotonic()-self.start)))
            async with aiohttp.ClientSession(timeout=timeout,trust_env=False,auto_decompress=False,connector=aiohttp.TCPConnector(force_close=True),headers={'Accept-Encoding':'identity'}) as session:
                session._retry_connection=False
                async with session.get(url,allow_redirects=False) as response:
                    record.update(status=response.status,response_url=str(response.url),headers_received_utc=utc(),response_headers=list(response.headers.items()))
                    self.ledger()
                    with body.open('xb') as output:
                        async for chunk in response.content.iter_chunked(32768):
                            self.check()
                            if size+len(chunk)>2*MIB or self.total+len(chunk)>16*MIB:raise Stop('Response body/storage cap')
                            output.write(chunk);hasher.update(chunk);size+=len(chunk);self.total+=len(chunk)
                    record['complete_body']=True
                    if response.status!=200:raise Stop('HTTP status '+str(response.status)+'; no retry or redirect')
                    if str(response.url)!=url:raise Stop('Unexpected response URL')
                    if response.headers.get('Content-Encoding','identity').lower() not in ('','identity'):raise Stop('Unexpected encoded response; bytes retained without reinterpretation')
        except BaseException as exc:
            record['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            record.update(body=body.name if body.exists() else None,bytes=size,sha256=hasher.hexdigest(),end_utc=utc(),end_elapsed=time.monotonic()-self.start,peak_rss_bytes=rss())
            self.ledger();print(json.dumps({k:record.get(k) for k in ('attempt','url','status','bytes','error')}),flush=True)
        return body.read_bytes()
    async def run(self):
        series=json.loads(await self.get(SERIES))['series']
        if series.get('ticker')!='KXNFLGAME':raise Stop('Series scope mismatch')
        terms=series.get('contract_terms_url');save('series-link-review.json',dict(series='KXNFLGAME',contract_terms_url=terms,contract_url=series.get('contract_url'),state='Awaiting exact-reference review; no retrieval yet'))
        cursor='';complete=False
        for page in range(2):
            url=FEES if not cursor else FEES+'&'+urlencode({'cursor':cursor})
            self.allowed.add(url)
            changes=json.loads(await self.get(url))
            for row in changes['event_fee_changes']:
                if row.get('event_ticker')!=EVENT or row.get('series_ticker')!='KXNFLGAME':raise Stop('Event fee history scope mismatch')
            cursor=changes['cursor']
            if not isinstance(cursor,str):raise Stop('Ambiguous pagination cursor')
            if not cursor:complete=True;break
        if not complete:raise Stop('Pagination exhausted; history incomplete')
        for url in DOCS:await self.get(url)
        print(json.dumps(dict(awaiting_review=True,terms_url=terms,seconds_remaining=90-(time.monotonic()-self.start),instruction='Send JSON object with kalshi_terms_url equal to returned exact authoritative reference or null; us_terms_url only with exact directly-linked applicable evidence, otherwise null.')),flush=True)
        while not select.select([sys.stdin],[],[],0)[0]:
            self.check();await asyncio.sleep(.05)
        decision=json.loads(sys.stdin.readline());save('document-link-decision.json',decision)
        url=decision.get('kalshi_terms_url')
        if url:
            p=urlsplit(url)
            if url!=terms or p.scheme!='https' or p.username or p.password or p.fragment or p.port not in (None,443):raise Stop('Ambiguous or invalid Kalshi document linkage')
            self.allowed.add(url);await self.get(url)
        us=decision.get('us_terms_url')
        if us:
            # Direct exact link must occur in the acquired official fee document.
            fee_record=next(r for r in self.log if r['url']==DOCS[-1])
            text=(ROOT/fee_record['body']).read_text()
            p=urlsplit(us)
            if us not in text or p.scheme!='https' or p.hostname not in ('polymarket.us','www.polymarket.us','docs.polymarket.us') or not decision.get('us_exact_contract_applicability'):raise Stop('US authoritative exact-contract reference unresolved')
            self.allowed.add(us);await self.get(us)
        self.stop='Completed needed approved slots; unresolved/unneeded slots unused'
async def main():
    attempt=Attempt()
    try:
        async with asyncio.timeout(90): await attempt.run()
    except BaseException as exc:attempt.stop=type(exc).__name__+': '+str(exc)
    finally:
        save('result.json',dict(consumed=True,retry_allowed=False,stop_reason=attempt.stop,requests=len(attempt.log),retained_body_bytes=attempt.total,elapsed_seconds=time.monotonic()-attempt.start,peak_rss_bytes=rss(),closed_utc=utc(),credentials_accessed=False,streaming=False,credits=0,connections_closed=True))
        print((ROOT/'result.json').read_text(),flush=True)
if __name__=='__main__':asyncio.run(main())
