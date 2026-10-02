"""Fresh component-baseline control; expected failure reproduction is evidence.

Restore the authority-hashed pre-repair history reader, the Git-baseline identical
resolution read loop, and original row decoder. Other current app code stays in
place. This is a component comparison, not a claim to recreate a full old checkout.
"""
import ast,asyncio,json,subprocess,sys,unittest
from pathlib import Path
from aiohttp import ClientSession
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));OUT=ROOT/'evidence/public-contract-integration-20261001-v1'
from app.dashboard import session_history,multi_game_server
from app.collection import journal_encoding
from app.collection.continuous import rss

history={ '__name__':'baseline_history_component','__file__':str(ROOT/'app/dashboard/session_history.py') }
exec(compile((OUT/'verification/pre-repair-session_history.py').read_text(),str(OUT/'verification/pre-repair-session_history.py'),'exec'),history)
session_history.verified=history['verified'];session_history.resolution_history=history['resolution_history']
decoder={'__name__':'baseline_decoder_component'}
exec(subprocess.check_output(['git','show','HEAD:app/collection/journal_encoding.py'],text=True),decoder)
journal_encoding.decode=decoder['decode']
source=(ROOT/'app/dashboard/multi_game_server.py').read_text();start=source.index('    async def resolution(req):');end=source.index('    async def catalog(req):',start)
old=(OUT/'verification/baseline-resolution-handler.py').read_text();source=source[:start]+'    '+old.rstrip()+'\n'+source[end:]
namespace=dict(vars(multi_game_server));exec(compile(source,str(ROOT/'app/dashboard/multi_game_server.py'),'exec'),namespace);multi_game_server.create_app=namespace['create_app']
requests=[];errors=[];request=ClientSession._request
async def traced(self,method,url,*args,**kwargs):
 response=await request(self,method,url,*args,**kwargs)
 text=str(url)
 if '/api/resolution' in text or '/api/stop' in text or '/api/start' in text:
  requests.append(dict(method=method,url=text,json=kwargs.get('json'),response_status=response.status,response=json.loads(await response.text()),peak_rss_bytes=rss()))
 return response
ClientSession._request=traced
original=multi_game_server.failure
def failure(module,operation,exc):
 errors.append(dict(operation=operation,exception=type(exc).__name__,reason=str(exc),peak_rss_bytes=rss()));original(module,operation,exc)
multi_game_server.failure=failure;namespace['failure']=failure
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_nfl_resolution.Lifecycle'))
expected=len(result.failures)==2 and not result.errors
value=dict(evidence_mode='synthetic',comparison='Restored pre-repair history/handler/decoder components; current app dependencies',tests_run=result.testsRun,expected_two_failures_reproduced=expected,requests=requests,errors=errors,rss_limit_bytes=268435456,publication_history_invented=False,production_limits_unchanged=True)
(OUT/'exact-failure-reproduction.json').write_text(json.dumps(value,indent=2)+'\n')
sys.exit(0 if expected else 1)
