"""Bounded subprocess fault matrix; retains stdout, exit status and verified prefixes."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
from app.collection.recovery import index,reopen_index

def run(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False);results=[]
    for mode in ('disk_full','short','partial','flush','fsync','terminal','export','manifest','report','race'):
        started=time.monotonic()
        p=subprocess.run([sys.executable,'-m','tests.e6_storage_fault_worker',str(root/mode),mode],capture_output=True,text=True,timeout=25)
        (root/(mode+'.stdout.json')).write_text(p.stdout)
        (root/(mode+'.stderr.txt')).write_text(p.stderr)
        assert p.returncode==3,(mode,p.returncode,p.stdout,p.stderr)
        value=json.loads(p.stdout);value['exit_code']=p.returncode;value['process_seconds']=time.monotonic()-started
        recovery=index(value['journal'],root/'catalog'/value['session']/'recovery.json')
        fresh,saved=reopen_index(root/'catalog'/value['session']/'recovery.json',recovery['recovery_identity'])
        assert fresh['replay']==value['recovery']['replay']
        results.append(value)
        print(mode,value['accounting'],flush=True)
    (root/'results.json').write_text(json.dumps(results,indent=2))
    return results
if __name__=='__main__':run(sys.argv[1])
