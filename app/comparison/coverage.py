"""Bounded sport/source observations and read-only inventory reconciliation.

Offering counts describe one exact query. Inventory counts describe the current
projection supplied by the caller. Neither one dispatches or renews a clock.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re
from app.dashboard.current_contract import stamp

VERSION = 'comparison-coverage-1'
SPORTS = ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')
VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx', 'pinnacle')
FAMILIES = ('moneyline', 'spread', 'total')
STATUSES = {'offerings_returned', 'no_offerings_returned', 'failed_source',
            'rejected_payload', 'not_checked'}
REASONS = {'query_empty', 'source_failed', 'payload_rejected', 'selector_unestablished',
           'query_capacity', 'mapping_unresolved', 'filtered_out', 'not_checked'}
COUNTS = ('games', 'markets', 'quotes')
DETAIL_CODES = set('''aggregate_event_bound aggregate_event_identity aggregate_books_shape aggregate_book_identity aggregate_market_identity aggregate_complete_two_way_required aggregate_outcome_identity aggregate_total_line_conflict aggregate_spread_line_conflict aggregate_quote_bound aggregate_decimal_price aggregate_binding_rejected aggregate_group_incomplete aggregate_schema_valueerror aggregate_schema_typeerror aggregate_schema_keyerror aggregate_schema_arithmeticerror aggregate_schema_stopiteration aggregate_transport_uncertain aggregate_rate_limit aggregate_authentication aggregate_http_failure malformed_catalog duplicate_catalog_identity native_http_timeout native_http_transport_error native_response_byte_cap native_wire_byte_cap native_entity_byte_cap native_decoded_byte_cap mapping_unresolved sanitized_failure'''.split())
DETAIL_CODES.update('aggregate_missing_'+k for k in ('markets','outcomes','price','point','home_team','away_team','commence_time','sport_key'))


def admission_code(value):
    return value if value in DETAIL_CODES or isinstance(value,str) and re.fullmatch(r'http_[1-5][0-9]{2}',value) else 'sanitized_failure'


class CoverageLedger:
    """Thirty fixed cells, one latest and one successful observation per cell."""
    def __init__(self, configured, families=FAMILIES):
        if set(configured) - set(VENUES) or any(set(s) - set(SPORTS) for s in configured.values()):
            raise ValueError('Unsupported coverage scope')
        if set(families) - set(FAMILIES):
            raise ValueError('Unsupported coverage family')
        self.configured = {v: tuple(configured.get(v, ())) for v in VENUES}
        self.families = tuple(families)
        self.observations = {}
        self.books = {}

    def observe_book(self, sport, venue, *, received_at, source_at):
        if sport not in SPORTS or venue not in VENUES:
            raise ValueError('Invalid book coverage identity')
        stamp(received_at)
        if source_at is not None:
            stamp(source_at)
        self.books[(sport, venue)] = dict(received_at=received_at, source_at=source_at)

    def observe(self, sport, venue, *, checked_at, status, offered=None,
                source_clocks=(), reason=None, evidence_sha256=None, family=None,
                completeness='unmeasured', query=None, detail_code=None):
        if sport not in SPORTS or venue not in VENUES or status not in STATUSES:
            raise ValueError('Invalid coverage cell/status')
        stamp(checked_at)
        if reason is not None and reason not in REASONS:
            raise ValueError('Coverage reasons are locally defined')
        if family is not None and family not in FAMILIES:
            raise ValueError('Invalid coverage family')
        if completeness not in ('unmeasured', 'partial', 'complete'):
            raise ValueError('Invalid query completeness')
        values = {k: None for k in COUNTS}
        if offered is not None:
            if set(offered) - set(COUNTS):
                raise ValueError('Invalid offering count')
            for key, value in offered.items():
                if value is not None and (type(value) is not int or not 0 <= value <= 10000):
                    raise ValueError('Invalid measured count')
                values[key] = value
        if status in ('failed_source', 'rejected_payload') and any(v is not None for v in values.values()):
            raise ValueError('Failed/rejected payload offerings remain unknown')
        if status == 'no_offerings_returned' and any(v not in (0, None) for v in values.values()):
            raise ValueError('Empty observation has positive offerings')
        clocks = sorted(set(source_clocks))
        if len(clocks) > 200:
            raise ValueError('Coverage clock bound')
        for clock in clocks:
            stamp(clock)
        if evidence_sha256 is not None and (len(evidence_sha256) != 64 or any(c not in '0123456789abcdef' for c in evidence_sha256)):
            raise ValueError('Invalid receipt hash')
        # Store a hash of the exact request, never provider text or private URLs.
        query_hash = None if query is None else sha256(json.dumps(query, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        value = dict(checked_at=checked_at, status=status, offered=values,
                     source_clocks=clocks, reason=reason, receipt_sha256=evidence_sha256,
                     family=family, completeness=completeness, query_sha256=query_hash,
                     admission_code=None if detail_code is None else admission_code(detail_code))
        key = (sport, venue)
        previous = self.observations.get(key, {})
        if previous.get('latest') and stamp(checked_at) < stamp(previous['latest']['checked_at']):
            raise ValueError('Coverage check clock regressed')
        success = value if status in ('offerings_returned', 'no_offerings_returned') else previous.get('last_success')
        self.observations[key] = dict(latest=value, last_success=deepcopy(success))

    def snapshot(self, inventory=(), *, sports=None, venues=None, families=None, exclusions=()):
        """Reconcile against *all* supplied current rows and caller display filters.

        Unresolved rows remain admitted source-local prices. They are measured
        separately, so they do not masquerade as rejected/disappeared prices.
        """
        rows = list(inventory)
        if len(rows) > 10000 or len(exclusions) > 1000:
            raise ValueError('Coverage inventory bound')
        allowed_s = set(SPORTS if sports is None else sports)
        allowed_v = set(VENUES if venues is None else venues)
        allowed_f = set(FAMILIES if families is None else families)
        if allowed_s - set(SPORTS) or allowed_v - set(VENUES) or allowed_f - set(FAMILIES):
            raise ValueError('Invalid coverage filters')
        identities = set()
        pools = {}
        for row in rows:
            if row.get('sport') not in SPORTS or row.get('venue') not in VENUES or row.get('family') not in FAMILIES:
                raise ValueError('Unrecognized inventory identity')
            identity = (row['venue'], row['id'])
            if identity in identities:
                raise ValueError('Duplicate inventory quote')
            identities.add(identity)
            pools.setdefault((row['sport'], row['venue']), []).append(row)
        cells = []
        for sport in SPORTS:
            for venue in VENUES:
                context = deepcopy(self.observations.get((sport, venue), {}))
                latest = context.get('latest')
                local = pools.get((sport, venue), [])
                shown = [r for r in local if sport in allowed_s and venue in allowed_v and r['family'] in allowed_f]
                unresolved = sum(r.get('mapping_verified') is False for r in local)
                reasons = sorted({e['reason'] for e in exclusions if e.get('sport') == sport and e.get('venue') == venue and e.get('reason') in REASONS})
                status = latest['status'] if latest else 'not_checked'
                display_reason = ('filtered_out' if local and not shown else 'mapping_unresolved' if unresolved else
                                  latest.get('reason') if latest else 'not_checked')
                cells.append(dict(sport=sport, venue=venue, configured=sport in self.configured[venue],
                    configured_families=list(self.families), checked=latest is not None,
                    status=status, latest=latest, last_success=context.get('last_success'),
                    last_book=deepcopy(self.books.get((sport,venue))),
                    counts=dict(admitted_quotes=len(local), displayed_quotes=len(shown),
                                filtered_quotes=len(local)-len(shown), unresolved_mapping_quotes=unresolved,
                                rejected_quotes=None, rejected_markets=sum(e.get('sport')==sport and e.get('venue')==venue for e in exclusions)),
                    admitted_family_counts={f: sum(r['family'] == f for r in local) for f in FAMILIES},
                    displayed_family_counts={f: sum(r['family'] == f for r in shown) for f in FAMILIES},
                    display_reason=display_reason, exclusion_reasons=reasons))
        return dict(schema=VERSION, evidence_class='current projection and exact query observations',
                    cells=cells, totals=dict(admitted_quotes=len(rows), displayed_quotes=sum(c['counts']['displayed_quotes'] for c in cells),
                                             filtered_quotes=sum(c['counts']['filtered_quotes'] for c in cells)))


def current_rows(index):
    """Convert the existing store index; use actual source instruments once."""
    result=[]
    for item in index.values():
        quote=item['quote']
        family=item['group'].get('market',item['group'].get('family'))
        result.append(dict(id=quote['id'],sport=item['event']['league'],venue=quote['venue'],
            family={'winner':'moneyline'}.get(family,family),mapping_verified=quote['binding']['verified']))
    return result


def aggregate_observation(ledger, body, sport, received_at, rejected=None):
    """Count sanitized complete aggregate offerings, before display filtering."""
    rejected = rejected or {}
    try:
        payload = json.loads(body)
        if not isinstance(payload, list) or len(payload) > 200:
            raise ValueError()
        receipt = sha256(body).hexdigest()
        for venue in ('novig', 'prophetx', 'pinnacle'):
            if venue in rejected:
                ledger.observe(sport, venue, checked_at=received_at, status='rejected_payload', reason='payload_rejected', evidence_sha256=receipt,detail_code=rejected[venue])
                continue
            games = markets = quotes = 0
            clocks = set()
            for event in payload:
                books = [b for b in event['bookmakers'] if b['key'] == venue]
                if books:
                    games += 1
                for book in books:
                    if book.get('last_update'):
                        clocks.add(book['last_update'])
                    for market in book['markets']:
                        markets += 1
                        quotes += len(market['outcomes'])
                        if market.get('last_update'):
                            clocks.add(market['last_update'])
            ledger.observe(sport, venue, checked_at=received_at,
                status='offerings_returned' if quotes else 'no_offerings_returned',
                offered=dict(games=games, markets=markets, quotes=quotes), source_clocks=clocks,
                reason=None if quotes else 'query_empty', evidence_sha256=receipt, completeness='complete')
    except (ValueError, KeyError, TypeError, UnicodeError):
        for venue in ('novig', 'prophetx', 'pinnacle'):
            ledger.observe(sport, venue, checked_at=received_at, status='rejected_payload', reason='payload_rejected')
