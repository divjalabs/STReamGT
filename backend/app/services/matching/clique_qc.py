"""Batch maximal-clique QC pass (Pirog): group by mutual compatibility, then flag where it
disagrees with the reference-anchored subgroups. Chaining-proof (a clique requires every member
to be mutually reliable), so disagreements surface reference drift / chained subgroups.
"""
from __future__ import annotations


def maximal_cliques(nodes, reliable_pairs: set) -> list:
    """Bron–Kerbosch (no pivot); small per-population graphs. Edges = reliable_pairs (frozensets)."""
    adj = {n: set() for n in nodes}
    for e in reliable_pairs:
        a, b = tuple(e)
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    cliques: list = []

    def bk(r: set, p: set, x: set):
        if not p and not x:
            cliques.append(frozenset(r))
            return
        for v in list(p):
            bk(r | {v}, p & adj[v], x & adj[v])
            p = p - {v}
            x = x | {v}

    bk(set(), set(nodes), set())
    return cliques


def clique_partition(nodes, reliable_pairs: set) -> dict:
    """Assign each node to one clique (its largest; ties by min member id) -> node -> group index."""
    cliques = sorted(maximal_cliques(nodes, reliable_pairs), key=lambda c: (-len(c), min(c)))
    part: dict = {}
    for idx, c in enumerate(cliques):
        for n in c:
            part.setdefault(n, idx)                  # first (largest) clique wins
    for n in nodes:                                  # isolated nodes: own group
        part.setdefault(n, f"solo-{n}")
    return part


def disagreements(part_a: dict, part_b: dict) -> list:
    """Pairs grouped together by one partition but not the other."""
    nodes = list(part_a)
    out = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            x, y = nodes[i], nodes[j]
            same_a = part_a[x] == part_a[y]
            same_b = part_b.get(x) == part_b.get(y)
            if same_a != same_b:
                out.append((x, y))
    return out
