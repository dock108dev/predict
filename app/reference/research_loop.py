"""File-only page arithmetic and append-only prediction research. No network."""
import argparse
import base64
from datetime import datetime, timezone, timedelta
from decimal import Decimal, Context, localcontext
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path

from app.reference.public_page import parse, timestamp, DelayedPolicy
from app.pricing.baseline import devig
from app.depth import consume
from app.opportunities.board import expected

LABEL = 'Page-derived estimate — bookmaker update time and delay unknown.'
TEAMS = {'Detroit Lions': 'DET', 'Buffalo Bills': 'BUF'}
FORMAT = 'page-research-record-1'


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha256(encoded(value)).hexdigest()


def dependencies(folder):
    folder = Path(folder)
    return dict(html_base64=base64.b64encode((folder/'vegasinsider.html').read_bytes()).decode(),
                capture=json.loads((folder/'capture.json').read_text()))


def calculation(deps):
    page = parse(base64.b64decode(deps['html_base64'], validate=True), deps['capture'], event_id='32144330')
    if {s['team']: s['abbreviation'] for s in page['sides']} != TEAMS:
        raise ValueError('unexpected_event_teams')
    if timestamp(page['scheduled_start']) != timestamp('2026-09-18T00:15:00Z'):
        raise ValueError('unexpected_event_start')
    arithmetic = devig([Decimal(s['decimal_odds']) for s in page['sides']])
    for i, side in enumerate(page['sides']):
        a = int(side['american_price'])
        exact = 1 + (Fraction(a, 100) if a > 0 else Fraction(100, -a))
        side.update(decimal_odds_exact=str(exact), implied_probability_exact=str(1/exact),
                    implied_probability=arithmetic['implied_probabilities'][i],
                    probability=arithmetic['probabilities'][i])
    return dict(page=page, arithmetic=arithmetic, label=LABEL, method='proportional-devig-1',
                precision='Exact rational American conversion retained; 50 significant digits HALF_EVEN; probabilities 18 decimal places.',
                limitations=['bookmaker update time and delay unknown', 'upstream synchronization unknown',
                             'independence unassessed', 'proportional margin removal is a model assumption',
                             'ordinary team-winner conditioning; exceptional mass unknown'],
                live_qualified=False, unconditional_ev=None)


def conditional(probability, *, teams, target_team, levels, quantity, entry_fee, later_fee,
                payout_win, payout_lose, assumption):
    """Explicit illustrative fee scenario; shared depth and state cashflow arithmetic.

    No venue fee schedule is inferred from this total-fee scenario.
    """
    if target_team not in teams or len(set(teams)) != 2 or not assumption:
        raise ValueError('explicit orientation and assumption required')
    with localcontext(Context(prec=100)):
        p, q = Decimal(probability), Decimal(quantity)
        if not p.is_finite() or not 0 <= p <= 1 or not q.is_finite() or q <= 0 or q != q.to_integral_value():
            raise ValueError('invalid probability or whole quantity')
        result = dict(unconditional_ev=None, assumption=assumption, expected_profit=None,
                      reasons=[], probability_source='explicit synthetic example')
        try:
            fills = consume(levels, quantity)
        except ValueError as exc:
            return dict(result, reasons=[str(exc)])
        cost = sum((Decimal(f['price'])*Decimal(f['quantity']) for f in fills), Decimal(0))
        result.update(fills=fills, cost=str(cost))
        if any(x is None for x in (entry_fee, later_fee, payout_win, payout_lose)):
            return dict(result, reasons=['material fee or payout unknown'])
        fee, later, win, lose = map(Decimal, (entry_fee, later_fee, payout_win, payout_lose))
        if any(not x.is_finite() or x < 0 for x in (fee, later, win, lose)) or win <= lose:
            raise ValueError('invalid fees or ordinary payouts')
        cash = cost+fee
        other = next(t for t in teams if t != target_team)
        flows = {'winner:'+t: dict(gross_payout=str(q*v), net_cashflow=str(q*v-cash-later))
                 for t, v in ((target_team, win), (other, lose))}
        leg = dict(id='synthetic:yes', team=target_team, cash=str(cash), cashflows=flows)
        ev = expected(leg, p, q, dict(teams=teams))
        ev['probability_source'] = 'explicit synthetic example'
        return dict(result, **ev, cash=str(cash), cashflows=flows)


def records(folder):
    result = []
    for path in sorted(Path(folder).glob('*.json')):
        record = json.loads(path.read_text())
        identity = record.pop('id')
        if record.get('format') != FORMAT or digest(record) != identity or path.stem != identity:
            raise ValueError('record integrity failure')
        result.append(dict(record, id=identity))
    return sorted(result, key=lambda r: (timestamp(r['saved_at']), r['id']))


