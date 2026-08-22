---
name: enteland-optimizer
description: Plan and validate Age of Enteland runs (Entelect hackathon). Use whenever the task involves the Enteland level files in levels/, the actions.txt submission, tick budgets, routing between towns and nodes, gather-vs-buy decisions, crafting and hauling, upgrade build order, tools, upkeep timing, or scoring. Wraps a deterministic simulator plus OR-Tools CP-SAT and routing solvers.
---

# Enteland optimizer

Route planning and resource allocation for *Age of Enteland*. Two halves:

- **Routing** — the map is a weighted graph; some pairs also have a tolled fast route.
- **Allocation** — one tick budget must be split across travel, gather, buy,
  craft, sell, build and upkeep. Every gain in Enteloot costs ticks.

## Environment

Solvers live in the repo venv. Set it once per shell:

```bash
PY=.venv/bin/python
SC=src
```

Installed: `ortools` 9.15 (CP-SAT + routing), `pulp` 3.3 (CBC), `pypdf`.
Recreate with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

Global game constants come from `supporting-resources/resources.json`.
**Never hardcode prices, recipes, or upgrade costs anywhere else.**
`engine.find_resources()` walks up the tree to locate that file, so scripts work
from any working directory.

## Always simulate before submitting

`src/engine.py` is a deterministic transcription of `specification.pdf`.
It reproduces the spec's worked example exactly (16 ticks, 360 Enteloot).

```bash
$PY $SC/engine.py --self-test
$PY $SC/engine.py --level levels/level2/level.json --actions actions.txt --level-num 2 --verbose
```

It prints per-action ticks and running totals plus a final report:
`final_tick`, `enteloot`, `held_resource_value`, `units_sold`,
`enteloot_invested`, `infrastructure_score`, `towns_developed`,
`invalid_actions`.

**A plan with non-zero `invalid_actions` is leaking ticks.** The current
baseline is 0 on all four levels — keep it there.

`Sim.run(actions, pad=False)` stops the clock the moment the last action ends
instead of crediting trickle to `total_ticks`. Use it whenever you need the
state a later action will actually see; using the padded numbers is what made
the first sell-off attempt fail with "not enough held".

## Generating a plan

```bash
$PY $SC/plan.py --level levels/level2/level.json --level-num 2 --out levels/level2/actions.txt
```

`plan.py` runs four stages:

1. **Enumerate loops.** A *loop* is one repeatable errand that starts and ends
   at a home town: `home -> node visits (gather) -> home -> craft -> sell town -> home`.
   Raw gather-and-sell loops are generated too; they are the only option on Level 1.
2. **Price each loop** in ticks and Enteloot. Stop ordering inside a loop is a
   small TSP solved with OR-Tools routing (`route.order_stops`).
3. **Choose counts with CP-SAT** — an integer knapsack over the tick budget,
   with a cash-flow constraint so the plan cannot spend money it never earns.
4. **Trim and liquidate.** `_trim_to_fit` cuts the list back against a real
   simulation, then `add_liquidation` sells everything still held.

Flags: `--reserve N` (ticks held back, default 20), `--time-limit` (solver
seconds), `--no-liquidate` (skip the sell-off, for A/B comparison).

### Why the trim stage exists

CP-SAT prices each loop in isolation, so the travel *between* consecutive loops
is not in the budget and the emitted list always overshoots. Trimming against a
real simulation is exact; raising `--reserve` alone is not.

### Why the sell-off is worth so much

A sell action costs **1 tick regardless of quantity**. Town trickle piles up
automatically all run. Cashing out at the end added +34% Enteloot on Level 2 and
+91% on Level 4, for two extra actions. It also multiplies `units_sold`, which
feeds the Level 1 multiplier.

## Map layer

`src/route.py`: `Map.dijkstra`, `Map.all_pairs`, `Map.path_actions`
(rebuilds travel actions, marking `fast`), and `order_stops`.

Construct with `allow_fast=(level >= 3)` and `boots=True` once the boots tool is
crafted. **Tools change effective edge weights, so re-run `all_pairs` after
crafting them.**

A fast route is identified by **charging a toll**, not by being listed second in
the level file. Levels 1, 2 and 4 all contain vertex pairs with two toll-free
routes; the slower of those is just a worse standard route, and treating it as
"fast" was a real bug.

