"""Read-only presentation of exact captured inputs; never changes rank or records."""
from collections import defaultdict
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
from app.comparison.display_identity import outcome_key as outcome_key
from .u0_display import quote_display


def decimal(value):
    with localcontext() as ctx:
        ctx.prec = 60
        f = Fraction(value)
        return str(Decimal(f.numerator) / Decimal(f.denominator))


def odds(value, units='decimal_odds', payout='1'):
    display = quote_display(value, units, payout, places=2)
    return dict(american=display.get('american'),
                decimal=display.get('conversion', {}).get('decimal_approx'),
                reason=display.get('reason'))


def presented(row, by_id=None):
    from app.storage.comparison_snapshot import expand_row
    from .product_finance import visible_row
    row = visible_row(expand_row(row))
    out = dict(row)
    original = row.get('original', {})
    display = dict(offered=odds(original.get('value'), original.get('units'), original.get('payout', '1')))
    p = row.get('probability')
    display['fair'] = odds(decimal(1 / Fraction(p))) if p is not None and 0 < Fraction(p) < 1 else None
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    display['benchmark'] = [odds(v) for v in ref.get('odds', [])]
    display['benchmark_venue'] = ref.get('bookmaker')
    display['gross_profit_per_100'] = row.get('gross_return_percent')
    cost = row.get('cost_per_normal_claim')
    display['win_profit_per_100'] = str(100 * (1 / Fraction(cost) - 1)) if cost else None
    display['conservative_profit_per_100'] = row.get('conservative_return_percent')
    display['net_profit_per_100'] = row.get('net_return_percent')
    display['minimum_profit_per_100'] = row.get('minimum_return_percent')
    if row.get('kind') == 'pair':
        display['positions'] = [presented(by_id[i]) for i in row['legs'] if i in (by_id or {})]
    out['display'] = display
    return out


def search_index(result):
    from app.normalization.registry import Registry

    entities = Registry.current().entities
    index = {}
    for game in result.get('games', []):
        terms = [game.get('title', '')]
        for participant in game.get('participants', []):
            identifier = participant.get('id', '')
            terms.extend((str(identifier), str(participant.get('name', ''))))
            team = entities.get(identifier, {})
            if team.get('kind') == 'team' and team.get('league') == game.get('league'):
                terms.append(team['name'])
        index[game['game_key']] = ' '.join(terms).casefold()
    return index


def desk_game_aliases(rows, games, event_facts):
    """Join only exact, unambiguous schedule identities for display."""
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.normalization.college_registry import expanded
    from app.storage.schedule_metadata import witness
    from app.storage.store import stamp

    sources = defaultdict(set)
    events = dict(event_facts or {})
    for row in rows:
        source = row.get('source') or {}
        if source.get('provider') and source.get('native_event_id'):
            key = source['provider'], source['native_event_id']
            sources[row['game_key']].add(key)
            if row.get('_desk_event') is not None:
                events[key] = row['_desk_event']
        else:
            sources[row['game_key']].add(None)

    entities = expanded().entities
    scheduled = defaultdict(list)
    for game_key in sources.keys() & games.keys():
        game = games[game_key]
        league = game.get('league')
        if not league or league == 'MLB' or not game.get('start_at'):
            # A doubleheader needs its reported game number.
            continue
        teams = defaultdict(set)
        for participant in game['participants']:
            if participant.get('id') and participant.get('role') in ('home', 'away'):
                teams[participant['role']].add(participant['id'])
        if len(teams['home']) != 1 or len(teams['away']) != 1:
            continue
        home, away = next(iter(teams['home'])), next(iter(teams['away']))
        if home == away or any(entities.get(team, {}).get('league') != league
                               or entities[team].get('kind') != 'team' for team in (home, away)):
            continue
        scheduled[league, stamp(game['start_at']), home, away].append(game_key)

    resolver = OccurrenceResolver()
    aliases = {}
    for (league, start, home, away), keys in scheduled.items():
        if len(keys) < 2:
            continue
        witnesses = []
        provider_games = defaultdict(set)
        roles = {'home': home, 'away': away}
        for key in {source for game in keys for source in sources[game]}:
            event = events.get(key)
            if (event is None or event.get('schedule_conflict') or event.get('competition') != league
                    or not event.get('participants') or not event.get('scheduled_start')
                    or stamp(event['scheduled_start']) != start
                    or any(event.get(role) != team for role, team in roles.items())):
                break
            provider, native_id = key
            stated_roles = event.get('source_participant_roles')
            if stated_roles is None and provider in ('sportsgameodds', 'oddslink_public_board'):
                # These adapters preserve their explicit home/away fields and
                # bind the schedule to the original provider-event receipt.
                schedule = witness(event)
                if schedule and schedule['authority'] == [provider, 'event', native_id]:
                    stated_roles = roles
            if stated_roles != roles:
                break
            source = dict(provider=provider, native_event_id=native_id, binding_version=None)
            facts = resolver._facts(dict(event=event, quote=dict(source=source, provenance={})))
            if facts['conflict'] or facts['replacement'] or facts['roles'] != roles:
                break
            provider_games[provider].add(facts['source_game'])
            witnesses.append(facts)
        else:
            if (any(len(ids) != 1 for ids in provider_games.values())
                    or any(not resolver._consistent(a, b) for index, a in enumerate(witnesses)
                           for b in witnesses[index + 1:])):
                continue
            canonical = min(keys, key=lambda key: (key.startswith(('native-current:', 'aggregate-current:')), key))
            aliases.update((key, canonical) for key in keys if key != canonical)
    return aliases


