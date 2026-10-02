"""Small synthetic saved packages for CI; no retained acquisition is copied.

Use the real normalizer, binder and journal writer in a disposable directory.
The separate archive tests still verify the owner's original records locally.
"""
import atexit
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from app.dashboard.session_projection import stable
from app.reference.aggregate import bind
from app.reference.aggregate_import import _write_batches
from app.reference.odds_bindings import normalize_event

AT = '2026-09-29T12:00:00Z'
BOOKS = ('novig', 'prophetx', 'pinnacle', 'draftkings', 'betmgm')


def records(sport='NFL', half=False):
    home, away = 'SYNTHETIC HOME', 'SYNTHETIC AWAY'
    event = dict(id='SYNTHETIC-' + sport, sport_key={
        'NFL': 'americanfootball_nfl', 'NCAAF': 'americanfootball_ncaaf'
    }[sport], home_team=home, away_team=away,
        commence_time='2026-10-02T00:00:00Z', bookmakers=[])
    for book in BOOKS:
        markets = []
        for family in ('h2h', 'spreads', 'totals'):
            # H1 exercises two venue cards and all three reference families.
            if half and book in BOOKS[:2] and family != 'h2h':
                continue
            names = ('Over', 'Under') if family == 'totals' else (home, away)
            outcomes = []
            for i, name in enumerate(names):
                outcome = dict(name=name, price='2.5' if book == 'novig' else '2.0',
                               sid='SYNTHETIC-' + book + '-' + family + '-' + str(i))
                if family != 'h2h':
                    outcome['point'] = (3.5 if i == 0 else -3.5) if family == 'spreads' else 47.5
                outcomes.append(outcome)
            markets.append(dict(key=family + ('_h1' if half else ''),
                                last_update=AT, outcomes=outcomes))
        event['bookmakers'].append(dict(key=book, last_update=AT, markets=markets))
    result = normalize_event(json.dumps(event).encode(), sport, AT)
    for row in result:
        row['evidence_mode'] = 'synthetic-fixture'
    return result


@lru_cache(maxsize=1)
def packages():
    temporary = tempfile.TemporaryDirectory(prefix='predict-synthetic-aggregate-')
    atexit.register(temporary.cleanup)
    root = Path(temporary.name)
    batches = []
    for sport in ('NFL', 'NCAAF'):
        raw = records(sport)
        if sport == 'NFL':
            # A bad reference quote must not suppress unrelated raw cards.
            raw[-1]['decimal_odds'] = '1'
        batches.append(dict(sport=sport, at=AT, records=bind(raw),
                            response_sha256=raw[0]['receipt_sha256']))
    full = _write_batches(batches, root / 'full')
    raw = records(half=True)
    half = _write_batches([dict(sport='NFL', at=AT, records=bind(raw),
                               response_sha256=raw[0]['receipt_sha256'])],
                          root / 'evidence/source-bindings-20260929/sessions')

    # Deliberately fictional source bytes exercise hashing and exact bindings.
    # They are never installed in app/fixtures or used by ordinary app processes.
    sources = []
    for name in ('novig-nfl-winner', 'prophetx-nfl-mainline'):
        relative = Path('evidence/synthetic-rules') / (name + '.txt')
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('SYNTHETIC TEST SOURCE: ' + name + '\n')
        digest = sha256(path.read_bytes()).hexdigest()
        sources.append(dict(id=name, title='Synthetic test source',
                            url='https://fixture.invalid/' + name,
                            retained_path=str(relative), text_path=str(relative),
                            sha256=digest, text_sha256=digest))
    bindings = [dict(record_sha256=stable(r), book=r['bookmaker'],
                     book_market_id=None, native_contract_verified=False,
                     contemporaneous_native_observation=False, rule_binding_verified=False)
                for r in raw if r['bookmaker'] in BOOKS[:2]]
    assessment = dict(version='aggregate-h1-rules-20260929-v1', reviewed_at=AT,
                      response_sha256=raw[0]['receipt_sha256'], sources=sources,
                      books={b: [dict(topic='scope', summary='Synthetic test only'),
                                 dict(topic='fees', summary='Synthetic fees unknown')]
                             for b in BOOKS[:2]},
                      bindings=bindings, summary='Synthetic rule-analysis test only',
                      blockers=['Synthetic listing has no native rule binding',
                                'ProphetX first-half tie disposition unknown in this synthetic test'],
                      native_lookup={})
    data = root / 'synthetic-assessment.json'
    data.write_text(json.dumps(assessment))
    return dict(root=root, full=full, half=half, data=data,
                data_sha256=sha256(data.read_bytes()).hexdigest())


FOLDER = packages()['full']
