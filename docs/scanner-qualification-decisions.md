# SC02 qualification decisions

All vectors are explicitly authored. The portable inputs are `tests/fixtures/sc02-financial-vectors.json`; `tests/test_sc02_finance.py` also reconciles the existing cashflow/fee owners independently. None establish a current live opportunity.

| Inputs/result | Covered-outcome arb | Conditional/EV handling | Coverage meaning |
| --- | --- | --- | --- |
| Distinct exact current execution venues; every required cashflow known; complete minimum after costs and one buffer positive | Candidate | Separate EV only with its own reference/partition meaning | Evaluated positive |
| Decisive +$3/+$2; tie -$10; capital $100; 0.5% buffer | Refused; complete minimum -$10.50 | Conditional decisive hedge | Required known state retained regardless of p=0 |
| Complete profits +$3/+$2/+$1 and neutral refund $0; capital $100 | Refused; buffered minimum -$0.50 | Conditional hedge | Returned capital is not profit |
| Cancellation refunds both principals but costs $2; asymmetric grade loses $42 on $102 capital | Refused; buffered minimum -$42.51 | Conditional scenarios retained | No cancellation suppression |
| Unknown mandatory settlement/cost or unknown joint completion meaning | Refused | Known decisive scenarios may remain conditional; EV conditioning stays explicit | Incomplete, never authoritative zero |
| All profits $0.50 on $100; 0.5% buffer | Refused; exact zero | No positive hedge from zero | Exactly one buffer, strict positivity |
| All profits negative | Refused | Negative EV may be inspected separately | Evaluated zero only with complete evaluation |
| Positive expectation but feasible zero-probability loss | Refused | EV and conditional hedge remain independent | p=0 never removes a state |
| Missing/stale optional Pinnacle/probability input; independently current mandatory cashflows | Still eligible for cashflow evaluation | EV absent or last-known/conditional | Optional reference cannot block arb |
| Expired execution/fee/payout/identity/quantity model, unknown grid, unsupported Short collateral | Refused before finance | No current candidate | Unavailable/unsupported; dates unchanged |
| Observed depth supports a smaller legal allocation than default $1,000 | Evaluate the smaller allocation | Supply deployed capital, quantity and observed size basis | No mandatory full deployment |
| Insufficient observed depth or duplicate/shared fill | No supported candidate from that allocation | No hypothetical residual promoted | Existing grid/exposure constraints retained |
| Bounded allocation search nonqualifying without exhausting legal grid | No positive proven | Conditional rows can remain labeled | `bounded_size_search_incomplete`; no authoritative zero |
| Complete checked selected pair set, no supported qualifying allocation and exhaustive search | No rows in arb category | Other categories separate | `evaluated_zero` and scoped no-qualifying flag |
| No pairs, no ready pairs, pending work, failed/unsupported scope, capacity failure | No current arb claim | Inspectable reasons/partial rows | Distinct unavailable/not-evaluated/partial/incomplete |

A further independent complete positive owner vector deploys $50 per leg, returns $52 per leg in every required authored state, applies an independently charged 10% net-gain settlement fee of $0.20 per leg, then one $0.50 buffer. Complete minimum is $3.10, or 3.10% of $100. This is an authored cashflow oracle, not a claim that a venue currently offers those terms.
