"""Historical personal exploration over validated E6 projections; no collector/storage."""
from decimal import Decimal, Context, localcontext
from hashlib import sha256
import json
from app.depth import consume
from app.fees import calculate
from app.fees.engine import number
from app.settlement import profile, fact, payout, compare_profiles, relationships, SCENARIOS
from app.arbitrage import Policy, total
from app.dashboard.e6_real import exact_time

ASSESSMENT_AT = '2026-09-16T00:27:31+00:00'
TEAMS = ('Buffalo Bills', 'Detroit Lions')
SIDES = {'kalshi:yes':dict(native_id='yes',participant=TEAMS[0],predicate='win'),
         'kalshi:no':dict(native_id='no',participant=TEAMS[0],predicate='not_win'),
         'polymarket_us:1315440':dict(native_id='1315440',participant=TEAMS[1],predicate='win'),
         'polymarket_us:1315441':dict(native_id='1315441',participant=TEAMS[0],predicate='win')}
CANDIDATES = [('cross-buffalo','Buffalo + Detroit · cross-venue',('kalshi:yes','polymarket_us:1315440')),
              ('kalshi-pair','Buffalo YES + NO · same-market comparison',('kalshi:yes','kalshi:no')),
              ('cross-detroit','Detroit + Buffalo · reverse pair',('kalshi:no','polymarket_us:1315441'))]

def textnum(n): return None if n is None else format(n,'f')
def display(n, places=2): return 'Unavailable' if n is None else format(Decimal(n),f'.{places}f')

def assess(rows, cutoff, identity=None):
    """Later analysis of only listing metadata already retained at this cutoff."""
    if identity and identity.get('product_identity',{}).get('competition')=='NHL':
        from app.normalization.nhl import assessment
        return assessment(rows,cutoff,identity)
    if identity and identity.get('product_identity',{}).get('competition')=='MLB':
        from app.normalization.mlb import assessment
        return assessment(rows,cutoff,identity)
    if identity and identity.get('product_identity',{}).get('competition')=='NBA':
        from app.normalization.nba import assessment
        return assessment(rows,cutoff,identity)
    if identity and identity.get('product_identity',{}).get('competition')=='NCAAF':
        from app.normalization.ncaaf import assessment
        return assessment(rows,cutoff,identity)
    if identity and identity.get('product_identity',{}).get('competition')=='NCAAB':
        from app.normalization.ncaab import assessment
        return assessment(rows,cutoff,identity)
    profiles={};sources={};coefficient=None
    for venue in ('kalshi','polymarket_us'):
        eligible=[r for r in rows if r['type']=='market_selected' and r['source']==venue and exact_time(r['observed_at'])<=exact_time(cutoff)]
        if not eligible: continue
        row=eligible[-1];raw=row['market']['raw'];native=json.loads(raw['json_text'],parse_float=str)
        if venue=='kalshi':
            m=next(m for m in native['markets'] if m['ticker']==(identity['sources'][venue]['market_id'] if identity else 'KXNFLGAME-26SEP17DETBUF-BUF'))
            text='\n\n'.join(m[k] for k in ('rules_primary','rules_secondary'))
            if (not identity and 'If Buffalo wins the DET Lions vs BUF Bills' not in text) or 'within 48 hours' not in text or '$0.50' not in text: raise ValueError('unrecognized retained Kalshi terms')
            postpone='begins within 48 hours of original start; otherwise venue fair price'
        else:
            candidates=native.get('markets',[])+[m for e in native.get('events',[]) if str(e['id'])==(identity['sources'][venue]['event_id'] if identity else '101466') for m in e['markets']]
            m=next(m for m in candidates if str(m['id'])==(identity['sources'][venue]['market_id'] if identity else '657964'))
            text=m['description'];coefficient=str(m.get('feeCoefficient'))
            if (not identity and 'Detroit Lions vs Buffalo Bills' not in text) or 'rescheduled to a date within two days' not in text or '$0.50' not in text:raise ValueError('unrecognized retained US terms')
            postpone='rescheduled date within two days; otherwise last fair market price'
        h=sha256(text.encode()).hexdigest();source=dict(url=raw['source'],sha256=h,text=text,priority='market-specific',received_at=raw['received_at'])
        profiles[venue]=profile(sources=[source],actor='Codex bounded retrospective assessment',
            dimensions={'tie':fact('fraction-0.50',evidence=h),'postponement':fact(postpone,evidence=h)},
            payouts={'tie':dict(kind='fraction',value='0.5',evidence=h),
                     'postponed_outside_window':dict(kind='discretionary',evidence=h,reason='venue-specific fair value; not a stake refund')})
        sources[venue]=dict(source=source,known_at=row['observed_at'],market_id=raw['ref']['market_id'])
    return dict(assessed_at=(identity.get('assessment_at') or __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat() if identity else ASSESSMENT_AT),observation_cutoff=cutoff,profiles=profiles,sources=sources,pmus_coefficient=coefficient,
                note='Retrospective assessment, not knowledge asserted available at the historical cutoff.')

