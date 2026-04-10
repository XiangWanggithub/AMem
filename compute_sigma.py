"""Compute σ (observation std dev) from two calibration runs.

Usage:
    python compute_sigma.py --locomo1 results/sma_calib_locomo_1.json \
                            --locomo2 results/sma_calib_locomo_2.json \
                            --lme-dir results/ --lme-suffix run
    python compute_sigma.py --locomo1 r1.json --locomo2 r2.json  # LoCoMo only

σ formula (single-point estimate from 2 runs):
    σ = |score1 - score2| / sqrt(2)

Reference: feature-adaptive-memory-mode.md §Smoke Matrix §Phase A.0
"""
import argparse
import json
import math
import os
from pathlib import Path


def load_score(path: str) -> float:
    """Load overall judge score from an eval result JSON file."""
    with open(path) as f:
        data = json.load(f)
    # eval_pipeline.py format: list of dicts with judge_score
    if isinstance(data, list):
        scores = [r["judge_score"] for r in data if "judge_score" in r]
        return sum(scores) / len(scores) if scores else 0.0
    # eval_longmemeval.py format: dict with overall_score
    if isinstance(data, dict):
        return float(data.get("overall_score", 0.0))
    return 0.0


def sigma(score1: float, score2: float) -> float:
    return abs(score1 - score2) / math.sqrt(2)


def load_lme_merged(results_dir: str, suffix: str) -> float | None:
    """Merge all 6 question-type files for a single LME run into one score."""
    types = [
        "single-session-user", "single-session-assistant", "single-session-preference",
        "multi-session", "temporal-reasoning", "knowledge-update",
    ]
    all_scores = []
    for qt in types:
        path = os.path.join(results_dir, f"sma_calib_lme_{qt}_{suffix}.json")
        if not os.path.exists(path):
            print(f"  [missing] {path}")
            return None
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            results = data.get("results", [])
            all_scores.extend(r["judge_score"] for r in results if "judge_score" in r)
    return sum(all_scores) / len(all_scores) if all_scores else None


def main():
    parser = argparse.ArgumentParser(description="Compute σ from 2 calibration runs")
    parser.add_argument("--locomo1", default="results/sma_calib_locomo_1.json")
    parser.add_argument("--locomo2", default="results/sma_calib_locomo_2.json")
    parser.add_argument("--lme-dir", default="results/")
    parser.add_argument("--lme-suffix", default="run",
                        help="Suffix used in filenames: sma_calib_lme_{type}_{suffix}1.json etc.")
    args = parser.parse_args()

    print("=" * 55)
    print("Phase A σ Calibration Results")
    print("=" * 55)

    # LoCoMo σ
    if os.path.exists(args.locomo1) and os.path.exists(args.locomo2):
        s1 = load_score(args.locomo1)
        s2 = load_score(args.locomo2)
        σ_loco = sigma(s1, s2)
        print(f"\nLoCoMo (conv-26):")
        print(f"  run1 = {s1:.4f}")
        print(f"  run2 = {s2:.4f}")
        print(f"  σ_LoCoMo = {σ_loco:.4f}")
        print(f"  2σ threshold = {2*σ_loco:.4f}")
    else:
        print(f"\nLoCoMo: files not found yet")
        print(f"  looking for: {args.locomo1}, {args.locomo2}")

    # LME σ
    lme1 = load_lme_merged(args.lme_dir, f"{args.lme_suffix}1")
    lme2 = load_lme_merged(args.lme_dir, f"{args.lme_suffix}2")
    if lme1 is not None and lme2 is not None:
        σ_lme = sigma(lme1, lme2)
        print(f"\nLongMemEval (30 stratified):")
        print(f"  run1 = {lme1:.4f}")
        print(f"  run2 = {lme2:.4f}")
        print(f"  σ_LME = {σ_lme:.4f}")
        print(f"  2σ threshold = {2*σ_lme:.4f}")

        if os.path.exists(args.locomo1) and os.path.exists(args.locomo2):
            print(f"\n{'='*55}")
            print("Smoke Matrix Thresholds:")
            print(f"  Exit 1 (exhaust not rescue LME): exhaustive(LME) - selective(LME) < {σ_lme:.4f}")
            print(f"  Exit 2 (hybrid kills LoCoMo):   hybrid(LoCoMo) - selective(LoCoMo) < -{2*σ_loco:.4f}")
            print(f"  Pass 1 (mode difference detectable): Δ > σ_benchmark in ≥1 benchmark")
            print(f"  Pass 2 (exhaustive rescues LME): exhaustive(LME) > selective(LME) + {σ_lme:.4f}")
    else:
        print(f"\nLME: files not complete yet (checking {args.lme_dir}sma_calib_lme_*_{args.lme_suffix}1/2.json)")

    print("=" * 55)


if __name__ == "__main__":
    main()
