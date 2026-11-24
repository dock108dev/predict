"""Read Sports Reference evidence through a separately authorized basic scrape.

The reader retains transport and source failures independently of parsing. The
parser only accepts a dated slate with a recognized layout or explicit empty
marker. A failed extraction never asserts a zero-game day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from app.normalization.mens_d1_membership import MembershipSnapshot, load_membership

SOURCE = 'sports_reference'
PARSER_VERSION = 'sports-reference-cbb-1'
SOURCE_ORIGIN = 'https://www.sports-reference.com'
FIRECRAWL_URL = 'https://api.firecrawl.dev/v2/scrape'
DOCUMENTED_BASIC_SCRAPE_CREDITS = 1
MAX_FIRECRAWL_RESPONSE_BYTES = 2 * 1024 * 1024
FIRECRAWL_READ_DEADLINE_SECONDS = 30
EASTERN = ZoneInfo('America/New_York')
_INDEX = {'schedule': '/cbb/seasons/schedule.cgi', 'results': '/cbb/boxscores/index.cgi'}
_RESULTS_INDEX = {_INDEX['results'], '/cbb/boxscores/'}
_DETAIL = re.compile(r'/cbb/boxscores/(\d{4}-\d{2}-\d{2})-[a-z0-9][a-z0-9-]*\.html')
_SCHOOL = re.compile(r'/cbb/schools/([a-z0-9-]+)/(men|women)(?:/|$)')
_CLOCK = re.compile(r'\b(\d{1,2}:\d{2}\s*[ap]m?)(?:\s+(E[SD]?T))?\b', re.I)
_GENDER = re.compile(r'\(([mw]|men|women)\)\s*$', re.I)
_SCHEDULE_SECTION = re.compile(r'\bGames\s*$', re.I)
_MATCHUP = re.compile(r'\s*@\s*')
_EMPTY = re.compile(r'(?:no (?:college basketball )?(?:games|games scheduled|games played|box scores|results)(?: (?:on|for) (?:this|that) (?:date|day))?)[.!]?', re.I)
_STATUS = {'final': 'final', 'f': 'final', 'scheduled': 'scheduled', 'postponed': 'postponed',
           'ppd': 'postponed', 'cancelled': 'cancelled', 'canceled': 'cancelled',
           'suspended': 'incomplete', 'in progress': 'incomplete', 'incomplete': 'incomplete'}


class SourcePageError(ValueError):
    """The receipt does not provide reliable evidence for the requested page."""


@dataclass(frozen=True)
class SourceReceipt:
    requested_url: str
    requested_at: datetime
    received_at: datetime
    final_url: str | None = None
    status_code: int | None = None
    transport_status: int | None = None
    raw_body: bytes = b''
    raw_html: str | None = None
    links: tuple[str, ...] = ()
    credits_used: int | None = None
    error: str | None = None

    @property
    def sha256(self) -> str:
        return sha256(self.raw_body).hexdigest()


def source_url(day: date, kind: str) -> str:
    query = urlencode({'day': day.day, 'month': day.month, 'year': day.year})
    return f'{SOURCE_ORIGIN}{_INDEX[kind]}?{query}'


def _source_path(url: str) -> str | None:
    p = urlsplit(url)
    if p.scheme == 'https' and p.netloc in {'www.sports-reference.com', 'sports-reference.com'}:
        return p.path
    return None


def _source_url_allowed(url: str) -> bool:
    path = _source_path(url)
    return (path in {*_INDEX.values(), *_RESULTS_INDEX}
            or (path is not None and _DETAIL.fullmatch(path) is not None))


def fetch_firecrawl(url: str, *, api_key: str, client: httpx.Client | None = None) -> SourceReceipt:
    """Issue one bounded request. The collector owns authorization and retries."""
    if not api_key.strip() or not _source_url_allowed(url):
        raise ValueError('sports_reference_request_not_configured')
    if client is None:
        with httpx.Client(timeout=25.0) as owned:
            return fetch_firecrawl(url, api_key=api_key, client=owned)

    requested_at = datetime.now(UTC)
    deadline = monotonic() + FIRECRAWL_READ_DEADLINE_SECONDS
    body = bytearray()
    transport_status = None
    try:
        with client.stream('POST', FIRECRAWL_URL, follow_redirects=False,
                           headers={'Authorization': f'Bearer {api_key}'},
                           json={'url': url, 'formats': ['rawHtml', 'links'], 'maxAge': 0,
                                 'proxy': 'basic', 'timeout': 20000}) as response:
            transport_status = response.status_code
            for chunk in response.iter_bytes():
                if monotonic() >= deadline:
                    return SourceReceipt(url, requested_at, datetime.now(UTC),
                                         transport_status=transport_status, error='firecrawl_response_deadline')
                if len(body) + len(chunk) > MAX_FIRECRAWL_RESPONSE_BYTES:
                    return SourceReceipt(url, requested_at, datetime.now(UTC),
                                         transport_status=transport_status,
                                         error='firecrawl_response_too_large')
                body.extend(chunk)
    except httpx.HTTPError:
        return SourceReceipt(url, requested_at, datetime.now(UTC), transport_status=transport_status,
                             error='firecrawl_transport_failure')
    received_at = datetime.now(UTC)
    raw_body = bytes(body)
    if api_key.encode() in raw_body:
        return SourceReceipt(url, requested_at, received_at, transport_status=transport_status,
                             error='firecrawl_credential_echo_discarded')
    response_fields = dict(transport_status=transport_status, raw_body=raw_body)
    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict):
        return SourceReceipt(url, requested_at, received_at, **response_fields,
                             error='firecrawl_invalid_response')
    if api_key in json.dumps(payload, ensure_ascii=False):
        return SourceReceipt(url, requested_at, received_at, transport_status=transport_status,
                             error='firecrawl_credential_echo_discarded')
    data = payload.get('data')
    data = data if isinstance(data, dict) else {}
    meta = data.get('metadata')
    meta = meta if isinstance(meta, dict) else {}
    final_url = meta.get('url') or meta.get('sourceURL')
    credits = payload.get('creditsUsed', meta.get('creditsUsed'))
    links = data.get('links')
    raw_html = data.get('rawHtml')
    status = meta.get('statusCode')
    error = None
    if transport_status != 200 or payload.get('success') is not True:
        error = 'firecrawl_request_failed'
    elif status != 200:
        error = 'sports_reference_http_failure'
    elif not isinstance(final_url, str) or not _source_url_allowed(final_url):
        error = 'sports_reference_unexpected_redirect'
    elif not isinstance(raw_html, str) or not raw_html.strip() or not isinstance(links, list):
        error = 'firecrawl_missing_raw_artifact'
    return SourceReceipt(
        url, requested_at, received_at, **response_fields, error=error,
        final_url=final_url if isinstance(final_url, str) else None,
        status_code=status if type(status) is int else None,
        raw_html=raw_html if isinstance(raw_html, str) else None,
        links=tuple(item for item in links if isinstance(item, str)) if isinstance(links, list) else (),
        credits_used=credits if type(credits) is int and credits >= 0 else None,
    )


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | str] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def raw_text(self):
        return ''.join(child.raw_text() if isinstance(child, _Node) else child for child in self.children)

    def text(self):
        return ' '.join(self.raw_text().split())

    def has_class(self, token):
        return token in self.attrs.get('class', '').split()


class _Tree(HTMLParser):
    _void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
             'meta', 'param', 'source', 'track', 'wbr'}
    _unclosed = {'li': {'li'}, 'p': {'p'}, 'tr': {'tr', 'td', 'th'},
                 'td': {'td', 'th'}, 'th': {'td', 'th'}}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node('document', {})
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        while self.stack[-1].tag in self._unclosed.get(tag, ()):
            self.stack.pop()
        node = _Node(tag, {name: value or '' for name, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in self._void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.stack[-1].tag not in {'style', 'script'}:
            self.stack[-1].children.append(data)

    def handle_comment(self, data):
        # Sports Reference embeds some line score tables as commented HTML.
        if re.search(r'<table\b[^>]*\bid=["\']line-score["\']', data, re.I) and '<!--' not in data:
            self.stack[-1].children.extend(_Tree(data).root.children)


def _page(receipt):
    if receipt.error or receipt.status_code != 200 or not receipt.raw_html or not receipt.final_url:
        raise SourcePageError(receipt.error or 'sports_reference_raw_receipt_unavailable')
    if not _source_url_allowed(receipt.final_url):
        raise SourcePageError('sports_reference_unexpected_redirect')
    nodes = list(_Tree(receipt.raw_html).root.walk())
    blocked = re.compile(r'access denied|just a moment|attention required|verify (that )?you are human|'
                         r'request blocked|page not found|sign in|log in', re.I)
    if any(blocked.search(node.text()) for node in nodes if node.tag in {'title', 'h1'}):
        raise SourcePageError('sports_reference_block_or_login_page')
    return nodes


def _heading_has_date(text, day):
    formats = ('%B %d, %Y', '%b %d, %Y')
    return any(re.search(r'\b' + re.escape(day.strftime(fmt).replace(' 0', ' ')) + r'\b', text, re.I)
               or re.search(r'\b' + re.escape(day.strftime(fmt)) + r'\b', text, re.I)
               for fmt in formats)


def _verify_index(receipt, nodes, day, kind):
    path = _source_path(receipt.final_url)
    allowed_paths = _RESULTS_INDEX if kind == 'results' else {_INDEX[kind]}
    if path not in allowed_paths:
        raise SourcePageError('sports_reference_wrong_page_kind')
    dates = parse_qs(urlsplit(receipt.final_url).query)
    try:
        if dates.keys() & {'day', 'month', 'year'} and date(
            int(dates['year'][0]), int(dates['month'][0]), int(dates['day'][0]),
        ) != day:
            raise SourcePageError('sports_reference_wrong_date')
    except (KeyError, ValueError, IndexError) as exc:
        raise SourcePageError('sports_reference_wrong_date') from exc
    title = re.compile(r'College Basketball Games on', re.I) if kind == 'schedule' else re.compile(
        r'(?:College Basketball )?(?:Box\s*Scores|Scores on)|NCAA (?:Men.s )?Basketball Scores', re.I)
    headings = [n.text() for n in nodes if n.tag in {'h1', 'h2', 'h3'} and title.search(n.text())]
    if not headings:
        raise SourcePageError('sports_reference_unrecognized_heading')
    if not any(_heading_has_date(h, day) for h in headings):
        raise SourcePageError('sports_reference_wrong_date')


def _schedule_section(nodes, day):
    for node in nodes:
        children = [child for child in node.children if isinstance(child, _Node)]
        for index, child in enumerate(children):
            if child.tag in {'h2', 'h3', 'h4'} and _SCHEDULE_SECTION.search(child.text()) and _heading_has_date(
                child.text(), day,
            ):
                return [member for sibling in children[index + 1:] for member in sibling.walk()]
    raise SourcePageError('sports_reference_schedule_section_unverified')


def _school_path(anchor):
    url = anchor.attrs.get('href', '')
    return _source_path(urljoin(SOURCE_ORIGIN, url)) or ''


def _participant(anchor, *, role, fallback_name=None):
    name = fallback_name or anchor.text()
    school = _SCHOOL.match(_school_path(anchor))
    return dict(source_team_id=school[1] if school else None, name=name, display_role=role,
                score=None, period_scores=None)


def _school_anchors(node):
    return [n for n in node.walk() if n.tag == 'a' and _SCHOOL.match(_school_path(n))]


def _allowed_detail(base, href, day):
    target = urljoin(base, href)
    match = _DETAIL.fullmatch(_source_path(target) or '')
    return target if match and match[1] == day.isoformat() else None


def _detail_id(url):
    return urlsplit(url).path.rsplit('/', 1)[-1].removesuffix('.html') if url else None


def _status(value):
    value = value.lower().strip()
    if re.fullmatch(r'f\s*inal(?:\s+\(?\d*\s*ot\)?)?', value):
        return 'final'
    return _STATUS.get(value)


def _points(value):
    return int(value) if re.fullmatch(r'\d{1,3}', value) else None


def _published_at(node):
    value = node.attrs.get('data-updated-at') or node.attrs.get('data-published-at')
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _overtime(value):
    match = re.search(r'\b(\d{1,2})?\s*OT\b', value, re.I)
    return int(match[1] or '1') if match else None


def _eastern_time(day, raw, zone):
    if not raw or not zone:
        return None
    try:
        clock = raw.replace(' ', '').upper()
        clock = f'{clock}M' if clock.endswith(('A', 'P')) else clock
        wall = datetime.combine(day, datetime.strptime(clock, '%I:%M%p').time())
    except ValueError:
        return None
    choices = set()
    for fold in (0, 1):
        local = wall.replace(tzinfo=EASTERN, fold=fold)
        instant = local.astimezone(UTC)
        if instant.astimezone(EASTERN).replace(tzinfo=None) == wall and zone in {'ET', local.tzname()}:
            choices.add(instant)
    return choices.pop().isoformat() if len(choices) == 1 else None


def _membership_fields(teams, gender, snapshot):
    for team in teams:
        team['membership'] = (snapshot.lookup(team['source_team_id'], team['name'])
                              if gender == 'men' else snapshot.unresolved('men_membership_not_applicable'))
        team['canonical_id'] = team['membership'].get('canonical_id')
    divisions = {team['membership']['division'] for team in teams}
    if gender == 'women':
        return 'excluded', 'womens_game'
    if gender != 'men':
        return 'unresolved', 'gender_unverified'
    if 'non_d1' in divisions:
        return 'excluded', 'participant_not_ncaa_division_i'
    if divisions != {'d1'}:
        return 'unresolved', 'participant_membership_unverified'
    return 'eligible', None


def _row(receipt, day, gender, teams, snapshot, *, source_time=None, source_timezone=None,
         scheduled_start=None, site=None, neutral_site=None, status, overtime_periods=None,
         detail_url=None, detail_reason=None, native_game_id=None, published_at=None, gender_evidence=None):
    membership_status, membership_reason = _membership_fields(teams, gender, snapshot)
    participants = sorted(t['membership'].get('membership_record_id') or t['source_team_id']
                          or t['name'].casefold() for t in teams)
    pair_hash = sha256(json.dumps([gender, participants], ensure_ascii=False).encode()).hexdigest()[:20]
    return dict(
        source_game_id=f'{day.isoformat()}:{pair_hash}', native_game_id=native_game_id, date=day.isoformat(),
        source_date=day.isoformat(), source_time=source_time, source_timezone=source_timezone,
        scheduled_start=scheduled_start, site=site, neutral_site=neutral_site,
        gender=gender, gender_evidence=gender_evidence,
        membership_status=membership_status, membership_reason=membership_reason,
        membership_version=snapshot.version, teams=teams, status=status,
        overtime_periods=overtime_periods, published_at=published_at, source_url=receipt.final_url,
        detail_url=detail_url, detail_reason=detail_reason,
    )


def _schedule_rows(nodes, receipt, day, snapshot):
    records = []
    eastern_legend = False
    rows = set()
    for node in reversed(nodes):
        if node.tag not in {'span', 'li', 'p', 'tr', 'div'}:
            continue
        text = node.text()
        if (not _MATCHUP.search(text) or len(text) > 240
                or any(n is not node for n in node.walk() if id(n) in rows)):
            continue
        gender = _GENDER.search(text)
        clock = _CLOCK.search(text[:gender.start()] if gender else text)
        notes = [n.text() for n in node.children if isinstance(n, _Node) and n.has_class('note')]
        note = notes[0] if len(notes) == 1 else None
        if gender is None and clock is None and note is None:
            continue
        rows.add(id(node))
        eastern_legend |= bool(clock and clock[2])
        records.append((node, text, gender, clock, note))

    for node, text, gender, clock, note in reversed(records):
        team_names = (text.removesuffix(note) if note is not None
                      else text.split(clock[0] if clock else gender[0], 1)[0]).strip()
        typed_status = re.search(r'\b(postponed|ppd|cancelled|canceled)\b', note or text, re.I)
        if typed_status and not note:
            team_names = team_names.removesuffix(typed_status[0]).strip()
        names = [re.sub(r'\s*\(\d+\)$', '', name.strip()) for name in _MATCHUP.split(team_names)]
        if len(names) != 2 or not all(names):
            raise SourcePageError('sports_reference_malformed_schedule_row')
        gender_evidence = gender[0] if gender else None
        gender = ('men' if gender[1].lower() in {'m', 'men'} else 'women') if gender else 'unknown'
        teams = []
        anchors = _school_anchors(node)
        for name, role in zip(names, ('away', 'home'), strict=True):
            matching = [anchor for anchor in anchors if anchor.text().casefold() == name.casefold()]
            anchor = matching[0] if len(matching) == 1 else _Node('span', {})
            teams.append(_participant(anchor, role=role, fallback_name=name))
        anchor_genders = {_SCHOOL.match(_school_path(anchor))[2] for anchor in anchors}
        if anchor_genders and anchor_genders != {gender}:
            gender_evidence = None
            gender = 'unknown'
        detail_url = next((link for link in (_allowed_detail(receipt.final_url, n.attrs.get('href', ''), day)
                                            for n in node.walk() if n.tag == 'a') if link), None)
        raw_time = clock[1] if clock else None
        zone = (clock[2] or ('ET' if eastern_legend else None)) if clock else None
        if zone:
            zone = zone.upper()
        neutral = {'true': True, 'false': False}.get(node.attrs.get('data-neutral-site'))
        yield _row(receipt, day, gender, teams, snapshot, source_time=raw_time, source_timezone=zone,
                   scheduled_start=_eastern_time(day, raw_time, zone),
                   site=node.attrs.get('data-site') or None, neutral_site=neutral,
                   status=_status(typed_status[1]) if typed_status else 'scheduled', detail_url=detail_url,
                   native_game_id=node.attrs.get('data-game-id') or _detail_id(detail_url),
                   published_at=_published_at(node), gender_evidence=gender_evidence)


def _index_team(row):
    cells = [n for n in row.children if isinstance(n, _Node) and n.tag in {'td', 'th'}]
    if len(cells) < 2:
        raise SourcePageError('sports_reference_malformed_result_team')
    name_cell = next((c for c in cells if c.attrs.get('data-stat') in {'team', 'school', 'team_name'}), cells[0])
    anchors = _school_anchors(name_cell)
    role = row.attrs.get('data-role')
    team = _participant(anchors[0] if len(anchors) == 1 else _Node('span', {}),
                        role=role if role in ('away', 'home') else None, fallback_name=name_cell.text())
    if not team['name']:
        raise SourcePageError('sports_reference_missing_result_team')
    score_cell = next((c for c in cells if c.attrs.get('data-stat') in {'pts', 'score', 'points'}
                       or c.has_class('right')), cells[1])
    marks = [c.text() for c in cells if c is not name_cell and c is not score_cell]
    return team, _points(score_cell.text()), marks


def _results_rows(nodes, receipt, day, snapshot):
    gender = 'unknown'
    for node in nodes:
        if node.tag in {'h2', 'h3', 'h4'}:
            heading = node.text().lower()
            if re.search(r'\bwomen\b', heading):
                gender = 'women'
            elif re.search(r'\bmen\b', heading):
                gender = 'men'
        if not node.has_class('game_summary'):
            continue
        tables = [n for n in node.walk() if n.tag == 'table' and n.has_class('teams')]
        if len(tables) != 1:
            raise SourcePageError('sports_reference_malformed_result_card')
        rows = [n for n in tables[0].walk() if n.tag == 'tr' and any(
            isinstance(c, _Node) and c.tag == 'td' and not c.has_class('desc') for c in n.children)]
        if len(rows) != 2:
            raise SourcePageError('sports_reference_malformed_result_card')
        parsed = [_index_team(row) for row in rows]
        teams = [item[0] for item in parsed]
        genders = {_SCHOOL.match(_school_path(anchor))[2]
                   for anchor in _school_anchors(tables[0])}
        explicit_gender = node.attrs.get('data-gender', '').lower()
        if node.has_class('gender-w'):
            explicit_gender = 'women'
        elif node.has_class('gender-m'):
            explicit_gender = 'men'
        descriptors = [n.text().lower().replace('’', "'") for n in node.walk() if n.has_class('desc')]
        if "women's" in descriptors:
            explicit_gender = 'women'
        elif "men's" in descriptors:
            explicit_gender = 'men'
        card_gender = explicit_gender if explicit_gender in {'men', 'women'} else gender
        if len(genders) == 1 and card_gender == 'unknown':
            card_gender = next(iter(genders))
        if len(genders) > 1 or (genders and card_gender not in genders):
            card_gender = 'unknown'
        marks = [mark for item in parsed for mark in item[2] if mark]
        states = {_status(mark) for mark in marks} - {None}
        status = next(iter(states)) if len(states) == 1 else 'unresolved'
        scores = [item[1] for item in parsed]
        clock = next((m for m in (_CLOCK.fullmatch(mark) for mark in marks) if m), None)
        if not states and clock and all(score is None for score in scores):
            status = 'scheduled'
        if status == 'final' and (None in scores or scores[0] == scores[1]):
            status = 'incomplete'
        if status == 'final':
            for team, score in zip(teams, scores, strict=True):
                team['score'] = score
        overtime = _overtime(' '.join(marks))
        detail_url = next((link for link in (_allowed_detail(receipt.final_url, n.attrs.get('href', ''), day)
                           for n in node.walk() if n.tag == 'a') if link), None)
        reason = ('confirm_result_status_or_scores' if status in {'incomplete', 'unresolved'} else
                  'confirm_overtime_period_scores' if overtime and status == 'final' else None)
        source_time = clock[1] if clock else None
        source_timezone = clock[2].upper() if clock and clock[2] else None
        result = _row(receipt, day, card_gender, teams, snapshot, status=status, overtime_periods=overtime,
                      source_time=source_time, source_timezone=source_timezone,
                      scheduled_start=_eastern_time(day, source_time, source_timezone),
                      detail_url=detail_url, detail_reason=reason if detail_url else None,
                      native_game_id=node.attrs.get('data-game-id') or _detail_id(detail_url),
                      published_at=_published_at(node),
                      gender_evidence=f'box_score_index:{card_gender}' if card_gender != 'unknown' else None)
        yield result


def parse_page(receipt: SourceReceipt, *, day: date, kind: str,
               membership: MembershipSnapshot | None = None) -> list[dict]:
    if kind not in _INDEX:
        raise ValueError('sports_reference_page_kind_unsupported')
    nodes = _page(receipt)
    _verify_index(receipt, nodes, day, kind)
    explicit_empty = any(_EMPTY.fullmatch(n.text()) for n in nodes if n.tag in {'p', 'div', 'li'})
    if kind == 'schedule':
        if explicit_empty and not any(_SCHEDULE_SECTION.search(n.text()) and _heading_has_date(n.text(), day)
                                      for n in nodes if n.tag in {'h2', 'h3', 'h4'}):
            return []
        nodes = _schedule_section(nodes, day)
    snapshot = membership or load_membership(day)
    parse = _schedule_rows if kind == 'schedule' else _results_rows
    rows = list(parse(nodes, receipt, day, snapshot))
    if not rows and not explicit_empty:
        raise SourcePageError('sports_reference_no_recognized_games_or_empty_marker')
    if len({item['source_game_id'] for item in rows}) != len(rows):
        raise SourcePageError('sports_reference_duplicate_game_identity')
    return rows


def parse_detail(receipt: SourceReceipt, *, day: date, game: dict,
                 membership: MembershipSnapshot | None = None) -> dict:
    nodes = _page(receipt)
    heading = next((n.text() for n in nodes if n.tag == 'h1'), '')
    gender = {'Men': 'men', 'Women': 'women'}.get(next(iter(re.findall(r'Box Score \((Men|Women)\)', heading)), ''))
    if (not _allowed_detail(receipt.requested_url, receipt.final_url, day)
            or _source_path(receipt.final_url) != _source_path(game.get('detail_url') or '')
            or (game['gender'] != 'unknown' and gender != game['gender']) or not _heading_has_date(heading, day)):
        raise SourcePageError('sports_reference_detail_identity_unverified')
    line_score = next((n for n in nodes if n.tag == 'table' and n.attrs.get('id') == 'line-score'), None)
    if line_score is None:
        raise SourcePageError('sports_reference_detail_line_score_unavailable')
    row_nodes = [n for n in line_score.walk() if n.tag == 'tr' and any(
        isinstance(c, _Node) and c.tag == 'td' for c in n.children)]
    if len(row_nodes) != 2:
        raise SourcePageError('sports_reference_detail_line_score_malformed')
    matched = {}
    regulation_periods = 4 if gender == 'women' else 2
    required_periods = regulation_periods + (game['overtime_periods'] or 0)
    for row in row_nodes:
        anchors = _school_anchors(row)
        if len(anchors) != 1:
            raise SourcePageError('sports_reference_detail_team_identity_unverified')
        seen = _participant(anchors[0], role=None)
        source_id = seen['source_team_id']
        team = next((t for t in game['teams'] if t['source_team_id'] == source_id), None)
        if team is None or source_id in matched:
            raise SourcePageError('sports_reference_detail_team_identity_unverified')
        total = next((n for n in row.walk() if n.tag == 'td' and n.attrs.get('data-stat') in
                      {'pts', 'score', 'T', 'total'}), None)
        points = _points(total.text()) if total else None
        periods = [_points(n.text()) for n in row.walk() if n.tag == 'td' and re.fullmatch(
            r'(?:[1-4]|[1-9]\d*OT|OT|period_[1-9]\d*)', n.attrs.get('data-stat', ''), re.I)]
        full_periods = len(periods) >= required_periods and None not in periods
        if points is None or (full_periods and sum(periods) != points):
            raise SourcePageError('sports_reference_detail_line_score_conflict')
        matched[source_id] = {**team, 'score': points, 'period_scores': periods if full_periods else None}
    teams = [matched[t['source_team_id']] for t in game['teams']]
    if teams[0]['score'] == teams[1]['score']:
        raise SourcePageError('sports_reference_detail_tied_final')
    scorebox = next((n for n in nodes if n.has_class('scorebox')), None)
    final_mark = scorebox and any(_status(n.text()) == 'final' for n in scorebox.walk()
                                  if n.tag in {'div', 'span', 'strong'})
    if game['status'] != 'final' and not final_mark:
        raise SourcePageError('sports_reference_detail_final_status_unverified')
    if any(t.get('score') is not None and t['score'] != revised['score']
           for t, revised in zip(game['teams'], teams, strict=True)):
        # A dated index/detail contradiction has to remain a separate result.
        return {**game, 'teams': teams, 'source_url': receipt.final_url, 'detail_reason': 'index_detail_score_conflict',
                'published_at': _published_at(scorebox) if scorebox else None}
    periods = [len(t['period_scores']) for t in teams if t['period_scores'] is not None]
    overtime = len(set(periods)) == 1 and len(periods) == 2 and max(periods) > regulation_periods
    snapshot = membership or load_membership(day)
    membership_status, membership_reason = _membership_fields(teams, gender, snapshot)
    venue = next((n.text() for n in nodes if n.attrs.get('data-stat') in {'venue', 'site', 'location'}
                  and n.tag in {'div', 'span'} and n.text()), None)
    return {**game, 'gender': gender, 'gender_evidence': f'box_score_title:{gender}', 'teams': teams,
            'status': 'final', 'source_url': receipt.final_url,
            'published_at': _published_at(scorebox) if scorebox else None, 'site': venue or game.get('site'),
            'overtime_periods': max(periods) - regulation_periods if overtime else game['overtime_periods'],
            'membership_status': membership_status, 'membership_reason': membership_reason,
            'membership_version': snapshot.version, 'detail_reason': None}
