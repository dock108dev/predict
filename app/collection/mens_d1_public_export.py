"""Import dated CollegeBasketballData public exporter observations without network access."""
import argparse
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from app.collection.current_storage_policy import SQL_BYTE_CAP, require_disk_space, sql_usage
from app.collection.mens_d1_source import MAX_FIRECRAWL_RESPONSE_BYTES, SourceReceipt, _row
from app.normalization.mens_d1_membership import load_membership
from app.research import records
from app.storage import mens_d1_coverage as coverage
from app.storage.store import ROOT, connect, encoded, hashed, stamp

SOURCE = coverage.PUBLIC_SOURCE
URL = 'https://www.collegebasketballdata.com/exporter/games'
TERMS = 'https://www.collegebasketballdata.com/terms'
ACQUISITION = 'official_public_exporter_displayed_rows'
PARSER_VERSION = 'college-basketball-data-public-exporter-1'
CORROBORATION_VERSION = coverage.OFFICIAL_CORROBORATION_VERSION
STATUS = dict(scheduled='scheduled', in_progress='incomplete', final='final',
              postponed='postponed', cancelled='cancelled')
GAME_FIELDS = {'Id', 'SourceId', 'Season', 'StartDate', 'StartTimeTbd', 'NeutralSite', 'Status', 'Venue'}
TEAM_FIELDS = ('TeamId', 'Team', 'Conference', 'Points', 'PeriodPoints')
REQUIRED_FIELDS = GAME_FIELDS | {side + key for side in ('Home', 'Away') for key in TEAM_FIELDS}

# These bindings use this publisher's exact native ID, display name and
# conference. The canonical institution must also appear in that season's
# NCAA men's D1 membership evidence. A bare ambiguous name remains unresolved.
D1 = {
    ('9', 'App State', 'Sun Belt'): 'NCAA27',
    ('46', 'Charleston', 'CAA'): 'NCAA1014',
    ('56', 'Colorado', 'Big 12'): 'NCAA157',
    ('75', 'East Tennessee State', 'SoCon'): 'NCAA198',
    ('77', 'Eastern Illinois', 'OVC'): 'NCAA201',
    ('84', 'Fairleigh Dickinson', 'NEC'): 'NCAA222',
    ('137', 'La Salle', 'A-10'): 'NCAA340',
    ('152', 'Loyola Maryland', 'Patriot'): 'NCAA369',
    ('168', 'Miami', 'ACC'): 'MIAFL',
    ('227', 'Pennsylvania', 'Ivy'): 'NCAA540',
    ('260', 'San José State', 'Mountain West'): 'NCAA630',
    ('262', 'Seattle U', 'WCC'): 'NCAA1356',
    ('279', "St. John's", 'Big East'): 'NCAA603',
    ('281', 'Stanford', 'ACC'): 'NCAA674',
    ('316', 'UL Monroe', 'Sun Belt'): 'NCAA498',
    ('362', 'Queens University', 'ASUN'): 'NCAA11504',
}
NCCAA = 'https://thenccaa.org/sports/2017/6/14/Member_Schools_17-18.aspx?id=660'
UNITED_EAST = 'https://gounitedeast.com/standings.aspx?path=mbball'
FRONTIER = 'https://fcsports.org/news/2026/10/16/2026-27-frontier-conference-mens-basketball-media-day-presented-by-ima-financial.aspx'
NON_D1 = {
    ('510', 'Notre Dame (Md)', ''): ('NCAA Division III', UNITED_EAST),
    ('537', 'Louisiana Christian', ''): ('NAIA', 'https://www.lcwildcats.net/sports/2020/8/17/louisiana-college-quick-facts'),
    ('539', 'Arkansas Baptist', ''): ('NAIA', 'https://abcbuffaloes.com/news/2026/3/2/general-arkansas-baptist-mbb-captures-2026-cac-mens-basketball-championship.aspx'),
    ('586', 'Carolina Christian College', ''): ('NCCAA', NCCAA),
    ('617', 'Fredonia State', ''): ('NCAA Division III', 'https://fredoniabluedevils.com/sports/2023/7/21/fredquently-asked-questions.aspx'),
    ('639', 'Dickinson State (ND)', ''): ('NAIA', FRONTIER),
    ('646', 'Carolina University', ''): ('NCCAA', NCCAA),
    ('697', 'Mansfield', ''): ('NCAA Division II', 'https://gomounties.com/sports/2017/10/10/athletic-branding-and-logos.aspx'),
    ('704', 'Vermont State - Randolph', ''): ('USCAA', None),
    ('707', 'Kentucky State', ''): ('NCAA Division II', 'https://ksuthorobreds.com/news/2026/3/5/mens-basketball-kentucky-state-begins-search-for-new-mens-basketball-coach.aspx'),
    ('742', 'Arlington Baptist', ''): ('NCCAA', NCCAA),
    ('768', 'Wisconsin-Stout', ''): ('NCAA Division III', 'https://www.wisconsin.edu/about/offices/wiac/'),
    ('831', 'Spalding', ''): ('NCAA Division III', 'https://spaldingathletics.com/sports/2020/8/13/conference-information'),
    ('842', 'Carroll (MT)', ''): ('NAIA', FRONTIER),
    ('862', 'Penn State (Brandywine)', ''): ('NCAA Division III', UNITED_EAST),
    ('1017', 'Indiana-South Bend', ''): ('NAIA', 'https://iuia.iu.edu/doc/compliance/ipeds/inst-characteristics/IUSB_2024_IPEDS%20Data%20Collection%20System.pdf'),
    ('1526', 'RIT', ''): ('NCAA Division III', 'https://ritathletics.com/news/2026/11/5/mens-basketball-six-things-you-need-to-know-about-the-2026-27-mens-basketball-team.aspx'),
}


