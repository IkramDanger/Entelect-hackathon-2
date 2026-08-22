# Entelect Hackathon 2 — Age of Enteland

Optimisation solution for the Age of Enteland hackathon. See
[`PROJECT-BREAKDOWN.md`](PROJECT-BREAKDOWN.md) for the work split, and
[`.claude/skills/enteland-optimizer/SKILL.md`](.claude/skills/enteland-optimizer/SKILL.md)
for how the solver works.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Layout

| Path | What |
|---|---|
| `src/` | All solver source (engine, routing, planners) |
| `levels/levelN/level.json` | The level input |
| `levels/levelN/actions.txt` | The generated submission for that level |
| `specification.pdf` | The problem statement (source of truth) |
| `supporting-resources/resources.json` | Global constants: prices, recipes, upgrades, tools |
| `.claude/skills/enteland-optimizer/` | Claude Code skill docs |

## Run

```bash
PY=.venv/bin/python

# generate a submission and simulate it in one step
$PY src/plan.py --level levels/level2/level.json --level-num 2 --out levels/level2/actions.txt

# check an existing submission
$PY src/engine.py --level levels/level2/level.json --actions levels/level2/actions.txt --level-num 2
```

`src/engine.py --self-test` reproduces the worked example from
`specification.pdf` (16 ticks, 360 Enteloot). Run it after any engine change.

## Package a submission (the official way)

```bash
$PY lane_H.py --level levels/level2/level.json --level-num 2
```

`lane_H.py` generates the plan **twice** and fails if the bytes differ,
validates it with the engine (any invalid action is a hard failure), then
publishes `levels/levelN/actions.txt` plus a reproducible `source.zip` beside
it. The ZIP alone regenerates the exact actions.txt — verified. Always ship
what this tool produced, never a hand-run plan.py output.

## Current baseline

| Level | Ticks | Enteloot | Infrastructure | Towns developed | Tools | Invalid actions |
|---|---|---|---|---|---|---|
| 1 | 1,000 | 30,990 | 0 | 0 | — | 0 |
| 2 | 5,000 | 95,141 | 168,000 (70/100 upgrades) | 7 of 10 | — | 0 |
| 3 | 50,000 | 2,003,367 | 435,000 (max) | 15 of 15 | boots + pickaxe | 0 |
| 4 | 100,000 | 6,588,418 | 870,000 (max) | 30 of 30 | boots + pickaxe | 0 |

Engine-reported Enteloot is now a *floor*: the planner deliberately sells at
towns where the assumed `sell_bonus_multiplier` (1.5x) would pay, which our
engine does not credit. `--no-sell-bonus` reverts that bet. See
`PROJECT-BREAKDOWN.md` section 5 for all three assumption bets.

Levels 3 and 4 build **every upgrade in every town** — 870,000 is the literal
infrastructure maximum on Level 4. Note: the real level files give towns almost
no passive Enteloot (rates of 1,250–5,000 ticks), the opposite of the spec's
example — so cash comes from trading and resource trickle, and civic upgrades
are score items, not money-makers.
