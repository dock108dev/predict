"""Versioned fee arithmetic; all monetary outputs are USD decimal strings.

Inputs are JSON-shaped, explicit scenarios. Complete ordered fill histories are
required: no inferred accumulator state, account facts, native stake conversion,
or cross-venue settlement qualification. Registry snapshots travel with audits.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, Context, localcontext, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
import hashlib
import json
from importlib.resources import files
from app.models.core import parse_decimal

D = parse_decimal
ZERO = Decimal('0')
ONE = Decimal('1')
ENGINE = 'fees-1'


def stamp(s):
    t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.utcoffset() is None:
        raise ValueError('time must have timezone')
    return t


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def number(value):
    n = D(value)
    if len(n.as_tuple().digits) > 24 or abs(n.as_tuple().exponent) > 12:
        raise ValueError('numeric input exceeds supported 24 digits / 12 decimal places')
    return n


def rounded(x, grid, mode):
    return (x / grid).to_integral_value(rounding=mode) * grid


class Registry:
    def __init__(self, data):
        self.data = deepcopy(data)
        if self.data.get('schema')!=1: raise ValueError('unsupported registry schema')
        rows = self.data['schedules']
        if len({r['version'] for r in rows}) != len(rows):
            raise ValueError('duplicate schedule version')
        for r in rows:
            if r['effective_from']:
                a = stamp(r['effective_from'])
                if r['effective_to'] and stamp(r['effective_to']) <= a:
                    raise ValueError('empty schedule interval')
            for other in rows:
                if r is other or (r['venue'],r['product']) != (other['venue'],other['product']):
                    continue
                if r['effective_from'] and other['effective_from']:
                    if ((not r['effective_to'] or stamp(other['effective_from']) < stamp(r['effective_to']))
                        and (not other['effective_to'] or stamp(r['effective_from']) < stamp(other['effective_to']))):
                        raise ValueError('overlapping schedules')

    def select(self, venue, product, when, version=None):
        t = stamp(when)
        if version is None and any(r['venue']==venue and r['product']==product and r['effective_from'] is None for r in self.data['schedules']):
            raise ValueError('unknown effective schedule could apply; explicit version required')
        rows = [r for r in self.data['schedules'] if r['venue']==venue and r['product']==product
                and (version is None or r['version']==version)
                and (r['effective_from'] is not None or version is not None)
                and (not r['effective_from'] or stamp(r['effective_from']) <= t)
                and (not r['effective_to'] or t < stamp(r['effective_to']))]
        if len(rows)!=1:
            raise ValueError('unknown or ambiguous applicable schedule; pin an evidenced version if effective time is unknown')
        return deepcopy(rows[0])


def load_registry():
    return Registry(json.loads(files('app.fixtures').joinpath('fee-schedules-v1.json').read_text()))


def kalshi_terms(c, when):
    """Resolve series then event, independently clearing each nullable override."""
    meta = c.get('kalshi_metadata')
    if not meta or not meta.get('source') or meta.get('series_id') != c.get('series_id') or meta.get('event_id') != c.get('event_id'):
        raise ValueError('scoped Kalshi series and event fee metadata required')
    def latest(rows):
        eligible = []
        seen = set()
        for r in rows:
            if r.get('series_ticker',c['series_id'])!=c['series_id'] or r.get('event_ticker',c['event_id'])!=c['event_id']:
                raise ValueError('fee change native scope mismatch')
            t = stamp(r['scheduled_ts'])
            if t in seen:
                raise ValueError('ambiguous fee changes at same instant')
            seen.add(t)
            if t <= stamp(when):
                eligible.append((t,r))
        return max(eligible,key=lambda x:x[0])[1] if eligible else None
    base = latest(meta.get('series_changes', []))
    if base is None:
        raise ValueError('no historical series baseline at trade time')
    result = {'fee_type':base['fee_type'], 'fee_multiplier':base['fee_multiplier']}
    event = latest(meta.get('event_changes', []))
    if event:
        for k in result:
            if event[k+'_override'] is not None:
                result[k] = event[k+'_override']
    return result


def calculate(context, registry=None):
    # Canonical serialization rejects Decimal/float wire ambiguities below; copy
    # isolates audit output from later caller mutation.
    c = deepcopy(context)
    def reject_float(x):
        if isinstance(x,float): raise ValueError('use decimal strings, never float')
        if isinstance(x,dict):
            for v in x.values(): reject_float(v)
        if isinstance(x,list):
            for v in x: reject_float(v)
    reject_float(c)
    canonical(c)
    with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN)):
        return _calculate(c, registry or load_registry())


def _calculate(c, registry):
    for key in ('venue','environment','market_id','product','trade_time','calculation_time'):
        if not isinstance(c.get(key),str) or not c[key].strip(): raise ValueError('required context: '+key)
    stamp(c['calculation_time']); stamp(c['trade_time'])
    result = dict(scope='hypothetical venue trading fees; excludes unverified account-specific charges', engine=('fees-1-refunds-1' if 'refund_outcomes' in c else ENGINE), context=c, context_hash=digest(c), currency='USD',
                  registry=deepcopy(registry.data), registry_hash=digest(registry.data),
                  schedule=None, schedule_hash=None, schedule_applicability='unverified',
                  formula_support='unselected', rounding_qualification='unverified', entry_notional=None, entry_fees=None,
                  entry_cash_requirement=None, credits=[], outcomes={}, trace=[],
                  assumptions=[], unsupported=[], qualification='unsupported',
                  fill_reconciliation='unverified', settlement_status=c.get('settlement_status','UNKNOWN'))
    issues = result['unsupported']; assumptions = result['assumptions']
    try:
        s = registry.select(c['venue'],c['product'],c['trade_time'],c.get('schedule_version'))
    except ValueError as e:
        issues.append(str(e)); return result
    result['schedule']=s; result['schedule_hash']=digest(s)
    result['formula_support']='implemented_requires_context'
    result['schedule_applicability']='conditional'
    result['rounding_qualification']='documented' if c['venue']!='prophetx' else 'unverified'
    if not s['effective_from']: assumptions.append('schedule effective time unknown; explicitly pinned documentation scenario')
    if c['environment']!='production': assumptions.append('production schedule applied hypothetically to '+c['environment'])
    evidence = c.get('applicability_evidence')
    if not evidence: assumptions.append('native market applicability not independently established')
    elif s['effective_from']: result['schedule_applicability']='documented_schedule_with_caller_applicability_evidence'
    if c.get('action','buy')!='buy':
        issues.append('only acquisition scenarios supported; closing sales require inventory/collateral context'); return result
    venue = c['venue']; fills=c.get('fills',[])
    if venue!='prophetx' and (not fills or c.get('complete_order_history') is not True):
        issues.append('complete ordered fill history required, including earlier maker/taker fills'); return result
    if len(fills)>10000: raise ValueError('at most 10000 fills')
    seen=set(); parsed=[]; order_times={}
    for f in fills:
        for k in ('fill_id','order_id','role'):
            if not isinstance(f.get(k),str) or not f[k]: raise ValueError('fill requires '+k)
        if f['fill_id'] in seen: raise ValueError('duplicate fill ID')
        seen.add(f['fill_id'])
        if f.get('market_id',c['market_id'])!=c['market_id']: raise ValueError('fill belongs to another market')
        fill_time=f.get('trade_time',c['trade_time'])
        if f['order_id'] in order_times and stamp(fill_time)<order_times[f['order_id']]: raise ValueError('fills must be chronological within order')
        order_times[f['order_id']]=stamp(fill_time)
        if stamp(fill_time)>stamp(c['trade_time']): raise ValueError('fill time exceeds scenario trade time')
        try: fill_schedule=registry.select(c['venue'],c['product'],fill_time,c.get('schedule_version'))
        except ValueError as e:
            issues.append('earlier fill: '+str(e)); return result
        if fill_schedule!=s:
            issues.append('order crosses schedule versions; mixed-version order replay unsupported'); return result
        if f['role'] not in ('maker','taker'): raise ValueError('unknown liquidity role')
        p=number(f['price']); q=number(f['quantity'])
        if not ZERO<p<ONE or q<=ZERO: raise ValueError('price must be between 0 and 1, quantity positive')
        unit=f.get('unit')
        if unit=='payout_cents' and venue=='novig':
            if q!=q.to_integral_value(): raise ValueError('payout cents must be integral')
            q=q/Decimal('100')
        elif unit!='contracts': raise ValueError('unknown quantity convention; no automatic native conversion')
        if venue=='polymarket_us' and not D('.01')<=p<=D('.99'):
            issues.append('PMUS documented price range .01 through .99'); return result
        if venue=='polymarket_us' and q!=q.to_integral_value():
            issues.append('PMUS retail documentation only supports whole contracts; fractional execution applicability unsupported'); return result
        parsed.append((f,p,q))
    cost=sum((p*q for _,p,q in parsed),ZERO); quantity=sum((q for _,_,q in parsed),ZERO)
    fee=ZERO; credits=ZERO; states={}
    if venue=='kalshi':
        try: terms=kalshi_terms(c,c['trade_time'])
        except (ValueError, KeyError) as e: issues.append('fee metadata: '+str(e)); return result
        result['resolved_terms']=terms
        if not c['kalshi_metadata'].get('event_history_complete'): assumptions.append('event override history incomplete')
        mult=number(terms['fee_multiplier'])
        if mult<ZERO: raise ValueError('negative multiplier')
        maker={'quadratic':ZERO,'quadratic_with_maker_fees':D('.25'),'quadratic_with_combo_maker_fees':D('.5')}.get(terms['fee_type'])
        if maker is None: issues.append('unsupported Kalshi fee type '+terms['fee_type']); return result
        grid=c.get('balance_precision')
        if grid not in ('0.01','0.0001'):
            issues.append('explicit account balance_precision 0.01 or 0.0001 required'); return result
        grid=D(grid)
        assumptions.append('supplied account precision; FCM/additional account charges excluded and unverified')
        for f,p,q in parsed:
            if p*q != rounded(p*q,D('.000001'),ROUND_FLOOR):
                issues.append('Kalshi revenue finer than documented six decimals'); return result
            try: fill_terms=kalshi_terms(c,f.get('trade_time',c['trade_time']))
            except (ValueError, KeyError) as e: issues.append('fee metadata: '+str(e)); return result
            fill_mult=number(fill_terms['fee_multiplier'])
            fill_maker={'quadratic':ZERO,'quadratic_with_maker_fees':D('.25'),'quadratic_with_combo_maker_fees':D('.5')}.get(fill_terms['fee_type'])
            if fill_mult<ZERO: raise ValueError('negative multiplier')
            if fill_maker is None: issues.append('unsupported earlier fill fee type'); return result
            raw=D(s['coefficient'])*fill_mult*p*(ONE-p)*q*(fill_maker if f['role']=='maker' else ONE)
            trade=rounded(raw,D('.000001'),ROUND_CEILING)
            change=-p*q-trade; rounding=change-rounded(change,grid,ROUND_FLOOR)
            acc=states.get(f['order_id'],ZERO)+rounding
            rebate=min(rounded(acc,grid,ROUND_FLOOR),rounded(trade+rounding,grid,ROUND_FLOOR))
            states[f['order_id']]=acc-rebate
            fee+=trade+rounding; credits+=rebate
            result['trace'].append(dict(fill_id=f['fill_id'],terms=fill_terms,raw=str(raw),trade_fee=str(trade),rounding_fee=str(rounding),rounding_refund=str(rebate),accumulator=str(acc-rebate)))
        result['credits'].append(dict(kind='order_rounding_refund',amount=str(credits),timing='fill',conditional=False))
    elif venue=='polymarket_us':
        for f,p,q in parsed:
            raw=D(s['maker_coefficient'] if f['role']=='maker' else s['coefficient'])*q*p*(ONE-p)
            amount=rounded(raw,D('.01'),ROUND_HALF_EVEN)
            if f['role']=='maker':
                credits+=amount
            else:
                exact,paid=states.get(f['order_id'],(ZERO,ZERO)); exact+=raw
                amount=min(amount,max(ZERO,rounded(exact,D('.01'),ROUND_HALF_EVEN)-paid))
                states[f['order_id']]=(exact,paid+amount); fee+=amount
            result['trace'].append(dict(fill_id=f['fill_id'],raw=str(raw),amount=str(amount),role=f['role'],order_state=None if f['role']=='maker' else [str(x) for x in states[f['order_id']]]))
        result['credits'].append(dict(kind='maker_rebate',amount=str(credits),timing='fill',conditional=False))
        tier=c.get('taker_rebate_rate')
        if tier is not None:
            if tier not in ('0','0.10','0.25','0.50'): raise ValueError('unsupported rebate tier')
            assumptions.append('supplied prior-month/accelerated rebate eligibility; later payout rounding unverified')
        result['credits'].append(dict(kind='volume_rebate',unrounded=None if tier is None else str(fee*D(tier)),amount=None,timing='weekly',conditional=True))
    elif venue=='novig':
        if c['product']=='parlay':
            if c.get('channel')=='api' and any(f['role']=='taker' for f,_,_ in parsed):
                issues.append('Novig API cannot take parlays'); return result
            if c.get('channel')!='api' and (c.get('channel') not in ('app','web') or c.get('price_basis')!='pre_fee'):
                issues.append('app parlay fee embedded in quote; explicit pre_fee price basis required'); return result
        coefficient=D(s['coefficient'])
        if c['product']=='futures' and c.get('sport') in ('golf','tennis'):
            if stamp(c['trade_time']).date().isoformat()<'2026-09-10':
                issues.append('golf/tennis exemption not established before September 10'); return result
            coefficient=ZERO
            assumptions.append('help-page golf/tennis futures exemption; effective instant not documented')
        policy=c.get('aggregation')
        if len(parsed)>1 and coefficient and any(f['role']=='taker' for f,_,_ in parsed):
            if policy not in ('per_fill','match_vwap'):
                result['rounding_qualification']='unresolved_aggregation'
                issues.append('Novig sources conflict: supply per_fill or match_vwap scenario'); return result
            assumptions.append('Novig aggregation conflict; supplied '+policy+' scenario')
            result['rounding_qualification']='conditional_aggregation'
        groups={}
        for f,p,q in parsed:
            key=f['fill_id']
            if policy=='match_vwap':
                if not f.get('match_id'): raise ValueError('match_vwap needs match_id')
                key=(f['order_id'],f['match_id'],f['role'])
            groups.setdefault(key,[]).append((f,p,q))
        for group in groups.values():
            q=sum((x[2] for x in group),ZERO); stake=sum((x[1]*x[2] for x in group),ZERO); p=stake/q
            raw=coefficient*p*(ONE-p)*q if group[0][0]['role']=='taker' else ZERO
            amount=rounded(raw,D('.00001'),ROUND_HALF_UP); fee+=amount
            result['trace'].append(dict(fill_ids=[x[0]['fill_id'] for x in group],contracts=str(q),vwap=str(p),raw=str(raw),amount=str(amount)))
        if any(f['role']=='maker' for f,_,_ in parsed) and coefficient:
            rate=D('.70') if c['product']=='futures' and c.get('sport') in ('nfl','ncaaf') else D('.50')
            eligible=c.get('maker_credit_eligible') is True and (c['product']=='live' or (c['product']=='futures' and c.get('sport') in ('nfl','ncaaf')))
            collected=c.get('counterparty_fee_retained')
            value=None if not eligible or collected is None else number(collected)*rate
            if value is not None and value<ZERO: raise ValueError('negative retained fee')
            result['credits'].append(dict(kind='maker_credit',unrounded=None if value is None else str(value),amount=None,timing='cash within seven days, reversible',conditional=True))
    elif venue=='prophetx':
        if fills:
            issues.append('ProphetX native quantity/value conversion unavailable; use explicit market stake/payout'); return result
        market=c.get('market_cashflows')
        if not market or market.get('market_id')!=c['market_id']:
            issues.append('scoped market_cashflows with stake_usd and gross_payouts required'); return result
        cost=number(market['stake_usd'])
        if cost<ZERO: raise ValueError('negative stake')
        if market.get('complete_market') is not True: assumptions.append('standalone scenario assumes no other market gains/losses')
        assumptions.append('net gain modeled from explicit aggregate cashflows; detailed venue netting and settlement rounding unverified')
        monthly=c.get('monthly_rebate_context')
        unrounded=None
        if monthly:
            volume=number(monthly['make_volume_usd']); paid=number(monthly['fees_paid_usd'])
            if volume<ZERO or paid<ZERO: raise ValueError('negative monthly totals')
            remaining=volume; weighted=ZERO
            for width,rate in [('50000','0'),('700000','.2'),('2250000','.4'),('4500000','.6')]:
                chunk=min(remaining,D(width)); weighted+=chunk*D(rate); remaining-=chunk
            weighted+=remaining*D('.8')
            unrounded=str(ZERO if volume==ZERO else weighted*paid/volume)
            assumptions.append('supplied full monthly make volume and fees; program eligibility and published example truncation unverified')
        result['credits'].append(dict(kind='maker_volume_program',unrounded=unrounded,amount=None,timing='month end; eligibility required',conditional=True))
    else:
        issues.append('unsupported venue'); return result
    result['entry_notional']=str(cost); result['entry_fees']=str(fee)
    # Keep all credits separate; only Kalshi rounding refund restores entry balance.
    result['entry_cash_requirement']=str(cost+fee-(credits if venue=='kalshi' else ZERO))
    result['entry_balance_debit']=str(cost+fee-(credits if venue in ('kalshi','polymarket_us') else ZERO))
    payouts=deepcopy(c.get('outcomes',{}))
    refunds=c.get('refund_outcomes',[])
    if not isinstance(refunds,list) or any(not isinstance(x,str) or not x for x in refunds) or len(set(refunds))!=len(refunds):
        raise ValueError('refund_outcomes requires unique outcome names')
    if refunds and (venue=='prophetx' or set(refunds)&set(payouts)):
        raise ValueError('refund outcomes must be distinct acquisition outcomes')
    payouts.update({name:'0' for name in refunds})
    if venue=='prophetx': payouts=c['market_cashflows']['gross_payouts']
    for name,value in payouts.items():
        gross=number(value)
        if venue!='prophetx':
            if not ZERO<=gross<=ONE: raise ValueError('outcomes must be payout fractions per $1 contract')
            gross=cost if name in refunds else gross*quantity
        if gross<ZERO: raise ValueError('negative gross payout')
        raw=ZERO; settlement=ZERO
        if venue=='prophetx':
            raw=max(ZERO,gross-cost)*D(s['coefficient'])
            settlement=ZERO if raw==ZERO else None
            if raw and c.get('settlement_rounding'):
                rule=c['settlement_rounding']
                if rule not in ('cent_half_even','cent_half_up'): raise ValueError('unsupported scenario rounding')
                settlement=rounded(raw,D('.01'),ROUND_HALF_EVEN if rule=='cent_half_even' else ROUND_HALF_UP)
                assumptions.append('hypothetical ProphetX '+rule+' settlement rounding')
        elif venue=='polymarket_us' and not c.get('assume_no_settlement_fee',False):
            raw=None; settlement=None
        elif venue=='polymarket_us': assumptions.append('assumed no independent settlement fee; not established by trading schedule')
        result['outcomes'][name]=dict(gross_payout=str(gross),settlement_fee_unrounded=None if raw is None else str(raw),settlement_fee=None if settlement is None else str(settlement),net_payout=None if settlement is None else str(gross-settlement),net_cashflow=None if settlement is None else str(gross-settlement-D(result['entry_balance_debit'])))
    if any(v['settlement_fee'] is None for v in result['outcomes'].values()): assumptions.append('net payout unavailable where settlement charge is unresolved')
    result['assumptions']=list(dict.fromkeys(assumptions))
    result['qualification']='conditional' if assumptions else 'documented_scenario'
    result['formula_support']='implemented'
    return result


def replay(audit):
    if audit['engine'] not in (ENGINE,'fees-1-refunds-1') or digest(audit['context'])!=audit['context_hash'] or digest(audit['registry'])!=audit['registry_hash']:
        raise ValueError('audit identity mismatch')
    rebuilt=calculate(audit['context'],Registry(audit['registry']))
    if rebuilt!=audit: raise ValueError('audit result mismatch')
    return rebuilt