def contracts(point, identity=None):
    sides = identity['sides'] if identity else SIDES
    result={}
    for card in point['cards']:
        b=card['book'];v=card['venue']
        for key,side in sides.items():
            if not key.startswith(v+':'):continue
            native=side.get('native_id',key.split(':')[1]);o=None if b is None else next(o for o in b['outcomes'] if o['side']==native)
            levels=None;transform='native ask only'
            if o is not None and o['quote']['ask'] is not None:
                ladder=o['depth']['asks']
                if v=='kalshi' and len(b['outcomes'])!=2:
                    ladder=None;transform='Unreviewed multi-outcome Kalshi depth; no arbitrary complement'
                elif v=='kalshi':
                    other=next(x for x in b['outcomes'] if x['side']!=native)
                    ladder=other['depth']['bids'];transform='1 minus opposite Kalshi bid; same quantity'
                if ladder is not None:
                    levels=[dict(price=textnum(1-Decimal(l['price']['value'])) if v=='kalshi' else l['price']['value'],quantity=l['quantity']['value'],provenance=b['id']) for l in ladder['levels']]
                    levels.sort(key=lambda l:Decimal(l['price']))
                    if levels and (Decimal(levels[0]['price'])!=Decimal(o['quote']['ask']) or Decimal(levels[0]['quantity'])!=Decimal(o['quote']['ask_size'])):raise ValueError('adapter ask/depth mismatch')
            warnings=[]
            if not b:warnings.append('No book retained by this cutoff')
            else:
                if card['receipt_stale']:warnings.append('Receipt stale at cutoff')
                if card['connection']!='connected':warnings.append('Venue '+card['connection']+' at cutoff')
                if b['sync']!='synchronized':warnings.append('Book unsynchronized at cutoff')
                if b['market_state']!='active':warnings.append('Market is not active at cutoff')
                if b['source_progress'] not in ('advanced','unchanged','initial','first','repeated'):warnings.append('Source-time progress: '+b['source_progress'])
            if not levels:warnings.append('No supported purchasable ask')
            result[key]=dict(id=key,venue=v,label=card['label'],side=native,team=side['participant'],
                contract=((side['participant']+' does not win (NO)' if identity else 'Buffalo does not win (NO)') if side.get('predicate')=='not_win' else side['participant']+' '+('YES' if v=='kalshi' else '' if side.get('native_label')==side['participant'] else side.get('native_label', 'Long' if native=='1315440' else 'Short'))),
                ask=None if not o else o['quote']['ask'],top_size=None if not o else o['quote']['ask_size'],
                visible_size=None if levels is None else textnum(sum((Decimal(l['quantity']) for l in levels),Decimal(0))),
                levels=levels,transformation=transform,warnings=warnings,age_seconds=card['age_seconds'],connection=card['connection'],
                received_at=None if not b else b['received_at'],source_at=None if not b else b['source_at'],book_id=None if not b else b['id'])
    return result

