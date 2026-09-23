"""Review5: dated series history and conflicting contract versions, not qualification."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import hashlib,json
VERSION='atl-gb-native-review-5'
ROOT=Path(__file__).resolve().parents[2]/'evidence/b6-public-research-repair-20260923/acquisition'
HASHES={'01-response.bin':'d89ea1b11d8ec7290111eeb6f3878864ff0ea790185d619b4e6f89b6359fc2cc','02-response.bin':'705007d99a8b49a98350e0592ab70c297c4131f58df282f5a5f4144217e6268e','03-response.bin':'8ea02e068a64812adfe344b151d6173ad8038b1973de184e7b802552f757ab02','04-response.bin':'6f993d4b893de1dd351ca4eac3413123364ca5a3b47c2013a9eea37227f727f4','requests.json':'e076bfab6255a687aadedacebb67610bb75a44c71796d3fea30693cd72cf04fe','result.json':'bdf278c31dd74687f158bdf629d29172e56377aff3592fc53161d777ba13ea03','consumed.json':'75f62aa87e63862e0262dbdc1b97c66ac28319968572f484114f76d42c4b02f2'}

def series_at(history,at):
    """Select explicit native effective entry; refuse missing or conflicting baseline."""
    when=datetime.fromisoformat(at.replace('Z','+00:00'))
    if when.utcoffset() is None or history.get('cursor') or history.get('next_cursor'):return None
    rows=history.get('series_fee_change_arr',[])
    if not rows:return None
    eligible=[]
    for row in rows:
        if row.get('series_ticker')!='KXNFLGAME':return None
        t=datetime.fromisoformat(row['scheduled_ts'].replace('Z','+00:00'))
        if t.utcoffset() is None:return None
        if t<=when:eligible.append((t,row))
    if not eligible:return None
    latest=max(t for t,r in eligible);selected=[r for t,r in eligible if t==latest]
    if len({(r.get('fee_type'),str(r.get('fee_multiplier'))) for r in selected})!=1:return None
    row=selected[0]
    if row.get('fee_type')!='quadratic_with_maker_fees' or str(row.get('fee_multiplier'))!='1':return None
    return dict(fee_type=row['fee_type'],fee_multiplier='1',effective_from=row['scheduled_ts'],source_record_id=row['id'],
        limitation='Effective metadata entry only; not a fee formula/rounding/settlement schedule or proof of every contract amendment')

def suspension_modes(minutes,*,league_final=None,not_resumed=None):
    """Narrow full-game post55 pre-regulation-end scenario; never assign payouts."""
    m=Decimal(minutes)
    if not m.is_finite() or not 55<m<60 or not_resumed is not True or type(league_final) is not bool:
        return dict(available=False,filing=None,current_terms=None,payout=None)
    return dict(available=True,filing='official final result' if league_final else 'discretionary fair price',
        current_terms='official final result' if league_final else 'result at suspension',payout=None,
        applicability='Conditional text comparison only. Exact contract effective version and review precedence unresolved.')

def facts():
    for name,h in HASHES.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:raise ValueError('Filing review evidence mismatch: '+name)
    return dict(hashes=HASHES,acquisition='b6-public-research-repair-20260923',requests=5,http200=4,settlement_page='Timed out before headers; no response body; no retry',
        series_history=series_at(json.loads((ROOT/'03-response.bin').read_text()),'2026-09-23T15:09:37.623609+00:00'),
        filing_date='2026-02-18',initial_listing='after close of business February18 per filing',
        filing_scope='FOOTBALLGAMEWIN original filing linked by native KXNFLGAME series metadata',
        fee_precedence='Filing invokes Rule3.13 and says fees may be revised on exchange website; does not supply exact schedule',
        contract_version_conflict=dict(filing_pages=[8,9],current_terms_page=2,scenario='Full-game suspension after55 but before60 minutes, no resumption in required timeframe, no league final',
          comparison=suspension_modes('56',league_final=False,not_resumed=True),
          other_difference='Original before55 text has no scheduled resumption/completion; current version adds48h and definitively satisfied/unsatisfied criterion exceptions',
          resolution='Dated amendment/effective-version and precedence evidence needed for Sep23 contract; neither document automatically overrides the other'),
        us_rule_structure='General undated guide locates alternative settlements in resolution criteria and says unlisted sources have no effect. Its cancellation50-50 example is not a rule for779756.',
        historical_contract_version_qualified=False,fees_fully_qualified=False)

def annotate(result):
    from .native_acquisition_review import HISTORICAL_FEE_GAP
    f=facts();result['retained_review'].update(version=VERSION,filing_review=f,
        note='Review5 resolves explicit Kalshi series fee metadata effective entry; exact schedule still unqualified. February filing conflicts with current suspension rules, so version history is material. Reviews1–4 remain exact.')
    replacement='Kalshi January1 series fee metadata established; fee schedule continuity, rounding precedence and private charges remain unavailable'
    for c in result['candidates']:
        c['reasons']=[replacement if x==HISTORICAL_FEE_GAP else x for x in c['reasons']]
        c['reasons'].append('Kalshi dated filing and current suspension rules differ; effective contract version unresolved')
        for leg in c['legs']:leg['reasons']=[replacement if x==HISTORICAL_FEE_GAP else x for x in leg['reasons']]
    return result