def append(folder, payload):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    record = dict(payload, format=FORMAT, saved_at=now())
    record['id'] = digest(record)
    with (folder/(record['id']+'.json')).open('x') as f:
        json.dump(record, f, indent=2, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    return record


def get(folder, identity):
    return next(r for r in records(folder) if r['id'] == identity)


def save(folder, deps, *, primary=False, cutoff=None, supersedes_id=None, reason=None, synthetic_clock=None):
    result = calculation(deps)
    estimated = now(); cutoff = cutoff or estimated
    page = result['page']; start = timestamp(page['scheduled_start'])
    receipt = timestamp(page['retrieved_at'])
    if timestamp(cutoff) < receipt:
        raise ValueError('reference received after cutoff; cannot insert new reference into old target cutoff')
    if timestamp(cutoff) > timestamp(estimated):
        raise ValueError('future cutoff')
    prior = records(folder)
    if supersedes_id:
        old = get(folder, supersedes_id)
        if old['kind'] != 'prediction' or not reason:
            raise ValueError('prediction correction requires reason and prediction link')
        primary = False  # Corrections never replace the predeclared primary score.
    if primary and any(r['kind'] == 'prediction' and r['primary'] for r in prior):
        raise ValueError('one designated primary per game; further records are exploratory')
    evaluation_clock = synthetic_clock or estimated
    simulated = synthetic_clock is not None
    if simulated:
        timestamp(synthetic_clock)
    in_window = start-timedelta(minutes=30) <= timestamp(evaluation_clock) <= start-timedelta(minutes=20)
    designation = 'synthetic_demonstration' if simulated else ('prospective_primary' if primary and in_window else 'exploratory')
    if not simulated and timestamp(estimated) >= start-timedelta(seconds=60):
        designation = 'retrospective'
    payload = dict(kind='prediction', dependencies=deps, result=result, estimated_at=estimated, cutoff=cutoff,
                   event_id=page['event_id'], outcome='Detroit Lions', primary=primary,
                   baseline_probability='0.5', selection_rule='first primary in 30-to-20-minute pregame window; one per game',
                   evaluation_designation=designation, synthetic_clock=synthetic_clock,
                   supersedes_id=supersedes_id, correction_reason=reason,
                   ev=dict(conditional_ev=None, unconditional_ev=None,
                           reasons=['No contemporaneous target supplied; normal-winner rule comparability unassessed.']))
    # Save classification uses the actual persistence clock, not a supplied historic time.
    if not simulated and timestamp(now()) >= start-timedelta(seconds=60):
        payload['evaluation_designation'] = 'retrospective'
    return append(folder, payload)


def reopen(folder, identity):
    record = get(folder, identity)
    if record['kind'] != 'prediction' or calculation(record['dependencies']) != record['result']:
        raise ValueError('prediction recomputation mismatch')
    return record


def annotate(folder, prediction_id, kind, data, *, supersedes_id=None, reason=None):
    prediction = reopen(folder, prediction_id)
    if kind not in ('sporting', 'settlement'):
        raise ValueError('annotation kind')
    required = {'source', 'published_at', 'observed_at', 'final', 'synthetic'}
    if not required <= data.keys() or not data['source'] or type(data['final']) is not bool or type(data['synthetic']) is not bool:
        raise ValueError('source, times, finality and synthetic designation required')
    published, observed = map(timestamp, (data['published_at'], data['observed_at']))
    if published > observed:
        raise ValueError('publication after observation')
    if not data['synthetic'] and (observed > timestamp(now()) or observed < timestamp(prediction['saved_at'])):
        raise ValueError('outcome must be observed later than prediction and not in future')
    if data['synthetic'] != (prediction['evaluation_designation'] == 'synthetic_demonstration'):
        raise ValueError('synthetic outcomes must stay in synthetic demonstration')
    if kind == 'sporting':
        if data.get('result') not in (*TEAMS, 'tie', 'cancelled', 'unresolved') or 'score' not in data:
            raise ValueError('sporting result and score required')
    else:
        if not data.get('contract_id') or not data.get('basis') or 'payout_per_contract' not in data:
            raise ValueError('separate contract, payout and basis required')
        if data['payout_per_contract'] is not None:
            p = Decimal(data['payout_per_contract'])
            if not p.is_finite() or not 0 <= p <= 1:
                raise ValueError('invalid settlement payout')
    existing = [r for r in records(folder) if r['kind'] == kind and r['prediction_id'] == prediction_id]
    if existing:
        latest = existing[-1]
        if supersedes_id != latest['id'] or not reason:
            raise ValueError('annotation correction must supersede latest with reason')
    elif supersedes_id:
        raise ValueError('no annotation to supersede')
    return append(folder, dict(kind=kind, prediction_id=prediction_id, event_id=prediction['event_id'],
                              data=data, supersedes_id=supersedes_id, correction_reason=reason))


def evaluate(folder):
    rows = records(folder); scores = []; excluded = []; seen = set()
    for r in rows:
        if r['kind'] != 'prediction':
            continue
        reopen(folder, r['id'])
        annotations = [a for a in rows if a['kind'] == 'sporting' and a['prediction_id'] == r['id']]
        outcome = annotations[-1] if annotations else None
        why = None
        if not r['primary'] or r['event_id'] in seen: why = 'repeated/exploratory'
        elif r['evaluation_designation'] not in ('prospective_primary', 'synthetic_demonstration'): why = r['evaluation_designation']
        elif not outcome or not outcome['data']['final']: why = 'unresolved'
        elif outcome['data']['result'] not in TEAMS: why = outcome['data']['result']
        if why:
            excluded.append(dict(prediction_id=r['id'], reason=why)); continue
        seen.add(r['event_id'])
        with localcontext(Context(prec=100)):
            p = Decimal(next(s['probability'] for s in r['result']['page']['sides'] if s['team'] == r['outcome']))
            score = (p-int(outcome['data']['result'] == r['outcome']))**2
            scores.append(dict(prediction_id=r['id'], annotation_id=outcome['id'], brier=str(score),
                               baseline='0.25', difference=str(score-Decimal('.25')),
                               designation=r['evaluation_designation']))
    real = [s for s in scores if s['designation'] == 'prospective_primary']
    with localcontext(Context(prec=100)):
        mean = str(sum((Decimal(s['brier']) for s in real), Decimal(0))/len(real)) if real else None
    return dict(method='ordinary-result-brier-1', scores=scores, excluded=excluded,
                prospective_count=len(real), prospective_mean_brier=mean, baseline_mean='0.25' if real else None,
                settlement_annotations=[r for r in rows if r['kind'] == 'settlement'],
                note='Synthetic scores excluded from prospective aggregates. Sporting score is not contract settlement or realized profit.')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest='command', required=True)
    p = sub.add_parser('calculate'); p.add_argument('capture')
    p = sub.add_parser('save'); p.add_argument('capture'); p.add_argument('journal'); p.add_argument('--primary', action='store_true'); p.add_argument('--cutoff'); p.add_argument('--supersedes-id'); p.add_argument('--reason')
    p = sub.add_parser('reopen'); p.add_argument('journal'); p.add_argument('id')
    p = sub.add_parser('annotate'); p.add_argument('journal'); p.add_argument('id'); p.add_argument('kind', choices=['sporting','settlement']); p.add_argument('annotation'); p.add_argument('--supersedes-id'); p.add_argument('--reason')
    p = sub.add_parser('evaluate'); p.add_argument('journal')
    p = sub.add_parser('demo'); p.add_argument('capture'); p.add_argument('journal')
    a = cli.parse_args()
    if a.command == 'calculate': result = calculation(dependencies(a.capture))
    elif a.command == 'save': result = save(a.journal, dependencies(a.capture), primary=a.primary, cutoff=a.cutoff, supersedes_id=a.supersedes_id, reason=a.reason)
    elif a.command == 'reopen': result = reopen(a.journal, a.id)
    elif a.command == 'annotate': result = annotate(a.journal, a.id, a.kind, json.loads(Path(a.annotation).read_text()), supersedes_id=a.supersedes_id, reason=a.reason)
    elif a.command == 'evaluate': result = evaluate(a.journal)
    else:
        r = save(a.journal, dependencies(a.capture), primary=True, synthetic_clock='2026-09-17T23:50:00Z')
        reopen(a.journal, r['id'])
        base = dict(source='synthetic:invented outcome, not an actual game result', published_at='2026-09-18T04:00:00Z', observed_at='2026-09-18T04:01:00Z', final=True, synthetic=True)
        annotate(a.journal, r['id'], 'sporting', dict(base, result='Detroit Lions', score={'Detroit Lions':24,'Buffalo Bills':21}))
        annotate(a.journal, r['id'], 'settlement', dict(base, contract_id='synthetic:DET-YES', payout_per_contract='1', basis='invented normal winner resolution'))
        result = evaluate(a.journal)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
