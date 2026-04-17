#!/usr/bin/env python3
"""Phase B Self-Evolution Runner for v0.1 hierarchical memory.

Usage:
  python run_self_evolution_v1.py --rounds 5 --n-per-type 10

The runner writes a JSON policy file (evolve_policy_v1.json) that
v1_memory_strategy.py reads via POLICY_CONFIG_PATH env var.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import re

# Add src path
sys.path.insert(0, "/home/kailong/Mem/workspace/meta-memory")

from src.llm.client import LLMClient, load_provider_env


QUESTION_TYPES = [
    "knowledge-update",
    "temporal-reasoning",
    "multi-session",
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
]

# Initial WEAK policy — everything off so MetaOptimizer has room to learn
INITIAL_POLICY = {
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

# Tunable ranges for the MetaOptimizer prompt
PARAM_RANGES = {
    "card_pool_size": "int 20-80",
    "episode_top_k": "int 3-10",
    "bm25_weight": "float 0.0-0.5",
    "similarity_threshold": "float 0.5-0.9",
    "recency_weight": "float 0.0-0.5",
    "use_ce_rerank": "bool",
    "use_entity_boost": "bool",
    "use_temporal_boost": "bool",
    "use_l1_enrichment": "bool (note: currently no effect — facts not ingested)",
}


def run_eval_round(n_per_type: int, round_num: int, results_dir: str, policy_path: str) -> dict:
    """Run LME 6-type stratified eval for v1 strategy, return per-type results with details."""
    all_results = {}

    for qt in QUESTION_TYPES:
        print(f"  [{qt}] running n={n_per_type}...")

        cmd = [
            "conda", "run", "-n", "metamem", "python", "eval_longmemeval.py",
            "--strategy", "v1",
            "--question-types", qt,
            "--n", str(n_per_type),
        ]

        env = os.environ.copy()
        env["POLICY_CONFIG_PATH"] = os.path.abspath(policy_path)

        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            cwd="/home/kailong/Quant/memory-eval"
        )

        if proc.returncode != 0:
            print(f"  [{qt}] subprocess stderr: {proc.stderr[-500:]}")

        # Find the latest v1 result file
        result_files = sorted(glob.glob("/home/kailong/Quant/memory-eval/results/longmemeval_v1_*.json"))
        if result_files:
            latest = result_files[-1]
            with open(latest) as f:
                eval_data = json.load(f)

            score = eval_data.get("overall_score", 0.0)
            details = []
            for r in eval_data.get("results", []):
                details.append({
                    "question": r.get("question", ""),
                    "answer": r.get("answer", ""),
                    "prediction": r.get("prediction", ""),
                    "score": r.get("judge_score", 0.0),
                    "question_type": qt,
                })

            all_results[qt] = {
                "score": score,
                "n": n_per_type,
                "details": details,
            }
            print(f"  [{qt}] score={score:.3f}")
        else:
            all_results[qt] = {"score": 0.0, "n": 0, "details": []}
            print(f"  [{qt}] FAILED (no result file found)")

    # Save round results
    round_file = os.path.join(results_dir, f"round{round_num}_summary.json")
    with open(round_file, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    avg = sum(r["score"] for r in all_results.values()) / len(all_results) if all_results else 0
    print(f"  Round {round_num} average: {avg:.3f}")
    return all_results


def build_meta_optimizer_prompt(
    round_results: dict,
    current_policy: dict,
    round_num: int,
    prev_results: dict | None = None,
) -> str:
    """Build the LLM prompt for MetaOptimizer analysis."""

    summary_lines = []
    failure_details = []

    for qt, data in round_results.items():
        score = data["score"]
        summary_lines.append(f"- {qt}: score={score:.3f}")

        for d in data.get("details", []):
            if d["score"] < 1.0:
                failure_details.append(
                    f"  [FAIL {qt}] Q: {str(d['question'])[:100]}\n"
                    f"    Expected: {str(d['answer'])[:80]}\n"
                    f"    Got: {str(d['prediction'])[:80]}\n"
                    f"    Score: {d['score']}"
                )

    failures_text = "\n".join(failure_details[:20])  # cap at 20 failures

    # Per-type delta section
    delta_section = ""
    if prev_results and round_num > 0:
        delta_lines = []
        for qt, data in round_results.items():
            curr_score = data["score"]
            prev_score = prev_results.get(qt, {}).get("score")
            if prev_score is not None:
                delta = curr_score - prev_score
                arrow = f"+{delta:.3f}" if delta >= 0 else f"{delta:.3f}"
                trend = "REGRESSION" if delta < -0.05 else ("IMPROVED" if delta > 0.05 else "stable")
                delta_lines.append(f"- {qt}: {prev_score:.3f} → {curr_score:.3f} ({arrow}) — {trend}")
        if delta_lines:
            delta_section = f"""
