#!/usr/bin/env python3
"""verify_no_leak.py — Leakage Sanity Check for P-1 no-leak Phase B.

Runs N MetaOptimizer calls side-by-side under two contexts:

  (A) LEAK context: prompt built WITH gold-answer "Expected:" lines (legacy).
  (B) NO-LEAK context: prompt built with constrained-vocab failure_category
      + Option D retrieval metrics; gold answer stripped.

If the proposal distributions from A and B are nearly identical
(low KL divergence), the judge commentary may implicitly leak gold info.
If they differ (KL > 0.1), the two contexts carry different information —
which is the expected behavior (we WANT the no-leak optimizer to decide
based on materially different evidence).

Also performs a textual leakage scan on the no-leak prompt: reports any
reference tokens (4+ chars) that appear in the no-leak prompt for manual
inspection.

Inputs:
  - A round{N}_locomo.json file (from a completed eval round with NO_LEAK=1)
    that contains both `reference` and `failure_category` / `retrieval_metrics`.

Usage:
  python verify_no_leak.py --eval-json results/.../round0_locomo.json --n-trials 10
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

# Make runner + pipeline importable
sys.path.insert(0, "/home/kailong/Quant/memory-eval")

from run_self_evolution_v1_locomo import (  # type: ignore
    build_meta_optimizer_prompt,
    call_llm,
    LOCOMO_CATEGORIES,
)


def records_to_round_results(records: list[dict]) -> dict:
    """Regroup a flat list of per-QA records into the cat_results dict shape
    that build_meta_optimizer_prompt expects.
    """
    per_cat: dict[str, list] = defaultdict(list)
    for r in records:
        if r.get("strategy") != "v1_memory":
            continue
        per_cat[r.get("category", "unknown")].append(r)

    def _build_detail(r: dict, cat: str) -> dict:
        return {
            "question": r.get("question", ""),
            "reference": r.get("reference", ""),
            "prediction": r.get("prediction", ""),
            "score": r.get("judge_score", 0),
            "category": cat,
            "sample_id": r.get("sample_id", ""),
            "failure_category": r.get("failure_category", ""),
            "retrieval_metrics": r.get("retrieval_metrics", {}) or {},
        }

    out: dict = {}
    for cat in list(LOCOMO_CATEGORIES) + [c for c in per_cat if c not in LOCOMO_CATEGORIES]:
        cat_records = per_cat.get(cat, [])
        if not cat_records:
            out[cat] = {"score": 0.0, "n": 0, "details": []}
            continue
        score = sum(r.get("judge_score", 0) for r in cat_records) / len(cat_records)
        out[cat] = {
            "score": score,
            "n": len(cat_records),
            "details": [_build_detail(r, cat) for r in cat_records],
        }
    return out


def proposals_to_key(proposals: list[dict]) -> tuple:
    """Canonicalize the MetaOptimizer's top-K proposals into a hashable key
    for distribution estimation. We take the top-3 by confidence, keeping
    (param, repr(value)) tuples.
    """
    filtered = [p for p in proposals if isinstance(p, dict) and "param" in p]
    filtered.sort(key=lambda p: -float(p.get("confidence", 0) or 0))
    top = []
    for p in filtered[:3]:
        top.append((str(p.get("param", "")), json.dumps(p.get("value"), sort_keys=True)))
    return tuple(top)


def top1_to_key(proposals: list[dict]) -> tuple:
    filtered = [p for p in proposals if isinstance(p, dict) and "param" in p]
    filtered.sort(key=lambda p: -float(p.get("confidence", 0) or 0))
    if not filtered:
        return ("__none__", "null")
    p = filtered[0]
    return (str(p.get("param", "")), json.dumps(p.get("value"), sort_keys=True))


def kl_divergence(p_counts: Counter, q_counts: Counter, smoothing: float = 0.5) -> float:
    """Symmetric Laplace-smoothed KL over the union of keys."""
    keys = set(p_counts) | set(q_counts)
    p_total = sum(p_counts.values()) + smoothing * len(keys)
    q_total = sum(q_counts.values()) + smoothing * len(keys)
    kl_pq = 0.0
    kl_qp = 0.0
    for k in keys:
        p = (p_counts.get(k, 0) + smoothing) / p_total
        q = (q_counts.get(k, 0) + smoothing) / q_total
        kl_pq += p * math.log(p / q)
        kl_qp += q * math.log(q / p)
    return 0.5 * (kl_pq + kl_qp)


def tokenize_for_leakage_scan(s: str) -> set[str]:
    """Lowercase tokens of length >= 4, alphanumeric only. Used for coarse
    overlap checks between reference strings and the no-leak prompt."""
    s = str(s).lower()
    toks = re.findall(r"[a-z0-9]{4,}", s)
    # drop very common question words that are not informative
    stop = {"what", "when", "where", "which", "whose", "whom", "that", "this",
            "with", "from", "have", "been", "were", "will", "says", "said",
            "mentioned", "there", "about", "they", "them", "their", "your",
            "tell", "like", "something", "someone", "person"}
    return {t for t in toks if t not in stop}


def leakage_scan(prompt: str, references: list[str]) -> list[tuple[str, list[str]]]:
    """For each reference, list overlapping 4+ char tokens that appear in prompt.
    Returns [(ref_string, [overlapping_tokens]), ...] for refs that have any
    overlap."""
    prompt_tokens = tokenize_for_leakage_scan(prompt)
    hits: list[tuple[str, list[str]]] = []
    for ref in references:
        ref_toks = tokenize_for_leakage_scan(ref)
        if not ref_toks:
            continue
        overlap = sorted(ref_toks & prompt_tokens)
        if overlap:
            hits.append((ref, overlap))
    return hits


def current_policy_for_round_0() -> dict:
    # Matches INITIAL_POLICY in run_self_evolution_v1_locomo.py
    return {
        "card_pool_size": 20,
        "episode_top_k": 3,
        "bm25_weight": 0.0,
        "similarity_threshold": 0.7,
        "recency_weight": 0.0,
        "use_ce_rerank": False,
        "use_entity_boost": False,
        "use_temporal_boost": False,
        "use_l1_enrichment": False,
    }


def main():
    ap = argparse.ArgumentParser(description="P-1 No-Leak Sanity Check")
    ap.add_argument(
        "--eval-json",
        required=True,
        help="Path to round{N}_locomo.json produced by eval_pipeline with NO_LEAK=1 "
        "(must contain failure_category + retrieval_metrics).",
    )
    ap.add_argument("--n-trials", type=int, default=10, help="Paired trials per context (default 10)")
    ap.add_argument(
        "--out-dir",
        default="results/verify_no_leak",
        help="Directory for prompt/response dumps + final report",
    )
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    with open(args.eval_json) as f:
        records = json.load(f)
    round_results = records_to_round_results(records)

    current_policy = current_policy_for_round_0()

    # Build both prompts ONCE — they are deterministic given the data.
    prompt_leak = build_meta_optimizer_prompt(
        round_results, current_policy, round_num=0, no_leak=False
    )
    prompt_noleak = build_meta_optimizer_prompt(
        round_results, current_policy, round_num=0, no_leak=True
    )

    with open(os.path.join(args.out_dir, "prompt_leak.txt"), "w") as f:
        f.write(prompt_leak)
    with open(os.path.join(args.out_dir, "prompt_noleak.txt"), "w") as f:
        f.write(prompt_noleak)

    # Textual leakage scan: do reference tokens appear in the no-leak prompt?
    fail_refs: list[str] = []
    fail_categories_seen: Counter = Counter()
    sample_commentary: list[dict] = []
    for cat, data in round_results.items():
        for d in data.get("details", []):
            if d.get("score", 1.0) < 1.0:
                fail_refs.append(str(d.get("reference", "")))
                fc = d.get("failure_category") or "unknown"
                fail_categories_seen[fc] += 1
                if len(sample_commentary) < 20:
                    sample_commentary.append({
                        "question": str(d.get("question", ""))[:160],
                        "prediction": str(d.get("prediction", ""))[:160],
                        "score": d.get("score"),
                        "failure_category": fc,
                        "retrieval_metrics": d.get("retrieval_metrics", {}),
                    })

    leak_hits = leakage_scan(prompt_noleak, fail_refs)

    # ── Run N_TRIALS paired MetaOptimizer calls ───────────────────────────────
    print(f"[verify_no_leak] running {args.n_trials} paired trials...")
    top1_leak: Counter = Counter()
    top1_noleak: Counter = Counter()
    top3_leak: Counter = Counter()
    top3_noleak: Counter = Counter()
    all_responses = []

    for trial in range(args.n_trials):
        print(f"  trial {trial+1}/{args.n_trials}: LEAK ...", flush=True)
        r_leak = call_llm(prompt_leak)
        print(f"  trial {trial+1}/{args.n_trials}: NOLEAK ...", flush=True)
        r_noleak = call_llm(prompt_noleak)

        p_leak = r_leak.get("proposals", []) if isinstance(r_leak, dict) else []
        p_noleak = r_noleak.get("proposals", []) if isinstance(r_noleak, dict) else []

        top1_leak[top1_to_key(p_leak)] += 1
        top1_noleak[top1_to_key(p_noleak)] += 1
        top3_leak[proposals_to_key(p_leak)] += 1
        top3_noleak[proposals_to_key(p_noleak)] += 1

        all_responses.append({
            "trial": trial,
            "leak": r_leak,
            "noleak": r_noleak,
        })

    kl_top1 = kl_divergence(top1_leak, top1_noleak)
    kl_top3 = kl_divergence(top3_leak, top3_noleak)

    # Did both contexts actually produce different top-1? Fraction of trials
    # where top-1(leak) == top-1(noleak) under a fresh paired sampling check.
    same_top1 = 0
    for resp in all_responses:
        k_l = top1_to_key(resp["leak"].get("proposals", []) if isinstance(resp["leak"], dict) else [])
        k_n = top1_to_key(resp["noleak"].get("proposals", []) if isinstance(resp["noleak"], dict) else [])
        if k_l == k_n:
            same_top1 += 1
    same_top1_rate = same_top1 / max(1, args.n_trials)

    # Verdict
    kl_pass = kl_top1 > 0.1 or kl_top3 > 0.1
    commentary_clean = len(leak_hits) == 0  # strict: zero overlap

    report = {
        "eval_json": os.path.abspath(args.eval_json),
        "n_trials": args.n_trials,
        "total_fail_cases": len(fail_refs),
        "failure_category_distribution": dict(fail_categories_seen),
        "top1_proposal_distribution_leak": [
            {"key": list(k), "count": v} for k, v in top1_leak.most_common()
        ],
        "top1_proposal_distribution_noleak": [
            {"key": list(k), "count": v} for k, v in top1_noleak.most_common()
        ],
        "top3_proposal_distribution_leak": [
            {"key": [list(x) for x in k], "count": v} for k, v in top3_leak.most_common()
        ],
        "top3_proposal_distribution_noleak": [
            {"key": [list(x) for x in k], "count": v} for k, v in top3_noleak.most_common()
        ],
        "kl_divergence_top1": kl_top1,
        "kl_divergence_top3": kl_top3,
        "same_top1_rate": same_top1_rate,
        "leakage_scan_hits": [
            {"reference": ref, "overlap_tokens": toks} for ref, toks in leak_hits
        ],
        "leakage_scan_hit_count": len(leak_hits),
        "verdict": {
            "kl_divergence_ok": kl_pass,
            "commentary_clean_token_scan": commentary_clean,
            "overall_pass": kl_pass and len(leak_hits) <= max(2, int(0.05 * max(1, len(fail_refs)))),
        },
        "sample_commentary": sample_commentary,
    }

    out_path = os.path.join(args.out_dir, "verify_no_leak_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Also dump full per-trial responses for audit
    with open(os.path.join(args.out_dir, "paired_responses.json"), "w") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("verify_no_leak summary")
    print("=" * 60)
    print(f"  N trials:               {args.n_trials}")
    print(f"  Failures analyzed:      {len(fail_refs)}")
    print(f"  Failure-cat distrib:    {dict(fail_categories_seen)}")
    print(f"  KL(leak || noleak) top1:{kl_top1:.4f}")
    print(f"  KL(leak || noleak) top3:{kl_top3:.4f}")
    print(f"  Same top-1 rate:        {same_top1_rate:.2%}")
    print(f"  Leakage scan hits:      {len(leak_hits)} refs with overlap tokens")
    print(f"  Verdict: kl_ok={kl_pass}  commentary_clean={commentary_clean}")
    print(f"  Report: {out_path}")

    if not report["verdict"]["overall_pass"]:
        print("\n[FAIL] Sanity check did not pass. Inspect paired_responses.json and prompt_noleak.txt")
        sys.exit(2)
    print("\n[PASS] Sanity check passed.")


if __name__ == "__main__":
    main()