def leg_value(contract, assessment, at, quantity, scenario, identity=None, score_payouts=None):
    sides=identity['sides'] if identity else SIDES
    teams=identity['teams'] if identity else TEAMS
    result={**contract,'fills':None,'notional':None,'fee_audit':None,'cash':None,'fee':None,'cashflows':{},'reasons':list(contract['warnings'])}
    if not contract['levels']:return result
    try:fills=consume(contract['levels'],str(quantity))
    except ValueError as exc:result['reasons'].append(str(exc));return result
    result['fills']=fills;result['notional']=textnum(sum((Decimal(f['price'])*Decimal(f['quantity']) for f in fills),Decimal(0)))
    v=contract['venue'];p=assessment['profiles'].get(v)
    if p is None:
        if v in ('novig','prophetx'):
            from app.collection.native_semantics import SEMANTICS
            result['reasons'] += [SEMANTICS[v]['fees'],SEMANTICS[v]['settlement']]
        else:result['reasons'].append('Unsupported source fee/settlement handler' if v not in ('kalshi','polymarket_us') else 'Listing terms missing at cutoff')
        return result
    side=sides[contract['id']]
    pays=score_payouts if score_payouts is not None else {s:payout(side,s,p) for s in [*('winner:'+t for t in teams),*SCENARIOS]}
    outcomes={s:x['value'] for s,x in pays.items() if x['kind']=='fraction'}
    c=dict(venue=v,environment='production',market_id=assessment['sources'][v]['market_id'],product='event_contract',
           trade_time=at,calculation_time=assessment['assessed_at'],complete_order_history=True,settlement_status='UNKNOWN',
           fills=[dict(fill_id=str(i),order_id='hypothetical-new-order',role='taker',price=f['price'],quantity=f['quantity'],unit='contracts') for i,f in enumerate(fills)],outcomes=outcomes)
    if score_payouts is not None:
        c['refund_outcomes']=[s for s,x in pays.items() if x['kind']=='stake_refund']
    sport=identity.get('product_identity',{}).get('competition') if identity else None
    reviewed_sport=sport in ('NHL','MLB','NBA','NCAAF','NCAAB') or (sport=='NFL' and score_payouts is not None)
    series={'MLB':'KXMLBGAME','NBA':'KXNBAGAME','NCAAF':'KXNCAAFGAME','NCAAB':'KXNCAAMBGAME'}.get(sport,'KXNHLGAME')
    fee_key=sport.lower()+'_fee_bases' if reviewed_sport else 'nhl_fee_bases'
    basis=assessment.get(fee_key,{}).get(v) if reviewed_sport else None
    if reviewed_sport and not basis:
        result['reasons'].append(sport+' source fee basis missing');return result
    fee_type='quadratic_with_maker_fees'
    if score_payouts is not None and v=='kalshi':
        series=basis.get('series_id')
        allowed=('KXNHL' if sport=='NHL' else 'KXMLB' if sport=='MLB' else 'KXNBA' if sport=='NBA' else 'KXNFL' if sport=='NFL' else 'KXNCAAF' if sport=='NCAAF' else 'KXNCAAMB')+('SPREAD' if identity['product_identity']['family']=='spread' else 'TOTAL')
        from app.normalization import score_periods
        if score_periods.scope(identity['product_identity']) or identity['product_identity']['family']=='futures':allowed=identity['score_reviews'][v]['descriptor']['series_id']
        if sport in ('NFL','NCAAF','NBA','NCAAB') and identity['product_identity']['period']=='first_half':
            from app.normalization.first_half import series as half_series
            allowed=half_series(identity['product_identity'])
        if series!=allowed or basis.get('fee_type') not in ('quadratic','quadratic_with_maker_fees'):
            result['reasons'].append('Score-line native fee series/type unavailable');return result
        fee_type=basis['fee_type']
    if sport=='NCAAF' and v=='kalshi' and score_payouts is None:
        series=basis.get('series_id')
        fee_type={'KXNCAAFGAME':'quadratic_with_maker_fees','KXNCAAFCSGAME':'quadratic'}.get(series)
        if not fee_type:
            result['reasons'].append('Unsupported NCAAF native series fee basis');return result
    if reviewed_sport and v=='kalshi' and (basis.get('series_id')!=series or basis.get('fee_type')!=fee_type or basis.get('multiplier') not in (('0.5','1') if sport=='MLB' else ('1',))):
        result['reasons'].append('Unsupported '+sport+' fee basis');return result
    multiplier=basis['multiplier'] if reviewed_sport and v=='kalshi' else '1'
    if v=='kalshi':
        c.update(schedule_version='kalshi-july7-observed-sep12')
        if scenario!='unknown':
            c.update(series_id=series if reviewed_sport else 'KXNFLGAME',event_id=identity['sources']['kalshi']['event_id'] if identity else 'KXNFLGAME-26SEP17DETBUF',balance_precision='0.0001' if scenario=='direct' else '0.01',
                kalshi_metadata=dict(source='Explicit what-if: retained series type, multiplier '+multiplier+'; no event override',series_id=series if reviewed_sport else 'KXNFLGAME',event_id=identity['sources']['kalshi']['event_id'] if identity else 'KXNFLGAME-26SEP17DETBUF',event_history_complete=False,
                    series_changes=[dict(scheduled_ts=at,fee_type=fee_type,fee_multiplier=multiplier)],event_changes=[]))
    elif v=='polymarket_us':
        if assessment['pmus_coefficient']!='0.06':result['reasons'].append('Retained coefficient not supported by pinned schedule');return result
        c.update(schedule_version='pmus-2026-07-01',applicability_evidence=assessment['sources'][v],assume_no_settlement_fee=scenario!='unknown',taker_rebate_rate='0')
    else:
        result['reasons'].append('Unsupported source fee handler');return result
    audit=calculate(c);result['fee_audit']=audit
    result['cash']=audit['entry_cash_requirement'];result['fee']=None if result['cash'] is None else textnum(Decimal(result['cash'])-Decimal(result['notional']))
    result['cashflows']={s:audit['outcomes'].get(s) for s in pays}
    result['reasons']+=audit['unsupported']
    if any(x['net_cashflow'] is None for x in audit['outcomes'].values()):
        result['reasons'].append('Polymarket US settlement charge unresolved; net payout and break-even unavailable')
    return result

