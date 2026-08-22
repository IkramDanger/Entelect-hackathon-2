# Project breakdown and work split

Two people: **Ikram** (solver) and **Fayyad** (harness). This document says
what the project is made of, what is already done, and who takes what next.

> **Fayyad — start here.** Your lane is Lane H, section 4 below. Your first
> task is **submission packaging** (item 1): it is small, it unblocks
> submitting Level 1 today, and it is the only task in the whole project that
> can turn a finished solution into a score of 0. After that, the three
> unknowns in section 5 — they block Ikram's calibration. Your checklist:
>
> 1. ~~Packaging~~ — **done**: `lane_H.py` (generate twice, byte-compare, validate, reproducible zip)
> 2. Answer the three unknowns against the official engine (section 5)
> 3. `scoreboard.py` — one command, one table, every run appended
> 4. `test_regression.py` — fails loudly if anything gets worse
> 5. `levels.py` — input validator with clear error messages
> 6. Ongoing: run Ikram's experiments and hand back the winner

Read this first, then `.claude/skills/enteland-optimizer/SKILL.md` for how the
code works.

**The split in one line:** Ikram owns the **solver** (everything that decides
what actions to take), Fayyad owns the **harness** (everything that feeds it,
proves it, and measures it).

---

## 1. What the problem actually is

Age of Enteland is one long **resource allocation problem with a routing
sub-problem inside it**.

- You get a fixed tick budget per level (1,000 → 100,000).
- Every action costs ticks. Ticks are the only truly scarce thing.
- You submit one flat, ordered JSON list of actions per level. No feedback loop,
  no reacting mid-run. It is a plan, not a bot.
- The map is a weighted graph. From Level 3 some pairs also have a tolled fast
  route, so travel cost is two-dimensional (ticks vs Enteloot).

**Score is not Enteloot.** On Levels 2-4 infrastructure is the primary driver,
spread across towns earns a multiplier, and hoarded Enteloot scores far less
than invested Enteloot. A plan that only trades is a losing plan.

---

## 2. Sections of the system

Lane **S** = Solver. Lane **H** = Harness.

| # | Section | File | State | Lane |
|---|---|---|---|---|
| 1 | Level loader + global constants | `engine.py` | **Done** | Shared |
| 2 | Deterministic simulator | `engine.py` | **Done** | S |
| 3 | Map layer (Dijkstra, tolls, TSP) | `route.py` | **Done** | S |
| 4 | Loop enumeration + pricing | `plan.py` | **Done** | S |
| 5 | CP-SAT allocation | `plan.py` | **Done** | S |
| 6 | Trim + end-of-run sell-off | `plan.py` | **Done** | S |
| 7 | Construction planner (v2: full 11-upgrade set) | `build.py` | **Done** | S |
| 8 | Tools (boots + pickaxe in the build sweep) | `build.py` | **Done** | S |
| 9 | Upkeep planner (declines itself: L4 towns trickle ~0) | `upkeep.py` | **Done** | S |
| 10 | **Level input loader + validator** | `levels.py` | **Not started** | **H** |
| 11 | Submission packaging + determinism | `lane_H.py` | **Done** | H |
| 12 | **Scoreboard** | `scoreboard.py` | **Not started** | **H** |
| 13 | **Regression guard** | `test_regression.py` | **Not started** | **H** |
| 14 | **Verify rules vs the official engine** | — | **Not started** | **H** |
| 15 | **Experiment runs** | — | Ongoing | **H** |

### What the built pieces do

**1-2. Engine.** Reads the level file and `supporting-resources/resources.json`,
then replays an action list tick by tick and reports the outcome. It reproduces
the spec's worked example exactly (16 ticks, 360 Enteloot). This is the referee
— nothing gets submitted without passing through it.

**3. Map layer.** All-pairs shortest paths where cost is ticks first, toll
second. Rebuilds concrete travel actions from a path, marking `fast` correctly.
Also orders stops inside a trip with OR-Tools routing.

**4-6. Profit planner.** Enumerates repeatable "loops"
(`home → gather → home → craft → sell town → home`), prices each in ticks and
Enteloot, and uses CP-SAT to pick how many times to run each inside the budget.
Then trims to fit and sells everything held at the end.

---

## 3. Where we stand

| Level | Ticks | Enteloot | Infrastructure | Towns developed | Invalid actions |
|---|---|---|---|---|---|
| 1 | 1,000 | 30,990 | 0 | 0 | 0 |
| 2 | 5,000 | 107,906 | 180,000 | 9 of 10 | 0 |
| 3 | 50,000 | 2,227,967 | 435,000 | 15 of 15 | 0 |
| 4 | 100,000 | 7,513,206 | 870,000 | 30 of 30 | 0 |

