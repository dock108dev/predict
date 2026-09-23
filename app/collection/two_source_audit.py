"""Offline exact replay and separate collection/economic qualification results."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from app.dashboard import session_history,product_view
from app.dashboard.coverage_owner import replay_groups
from app.collection.transport_session import reopen
from app.dashboard.e6_live import save_json


def normalized(value):return json.loads(json.dumps(value,sort_keys=True,default=str))

def oracle(snapshot):
    fields=('games','points','sources','references','market_catalog','qualification_fee_policy')
    return dict(cutoff=snapshot['durable_cursor'],snapshot=normalized({k:snapshot.get(k) for k in fields}),
        calculations=normalized({g['id']:{k:v for k,v in product_view.calculate(snapshot,g,{}).items() if k!='state'} for g in snapshot['games']}))


def scope_check(rows,selections):
    selected=selections[-1] if selections else {}
    expected=selected.get('markets',{});violations=[];observed={v:set() for v in ('kalshi','polymarket_us')}
    inventories=[r['inventory'] for r in rows if r['type']=='coverage_inventory']
    cats=inventories[-1] if inventories else {}
    wire_ids={v:{m['id'] if v=='kalshi' else m.get('native_slug') for m in cats.get(v,{}).get('markets',[]) if m['id'] in expected.get(v,[])} for v in observed}
    for row in rows:
        v=row.get('source')
        if v not in observed:continue
        if row['type']=='qualification_scope_violation':
            violations.append(dict(source=v,type=row['type'],direction=row['direction'],reason=row['reason']))
        elif row['type']=='prediction_frame' and expected:
            from .two_source_scope import violation
            reason=violation(v,row,dict(selected,subscription_ids=wire_ids))
            if reason:violations.append(dict(source=v,type='received_frame',direction='incoming',reason=reason))
        elif row['type'] in ('market_selected','prediction_book'):
            value=row.get('market',row.get('book'));ref=value['raw']['ref'];mid=ref['market_id'];observed[v].add(mid)
            if mid not in expected.get(v,[]) or ref['event_id']!=selected.get(v):violations.append(dict(source=v,type=row['type'],market_id=mid,event_id=ref['event_id']))
        elif row['type']=='prediction_command':
            c=json.loads(row['body']);ids=c.get('params',{}).get('market_tickers') if v=='kalshi' else c.get('subscribe',{}).get('marketSlugs')
            from .two_source_scope import violation
            if violation(v,row,dict(selected,subscription_ids=wire_ids)):violations.append(dict(source=v,type='prediction_command',direction='outgoing',requested=ids))
    return dict(state='FAIL' if violations else 'PASS',expected=expected,observed={v:sorted(ids) for v,ids in observed.items()},violations=violations)


def verify(folder):
    folder=Path(folder);data=json.loads((folder/'qualification-oracle.json').read_text())
    binding=json.loads((folder/'qualification-manifest.json').read_text())
    for name,h in binding['files'].items():
        if name not in ('manifest.json','qualification-oracle.json') or sha256((folder/name).read_bytes()).hexdigest()!=h:raise ValueError('qualification artifact identity mismatch')
    snapshot=session_history.load(folder,data['cutoff'])
    if oracle(snapshot)!=data:raise ValueError('fresh-process snapshot/calculation disagreement')
    native=reopen(folder/(folder.name+'.jsonl'))
    if replay_groups(native)!=json.loads((folder/'replay.json').read_text()):raise ValueError('native replay disagreement')
    counts=Counter(r['source'] for r in native['rows'] if r['type']=='prediction_frame')
    books=Counter(r['source'] for r in native['rows'] if r['type']=='prediction_book')
    selections=[r['selection'] for r in native['rows'] if r['type']=='qualification_selection']
    scope=scope_check(native['rows'],selections)
    report=json.loads((folder/'report.json').read_text())
    candidates=[c for calc in data['calculations'].values() for c in calc['candidates'] if len({l['venue'] for l in c['legs']})==2]
    assert not snapshot['references'],'reference unexpectedly imported'
    assert all(c['profit'] is None for c in candidates),'unverified native economics became available'
    collection=bool(selections and all(books[v]>0 for v in ('kalshi','polymarket_us')) and report['cleanup_complete'] and native['state']=='complete')
    audit=dict(state='PASS',exact_cutoff=data['cutoff'],exact_snapshot=True,exact_calculations=True,exact_native_replay=True,
        evidence_mode=snapshot['data_mode'],collection='PASS' if collection else 'FAIL / incomplete required source observations',
        selected_event=selections[-1] if selections else None,wire_frames=dict(counts),derived_books=dict(books),
        stop_reason=report['reason'],cleanup_complete=report['cleanup_complete'],resources=report['resources'],coverage=report['coverage'],
        comparisons=dict(cross_venue_candidates=len(candidates),qualified=0,finite_native_net_values=0,
            reason='Native fee applicability/settlement charges unresolved; no hypothetical fee substitution'),
        native_checks=dict(identity='Exact native event/market selection retained; outcome and terms remain source-specific',
            purchase_units='Original wire reconstruction exact; Kalshi opposite bid complements, US Long offers / Short bid complements retain supplied contract quantities',
            depth='Visible supplied levels only; unknown or absent size unavailable; no completeness or fill claim',
            settlement='Original listing text and per-venue rule assessment retained in oracle; unknown exceptional payouts are not refunds',
            fees='Pinned handler identities and native listing coefficient retained when supplied; missing current series/event applicability and settlement charges unavailable'),
        source_assessments={gid:calc['assessment'] for gid,calc in data['calculations'].items()},
        remaining=['Native current fee applicability and settlement charges','Full native exceptional-rule/payout qualification','Actual model and compatible current reference inputs','Novig/ProphetX provisioning','Remaining sports/period/futures actual data','Owner beta review after readiness'],
        historical_pinnacle='Separate; no references imported or acquired',beta_signoff='OPEN')
    audit['scope']=scope
    if scope['state']=='FAIL':
        audit['state']='FAIL';audit['collection']='FAIL / subscription or admission scope violation'
    audit['checks_reached']=dict(selected_native_contracts=bool(selections),purchase_units_depth_freshness=bool(books),qualified_economics=False)
    if not selections:
        audit['native_checks']={k:'NOT REACHED: no shared native event or selected contract' for k in audit['native_checks']}
    return audit


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    result=verify(a.folder);save_json(a.report,result)
    print(json.dumps({k:result[k] for k in ('state','evidence_mode','collection','exact_snapshot','exact_calculations','exact_native_replay','comparisons')},indent=2))

if __name__=='__main__':main()
