"""Isolated authored loopback preview; no ordinary startup/config/worker path."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from aiohttp import web
from app.comparison.coverage import CoverageLedger, SPORTS
from app.dashboard.current_contract import stamp, event_identity, identity, binding_context, quotes_of
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from tests.comparison_fixture import software_fixture
from tests.current_fixture import fixture, InjectedTestProvider
from tests.test_current_state import owner


def preview_fixture():
    raw=software_fixture();event=deepcopy(fixture()['events'][2])
    event['start_at']='2026-10-08T23:00:00+00:00';event['id']=event_identity(event)
    event['groups']=event['groups'][:1]
    for group in event['groups']:
        group['id']=identity('group',[event['id'],*[group[k] for k in
            ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],
            group.get('result_policy','unspecified')])
        for index,outcome in enumerate(group['outcomes']):
            outcome['id']=identity('outcome',[group['id'],outcome['participant'],outcome['predicate'],
                outcome['signed_line'],outcome.get('result_interpretation','normal_win')])
            for venue_index,q in enumerate(quotes_of(outcome)):
                at=(stamp(raw['clock_at'])-timedelta(seconds=(6,45,901,23)[venue_index])).isoformat()
                q['times'].update(source_at=at,received_at=raw['clock_at'],projected_at=raw['clock_at'])
                q['binding']['selection']=binding_context(event,group,outcome)
                q['sharp_reference']=dict(bookmaker='pinnacle',version='pinnacle-proportional-no-vig-1',
                    selection_digest=identity('binding',q['binding']['selection']),odds=['2.10','1.80'],selected=index,
                    source_at=[raw['clock_at'],raw['clock_at']],received_at=raw['clock_at'],sha256='c'*64,
                    maximum_age_seconds=1800,selected_odds=['2.10','1.80'][index])
    raw['events'].append(event)
    return raw


async def main():
    raw=preview_fixture();provider=InjectedTestProvider(raw)
    provider.coverage=CoverageLedger(dict(kalshi=['NFL'],polymarket_us=['NFL'],
        novig=list(SPORTS),prophetx=list(SPORTS),pinnacle=list(SPORTS)))
    provider.coverage.observe('NCAAB','novig',checked_at=raw['clock_at'],status='no_offerings_returned',
        offered=dict(games=0,markets=0,quotes=0))
    provider.coverage.observe('NFL','polymarket_us',checked_at=raw['clock_at'],status='failed_source',
        reason='source_failed')
    app=create_app(owner=owner(),sessions={},current_provider=provider)
    app[CURRENT_KEY].monotonic=lambda:0;app[CURRENT_KEY]._age_origin=0
    runner=web.AppRunner(app);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    print('AUTHORED_PREVIEW_URL=http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]),flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()


if __name__=='__main__':asyncio.run(main())
