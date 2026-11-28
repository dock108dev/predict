"""Read-only ProphetX affiliate data; never authenticate a trading session."""

import asyncio
import json
import re
from datetime import timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from fractions import Fraction as F
from hashlib import sha256

import httpx

from app.comparison.sgo_reference import american_probability
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.storage.store import hashed, stamp

from .admission_enrichment import resolve_team
from .native_trading_identity import native_event, record, expected
from .service_secrets import keychain_or_file

HOST = "https://cash.api.prophetx.co/partner"
TOURNAMENTS = "/affiliate/get_tournaments"
EVENTS = "/affiliate/get_sport_events"
MARKETS = "/v4/affiliate/get_multiple_markets"
PATHS = frozenset((TOURNAMENTS, EVENTS, MARKETS))
SOURCE = "https://docs.prophetx.co/reference/get_v4-affiliate-get-multiple-markets"
BOOK_AGE = timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS)
# The affiliate sport-event reference publishes these four IDs. An exact
# match in the authenticated tournament response is still required at runtime.
DOCUMENTED_TOURNAMENTS = {"NFL": "31", "NBA": "132", "MLB": "109", "NHL": "234"}
TOURNAMENT_LEAGUES = {tid: league for league, tid in DOCUMENTED_TOURNAMENTS.items()}
TOURNAMENT_NAMES = {
    **{league: {league.casefold()} for league in DOCUMENTED_TOURNAMENTS},
    "NCAAB": {
        "ncaab",
        "ncaam",
        "ncaamen",
        "ncaamensbasketball",
        "ncaadivisionimensbasketball",
    },
    "NCAAF": {"ncaaf", "ncaafootball", "ncaadivisionifootball", "collegefootball"},
}


def _numeric_id(value):
    if type(value) not in (int, str) or not re.fullmatch(r"[0-9]{1,20}", str(value)):
        return None
    number = int(value)
    return str(number) if number else None


def _origin(proof):
    received = stamp(proof["received_at"])
    source = stamp(parsedate_to_datetime(proof["date"]))
    age = int(proof.get("age", "0"))
    if source > received or age < 0:
        raise ValueError("prophetx_cache_clock_invalid")
    return min(source, received - timedelta(seconds=age))


def _phase_expiry(event, at):
    proof = event["native_role_evidence"]
    try:
        if (
            proof.get("path") != EVENTS
            or proof.get("status") != 200
            or proof.get("event_status") != "scheduled"
            or proof.get("event_id") != event["id"]
            or stamp(proof["scheduled_start"]) != stamp(event["scheduled_start"])
            or not stamp(proof["requested_at"]) <= stamp(proof["received_at"]) <= at
        ):
            return None
        expiry = min(stamp(event["scheduled_start"]), _origin(proof) + BOOK_AGE)
        return expiry if at < expiry else None
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None


def credentials():
    try:
        value = json.loads(
            keychain_or_file(
                "prophetx-market-data.json",
                "prediction-arb.prophetx.market-data.production",
                "read-only",
            )
            or "{}"
        )
        if (
            set(value) != {"api_key", "tournaments"}
            or not isinstance(value["api_key"], str)
            or not value["api_key"]
        ):
            raise ValueError()
        if not isinstance(value["tournaments"], dict) or any(
            league not in TOURNAMENT_NAMES or _numeric_id(tid) is None
            for league, tid in value["tournaments"].items()
        ):
            raise ValueError()
        return dict(value, tournaments=DOCUMENTED_TOURNAMENTS | value["tournaments"])
    except Exception:
        raise ValueError(
            "prophetx_production_affiliate_key_and_tournament_ids_required"
        ) from None


