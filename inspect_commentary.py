#!/usr/bin/env python3
"""inspect_commentary.py — manual audit helper.

Prints the first N failure cases from a round{N}_locomo.json, showing the
question, prediction, reference (for human sanity check), and the judge's
failure_category + retrieval_metrics. Humans verify that `failure_category`
never reveals gold-answer information and that retrieval_metrics are numeric
only.
"""
from __future__ import annotations

import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-json", required=True)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    with open(args.eval_json) as f:
        records = json.load(f)

    fails = [r for r in records if r.get("strategy") == "v1_memory" and r.get("judge_score", 1.0) < 1.0]
    if not fails:
        print("No failures found.")
        sys.exit(0)
    print(f"Total v1_memory records: {sum(1 for r in records if r.get('strategy') == 'v1_memory')}")
    print(f"Failure count: {len(fails)}")
    print()

    from collections import Counter
    cats = Counter(r.get("failure_category", "") for r in fails)
    print(f"Failure category distribution: {dict(cats)}")
    print()

    for i, r in enumerate(fails[: args.n]):
        print(f"--- fail {i+1}/{min(args.n, len(fails))} ---")
        print(f"  category:         {r.get('category')}")
        print(f"  question:         {r.get('question','')[:160]}")
        print(f"  prediction:       {str(r.get('prediction',''))[:160]}")
        print(f"  reference (gold): {str(r.get('reference',''))[:160]}")
        print(f"  score:            {r.get('judge_score')}")
        print(f"  failure_category: {r.get('failure_category','')}")
        print(f"  retrieval_metrics: {r.get('retrieval_metrics',{})}")
        print()


if __name__ == "__main__":
    main()
