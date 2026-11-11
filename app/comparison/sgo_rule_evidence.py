"""Reviewed, jurisdiction-specific normal-scoring rules for an SGO median.

These profiles do not establish which jurisdiction or contract an SGO quote
represents. Exact per-market jurisdiction evidence must be independently
reviewed and bound to the source frame. The production registry starts empty.
"""
from hashlib import sha256
import json
from pathlib import Path

from .sgo_reference import capture_witness, _time, _digest, ContributorFrameWitness

ROOT=Path(__file__).resolve().parents[2]
RULES=ROOT/'app/fixtures/sgo-reviewed-market-rules-20261110.json'
BINDINGS=ROOT/'app/fixtures/sgo-reviewed-jurisdiction-bindings.json'
FIELDS=('provider','venue','jurisdiction','event_id','odd_id','frame_id','league','market','period')
SETTLEMENT='nba-completed-two-way-winner-including-overtime'


class ReviewedBindings:
    """Read bounded manual reviews and verify their retained evidence bytes."""
    def __init__(self, document, *, evidence_root):
        if document.get('version')!='sgo-reviewed-jurisdiction-bindings-1' or not isinstance(document.get('bindings'),list) or len(document['bindings'])>4096:
            raise ValueError('invalid jurisdiction binding registry')
        self.root=Path(evidence_root).resolve()
        self.rows=[]
        for item in document['bindings']:
            if not isinstance(item,dict) or item.get('review_class')!='manual_review':
                raise ValueError('jurisdiction evidence review required')
            identity={k:item.get(k) for k in FIELDS}
            if any(not isinstance(v,str) or not v or len(v)>256 for v in identity.values()):
                raise ValueError('exact jurisdiction binding required')
            path=(self.root/item['evidence_path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file() or path.stat().st_size>131072:
                raise ValueError('jurisdiction evidence path invalid')
            body=path.read_bytes()
            if sha256(body).hexdigest()!=item.get('evidence_sha256'):
                raise ValueError('jurisdiction evidence hash conflict')
            evidence=json.loads(body)
            if (evidence.get('kind')!='reviewed_source_market_jurisdiction'
                    or evidence.get('identity')!=identity or not evidence.get('source_url','').startswith('https://')
                    or evidence.get('normal_scoring')!=SETTLEMENT
                    or evidence.get('specific_market_terms_reviewed') is not True):
                raise ValueError('jurisdiction evidence identity conflict')
            _time(item['reviewed_at']);_time(item['effective_from'])
            if item.get('effective_until') is not None and _time(item['effective_until'])<=_time(item['effective_from']):
                raise ValueError('jurisdiction evidence interval invalid')
            self.rows.append((identity,item))

    def resolve(self, quote, at):
        clock=_time(at)
        matches=[]
        for identity,item in self.rows:
            if any(identity[k] != quote.get(k) for k in FIELDS if k!='jurisdiction'):
                continue
            if (_time(item['reviewed_at'])<=clock and _time(item['effective_from'])<=clock
                    and (item.get('effective_until') is None or clock<_time(item['effective_until']))):
                matches.append((identity,item))
        # Multiple reviewed jurisdictions for one source quote are ambiguous.
        return matches[0] if len(matches)==1 else None


def owned_bindings():
    return ReviewedBindings(json.loads(BINDINGS.read_text()), evidence_root=ROOT)


def reviewed_median(quotes, contract, *, at, evaluated_venue, registry):
    """Build a captured median only from exact, separately reviewed bindings.

    The calling owner must first independently qualify the native occurrence,
    contract and scoring scope. This function cannot create native evidence.
    """
    unavailable=lambda reason: ({'available':False,'reason':reason,'contributors':[],'exclusions':{}},None)
    rules=json.loads(RULES.read_text())
    if (_time(at)<_time(rules['reviewed_at']) or contract.get('league')!='NBA'
            or contract.get('market')!='moneyline' or contract.get('period')!='game'
            or contract.get('settlement')!=SETTLEMENT or not contract.get('occurrence_evidence')
            or not contract.get('settlement_evidence')):
        return unavailable('reviewed_median_native_or_rule_scope_unavailable')
    if not isinstance(registry,ReviewedBindings):
        return unavailable('reviewed_jurisdiction_registry_unavailable')
    qualified=[];excluded={}
    for raw in quotes:
        q=dict(raw)
        try:
            match=registry.resolve(q,at)
            if not match:
                raise ValueError('exact_jurisdiction_binding_unavailable')
            identity, review=match
            rule=rules['profiles'].get(identity['venue']+':'+identity['jurisdiction'])
            if not rule:
                raise ValueError('jurisdiction_rules_unreviewed')
            q['settlement']=SETTLEMENT
            q['settlement_evidence']='jurisdiction-review:'+review['evidence_sha256']+';rules:'+sha256(RULES.read_bytes()).hexdigest()
            q['jurisdiction']=identity['jurisdiction']
            q['rule_source']=rule['source']
            q['rule_reviewed_at']=rules['reviewed_at']
            qualified.append(q)
        except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
            excluded[q.get('venue','unknown')]=str(exc)
    result,witness=capture_witness(qualified,contract,at=at,evaluated_venue=evaluated_venue)
    result['exclusions'].update(excluded)
    if witness is not None:
        payload=json.loads(witness.wire)
        payload['basis']['exclusions'].update(excluded)
        payload['basis_sha256']=_digest(payload['basis'])
        result['basis']=payload['basis'];result['basis_sha256']=payload['basis_sha256']
        witness=ContributorFrameWitness(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False))
    return result,witness