class MarketData:
    def __init__(
        self,
        config,
        *,
        now,
        allowed,
        http=None,
        requests=10000,
        bytes_limit=256 * 1024 * 1024,
    ):
        self.config, self.now, self.allowed = config, now, allowed
        self.http = http or httpx.AsyncClient(
            timeout=3, follow_redirects=False, trust_env=False
        )
        self.request_limit, self.byte_limit = requests, bytes_limit
        self.remaining, self.bytes = requests, bytes_limit
        self.blocked_until = self.window_start = now()
        self.event_cache = {}
        self.inflight = {}
        self.tournament_catalog = None

    async def close(self):
        pending = tuple(self.inflight.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.http.aclose()

    async def get(self, path, params, cutoff):
        if path not in PATHS:
            raise ValueError("prophetx_read_only_endpoint_required")
        if (
            not self.allowed()
            or self.now() >= cutoff
            or self.now() < self.blocked_until
        ):
            return None, None, "deferred"
        key = path, tuple(sorted(params.items()))
        task = self.inflight.get(key)
        if task is None and path == MARKETS:
            # A protected consumer looking for one exact event can use the
            # original concurrent catalog refresh if it covers that event.
            ids = set(params["event_ids"].split(","))
            options = {k: v for k, v in params.items() if k != "event_ids"}
            for (route, query), pending in self.inflight.items():
                if route != path or pending.done():
                    continue
                batch = dict(query)
                covered = set(batch.pop("event_ids").split(","))
                if options == batch and ids <= covered:
                    task = pending
                    break
        if task is None:
            if not self.inflight and self.now() >= self.window_start + timedelta(
                hours=1
            ):
                self.window_start = self.now()
                self.remaining, self.bytes = self.request_limit, self.byte_limit
            task = asyncio.create_task(self._get(path, params, cutoff))
            self.inflight[key] = task

            def forget(done):
                if self.inflight.get(key) is done:
                    self.inflight.pop(key, None)

            task.add_done_callback(forget)
        try:
            async with asyncio.timeout(max(0, (cutoff - self.now()).total_seconds())):
                data, proof, reason = await asyncio.shield(task)
        except TimeoutError:
            return None, None, "deferred"
        if not self.allowed() or proof and stamp(proof["received_at"]) > cutoff:
            return None, None, "deferred"
        return data, proof, reason

    async def _get(self, path, params, cutoff):
        if (
            not self.allowed()
            or self.now() >= cutoff
            or self.now() < self.blocked_until
        ):
            return None, None, "deferred"
        if self.remaining <= 0 or self.bytes <= 0:
            return None, None, "prophetx_request_budget"
        sent = self.now()
        self.remaining -= 1
        try:
            async with (
                asyncio.timeout(3),
                self.http.stream(
                    "GET",
                    HOST + path,
                    params=params,
                    headers={"Authorization": self.config["api_key"]},
                    timeout=3,
                ) as response,
            ):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    self.bytes -= len(chunk)
                    body.extend(chunk)
                    if len(body) > 3 * 1024 * 1024 or self.bytes < 0:
                        return None, None, "prophetx_response_capacity"
                received = self.now()
                proof = dict(
                    path=path,
                    source_url=HOST + path,
                    status=response.status_code,
                    requested_at=sent.isoformat(),
                    received_at=received.isoformat(),
                    sha256=sha256(body).hexdigest(),
                    date=response.headers.get("date"),
                    age=response.headers.get("age", "0"),
                )
                if response.status_code == 429:
                    retry = response.headers.get("retry-after", "60")
                    try:
                        until = received + timedelta(seconds=max(1, int(retry)))
                    except ValueError:
                        try:
                            until = stamp(parsedate_to_datetime(retry))
                        except (TypeError, ValueError):
                            until = received + timedelta(seconds=60)
                    self.blocked_until = max(self.blocked_until, until)
                    return None, proof, "throttled"
                if response.status_code in (401, 403):
                    self.blocked_until = received + timedelta(minutes=5)
                    return None, proof, "prophetx_market_data_entitlement_denied"
                if response.status_code != 200:
                    return None, proof, "prophetx_unavailable"
                if self.config["api_key"].encode() in body:
                    return None, None, "prophetx_invalid_response"
                return json.loads(body, parse_float=Decimal)["data"], proof, None
        except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError):
            return None, None, "prophetx_unavailable"

    async def qualify_tournament(self, league, cutoff):
        mapping = self.config["tournaments"]
        tid = _numeric_id(mapping.get(league))
        if tid is None:
            return None, "prophetx_tournament_mapping_required"
        if TOURNAMENT_LEAGUES.get(tid, league) != league:
            return None, "prophetx_tournament_league_conflict"
        if any(
            other != league and _numeric_id(value) == tid
            for other, value in mapping.items()
        ):
            return None, "prophetx_tournament_mapping_duplicate"
        catalog = self.tournament_catalog
        if not catalog or self.now() - stamp(catalog[1]["received_at"]) >= timedelta(
            hours=1
        ):
            data, proof, reason = await self.get(TOURNAMENTS, {}, cutoff)
            if reason:
                return None, reason
            tournaments = data.get("tournaments") if isinstance(data, dict) else None
            if not isinstance(tournaments, list):
                return None, "prophetx_tournament_catalog_unverified"
            self.tournament_catalog = catalog = tournaments, proof
        tournaments, proof = catalog
        if stamp(proof["received_at"]) > min(self.now(), cutoff):
            return None, "deferred"
        matches = [
            row
            for row in tournaments
            if isinstance(row, dict) and _numeric_id(row.get("id")) == tid
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("name"), str):
            return None, "prophetx_tournament_id_not_verified"
        name = re.sub(r"[^a-z0-9]", "", matches[0]["name"].casefold())
        if name not in TOURNAMENT_NAMES[league]:
            return None, "prophetx_tournament_league_conflict"
        return dict(proof, tournament_id=tid, tournament_name=matches[0]["name"]), None

    async def discover(self, league, start, end, cutoff):
        tournament, reason = await self.qualify_tournament(league, cutoff)
        if reason:
            return {}, reason
        tid = tournament["tournament_id"]
        events, proof, reason = await self.get(EVENTS, {"tournament_id": tid}, cutoff)
        if reason:
            return {}, reason
        listed = events.get("sport_events") if isinstance(events, dict) else None
        if not isinstance(listed, list):
            return {}, "prophetx_event_catalog_unverified"
        for event in listed:
            self._remember_event(event, proof, league, tournament, window=(start, end))
        self.event_cache = {
            eid: event
            for eid, event in self.event_cache.items()
            if self.now()
            < stamp(event["scheduled_start"])
            <= self.now() + timedelta(hours=24)
        }
        return await self.refresh(
            (
                eid
                for eid, event in self.event_cache.items()
                if event["competition"] == league
                and start <= stamp(event["scheduled_start"]) < end
            ),
            cutoff,
        )

    def _remember_event(self, event, proof, league, tournament, *, window=None):
        try:
            eid = _numeric_id(event["event_id"])
            tid = event.get("tournament_id")
            if (
                not eid
                or tid is not None
                and _numeric_id(tid) != tournament["tournament_id"]
            ):
                return
            prior = self.event_cache.get(eid)
            observed = _origin(proof)
            if prior and (
                prior["competition"] != league
                or _origin(prior["native_role_evidence"]) > observed
            ):
                return
            starts = stamp(event["scheduled"])
            if event.get("status") != "scheduled" or starts <= self.now():
                self.event_cache.pop(eid, None)
                return
            if (
                prior is None
                and window is not None
                and not window[0] <= starts < window[1]
            ):
                return
            teams = {t["side"]: t for t in event["competitors"]}
            ids = {_numeric_id(t.get("id")) for t in teams.values()}
            if (
                set(teams) != {"home", "away"}
                or len(teams) != len(event["competitors"])
                or len(ids) != 2
                or None in ids
            ):
                return
            labels = {side: t["name"] for side, t in teams.items()}
            roles = {
                side: resolve_team(t, league, "prophetx")
                or "prophetx:team:" + _numeric_id(t["id"])
                for side, t in teams.items()
            }
            self.event_cache[eid] = native_event(
                "prophetx",
                eid,
                league,
                starts,
                roles,
                labels,
                proof=dict(
                    proof,
                    competitors=teams,
                    tournament=tournament,
                    event_status=event["status"],
                    event_id=eid,
                    scheduled_start=starts.isoformat(),
                ),
            )
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
            return

    async def _refresh_phase(self, selected, cutoff):
        pending = {
            eid: self.event_cache[eid]
            for eid in selected
            if eid in self.event_cache
            and not _phase_expiry(self.event_cache[eid], self.now())
        }
        if not pending:
            return
        data, proof, reason = await self.get(
            EVENTS, {"event_ids": ",".join(pending)}, cutoff
        )
        listed = data.get("sport_events") if isinstance(data, dict) else None
        if reason or not isinstance(listed, list):
            return
        for event in listed:
            eid = (
                _numeric_id(event.get("event_id")) if isinstance(event, dict) else None
            )
            if eid in pending:
                old = pending[eid]
                self._remember_event(
                    event,
                    proof,
                    old["competition"],
                    old["native_role_evidence"]["tournament"],
                )

    async def refresh(self, event_ids, cutoff):
        """Reuse current event status, refreshing it alongside depth when it expires."""
        output = {}
        observed_strikes, conflicts = {}, set()
        identity_gap = None
        ids = sorted(
            {
                eid
                for eid in event_ids
                if eid in self.event_cache
                and self.now() < stamp(self.event_cache[eid]["scheduled_start"])
            }
        )
        for offset in range(0, len(ids), 65):
            selected = ids[offset : offset + 65]
            market_read = self.get(
                MARKETS,
                dict(
                    event_ids=",".join(selected),
                    market_types="moneyline,spread,total",
                    get_all_market="true",
                ),
                cutoff,
            )
            (data, receipt, reason), _ = await asyncio.gather(
                market_read, self._refresh_phase(selected, cutoff)
            )
            if reason:
                identity_gap = reason
                break
            if not isinstance(data, dict):
                identity_gap = "prophetx_market_membership_unverified"
                break
            for eid in selected:
                if eid not in self.event_cache:
                    continue
                markets = data.get(eid, [])
                if not isinstance(markets, list):
                    continue
                for market in markets:
                    try:
                        books = bindings(
                            self.event_cache[eid], market, receipt, at=self.now()
                        )
                    except ValueError as exc:
                        if str(exc) in (
                            "prophetx_market_identity_conflict",
                            "prophetx_outcome_identity_unverified",
                            "prophetx_outcome_identity_conflict",
                            "prophetx_strike_identity_conflict",
                        ):
                            identity_gap = str(exc)
                        continue
                    except (ArithmeticError, AttributeError, KeyError, TypeError):
                        continue
                    for cid, book in books.items():
                        strike = book["native_strike_id"]
                        if (
                            observed_strikes.setdefault(strike, cid) != cid
                            or cid in output
                            and output[cid] != book
                        ):
                            conflicts.add(strike)
                        output[cid] = book
        if conflicts:
            output = {
                cid: book
                for cid, book in output.items()
                if book["native_strike_id"] not in conflicts
            }
            identity_gap = "prophetx_strike_identity_conflict"
        return output, identity_gap


