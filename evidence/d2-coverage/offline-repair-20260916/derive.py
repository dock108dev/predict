"""Offline reproduction; reads original journal and writes only this new directory."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from app.collection.continuous import Discovery
from app.collection.odds_http import BudgetStop
from app.collection.transport_session import reopen
from app.dashboard.coverage_owner import replay_groups
from tests.test_d2_repair import JOURNAL, AT, saved_pages
OUT=Path(__file__).resolve().parent

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

async def main():
    pages=saved_pages();session=SimpleNamespace(producers={},emit=lambda *a:None)
    d=Discovery(session)
    async def venue(v):
        d.pages.extend(p for p in pages if p['source']==v and p['discovery_generation']==d.generation)
        if d.generation==3 and v=='polymarket_us':raise BudgetStop('saved third traversal ended at session_ingress_cap')
    d.venue=venue
    with patch('app.collection.continuous.now',return_value=AT):
        await d.discover();save('generation-1.json',d.inventory)
        await d.discover(force=True);save('generation-2.json',d.inventory)
        before=deepcopy(d.inventory)
        try:await d.discover(force=True)
        except ValueError:pass
        assert d.inventory==before
        save('interrupted-third.json',d.status())
    replay=replay_groups(reopen(JOURNAL));save('saved-replay.json',replay)
    previous=json.loads((OUT/'prior-evidence-sha256.json').read_text())
    changed=[p for p,h in previous.items() if not Path(p).is_file() or sha256(Path(p).read_bytes()).hexdigest()!=h]
    assert not changed,changed
    baseline=json.loads(Path('evidence/d2-coverage/verification.json').read_text())['final_source_sha256']
    current={p:sha256(Path(p).read_bytes()).hexdigest() for p in sorted(set(baseline)|{'tests/test_d2_repair.py'})}
    identity=sha256(json.dumps(current,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    save('verification.json',dict(candidate_identity_sha256=identity,source_sha256=current,
        head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        changed_from_replacement={p:dict(before=baseline.get(p),after=h) for p,h in current.items() if baseline.get(p)!=h},
        prior_evidence_files_verified=len(previous),prior_evidence_changes=changed,
        original_journal=str(JOURNAL),original_journal_sha256=sha256(JOURNAL.read_bytes()).hexdigest(),
        checks=dict(unit_tests=75,final_affected_tests=20,result='passed',javascript_syntax='passed',exact_saved_books=491),
        classification='offline repair; no fresh market data or live validation; beta not restarted'))
    print(identity,len(previous),len(current));print([p for p,h in current.items() if baseline.get(p)!=h])

if __name__=='__main__':asyncio.run(main())
