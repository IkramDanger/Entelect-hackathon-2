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

## Run

```bash
PY=.venv/bin/python
SC=.claude/skills/enteland-optimizer/scripts

# generate a submission and simulate it in one step
$PY $SC/plan.py --level Levels/2.txt --level-num 2 --out submissions/level2/actions.txt

# check an existing submission
$PY $SC/engine.py --level Levels/2.txt --actions submissions/level2/actions.txt --level-num 2
```

`engine.py --self-test` reproduces the worked example from `specification.pdf`
(16 ticks, 360 Enteloot). Run it after any change to the engine.

## Layout

| Path | What |
|---|---|
| `specification.pdf` | The problem statement (source of truth) |
| `supporting-resources/resources.json` | Global constants: prices, recipes, upgrades, tools |
| `Levels/1.txt` … `4.txt` | The four level files |
| `.claude/skills/enteland-optimizer/` | Solver + simulator + docs |
| `submissions/levelN/` | Per-level `actions.txt` to submit |

## Current baseline

| Level | Ticks | Enteloot | Units sold | Infrastructure | Towns developed | Invalid actions |
|---|---|---|---|---|---|---|
| 1 | 1,000 | 30,990 | 3,976 | 0 | 0 | 0 |
| 2 | 5,000 | 139,788 | 20,517 | 150,000 | 10 | 0 |
| 3 | 50,000 | 2,213,665 | 432,958 | 225,000 | 15 | 0 |
| 4 | 100,000 | 7,439,705 | 1,374,931 | 450,000 | 30 | 0 |

Every buildable town now runs the full chain (production upgrade →
rec-center → school → library) via the build sweep in `build.py`. The civic
upgrades pay for themselves: Levels 3 and 4 end with **more** Enteloot than the
earn-only plan did. Remaining solver work (fire-station/police-station chains,
tools, tolls, upkeep) is in `PROJECT-BREAKDOWN.md` section 4.
