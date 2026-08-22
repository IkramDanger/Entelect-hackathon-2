"""Deterministic simulator for Age of Enteland.

Transcribed from specification.pdf. Global constants are read from
supporting-resources/resources.json so there is one source of truth.

Usage:
    python engine.py --level level1.json --actions actions.txt [--level-num 1]
    python engine.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict

def find_resources(start=None):
    """Walk up from this file (then the cwd) looking for the constants file."""
    for base in (start or os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
        cur = os.path.abspath(base)
        while True:
            cand = os.path.join(cur, "supporting-resources", "resources.json")
            if os.path.exists(cand):
                return cand
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    raise FileNotFoundError(
        "supporting-resources/resources.json not found above "
        + os.path.dirname(os.path.abspath(__file__)))


def load_constants(path=None):
    with open(path or find_resources()) as fh:
        return json.load(fh)


class Town:
    def __init__(self, name, data):
        self.name = name
        self.prod_rate = data.get("production", {}).get("rate", 0)
        self.prod_base = dict(data.get("production", {}).get("resources", {}))
        self.upgrades = set(data.get("upgrades", []))
        self.affinities = set(data.get("affinities", []))
        self.item_rates = dict(data.get("item-rates", {}))
        self.enteloot_rate = data.get("enteloot", {}).get("rate", 0)
        self.enteloot_amount = data.get("enteloot", {}).get("amount", 0)
        self.prod_cycles = 0
        self.el_cycles = 0
        self.boost_until = -1

    def prod_amount(self, resource, C):
        amount = self.prod_base.get(resource, 0)
        for up, meta in C["upgrades"]["production"].items():
            if up in self.upgrades and meta["effect"].get("resource") == resource:
                amount *= 2
        return int(math.floor(amount))

    def el_pct(self, C):
        pct = 0.0
        for up, meta in C["upgrades"]["civic"].items():
            if up in self.upgrades and meta["effect"]["type"] == "enteloot_amount_pct":
                pct += meta["effect"]["value"]
        return pct

    def el_amount(self, C, tick):
        amount = int(math.floor(self.enteloot_amount * (1 + self.el_pct(C))))
        if tick <= self.boost_until:
            amount *= C["constants"]["upkeep_boost_multiplier"]
        return amount

    def el_rate(self, C):
        rate = self.enteloot_rate
        for up, meta in C["upgrades"]["civic"].items():
            if up in self.upgrades and meta["effect"]["type"] == "enteloot_rate_delta":
                rate = max(meta["effect"]["min"], rate + meta["effect"]["value"])
        return rate

    def boost_duration(self, C):
        base = C["constants"]["upkeep_boost_duration_ticks"]
        for up, meta in C["upgrades"]["civic"].items():
            if up in self.upgrades and meta["effect"]["type"] == "upkeep_boost_duration_pct":
                base = int(math.floor(base * (1 + meta["effect"]["value"])))
        return base


class Sim:
    def __init__(self, level, level_num=4, constants=None, trickle_mode="incremental"):
        self.C = constants or load_constants()
        self.level = level
        self.level_num = level_num
        self.trickle_mode = trickle_mode
        run = level["run"]
        self.total_ticks = run["total_ticks"]
        self.tick = 0
        self.enteloot = run["starting_enteloot"]
        self.location = run["starting_town"]
        self.inv = defaultdict(int)
        self.tools = set()
        self.towns = {n: Town(n, d) for n, d in level["towns"].items()}
        self.nodes = dict(level.get("nodes", {}))
        self.log = []
        self.sold_units = 0
        self.invested = 0
        self.ended = False
        self._build_routes(level.get("routes", []))

    # ---------- map ----------
    def _build_routes(self, routes):
        pairs = defaultdict(list)
        for r in routes:
            a, b = r["between"]
            pairs[frozenset((a, b))].append(r)
        self.routes = {}
        for key, rs in pairs.items():
            # A fast route is defined by charging a toll, not by being listed
            # second. Levels 1, 2 and 4 all contain pairs with two toll-free
            # routes; the slower of those is simply a worse standard route.
            free = [r for r in rs if r.get("toll", 0) == 0]
            tolled = [r for r in rs if r.get("toll", 0) > 0]
            std = min(free, key=lambda r: r["weight"]) if free else None
            fast = min(tolled, key=lambda r: r["weight"]) if tolled else None
            self.routes[key] = {"standard": std, "fast": fast}

    def edge(self, a, b, fast):
        entry = self.routes.get(frozenset((a, b)))
        if not entry:
            return None
        return entry["fast"] if fast else entry["standard"]  # None if absent

    def travel_ticks(self, weight):
        delta = -1 if "boots" in self.tools else 0
        return max(self.C["constants"]["min_travel_ticks"], weight + delta)

    def gather_ticks(self, base):
        delta = -1 if "pickaxe" in self.tools else 0
        return max(self.C["constants"]["min_gather_ticks"], base + delta)

    def craft_ticks(self, town):
        if "crafting" in self.towns[town].affinities:
            return self.C["constants"]["craft_time_affinity"]
        return self.C["constants"]["craft_time_base"]

    # ---------- passive systems ----------
    def _advance(self, ticks):
        target = self.tick + ticks
        for t in self.towns.values():
            if t.prod_rate > 0:
                done = target // t.prod_rate
                new = done - t.prod_cycles
                if new > 0:
                    for res in t.prod_base:
                        self.inv[res] += new * t.prod_amount(res, self.C)
                    t.prod_cycles = done
            rate = t.el_rate(self.C)
            if rate > 0:
                done = target // rate
                new = done - t.el_cycles
                if new > 0:
                    if t.boost_until >= self.tick and t.boost_until < target:
                        # split the window at boost expiry so the multiplier is exact
                        cut = t.boost_until
                        mid = min(done, cut // rate)
                        self.enteloot += max(0, mid - t.el_cycles) * t.el_amount(self.C, cut)
                        self.enteloot += (done - max(mid, t.el_cycles)) * t.el_amount(self.C, target)
                    else:
                        self.enteloot += new * t.el_amount(self.C, target)
                    t.el_cycles = done
        self.tick = target

    # ---------- action helpers ----------
    def _fail(self, idx, action, reason):
        if self.tick + self.C["constants"]["invalid_action_ticks"] > self.total_ticks:
            return self._cutoff(idx, action, reason)
        self._advance(self.C["constants"]["invalid_action_ticks"])
        self.log.append({"i": idx, "action": action, "ok": False, "reason": reason,
                         "ticks": 1, "tick": self.tick, "enteloot": self.enteloot})
        return True

    def _cutoff(self, idx, action, reason="tick budget exceeded"):
        self._advance(self.total_ticks - self.tick)
        self.log.append({"i": idx, "action": action, "ok": False, "reason": reason,
                         "ticks": 0, "tick": self.tick, "enteloot": self.enteloot})
        self.ended = True
        return False

    def _ok(self, idx, action, ticks, note=""):
        self._advance(ticks)
        self.log.append({"i": idx, "action": action, "ok": True, "note": note,
                         "ticks": ticks, "tick": self.tick, "enteloot": self.enteloot})
        return True

    def recipe_of(self, item):
        if item in self.C["recipes"]:
            return self.C["recipes"][item]
        if item in self.C["components"]:
            return self.C["components"][item]
        if item in self.C["tools"]:
            return self.C["tools"][item]
        return None

    def unlocked(self, feature):
        for lvl, feats in self.C["level_unlocks"].items():
            if feature in feats:
                return self.level_num >= int(lvl)
        return True

    # ---------- the seven actions ----------
    def step(self, idx, a):
        if not isinstance(a, dict) or "type" not in a:
            return self._fail(idx, a, "malformed action")
        kind = a["type"]
        handler = getattr(self, "_do_" + kind.replace("-", "_"), None)
        if handler is None:
            return self._fail(idx, a, "unknown action type")
        return handler(idx, a)

    def _do_travel(self, idx, a):
        dest = a.get("destination")
        if not isinstance(dest, str):
            return self._fail(idx, a, "missing destination")
        fast = bool(a.get("fast", False))
        if fast and not self.unlocked("fast_routes"):
            return self._fail(idx, a, "fast routes locked at this level")
        edge = self.edge(self.location, dest, fast)
        if edge is None:
            return self._fail(idx, a, "no such route")
        toll = edge.get("toll", 0)
        if toll > self.enteloot:
            return self._fail(idx, a, "cannot pay toll")
        ticks = self.travel_ticks(edge["weight"])
        if self.tick + ticks > self.total_ticks:
            return self._cutoff(idx, a)
        self.enteloot -= toll
        self.location = dest
        return self._ok(idx, a, ticks, f"toll {toll}")

    def _do_gather(self, idx, a):
        node = self.nodes.get(self.location)
        if node is None:
            return self._fail(idx, a, "not at a resource node")
        ticks = self.gather_ticks(node.get("gather-time", 2))
        if self.tick + ticks > self.total_ticks:
            return self._cutoff(idx, a)
        self.inv[node["resource"]] += node["yield"]
        return self._ok(idx, a, ticks, f"+{node['yield']} {node['resource']}")

    def _do_buy(self, idx, a):
        town = self.towns.get(self.location)
        item, qty = a.get("item"), a.get("quantity")
        if town is None:
            return self._fail(idx, a, "not in a town")
        if not isinstance(item, str) or not isinstance(qty, int) or qty <= 0:
            return self._fail(idx, a, "bad item/quantity")
        if item not in town.prod_base:
            return self._fail(idx, a, "town does not produce this resource")
        price = self.C["resources"].get(item, {}).get("buy_price")
        if price is None:
            return self._fail(idx, a, "resource cannot be bought")
        cost = price * qty
        if cost > self.enteloot:
            return self._fail(idx, a, "not enough enteloot")
        if self.tick + 1 > self.total_ticks:
            return self._cutoff(idx, a)
        self.enteloot -= cost
        self.inv[item] += qty
        return self._ok(idx, a, 1, f"-{cost} enteloot")

    def _do_sell(self, idx, a):
        town = self.towns.get(self.location)
        item, qty = a.get("item"), a.get("quantity")
        if town is None:
            return self._fail(idx, a, "not in a town")
        if not isinstance(item, str) or not isinstance(qty, int) or qty <= 0:
            return self._fail(idx, a, "bad item/quantity")
        if self.inv[item] < qty:
            return self._fail(idx, a, "not enough held")
        if item in self.C["resources"]:
            unit = self.C["resources"][item]["sell_price"]
        elif item in town.item_rates:
            unit = town.item_rates[item]
        else:
            return self._fail(idx, a, "item not sellable here")
        if self.tick + 1 > self.total_ticks:
            return self._cutoff(idx, a)
        self.inv[item] -= qty
        self.enteloot += unit * qty
        self.sold_units += qty
        return self._ok(idx, a, 1, f"+{unit * qty} enteloot")

    def _do_craft(self, idx, a):
        town = self.towns.get(self.location)
        item, qty = a.get("item"), a.get("quantity", 1)
        if town is None:
            return self._fail(idx, a, "not in a town")
        if not isinstance(item, str) or not isinstance(qty, int) or qty <= 0:
            return self._fail(idx, a, "bad item/quantity")
        if not self.unlocked("craft"):
            return self._fail(idx, a, "crafting locked at this level")
        recipe = self.recipe_of(item)
        if recipe is None:
            return self._fail(idx, a, "unknown recipe")
        if recipe.get("min_level", 1) > self.level_num:
            return self._fail(idx, a, "recipe locked at this level")
        if item in self.C["tools"]:
            if item in self.tools or qty != 1:
                return self._fail(idx, a, "tool already crafted or qty != 1")
        for res, need in recipe["inputs"].items():
            if self.inv[res] < need * qty:
                return self._fail(idx, a, f"missing {res}")
        ticks = self.craft_ticks(self.location) * qty
        if self.tick + ticks > self.total_ticks:
            return self._cutoff(idx, a)
        for res, need in recipe["inputs"].items():
            self.inv[res] -= need * qty
        if item in self.C["tools"]:
            self.tools.add(item)
        else:
            self.inv[item] += qty
        return self._ok(idx, a, ticks, f"+{qty} {item}")

    def _do_build(self, idx, a):
        town = self.towns.get(self.location)
        name = a.get("upgrade")
        if town is None:
            return self._fail(idx, a, "not in a town")
        if not isinstance(name, str):
            return self._fail(idx, a, "missing upgrade")
        if not self.unlocked("build"):
            return self._fail(idx, a, "building locked at this level")
        meta = self.C["upgrades"]["production"].get(name) or self.C["upgrades"]["civic"].get(name)
        if meta is None:
            return self._fail(idx, a, "unknown upgrade")
        if meta.get("min_level", 1) > self.level_num:
            return self._fail(idx, a, "upgrade locked at this level")
        if name in town.upgrades:
            return self._fail(idx, a, "already built in this town")
        pre = meta.get("prerequisite")
        if pre:
            if pre["type"] == "any_production_upgrades":
                built = len(town.upgrades & set(self.C["upgrades"]["production"]))
                if built < pre["count"]:
                    return self._fail(idx, a, "prerequisite not met")
            elif pre["type"] == "specific_upgrade" and pre["upgrade"] not in town.upgrades:
                return self._fail(idx, a, "prerequisite not met")
        for comp, need in meta["components"].items():
            if self.inv[comp] < need:
                return self._fail(idx, a, f"missing {comp}")
        if meta["enteloot_cost"] > self.enteloot:
            return self._fail(idx, a, "not enough enteloot")
        ticks = meta["build_time"]
        if self.tick + ticks > self.total_ticks:
            return self._cutoff(idx, a)
        for comp, need in meta["components"].items():
            self.inv[comp] -= need
        self.enteloot -= meta["enteloot_cost"]
        self.invested += meta["enteloot_cost"]
        town.upgrades.add(name)
        return self._ok(idx, a, ticks, f"built {name}")

    def _do_upkeep(self, idx, a):
        town = self.towns.get(self.location)
        if town is None:
            return self._fail(idx, a, "not in a town")
        if not self.unlocked("upkeep"):
            return self._fail(idx, a, "upkeep locked at this level")
        ticks = self.C["constants"]["upkeep_action_ticks"]
        if self.tick + ticks > self.total_ticks:
            return self._cutoff(idx, a)
        ok = self._ok(idx, a, ticks, "boost refreshed")
        town.boost_until = self.tick + town.boost_duration(self.C)
        return ok

    # ---------- run ----------
    def run(self, actions, pad=True):
        """Execute actions. pad=True credits passive systems for the leftover
        ticks, which is what scoring sees. Pass pad=False when you need the
        state as it stands the moment the last action finishes."""
        for i, a in enumerate(actions):
            if self.ended or not self.step(i, a):
                break
        if pad and not self.ended and self.tick < self.total_ticks:
            self._advance(self.total_ticks - self.tick)
        return self.report()

    def report(self):
        held = 0
        for item, qty in self.inv.items():
            if qty <= 0:
                continue
            if item in self.C["resources"]:
                held += self.C["resources"][item]["sell_price"] * qty
        infra = 0
        towns_with = 0
        for t in self.towns.values():
            score = sum(
                (self.C["upgrades"]["production"].get(u) or self.C["upgrades"]["civic"].get(u) or {})
                .get("score_value", 0) for u in t.upgrades)
            infra += score
            if score:
                towns_with += 1
        return {
            "final_tick": self.tick,
            "enteloot": self.enteloot,
            "held_resource_value": held,
            "inventory": {k: v for k, v in sorted(self.inv.items()) if v},
            "tools": sorted(self.tools),
            "units_sold": self.sold_units,
            "enteloot_invested": self.invested,
            "infrastructure_score": infra,
            "towns_developed": towns_with,
            "upgrades_by_town": {n: sorted(t.upgrades) for n, t in self.towns.items() if t.upgrades},
            "invalid_actions": sum(1 for e in self.log if not e["ok"]),
        }


def self_test():
    """Worked example, specification.pdf page 12: 16 ticks, 360 enteloot."""
    level = {
        "run": {"total_ticks": 16, "starting_town": "Demacia", "starting_enteloot": 200},
        "towns": {
            "Demacia": {"production": {"rate": 10, "resources": {"wheat": 2}},
                        "upgrades": [], "affinities": ["crafting"],
                        "item-rates": {"bread": 10}, "enteloot": {"rate": 0, "amount": 0}},
            "Piltover": {"production": {"rate": 10, "resources": {"fish": 2}},
                         "upgrades": [], "affinities": [],
                         "item-rates": {"bread": 40}, "enteloot": {"rate": 0, "amount": 0}},
        },
        "nodes": {"N1": {"type": "fields", "resource": "wheat", "yield": 6, "gather-time": 2}},
        "routes": [{"between": ["Demacia", "N1"], "weight": 2, "toll": 0},
                   {"between": ["Demacia", "Piltover"], "weight": 3, "toll": 0}],
    }
    actions = [
        {"type": "travel", "destination": "N1"},
        {"type": "gather"}, {"type": "gather"},
        {"type": "travel", "destination": "Demacia"},
        {"type": "craft", "item": "bread", "quantity": 4},
        {"type": "travel", "destination": "Piltover"},
        {"type": "sell", "item": "bread", "quantity": 4},
    ]
    sim = Sim(level, level_num=2)
    rep = sim.run(actions)
    for e in sim.log:
        print(f"  {e['i']}: {e['action']['type']:<7} ticks={e['ticks']} "
              f"tick={e['tick']} enteloot={e['enteloot']} ok={e['ok']}")
    # 2 wheat trickle at tick 10 is credited, so wheat 2 remains in inventory.
    assert rep["final_tick"] == 16, rep
    assert rep["enteloot"] == 360, rep
    assert rep["invalid_actions"] == 0, rep
    print("PASS  16 ticks, 360 enteloot -> matches the spec worked example")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--level")
    p.add_argument("--actions")
    p.add_argument("--level-num", type=int, default=4)
    p.add_argument("--resources", default=None)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    level = json.load(open(args.level))
    payload = json.load(open(args.actions))
    sim = Sim(level, level_num=args.level_num, constants=load_constants(args.resources))
    rep = sim.run(payload["actions"])
    if args.verbose:
        for e in sim.log:
            print(json.dumps(e))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
