"""Offline adapter replay and normalization; JSON output for the next slice."""
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from app.adapters.kalshi import KalshiAdapter, Response as KalshiResponse
from app.adapters.polymarket_us import PolymarketUSAdapter, Response as PMResponse
from app.adapters.prophetx import ProphetXAdapter, Response as PXResponse
from app.models.core import Event, RawPayload, NativeRef, Venue, EvidenceKind
from app.normalization import Registry, enrich_event

ROOT = Path(__file__).resolve().parents[1]
PX_ROOT = ROOT / 'evidence/slice-3/sandbox-qualification-20260912/attempt-1/sandbox-20260912T005720Z'


async def captured_events():
    """Use existing adapter ingestion with local responses and original provenance."""
    pm_root = ROOT / 'evidence/phase-0'
    meta = next(x for x in json.loads((pm_root/'manifest.json').read_text()) if x['file']=='pmus-nfl-events.json')
    pm = PolymarketUSAdapter(max_pages=1, page_size=10)
    async def pm_get(path, params=None):
        assert path == '/v2/leagues/nfl/events'
        return PMResponse((pm_root/meta['file']).read_text(), meta['source_endpoint'],
                          datetime.fromisoformat(meta['retrieved_at_utc']), EvidenceKind.OBSERVATION)
    pm._get = pm_get
    async with pm:
        pm_events = await pm.discover_events()
    px_meta = next(x for x in json.loads((PX_ROOT/'result.json').read_text())['records'] if x['file']=='market-002.json')
    class ReplayClient:
        async def request(self, method, path, **kwargs):
            assert method == 'GET' and path == '/mm/get_sport_events'
            return PXResponse((PX_ROOT/px_meta['file']).read_text(), px_meta['source'],
                              datetime.fromisoformat(px_meta['received_at']), EvidenceKind.OBSERVATION)
    px = ProphetXAdapter(ReplayClient(), tournament_ids=('31',))
    px_events = await px.discover_events()
    kroot = ROOT / 'evidence/slice-4/public-20260912'
    report = json.loads((kroot/'report.json').read_text())
    kalshi = KalshiAdapter(series=('KXNFLGAME',), max_pages=1, page_size=5,
                           now=lambda: datetime.fromisoformat(report['started_at']))
    async def k_get(path, params=None):
        filename = {'/series/KXNFLGAME':'rest-00.json', '/events':'rest-01.json'}[path]
        meta = next(x for x in report['responses'] if x['file']==filename)
        return KalshiResponse((kroot/filename).read_text(), meta['source'], datetime.fromisoformat(meta['received_at']))
    kalshi._get = k_get
    async with kalshi:
        k_events = await kalshi.discover_events()
    return [(e, 'production', 'evidence/phase-0/pmus-nfl-events.json') for e in pm_events] + [
        (e, 'sandbox', str((PX_ROOT/'market-002.json').relative_to(ROOT))) for e in px_events] + [
        (e, 'production', 'evidence/slice-4/public-20260912/rest-01.json') for e in k_events]


def serialize(result, artifact, evidence_class):
    event = result.observation
    return {'evidence_class':evidence_class, 'artifact':artifact,
            'venue':event.raw.ref.venue.value, 'environment':result.environment,
            'native_event_id':event.raw.ref.event_id, 'native_title':event.title,
            'native_league':event.league, 'source':event.raw.source,
            'received_at':event.raw.received_at.isoformat(),
            'raw_sha256':sha256(event.raw.json_text.encode()).hexdigest(),
            'scheduled_start':event.scheduled_start.isoformat() if event.scheduled_start else None,
            'league':asdict(result.league), 'participants':[asdict(p) for p in result.participants],
            'extraction_status':result.extraction_status,
            'extraction_provenance':result.extraction_provenance, 'native_roles':result.native_roles}


async def report():
    registry = Registry.load()
    records = [serialize(enrich_event(e, environment=env, registry=registry), path, 'actual_capture')
               for e, env, path in await captured_events()]
    # Same shared observation contract, explicitly invented data, no Novig wire claim.
    raw = RawPayload(ref=NativeRef(venue=Venue.NOVIG, event_id='synthetic-event'),
        source='synthetic:normalization-edge', received_at=datetime(2026,9,12,tzinfo=timezone.utc),
        json_text='{"id":"synthetic-event","description":"Synthetic away at home","league":"NFL"}',
        kind=EvidenceKind.SYNTHETIC)
    for title, names in [('Synthetic away at home', ()), ('Synthetic named participants', ('Dallas Cowboys','Unknown Club'))]:
        e = Event(raw=raw, title=title, league='NFL', participants=names)
        records.append(serialize(enrich_event(e, environment='qa', registry=registry), None, 'synthetic'))
    coverage = []
    for evidence_class, venue, env in sorted({(x['evidence_class'], x['venue'], x['environment']) for x in records}):
        subset = [x for x in records if (x['evidence_class'],x['venue'],x['environment'])==(evidence_class,venue,env)]
        for league in sorted({x['league']['canonical_id'] or 'unknown' for x in subset}):
            rows = [x for x in subset if (x['league']['canonical_id'] or 'unknown') == league]
            participants = [p for x in rows for p in x['participants']]
            coverage.append({'evidence_class':evidence_class,'venue':venue,'environment':env,'league':league,
                'events':len(rows),'extraction_unknown':sum(x['extraction_status']=='unknown' for x in rows),
                'participant_results':dict(Counter(p['resolution']['status'] for p in participants)),
                'unique_resolved_teams':len({p['resolution']['canonical_id'] for p in participants if p['resolution']['status']=='resolved'})})
    edges = [('shared city', registry.resolve('team','New York',league='NFL')),
             ('cross-league abbreviation',registry.resolve('team','CIN')),
             ('unknown',registry.resolve('team','Unknown Club',league='NFL')),
             ('native/name conflict',registry.resolve('team','Dallas Cowboys',league='NFL',venue='polymarket_us',environment='production',native_id='77')),
             ('unsupported league',registry.resolve('league','NCAAF'))]
    return {'registry_version':registry.version,'registry_sha256':registry.fingerprint,
            'registry_teams':dict(Counter(e['league'] for e in registry.entities.values() if e['kind']=='team')),
            'scope':'Identity enrichment only; no event equivalence, line comparison or settlement approval.',
            'coverage':coverage,'records':records,
            'synthetic_edges':[{'label':label,'result':asdict(r)} for label,r in edges],
            'documentation_examples':[{'evidence_class':'documentation_example','input':name,
                'result':asdict(registry.resolve('team',name,league='MLB'))} for name in ('NY Yankees','Boston Red Sox')],
            'limitations':['Novig: synthetic only; no live capture or native mappings.',
                'MLB: 30 registry teams; no MLB event capture in this replay.',
                'NCAAF/NBA/NHL remain planned, absent from registry.',
                'Historical names not present in these captures are not auto-merged.']}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(report()), indent=2))
