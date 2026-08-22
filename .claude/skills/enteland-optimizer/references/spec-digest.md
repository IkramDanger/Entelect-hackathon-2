# Spec digest — Age of Enteland

Source of truth: `specification.pdf` (17 pages) and
`supporting-resources/resources.json`. This is a lookup sheet, not a
replacement — read the PDF for wording disputes.

## Run rules

| Rule | Detail |
|---|---|
| Clock | One global tick clock, `run.total_ticks` long |
| Order | Actions execute strictly in submission order, one at a time |
| Validation | Checked at execution time, not submission time |
| Invalid action | Skipped, costs 1 tick, logged, run continues |
| Over budget | Action skipped, clock jumps to `total_ticks`, run ends cleanly |
| Passive systems | Town production and Enteloot fire on the clock regardless of player |
| Determinism | No randomness anywhere |
| Debt | Enteloot can never go below zero |
| Inventory | Unlimited |
| Travel | Atomic; cannot act mid-route |

Trickle: `accumulated = floor(current_tick / rate) * amount`, amount floored
after any upgrade modifier.

## Action costs

| Action | Where | Ticks |
|---|---|---|
| travel | between connected vertices | edge weight (−1 with boots, min 1) |
| gather | at a node | node gather-time (−1 with pickaxe, min 1) |
| buy | any town, resources it produces | 1 |
| sell | any town | 1 |
| craft | any town | 2 per item, 1 at a crafting-affinity town |
| build | any town | per upgrade (3–5) |
| upkeep | any town | 5 |

## Level unlocks

| Level | Adds |
|---|---|
| 1 | travel, buy, sell, gather |
| 2 | craft, build, recipes, components, production + civic upgrades |
| 3 | fast routes, mine nodes, ore, iron-fittings, tools, police-station |
| 4 | upkeep |

## Scoring drivers

- **Level 1** — Enteloot generated + value of items held at the end, multiplied
  by items sold.
- **Levels 2 & 3** — infrastructure is primary; development spread across towns
  earns a multiplier.
- **Level 4** — upkeep adds no dedicated term; it only shifts base Enteloot.

Exact weights and the distribution-multiplier formula are not published.

## The four real levels (`Levels/1.txt` … `4.txt`)

| Level | Ticks | Start Enteloot | Towns | Nodes | Routes | Tolled routes | Crafting-affinity towns | Mines |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,000 | 200 | 5 | 7 | 14 | 0 | 3 | 0 |
| 2 | 5,000 | 500 | 10 | 14 | 30 | 0 | 8 | 0 |
| 3 | 50,000 | 1,000 | 15 | 21 | 51 | 6 | 2 | 3 |
| 4 | 100,000 | 2,000 | 30 | 28 | 92 | 18 | 8 | 7 |

Note the shape change at Level 3: the tick budget jumps 10x, tolled fast routes
appear, and crafting-affinity towns become **scarce** (2 of 15). Craft location
matters much more from Level 3 on.

Levels 1, 2 and 4 each contain vertex pairs joined by two **toll-free** routes.
Those are not fast routes — the slower one is simply worse. Classify a fast
route by `toll > 0`.

## Tables

Resources, recipes, components, upgrades and tools are all in
`supporting-resources/resources.json`. Load them, do not retype them.

Quick orientation:

- 7 resources; ore alone cannot be bought.
- 9 sellable recipes; every town sets an item-rate for every good.
- 10 components, never sold. Chains: `mortar → bricks`, `rope → fencing → nets`.
- 6 production upgrades (1000 pts each), 5 civic (3000–6000 pts), per-town
  prerequisites, once per town.
- 2 tools, once per run, both need iron-fittings.
