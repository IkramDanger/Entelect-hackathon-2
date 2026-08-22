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

## Current baseline — decoded scoring

The official score formula was decoded exactly from six uploaded logs:

```
score = M x [ enteloot + held + 1.5 x revenue + 2 x infra x D ]
M = 100 / 15 / 2 / 1 for L1-L4,  D = (1 + towns_developed/towns_total) / 2
```

Consequences built into the planner: revenue outranks cash (loops valued at
4.5xrevenue - 3xspend), every run ends with a clay churn converting each held
Enteloot into ~3 score points, and the build sweep is A/B-tested per level
(L2 scores higher with no builds at all).

| Level | Predicted score | Real (v4 upload) | Prediction accuracy |
|---|---|---|---|
| 1 | 13,535,550 | 12,984,700 (prev pkg) | 98.8% |
| 2 | 17,424,120 | 17,408,250 | 99.9% |
| 3 | 30,918,325 | 30,026,366 (prev pkg) | 99.98% |
| 4 | 41,504,518 | 41,578,345 (prev pkg) | 99.99% |
| **Total** | **~103.4M** | 102.0M real | |

The simulator now predicts the official engine to within 0.1% on the big
levels. Real scores: 47M -> 60M -> 93M -> 102M across uploads.