## Changes Since Last Round:
{chr(10).join(delta_lines)}
"""

    prompt = f"""You are a MetaOptimizer for a hierarchical memory retrieval system (v0.1). Your job is to analyze evaluation failures and propose global policy parameter changes to improve performance.

## Current Round: {round_num}

## Per-Type Results:
{chr(10).join(summary_lines)}
{delta_section}
## Current Policy:
{json.dumps(current_policy, indent=2)}

## Failed Questions (up to 20):
{failures_text}

## v0.1 Pipeline Architecture

The retrieval pipeline has exactly these stages in order:

**Stage 1 — Card Search:**
- `card_pool_size` candidates are retrieved from the card store.
- `bm25_weight` blends BM25 keyword score with dense embedding score (0.0 = dense-only, 0.5 = equal blend). BM25 helps with exact-name / keyword queries.
- `similarity_threshold` filters out cards below this cosine similarity (lower = more recall, higher = more precision).

**Stage 2 — Episode Expand:**
- Top `episode_top_k` episodes are fetched from the L0 episode store for each shortlisted card.
- If `use_entity_boost=True`: episodes whose text contains query entities receive +0.2 score boost per matching entity — helps cross-session and multi-hop queries.
- If `use_temporal_boost=True`: episodes whose stored date matches a date mentioned in the query receive +0.3 boost — critical for temporal-reasoning and knowledge-update queries.
- `recency_weight`: shifts final episode scores toward newer episodes (0.0 = no recency bias; higher = more recent episodes preferred).

**Stage 3 — CE Rerank:**
- If `use_ce_rerank=True`: a CrossEncoder model reranks expanded episodes. Very effective (+9pp in ablation). Recommended for most query types. Only skip if counting/aggregation recall is more important than precision.

**Stage 4 — Context Assembly:**
- `use_l1_enrichment`: appends L1 fact units to context. Currently has NO effect because facts are not ingested (extract_facts=False during ingest). Leave False unless ingest pipeline is updated.

## Common Failure Modes:
- "I don't know" → retrieval miss: increase `card_pool_size` or `episode_top_k`, enable `use_ce_rerank`
- Temporal questions wrong → enable `use_temporal_boost`; consider small `recency_weight` (0.1-0.2)
- Cross-session / multi-session queries failing → enable `use_entity_boost`
- Stale value returned for knowledge-update → enable both `use_temporal_boost` and `recency_weight`
- Counting queries ("how many sessions/times") → CE might over-filter; try lower `similarity_threshold` for more recall
- Preference/single-session queries → dense-only usually fine; BM25 rarely helps here

## Tunable Parameter Ranges:
{json.dumps(PARAM_RANGES, indent=2)}

## Your Task:
Analyze the failures and propose GLOBAL policy changes (this system has no per-type routing).

For parameters you want to change, explain:
1. Why the current value is causing failures
2. What the new value should be and why
3. Your confidence (0.0-1.0) — only high-confidence changes will be applied (threshold: 0.5)

