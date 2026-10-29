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
        configured_families={v:tuple(families.get(v,FAMILIES)) for v in VENUES} if isinstance(families,dict) else {v:tuple(families) for v in VENUES}
        if any(set(values)-set(FAMILIES) for values in configured_families.values()):
            raise ValueError('Unsupported coverage family')
        self.configured = {v: tuple(configured.get(v, ())) for v in VENUES}
        self.configured_families=configured_families
        self.families = tuple(f for f in FAMILIES if any(f in values for values in configured_families.values()))
        self.observations = {}
        self.family_observations = {}
        self.books = {}
        from .offered_scope import NativePriceInventory
        self.native_prices=NativePriceInventory()
        self.offered_units={}

    def observe_native_price(self,venue,book,catalog,disposition):
        self.observe_native_prices(venue,[book],catalog,disposition)

    def observe_native_prices(self,venue,books,catalog,disposition):
        """Reconcile a complete admission batch, counting each affected cell once."""
        events={e['id']:e for e in catalog.get('events',[])}
        markets={m['id']:m for m in catalog.get('markets',[])}
        affected=set()
        for book in books:
            ref=book['raw']['ref']
            event=events.get(ref['event_id']);market=markets.get(ref['market_id'])
            if not event or not market:continue
            sport=event.get('competition');family=market.get('market_type')
            if sport not in SPORTS or family not in FAMILIES:continue
            self.native_prices.observe(venue,sport,family,book,disposition)
            affected.add((sport,family))
        for sport,family in affected:
            context=self.family_observations.get((sport,venue,family),{})
            counts=self.native_prices.counts(venue,sport,family)
            for name in ('latest','last_success'):
                if context.get(name):
                    context[name].setdefault('inventory',{}).update(counts)

    def observe_book(self, sport, venue, *, received_at, source_at):
        if sport not in SPORTS or venue not in VENUES:
            raise ValueError('Invalid book coverage identity')
        stamp(received_at)
        if source_at is not None:
            stamp(source_at)
        self.books[(sport, venue)] = dict(received_at=received_at, source_at=source_at)

    def observe(self, sport, venue, *, checked_at, status, offered=None,
                source_clocks=(), reason=None, evidence_sha256=None, family=None,
                completeness='unmeasured', query=None, detail_code=None,
                unique_offered=None, offered_scope='exact_query', inventory=None):
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
                if value is not None and (type(value) is not int or value < 0):
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
        if unique_offered is not None:
            if (not isinstance(unique_offered,dict) or set(unique_offered)-set(COUNTS)
                    or any(v is not None and (type(v) is not int or v<0) for v in unique_offered.values())
                    or offered_scope not in ('exact_query','bounded_listing_and_selected_metadata','complete_listing_and_metadata_traversal_price_boundary_unverified')):
                raise ValueError('Invalid unique query measurement')
            if status in ('failed_source','rejected_payload') and any(v is not None for v in unique_offered.values()):
                raise ValueError('Failed query unique totals remain unknown')
            value.update(unique_offered={k:unique_offered.get(k) for k in COUNTS},offered_scope=offered_scope)
        if inventory is None:
            inventory=dict(route='native_listing' if venue in ('kalshi','polymarket_us') else 'sport_odds',
                requested_scope=dict(sport=sport,family=family,period='full_game',venue=venue),
                started_at=None,completed_at=checked_at,pages=None,exhausted=False,continuation=None,
                failures=1 if status in ('failed_source','rejected_payload') else 0,
                denominator_status='unknown',received=None,admitted=None,rejected=None,omitted=None,pending=None,
                omission_reasons={reason or 'inventory_unmeasured':1},provider_universe_complete=False)
        if venue in ('kalshi','polymarket_us') and family is not None:
            inventory.update(self.native_prices.counts(venue,sport,family))
        value['inventory']=deepcopy(inventory)
        key = (sport, venue)
        previous = self.observations.get(key, {})
        if previous.get('latest') and stamp(checked_at) < stamp(previous['latest']['checked_at']):
            raise ValueError('Coverage check clock regressed')
        success = value if status in ('offerings_returned', 'no_offerings_returned') else previous.get('last_success')
        self.observations[key] = dict(latest=value, last_success=deepcopy(success))
        if family is not None:
            previous=self.family_observations.get((sport,venue,family),{})
            success=value if status in ('offerings_returned','no_offerings_returned') else previous.get('last_success')
            self.family_observations[(sport,venue,family)]=dict(latest=deepcopy(value),last_success=deepcopy(success))

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
                    configured_families=list(self.configured_families[venue]), checked=latest is not None,
                    status=status, latest=latest, last_success=context.get('last_success'),
                    last_book=deepcopy(self.books.get((sport,venue))),
                    counts=dict(admitted_quotes=len(local), displayed_quotes=len(shown),
                                filtered_quotes=len(local)-len(shown), unresolved_mapping_quotes=unresolved,
                                rejected_quotes=None, rejected_markets=sum(e.get('sport')==sport and e.get('venue')==venue for e in exclusions)),
                    admitted_family_counts={f: sum(r['family'] == f for r in local) for f in FAMILIES},
                    displayed_family_counts={f: sum(r['family'] == f for r in shown) for f in FAMILIES},
                    family_queries=[dict(family=family,configured=sport in self.configured[venue] and family in self.configured_families[venue],
                        **deepcopy(self.family_observations.get((sport,venue,family),dict(latest=None,last_success=None)))) for family in FAMILIES],
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