## Modelling notes that matter

- **Score is driven by infrastructure, not cash.** Hoarded Enteloot scores far
  less than invested Enteloot, and development spread across towns earns a
  multiplier. On Levels 2+ a plan that only trades is a losing plan.
- **On the real maps, town Enteloot trickle is nearly zero** (rates of
  1,250-5,000 ticks, amounts under 200) — the opposite of the spec's example.
  Cash comes from trading and resource trickle; civic upgrades are score
  items. Check `enteloot.amount / enteloot.rate` before assuming either way.
- **Buying is always faster and always worse per Enteloot.** Use buys to fill a
  small shortfall, gathering trips for bulk.
- **Craft at affinity towns.** 1 tick per item instead of 2.
- **Ore cannot be bought.** Mine nodes only, Level 3+. It gates iron-fittings,
  which gate both tools and the police-station.
- **Invalid actions cost 1 tick each.** Cheapest bug to find, easiest to leave in.

## The build sweep (`src/build.py`)

Runs by default on levels 2+ (`--no-build` disables). Strategy: earn until
cash covers the programme, then one sweep — buy raws at producing towns,
craft every component at a crafting-affinity town, visit each town and build
its chain (production upgrade -> rec-center -> school -> library) — then walk
back to the split-point location so the resumed earn actions stay valid.
Escalates a working-capital reserve and shrinks the town count until the
combined plan simulates with 0 invalid actions.

Two hard-won rules encoded there:

- **Return to the split location.** The resumed earn actions assume the player
  is where the split left them; skip the walk-back and every later travel is
  invalid (~400 wasted ticks).
- **Validate by simulation, not estimate.** The sweep is accepted only when
  the full combined plan simulates clean.

## Extending the planner

Remaining score work on Levels 2-4:

1. **Deeper chains.** Fire-station needs a second production upgrade per town;
   police-station needs fire-station + iron-fittings (Level 3+). Both are
   skipped by the v1 sweep.
2. **Build earlier / in waves.** The sweep waits for full cash; staged waves
   would let civic boosts compound sooner.
3. **Distribution multiplier.** The formula is not in the spec. Model it as a
   bonus on the number of distinct towns holding an upgrade, and confirm against
   the real engine's returned score before tuning.
4. **Tools.** Boots or a pickaxe early changes every later loop's tick cost.
   Solve twice — with and without — and compare final score.
5. **Upkeep (Level 4).** 5 ticks doubles a town's Enteloot amount for 50 ticks
   (75 with a fire-station). Worth it only when the extra Enteloot beats what
   5 ticks buys elsewhere.

See `PROJECT-BREAKDOWN.md` for who owns which of these.

## Known assumptions to verify against the real engine

The spec is ambiguous here. `engine.py` picks one reading; confirm against the
official engine's per-action log before relying on any of them.

- **Trickle after an upgrade.** The spec formula `floor(tick / rate) * amount`
  is retroactive. `engine.py` credits cycles incrementally at the amount active
  when each cycle completes, so an upgrade does not retroactively pay out for
  earlier ticks. A retroactive engine would make early upgrades much stronger.
- **`sell_bonus_multiplier: 1.5`** exists in `resources.json` but is never
  explained in the PDF. `engine.py` ignores it.
- **Scoring weights** are not published. `engine.py` reports the raw inputs
  rather than inventing a total.
- **Enteloot rate changes** (police-station, −2 ticks) are applied to future
  cycles only, using the same incremental reading as above.

## Submission format

`actions.txt` must be a JSON object with a top-level `actions` array. A parse
failure or a missing/non-array `actions` key scores **0**. Everything else
degrades to per-action invalid handling.

```json
{ "actions": [ { "type": "travel", "destination": "N1" }, { "type": "gather" } ] }
```

Required fields: `travel` → `destination` (+ optional `fast`); `buy`/`sell`/
`craft` → `item`, `quantity`; `build` → `upgrade`; `gather` and `upkeep` → none.

The submitted source must reproduce the submitted `actions.txt` exactly, so keep
the pipeline deterministic — no clocks, no RNG, fixed CP-SAT `num_workers` and
`max_time_in_seconds`, and commit the level file used.