Output ONLY a valid JSON object with this exact format:
{{
  "analysis": "brief overall analysis string",
  "proposals": [
    {{"param": "use_ce_rerank", "value": true, "rationale": "CE reranking showed strong ablation gains; currently disabled", "confidence": 0.85}},
    {{"param": "card_pool_size", "value": 40, "rationale": "...", "confidence": 0.7}}
  ]
}}
"""
    return prompt


def call_llm(prompt: str) -> dict:
    """Call LLM to get MetaOptimizer proposals. Retries on rate limit."""
    import asyncio

    load_provider_env()
    client = LLMClient()

    async def _call():
        response = await client.complete(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
        )
        return response

    last_error = None
    for attempt in range(3):
        try:
            if attempt > 0:
                wait = 30 * attempt  # 30s, 60s
                print(f"  Rate limited, waiting {wait}s before retry {attempt+1}/3...")
                time.sleep(wait)
            response = asyncio.run(_call())
            text = response.content
            break
        except Exception as e:
            last_error = e
            if "429" in str(e) or "rate" in str(e).lower():
                continue
            raise
    else:
        print(f"  LLM call failed after 3 retries: {last_error}")
        return {"analysis": f"LLM call failed: {last_error}", "proposals": []}

    # Parse JSON from response
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return {"analysis": "Failed to parse LLM response", "proposals": []}


def apply_proposals(current_policy: dict, proposals: list, min_confidence: float = 0.5) -> dict:
    """Apply MetaOptimizer proposals to policy. Returns updated policy dict."""
    new_policy = dict(current_policy)
    applied = []

    for p in proposals:
        if p.get("confidence", 0) < min_confidence:
            print(f"  Skipping '{p.get('param')}' (confidence={p.get('confidence', 0):.2f} < {min_confidence})")
            continue

        param = p.get("param", "")
        value = p.get("value")

        if param not in new_policy:
            print(f"  Skipping unknown param '{param}'")
            continue

        new_policy[param] = value
        applied.append(f"{param}={value!r} (confidence={p.get('confidence', 0):.2f})")

    print(f"  Applied {len(applied)} proposals: {applied}")
    return new_policy


def main():
    parser = argparse.ArgumentParser(description="Phase B Self-Evolution Runner for v0.1 hierarchical memory")
    parser.add_argument("--rounds", type=int, default=5, help="Number of evolution rounds")
    parser.add_argument("--n-per-type", type=int, default=10, help="Questions per type per round")
    parser.add_argument("--results-dir", default="results/self_evolution_v1", help="Output directory")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Min confidence to apply a proposal")
    parser.add_argument("--policy-path", default="evolve_policy_v1.json", help="Path to write/read policy JSON")
    args = parser.parse_args()

    os.makedirs(args.results_dir, exist_ok=True)

    print("=" * 60)
    print("Phase B Self-Evolution — v0.1 Hierarchical Memory")
    print(f"Rounds: {args.rounds}, N per type: {args.n_per_type}")
    print(f"Policy file: {args.policy_path}")
    print("=" * 60)

    # Step 1: Write initial WEAK policy
    current_policy = dict(INITIAL_POLICY)
    with open(args.policy_path, "w") as f:
        json.dump(current_policy, f, indent=2)
    print(f"\nInitial (weak) policy written to {args.policy_path}")
    print(json.dumps(current_policy, indent=2))

    history = []
    prev_results: dict | None = None

    for round_num in range(args.rounds):
        print(f"\n{'='*60}")
        print(f"Round {round_num}")
        print(f"{'='*60}")

        # Step 2a: Run eval
        print("Running eval...")
        results = run_eval_round(args.n_per_type, round_num, args.results_dir, args.policy_path)

        avg = sum(r["score"] for r in results.values()) / len(results) if results else 0.0
        history.append({
            "round": round_num,
            "avg_score": avg,
            "per_type": {qt: r["score"] for qt, r in results.items()},
            "policy": dict(current_policy),
        })

        # Step 2b: Save round summary (already done inside run_eval_round)

        # Step 2c: Convergence check
        if avg >= 0.70:
            print(f"\nConverged at round {round_num}! avg={avg:.3f} >= 0.70")

        if round_num < args.rounds - 1:
            # Step 2d: Build MetaOptimizer prompt
            print("\nCalling MetaOptimizer...")
            prompt = build_meta_optimizer_prompt(
                results, current_policy, round_num, prev_results=prev_results
            )

            # Save prompt for debugging
            with open(os.path.join(args.results_dir, f"round{round_num}_prompt.txt"), "w") as f:
                f.write(prompt)

            print("  Waiting 30s before MetaOptimizer call (rate limit cooldown)...")
            time.sleep(30)

            # Step 2e: Call LLM
            llm_response = call_llm(prompt)

            # Save LLM response
            with open(os.path.join(args.results_dir, f"round{round_num}_response.json"), "w") as f:
                json.dump(llm_response, f, indent=2, ensure_ascii=False)

            print(f"  Analysis: {llm_response.get('analysis', 'N/A')[:200]}")

            # Step 2f: Apply proposals
            proposals = llm_response.get("proposals", [])
            current_policy = apply_proposals(current_policy, proposals, args.min_confidence)

            # Step 2g: Write updated policy JSON
            with open(args.policy_path, "w") as f:
                json.dump(current_policy, f, indent=2)
            print(f"  Updated policy written to {args.policy_path}")
            print(f"  New policy: {json.dumps(current_policy)}")

        prev_results = results

    # Final summary table
    print(f"\n{'='*60}")
    print("Evolution History")
    print(f"{'='*60}")
    header = "Round | Avg   | " + " | ".join(f"{qt[:12]:12}" for qt in QUESTION_TYPES)
    print(header)
    print("-" * len(header))
    for h in history:
        row = f"  {h['round']:3d} | {h['avg_score']:.3f} | "
        row += " | ".join(f"{h['per_type'].get(qt, 0.0):.3f}        " for qt in QUESTION_TYPES)
        print(row)

    # Save full history
    with open(os.path.join(args.results_dir, "evolution_history.json"), "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {args.results_dir}/")
    print(f"Final policy: {args.policy_path}")


if __name__ == "__main__":
    main()
