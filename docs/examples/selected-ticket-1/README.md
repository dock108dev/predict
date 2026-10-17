# Authored selected-ticket v1 examples

These are explicit authored native inputs, depth, supported grading assumptions and invented destination route fixtures. They demonstrate the implemented protocol and financial arithmetic; they do not qualify current venues, links, sources, installation or owner acceptance.

`binding.json` returns the complete selection. `command.json` opens it. `selected.json` holds the first coherent requested calculation; `unchanged.json` preserves its original clocks. `amount_revised.json` keeps the previous frame while proposing a $40 replacement; `adopted.json` explicitly adopts it. `stopped.json` removes action authority while retaining inspectable old arithmetic. Exact native actions, funding, state cashflows, source/model identities and one buffer remain in each frame. The examples use conditional hedges: neutral refunds after a modeled buffer cannot claim positive complete minimum.

Use the [ticket contract](../../scanner-ticket-contract.md), [response schema](../../contracts/predict-selected-ticket-1.schema.json), [command schema](../../contracts/predict-ticket-command-1.schema.json) and [selection schema](../../contracts/predict-ticket-selection-1.schema.json). Consumers use top-level readiness/state; an old frame's historical `ready` flag never authorizes present action.
