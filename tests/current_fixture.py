"""Explicit test-only injected provider. Ordinary launcher has no switch to this."""
from copy import deepcopy
from tests.current_sample import sample_payload
from app.dashboard.current_contract import identity, stamp, line, binding_context, VENUES
from app.dashboard.current_state import CurrentStateProvider


def fixture(revision=1):
    r=sample_payload(revision)
    for k in ('selection_policy','admin_href'):r.pop(k,None)
    for e in r['events']:
        e['id']=identity('event',[*[e[k] for k in ('sport','league','season','stage','event_discriminator')],stamp(e['start_at']).isoformat(),sorted((p['role'],p['id']) for p in e['participants'])])
        for g in e['groups']:
            g['line']=line(g['line'])
            g['id']=identity('group',[e['id'],*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
            for o in g['outcomes']:
                o['signed_line']=line(o['signed_line'])
                o['id']=identity('outcome',[g['id'],o['participant'],o['predicate'],o['signed_line'],o.get('result_interpretation','normal_win')])
                for q in o['quotes'].values():
                    for k in ('display','comparison','calculations','age_seconds','stale'):q.pop(k,None)
                    q['binding']=dict(verified=True,evidence=['syn:explicit-binding-fixture'],selection=binding_context(e,g,o))
                    q['freshness_policy']=dict(version='syn:test-only-policy',maximum_age_seconds=14400)
                    q['rules_differ']=q['venue']=='polymarket_us'
    return r


def rebind(raw):
    for e in raw['events']:
        e['id']=identity('event',[*[e[k] for k in ('sport','league','season','stage','event_discriminator')],stamp(e['start_at']).isoformat(),sorted((p['role'],p['id']) for p in e['participants'])])
        for g in e['groups']:
            g['id']=identity('group',[e['id'],*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
            for o in g['outcomes']:
                o['id']=identity('outcome',[g['id'],o['participant'],o['predicate'],line(o['signed_line']),o.get('result_interpretation','normal_win')])
                for q in [*o['quotes'].values(),*(q for qs in o.get('alternatives',{}).values() for q in qs)]:q['binding']['selection']=binding_context(e,g,o)
    return raw


class InjectedTestProvider(CurrentStateProvider):
    allow_synthetic=True
    def __init__(self,raw=None):self.raw=raw or fixture();self.close_count=0
    def initial_state(self):return deepcopy(self.raw)
    async def close(self):self.close_count+=1
