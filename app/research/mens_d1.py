"""Versioned men's Division I populations for opportunity-only paper analyses."""
from collections import Counter
from datetime import date, datetime, timezone

from app.storage.store import hashed
from . import experiment, paper

SCOPE = "mens-d1"
SCOPE_VERSION = "mens-d1-vs-d1-1"
DAILY = "mens-d1-daily"
RECOVERY = "retrospective_mens_d1_recovery"
DAILY_DESIGNATION = "mens_d1_daily"
RECONCILED = "mens_d1_reconciled_occurrences"
RETAINED = "mens_d1_retained_provider_snapshot"
ORIGINAL_RUN = "85dd517e0f454701f281c0ada636607d738f6ed5538a2801dc8ad00f69ed40bb"


def in_paper_cohort(row):
    return row["scope_state"] == "eligible" and row.get("paper_eligible", True)


def template(parent):
    return dict(parent, id=DAILY, version=DAILY, supersedes=parent["version"],
                title="Men’s D1 daily T−10 opportunities", designation=DAILY_DESIGNATION,
                question="Which paper opportunities qualify for verified men’s D1 versus D1 games on this Eastern date?",
                registration="Dated occurrence evidence establishes which games can be examined. The full slate may be unknown.",
                policy=dict(parent["policy"], scope=SCOPE, scope_version=SCOPE_VERSION, defer_results=True))


def definition(parent, population, designation, *, recovery=None):
    policy = dict(parent["policy"], scope=SCOPE, scope_version=SCOPE_VERSION, defer_results=True,
                  membership_version=population["membership_version"], population_revision=population["revision"],
                  population_kind=population["kind"])
    if recovery:
        policy.update(recovery)
    supersedes = parent["supersedes"] if parent["version"] == DAILY else parent["version"]
    body = dict(parent, version=hashed([parent["version"], designation, policy]), supersedes=supersedes,
                template_version=parent["version"], policy=policy, designation=designation)
    body.pop("recorded_at", None)
    if designation == RECOVERY:
        body.update(id=hashed([ORIGINAL_RUN, SCOPE_VERSION]), title="2026-11-23 · Men’s D1 retrospective scope correction",
                    original_run_id=ORIGINAL_RUN,
                    registration="Corrects the population of the original retained opportunity run using season membership. "
                                 "The source-declared daily slate remains a separate population. "
                                 "Original captures and later reconstructions retain their original evidence and clocks.")
    elif designation == RETAINED:
        body.update(id=hashed([RETAINED, SCOPE_VERSION]), title="Men’s D1 retained odds-provider opportunities",
                    registration="Applies the paper policy to season-verified games observed by the odds provider. "
                                 "Source-declared coverage and cross-source matches remain separate.")
    return body


def retained_population(db, original):
    from app.normalization.mens_d1_membership import load_membership

    day = original["game_date"]
    membership = load_membership(day)
    games = original["payload"]["report"]["games"]
    schedules = experiment._closure(db, [game["schedule_id"] for game in games])
    rows = []
    for game in games:
        row = schedules[game["schedule_id"]]
        event = experiment._value(row, schedules)["event"]
        labels = event["title"].split(" at ", 1)
        teams = []
        for index, side in enumerate(("away", "home")):
            label = labels[index] if len(labels) == 2 else None
            evidence = membership.lookup(name=label, canonical_id=event[side])
            teams.append(dict(label=label, side=side, provider_team_id=event[side], **evidence))
        divisions = {team["division"] for team in teams}
        if event.get("league") != "NCAAB":
            state, reason = "unresolved", "provider_mens_league_unverified"
        elif "non_d1" in divisions:
            state, reason = "excluded", "at_least_one_participant_outside_mens_d1"
        elif divisions == {"d1"}:
            state, reason = "eligible", "both_participants_mens_d1"
        else:
            state, reason = "unresolved", "season_membership_unverified"
        rows.append(dict(game_id=game["game_id"], provider_event_id=event["source_event_id"], title=event["title"],
                         scope_state=state, scope_reason=reason, teams=teams))
    basis = dict(kind="retained_original_run", original_run_id=original["id"], source="sportsgameodds",
                 observed_at=experiment.clock(original["observed_at"]), membership_version=membership.version,
                 games=rows)
    return dict(basis, revision=hashed(basis))


def replay_retained(db, day, policy, population, original):
    """Recalculate only with the exact frozen/corrected checkpoints named by the saved run."""
    dispositions, tickets, gaps = [], [], Counter()
    eligible = {row["game_id"] for row in population["games"] if row["scope_state"] == "eligible"}
    for game in original["payload"]["report"]["games"]:
        if game["game_id"] not in eligible:
            continue
        entry = dict(game, outcome_id=None)
        if entry["status"] in ("captured", "reconstructed"):
            key = entry["checkpoint_id"]
            index = experiment._closure(db, [key])
            row = index[key]
            checkpoint = experiment._value(row, index)
            if row["game_id"] != entry["game_id"] or checkpoint["schedule_id"] != entry["schedule_id"]:
                raise ValueError("saved_checkpoint_binding_changed")
            checkpoint = dict(checkpoint, persisted_at=experiment.clock(row["recorded_at"]))
            found, excluded = paper.scoped_candidates(entry, checkpoint, policy)
            tickets.extend(found)
            gaps.update(excluded)
        dispositions.append(entry)
    return paper.assemble(day, datetime.now(timezone.utc).isoformat(), policy, dispositions, tickets, gaps,
                          evidence=True, population=population)


