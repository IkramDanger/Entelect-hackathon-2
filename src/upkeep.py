"""Upkeep insertion for Level 4.

Upkeep costs 5 ticks and doubles the current town's Enteloot production for
50 ticks (75 with a fire-station), refreshing rather than stacking. The plan
already stands in towns constantly, so: replay the plan, and whenever the
player is standing in a town whose boost is worth well more than the 5 ticks
it costs — and that town's boost is about to lapse — insert an upkeep.

Accepted only if the full simulation says it beats the plan without it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Sim  # noqa: E402


def add_upkeep(level, C, level_num, actions, verbose=print):
    if level_num < 4:
        return actions
    total = level["run"]["total_ticks"]

    base = Sim(level, level_num=level_num, constants=C)
    base_rep = base.run(list(actions))
    profit_per_tick = base_rep["enteloot"] / max(1, total)

    # a boost's worth: the doubled part of ~50 ticks of generation
    def boost_value(town):
        t = level["towns"][town]["enteloot"]
        return (50 // max(1, t["rate"])) * t["amount"]

    worth_it = {t for t in level["towns"]
                if boost_value(t) >= 3 * 5 * profit_per_tick}
    if not worth_it:
        verbose("upkeep: no town's boost beats 5 ticks of trading; skipped")
        return actions

    # replay step by step to know where the player stands at each action
    sim = Sim(level, level_num=level_num, constants=C)
    out, last = [], {}
    for i, a in enumerate(actions):
        out.append(a)
        if not sim.step(i, a):
            out.extend(actions[i + 1:])
            break
        loc, tick = sim.location, sim.tick
        if (loc in worth_it and tick < total * 0.95
                and tick - last.get(loc, -10 ** 9) >= 45):
            out.append({"type": "upkeep"})
            sim.step(-1, {"type": "upkeep"})
            last[loc] = sim.tick

    rep = Sim(level, level_num=level_num, constants=C).run(list(out))
    added = len(out) - len(actions)
    if rep["enteloot"] > base_rep["enteloot"] and rep["invalid_actions"] <= base_rep["invalid_actions"]:
        verbose(f"upkeep: +{added} boosts across {len(worth_it)} towns, "
                f"enteloot {base_rep['enteloot']} -> {rep['enteloot']}")
        return out
    verbose(f"upkeep: {added} boosts tried but did not pay "
            f"({base_rep['enteloot']} -> {rep['enteloot']}); keeping plan without")
    return actions
