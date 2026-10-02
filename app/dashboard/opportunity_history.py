"""Compact, bounded signal transitions; historical reconstruction is never live.

Watch definitions grant no collection authority. All numerical values come from
ordinary product calculations at the original durable cutoff.
"""
import json
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from collections import Counter
from app.dashboard.session_projection import SessionProjection, stable
from app.dashboard.query_policy import decimal_input, validate_http_query

VERSION = 'opportunity-history-2'
MAX_WATCHES = 16
MAX_ITEMS = 1024
MAX_EVENTS = 2048
MAX_EVALUATIONS = 4096
FILTERS = ('competition', 'season', 'family', 'period', 'venue', 'search')


def validate_watch(value):
    if not isinstance(value, dict) or set(value) - {'name', 'metric', 'threshold', 'filters', 'quantity'}:
        raise ValueError('Unknown watchlist setting')
    name = value.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError('Watchlist needs a name of at most 80 characters')
    if value.get('metric') not in ('raw_gap', 'arb_return', 'ev'):
        raise ValueError('Choose raw gap, supported arbitrage return, or supported EV')
    threshold = decimal_input(value.get('threshold'), 'threshold')
    quantity = decimal_input(value.get('quantity', '100'), 'quantity')
    if not -100000 <= threshold <= 100000 or not 0 < quantity <= 100000000 or quantity != quantity.to_integral_value():
        raise ValueError('Invalid threshold or whole-contract size')
    filters = value.get('filters', {})
    if not isinstance(filters, dict) or set(filters) - set(FILTERS) or any(not isinstance(v, str) or len(v) > 160 for v in filters.values()):
        raise ValueError('Invalid watch filters')
    validate_http_query(filters)
    result = dict(name=name.strip(), metric=value['metric'], threshold=str(threshold), quantity=str(quantity), filters=filters)
    return dict(result, id=stable(result))


class WatchStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 32768:
            raise ValueError('Watchlist storage limit')
        values = json.loads(self.path.read_text())
        if not isinstance(values, list) or len(values) > MAX_WATCHES:
            raise ValueError('Watchlist count limit')
        return [validate_watch({k:v for k,v in x.items() if k != 'id'}) for x in values]

    def save(self, values):
        if not isinstance(values, list) or len(values) > MAX_WATCHES:
            raise ValueError('At most 16 watchlists')
        if any(not isinstance(x,dict) for x in values):raise ValueError('Invalid watchlist entry')
        clean = [validate_watch({k:v for k,v in x.items() if k != 'id'}) for x in values]
        if len({v['id'] for v in clean}) != len(clean):
            raise ValueError('Duplicate watchlist')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(clean, indent=2))
        temp.replace(self.path)
        return clean


