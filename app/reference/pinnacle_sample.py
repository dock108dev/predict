"""Explicit one-request owner-approved B4 sample. No startup hook, retries or fallback."""
import asyncio
from datetime import datetime,timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import os
import httpx
from app.reference.odds_credentials import SERVICE,ACCOUNT,REFERENCE

ENDPOINT='https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds'
PARAMS=dict(bookmakers='pinnacle',markets='h2h',oddsFormat='decimal',dateFormat='iso')
LIMIT=256*1024
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'evidence/b4-pinnacle-sample-20260921'

def now():return datetime.now(timezone.utc).isoformat()
def save(folder,name,value):
    with (folder/name).open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())

async def capture(folder,key,*,transport=None):
    """Called only after preflight; durable attempt precedes the single HTTP call."""
    save(folder,'attempt.json',dict(started_at=now(),endpoint=ENDPOINT,params=PARAMS,
        credential_reference=REFERENCE,requests_authorized=1,planned_credits=1,body_limit=LIMIT,timeout_seconds=20,
        retries=0,approval='Owner explicit B4 NFL Pinnacle sample authorization',attempt_consumed=True))
    result=dict(requests_attempted=1,started_at=now(),status=None,headers={},outcome='failed',body_complete=False)
    body=bytearray()
    # This dedicated executable must never log authenticated request URLs.
    logging.disable(logging.CRITICAL)
    try:
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=20) as client:
                async with client.stream('GET',ENDPOINT,params=dict(PARAMS,apiKey=key),headers={'Accept-Encoding':'identity'}) as response:
                    result.update(status=response.status_code,headers={k:v for k,v in response.headers.items() if k in ('x-requests-last','x-requests-used','x-requests-remaining','date')})
                    async for chunk in response.aiter_bytes():
                        remaining=LIMIT-len(body)
                        body.extend(chunk[:remaining])
                        if len(chunk)>remaining:
                            result['outcome']='oversize';break
                    else:result['body_complete']=True
                    result['received_at']=now()
                    if result['body_complete']:
                        if response.status_code!=200:result['outcome']='http_failure'
                        elif result['headers'].get('x-requests-last') not in ('0','1'):result['outcome']='unexpected_or_unknown_cost'
                        else:result['outcome']='received'
    except Exception as exc:
        result.update(outcome='transport_failure',error_type=type(exc).__name__,received_at=now())
    result.update(body_bytes=len(body),body_sha256=sha256(body).hexdigest(),reserved_credits=1)
    if key.encode() in body or any(key in str(v) for v in result['headers'].values()):
        result.update(outcome='credential_echo_not_retained',headers={},body_retained=False)
    else:
        with (folder/'response.bin').open('xb') as f:f.write(body);f.flush();os.fsync(f.fileno())
        result['body_retained']=True
    save(folder,'result.json',result)
    return result

def main():
    os.umask(0o077)
    if OUTPUT.exists():raise SystemExit('Sample directory already exists. Stop: do not repeat this allowance.')
    from keyring.backends.macOS import Keyring
    raw=Keyring().get_password(SERVICE,ACCOUNT)
    if not raw:raise SystemExit('Local key is not configured. No request made.')
    try:
        value=json.loads(raw);key=value['api_key']
        if value.get('plan')!='free' or value.get('monthly_credits')!=500 or value.get('confirmation')!='owner-local account-plan check' or not isinstance(key,str) or not key:raise ValueError()
    except (ValueError,KeyError,TypeError):raise SystemExit('Free-plan local preflight failed. No request made.')
    OUTPUT.mkdir() # exclusive claim: even failure/crash cannot be restarted automatically
    save(OUTPUT,'preflight.json',dict(at=now(),credential_reference=REFERENCE,plan='free',monthly_credits=500,plan_evidence='owner-local confirmation; not independently inferred from API',kenpom='deferred',prediction_collection=False))
    try:result=asyncio.run(capture(OUTPUT,key))
    except Exception:raise SystemExit('Sample stopped; inspect sanitized local evidence. Do not retry.') from None
    print(json.dumps(dict(outcome=result['outcome'],status=result['status'],quota=result['headers'],evidence=str(OUTPUT))))

if __name__=='__main__':main()
