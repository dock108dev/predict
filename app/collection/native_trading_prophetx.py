"""Read-only ProphetX affiliate data; never authenticate a trading session."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from fractions import Fraction as F
from hashlib import sha256

import httpx

from app.comparison.sgo_reference import american_probability
from app.storage.store import hashed, stamp

from .admission_enrichment import resolve_team
from .native_trading_identity import native_event, record, expected
from .service_secrets import keychain_or_file

HOST = "https://cash.api.prophetx.co/partner"
PATHS = frozenset(
    (
        "/affiliate/get_tournaments",
        "/affiliate/get_sport_events",
        "/v4/affiliate/get_multiple_markets",
    )
)
SOURCE = "https://docs.prophetx.co/docs/market-data-integration"


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
        if (
            not isinstance(value["tournaments"], dict)
            or not value["tournaments"]
            or any(
                league not in ("NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL")
                or not str(tid).isdigit()
                for league, tid in value["tournaments"].items()
            )
        ):
            raise ValueError()
        return value
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
        if task is None:
            if not self.inflight and self.now() >= self.window_start + timedelta(hours=1):
                self.window_start = self.now()
                self.remaining, self.bytes = self.request_limit, self.byte_limit
            task = asyncio.create_task(self._get(path, params, cutoff))
            self.inflight[key] = task

            def forget(done):
                if self.inflight.get(key) is done:
                    self.inflight.pop(key, None)

            task.add_done_callback(forget)
        data, proof, reason = await asyncio.shield(task)
        if proof and stamp(proof['received_at']) > cutoff:
            return None, None, 'deferred'
        return data, proof, reason

    async def _get(self, path, params, cutoff):
        if not self.allowed() or self.now() >= cutoff or self.now() < self.blocked_until:
            return None, None, 'deferred'
        if self.remaining <= 0 or self.bytes <= 0:
            return None, None, "prophetx_request_budget"
        sent = self.now()
        self.remaining -= 1
        try:
            async with self.http.stream(
                "GET",
                HOST + path,
                params=params,
                headers={"Authorization": self.config["api_key"]},
                timeout=min(3, (cutoff - sent).total_seconds()),
            ) as response:
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
                if response.status_code != 200 or received > cutoff:
                    return None, proof, "prophetx_unavailable"
                if self.config["api_key"].encode() in body:
                    return None, None, "prophetx_invalid_response"
                return json.loads(body, parse_float=Decimal)["data"], proof, None
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None, None, "prophetx_unavailable"

    async def discover(self, league, start, end, cutoff):
        tid = self.config["tournaments"].get(league)
        if tid is None:
            return {}, "prophetx_tournament_mapping_required"
        events, proof, reason = await self.get(
            "/affiliate/get_sport_events", {"tournament_id": tid}, cutoff
        )
        if reason:
            return {}, reason
        for event in events["sport_events"]:
            if (
                event.get("status") != "scheduled"
                or not start <= stamp(event["scheduled"]) < end
            ):
                continue
            teams = {t["side"]: t for t in event["competitors"]}
            if set(teams) != {"home", "away"} or len(teams) != len(
                event["competitors"]
            ):
                continue
            labels = {side: t["name"] for side, t in teams.items()}
            roles = {
                side: resolve_team(t, league, "prophetx")
                or "prophetx:team:" + str(t["id"])
                for side, t in teams.items()
            }
            eid = str(event["event_id"])
            native = native_event(
                "prophetx",
                eid,
                league,
                event["scheduled"],
                roles,
                labels,
                proof=dict(proof, competitors=teams),
            )
            self.event_cache[eid] = native
        self.event_cache = {
            eid: event
            for eid, event in self.event_cache.items()
            if self.now()
            < stamp(event["scheduled_start"])
            <= self.now() + timedelta(hours=24)
        }
        return await self.refresh(
            (eid for eid, event in self.event_cache.items() if event["competition"] == league
             and start <= stamp(event["scheduled_start"]) < end),
            cutoff,
        )

    async def refresh(self, event_ids, cutoff):
        """Refresh exact depth for discovered events without another schedule read."""
        output = {}
        ids = sorted({eid for eid in event_ids if eid in self.event_cache
                      and self.now() < stamp(self.event_cache[eid]["scheduled_start"])})
        for offset in range(0, len(ids), 65):
            selected = ids[offset : offset + 65]
            data, receipt, reason = await self.get(
                "/v4/affiliate/get_multiple_markets",
                dict(
                    event_ids=",".join(selected),
                    market_types="moneyline,spread,total",
                    get_all_market="true",
                ),
                cutoff,
            )
            if reason:
                return output, reason
            if not isinstance(data, dict):
                return output, "prophetx_market_membership_unverified"
            for eid in selected:
                for market in data.get(eid, []):
                    try:
                        output.update(
                            bindings(
                                self.event_cache[eid], market, receipt, at=self.now()
                            )
                        )
                    except (ArithmeticError, KeyError, TypeError, ValueError):
                        continue
        return output, None


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
    origin = min(
        stamp(parsedate_to_datetime(receipt["date"])),
        stamp(receipt["received_at"]) - timedelta(seconds=int(receipt.get("age", "0"))),
    )
    expiry = min(stamp(event["scheduled_start"]), origin + timedelta(seconds=30))
    if not stamp(receipt["received_at"]) <= at < expiry:
        return {}
    result = {}
    for group in market["selections"]:
        for selection in group:
            if family == "total":
                side = selection["name"].casefold()
            else:
                # Native competitor IDs and independently observed event roles
                # outrank display names. No substring or positional matching.
                teams = event["native_role_evidence"]["competitors"]
                side = next(
                    (
                        s
                        for s, t in teams.items()
                        if str(t["id"]) == str(selection.get("competitor_id"))
                    ),
                    None,
                )
            if side not in (
                ("over", "under") if family == "total" else ("home", "away")
            ):
                continue
            line = None if family == "moneyline" else str(F(selection["strike"]))
            sid = str(selection["strike_id"])
            settle = dict(
                available=False,
                reason="prophetx_exact_settlement_unverified",
                evidence={"source_url": SOURCE},
            )
            row = record(
                "prophetx",
                event,
                str(market["id"]),
                sid,
                "buy",
                family,
                side,
                line,
                settlement=settle,
            )
            row["quote"]["source"].update(
                native_strike_id=sid, provider_outcome_id=str(selection["outcome_id"])
            )
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
                if (
                    prior["contract"]["selected_side"] != side
                    or prior["contract"]["signed_line"] != line
                ):
                    raise ValueError("prophetx_strike_identity_conflict")
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
                market_id=str(market["id"]),
                outcome_id=sid,
                native_side="buy",
                contract=dict(exact, phase="pregame", settlement=settle),
                native_outcome_id=selection["outcome_id"],
                native_strike_id=sid,
                native_price=str(selection["price"]),
                native_quantity=str(selection["quantity"]),
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


def wire_fraction(value):
    return str(value)
