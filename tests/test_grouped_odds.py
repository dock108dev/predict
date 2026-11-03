from app.dashboard.grouped_odds import group_prices


def quote(id,venue='kalshi',key=None):
    return dict(quote_id=id,venue=venue,market=dict(market='spread',period='full_game',line='6.5'),
        selection=dict(participant='home',predicate='cover',signed_line='-6.5'),
        same_outcome=dict(supported=key is not None,key=key,reason=None if key else 'comparison_equality_missing'))


def test_exact_identity_groups_preserve_all_originals_and_unqualified_disposition():
    a=quote('a',key=['occurrence-1','-6.5']);b=quote('b','novig',a['same_outcome']['key'])
    c=quote('c',key=['occurrence-1','-7']);d=quote('d');e=quote('e','prophetx')
    other=quote('other',key=['occurrence-2','-6.5'])
    value=group_prices([a,b,c,d,e,other]);assert value['observations']==6
    assert len(value['rows'])==4
    unqualified=next(r for r in value['rows'] if not r['comparable'])
    assert unqualified['cells']=={'kalshi':['d'],'prophetx':['e']}
    assert unqualified['reason_codes']==['comparison_equality_missing']
    ids=[id for row in value['rows'] for cell in row['cells'].values() for id in cell]
    assert sorted(ids)==['a','b','c','d','e','other']
    assert value==group_prices([other,e,d,c,b,a])


def test_grid_wire_preserves_full_browser_freshness_contract():
    from copy import deepcopy
    from app.dashboard.grouped_odds import grid_wire
    status=dict(state='last_known',read_at='2026-10-31T00:00:00Z',
        current_until=None,source_age_seconds=90,received_age_seconds=80,
        reason_codes=['source_old'],source_reason_codes=['source_old'],publication_reason_codes=[])
    q=quote('a');q.update(observation_display=deepcopy(status),event={'large':'evidence'})
    board=grid_wire(dict(prices=[q]))
    assert board['prices'][0]['observation_display']==status
    assert 'event' not in board['prices'][0]
