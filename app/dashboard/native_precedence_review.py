"""Review6: explicit evidence priority and narrow shared branches; no historical repair."""
from pathlib import Path
from decimal import Decimal,InvalidOperation
import hashlib,json,re
VERSION='atl-gb-native-review-6'
ROOT=Path(__file__).resolve().parents[2]
TABLE='evidence/b6-native-review-20260923-v6/precedence.json'
TABLE_HASH='11f60039c8bce704957fada0963a736693dbc6ea75f5360f713d20a8d3010383'

def precedence():
    data=(ROOT/TABLE).read_bytes()
    if hashlib.sha256(data).hexdigest()!=TABLE_HASH:raise ValueError('Precedence table mismatch')
    table=json.loads(data)
    for source in table['sources'].values():
        raw=(ROOT/source['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Precedence source mismatch')
    for row in table['rows']:
        for p in row['passages']:
            raw=(ROOT/table['sources'][p['source']]['file']).read_text()
            if re.sub(r'\s+',' ',p['exact_passage']) not in re.sub(r'\s+',' ',raw):raise ValueError('Unsupported quoted passage')
    return table

def shared_suspension(minutes,*,league_final=None,no_scheduled_resumption=None,not_completed_in_time=None,period_complete=None,criterion_definitive=None):
    out=dict(available=False,mode=None,payout=None,applicability='Conditional agreement of retained Kalshi versions only; not cross-venue equivalence; does not establish effective version, fair-price amount or net qualification')
    try:m=Decimal(minutes)
    except (TypeError,InvalidOperation):return out
    flags=(league_final,no_scheduled_resumption,not_completed_in_time,period_complete,criterion_definitive)
    if not m.is_finite() or not 0<=m<60 or m==55 or any(type(x) is not bool for x in flags):return out
    if not no_scheduled_resumption or not not_completed_in_time or period_complete or criterion_definitive:return out
    if m<55 and not league_final:return dict(out,available=True,mode='discretionary fair price; amount unavailable')
    if m>55 and league_final:return dict(out,available=True,mode='official final result; outcome still required')
    return out

def annotate(result):
    result['retained_review'].update(version=VERSION,precedence_review=precedence(),
        closed_historical_gaps=['Original missing state and clock evidence are not recovery targets','C3/C4 age and alignment failures remain attached to original cutoff'],
        note='Review6 distinguishes established native terms, actual differences and unknown priority. New document publication/retrieval is never historical supersession. Independent retained-evidence engineering complete.')
    flags=dict(no_scheduled_resumption=True,not_completed_in_time=True,period_complete=False,criterion_definitive=False)
    result['retained_review']['shared_conditional_branches']={
        'before55_no_final':shared_suspension('54',league_final=False,**flags),
        'after55_league_final':shared_suspension('56',league_final=True,**flags),
        'after55_no_final':shared_suspension('56',league_final=False,**flags),
        'exact55':shared_suspension('55',league_final=False,**flags)}
    return result
