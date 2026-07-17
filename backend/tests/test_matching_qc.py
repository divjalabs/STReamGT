"""Clique-QC (maximal cliques + disagreement detection) and the α/β/γ accuracy harness."""
from app.services.matching.clique_qc import maximal_cliques, clique_partition, disagreements
from app.services.matching.accuracy import accuracy

fs = frozenset


def test_maximal_cliques_and_chaining():
    # A-B-C chain (A~B, B~C) but A NOT ~ C: cliques are {A,B} and {B,C}, NOT {A,B,C}.
    nodes = ["A", "B", "C"]
    pairs = {fs(("A", "B")), fs(("B", "C"))}
    cliques = {frozenset(c) for c in maximal_cliques(nodes, pairs)}
    assert fs({"A", "B"}) in cliques and fs({"B", "C"}) in cliques
    assert fs({"A", "B", "C"}) not in cliques          # chaining prevented

    # a fully-connected triangle IS one clique
    tri = {fs(("A", "B")), fs(("B", "C")), fs(("A", "C"))}
    assert fs({"A", "B", "C"}) in {frozenset(c) for c in maximal_cliques(nodes, tri)}


def test_disagreements():
    # reference-anchored lumps A,B,C into one group; cliques split the chain -> disagreement
    ref_part = {"A": 0, "B": 0, "C": 0}
    clique_part = clique_partition(["A", "B", "C"], {fs(("A", "B")), fs(("B", "C"))})
    assert len(disagreements(ref_part, clique_part)) >= 1


def test_accuracy_perfect_and_errors():
    truth = {1: "X", 2: "X", 3: "Y", 4: "Y"}
    perfect = {1: "a", 2: "a", 3: "b", 4: "b"}
    acc = accuracy(perfect, truth)
    assert acc.alpha == 0 and acc.beta == 0 and acc.gamma == 0
    assert acc.n_animals_assigned == 2 and acc.n_animals_true == 2

    # split X into two (1 vs 2): 2 same-truth pairs (X-pair, Y-pair), only the X-pair is split
    split = {1: "a", 2: "c", 3: "b", 4: "b"}
    assert accuracy(split, truth).alpha == 0.5

    # lump X and Y together -> diff-truth pairs lumped -> beta > 0
    lump = {1: "a", 2: "a", 3: "a", 4: "a"}
    assert accuracy(lump, truth).beta > 0
