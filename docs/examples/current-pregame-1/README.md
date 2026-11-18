# Current pregame response example

`positive-board.json` is an authored synthetic response, not a live opportunity.
The $100 internal comparison commits $100 on a +120 posted price with a 2%
winning-gains commission: $2.40 fee, $217.60 winning receipt, +8.80% Net EV at
fair probability 0.5. All timestamps and identities are fixture values.

Read with `GET /api/pregame`. Compare the exact bet with
`GET /api/pregame?bet_id=exact-home-spread&lines=all`.
A cheap `GET /api/pregame/updates?after=<cursor>` reports whether to reread.
There are no unit-size or calculation-mode parameters and no partial rows.
See the [current contract](../../current-pregame.md).