def ranking_value(row, metric, *, current=False, qualified=False):
    """Only the declared supported current basis may compete; never fill blanks."""
    value = row.get(metric)
    if value is None:
        return None
    if qualified and row.get('kind') != 'pair':
        from app.storage.comparison_snapshot import expand_row
        from .product_finance import qualified_ev
        if metric != 'conditional_return_percent' or not qualified_ev(expand_row(row)):
            return None
    if metric == 'sportsbook_return_percent':
        return Fraction(value) if row.get('price_current') and row.get('sportsbook_baseline') else None
    if current and row.get('kind') != 'pair':
        if not row.get('price_current') or not row.get('current_authority') or row.get('current_reasons'):
            return None
        status = {'conditional_return_percent': 'after_trade_fee_ev',
                  'conservative_return_percent': 'conservative_trade_fee_ev',
                  'gross_return_percent': 'before_fee_ev', 'net_return_percent': 'assumed_net_ev'}.get(metric)
        state=row.get('metric_status', {}).get(status, {}).get('state', row.get('_metric_states',{}).get(status))
        if status and state != 'available':
            return None
        if metric in ('conditional_return_percent', 'conservative_return_percent'):
            from app.comparison.snapshot_fee_scope import RANKING_BASIS
            key='conditional_trade_benchmark' if metric == 'conditional_return_percent' else 'conservative_trade_benchmark'
            fee = row.get(key)
            available,basis=(fee.get('available'),fee.get('ranking_basis')) if fee is not None else row.get('_fee_bases',{}).get(key,(None,None))
            if not available or basis != RANKING_BASIS:
                return None
    return Fraction(value)


@lru_cache(maxsize=32768)
def outcome_id(key):
    # Bounded cache of semantic IDs only, never prices or current authority.
    from app.storage.store import hashed
    return hashed(key)


def comparison_groups(rows, by_id, metric, *, pairs=False, current=False, individual=False, qualified=False,
                      score_row=None):
    """Group the complete filtered slate before pagination; preserve every quote."""
    groups = {}
    values = {r['id']: score_row(r) if score_row else ranking_value(r, metric, current=current, qualified=qualified)
              for r in rows}
    def rank(r):
        value = values[r['id']]
        return (value is None, -value if value is not None else 0,
                current and not r.get('price_current'),
                r.get('start_at', ''), r['id'], r.get('evidence_result_id', ''))
    for row in rows:
        if pairs:
            keys = [outcome_key(by_id[i]) for i in row['legs'] if i in by_id]
            key = ('pair', tuple(sorted(keys, key=repr))) if len(keys) == 2 else ('unresolved', row['id'])
        else:
            key = ('offer', row['id']) if individual else outcome_key(row)
        groups.setdefault(key, []).append(row)
    result = []
    for key, members in groups.items():
        members = sorted(members, key=rank)
        first = members[0]
        result.append(dict(id=outcome_id(key), kind='pair_group' if pairs else 'outcome_group',
                           game_key=first['game_key'], game_title=first['game_title'],
                           league=first['league'], start_at=first['start_at'],
                           market=first['market'], quotes=members,
                           score=None if values[first['id']] is None else str(values[first['id']]),
                           score_source=None if values[first['id']] is None else dict(
                               id=first['id'], venue=first.get('venue'), source=first.get('source'),
                               evidence_result_id=first.get('evidence_result_id')),
                           outcome_key=list(key),
                           meaning='Display grouping only; each quote retains its own reference and settlement evidence.'))
    return sorted(result, key=lambda g: (g['score'] is None,
        -Fraction(g['score']) if g['score'] is not None else 0,
        current and not g['quotes'][0].get('price_current'), g['start_at'],
        repr(g['outcome_key']), g['quotes'][0]['id']))