def daily_population(db, day):
    from app.storage.mens_d1_coverage import read_reconciled_population

    value = read_reconciled_population(db, date.fromisoformat(day))
    return dict(value, kind="reconciled_occurrences") if value and value["games"] else None


def retained_provider_population(db, day):
    from app.normalization.mens_d1_membership import load_membership
    from app.storage.mens_d1_coverage import _providers

    date_key = date.fromisoformat(day)
    at = datetime.now(timezone.utc)
    providers = _providers(db, date_key, at)
    if not providers:
        return None
    games = [dict(provider_event_id=key, title=event["title"], starts_at=event["starts_at"],
                  scope_state=event["retained_scope"]["state"], scope_reason=event["retained_scope"]["reason"],
                  teams=[dict(label=team["name"], **team["membership"]) for team in event["teams"]])
             for key, event in sorted(providers.items())]
    basis = dict(kind="retained_provider_snapshot", source="sportsgameodds", date=day,
                 membership_version=load_membership(date_key).version, games=games)
    return dict(basis, revision=hashed(basis),
                observed_at=max(event["observed_at"] for event in providers.values()))


def daily_recovery(db, day, population):
    """Admit earlier reconstructions only for still-exact reviewed match occurrences."""
    from .recovery import VERSION as RECOVERY_VERSION

    providers = [row["provider_event_id"] for row in population["games"]
                 if in_paper_cohort(row) and row.get("provider_event_id")]
    if not providers:
        return {}
    checkpoints = {row["game_id"]: row["id"] for row in db.execute("""SELECT DISTINCT ON (r.game_id) r.game_id,r.id
        FROM public.ev_experiment_record r JOIN public.ev_experiment_game g ON g.id=r.game_id
        JOIN public.ev_experiment_task t ON t.game_id=g.id AND t.checkpoint='late'
        WHERE g.provider='sportsgameodds' AND g.source_event_id=ANY(%s) AND g.late_id IS NULL
          AND r.kind='checkpoint' AND r.checkpoint='late' AND r.payload#>>'{summary,scope}'=%s
          AND r.payload#>>'{summary,source_kind}'='retrospective_raw_t10' AND r.payload#>>'{summary,version}'=%s
          AND r.payload#>>'{summary,schedule_id}'=g.schedule_id AND t.schedule_id=g.schedule_id
          AND t.state IN ('missed','refused','failed')
        ORDER BY r.game_id,r.payload#>>'{summary,received_at}' DESC,r.id""", (providers, SCOPE, RECOVERY_VERSION))}
    record = db.execute("""SELECT d.payload->'policy' policy, r.payload#>'{report,games}' games
        FROM public.research_workspace_run r JOIN public.research_workspace_definition d
        ON d.version=r.definition_version
        WHERE r.game_date=%s AND d.payload->>'designation'='retrospective_raw_recovery'
        ORDER BY r.observed_at DESC,r.id LIMIT 1""", (day,)).fetchone()
    if record:
        prior = {game["game_id"]: game for game in record["games"] if game["status"] == "reconstructed"}
        for row in db.execute("""SELECT id,schedule_id FROM public.ev_experiment_game
            WHERE provider='sportsgameodds' AND source_event_id=ANY(%s) AND id=ANY(%s) AND late_id IS NULL""",
            (providers, list(prior))):
            game = prior[row["id"]]
            if row["schedule_id"] == game["schedule_id"]:
                checkpoints.setdefault(row["id"], game["checkpoint_id"])
    if not checkpoints:
        return {}
    fees = "Original captures preserve their fee mode; reconstructed responses explicitly assume $0 fees."
    return dict(recovered_checkpoints=checkpoints, recovery_version=record["policy"]["recovery_version"] if record else RECOVERY_VERSION,
                fees=record["policy"]["fees"] if record else fees)


def main():
    import argparse
    from app.storage.store import connect, encoded
    from . import workspace

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--correct-original", action="store_true",
                       help="Save the retrospective scope correction of the original November 23 run.")
    modes.add_argument("--date", help="Save an opportunity analysis for a verified Eastern game date.")
    modes.add_argument("--retained-provider-date", help="Save a limited analysis of retained odds-provider observations.")
    args = parser.parse_args()
    with connect() as db:
        if args.correct_original:
            value = workspace.correct_mens_d1_recovery(db)
        elif args.retained_provider_date:
            value = workspace.save_mens_d1_provider_snapshot(db, workspace.game_day(args.retained_provider_date))
        else:
            value = workspace.replay(db, workspace.game_day(args.date), DAILY, {})
    print(encoded(dict(run=value["run"], population=value["report"]["population"],
                       provider_requests=0, orders_submitted=0)).decode())


if __name__ == "__main__":
    main()