def _boolean(value):
    if value not in ('true', 'false'):
        raise ValueError('cbbd_invalid_boolean')
    return value == 'true'


def _team(row, side, final, *, allow_incomplete_periods=False):
    native, name, conference, score, period_scores = (row[side + key] for key in TEAM_FIELDS)
    if not native.isdigit() or not name or len(name) > 160:
        raise ValueError('cbbd_invalid_team')
    periods = json.loads(period_scores) if final and period_scores else None
    points = int(score) if final and score.isdigit() else None
    if periods is not None and (not isinstance(periods, list) or not 2 <= len(periods) <= 20
            or any(type(value) is not int or value < 0 for value in periods) or sum(periods) != points):
        if not allow_incomplete_periods:
            raise ValueError('cbbd_invalid_period_scores')
        periods = None
    return dict(source_team_id=native, name=name, source_conference=conference,
                display_role=side.lower(), score=points, period_scores=periods)


def _review_membership(team, membership):
    lookup = team['source_team_id'], team['name'], team['source_conference']
    if membership.season != '2026-2027':
        return
    evidence = team['membership']
    if identity := D1.get(lookup):
        evidence = membership.lookup(team['source_team_id'], team['name'], canonical_id='NCAAB:M:D1:' + identity)
        evidence['source_native_binding'] = dict(source=SOURCE, id=lookup[0], name=lookup[1], conference=lookup[2])
    elif tied := NON_D1.get(lookup):
        classification, membership_source = tied
        if membership_source is None:
            evidence = membership.lookup(team['source_team_id'], 'Vermont State University Randolph')
            evidence = dict(evidence, source_alias='Vermont State - Randolph')
        elif evidence['division'] == 'unknown':
            evidence = dict(evidence, division='non_d1', classification=classification, sources=[membership_source],
                            reason='participant_not_ncaa_division_i', source_team_id=lookup[0], matched_label=lookup[1],
                            binding='reviewed_source_id_and_name')
    elif team['name'] == 'TBD':
        evidence = membership.unresolved('source_participant_tbd')
    team.update(membership=evidence, canonical_id=evidence.get('canonical_id'))


