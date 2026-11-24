"""CollegeBasketballData's documented, keyed game and account endpoints."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from time import monotonic
from urllib.parse import urlencode

import httpx

from app.storage import mens_d1_coverage as coverage
from app.storage.store import stamp
from .mens_d1_public_export import REQUIRED_FIELDS, _exclude_placeholder_duplicates, _game
from .mens_d1_source import MAX_FIRECRAWL_RESPONSE_BYTES, SourcePageError, SourceReceipt, load_membership
from .service_secrets import read_file

ORIGIN = 'https://api.collegebasketballdata.com'
ACCOUNT_URL = ORIGIN + '/info'
GAMES_URL = ORIGIN + '/games'
PARSER_VERSION = 'college-basketball-data-games-api-1'
KEY_UNAVAILABLE = 'cbbd_api_credential_unavailable'
ACCOUNT_UNVERIFIED = 'cbbd_api_account_allowance_unverified'
ACCESS_DENIED = 'cbbd_api_access_denied'
RATE_LIMITED = 'cbbd_api_rate_limited'
ALLOWANCE_EXHAUSTED = 'cbbd_api_monthly_allowance_exhausted_or_held'
REQUEST_TIMEOUT = 20
GAMES_RESPONSE_LIMIT = 3000


@dataclass(frozen=True)
class Account:
    starts_at: datetime
    ends_at: datetime
    monthly_limit: int
    remaining: int
    tier: str
    key: str

    @property
    def window_id(self):
        return 'cbbd:' + self.ends_at.date().isoformat()

    def budget(self):
        return dict(window_starts_at=coverage.clock(self.starts_at), window_ends_at=coverage.clock(self.ends_at),
            monthly_call_limit=self.monthly_limit, remaining_calls_at_check=self.remaining, tier=self.tier,
            shared_with_college_football=True, per_request_call_reservation=1)


def credential():
    try:
        key = read_file('cbbd')
    except FileNotFoundError:
        key = None
    except (OSError, ValueError, UnicodeError):
        return None
    key = (key or os.environ.get('CBBD_API_KEY') or '').strip()
    if not key or len(key) > 1024 or any(not 33 <= ord(char) <= 126 for char in key):
        return None
    return key


def source_url(day):
    eastern_start = coverage.eastern_time(day).astimezone(timezone.utc)
    eastern_end = coverage.eastern_time(day + timedelta(days=1)).astimezone(timezone.utc)
    query = urlencode(dict(season=int(load_membership(day).season.split('-')[1]),
        startDateRange=eastern_start.isoformat(), endDateRange=(eastern_end - timedelta(milliseconds=1)).isoformat()))
    return f'{GAMES_URL}?{query}'


def _read(client, url, key, *, limit, now):
    requested_at = now()
    end = monotonic() + REQUEST_TIMEOUT
    body = bytearray()
    status, documented_charge, error = None, None, None
    try:
        with client.stream('GET', url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'},
                           follow_redirects=False, timeout=REQUEST_TIMEOUT) as response:
            status = response.status_code
            if status == 200:
                documented_charge = int(url != ACCOUNT_URL)
            elif status in (401, 403, 429):
                documented_charge = 0
            for chunk in response.iter_bytes():
                if monotonic() > end:
                    error = 'cbbd_api_response_deadline'
                    break
                if len(body) + len(chunk) > limit:
                    error = 'cbbd_api_response_too_large'
                    break
                body.extend(chunk)
    except httpx.HTTPError:
        error = 'cbbd_api_transport_failure'
    if key.encode('ascii') in body:
        body.clear()
        error = 'cbbd_api_credential_echo_discarded'
    status_reason = (ACCESS_DENIED if status in (401, 403) else RATE_LIMITED if status == 429 else
                     'cbbd_api_unexpected_http_status' if status != 200 else None)
    return SourceReceipt(url, requested_at, now(), final_url=url if status is not None else None,
        status_code=status, transport_status=status, raw_body=bytes(body), credits_used=documented_charge,
        error=error or status_reason)


def verify_account(key, *, client=None, now=coverage.utc):
    if client is None:
        with httpx.Client(trust_env=False) as owned:
            return verify_account(key, client=owned, now=now)
    receipt = _read(client, ACCOUNT_URL, key, limit=16_384, now=now)
    if receipt.error:
        return None, receipt.error
    try:
        data = json.loads(receipt.raw_body)
        remaining, limit, tier = data['remainingCalls'], data['monthlyLimit'], data['tierName']
        end = stamp(data['resetAt']).astimezone(timezone.utc)
        start = (end - timedelta(days=1)).replace(day=1)
        if (type(limit) is not int or type(remaining) is not int or remaining < 0 or limit < 1
                or not isinstance(tier, str) or not 0 < len(tier) <= 100
                or data['sharedPool'] is not True or not isinstance(data['products'], list)
                or 'cbb' not in data['products']
                or end.day != 1 or end.hour or end.minute or end.second or end.microsecond
                or not start <= receipt.received_at < end):
            raise ValueError(ACCOUNT_UNVERIFIED)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return None, ACCOUNT_UNVERIFIED
    return Account(start, end, limit, remaining, tier, key), None if remaining else ALLOWANCE_EXHAUSTED


def fetch_games(url, *, api_key, client=None, now=coverage.utc):
    if not url.startswith(GAMES_URL + '?'):
        raise ValueError('cbbd_api_request_not_configured')
    if client is None:
        with httpx.Client(trust_env=False) as owned:
            return fetch_games(url, api_key=api_key, client=owned, now=now)
    return _read(client, url, api_key, limit=MAX_FIRECRAWL_RESPONSE_BYTES, now=now)


def _export_fields(row):
    """Map the structured fields to the existing CBBD membership and identity parser."""
    result = {}
    for field in REQUIRED_FIELDS:
        value = row[field[0].lower() + field[1:]]
        if field in {'Id', 'Season', 'AwayTeamId', 'HomeTeamId'}:
            if type(value) is not int or value < 0:
                raise ValueError('cbbd_api_invalid_integer')
        elif field in {'StartTimeTbd', 'NeutralSite'}:
            if type(value) is not bool:
                raise ValueError('cbbd_api_invalid_boolean')
        elif field in {'HomePoints', 'AwayPoints'}:
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('cbbd_api_invalid_score')
        elif field in {'HomePeriodPoints', 'AwayPeriodPoints'}:
            if value is not None and not isinstance(value, list):
                raise ValueError('cbbd_api_invalid_period_scores')
        elif not (isinstance(value, str) or value is None and field in {'Venue', 'HomeConference', 'AwayConference'}):
            raise ValueError('cbbd_api_invalid_text')
        result[field] = '' if value is None else value if isinstance(value, str) else json.dumps(value)
    return result


def parse_games(receipt, *, day, kind):
    if receipt.error or kind not in ('schedule', 'results') or receipt.requested_url != source_url(day):
        raise SourcePageError('cbbd_api_unexpected_receipt_scope')
    season = load_membership(day).season.split('-')[1]
    try:
        payload = json.loads(receipt.raw_body)
        if not isinstance(payload, list) or len(payload) >= GAMES_RESPONSE_LIMIT:
            raise ValueError('cbbd_api_unexpected_or_truncated_payload')
        rows, seen = [], set()
        for item in payload:
            row = _export_fields(item)
            if (row['Season'] != season or row['Id'] in seen
                    or stamp(row['StartDate']).astimezone(coverage.EASTERN).date() != day):
                raise ValueError('cbbd_api_unexpected_or_duplicate_game')
            rows.append(_game(row, day, receipt,
                gender_evidence='CollegeBasketballData men’s college basketball games API', allow_provisional_final=True))
            seen.add(row['Id'])
        _exclude_placeholder_duplicates(rows)
        return rows
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        raise SourcePageError('cbbd_api_game_payload_or_row_invalid') from exc
