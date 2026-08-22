"""Level 1-3 profit planner: enumerate candidate loops, pick counts with CP-SAT.

Model
-----
A *loop* is one repeatable errand that starts and ends at a home town:
    home -> (node visits, gathering) -> home -> craft -> sell town -> home
Each loop has a fixed tick cost and a fixed Enteloot profit, so choosing how
many times to run each loop is an integer knapsack over the tick budget.
That is the resource-allocation half. The stop ordering inside a loop is a
small TSP, solved with OR-Tools routing. That is the routing half.

This is a strong baseline, not a proven optimum. Extend it before trusting
it on Levels 2-4 (see SKILL.md, "Extending the planner").
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Sim, load_constants          # noqa: E402
from route import Map, order_stops              # noqa: E402

BATCHES = (1, 2, 3, 5, 8, 12)


def _tour_cost(home, stops, ticks, tolls, prevs):
    seq = order_stops(home, stops, ticks)
    legs, cur, t, tl = [], home, 0, 0
    for s in seq + [home]:
        if s == cur:
            continue
        if s not in ticks[cur]:
            return None
        t += ticks[cur][s]
        tl += tolls[cur][s]
        legs.append((cur, s))
        cur = s
    return {"seq": seq, "legs": legs, "ticks": t, "toll": tl}


def _source_options(resource, need, home, towns, node_by_res, nodes, C, prefer_buy):
    """Return (kind, payload, ticks_local, enteloot_cost, node) or None."""
    price = C["resources"].get(resource, {}).get("buy_price")
    can_buy = price is not None and resource in towns[home].get("production", {}).get("resources", {})
    if prefer_buy and can_buy:
        return ("buy", need, 1, price * need, None)
    best = None
    for n in node_by_res.get(resource, []):
        yld = nodes[n]["yield"]
        gathers = math.ceil(need / yld)
        cost = gathers * nodes[n].get("gather-time", 2)
        if best is None or cost < best[2]:
            best = ("gather", gathers, cost, 0, n)
    if best is None and can_buy:
        return ("buy", need, 1, price * need, None)
    return best


def build_loops(level, C, level_num, ticks, tolls, prevs):
    towns, nodes = level["towns"], level.get("nodes", {})
    node_by_res = defaultdict(list)
    for n, d in nodes.items():
        node_by_res[d["resource"]].append(n)
    loops = []

    # --- raw gather-and-sell loops (the only option on Level 1) ---
    for home in towns:
        for res, ns in node_by_res.items():
            for n in ns:
                if n not in ticks[home]:
                    continue
                for reps in (1, 2, 4, 8):
                    yld = nodes[n]["yield"] * reps
                    t = (ticks[home][n] * 2 + reps * nodes[n].get("gather-time", 2) + 1)
                    toll = tolls[home][n] * 2
                    profit = C["resources"][res]["sell_price"] * yld - toll
                    if profit <= 0:
                        continue
                    loops.append({
                        "kind": "raw", "home": home, "node": n, "reps": reps,
                        "res": res, "qty": yld, "ticks": t, "profit": profit,
                        "spend": toll,
                    })

    if level_num < 2:
        return loops

    # --- craft-and-haul loops ---
    for good, rec in C["recipes"].items():
        if rec.get("min_level", 1) > level_num:
            continue
        for home in towns:
            craft_t = 1 if "crafting" in towns[home].get("affinities", []) else 2
            for sell_town in towns:
                rate = towns[sell_town].get("item-rates", {}).get(good)
                if not rate:
                    continue
                if sell_town not in ticks[home]:
                    continue
                for q in BATCHES:
                    for prefer_buy in (False, True):
                        srcs, gather_ticks, spend, stops, bad = [], 0, 0, [], False
                        for res, per in rec["inputs"].items():
                            opt = _source_options(res, per * q, home, towns,
                                                  node_by_res, nodes, C, prefer_buy)
                            if opt is None:
                                bad = True
                                break
                            kind, payload, lt, cost, node = opt
                            srcs.append((res, kind, payload, node))
                            gather_ticks += lt
                            spend += cost
                            if node:
                                stops.append(node)
                        if bad:
                            continue
                        tour = _tour_cost(home, stops, ticks, tolls, prevs) if stops else \
                            {"seq": [], "legs": [], "ticks": 0, "toll": 0}
                        if tour is None:
                            continue
                        haul = ticks[home][sell_town] * 2
                        haul_toll = tolls[home][sell_town] * 2
                        t = tour["ticks"] + gather_ticks + craft_t * q + haul + 1
                        toll = tour["toll"] + haul_toll
                        profit = rate * q - spend - toll
                        if profit <= 0:
                            continue
                        loops.append({
                            "kind": "craft", "home": home, "good": good, "q": q,
                            "sell_town": sell_town, "srcs": srcs, "seq": tour["seq"],
                            "ticks": t, "profit": profit, "spend": spend + toll,
                        })
    return loops


def choose(loops, budget, starting_enteloot, time_limit=20.0):
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    xs = []
    for l in loops:
        cap = max(1, budget // max(1, l["ticks"]))
        xs.append(m.new_int_var(0, cap, f"x{len(xs)}"))
    m.add(sum(x * l["ticks"] for x, l in zip(xs, loops)) <= budget)
    # keep upfront spending inside a plausible cash envelope
    m.add(sum(x * l["spend"] for x, l in zip(xs, loops))
          <= starting_enteloot + sum(x * l["profit"] for x, l in zip(xs, loops)))
    m.maximize(sum(x * l["profit"] for x, l in zip(xs, loops)))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = 8
    st = s.solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], st
    picked = [(l, s.value(x)) for x, l in zip(xs, loops) if s.value(x) > 0]
    picked.sort(key=lambda p: (p[0]["spend"] > 0, -p[0]["profit"] / p[0]["ticks"]))
    return picked, s.status_name(st)


def emit(picked, level, mp, ticks, tolls, prevs, C):
    actions, cur = [], level["run"]["starting_town"]

    def go(dst):
        nonlocal cur
        steps = mp.path_actions(prevs[cur], cur, dst)
        if steps:
            actions.extend(steps)
            cur = dst

    for loop, count in picked:
        for _ in range(count):
            go(loop["home"])
            if loop["kind"] == "raw":
                go(loop["node"])
                actions.extend([{"type": "gather"}] * loop["reps"])
                go(loop["home"])
                actions.append({"type": "sell", "item": loop["res"], "quantity": loop["qty"]})
                continue
            buys = [(r, p) for r, k, p, n in loop["srcs"] if k == "buy"]
            for res, qty in buys:
                actions.append({"type": "buy", "item": res, "quantity": qty})
            for stop in loop["seq"]:
                go(stop)
                reps = next((p for r, k, p, n in loop["srcs"] if n == stop), 1)
                actions.extend([{"type": "gather"}] * reps)
            go(loop["home"])
            actions.append({"type": "craft", "item": loop["good"], "quantity": loop["q"]})
            go(loop["sell_town"])
            actions.append({"type": "sell", "item": loop["good"], "quantity": loop["q"]})
    return actions


def _trim_to_fit(actions, level, C, level_num, need):
    """Cut the action list back so `need` ticks remain before total_ticks.

    CP-SAT prices each loop in isolation; the travel *between* consecutive
    loops is not in that price, so the emitted list always overshoots the
    solver's budget. Trimming against a real simulation is exact.
    """
    sim = Sim(level, level_num=level_num, constants=C)
    sim.run(list(actions), pad=False)
    limit = level["run"]["total_ticks"] - need
    keep = 0
    for e in sim.log:
        if e["tick"] > limit:
            break
        keep = e["i"] + 1
    return actions[:keep]


def add_liquidation(actions, level, C, level_num, ticks, prevs, mp, passes=2):
    """Dump everything held at the end of the run.

    A sell action costs 1 tick regardless of quantity, so cashing out 170,000
    fish costs the same single tick as selling one. Town trickle piles up
    automatically all run and hoarded stock scores far less than Enteloot, so
    this is close to free money. Two passes, because trickle keeps arriving
    during the sell-off itself.
    """
    towns = set(level["towns"])
    need = 12 + passes * (len(C["resources"]) + len(C["recipes"]))
    actions = _trim_to_fit(actions, level, C, level_num, need)
    for _ in range(passes):
        sim = Sim(level, level_num=level_num, constants=C)
        # pad=False: measure what is actually held the moment the last action
        # ends. Padding to total_ticks would credit trickle that has not
        # arrived yet, and every sell would fail with "not enough held".
        sim.run(list(actions), pad=False)
        held = {k: v for k, v in sim.inv.items() if v > 0}
        if not held:
            break
        loc, extra = sim.location, []
        if loc not in towns:
            dest = min(towns, key=lambda t: ticks[loc].get(t, 10 ** 9))
            steps = mp.path_actions(prevs[loc], loc, dest)
            if steps:
                extra.extend(steps)
                loc = dest
        rates = level["towns"].get(loc, {}).get("item-rates", {})
        for item, qty in sorted(held.items()):
            if item in C["resources"] or item in rates:
                extra.append({"type": "sell", "item": item, "quantity": qty})
        if not extra:
            break
        actions.extend(extra)
    return actions


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--level", required=True)
    p.add_argument("--level-num", type=int, required=True)
    p.add_argument("--out", default="actions.txt")
    p.add_argument("--reserve", type=int, default=20,
                   help="ticks held back for the end-of-run sell-off and any building/upkeep work")
    p.add_argument("--no-liquidate", action="store_true",
                   help="skip the end-of-run sell-off")
    p.add_argument("--no-build", action="store_true",
                   help="skip the construction sweep (levels 2+)")
    p.add_argument("--no-upkeep", action="store_true",
                   help="skip upkeep boost insertion (level 4)")
    p.add_argument("--time-limit", type=float, default=20.0)
    args = p.parse_args()

    level = json.load(open(args.level))
    C = load_constants()
    boots = False
    mp = Map(level.get("routes", []), boots=boots,
             allow_fast=args.level_num >= 3)
    ticks, tolls, prevs = mp.all_pairs()

    loops = build_loops(level, C, args.level_num, ticks, tolls, prevs)
    print(f"candidate loops: {len(loops)}")
    budget = level["run"]["total_ticks"] - args.reserve
    picked, status = choose(loops, budget, level["run"]["starting_enteloot"], args.time_limit)
    print(f"solver: {status}, loops chosen: {sum(c for _, c in picked)}")
    for loop, count in picked:
        tag = loop.get("good") or loop.get("res")
        print(f"  x{count:<4} {loop['kind']:<5} {tag:<15} home={loop['home']:<10} "
              f"ticks={loop['ticks']:<4} profit={loop['profit']}")

    actions = emit(picked, level, mp, ticks, tolls, prevs, C)
    if args.level_num >= 2 and not args.no_build:
        from build import plan_builds
        actions = plan_builds(level, C, args.level_num, actions, mp, ticks, tolls, prevs)
    if args.level_num >= 4 and not args.no_upkeep:
        from upkeep import add_upkeep
        actions = add_upkeep(level, C, args.level_num, actions)
    if not args.no_liquidate:
        base = Sim(level, level_num=args.level_num, constants=C).run(list(actions))
        n_before = len(actions)
        actions = add_liquidation(actions, level, C, args.level_num, ticks, prevs, mp)
        after = Sim(level, level_num=args.level_num, constants=C).run(list(actions))
        print(f"end-of-run sell-off: enteloot {base['enteloot']} -> {after['enteloot']} "
              f"(+{after['enteloot'] - base['enteloot']}), "
              f"actions {n_before} -> {len(actions)}")
    with open(args.out, "w") as fh:
        json.dump({"actions": actions}, fh, indent=1)
    print(f"wrote {len(actions)} actions -> {args.out}")

    sim = Sim(level, level_num=args.level_num, constants=C)
    rep = sim.run(actions)
    print("\nsimulated result:")
    print(json.dumps(rep, indent=2))
    if rep["invalid_actions"]:
        print("\nfirst invalid actions:")
        for e in [e for e in sim.log if not e["ok"]][:5]:
            print(" ", e["i"], e["action"], "->", e["reason"])


if __name__ == "__main__":
    main()