The build sweep (`build.py`, done 2026-08-22) put the full four-upgrade chain
in every town on Levels 2-4 — and the civic upgrades pay for themselves, so
Enteloot went **up** too. Lane S's remaining work: fire-station and
police-station chains, tools, toll trade-offs, upkeep, and building *earlier*
(the sweep currently waits for cash; staging it in waves would compound more).

---

## 4. The split

### Lane S — Solver (Ikram)

Ikram owns everything that decides **what actions to take**. This is the score.

1. **Construction planner** (section 7). Expand the component chains
   (`mortar → bricks`, `rope → fencing → nets`, `ore → iron-fittings`). Then a
   CP-SAT model with integer vars per `(upgrade, town)` pair and `score_value`
   in the objective. Constraints: components available, Enteloot available,
   per-town prerequisites (`rec-center` needs 1 production upgrade *in that
   town*; `school` needs `rec-center`; `library` needs `school`;
   `police-station` needs `fire-station`), once per town.
2. **Build order over time.** Civic upgrades multiply Enteloot generation, so
   they compound — a building bought at tick 500 pays out for 99,500 ticks; the
   same building at tick 90,000 pays almost nothing. "What to build" and "when
   to build it" cannot be solved separately.
3. **Distribution multiplier.** Reward spreading upgrades across towns. The
   formula is not published — model it, then calibrate once H answers it.
4. **Tools** (section 8). Boots (−1 tick per edge) and pickaxe (−1 tick per
   gather) are permanent and both need a mine trip. Solve the run twice, with
   and without, and compare. Re-run `Map.all_pairs(boots=True)` after crafting.
5. **Fast routes and tolls.** Dijkstra currently minimises ticks and ignores the
   trade-off. Tune the `toll_weight` knob that already exists at `route.py:33`:
   how much Enteloot is one tick worth on this level? Levels 3 and 4 have 6 and
   18 tolled routes.
6. **Upkeep** (section 9). 5 ticks doubles a town's Enteloot amount for 50
   ticks, 75 with a fire-station. Pick which towns and when.

Touches: `plan.py`, `route.py`, `engine.py`, new `build.py`, `tools.py`,
`upkeep.py`.

### Lane H — Harness (Fayyad)

Fayyad owns everything **around** the solver. No solver logic, no merge conflicts.

1. **Level input loader + validator** (section 10). A proper loader for
   `levels/levelN/level.json`. Fail loudly and early on a missing or malformed field instead
   of crashing halfway through a run. Report which town, which key, what was
   expected.
2. **Submission packaging** (section 11). `make_submission.py` writes
   `levels/levelN/actions.txt`, zips the source, then re-runs the whole
   pipeline and proves the output is **byte-identical**.
   **A submission whose source does not reproduce the file is invalid — this is
   the only task that can turn a good solution into a zero. Do it first.**
3. **Scoreboard** (section 12). One command runs all four levels and prints one
   table: ticks used, Enteloot, infrastructure score, towns developed, units
   sold, invalid actions, wall-clock seconds. Append every run to a file so any
   two runs can be compared.
4. **Regression guard** (section 13). A test that fails loudly if
   `invalid_actions` rises above 0, if `engine.py --self-test` stops passing, or
   if any level scores worse than the last committed baseline.
5. **Verify the ambiguous rules** (section 14). Send small throwaway action
   lists to the official engine and read the per-action log. Three unknowns, in
   section 5 below. Report the answers to S.
6. **Run the experiments** (section 15, ongoing). Ikram says "try toll weight
   0.5, 1 and 2" or "compare boots-first against boots-never". Fayyad runs
   them, fills in the scoreboard, and hands back the winner.

Touches: new `levels.py`, `make_submission.py`, `scoreboard.py`,
`test_regression.py`.

### Why the lanes are shaped this way

S's real bottleneck is not writing models — it is **waiting to find out whether
a change helped**. Item 6 above removes that wait: S writes, H measures. That is
worth more than any single feature H could build.

H's items 1-4 are real, needed, and touch **zero** solver code, so the two lanes
never edit the same file.

---

## 5. The three unknowns — SOLVED (decoded from official logs)

Fayyad owns this, and it blocks Ikram's calibration. Budget an hour, on day one.

**Update 2026-08-22: the planner now acts on a chosen answer for each.** The
bets are picked to be plausible *and* score-maximising; Fayyad's verification
now tells us whether to keep or revert them, so it matters more, not less.

