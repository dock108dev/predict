"""Sanitized calculation seam durations and simultaneous ownership markers."""
from functools import wraps
import importlib
import json
import resource
from time import perf_counter
from unittest.mock import patch


def instrument_seams(stack, destination):
    active=[]
    path=destination/'seams.jsonl'
    targets=(('app.comparison.effective_policy','recalculate'),
             ('app.dashboard.current_incremental','project'),
             ('app.comparison.estimated_pair','assemble'),
             ('app.comparison.current_details','selected'),
             ('app.comparison.metrics','snapshot_metrics'),
             ('app.dashboard.current_contract','packed'),
             ('app.dashboard.current_encoded','EncodedBodies.encode'),
             ('app.dashboard.current_encoded','EncodedBodies.adopt_file'),
             ('app.dashboard.current_deadlines','next_deadline'),
             ('app.dashboard.current_state','CurrentStore.__init__'),
             ('app.dashboard.current_state','CurrentStore.refresh_age'),
             ('app.dashboard.current_state','CurrentStore.commit'))
    def install(module,name):
        owner=importlib.import_module(module)
        parts=name.split('.')
        for part in parts[:-1]:owner=getattr(owner,part)
        original=getattr(owner,parts[-1]);label=module+'.'+name
        @wraps(original)
        def measured(*args,**kwargs):
            tick=perf_counter();active.append(label)
            def record(phase,**extra):
                with path.open('a') as stream:
                    stream.write(json.dumps(dict(seam=label,phase=phase,active=list(active),
                        peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**extra))+'\n')
            record('enter')
            try:return original(*args,**kwargs)
            finally:
                record('exit',seconds=perf_counter()-tick);active.pop()
        stack.enter_context(patch.object(owner,parts[-1],measured))
    for module,name in targets:install(module,name)
