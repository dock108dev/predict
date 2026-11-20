"""Disposable journal HTTP fixture shared by browser feature tests."""

from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_tests.test_pregame_current import offer

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


class JournalUI:
    """Normal browser requests backed by a disposable, real personal journal."""

    def __init__(self, path, quote):
        from app.dashboard.bet_journal import Journal

        self.journal = Journal(path)
        self.quote = quote
        self.updates, self.reads, self.previews = [], [], []
        self.list_packets, self.detail_reads = [], []
        self.conflict = self.fail_save = False

    def serve(self, route):
        from app.dashboard.bet_journal import Conflict

        request, url = route.request, urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/bet-journal":
            if request.method == "POST":
                body = request.post_data_json
                key = self.journal.observe(body["kind"], body["snapshot"], manual=True)
                route.fulfill(status=201, json=self.journal.get(key))
            else:
                self.reads.append(q)
                options = dict(q)
                if "defer_observed" in options:
                    options["defer_observed"] = options["defer_observed"] == "1"
                packet = self.journal.list(**options)
                self.list_packets.append(deepcopy(packet))
                route.fulfill(json=packet)
        elif url.path.endswith("/preview") and url.path.startswith("/api/bet-journal/"):
            key = url.path.split("/")[-2]
            self.previews.append(deepcopy(request.post_data_json))
            try:
                result = self.journal.preview(key, request.post_data_json)
            except ValueError as error:
                route.fulfill(status=400, json=dict(message=str(error)))
            else:
                route.fulfill(json=result)
        elif url.path.startswith("/api/bet-journal/"):
            key = url.path.rsplit("/", 1)[-1]
            if request.method == "POST":
                changes = request.post_data_json
                self.updates.append(deepcopy(changes))
                if self.conflict:
                    route.fulfill(status=409, json=dict(error="revision_conflict"))
                elif self.fail_save:
                    route.fulfill(
                        status=503,
                        json=dict(error="Stored changes unavailable; retry."),
                    )
                else:
                    try:
                        result = self.journal.update(key, changes)
                    except Conflict:
                        route.fulfill(status=409, json=dict(error="revision_conflict"))
                    except ValueError as error:
                        route.fulfill(status=400, json=dict(message=str(error)))
                    else:
                        route.fulfill(json=result)
            else:
                self.detail_reads.append(key)
                route.fulfill(json=self.journal.get(key, history=True))
        elif url.path.startswith("/api/pregame"):
            route.fulfill(
                json=dict(
                    rows=[deepcopy(self.quote)],
                    total=1,
                    cursor="one",
                    sportsbooks=[],
                    refresh_at=self.quote["kickoff"],
                    changed=False,
                )
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(
                path=ASSETS
                / ("bet-journal.html" if url.path == "/my-bets" else "pregame.html")
            )


def prophetx_quote():
    from tests.test_fee_pricing import rule

    quote = offer()
    quote["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    quote["fee"]["evidence"] = dict(database_fee_rule=rule("prophetx"))
    return quote


def journal_arb():
    a = prophetx_quote()
    a["side"] = "home"
    b = deepcopy(a)
    b.update(
        id="book-leg",
        venue="draftkings",
        side="away",
        selection_label="Milwaukee Bucks",
    )
    b["selection"].update(participant="NBA:MIL", signed_line="1.5")
    b["posted"]["value"] = "+110"
    b["raw"].update(posted_decimal="2.1", after_fee_decimal="2.1")
    b["display"].update(posted_odds="+110", after_fees="+110")
    b["fee"].update(
        classification="sportsbook_no_placement_fee",
        entry_usd="0",
        evidence={},
        cashflows=dict(
            win=dict(total_fee_usd="0", net_receipt_usd="210"),
            loss=dict(total_fee_usd="0", net_receipt_usd="0"),
        ),
    )
    return dict(
        id="pair-journal",
        game=a["game"],
        league="NBA",
        kickoff=a["kickoff"],
        family="spread",
        return_rate=".05",
        legs=[a, b],
    )
