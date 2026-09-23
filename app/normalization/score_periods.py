"""Owner-selected baseball segments and hockey periods; explicit retained contracts."""
PERIODS={'MLB':{'first_3':(1,3),'first_5':(1,5),'first_6':(1,6),'regulation_9':(1,9)},'NHL':{'period_1':(1,1),'period_2':(2,2),'period_3':(3,3)}}
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections','settlement_fee','shortened_game','abandonment','forfeit','venue_change','resumed_game','tie','refund'}

def scope(i):return i.get('period') in PERIODS.get(i.get('competition'),{}) and i.get('family') in ('moneyline','spread','total')

def completion(i):return i['period']+'_definitively_completed'

def validate_descriptor(e,d):
    i=dict(d,competition=e['competition'])
    if not scope(i):raise ValueError('Unsupported sport scoring segment')
    start,end=PERIODS[e['competition']][d['period']]
    expected=dict(offered='pregame',overtime='excluded',overtime_format='not_applicable',regulation=d['period'],segment_start=start,segment_end=end,normal_completion=completion(i),settlement_score=d['period']+'_only',tied_score='evaluate_actual_score_predicate')
    if e['competition']=='MLB':expected.update(extra_innings='excluded',pitcher_conditions='action',completion_scope='specified_segment_only')
    if any(d.get(k)!=v for k,v in expected.items()):raise ValueError('Missing explicit segment boundaries, completion, excluded later scoring or action condition')
    if not isinstance(d.get('contract_document'),str) or not d['contract_document'].startswith('https://'):raise ValueError('Reviewed source contract document required')
    if d['family']=='moneyline':
        from app.normalization.first_half import validate_payout
        validate_payout(d)

def validate_result(p):
    i=p['target']['market_identity'];start,end=PERIODS[i['competition']][i['period']]
    expected=dict(score_scope=i['period']+'_only',score_representation='official_segment_score',completion=completion(i),segment_start=start,segment_end=end)
    if any(p.get(k)!=v for k,v in expected.items()):return 'Missing explicit completed segment score; no cumulative subtraction or later scoring'
    if i['competition']=='MLB' and p.get('pitcher_conditions')!='action':return 'Unknown segment pitcher conditions'
    return None