def _game(row, day, receipt, *, gender_evidence='CollegeBasketballData men’s college basketball games exporter',
          allow_provisional_final=False):
    native, upstream = row['Id'], row['SourceId']
    if not native.isdigit() or not upstream or len(upstream) > 128 or row['Status'] not in STATUS:
        raise ValueError('cbbd_invalid_game_identity_or_status')
    start, tbd = stamp(row['StartDate']), _boolean(row['StartTimeTbd'])
    status = STATUS[row['Status']]
    teams = [_team(row, side, status == 'final', allow_incomplete_periods=allow_provisional_final)
             for side in ('Away', 'Home')]
    if teams[0]['source_team_id'] == teams[1]['source_team_id']:
        raise ValueError('cbbd_duplicate_participants')
    detail_reason = None
    if status == 'final' and (any(team['score'] is None for team in teams) or teams[0]['score'] == teams[1]['score']):
        if not allow_provisional_final:
            raise ValueError('cbbd_invalid_final_scores')
        status, detail_reason = 'incomplete', 'source_final_score_unavailable'
    membership = load_membership(day)
    counts = {len(team['period_scores']) for team in teams if team['period_scores'] is not None}
    overtime = next(iter(counts)) - 2 if len(counts) == 1 and all(team['period_scores'] for team in teams) else None
    game = _row(receipt, day, 'men', teams, membership, source_time=row['StartDate'], source_timezone='UTC',
                scheduled_start=None if tbd else coverage.clock(start), site=row['Venue'] or None,
                neutral_site=_boolean(row['NeutralSite']), status=status, native_game_id=native,
                gender_evidence=gender_evidence, overtime_periods=overtime, detail_reason=detail_reason)
    for team in teams:
        _review_membership(team, membership)
    divisions = {team['membership']['division'] for team in teams}
    state, reason = ('excluded', 'participant_not_ncaa_division_i') if 'non_d1' in divisions else (
        ('eligible', None) if divisions == {'d1'} and coverage._pair(teams, 'canonical_id') else
        ('unresolved', 'participant_membership_or_identity_unverified'))
    return dict(game, source_game_id=f'cbbd:{native}', upstream_game_id=upstream, source_time_tbd=tbd,
                membership_status=state, membership_reason=reason)


def _exclude_placeholder_duplicates(rows):
    confirmed = Counter(coverage._pair(row['teams'], 'canonical_id') for row in rows
                        if not row['source_time_tbd'] and row['membership_status'] == 'eligible'
                        and row['status'] not in ('cancelled', 'postponed'))
    for row in rows:
        pair = coverage._pair(row['teams'], 'canonical_id')
        if row['source_time_tbd'] and pair and confirmed[pair] == 1 and row['status'] == 'scheduled':
            row.update(membership_status='excluded', membership_reason='superseded_source_placeholder')


def parse(body, *, now):
    if not body or len(body) > MAX_FIRECRAWL_RESPONSE_BYTES:
        raise ValueError('cbbd_evidence_size')
    source = json.loads(body)
    if (source['source'] != SOURCE or source['source_url'] != URL or source['source_terms_url'] != TERMS
            or source['acquisition'] != ACQUISITION or source['last_page'] is not True):
        raise ValueError('cbbd_evidence_source_or_pagination')
    query = source['query']
    if query.keys() != {'season', 'startDateRange', 'endDateRange'} or type(query['season']) is not int:
        raise ValueError('cbbd_incomplete_daily_query')
    lower, upper = (stamp(query[key]) for key in ('startDateRange', 'endDateRange'))
    first = lower.astimezone(coverage.EASTERN).date()
    last = upper.astimezone(coverage.EASTERN).date()
    if (not first <= last <= first + timedelta(days=2) or lower != coverage.eastern_time(first)
            or upper != coverage.eastern_time(last + timedelta(days=1)) - timedelta(seconds=1)):
        raise ValueError('cbbd_incomplete_eastern_date_bounds')
    observed = stamp(source['observed_at'])
    if observed > now:
        raise ValueError('cbbd_future_observation')
    headers, pages = source['headers'], source['pages']
    if (not REQUIRED_FIELDS <= set(headers) or len(set(headers)) != len(headers) or not pages
            or sum(map(len, pages)) >= 3000 or any(not page for page in pages)):
        raise ValueError('cbbd_missing_or_truncated_export')
    receipt = SourceReceipt(URL, observed, observed, final_url=URL, raw_body=body, credits_used=0)
    grouped = defaultdict(list)
    seen = set()
    for page in pages:
        for values in page:
            row = dict(zip(headers, values, strict=True))
            instant = stamp(row['StartDate'])
            day = instant.astimezone(coverage.EASTERN).date()
            if (not lower <= instant <= upper or row['Id'] in seen or row['Season'] != str(query['season'])
                    or row['Season'] != load_membership(day).season.split('-')[1]):
                raise ValueError('cbbd_unexpected_or_duplicate_game')
            game = _game(row, day, receipt)
            grouped[day].append(game)
            seen.add(row['Id'])
    expected_days = {first + timedelta(days=offset) for offset in range((last - first).days + 1)}
    if set(grouped) != expected_days:
        raise ValueError('cbbd_missing_date_rows')
    for rows in grouped.values():
        _exclude_placeholder_duplicates(rows)
    return receipt, query, grouped, [len(page) for page in pages]


