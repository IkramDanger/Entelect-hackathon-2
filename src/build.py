"""Construction planner: turn Enteloot into built upgrades.

Strategy (v1): earn until cash covers the build programme, then run one build
sweep — buy raw resources, craft every component at a crafting-affinity town,
then visit each target town and build its chain — and let the remaining earn
actions continue afterwards. Civic upgrades multiply town Enteloot generation
for the rest of the run, so the sweep sits as early as cash allows.

Per-town chain (v2): two production upgrades, then
rec-center -> fire-station -> school -> police-station (L3+) -> library,
respecting each prerequisite. On Level 3+ the sweep also crafts both tools
(boots, pickaxe) once, since every later travel and gather is cheaper for the
rest of the run.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Sim            # noqa: E402
from route import order_stops     # noqa: E402

# civic order satisfies every per-town prerequisite when built in sequence
CIVIC_CHAIN = ["rec-center", "fire-station", "school", "police-station", "library"]
TOOLS = ["boots", "pickaxe"]


def pick_productions(town_data, C):
    """All six production upgrades, matching ones first: an upgrade whose
    resource the town actually produces doubles real trickle, the rest are
    pure score. Two must precede the civic chain (fire-station's
    prerequisite); the rest trail it so a tick-budget trim costs the
    cheapest score first."""
    produced = set(town_data.get("production", {}).get("resources", {}))
    ranked = sorted(C["upgrades"]["production"].items(),
                    key=lambda kv: (kv[1]["effect"].get("resource") not in produced,
                                    kv[1]["enteloot_cost"], kv[0]))
    return [n for n, _ in ranked]


def expand(C, item, qty, raw, crafts, depth):
    rec = C["components"].get(item)
    if rec is None:                       # raw resource
        raw[item] += qty
        return 0
    crafts[item] += qty
    d = 0
    for inp, per in rec["inputs"].items():
        d = max(d, 1 + expand(C, inp, per * qty, raw, crafts, depth))
    depth[item] = max(depth.get(item, 0), d)
    return d


def chain_requirements(sel, chains, C, tools=()):
    raw, crafts, depth = defaultdict(int), defaultdict(int), {}
    cost = 0
    for town in sel:
        for up in chains[town]:
            meta = C["upgrades"]["production"].get(up) or C["upgrades"]["civic"][up]
            cost += meta["enteloot_cost"]
            for comp, need in meta["components"].items():
                expand(C, comp, need, raw, crafts, depth)
    for tool in tools:
        # tools are not components, so expand their inputs by hand
        for comp, need in C["tools"][tool]["inputs"].items():
            expand(C, comp, need, raw, crafts, depth)
    return raw, crafts, depth, cost


def emit_build(level, C, sel, chains, raw, crafts, depth, mp, ticks, prevs,
               start_loc, tools=()):
    towns = level["towns"]
    nodes = level.get("nodes", {})
    acts, cur = [], start_loc

    def go(dst):
        nonlocal cur
        if dst == cur:
            return True
        steps = mp.path_actions(prevs[cur], cur, dst)
        if steps is None:
            return False
        acts.extend(steps)
        cur = dst
        return True

    # craft town: nearest crafting-affinity town, else nearest town
    aff = [t for t, d in towns.items() if "crafting" in d.get("affinities", [])]
    pool = aff or list(towns)
    craft_town = min(pool, key=lambda t: ticks[start_loc].get(t, 10 ** 9))

    # assign each raw resource to a source: a producing town (buy) or a node
    producers = defaultdict(list)
    for t, d in towns.items():
        for res in d.get("production", {}).get("resources", {}):
            producers[res].append(t)
    node_by_res = defaultdict(list)
    for n, d in nodes.items():
        node_by_res[d["resource"]].append(n)

    buy_at, gather_at = defaultdict(dict), defaultdict(dict)
    for res, qty in raw.items():
        if producers[res]:
            stop = min(producers[res], key=lambda t: ticks[craft_town].get(t, 10 ** 9))
            buy_at[stop][res] = qty
        elif node_by_res[res]:
            stop = min(node_by_res[res], key=lambda n: ticks[craft_town].get(n, 10 ** 9))
            gather_at[stop][res] = qty
        else:
            return None, None                     # resource unobtainable

    stops = list(buy_at) + list(gather_at)
    for stop in order_stops(cur, stops, ticks):
        if not go(stop):
            return None, None
        for res, qty in buy_at.get(stop, {}).items():
            acts.append({"type": "buy", "item": res, "quantity": qty})
        for res, qty in gather_at.get(stop, {}).items():
            reps = math.ceil(qty / nodes[stop]["yield"])
            acts.extend([{"type": "gather"}] * reps)

    # craft every component at the affinity town, dependency order
    if not go(craft_town):
        return None, None
    for item in sorted(crafts, key=lambda i: depth.get(i, 0)):
        acts.append({"type": "craft", "item": item, "quantity": crafts[item]})
    for tool in tools:
        acts.append({"type": "craft", "item": tool, "quantity": 1})

    # build each town's chain
    for town in order_stops(cur, list(sel), ticks):
        if not go(town):
            return None, None
        for up in chains[town]:
            acts.append({"type": "build", "upgrade": up})
    return acts, cur


def plan_builds(level, C, level_num, earn_actions, mp, ticks, tolls, prevs,
                cash_buffer=1.25, verbose=print):
    """Insert a build sweep into an earn-only action list. Returns the combined
    list, or the original if no build programme fits."""
    towns = level["towns"]

    def make_chains(full):
        out = {}
        for t, d in towns.items():
            prods = pick_productions(d, C)
            chain = prods[:2]
            for c in CIVIC_CHAIN:
                if C["upgrades"]["civic"][c].get("min_level", 1) <= level_num:
                    chain.append(c)
            if full:
                chain.extend(prods[2:])
            out[t] = chain
        return out
    # boost the best Enteloot generators first
    candidates = sorted(towns, key=lambda t: -(towns[t]["enteloot"]["amount"]
                                               / max(1, towns[t]["enteloot"]["rate"])))

    base = Sim(level, level_num=level_num, constants=C)
    base.run(list(earn_actions), pad=False)
    log = base.log

    tools = [t for t in TOOLS
             if C["tools"][t].get("min_level", 1) <= level_num]

    # try the full 11-upgrade programme and the lean 7-upgrade one; short
    # levels cannot afford full chains in every town, and developed-town
    # spread beats a few extra production upgrades
    # ASSUMPTION: the distribution multiplier is the one the spec's own
    # appendix floats — upgrades built / total possible — and it multiplies
    # the infrastructure score. So rank programmes by infra x built/total.
    per_town_max = len(make_chains(True)[next(iter(towns))])
    total_possible = per_town_max * len(towns)
    best = None
    for full in (True, False):
        chains = make_chains(full)
        result = _descend(level, C, level_num, earn_actions, mp, ticks, prevs,
                          chains, candidates, tools, log, cash_buffer, verbose)
        if result is None:
            continue
        combined, rep = result
        built = sum(len(v) for v in rep["upgrades_by_town"].values())
        key = rep["infrastructure_score"] * built / total_possible
        if best is None or key > best[0]:
            best = (key, combined, rep, "full" if full else "lean")
    if best:
        _, combined, rep, prof = best
        verbose(f"build sweep: kept {prof} programme — "
                f"{rep['towns_developed']} towns, "
                f"infrastructure {rep['infrastructure_score']}, "
                f"assumed multiplier {best[0] / max(1, rep['infrastructure_score']):.2f}, "
                f"invested {rep['enteloot_invested']}")
        return combined
    verbose("build sweep: no build programme fits, keeping earn-only plan")
    return earn_actions


def _descend(level, C, level_num, earn_actions, mp, ticks, prevs, chains,
             candidates, tools, log, cash_buffer, verbose):
    for n in range(len(candidates), 0, -1):
        sel = candidates[:n]
        raw, crafts, depth, upgrade_cost = chain_requirements(sel, chains, C, tools)
        raw_cost = sum(qty * (C["resources"][r].get("buy_price") or 0)
                       for r, qty in raw.items())
        base_need = int((upgrade_cost + raw_cost) * cash_buffer)

        # working capital: the earn loops that resume after the sweep still
        # need cash for their own buys, so escalate a reserve until the
        # combined plan runs without invalid actions
        for reserve in (2000, 8000, 25000, 80000):
            cash_needed = base_need + reserve
            split = next((i for i, e in enumerate(log)
                          if e["enteloot"] >= cash_needed), None)
            if split is None:
                break                              # never earn this much
            prefix = earn_actions[:split + 1]

            state = Sim(level, level_num=level_num, constants=C)
            state.run(list(prefix), pad=False)
            build_acts, end_loc = emit_build(level, C, sel, chains, raw, crafts,
                                             depth, mp, ticks, prevs,
                                             state.location, tools)
            if build_acts is None:
                break                              # unreachable resource
            # the resumed earn actions assume the player is where the split
            # left them — walk back, or every later travel is invalid
            if end_loc != state.location:
                back = mp.path_actions(prevs[end_loc], end_loc, state.location)
                if back is None:
                    break
                build_acts = build_acts + back

            combined = prefix + build_acts + earn_actions[split + 1:]
            rep = Sim(level, level_num=level_num, constants=C).run(list(combined))
            want = sum(len(chains[t]) for t in sel)
            built = sum(len(v) for v in rep["upgrades_by_town"].values())
            if built == want and rep["invalid_actions"] <= 1:
                verbose(f"  candidate: {n} towns x {len(chains[sel[0]])} upgrades"
                        f"{' + tools' if tools else ''} "
                        f"at tick ~{log[split]['tick']}, reserve {reserve}")
                return combined, rep
    return None
