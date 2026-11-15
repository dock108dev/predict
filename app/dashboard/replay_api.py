"""Browse frozen and synthetic odds without a live source or SQL write."""
import asyncio
from functools import lru_cache
import re

from aiohttp import web

from app.storage import odds_replay, comparison_snapshot as snapshots
from app.storage.store import connect, stamp
from .local_security import PublicRequestError
from .product_finance import retained_novig_fee, visible_assumptions, visible_row
from .snapshot_api import page_options, pregame_capture, retained_pregame
from .trade_desk import page


@lru_cache(maxsize=2)
def board(path, identity):
    with odds_replay.open_archive(path) as db:
        result = snapshots.unpack(db.execute("SELECT payload FROM archive WHERE kind='board'").fetchone()[0])
    result['rows'] = [archive_offer(row, result['captured_at']) for row in result['rows']
                      if row['venue'] != 'pinnacle']
    result['assumptions'] = visible_assumptions(result['assumptions'])
    from app.storage.ordinary_projection import counts
    counts(result)
    return result


def archive_offer(row, captured_at):
    fee = retained_novig_fee(row, captured_at)
    if fee:
        row = dict(row, trade_fee=fee)
    return visible_row(row)


def archive_detail(value, result_id):
    from app.comparison.inspection_math import offer_disclosures, offer_math

    at = value['captured_at']
    row = archive_offer(value['row'], at)
    terms = offer_disclosures(row, at, value.get('originals', []), value.get('assumptions'))
    return dict(result_id=result_id, row=row, captured_at=at, provider_requests=0,
                assumptions=visible_assumptions(value.get('assumptions') or {}),
                inspection=dict(offer_math(row), **terms))


def retained_capture(db, result_id, game_key):
    """An exact ordinary publication member, limited to its captured game."""
    if not re.fullmatch(r'[0-9a-f]{32}', result_id or '') or not game_key or len(game_key) > 128:
        return None
    saved = db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s AND automatic AND read_summary IS NOT NULL',
                       (result_id,)).fetchone()
    if not saved:
        return None
    result = snapshots.unpack(saved['result'], lazy=True)
    if (result.get('publication') or {}).get('schema') != 'ordinary-comparison-1' or result.get('component_slices'):
        return None
    rows = [r for r in result['rows'] if r['game_key'] == game_key and r['venue'] != 'pinnacle']
    if not rows:
        return None
    return dict(result, rows=rows, games=[g for g in result['games'] if g['game_key'] == game_key])


def retained_game(query, *, details=False, allow_live=False):
    result_id, game_key = query.get('result_id'), query.get('game_key')
    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        result = retained_capture(db, result_id, game_key)
        if result and not allow_live:
            result = retained_pregame(result)
        if not result:
            if details:
                raise PublicRequestError('Game capture expired')
            return dict(state='initializing', rows=[], total=0, provider_requests=0)
        at = result['captured_at']
        rows = []
        for saved in result['rows']:
            if details and saved['id'] != query.get('id'):
                continue
            row = snapshots.expand_row(saved)
            authority = row['current_authority']['price']
            reasons, deadline = authority.get('reasons', []), authority.get('current_until')
            row = dict(row, price_current=bool(deadline and not reasons and stamp(at) <= stamp(deadline)),
                       current_reasons=reasons, game_state=authority.get('lifecycle', {}).get('state', 'unknown'),
                       evidence_result_id=result_id, captured_at=at)
            rows.append(row)
        if details:
            if not rows:
                raise PublicRequestError('Offer unavailable in this game capture')
            row, = rows
            stored = db.execute('SELECT inputs FROM comparison_snapshot WHERE id=%s', (result['snapshot_id'],)).fetchone()
            originals = [q for q in snapshots.unpack(stored['inputs']).get('quotes', []) if q['id'] == row['id']] if stored else []
            return archive_detail(dict(row=row, captured_at=at, originals=originals,
                                       assumptions=result['assumptions']), result_id)
    replay = dict(dataset='retained', id=result_id, captured_at=at, synthetic=False)
    result = dict(result, rows=[archive_offer(row, at) for row in rows], replay=replay,
                  assumptions=visible_assumptions(result['assumptions']))
    query = dict(query, phase='', browse_odds='1', last_known='1', view='odds')
    out = page(result, query, page_options(query), policy=result['publication']['policy'])
    return dict(out, replay=replay)


def load(query, *, details=False, allow_live=False):
    if not allow_live:
        query = {key: value for key, value in query.items() if key != 'phase'}
    dataset = query.get('dataset', 'frozen')
    if dataset == 'retained':
        return retained_game(query, details=details, allow_live=allow_live)
    if dataset == 'practice':
        from .replay_practice import practice
        result, proofs = practice(query.get('frame', 'initial'))
    elif dataset in odds_replay.DATASETS:
        path = odds_replay.DIRECTORY / f'{dataset}.sqlite3'
        try:
            info = path.stat()
        except FileNotFoundError:
            if details:
                raise PublicRequestError('Replay archive is unavailable') from None
            return dict(state='initializing', replay=dict(dataset=dataset), rows=[], total=0, provider_requests=0)
        result = board(path, (info.st_ino, info.st_mtime_ns))
    else:
        raise PublicRequestError('Unknown replay dataset')
    if details:
        if result['id'] != query.get('result_id'):
            raise PublicRequestError('Replay revision changed. Refresh the list.')
        if dataset == 'practice':
            value = proofs.get(query.get('id'))
        else:
            with odds_replay.open_archive(path) as db:
                row = db.execute('SELECT payload FROM detail WHERE id=?', (query.get('id'),)).fetchone()
                value = snapshots.unpack(row[0]) if row else None
        if not value or value['result_id'] != result['id']:
            raise PublicRequestError('Offer unavailable in this replay revision')
        if not allow_live and not pregame_capture(value['row'], value['captured_at']):
            raise PublicRequestError('Offer unavailable in this replay revision')
        return archive_detail(value, result['id'])
    if not allow_live:
        result = retained_pregame(result)
        from app.storage.ordinary_projection import counts
        result = dict(result)
        counts(result)
    out = page(result, query, page_options(query), captured_pairs=result['pairs'],
               policy=result['publication']['policy'])
    out.update(replay=result['replay'], archive_counts=result['counts'])
    return out


def mount(app):
    async def read(req):
        def work():
            from app.collection.current_policy import live_enabled
            from app.collection.runtime_status import read_runtime
            # Practice is always an isolated, pregame fixture with no SQL dependency.
            allow_live = False
            if req.query.get('dataset', 'frozen') != 'practice':
                with connect() as db:
                    allow_live = live_enabled(read_runtime(db, ordinary_authority=True)['config'])
            return load(dict(req.query), details=req.path.endswith('/details'), allow_live=allow_live)

        return web.json_response(await asyncio.to_thread(work))

    app.router.add_get('/api/odds-replay', read)
    app.router.add_get('/api/odds-replay/details', read)
