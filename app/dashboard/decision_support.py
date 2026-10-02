"""Derived decision support over frozen inputs and the ordinary calculation path.

Never changes a retained calculation, source journal, or collection authority.
"""
from decimal import Decimal
from app.dashboard.query_policy import decimal_input

VERSION = 'decision-support-1'


def explanation(row):
    audit = row.get('settlement_audit') or row.get('settlement')
    audit = audit if isinstance(audit, dict) else {}
    settlement = []
    for conflict in audit.get('conflicts', []):
        def value(part):
            return str(part.get('value') or part.get('reason') or part.get('kind') or 'unknown')
        settlement.append(conflict['condition'].replace('_', ' ') + ': ' + value(conflict['left']) + ' versus ' + value(conflict['right']))
    unknown = [x['condition'].replace('_', ' ') for x in audit.get('unknown', [])]
    if unknown:
        settlement.append('Unverified conditions: ' + ', '.join(unknown))
    if not settlement:
        settlement.append('Material settlement terms match at this cutoff.' if audit.get('qualified') else 'Exact native settlement terms or effective coverage are missing.')
    costs, quantity, freshness, reasons = [], [], [], list(row.get('reasons', []))
    for leg in row.get('legs', []):
        label = leg.get('label', leg.get('venue', 'Venue'))
        entry = leg.get('entry')
        fee = leg.get('fee_audit') or {}
        if entry is not None:
            costs.append(label + ': ' + entry['basis'])
            if entry.get('upper') is None:
                reasons.append(label + ': ' + entry.get('reason', 'entry cost unavailable'))
        elif leg.get('fee') is not None:
            costs.append(label + ': modeled entry fee $' + leg['fee'] + '; ' + str((fee.get('schedule') or {}).get('version', 'retained fee scenario')) + '. Account and exceptional settlement charges are not established by this scenario.')
        else:
            costs.append(label + ': entry fees unknown; no zero charge assumed.')
        reasons.extend(label + ': ' + r for r in leg.get('reasons', leg.get('warnings', [])))
        quantity.append(label + ': ' + str(leg.get('top_size') or 'unknown') + ' contracts at the top price; ' + str(leg.get('visible_size') or 'unknown') + ' in supplied depth. ' + leg.get('transformation', 'Native quantity rules apply.'))
        freshness.append(label + ': receipt age ' + str(leg.get('age_seconds', 'unknown')) + ' seconds; ' + str(leg.get('connection', 'unknown')) + '.')
    if not audit.get('qualified') and not row.get('rule_analysis'):
        reasons.extend(settlement)
    if row.get('timing'):
        freshness.append('Receipt alignment ' + str(row['timing'].get('receipt_skew_seconds')) + ' seconds. ' + row['timing']['reason'])
    research = row.get('rule_analysis')
    if research:
        settlement = [research['summary']]
        reasons.extend(research['blockers'])
        for book, assessment in research.get('books', {}).items():
            for item in assessment['facts']:
                if item['topic'] == 'fees':
                    costs.append(book + ' documented only: ' + item['summary'])
                else:
                    settlement.append(book + ' documented only: ' + item['summary'])
    public=row.get('public_contracts')
    if public:
        settlement.append(public['summary'])
        for venue,document in public.get('fee_rules',{}).items():
            costs.append(venue+' public successor rule: '+document['clause']+' Effective listing/account association and scenario fills checked separately.')
        if public.get('contract_templates'):
            settlement.append('Documented scope rules: '+', '.join(dict.fromkeys(x['document']['id'] for x in public['contract_templates']))+'. Exact selected predicate and exceptional decision applicability remain separate.')
        for identity in public['identity']:
            enrichment=identity.get('enrichment')
            if enrichment:
                settlement.append(identity['original']['source']+': authoritative '+enrichment['season']+' '+enrichment['stage']+'; '+identity['qualification'])
                settlement.extend(identity['conflicts'])
            else:settlement.append(identity['original']['source']+': '+identity['reason'])
    unavailable = row.get('profit', row.get('net')) is None
    if unavailable:
        if any(l.get('entry') for l in row.get('legs', [])):
            reasons.append('Entry ranges are provisional; mandatory settlement/private charges are unknown. Same-outcome prices are alternatives, not a combined hedge.')
        if ('probability' in row or 'ev' in row) and row.get('probability') is None:
            reasons.append('EV requires a supported probability for this exact contract.')
    return dict(version=VERSION, settlement=settlement, costs=costs, freshness=freshness,
                quantity=quantity, net_reason=list(dict.fromkeys(reasons)) if unavailable else [],
                conclusion='Net result unavailable.' if unavailable else 'Conditional modeled return only; exceptional outcomes and account costs remain as stated. No realized profit or guaranteed fill.')