| Unknown | Bet taken | Where | If the bet is wrong |
|---|---|---|---|
| Retroactive trickle | No action needed — early building is fine under both readings | — | Nothing changes |
| `sell_bonus_multiplier` | Pays 1.5x when a good is sold at a town producing none of its inputs; steers loop *ranking* only, cash stays real | `plan.py` (`--no-sell-bonus` reverts) | ~10% Enteloot given up for nothing |
| Distribution multiplier | The spec appendix's own formula: upgrades built / total possible, multiplying infra score | `build.py` | L2 favours 7 deep towns over 9 shallow ones needlessly |

- **Does trickle after an upgrade pay out retroactively?** The spec formula
  `floor(tick / rate) * amount` reads as retroactive. `engine.py` credits each
  cycle at the amount active when that cycle completed, so an upgrade does *not*
  pay for earlier ticks. If the real engine is retroactive, early upgrades get
  much stronger and S's whole build order changes.
- **What is `sell_bonus_multiplier: 1.5`?** It sits in `resources.json` and is
  never mentioned in the PDF. `engine.py` ignores it.
- **What are the real scoring weights,** and what is the distribution-multiplier
  formula? Neither is published, so S cannot calibrate sections 7 and 3 without
  them.

---

## 5b. Leaderboard experiments (the road past 47M)

The first upload scored 47M, fitting `enteloot + infra x towns` almost
exactly. Under that formula our mechanics are near the ceiling (~48M), so
150M requires a term we cannot see locally. Prime suspect: a **units-sold
multiplier** (documented for Level 1, possibly global). Buy+sell cost 1 tick
each at ANY quantity, so churning converts cash into units at ~cash/4 units
per cycle.

`experiments/level4-churn2/` and `experiments/level1-churn1/` are
self-reproducing packages (their zips regenerate their actions.txt bytes).
Protocol: upload ONE experiment in place of that level's main submission,
read the score delta, restore the main. If Level 4's score jumps, churn gets
baked into every level and re-tuned for the optimal cash/units balance.

## 6. Working agreement

- **`engine.py` is a shared contract.** S owns it, but change it only when the
  official engine's log disagrees with it, and tell H immediately — every
  scoreboard number before that change becomes incomparable. Every change must
  keep `engine.py --self-test` passing.
- **Branch per section.** `feat/build-planner`, `feat/packaging`, and so on.
- **H never edits solver files. S never edits harness files.** If you need
  something from the other lane, ask for it rather than reaching across.
- **Interface between lanes:** H's tools always take
  `(level_path, level_num)` and shell out to `plan.py` / `engine.py`. They never
  import solver internals, so S can refactor freely.
- **Every planner S writes exposes** `plan(level, C, level_num, state) →
  (actions, ticks_used)`, so `plan.py` can compose them in order.
- **Definition of done for a level:** `invalid_actions == 0`, the source
  reproduces `actions.txt` byte for byte, and the score beats the previous
  committed baseline. H records the numbers.
- **Determinism is a hard requirement.** No wall clocks, no RNG, fixed CP-SAT
  `num_workers` and `max_time_in_seconds`. A non-reproducible submission scores 0.
  Verified today: two runs of Level 3 produce identical files.

---

## 7. Suggested order

| When | Lane S | Lane H |
|---|---|---|
| Day 1 | Component chains for Level 2 | **Packaging + determinism check**, then the three unknowns |
| Then | Upgrade selection model | Scoreboard + regression guard |
| Then | Build order over time; calibrate the multiplier | Run S's calibration experiments |
| Then | Tools, then tolls, for Level 3 | Level input validator; keep measuring |
| Then | Upkeep for Level 4 | Run the Level 4 sweeps |
| Last | Joint tuning pass on Level 4 | ← same |

H's packaging comes first on purpose: it is small, it unblocks submitting
Level 1 immediately, and it makes every later result measurable.

---

## 8. Biggest risks

| Risk | Why it hurts | What to do |
|---|---|---|
| Non-reproducible submission | Automatic 0, all of S's work lost | H's packaging check, day one |
| Our engine disagrees with theirs | Every tuned number is wrong | H verifies, section 5 |
| S becomes the single bottleneck | Whole project stalls behind one person | S flags a stall early; H can take section 9 (upkeep) if needed |
| H runs out of work | Idle partner, uneven load | Section 15 is ongoing by design — S must keep feeding experiments |
| Chasing Enteloot | It is not the score on L2-4 | Scoreboard shows `infrastructure_score` in every row |
| Level 4 solver blow-up | 30 towns, 92 routes, 100k ticks | Runs in ~16s today — H tracks runtime per row |
