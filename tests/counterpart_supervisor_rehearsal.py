"""OFFLINE owned-child process cleanup. Stand-ins never acquire or read credentials."""
import importlib.util,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];PACKAGE=ROOT/'scripts/v1_counterpart_package'
sys.path.insert(0,str(PACKAGE));module_spec=importlib.util.spec_from_file_location('counterpart_child_supervisor',PACKAGE/'execute-child.py');execute=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(execute)

def main():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);attempt=dict(attempt_id='e5839793-35ae-45e1-97ce-a591322152b7',output=str(p/'UNUSED-output'))
        (p/'attempt.json').write_text(json.dumps(attempt))
        (p/'launch.py').write_text("import json,time\nfrom pathlib import Path\np=Path(__file__).parent\n(p/'server-ready.json').write_text('{}')\ntime.sleep(240)\n")
        (p/'control.py').write_text("# OFFLINE control stand-in: actual controller separately timed\n")
        with patch.object(execute,'PACKAGE',p),patch.object(execute.launch,'prepared',return_value=({},p/'UNUSED-output')):
            execute.execute();result=json.loads((p/'supervisor-result.json').read_text());assert result['children_reaped'];assert result['elapsed_seconds']<3
            try:execute.execute()
            except FileExistsError:pass
            else:raise AssertionError('Consumed supervision reused')
        report=dict(classification='OFFLINE actual supervisor with process stand-ins; actual launcher/control qualified separately',consumed_attempt_refused=True,actual_provider_requests=0,credentials=0,**result)
        (ROOT/'evidence/v1-counterpart-completion-20261001-v1/supervisor-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
