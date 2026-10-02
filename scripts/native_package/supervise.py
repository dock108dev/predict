"""Own one sealed server/control execution; no provider or credential implementation."""
import json,subprocess,sys,time
from pathlib import Path
import control,launch
P=Path(__file__).resolve().parent
launch.prepared(True)
server=None;result={}
try:
 with (P/'owned-server.log').open('x') as log:
  server=subprocess.Popen([sys.executable,str(P/'launch.py'),'--serve'],stdout=log,stderr=subprocess.STDOUT,cwd=launch.ROOT)
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   if server.poll() is not None:raise RuntimeError('Owned server exited before readiness')
   binding=control.request('/probe-binding')
   if binding.get('status')==200:break
   time.sleep(.2)
  else:raise RuntimeError('Owned server readiness deadline')
  # Exactly one control invocation. It durably consumes dispatch before Start.
  c=subprocess.run([sys.executable,str(P/'control.py'),'--run'],cwd=launch.ROOT,stdout=log,stderr=subprocess.STDOUT)
  result['control_exit']=c.returncode
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   status=control.request('/api/status');b=status.get('body',{})
   if status.get('status')==200 and not b.get('active') and b.get('state') not in ('stopping','running','starting'):
    result['settled_status']=b;break
   time.sleep(.5)
  else:result['cleanup_status_unsettled']=True
finally:
 if server is not None:
  server.terminate()
  try:server.wait(timeout=10)
  except subprocess.TimeoutExpired:server.kill();server.wait()
  result['owned_server_closed']=server.poll() is not None
 control.save('supervisor-result.json',result)
print(json.dumps(dict(control_exit=result.get('control_exit'),owned_server_closed=result.get('owned_server_closed'))))
