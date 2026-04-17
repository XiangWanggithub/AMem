#!/usr/bin/env python3
"""Dry-run P0.5 variance-aware rollback against the existing P0 evolution_history.json.

For each historical round, compute what the new P0.5 should_rollback() would
decide, and compare to the P0 actual decision. Used to validate the new
function before re-running Phase B.
"""
import json
import sys

sys.path.insert(0, "/home/kailong/Quant/memory-eval")
from run_self_evolution_v1_locomo import should_rollback, VARIANCE_FLOOR_ABS, SIGMA_ESTIMATE


def main():
    path = "/home/kailong/Quant/memory-eval/results/self_evolution_v1_locomo/evolution_history.json"
    with open(path) as f:
        history = json.load(f)

    floor = max(VARIANCE_FLOOR_ABS, 2 * SIGMA_ESTIMATE)
    print(f"Variance floor = max({VARIANCE_FLOOR_ABS}, 2*{SIGMA_ESTIMATE}) = {floor:.3f}\n")

    # Walk rounds in order. For each round R>0, compare against the most-recent
    # non-rolled-back prior round (same logic the runner uses).
    print(f"{'Round':<6} {'Score':<7} {'OLD':<12} {'NEW':<12} {'reason'}")
    print("-" * 100)
    for i, h in enumerate(history):
        rnd = h["round"]
        score = h["avg_score"]
        old_status = h["status"]
        if i == 0:
            print(f"R{rnd:<5} {score:<7.3f} {old_status:<12} {'—':<12} (baseline, no decision)")
            continue
        # Find prior non-rolled-back entry
        prev = None
        for j in range(i - 1, -1, -1):
            if history[j]["status"] != "rolled_back":
                prev = history[j]
                break
        if prev is None:
            print(f"R{rnd:<5} {score:<7.3f} {old_status:<12} {'?':<12} (no prior good entry)")
            continue
        new_should_rb, reason = should_rollback(
            prev_score=prev["avg_score"],
            cur_score=score,
            prev_per_cat=prev["per_cat"],
            cur_per_cat=h["per_cat"],
        )
        new_status = "rolled_back" if new_should_rb else "accepted"
        marker = "" if new_status == old_status else "  <-- DIFF"
        print(f"R{rnd:<5} {score:<7.3f} {old_status:<12} {new_status:<12} {reason}{marker}")


if __name__ == "__main__":
    main()
