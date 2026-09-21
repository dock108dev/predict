"""File-only VegasInsider NFL moneyline evidence parser; no scanner integration.

Same displayed bookmaker column is evidence of co-display, not synchronized
upstream updates, independent lineage, or compatible settlement.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal, localcontext, Context, ROUND_HALF_EVEN
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

URL = 'https://www.vegasinsider.com/nfl/odds/las-vegas/'
LABEL = 'delayed-reference research estimate'


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


@dataclass(frozen=True)
class DelayedPolicy:
    version: str = 'public-page-delayed-research-1'
    max_receipt_age_seconds: int = 1200
    max_displayed_update_age_seconds: int = 1200
    accepted_disclosed_delay_seconds: int = 900
    max_target_age_seconds: int = 30
    max_receipt_skew_seconds: int = 1200
    pregame_buffer_seconds: int = 60

    def assess(self, *, retrieved_at, cutoff, scheduled_start,
               bookmaker_updated_at=None, disclosed_delay_seconds=None, target_received_at=None):
        receipt, end, start = map(timestamp, (retrieved_at, cutoff, scheduled_start))
        reasons = []
        age = (end - receipt).total_seconds()
        if age < 0 or age > self.max_receipt_age_seconds:
            reasons.append('receipt_outside_research_window')
        if (start - end).total_seconds() <= self.pregame_buffer_seconds:
            reasons.append('not_safely_pregame')
        if bookmaker_updated_at is not None:
            update = timestamp(bookmaker_updated_at)
            if update > receipt or (end - update).total_seconds() > self.max_displayed_update_age_seconds:
                reasons.append('displayed_update_outside_research_window')
        elif disclosed_delay_seconds is None:
            reasons.append('update_and_delay_unknown')
        if disclosed_delay_seconds is not None and not 0 <= disclosed_delay_seconds <= self.accepted_disclosed_delay_seconds:
            reasons.append('disclosed_delay_outside_policy')
        if target_received_at is not None:
            target = timestamp(target_received_at)
            if not 0 <= (end - target).total_seconds() <= self.max_target_age_seconds:
                reasons.append('target_outside_research_window')
            if abs((target - receipt).total_seconds()) > self.max_receipt_skew_seconds:
                reasons.append('reference_target_receipt_skew')
        return dict(policy=asdict(self), reasons=reasons,
                    research_time_eligible=not reasons, current_executable=False,
                    bookmaker_updated_at=bookmaker_updated_at,
                    upstream_age_verified=bookmaker_updated_at is not None,
                    label=LABEL)


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    text: str = ''

    def all(self, tag=None, cls=None):
        result = []
        for child in self.children:
            if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                result.append(child)
            result.extend(child.all(tag, cls))
        return result

    def content(self):
        return ' '.join((self.text + ' ' + ' '.join(c.content() for c in self.children)).split())


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'embed', 'param', 'col'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].text += data


def one(items, reason):
    if len(items) != 1:
        raise ValueError(reason)
    return items[0]


def american_decimal(raw):
    if not re.fullmatch(r'[+-]\d+', raw) or abs(int(raw)) < 100:
        raise ValueError('invalid_american_price')
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        value = Decimal(raw)
        return str(1 + (value / 100 if value > 0 else 100 / -value))


def parse(raw, metadata, *, event_id, bookmaker='draftkings'):
    """One explicitly selected event/book, never best/open/consensus or fallback."""
    if metadata['url'] != URL or metadata['status'] != 200:
        raise ValueError('unsupported_source_or_http_status')
    if sha256(raw).hexdigest() != metadata['sha256']:
        raise ValueError('raw_hash_mismatch')
    timestamp(metadata['retrieved_at'])
    if bookmaker != 'draftkings':
        raise ValueError('only_selected_draftkings_column_supported')
    source = raw.decode('utf-8', errors='strict')
    bodies = re.findall(r'<tbody\b[^>]*\bid="odds-table-moneyline--0"[^>]*>.*?</tbody>', source, re.S)
    body = one(bodies, 'missing_or_duplicate_moneyline_table')
    tree = Tree(); tree.feed(body)
    rows = tree.root.all('tr')
    header_indexes = [i for i, row in enumerate(rows) if any(
        f'/nfl/events/{event_id}/odds/' in n.attrs.get('data-content', '') for n in row.all('td', 'game-time'))]
    index = one(header_indexes, 'missing_or_duplicate_event')
    header = rows[index]
    times = [n.attrs['data-value'] for n in header.all('span') if n.attrs.get('data-role') == 'localtime']
    start = one(times, 'ambiguous_start'); timestamp(start)
    cells = [n for n in header.children if n.tag in ('td', 'th')]
    columns = [i for i, c in enumerate(cells) if any(n.attrs.get('alt') == bookmaker for n in c.all('img'))]
    column = one(columns, 'missing_or_duplicate_bookmaker')
    team_rows = []
    for row in rows[index+1:]:
        if row.all('td', 'game-time'):
            break
        if row.all('td', 'game-team'):
            team_rows.append(row)
    if len(team_rows) != 2:
        raise ValueError('exactly_two_team_rows_required')
    sides = []
    for row in team_rows:
        row_cells = [n for n in row.children if n.tag in ('td', 'th')]
        # The captured layout includes one trailing empty action cell.
        if row_cells and row_cells[-1].attrs.get('class') == 'game-odds blank' and not row_cells[-1].content():
            row_cells = row_cells[:-1]
        if len(row_cells) != len(cells) or any(n.attrs.get('colspan') or n.attrs.get('rowspan') for n in row_cells + cells):
            raise ValueError('column_alignment_ambiguous')
        team_cell = one(row.all('td', 'game-team'), 'ambiguous_team')
        team = one(team_cell.all('img'), 'ambiguous_team').attrs.get('alt')
        abbr = one(team_cell.all('a', 'team-name'), 'ambiguous_team').attrs.get('data-abbr')
        if not team or not abbr:
            raise ValueError('missing_team_identity')
        price_cell = row_cells[column]
        if any('disabled' in n.attrs.get('class', '').split() for n in [price_cell] + price_cell.all()):
            raise ValueError('disabled_price')
        if 'game-odds' not in price_cell.attrs.get('class', '').split() or 'best' in price_cell.attrs.get('class', '').split():
            raise ValueError('not_bookmaker_price_cell')
        price = one(price_cell.all('span', 'data-moneyline'), 'missing_or_duplicate_price').content()
        sides.append(dict(team=team, abbreviation=abbr, american_price=price, decimal_odds=american_decimal(price)))
    if sides[0]['team'] == sides[1]['team'] or sides[0]['abbreviation'] == sides[1]['abbreviation']:
        raise ValueError('duplicate_team')
    page = Tree(); page.feed(source)
    notices = sorted(set(n.content() for n in page.root.all() if not n.children and
                         re.search(r'last updated|\bdelay(?:ed)?\b|odds.*updat', n.text, re.I) and n.tag not in ('script', 'style')))
    delay_notices = [n for n in notices if re.search(r'\bdelay(?:ed)?\b', n, re.I)]
    return dict(format='public-nfl-page-evidence-1', mode='public_page_research',
                url=metadata['url'], retrieved_at=metadata['retrieved_at'], raw_sha256=metadata['sha256'],
                event_id=str(event_id), league='NFL', scheduled_start=start,
                market='full_game_moneyline', bookmaker=bookmaker, source_family=bookmaker,
                sides=sides, pairing='same_displayed_column; upstream_synchronization_unknown',
                displayed_notice_text=notices, bookmaker_updated_at=None, delay_notice=delay_notices or None,
                disclosed_delay_seconds=None, copied_from=None, provenance_assessment=None,
                normal_winner_rules=None, full_settlement_compatibility=None,
                label=LABEL, probabilities=None, conditional_ev=None, unconditional_ev=None,
                current_executable=False,
                reasons=['update_and_delay_unknown', 'target_independent_provenance_unassessed',
                         'normal_winner_rules_unassessed', 'prospective_target_record_absent'])


def main():
    import argparse
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('capture_directory', type=Path)
    cli.add_argument('--event-id', required=True)
    args = cli.parse_args()
    metadata = json.loads((args.capture_directory / 'capture.json').read_text())
    result = parse((args.capture_directory / 'vegasinsider.html').read_bytes(), metadata, event_id=args.event_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