def attach(db, body):
    now = coverage.utc()
    receipt, query, grouped, pages = parse(body, now=now)
    digest = sha256(body).hexdigest()
    public_export = dict(evidence_mode='retrospective_public_export', acquisition=ACQUISITION, query=query,
                         displayed_page_rows=pages, source_terms_url=TERMS, source_request_clock='unavailable')
    with db.transaction():
        records._writer_lock(db)
        # Account for one append to each schedule and independent result ledger,
        # including the original pages, normalized rows and each binding revision.
        size = 6 * (len(body) + len(encoded(grouped_to_json(grouped))))
        _admit_storage(db, size)
        for day, rows in sorted(grouped.items()):
            for kind in ('schedule', 'results'):
                purpose = f'{kind}_public_export_{digest[:24]}'
                job = dict(game_date=day, source=SOURCE, kind=kind)
                attempt = dict(id=hashed([SOURCE, str(day), kind, digest, PARSER_VERSION]), request_url=URL,
                               request_reason='attach_retained_public_export', admitted_at=receipt.received_at)
                db.execute("""INSERT INTO public.mens_d1_job
                    (source,game_date,purpose,kind,due_at,expires_at,next_attempt_at,state,last_success_at,input)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'succeeded',%s,%s) ON CONFLICT DO NOTHING""",
                    (SOURCE, day, purpose, kind, now, now + timedelta(seconds=1), now, now, Jsonb(public_export)))
                db.execute("""INSERT INTO public.mens_d1_attempt
                    (id,source,game_date,purpose,request_url,request_reason,account_window,admitted_at,
                     reserved_credits,reserved_storage_bytes,settled_at,disposition,charged_credits)
                    VALUES (%s,%s,%s,%s,%s,%s,'public_export',%s,0,0,%s,'not_dispatched',0)
                    ON CONFLICT DO NOTHING""", (attempt['id'], SOURCE, day, purpose, URL,
                    attempt['request_reason'], receipt.received_at, now))
                facts = rows if kind == 'schedule' else [row for row in rows if row['status'] != 'scheduled']
                coverage.retain(db, job, attempt, receipt, rows=facts, parser_version=PARSER_VERSION,
                                membership_version=load_membership(day).version, public_export=public_export)
            coverage.retain_bindings(db, day, at=coverage.utc())
    return grouped


def _admit_storage(db, size):
    usage = records.retention_usage(db)
    if usage['total'] + usage['reserved'] + size > records.TOTAL_BYTE_CAP:
        raise ValueError('research_retention_capacity')
    if sql_usage(db) + size + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        raise ValueError('research_sql_runway')
    require_disk_space(ROOT / '.local/postgres', append_bytes=size)


def _official_game(note, original, day, observed):
    url, publisher, start, status = (note[key] for key in ('source_url', 'publisher', 'scheduled_start', 'status'))
    address = urlsplit(url)
    if (address.scheme != 'https' or not address.hostname or address.username or address.password
            or len(url) > 500 or not 0 < len(publisher) <= 120 or status not in ('scheduled', 'final')):
        raise ValueError('invalid_official_source_evidence')
    membership = load_membership(day)
    teams = []
    for team in note['teams']:
        evidence = membership.lookup(name=team['name'])
        score = team.get('score')
        if not evidence['canonical_id'] or (type(score) is not int or not 0 <= score <= 999
                if status == 'final' else score is not None):
            raise ValueError('invalid_official_team_or_score')
        teams.append(dict(name=team['name'], canonical_id=evidence['canonical_id'], score=score, membership=evidence))
    pair = coverage._pair(teams, 'canonical_id')
    original_ids = {team['membership'].get('canonical_id') for team in original['teams']} - {None}
    if (len(teams) != 2 or not pair or not original_ids or not original_ids <= pair
            or original['membership_status'] == 'excluded'
            or status == 'final' and teams[0]['score'] == teams[1]['score']):
        raise ValueError('official_game_does_not_corroborate_source_row')
    official_day = stamp(start).astimezone(coverage.EASTERN).date() if start else None
    date_disagreement = official_day is not None and official_day != day
    if date_disagreement:
        # Require exact participants and allow the midnight boundary clock
        # difference. Wider schedule changes need a separate occurrence witness.
        original_start = original.get('scheduled_start')
        if (original_ids != pair or not original_start
                or abs(stamp(start) - stamp(original_start)) > timedelta(minutes=1)):
            raise ValueError('official_game_cross_date_identity_unverified')
    return dict(kind=CORROBORATION_VERSION, source_game_id=original['source_game_id'],
        publisher=publisher, source_url=url, observed_at=coverage.clock(observed), status=status,
        scheduled_start=coverage.clock(start), eastern_game_date=str(official_day) if official_day else None,
        eastern_date_disagreement=date_disagreement, teams=teams)