def observations(snapshot, watch, reuse=None):
    from app.dashboard.price_comparison import comparisons
    from app.dashboard.product_view import dashboard
    q = dict(watch['filters'], quantity=watch['quantity'], scenario='unknown')
    if watch['metric'] == 'raw_gap':
        rows = comparisons(snapshot, q)
    else:
        rows = dashboard(snapshot, dict(q, view='arb' if watch['metric']=='arb_return' else 'ev'), {}, reuse={} if reuse is None else reuse)
    if watch['metric'] != 'raw_gap':
        rows += [row for row in comparisons(snapshot,q) if row.get('aggregated') or row.get('native_raw') or row.get('manual_raw')]
    values = []
    for row in rows:
        raw = watch['metric'] == 'raw_gap'
        metric = row.get('raw_difference') if raw else row.get('return_pct')
        reasons = []
        if row.get('manual_raw'):
            if not raw:reasons.append('Optional net/EV inputs unavailable')
            if not row['timing']['receipt_limits_pass']:reasons.append('Stale or misaligned receipts')
            reasons += [r for leg in row['legs'] for r in leg.get('warnings', [])]
            if any(l.get('source_age_seconds') is None or not 0<=Decimal(l['source_age_seconds'])<=15 for l in row['legs']):reasons.append('Source time stale or unknown')
        elif row.get('aggregated'):
            reasons.append('Aggregate observations cannot emit source-qualified signals; source state and delay unknown' if snapshot.get('source_session_version') else 'Historical aggregate observations cannot emit live signals; source state and delay unknown')
            reasons += [r for leg in row['legs'] for r in leg.get('warnings', [])]
            if not raw:reasons.append('Aggregate execution, depth, fees, settlement and fair probability unsupported')
        elif row.get('native_raw') and not raw:
            reasons.append('Native net/EV unavailable: incompatible settlement, incomplete fee coverage and no supported probability')
        elif raw:
            if row.get('native_raw') and row.get('native_review',{}).get('version')=='native-book-comparison-4' and row['native_review']['record'].get('timing_assessment',{}).get('status')!='SUPPORTED':
                reasons.append('Native clock uncertainty and state continuity unverified; display does not qualify fresh pricing')
            if not row['timing']['receipt_limits_pass']:
                reasons.append('Receipt age exceeds 15s, alignment exceeds 5s, or required timing is unknown')
            reasons += [r for leg in row['legs'] for r in leg.get('warnings', [])]
            if row.get('native_raw') and not row['timing'].get('source_limits_pass'):
                reasons.append('Native source timestamp missing or older than 15 seconds; new receipt is not new pricing')
            if any(l.get('market_state') != 'active' for l in row['legs']):
                reasons.append('Required market is not known active')
        else:
            if not row.get('usable'):
                reasons.append('Required price, depth or source health is unavailable')
            reasons += row.get('reasons', [])
            reasons += [r for leg in row['legs'] for r in leg.get('reasons', [])]
            if watch['metric'] == 'arb_return' and not (row.get('settlement') or {}).get('qualified'):
                reasons.append('Material settlement equivalence is unverified or conflicting')
            if snapshot.get('qualification_fee_policy'):
                reasons.append('Native fee applicability and mandatory costs remain unresolved')
            ages=[l.get('age_seconds') for l in row['legs']]
            receipts=[l.get('received_at') for l in row['legs']]
            if any(a is None or not 0<=Decimal(a)<=15 for a in ages) or any(t is None for t in receipts):
                reasons.append('Required net inputs exceed 15s receipt age or timing is unknown')
            elif len(receipts)>1 and abs(seconds(max(receipts),min(receipts)))>5:
                reasons.append('Required net inputs exceed 5s receipt alignment')
            if watch['metric']=='ev' and row.get('probability') is not None:
                ref=next((r for r in snapshot['references'] if r['id']==row.get('reference_id')),None)
                if not ref or ref.get('freshness')!='within_refresh_plan' or ref.get('delay_seconds') is None:
                    reasons.append('Required probability freshness or publication delay is unverified or stale')
            # An assumed schedule/no-settlement-fee scenario cannot qualify a signal.
            if any(l.get('fee') is None or not l.get('fee_audit') or l['fee_audit'].get('unsupported') or l['fee_audit'].get('qualification') != 'documented_scenario' for l in row['legs']):
                reasons.append('Supported complete fee calculation unavailable')
        if row.get('rule_analysis') and not raw:
            reasons.extend(row['rule_analysis']['blockers'])
        if metric is None:
            reasons.append('Selected metric unavailable; missing economics or probability')
        elif Decimal(metric) < Decimal(watch['threshold']):
            reasons.append('Below explicit threshold')
        stamp = dict(session=row['session'], hash=row['hash'], cutoff=row['cutoff'], at=row['at'],
                     contract=row.get('contract') or row['legs'][0]['id'], candidate=row.get('candidate', ''),
                     reference=row.get('reference_id') or '', quantity=watch['quantity'], scenario='unknown')
        values.append(dict(id=row['id'], title=row['game_title'], metric=metric, size=None if row.get('aggregated') else row.get('modeled_quantity',str(min([Decimal(watch['quantity']),*[Decimal(l.get('visible_size') or '0') for l in row['legs']]]))),
                           qualifies=not reasons, reasons=list(dict.fromkeys(reasons)), point=stamp,
                           # A calculation can change without a new book: reference,
                           # rule/fee evidence or eligibility may change at a cutoff.
                           # Exclude clock/cursor churn so identical polls still deduplicate.
                           signature=stable(dict(books=[(l.get('book_id'),l.get('received_at')) for l in row['legs']],
                               metric=metric, size=row.get('modeled_quantity'), probability=row.get('probability'),
                               reference=row.get('reference_id'), reasons=list(dict.fromkeys(reasons)))),
                           mode=snapshot['data_mode'], basis=dict(aggregate_version=snapshot.get('aggregate_version'),source_versions=[dict(id=l['book_id'],response=l['provenance']['response'],registry=l['provenance']['registry_sha256']) for l in row['legs']] if row.get('aggregated') else None,metric_units='raw implied probability' if row.get('aggregated') and raw else 'native metric',settlement_version=(row.get('settlement_audit') or row.get('settlement') or {}).get('version') if isinstance(row.get('settlement_audit') or row.get('settlement'),dict) else None, fees=[dict(entry_audit_hash=stable(l['entry']['audit']) if l.get('entry',{}).get('audit') else None,engine=(l.get('fee_audit') or {}).get('engine'),registry_hash=(l.get('fee_audit') or {}).get('registry_hash'),schedule_hash=(l.get('fee_audit') or {}).get('schedule_hash'),context_hash=(l.get('fee_audit') or {}).get('context_hash')) for l in row['legs']])) )
        if row.get('native_raw'):
            values[-1]['basis']['native_review']=row['native_review']
            if row['native_review'].get('version')=='native-book-comparison-4':values[-1]['signature']=stable([values[-1]['signature'],row['native_review']['binding_sha256']])
            values[-1]['basis']['observations']=[dict(venue=l['venue'],source_at=l['source_at'],received_at=l['received_at'],observation=l.get('native_observation')) for l in row['legs']]
        if row.get('cross_source'):
            values[-1]['basis']['source_correspondence'] = row['source_correspondence']
            values[-1]['metric_units'] = row['raw_comparison_units'] if raw else 'unavailable source economics'
            binding = row['source_correspondence']
            values[-1]['signature'] = stable([values[-1]['signature'], {k: binding[k] for k in
                ('native_review_sha256', 'native_book_id', 'aggregate_record_sha256',
                 'aggregate_receipt_sha256', 'predicate')}])
        if row.get('rule_analysis'):
            analysis = row['rule_analysis']
            stamp['rule_version'] = analysis['version']
            values[-1]['basis']['rule_analysis'] = dict(version=analysis['version'], hash=analysis.get('hash'), status=analysis['status'])
            values[-1]['signature'] = stable([values[-1]['signature'], values[-1]['basis']['rule_analysis']])
    return values


