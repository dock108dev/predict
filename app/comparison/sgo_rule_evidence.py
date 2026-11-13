"""Reviewed, jurisdiction-specific normal-scoring rules for an SGO median.

These profiles do not establish which jurisdiction or contract an SGO quote
represents. Exact per-market jurisdiction evidence must be independently
reviewed and bound to the source frame. The production registry starts empty.
"""
from hashlib import sha256
import json
from pathlib import Path

from .sgo_reference import capture_witness, _time, _line

ROOT=Path(__file__).resolve().parents[2]
RULES=ROOT/'app/fixtures/sgo-reviewed-market-rules-20261110.json'
BINDINGS=ROOT/'app/fixtures/sgo-reviewed-jurisdiction-bindings.json'
FIELDS=('provider','venue','jurisdiction','event_id','odd_id','frame_id','league','market','period')
SETTLEMENT='nba-completed-two-way-winner-including-overtime'


def settlement_key(league, market, period):
    from .line_reference import scoring

    scoring(league)
    if period != 'game' or market not in ('moneyline', 'spread', 'total'):
        raise ValueError('unreviewed reference settlement scope')
    if (league, market) == ('NBA', 'moneyline'):
        return SETTLEMENT
    return f'{league.lower()}-completed-two-way-{market}-full-game-score'


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
            if identity['market'] in ('spread', 'total'):
                line = item.get('line')
                if line is None:
                    raise ValueError('exact jurisdiction line required')
                _line(line)
                identity['line'] = line
            elif item.get('line') is not None:
                raise ValueError('unexpected jurisdiction line')
            path=(self.root/item['evidence_path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file() or path.stat().st_size>131072:
                raise ValueError('jurisdiction evidence path invalid')
            body=path.read_bytes()
            if sha256(body).hexdigest()!=item.get('evidence_sha256'):
                raise ValueError('jurisdiction evidence hash conflict')
            evidence=json.loads(body)
            if (evidence.get('kind')!='reviewed_source_market_jurisdiction'
                    or evidence.get('identity')!=identity or not evidence.get('source_url','').startswith('https://')
                    or evidence.get('normal_scoring')!=settlement_key(identity['league'],identity['market'],identity['period'])
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
            if 'line' in identity and _line(identity['line']) != _line(quote.get('line')):
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
    return _reviewed_reference(quotes, contract, at=at, evaluated_venue=evaluated_venue,
                               registry=registry, best_payout=False)


def reviewed_best_payout(quotes, contract, *, at, evaluated_venue, registry):
    return _reviewed_reference(quotes, contract, at=at, evaluated_venue=evaluated_venue,
                               registry=registry, best_payout=True)


def _reviewed_reference(quotes, contract, *, at, evaluated_venue, registry, best_payout):
    unavailable=lambda reason: ({'available':False,'reason':reason,'contributors':[],'exclusions':{}},None)
    rules_body = RULES.read_bytes()
    rules=json.loads(rules_body)
    rule_sha = sha256(rules_body).hexdigest()
    try:
        settlement = settlement_key(contract.get('league'), contract.get('market'), contract.get('period'))
    except ValueError:
        settlement = None
    if (_time(at)<_time(rules['reviewed_at']) or not settlement
            or not best_payout and settlement != SETTLEMENT
            or contract.get('settlement')!=settlement or not contract.get('occurrence_evidence')
            or not contract.get('settlement_evidence')):
        return unavailable('sgo_reference_settlement_unverified' if best_payout else 'reviewed_median_native_or_rule_scope_unavailable')
    def qualify_pair(pair):
        if not isinstance(registry, ReviewedBindings):
            raise ValueError('reviewed_jurisdiction_registry_unavailable')
        qualified = []
        for quote in pair:
            match = registry.resolve(quote, at)
            if not match:
                raise ValueError('exact_jurisdiction_binding_unavailable')
            identity, review = match
            rule = rules['profiles'].get(identity['venue'] + ':' + identity['jurisdiction'])
            if not rule or settlement not in rule.get('normal_scoring', [SETTLEMENT]):
                raise ValueError('jurisdiction_rules_unreviewed')
            qualified.append(dict(quote, settlement=settlement,
                settlement_evidence='jurisdiction-review:' + review['evidence_sha256'] + ';rules:' + rule_sha,
                jurisdiction=identity['jurisdiction'], rule_source=rule['source'],
                rule_reviewed_at=rules['reviewed_at']))
        return qualified

    return capture_witness(quotes, contract, at=at, evaluated_venue=evaluated_venue,
                           best_payout=best_payout, qualify_pair=qualify_pair)