def attach_corroborations(db, body):
    """Append verified school/conference facts while keeping the original source row intact."""
    if not body or len(body) > coverage.MAX_PARSED_BYTES:
        raise ValueError('official_evidence_size')
    data = json.loads(body)
    notes = data['games']
    observed, now = stamp(data['observed_at']), coverage.utc()
    if data['version'] != CORROBORATION_VERSION or observed > now or not 0 < len(notes) <= coverage.MAX_ROWS:
        raise ValueError('invalid_official_evidence_artifact')
    digest, entries = sha256(body).hexdigest(), []
    with db.transaction():
        records._writer_lock(db)
        _admit_storage(db, len(body) * 10)
        revisions = db.execute("""SELECT revision.id,revision.game_date,revision.facts,revision.observed_at
            FROM public.mens_d1_revision revision JOIN public.mens_d1_receipt receipt ON receipt.id=revision.receipt_id
            WHERE revision.source=%s AND revision.kind='schedule' AND receipt.body_sha256=%s
            ORDER BY revision.immutable_sequence DESC""", (SOURCE, data['public_export_body_sha256'])).fetchall()
        slates = {}
        for revision in revisions:
            slates.setdefault(str(revision['game_date']), revision)
        for note in notes:
            slate = slates.get(note['date'])
            if not slate or observed < slate['observed_at']:
                raise ValueError('official_evidence_original_slate_missing')
            original = next((row for row in slate['facts'] if row['source_game_id'] == note['source_game_id']), None)
            if original is None:
                raise ValueError('official_evidence_original_game_missing')
            facts = dict(_official_game(note, original, slate['game_date'], observed), artifact_sha256=digest)
            identity = hashed([slate['id'], facts])
            db.execute("""INSERT INTO public.mens_d1_binding(id,schedule_revision_id,facts)
                VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING""", (identity, slate['id'], Jsonb(facts)))
            entries.append(identity)
    return dict(artifact_sha256=digest, retained_corroborations=entries, provider_requests=0, charged_credits=0)


def grouped_to_json(grouped):
    return {str(day): rows for day, rows in sorted(grouped.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', help='Path to displayed public exporter receipt, or - for stdin')
    parser.add_argument('--validate-only', action='store_true', help='Verify the retained file without writing or querying production')
    parser.add_argument('--corroborations', action='store_true', help='Attach reviewed official facts to an already-retained exporter receipt')
    args = parser.parse_args()
    body = (sys.stdin.buffer.read(MAX_FIRECRAWL_RESPONSE_BYTES + 1) if args.receipt == '-' else
            Path(args.receipt).read_bytes())
    if args.corroborations:
        if args.validate_only:
            parser.error('Corroboration validation requires the original slate database receipt')
        with connect() as db:
            print(encoded(attach_corroborations(db, body)).decode())
        return
    if args.validate_only:
        _, _, grouped, _ = parse(body, now=coverage.utc())
    else:
        with connect() as db:
            grouped = attach(db, body)
    print(encoded(dict(receipt_sha256=sha256(body).hexdigest(), date_counts={str(day):
        dict(returned=len(rows), membership=Counter(row['membership_status'] for row in rows))
        for day, rows in sorted(grouped.items())}, provider_requests=0, charged_credits=0)).decode())


if __name__ == '__main__':
    main()
