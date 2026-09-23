"""Bound saved-page research only. No collection, manual assumptions or scores."""
from functools import lru_cache
from pathlib import Path
import json
from decimal import Decimal
from app.reference.public_page import parse, timestamp
from app.reference.research_loop import page_arithmetic
from app.reference.page_estimate import ROOT, estimate, binding_matches

SESSION = '5c9b7dca-a813-4d77-80f5-0691d06068eb'
MANIFEST = ROOT/'evidence/multi-page-research/assessments.json'


def source_for_game(raw, metadata, event_id, game):
    page = parse(raw, metadata, event_id=event_id)
    names = {s['team'] for s in page['sides']}
    codes = {s['team']: 'NFL:'+s['abbreviation'] for s in page['sides']}
    if names != set(game['teams']) or codes != game['sources']['polymarket_us']['participant_mapping']:
        raise ValueError('Saved page participants do not match this game')
    if timestamp(page['scheduled_start']) != timestamp(game['scheduled_start']):
        raise ValueError('Saved page schedule does not match this game')
    return page_arithmetic(page)


@lru_cache(maxsize=1)
def saved_comparisons():
    from app.dashboard.multi_game import OUTPUT, saved_rows, project_game, default_point
    from app.opportunities.board import assess, contracts
    saved = saved_rows(OUTPUT/SESSION)
    games = next(r['games'] for r in saved['rows'] if r['type']=='multi_game_selection')
    manifest = json.loads(MANIFEST.read_text())
    raw = (ROOT/'evidence/public-nfl-reference/vegasinsider.html').read_bytes()
    metadata = json.loads((ROOT/'evidence/public-nfl-reference/capture.json').read_text())
    entries = {}
    for game in games:
        matches = [a for a in manifest if a['binding']['game_id']==game['id']]
        if len(matches)!=1:
            entries[game['id']] = dict(comparison=None, reason='Missing or ambiguous saved event binding')
            continue
        a = matches[0]
        try:
            source = source_for_game(raw, metadata, a['binding']['source_event_id'], game)
        except ValueError as exc:
            entries[game['id']] = dict(comparison=None, reason=str(exc))
            continue
        timeline, rows = project_game(saved['rows'], game)
        point = default_point(timeline)
        c = dict(source_result=source, target_identity=game,
                 target_contract=contracts(point, game)['kalshi:yes'],
                 target_fee_assessment=assess(rows, point['at'], game),
                 reference_retrieved_at=source['page']['retrieved_at'],
                 target_cutoff=point['at'])
        c['target_received_at'] = c['target_contract']['received_at']
        # The source probability survives unsupported terms, but net does not.
        if not binding_matches(c, a, game) or a['binding']['session'] != SESSION:
            entries[game['id']] = dict(comparison=None, source=source,
                                      reason='Saved ordinary-winner assessment does not bind this target')
            continue
        entries[game['id']] = dict(comparison=c, assessment=a, cutoff_id=point['id'])
    return entries


def research_row(session, game, quantity, scenario, common, *, live=False):
    entry = saved_comparisons().get(game['id']) if session==SESSION and not live else None
    reason = 'No bound saved page for this capture; research is retrospective only'
    e = None
    if entry:
        reason = entry.get('reason')
        if entry.get('comparison'):
            e = estimate(entry['comparison'], entry['assessment'], game, quantity, scenario)
    p = None
    if entry and entry.get('source'):
        p = next(s['probability'] for s in entry['source']['page']['sides'] if s['team']==game['sides']['kalshi:yes']['participant'])
    return dict(**common, id=game['id']+'~page', candidate='', contract='kalshi:yes',
                target_team=game['sides']['kalshi:yes']['participant'],
                probability=e['probability'] if e else p,
                profit=e['expected_profit'] if e else None, return_pct=e['return_pct'] if e else None,
                requested_quantity=str(quantity), available_size=e['leg']['visible_size'] if e else None,
                legs=[e['leg']] if e else [], research=e,
                assumption=('Conditional ordinary winner · exceptional outcomes unknown' if e and e['expected_profit'] is not None
                            else ' · '.join(e['reasons']) if e and e['reasons'] else reason or 'Conditional EV unavailable'),
                usable=bool(e and e['expected_profit'] is not None),
                source=entry.get('source') if entry else None)


def rank_research(rows, sort='roi', search=''):
    from app.dashboard.query_policy import validate_choice
    validate_choice('sort', sort)
    field = 'return_pct' if sort=='roi' else 'profit'
    return sorted((r for r in rows if search.casefold() in r['game_title'].casefold()),
                  key=lambda r:(r[field] is None, Decimal(r[field]).copy_negate() if r[field] is not None else Decimal(0),r['id']))
