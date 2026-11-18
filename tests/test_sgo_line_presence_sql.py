"""Repeated complete scopes retire a line, never its game or a failed request."""

from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless

from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import PregameFixture, page, parse, AT
from app.storage.sportsgameodds_reference import prepare_page
from app.storage.sgo_line_presence import observe
from app.storage.store import stamp, exact_time
from app.storage.current_pregame import read


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class LinePresenceSQL(PregameFixture):
    async def test_complete_scope_grace_recovery_and_other_book_preservation(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            rows = prepare_page(parse(page()))
            observe(db, rows, include_alternates=True)
            target = next(r for r in rows if r["bookmaker_id"] == "prophetx")
            old = target["id"]
            db.execute(
                """UPDATE current_offer_storage SET sgo_quote_id=%s,sgo_quote_revision=%s,
              price_value=NULL,facts=facts#-'{original,value}' WHERE facts#>>'{source,provider}'='sportsgameodds'
              AND facts#>>'{source,native_outcome_id}'=%s AND facts->>'venue'='prophetx'""",
                (old, target["revision"], target["facts"]["odd_id"]),
            )
            moved = deepcopy(target)
            moved["id"] = "moved-line"
            moved["facts"]["line"] = "-2.5"

            def refresh(minutes, complete=True):
                row = deepcopy(moved)
                row["received_order"] = str(
                    exact_time((stamp(AT) + timedelta(minutes=minutes)).isoformat())
                )
                observe(db, [row], include_alternates=complete)

            refresh(1)
            self.assertFalse(
                db.execute(
                    "SELECT expired FROM sgo_line_presence WHERE quote_id=%s", (old,)
                ).fetchone()["expired"]
            )
            refresh(15)
            self.assertIsNotNone(
                db.execute(
                    "SELECT id FROM current_sgo_reference WHERE id=%s", (old,)
                ).fetchone()
            )
            refresh(16)
            self.assertIsNone(
                db.execute(
                    "SELECT id FROM current_sgo_reference WHERE id=%s", (old,)
                ).fetchone()
            )
            self.assertGreater(
                db.execute("SELECT count(*) n FROM current_event").fetchone()["n"], 0
            )
            self.assertTrue(
                all(
                    r["venue"] != "prophetx" or r["side"] != target["facts"]["side"]
                    for r in read(db, dict(browse="1", lines="all"), at=stamp(AT))[
                        "rows"
                    ]
                )
            )
            self.assertGreater(
                db.execute(
                    "SELECT count(*) n FROM current_sgo_reference WHERE bookmaker_id='fanduel'"
                ).fetchone()["n"],
                0,
            )
            # An older replay cannot resurrect an omitted quote.
            observe(db, [target], include_alternates=True)
            self.assertIsNone(
                db.execute(
                    "SELECT id FROM current_sgo_reference WHERE id=%s", (old,)
                ).fetchone()
            )
            returned = deepcopy(target)
            returned["received_order"] = str(
                exact_time((stamp(AT) + timedelta(minutes=17)).isoformat())
            )
            observe(db, [returned])
            self.assertIsNotNone(
                db.execute(
                    "SELECT id FROM current_sgo_reference WHERE id=%s", (old,)
                ).fetchone()
            )

    async def test_main_only_and_other_scopes_do_not_prove_alternate_absence(self):
        with self.connect() as db:
            self.ingest(db, page())
            rows = prepare_page(parse(page()))
            observe(db, rows)
            changed = deepcopy(rows[0])
            changed["id"] = "other"
            changed["received_order"] = str(
                exact_time((stamp(AT) + timedelta(hours=1)).isoformat())
            )
            observe(db, [changed], include_alternates=False)
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM sgo_line_presence WHERE expired OR missing_since IS NOT NULL"
                ).fetchone()["n"],
                0,
            )

    async def test_empty_complete_returned_game_scope_retires_book_quotes(self):
        with self.connect() as db:
            self.ingest(db, page())
            rows = prepare_page(parse(page()))
            observe(db, rows)
            event = rows[0]["event_id"]
            for minutes in (1, 16):
                observe(
                    db,
                    [],
                    include_alternates=True,
                    events=[event],
                    received_at=(stamp(AT) + timedelta(minutes=minutes)).isoformat(),
                )
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_sgo_reference").fetchone()[
                    "n"
                ],
                2,  # Legacy fixture prophetx is outside the requested prophetexchange scope.
            )
            self.assertTrue(
                all(
                    r["bookmaker_id"] == "prophetx"
                    for r in db.execute(
                        "SELECT bookmaker_id FROM current_sgo_reference"
                    )
                )
            )
            self.assertGreater(
                db.execute("SELECT count(*) n FROM current_event").fetchone()["n"], 0
            )