def expected(leg, probability, quantity, identity=None):
    teams=identity['teams'] if identity else TEAMS
    win='winner:'+(next(t for t in teams if t!=leg['team']) if (identity['sides'][leg['id']]['predicate']=='not_win' if identity else leg['id']=='kalshi:no') else leg['team'])
    lose=next('winner:'+t for t in teams if 'winner:'+t!=win)
    flows=leg['cashflows'];a=flows.get(win);b=flows.get(lose)
    result=dict(probability=textnum(probability),probability_source='User-entered normal-settlement assumption; no independent fair-value estimate',
        conditional_on='Normal winner settlement only; tie, void, refund and discretionary outcomes excluded',
        expected_payout=None,expected_profit=None,return_pct=None,break_even_pct=None,status='Unavailable')
    if probability is None:
        result['status']='Assumption needed'
        return result
    if a and b:
        result['expected_payout']=textnum(probability*Decimal(a['gross_payout'])+(1-probability)*Decimal(b['gross_payout']))
        if a['net_cashflow'] is not None and b['net_cashflow'] is not None and leg['cash'] is not None:
            x,y=Decimal(a['net_cashflow']),Decimal(b['net_cashflow']);net=probability*x+(1-probability)*y
            result.update(expected_profit=textnum(net),return_pct=textnum(net/Decimal(leg['cash'])*100),
                          break_even_pct=textnum(-y/(x-y)*100),status='Conditional scenario')
    return result