def seconds(a, b):
    return (datetime.fromisoformat(a.replace('Z','+00:00'))-datetime.fromisoformat(b.replace('Z','+00:00'))).total_seconds()


class Signals:
    def __init__(self):
        self.items = {}
        self.events = []
        self.exclusions = Counter()
        self.dropped = 0

    def event(self, kind, item, point, reason):
        if len(self.events) == MAX_EVENTS:
            self.events.pop(0); self.dropped += 1
        self.events.append(dict(kind=kind, id=item['id'], watch=item['watch'], point=point, reason=reason))

    def expire(self, item, point, reason):
        if item['active']:
            item['active'] = False
            item['ended_reason'] = reason
            self.event('expired', item, point, reason)

    def update(self, snapshot, watches, running=True, historical=False):
        token = snapshot['durable_cursor']
        at = next(iter(snapshot['points'].values()))['at'] if snapshot['points'] else snapshot['last_update'] or snapshot['started_at']
        present = set()
        reuse = {}  # Existing request-local calculation cache; never crosses a cutoff.
        for watch in watches:
            for obs in observations(snapshot, watch, reuse):
                key = snapshot['session_id'] + ':' + watch['id'] + ':' + obs['id']
                present.add(key)
                item = self.items.get(key)
                if item is None:
                    if len(self.items) >= MAX_ITEMS:
                        self.dropped += 1; continue
                    item = self.items[key] = dict(id=obs['id'], watch=watch['id'], title=obs['title'], session=snapshot['session_id'], metric=watch['metric'], threshold=watch['threshold'], mode=obs['mode'], active=False, episodes=0, qualifying_observations=0, first=None, last=None, changes=[], signature=None, last_token=None, reasons=[], observed_spans=[])
                if item['active'] and seconds(at,item['last']['at']) > 15:
                    self.expire(item,obs['point'],'Observation gap exceeded 15 seconds; continuity unknown')
                qualifies = obs['qualifies'] and running
                reason = '; '.join(obs['reasons']) if running else 'Session stopped; historical observations only'
                if not qualifies:
                    self.expire(item, obs['point'], reason)
                    # Count distinct excluded input states, never poll repetitions.
                    state = stable([obs['signature'], obs['reasons'], running])
                    if item.get('excluded_state') != state:
                        for r in (obs['reasons'] if running else ['Session stopped']):self.exclusions[r] += 1
                    item['excluded_state'] = state
                elif item['signature'] != obs['signature']:
                    if not item['active']:
                        item['active'] = True; item['episodes'] += 1
                        item['observed_spans'].append(dict(first=obs['point'],last=obs['point'],samples=0,observed_seconds=0))
                        if len(item['observed_spans'])>64:item['observed_spans'].pop(0);self.dropped+=1
                        self.event('historical crossing' if historical else 'crossing',item,obs['point'],'Threshold met at an admitted observation; raw signals do not establish synchronized freshness or net profit' if watch['metric']=='raw_gap' else 'Supported conditional threshold met')
                    item['qualifying_observations'] += 1
                    item['first'] = item['first'] or obs['point']; item['last'] = obs['point']
                    span=item['observed_spans'][-1];span.update(last=obs['point'],samples=span['samples']+1,observed_seconds=seconds(obs['point']['at'],span['first']['at']))
                    change = dict(point=obs['point'],value=obs['metric'],size=obs['size'],basis=obs.get('basis'))
                    item['changes'].append(change)
                    if len(item['changes'])>64:item['changes'].pop(0);self.dropped+=1
                item.update(signature=obs['signature'],last_token=token,reasons=obs['reasons'],last_observed_point=obs['point'],basis=obs.get('basis'))
        for key,item in self.items.items():
            if key not in present or not running:
                self.expire(item,dict(at=at,cutoff=token),'Session stopped, changed, or comparison left watch coverage')
        return self.report(historical)

    def report(self, historical=False):
        return dict(version=VERSION,historical=historical,items=list(self.items.values()),events=self.events,
                    exclusions=dict(self.exclusions),dropped=self.dropped,
                    limits=dict(candidates=MAX_ITEMS,events=MAX_EVENTS,changes_per_candidate=64),
                    assumptions='Derived new-version analysis; original outputs unchanged. Sampled spans do not prove continuous availability. Gaps over 15s break spans. Repeated polling is not an observation. Shared liquidity and repeated quotes are never summed as profit. No fills or realized P&L inferred.')