def aggregate_observation(ledger, body, sport, received_at, rejected=None, *, parsed_frame=None,
                          records=(), started_at=None, query=None, admitted_at=None):
    """Measure each venue independently, including rejected price identities."""
    try:
        payload=json.loads(body) if parsed_frame is None else parsed_frame.payload
        if not isinstance(payload,list):raise ValueError()
        receipt=sha256(body).hexdigest() if parsed_frame is None else parsed_frame.receipt_sha256
    except (ValueError,UnicodeError):
        payload=None;receipt=None
    for venue in ('novig','prophetx','pinnacle'):
        try:
            if payload is None:raise ValueError()
            _aggregate_venue_observation(ledger,payload,sport,venue,received_at,rejected or {},
                records,started_at,query,admitted_at,receipt)
        except (ValueError,KeyError,TypeError,UnicodeError,AttributeError):
            for family in ledger.configured_families[venue]:
                ledger.observe(sport,venue,family=family,checked_at=received_at,status='rejected_payload',
                    reason='payload_rejected',completeness='unmeasured')


def _aggregate_venue_observation(ledger,payload,sport,venue,received_at,rejected,
                               records,started_at,query,admitted_at,receipt):
    from .offered_scope import aggregate_inventory
    summaries=[]
    clocks={clock for e in payload for b in e.get('bookmakers',[]) if b.get('key')==venue
        for clock in [b.get('last_update'),*[m.get('last_update') for m in b.get('markets',[])]] if clock}
    for family in ledger.configured_families[venue]:
        inventory=aggregate_inventory(payload,venue,family,records,rejected=venue in rejected)
        inventory.update(route='sport_odds',requested_scope=dict(sport=sport,family=family,
            period='full_game',bookmaker=venue),started_at=started_at or received_at,
            completed_at=received_at,admitted_at=admitted_at,source_clocks=sorted(clocks),pages=1,exhausted=True,continuation=False,failures=0)
        units=set(inventory.pop('_unit_ids'))
        previous=ledger.offered_units.get((sport,venue,family))
        inventory.update(added_units=None if previous is None else len(units-previous),
            withdrawn_units=None if previous is None else len(previous-units),
            reconciliation='exact response replacement' if previous is not None else 'first measured boundary this runtime')
        ledger.offered_units[sport,venue,family]=units
        summaries.append(inventory)
        counts=inventory['unique_offered']
        ledger.observe(sport,venue,family=family,checked_at=received_at,
            status='offerings_returned' if counts['quotes'] else 'no_offerings_returned',
            offered=counts,unique_offered=counts,reason=None if counts['quotes'] else 'query_empty',
            evidence_sha256=receipt,completeness='complete',query=query,inventory=inventory,
            detail_code=rejected.get(venue),source_clocks=clocks)
    total=dict(games=len({e['id'] for e in payload if any(b.get('key')==venue for b in e.get('bookmakers',[]))}),
        markets=sum(i['unique_offered']['markets'] for i in summaries),quotes=sum(i['received'] for i in summaries))
    ledger.observe(sport,venue,checked_at=received_at,
        status='rejected_payload' if venue in rejected else 'offerings_returned' if total['quotes'] else 'no_offerings_returned',
        offered=None if venue in rejected else total,unique_offered=None if venue in rejected else total,
        reason='payload_rejected' if venue in rejected else None if total['quotes'] else 'query_empty',
        evidence_sha256=receipt,completeness='complete',query=query,source_clocks=clocks,
        detail_code=rejected.get(venue))
