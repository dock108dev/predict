"""Exact scoring witnesses over authored SportsGameOdds NHL event objects."""

from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from app.collection.sgo_nhl_scoring import BASIS, nhl_scoring
from app.collection import sgo_game_results
from app.collection.sportsgameodds_adapter import parse_page


START = '2026-11-26T00:00:00.000Z'
TEAM_IDS = {'home': 'NYI_NHL', 'away': 'STL_NHL'}


def scores(home, away):
    return {'home': home, 'away': away}


def event(display, *, regulation=((0, 0), (1, 1), (1, 1)), overtime=None, shootout=None, final=(3, 2)):
    periods = ['1p', '2p', '3p', 'game', 'reg']
    values = dict(zip(periods, (*regulation, final, tuple(map(sum, zip(*regulation)))), strict=True))
    if overtime is not None:
        periods.append('ot')
        values['ot'] = overtime
    if shootout is not None:
        periods.append('so')
        values['so'] = shootout
    return dict(eventID='nhl-event', leagueID='NHL',
                status=dict(started=True, completed=True, cancelled=False, ended=True, live=False,
                            finalized=False, displayShort=display, startsAt=START,
                            periods=dict(started=list(periods), ended=list(periods))),
                teams={role: dict(teamID=TEAM_IDS[role], score=score)
                       for role, score in scores(*final).items()},
                results={period: {role: dict(points=score) for role, score in scores(*pair).items()}
                         for period, pair in values.items()})


def verify(raw, *, final=(3, 2), **kwargs):
    arguments = dict(event_id='nhl-event', starts_at='2026-11-25T19:00:00-05:00',
                     team_ids=TEAM_IDS, final_scores=scores(*final))
    return nhl_scoring(raw, **dict(arguments, **kwargs))


@pytest.mark.parametrize('raw, decision, regulation, overtime, attempts', [
    (event('F', regulation=((1, 0), (1, 1), (1, 1))), 'regulation', (3, 2), (0, 0), None),
    (event('F (OT)', overtime=(1, 0)), 'overtime', (2, 2), (1, 0), None),
    (event('F (SO)', overtime=(0, 0), shootout=(2, 1)), 'shootout', (2, 2), (0, 0), (2, 1)),
])
def test_exact_final_score_keeps_regulation_overtime_and_shootout_distinct(raw, decision, regulation, overtime, attempts):
    assert verify(raw) == dict(decision=decision, basis=BASIS, scores=scores(3, 2),
                               regulation_scores=scores(*regulation), overtime_scores=scores(*overtime),
                               shootout_attempt_scores=scores(*attempts) if attempts is not None else None)


def test_away_shootout_winner_only_adds_one_to_its_score():
    result = verify(event('F (SO)', overtime=(0, 0), shootout=(0, 1), final=(2, 3)), final=(2, 3))
    assert result['scores'] == scores(2, 3)
    assert result['shootout_attempt_scores'] == scores(0, 1)


@pytest.mark.parametrize('changes', [
    {'event_id': 'different-game'},
    {'starts_at': '2026-11-26T00:00:00.000001Z'},
    {'team_ids': {'home': TEAM_IDS['away'], 'away': TEAM_IDS['home']}},
    {'final_scores': scores(2, 3)},
    {'final_scores': scores(True, 2)},
])
def test_retained_occurrence_roles_and_final_score_must_agree(changes):
    assert verify(event('F (SO)', overtime=(0, 0), shootout=(2, 1)), **changes) is None


@pytest.mark.parametrize('mutate', [
    lambda raw: raw.update(leagueID='NBA'),
    lambda raw: raw.update(results=[]),
    lambda raw: raw['status'].update(completed=False),
    lambda raw: raw['status'].update(live=True),
    lambda raw: raw['status'].update(suspended=True),
    lambda raw: raw['status'].update(cancelled=True),
    lambda raw: raw['status'].update(displayShort='F (OT)'),
    lambda raw: raw['status']['periods']['ended'].remove('3p'),
    lambda raw: raw['status']['periods']['started'].append('so'),
    lambda raw: raw['teams']['home'].update(score=4),
    lambda raw: raw['results']['3p']['away'].pop('points'),
    lambda raw: raw['results']['3p']['away'].update(points=0),
    lambda raw: raw['results']['reg']['away'].update(points=1),
    lambda raw: raw['results']['ot']['home'].update(points=1),
    lambda raw: raw['results']['so']['home'].update(points=1),
    lambda raw: raw['results']['so']['away'].update(points=3),
])
def test_absent_and_conflicting_provider_facts_are_inconclusive(mutate):
    raw = event('F (SO)', overtime=(0, 0), shootout=(2, 1))
    mutate(raw)
    assert verify(raw) is None


def test_source_and_retained_final_cannot_both_count_every_shootout_conversion():
    raw = event('F (SO)', overtime=(0, 0), shootout=(2, 1), final=(4, 2))
    assert verify(raw, final=(4, 2)) is None
    corrected = deepcopy(raw)
    corrected['results']['game']['home']['points'] = 3
    corrected['teams']['home']['score'] = 3
    assert verify(corrected)['scores'] == scores(3, 2)


def test_adapter_projects_only_a_verified_proof_and_an_accepted_final_carries_it():
    raw = event('F (SO)', overtime=(0, 0), shootout=(2, 1))
    raw['teams']['home']['names'] = {'long': 'New York Islanders'}
    raw['teams']['away']['names'] = {'long': 'St. Louis Blues'}
    received = '2026-11-26T04:00:00Z'

    def parse():
        return parse_page(json.dumps({'success': True, 'data': [raw]}).encode(), received)

    page = parse()
    proof = verify(raw)
    assert page.events[0]['nhl_scoring'] == proof
    [item] = sgo_game_results.observations(page, known_at=received)
    assert item['final'] and item['nhl_scoring'] == proof
    assert item['receipt_sha256'] == page.receipt_sha256

    accepted_event = sgo_game_results.event_record

    def swapped_roles(*args, **kwargs):
        projected = accepted_event(*args, **kwargs)
        return dict(projected, home=projected['away'], away=projected['home'])

    with patch.object(sgo_game_results, 'event_record', side_effect=swapped_roles):
        [disputed] = sgo_game_results.observations(page, known_at=received)
    assert not disputed['final'] and 'nhl_scoring' not in disputed

    del raw['results']['so']
    page = parse()
    assert 'nhl_scoring' not in page.events[0]
    [unproven] = sgo_game_results.observations(page, known_at=received)
    assert unproven['final'] and 'nhl_scoring' not in unproven