def evaluate(point, rows, quantity='100', scenario='cent', probability=None, selected='polymarket_us:1315440', identity=None):
    if identity and identity.get('score_reviews'):
        from app.opportunities.score_lines import evaluate as evaluate_lines
        return evaluate_lines(point,rows,quantity,scenario,probability,selected,identity)
    sides=identity['sides'] if identity else SIDES
    teams=identity['teams'] if identity else TEAMS
    candidate_defs=identity['candidates'] if identity else CANDIDATES
    with localcontext(Context(prec=100)):
        q=number(quantity);p=None if probability in (None,'') else number(probability)
        if q<=0 or q!=q.to_integral_value() or q>100000000:raise ValueError('Use a positive whole-contract quantity up to 100,000,000')
        if p is not None and not 0<=p<=1:raise ValueError('Probability must be from 0 to 1')
        if scenario not in ('unknown','cent','direct'):raise ValueError('Unknown fee scenario')
        if selected not in sides:raise ValueError('Unknown selected contract')
        if identity and identity.get('product_identity'):
            assessment=dict(assessed_at=point['at'],observation_cutoff=point['at'],profiles={},sources={},pmus_coefficient=None,note='Retained product metadata; unsupported rules remain unavailable')
            for row in rows:
                try: partial=assess([row],point['at'],identity)
                except (ValueError,KeyError,StopIteration): continue
                assessment['profiles'].update(partial['profiles']);assessment['sources'].update(partial['sources'])
                for key in ('nhl_fee_bases','mlb_fee_bases','nba_fee_bases','ncaaf_fee_bases','ncaab_fee_bases'):
                    if key in partial:assessment.setdefault(key,{}).update(partial[key])
                if partial['pmus_coefficient'] is not None: assessment['pmus_coefficient']=partial['pmus_coefficient']
        else: assessment=assess(rows,point['at'],identity)
        cs=contracts(point,identity)
        legs={k:leg_value(c,assessment,point['at'],q,scenario,identity) for k,c in cs.items()}
        candidates=[]
        for cid,title,keys in candidate_defs:
            ls=[legs[k] for k in keys];raw=total([l['ask'] for l in ls]);notional=total([l['notional'] for l in ls]);cash=total([l['cash'] for l in ls]);fees=total([l['fee'] for l in ls])
            reasons=list(dict.fromkeys(r for l in ls for r in l['reasons']));settlement=None;relation=None
            va,vb=[l['venue'] for l in ls]
            if va in assessment['profiles'] and vb in assessment['profiles']:
                pa,pb=[assessment['profiles'][v] for v in (va,vb)]
                settlement=compare_profiles(pa,pb)
                relation=relationships([sides[keys[0]]],[sides[keys[1]]],pa,pb,teams,settlement)[0]
            receipts=[exact_time(l['received_at']) for l in ls if l['received_at']]
            if len(receipts)==2 and abs(receipts[0]-receipts[1])>Decimal(Policy().max_observation_skew_seconds):reasons.append('Books more than 5 seconds apart at cutoff')
            normal={s:total([None if not l['cashflows'].get(s) else l['cashflows'][s]['net_cashflow'] for l in ls]) for s in ['winner:'+t for t in teams]}
            net=None if any(v is None for v in normal.values()) else min(normal.values())
            status='Conditional scenario' if net is not None else 'Raw price-gap diagnostic'
            candidates.append(dict(id=cid,title=title,legs=ls,status=status,raw_combined_price=textnum(raw),raw_gap=textnum(None if raw is None else 1-raw),
                notional=textnum(notional),fees=textnum(fees),cash=textnum(cash),profit=textnum(net),return_pct=textnum(None if net is None or cash is None else net/cash*100),
                normal_cashflows={k:textnum(v) for k,v in normal.items()},worst_case_all_outcomes=None,settlement=settlement,relationship=relation,
                reasons=reasons,positive_normal_scenario=net is not None and net>0,current_executable=False))
        candidates.sort(key=lambda c:(c['status']!='Conditional scenario',-Decimal(c['profit'] or '-Infinity'),c['id']))
        return dict(cutoff=point['at'],quantity=str(q),scenario=scenario,assessment=assessment,candidates=candidates,
                    ev={**expected(legs[selected],p,q,identity),'leg':legs[selected]},contracts=list(cs.values()),
                    assumptions=('Unknown fee inputs remain unknown.' if scenario=='unknown' else
                        'What-if fees: Kalshi multiplier 1, no event override, '+('0.0001' if scenario=='direct' else '0.01')+' balance precision; US retained 0.06 schedule and no settlement levy. No additional account charges or rebates. One new taker order per leg, one fill per consumed price level; both legs fill. Whole contracts only; no extra slippage beyond depth.'),
                    ranking='Within-class normal-settlement profit at equal quantity. Shared-liquidity alternatives cannot be added. No supported all-outcome net results.')