def retained_history_key(folder,watches):
    from app.dashboard.e6_live import digest
    folder=Path(folder);manifest=folder/'manifest.json'
    if not manifest.exists():return None
    value=json.loads(manifest.read_text())
    for name,expected in value['files'].items():
        path=folder/name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or digest(path)!=expected:
            raise ValueError('saved file changed')
    return stable(dict(manifest=value,watches=watches,calculation_version=VERSION))


def build_history(folder, watches):
    from app.dashboard.session_history import verified
    p = SessionProjection(); signals = Signals(); evaluated=0; skipped=0; records=0
    data = verified(folder)
    for row in data['rows']:
        records += 1; p.apply(row)
        if row['type'] not in ('prediction_book','source_health','coverage_inventory','product_reference','product_aggregate','session_finished'):
            continue
        if evaluated >= max(1,MAX_EVALUATIONS // max(1,len(watches))):
            skipped += 1; continue
        snapshot=p.snapshot(mode='saved')
        signals.update(snapshot,watches,running=row['type']!='session_finished',historical=True)
        evaluated += 1
    snapshot=p.snapshot(mode='saved')
    # Saved sessions never leave a live signal, even when interrupted or capped.
    signals.update(snapshot,[],running=False,historical=True)
    report=signals.report(True)
    report.update(session=p.sid,mode=snapshot['data_mode'],source_cutoff=snapshot['durable_cursor'],watchlists=watches,
                  coverage=dict(records=records,evaluations=evaluated,skipped_cutoffs=skipped,complete=not skipped and data['state']=='complete',state=data['state']),
                  calculation_version=VERSION,projection_version=snapshot['projection_revision'])
    return report
