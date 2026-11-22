"""Portable verified archive records feed general research without future data."""

from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.collection.sportsgameodds_current_rows import current_rows
from app.research.archive import from_changes
from app.research.calculation import freeze, reproduce
from app.storage.odds_archive import sgo_quote
from app.storage.sportsgameodds_reference import prepare_page
from app.storage.store import hashed
from tests.pregame_fixture import AT, page, parse


def archive_inputs():
    parsed = parse(page())
    normalized = current_rows(parsed, parsed.receipt_sha256)[0][0]
    event = normalized["event"]
    case = dict(case_key="retained-spread", event_id="canonical-event", starts_at=event["scheduled_start"],
        family="spread", period="full_game", line="-1.5", home=event["home"], away=event["away"],
        league=event["competition"], source_event_ids=["event"])
    refs = prepare_page(parsed)
    changes = [[row["id"], *row["body"]] for ref in refs for row in sgo_quote(ref)]
    return case, refs, changes


def test_receipt_cutoff_archive_pair_reproduces_with_no_fees_or_depth_invented():
    case, refs, changes = archive_inputs()
    replay = from_changes(changes, event_id="event", case=case, as_of=AT)
    payload = replay["payload"]
    assert payload["coherent_probability"]["book"] == "fanduel"
    assert F(reproduce(freeze(payload))["probability"]) == F(1, 2)
    assert reproduce(freeze(payload))["net_ev"] is None
    assert payload["replay"]["original_knowledge_cutoff"] is None
    assert payload["replay"]["freshness"] == "not_established"
    assert payload["replay"]["verified_input_change_ids"]
    assert replay["provider_requests"] == 0
    input_ids = {q["input_id"] for q in payload["coherent_probability"]["prices"]}
    assert input_ids <= {row["id"] for row in refs}


def test_later_receipt_cannot_replace_earlier_reference():
    case, refs, changes = archive_inputs()
    late = deepcopy(next(r for r in refs if r["facts"]["venue"] == "fanduel" and r["facts"]["side"] == "home"))
    late["facts"].update(source_at="2026-11-17T20:01:00Z", received_at="2026-11-17T20:02:00Z", price_american="+200")
    late["revision"] = hashed(late["facts"])
    future = [[row["id"], *row["body"]] for row in sgo_quote(late)]
    original = from_changes(changes + future, event_id="event", case=case, as_of=AT)
    later = from_changes(changes + future, event_id="event", case=case, as_of="2026-11-17T20:03:00Z")
    assert F(original["payload"]["coherent_probability"]["probability"]) == F(1, 2)
    assert F(later["payload"]["coherent_probability"]["probability"]) != F(1, 2)


def test_wrong_occurrence_roles_or_modified_archive_cannot_score():
    case, refs, changes = archive_inputs()
    wrong = dict(case, home=case["away"], away=case["home"])
    with pytest.raises(ValueError, match="participant_roles_conflict"):
        from_changes(changes, event_id="event", case=wrong, as_of=AT)
    corrupt = deepcopy(changes)
    corrupt[0][8] = "changed"
    with pytest.raises(ValueError, match="integrity"):
        from_changes(corrupt, event_id="event", case=case, as_of=AT)
