"""Map layer: shortest paths with tolls, and OR-Tools stop ordering.

Travel cost is two-dimensional (ticks and Enteloot toll). Dijkstra here
minimises ticks first, then toll, which is the right default because ticks
are the binding constraint in every level. Pass toll_weight > 0 to trade
ticks against Enteloot explicitly.
"""
from __future__ import annotations

import heapq
from collections import defaultdict


class Map:
    def __init__(self, routes, boots=False, allow_fast=True):
        self.adj = defaultdict(list)   # a -> [(b, weight, toll, fast)]
        pairs = defaultdict(list)
        for r in routes:
            a, b = r["between"]
            pairs[frozenset((a, b))].append(r)
        for key, rs in pairs.items():
            a, b = tuple(key) if len(key) == 2 else (next(iter(key)),) * 2
            for r in rs:
                toll = r.get("toll", 0)
                fast = toll > 0          # a fast route is one that charges a toll
                if fast and not allow_fast:
                    continue
                w = max(1, r["weight"] - 1) if boots else r["weight"]
                self.adj[a].append((b, w, toll, fast))
                self.adj[b].append((a, w, toll, fast))
        self.vertices = sorted(self.adj)

    def dijkstra(self, src, toll_weight=0.0):
        """Return (dist_ticks, dist_toll, prev) keyed by vertex."""
        best = {src: (0.0, 0, 0)}          # vertex -> (score, ticks, toll)
        prev = {}
        pq = [(0.0, 0, 0, src)]
        while pq:
            score, ticks, toll, u = heapq.heappop(pq)
            if best.get(u, (float("inf"),))[0] < score:
                continue
            for v, w, tl, fast in self.adj[u]:
                ns, nt, ntl = score + w + toll_weight * tl, ticks + w, toll + tl
                if ns < best.get(v, (float("inf"),))[0]:
                    best[v] = (ns, nt, ntl)
                    prev[v] = (u, fast)
                    heapq.heappush(pq, (ns, nt, ntl, v))
        return ({k: v[1] for k, v in best.items()},
                {k: v[2] for k, v in best.items()}, prev)

    def all_pairs(self, toll_weight=0.0):
        ticks, tolls, prevs = {}, {}, {}
        for v in self.vertices:
            ticks[v], tolls[v], prevs[v] = self.dijkstra(v, toll_weight)
        return ticks, tolls, prevs

    def path_actions(self, prev, src, dst):
        """Rebuild the travel actions for src -> dst from a prev table."""
        if src == dst:
            return []
        steps, cur = [], dst
        while cur != src:
            if cur not in prev:
                return None
            u, fast = prev[cur]
            step = {"type": "travel", "destination": cur}
            if fast:
                step["fast"] = True
            steps.append(step)
            cur = u
        steps.reverse()
        return steps


def order_stops(start, stops, ticks):
    """Order stops into a short tour start -> stops... -> start.

    Uses OR-Tools routing when available, otherwise nearest-neighbour.
    """
    stops = list(dict.fromkeys(stops))
    if len(stops) <= 1:
        return stops
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        return _nearest_neighbour(start, stops, ticks)
    pts = [start] + stops
    mgr = pywrapcp.RoutingIndexManager(len(pts), 1, 0)
    routing = pywrapcp.RoutingModel(mgr)

    def cb(i, j):
        a, b = pts[mgr.IndexToNode(i)], pts[mgr.IndexToNode(j)]
        return int(ticks[a].get(b, 10**6))

    idx = routing.RegisterTransitCallback(cb)
    routing.SetArcCostEvaluatorOfAllVehicles(idx)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    sol = routing.SolveWithParameters(params)
    if sol is None:
        return _nearest_neighbour(start, stops, ticks)
    out, i = [], routing.Start(0)
    while not routing.IsEnd(i):
        node = mgr.IndexToNode(i)
        if node != 0:
            out.append(pts[node])
        i = sol.Value(routing.NextVar(i))
    return out


def _nearest_neighbour(start, stops, ticks):
    left, cur, out = list(stops), start, []
    while left:
        nxt = min(left, key=lambda s: ticks[cur].get(s, 10**6))
        out.append(nxt)
        left.remove(nxt)
        cur = nxt
    return out