def sizes(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError('Choose one to eight explicit contract sizes')
    result = []
    for v in value:
        n = decimal_input(v, 'size')
        if not 0 < n <= 100000000:
            raise ValueError('Size must be positive and at most 100,000,000')
        result.append(str(n))
    return list(dict.fromkeys(result))


def size_report(snapshot, game, options):
    """No parallel fee solver: every whole-contract scenario uses product_view.

    Fractional entry walks use the same native entry-bound/consume path. The
    ordinary equal-leg engine has no supported fractional payout domain, so
    these retain costs where supported and explicitly withhold net results.
    """
    from app.dashboard.product_view import calculate
    from app.dashboard.price_comparison import entry_cost
    from app.opportunities.board import contracts
    if game.get('native_raw'):
        from app.dashboard.native_book_comparison import entry as entry_cost
    requested = sizes(options.get('sizes', ['1', '10', '100']))
    ceiling = options.get('ceiling')
    if ceiling not in (None, ''):
        ceiling = decimal_input(ceiling, 'spending ceiling')
        if ceiling <= 0:
            raise ValueError('Spending ceiling must be positive')
    else:
        ceiling = None
    point = snapshot['points'][game['id']]
    results = []
    native_contracts=contracts(point,game)
    for quantity in requested:
        q = Decimal(quantity)
        acquisitions=[dict(venue=c['venue'],contract=c['contract'],visible_size=c['visible_size'],entry=entry_cost(c,q,point['at'],game['product_identity'],game['sources'][c['venue']])) for c in native_contracts.values()]
        if game.get('native_raw'):
            results.append(dict(requested=quantity, candidates=[], acquisitions=acquisitions, fractional_entries=[], limitation='Raw native depth arithmetic and explicitly conditional fee scenarios only. Settlement conflicts, effective fee coverage and fair probability prevent net/EV sizing. No execution guarantee.'))
            continue
        if q != q.to_integral_value():
            legs = []
            for c in contracts(point, game).values():
                entry = entry_cost(c, q, point['at'], game['product_identity'], game['sources'][c['venue']])
                legs.append(dict(venue=c['venue'], contract=c['id'], entry=entry, visible_size=c['visible_size']))
            results.append(dict(requested=quantity, candidates=[], fractional_entries=legs,acquisitions=acquisitions,
                                limitation='Fractional entry arithmetic only where the native increment is retained; equal-leg conditional return engine requires whole contracts. No rounding up to an unsupported size.'))
            continue
        calculation = calculate(snapshot, game, dict(quantity=quantity, scenario=options.get('scenario', 'unknown'),
                               contract=options.get('contract') or next(iter(game['sides'])),
                               probability=options.get('probability'), reference=options.get('reference', '')))
        candidates = []
        for row in calculation['candidates']:
            row = dict(row)
            row['within_ceiling'] = None if ceiling is None or row.get('cash') is None else Decimal(row['cash']) <= ceiling
            row['decision'] = explanation(row)
            # Native locked fees can still support a provisional entry range.
            row['provisional_entries'] = [dict(venue=l['venue'], contract=l['id'],
                entry=entry_cost(l, Decimal(row['modeled_quantity']), point['at'], game['product_identity'], game['sources'][l['venue']]))
                for l in row['legs']] if snapshot.get('qualification_fee_policy') else []
            candidates.append(row)
        results.append(dict(requested=quantity, acquisitions=acquisitions, candidates=candidates, ev=calculation['ev'], assumptions=calculation['assumptions']))
    eligible = [c for s in results for c in s['candidates'] if c.get('profit') is not None and c.get('usable') and c.get('within_ceiling') is not False]
    best = max(eligible, key=lambda c: Decimal(c['profit']), default=None)
    return dict(version=VERSION, session=snapshot['session_id'], cutoff=point['id'], at=point['at'],
                mode=snapshot['data_mode'], historical=True, sizes=results, ceiling=None if ceiling is None else str(ceiling),
                best=None if best is None else dict(candidate=best['id'], quantity=best['modeled_quantity'], profit=best['profit'], cash=best['cash']),
                search='Best conditional net among supplied explicit sizes only; incomplete search of the full depth domain. Shared liquidity; alternatives cannot be added. Both modeled legs must fill. Provisional or unknown costs cannot establish an affordable net opportunity.',
                original_outputs='Derived analysis under '+VERSION+'; original saved outputs unchanged.')
