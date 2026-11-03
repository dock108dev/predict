from copy import deepcopy
from unittest.mock import patch
from app.collection.native_role_binding import attach_kalshi,kalshi_participant
from app.collection.normalization_trace import refusal


def catalog():
    event=dict(id='game',competition='NCAAF',identity='unresolved',participants={'Alpha':None,'Beta':None},
        observed_identity_facts=[dict(main_game_event_ticker='game',home_team_id='a',away_team_id='b')])
    markets=[dict(id=i,event_id='game',market_type='moneyline',period='full_game',_native=dict(
        strike_type='structured',yes_sub_title=label,custom_strike={'football_team':i},
        rules_primary=f'If {label} wins the game, then the market resolves to Yes.')) for i,label in [('a','Alpha'),('b','Beta')]]
    return dict(events=[event],markets=markets)


def resolve(team,league,source):
    return {'Alpha':'team:a','Beta':'team:b','Other':'team:other'}.get(team['name'])


def test_role_witness_recovery_and_withdrawal():
    c=catalog()
    with patch('app.collection.native_role_binding.resolve_team',side_effect=resolve):
        assert attach_kalshi(c)=={'game'}
        e=c['events'][0]
        assert (e['home'],e['away'])==('team:a','team:b')
        assert kalshi_participant(e,'a','Alpha')=='team:a'
        assert kalshi_participant(e,'a','Beta') is None
        assert attach_kalshi(c)==set()
        c['markets'].pop()
        assert attach_kalshi(c)=={'game'}
        assert 'native_role_evidence' not in e and 'home' not in e


def test_roles_reject_conflicting_ids_labels_events_and_prior_identity():
    with patch('app.collection.native_role_binding.resolve_team',side_effect=resolve):
        for mutate in (
            lambda c:c['markets'][1]['_native']['custom_strike'].update(football_team='a'),
            lambda c:c['markets'][1].update(event_id='other-game'),
            lambda c:c['markets'][1]['_native'].update(yes_sub_title='Other'),
            lambda c:c['events'][0].update(participants={'Alpha':'team:other','Beta':None}),
        ):
            c=catalog();mutate(c)
            assert attach_kalshi(c)==set()
            assert 'native_role_evidence' not in c['events'][0]


def test_refusal_never_copies_unrecognized_exception_text():
    c=catalog();r=refusal(ValueError('Authorization: secret'),c['events'][0],c['markets'][0],{},None,'kalshi')
    assert r['reason_code']=='normalization_exception_ValueError'
    assert 'secret' not in str(r)
    assert r['event_id']=='game' and r['stage']=='normalized'
