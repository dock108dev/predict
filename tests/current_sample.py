"""Authored synthetic input catalog for current-contract tests; no server routes."""
from datetime import datetime, timedelta, timezone
from app.dashboard.u0_display import VERSION, quote_display

VENUES = ['kalshi', 'polymarket_us', 'novig', 'prophetx']


def sample_payload(revision=1):
    """Every native ID and cross-source binding here is fictional and prefixed syn:."""
    now = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    events = []
    descriptions = [
        ('nfl-1','NFL','american_football','Buffalo Bills','Baltimore Ravens'),
        ('ncaaf-1','NCAAF','american_football','University of Louisiana at Lafayette Ragin’ Cajuns','University of Southern Mississippi Golden Eagles'),
        ('nhl-1','NHL','ice_hockey','New York Islanders','Toronto Maple Leafs'),
        ('nba-1','NBA','basketball','Boston Celtics','New York Knicks'),
    ]
    for index, (eid, league, sport, away, home) in enumerate(descriptions):
        event = dict(id='syn:'+eid, sport=sport, league=league, season='2026' if league in ('NFL','NCAAF') else '2026-2027',
                     stage='regular_season', participants=[dict(id='syn:'+eid+':away',name=away,role='away'),dict(id='syn:'+eid+':home',name=home,role='home')],
                     event_discriminator='syn:scheduled-fixture-'+eid, title=away+' at '+home, start_at=(now+timedelta(hours=index+1)).isoformat(), groups=[])
        for period in ['full_game'] + (['first_half'] if league in ('NFL','NCAAF','NBA') else ['period_1']):
            for market, line in [('winner',None),('spread','-3.5'),('spread','-4.5'),('total','47.5')]:
                if league=='NHL' and market!='winner':continue
                group_id = ':'.join([event['id'],period,market,str(line)])
                group = dict(id=group_id, market=market, period=period, period_boundary='full_game_including_overtime' if period=='full_game' else 'selected_period_only', outcome_cardinality=2, line=line, anchor_participant=event['participants'][0]['id'] if market=='spread' else None, outcomes=[])
                for side in (0,1):
                    label = ('Over ' if side==0 else 'Under ')+line if market=='total' else event['participants'][side]['name']+(' '+(line if side==0 else '+'+line[1:]) if market=='spread' else ' to win')
                    oid=group_id+':'+str(side)
                    outcome=dict(id=oid, participant=None if market=='total' else event['participants'][side]['id'], predicate=('over' if side==0 else 'under') if market=='total' else 'cover' if market=='spread' else 'win', signed_line=(line if side==0 else '+'+line[1:]) if market=='spread' else line, label=label, quotes={})
                    for vi, venue in enumerate(VENUES):
                        # Controlled tie at .5 and 2.0; negative scenario at .52.
                        v=(['0.48','0.5','2.05','2.0'] if side==0 else ['0.52','0.5','2.0','2.0'])[vi]
                        if revision == 2 and vi == 0: v = '0.47' if side == 0 else '0.53'
                        units='usd_per_contract' if vi<2 else 'decimal_odds'
                        qid=oid+':'+venue
                        age=[8,19,7200,10800][vi]
                        source_at=(now-timedelta(seconds=age)).isoformat()
                        outcome['quotes'][venue]=dict(id=qid, revision=revision if vi == 0 else 1, venue=venue,
                            source=dict(provider=venue if vi<2 else 'the_odds_api', native_event_id=event['id']+':'+venue,
                                        native_market_id=group_id+':'+venue, native_outcome_id=oid+':'+venue, native_side='yes' if vi<2 else ('over' if side==0 else 'under') if market=='total' else outcome['participant'], binding_id='syn:explicit-binding-1',binding_version='syn:bindings-1',native_line=line,quote_side='buy'),
                            original=dict(value=v,units=units,payout='1',payout_units='USD',quantity_units='contracts' if vi<2 else 'unknown',role='comparison'),
                            display=quote_display(v,units), times=dict(source_at=source_at,received_at=(now-timedelta(seconds=age-1)).isoformat(),projected_at=now.isoformat(),source_time_kind='synthetic'),
                            state='available', age_seconds=age, stale=False, rule_note=('Overtime included' if period=='full_game' else 'Selected period only; no overtime')+('; cancellation treatment differs' if venue=='polymarket_us' else '; exceptional settlement unverified'),
                            comparison=dict(eligible=True,reasons=[]),
                            calculations=dict(arbitrage=dict(eligible=False,reason='Settlement, costs and depth are not established'),ev=dict(eligible=False,reason='No supported probability model'),sizing=dict(eligible=False,reason='Executable depth and quantity rules unknown')),
                            provenance=dict(mode='synthetic',fixture='u0-board-1',real_source=False))
                    group['outcomes'].append(outcome)
                event['groups'].append(group)
        events.append(event)
    return dict(schema=VERSION,mode='synthetic',runtime_id='syn:runtime-1',state_revision=revision,projected_at=now.isoformat(),clock_at=now.isoformat(),
                state='available',source_status={v:dict(state='available',next_due_at=None) for v in VENUES},events=events,
                selection_policy=dict(ttl_seconds=300,maximum_per_client=1,restart_expires=True), admin_href='/admin')

