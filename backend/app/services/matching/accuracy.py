"""Matching-accuracy harness (Pirog et al. 2026): α (splitting), β (lumping), γ (overall) errors
against a known truth set (e.g. tissue references or MisBase confirmed animals).

Pair-counting formulation:
  α = split_pairs / same_truth_pairs        (true recaptures assigned to different animals)
  β = lumped_pairs / diff_truth_pairs        (distinct individuals assigned to the same animal)
  γ = (split + lumped) / total_pairs
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Accuracy:
    alpha: float                 # false individuals (splitting)
    beta: float                  # false recaptures (lumping)
    gamma: float                 # overall
    n_animals_assigned: int
    n_animals_true: int


def accuracy(assigned: dict, truth: dict) -> Accuracy:
    """assigned / truth: node -> group id. Only nodes present in both are scored."""
    nodes = [n for n in assigned if n in truth]
    same_truth = split = diff_truth = lumped = 0
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            x, y = nodes[i], nodes[j]
            same_t = truth[x] == truth[y]
            same_a = assigned[x] == assigned[y]
            if same_t:
                same_truth += 1
                if not same_a:
                    split += 1
            else:
                diff_truth += 1
                if same_a:
                    lumped += 1
    total = same_truth + diff_truth
    return Accuracy(
        alpha=split / same_truth if same_truth else 0.0,
        beta=lumped / diff_truth if diff_truth else 0.0,
        gamma=(split + lumped) / total if total else 0.0,
        n_animals_assigned=len(set(assigned[n] for n in nodes)),
        n_animals_true=len(set(truth[n] for n in nodes)),
    )
