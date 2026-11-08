"""Browse frozen and synthetic odds without a live source or SQL write."""
import asyncio
from functools import lru_cache

from aiohttp import web

from app.storage import odds_replay, comparison_snapshot as snapshots
from .local_security import PublicRequestError
from .snapshot_api import page_options
from .trade_desk import page


@lru_cache(maxsize=2)
def board(path, identity):
    with odds_replay.open_archive(path) as db:
        return snapshots.unpack(db.execute("SELECT payload FROM archive WHERE kind='board'").fetchone()[0])


def load(query, *, details=False):
    dataset = query.get('dataset', 'frozen')
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
        from app.comparison.inspection_math import offer_disclosures
        terms = offer_disclosures(value['row'], value['captured_at'], value.get('originals', []), value.get('assumptions'))
        return dict(value, inspection=dict(value['inspection'], **terms))
    out = page(result, query, page_options(query), captured_pairs=result['pairs'],
               policy=result['publication']['policy'])
    out.update(replay=result['replay'], archive_counts=result['counts'])
    return out


def mount(app):
    async def read(req):
        return web.json_response(await asyncio.to_thread(load, dict(req.query), details=req.path.endswith('/details')))

    app.router.add_get('/api/odds-replay', read)
    app.router.add_get('/api/odds-replay/details', read)