def bindings(event, market, receipt, *, at):
    family = market.get("type")
    if (
        family not in ("moneyline", "spread", "total")
        or market.get("sub_type") != family
        or market.get("category_name") != "Game Lines"
    ):
        return {}
    # An independently documented HTTP origin dates this image. Integer native
    # timestamps remain raw until their field-specific units are established.
    expiry = min(stamp(event["scheduled_start"]), _origin(receipt) + BOOK_AGE)
    if not stamp(receipt["received_at"]) <= at < expiry:
        return {}
    event_id = _numeric_id(event["id"])
    market_id = _numeric_id(market.get("id"))
    if not event_id or not market_id or not _market_scope(market, event_id, market_id):
        raise ValueError("prophetx_market_identity_conflict")
    phase_until = _phase_expiry(event, at)
    eligible_phase = (
        phase_until
        and market.get("status") in (None, "active", "open")
        and not market.get("is_live")
    )
    if eligible_phase:
        expiry = min(expiry, phase_until)
    result = {}
    outcome_sides, side_strikes, strikes = {}, {}, {}
    for group in market["selections"]:
        for selection in group:
            sid = selection.get("strike_id")
            oid = _numeric_id(selection.get("outcome_id"))
            if (
                not oid
                or not isinstance(sid, str)
                or not re.fullmatch(r"[0-9a-fA-F]{32}", sid)
            ):
                raise ValueError("prophetx_outcome_identity_unverified")
            if not _market_scope(selection, event_id, market_id):
                raise ValueError("prophetx_market_identity_conflict")
            if family == "total":
                side = selection["name"].casefold()
                if selection.get("competitor_id") is not None:
                    raise ValueError("prophetx_outcome_identity_conflict")
            else:
                # Native competitor IDs and independently observed event roles
                # outrank display names. No substring or positional matching.
                teams = event["native_role_evidence"]["competitors"]
                competitor = _numeric_id(selection.get("competitor_id"))
                if not competitor:
                    raise ValueError("prophetx_outcome_identity_unverified")
                side = next(
                    (s for s, t in teams.items() if _numeric_id(t["id"]) == competitor),
                    None,
                )
            if side not in (
                ("over", "under") if family == "total" else ("home", "away")
            ):
                raise ValueError("prophetx_outcome_identity_unverified")
            line = None if family == "moneyline" else str(F(selection["strike"]))
            if strikes.setdefault(sid, (oid, side, line)) != (oid, side, line):
                raise ValueError("prophetx_strike_identity_conflict")
            if outcome_sides.setdefault(oid, side) != side or side_strikes.setdefault(
                (side, line), (oid, sid)
            ) != (oid, sid):
                raise ValueError("prophetx_outcome_identity_conflict")
            settle = dict(
                available=False,
                reason="prophetx_exact_settlement_unverified",
                evidence={"source_url": SOURCE},
            )
            row = record(
                "prophetx",
                event,
                market_id,
                sid,
                "buy",
                family,
                side,
                line,
                settlement=settle,
            )
            row["quote"]["source"].update(native_strike_id=sid, provider_outcome_id=oid)
            exact = expected(row)
            price = F(american_probability(str(selection["price"])))
            quantity = F(selection["quantity"])
            if not 0 < price < 1 or quantity <= 0:
                continue
            levels = [
                dict(price=wire_fraction(price), quantity=wire_fraction(quantity))
            ]
            prior = result.get(exact["contract_id"])
            if prior:
                duplicate = next(
                    (level for level in prior["levels"] if F(level["price"]) == price),
                    None,
                )
                if duplicate:
                    if F(duplicate["quantity"]) != quantity:
                        raise ValueError("prophetx_duplicate_level_conflict")
                else:
                    prior["levels"].extend(levels)
                    prior["levels"].sort(key=lambda level: F(level["price"]))
                    prior["legal_prices"] = [
                        level["price"] for level in prior["levels"]
                    ]
                continue
            result[exact["contract_id"]] = dict(
                venue="prophetx",
                event_id=event["id"],
                market_id=market_id,
                outcome_id=sid,
                native_side="buy",
                contract=dict(
                    exact,
                    phase="pregame" if eligible_phase else "unverified",
                    settlement=settle,
                ),
                native_outcome_id=int(oid),
                native_strike_id=sid,
                native_price=str(selection["price"]),
                native_quantity=str(selection["quantity"]),
                **{
                    field: str(selection[field])
                    for field in ("adjusted_maker_price", "adjusted_taker_price")
                    if selection.get(field) is not None
                },
                quantity_unit="usd_stake",
                quantity_increment=".01",
                quantity_minimum="1",
                payout_usd="1",
                legal_prices=[wire_fraction(price)],
                levels=levels,
                complete=False,
                reason=None,
                fee=dict(reason="prophetx_exact_fee_schedule_unverified"),
                market_revision=hashed(json.loads(json.dumps(market, default=str))),
                received_at=receipt["received_at"],
                valid_until=expiry.isoformat(),
                receipts=[receipt],
                identity_receipts=[event["native_role_evidence"]],
                _record=row,
            )
    return result


def _market_scope(value, event_id, market_id):
    return all(
        field not in value or _numeric_id(value[field]) == expected
        for field, expected in (
            ("event_id", event_id),
            ("sport_event_id", event_id),
            ("market_id", market_id),
        )
    )


def wire_fraction(value):
    return str(value)
