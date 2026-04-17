#!/usr/bin/env python3
"""Phase B Self-Evolution Runner for v0.1 — LoCoMo benchmark.

Uses LoCoMo as the verification benchmark (Codex: LoCoMo baseline 0.739 is stable,
use it as Phase B main verification scene).

Usage:
  python run_self_evolution_v1_locomo.py --rounds 8
"""
import argparse
import json
import os
import subprocess
import sys
import time
import re
from collections import defaultdict

# Add src path
sys.path.insert(0, "/home/kailong/Mem/workspace/meta-memory")

from src.llm.client import LLMClient, load_provider_env


LOCOMO_CATEGORIES = [
    "single-hop",
    "temporal",
    "multi-hop",
    "open-domain",
    "adversarial",
]

# P0.5 — variance-aware rollback constants
VARIANCE_FLOOR_ABS = 0.03           # absolute score floor
SIGMA_ESTIMATE = 0.023              # σ estimated from R1/R3/R7 same-policy stddev (P0 prior run)
SMALL_N_CATEGORIES = {"multi-hop": 13}   # F1 FIX: multi-hop is the actual small-n category
SMALL_N_FLIP_TOLERANCE = 0.01       # numeric tolerance for detecting 1/n single-sample flip
# F1 FIX: actual counts measured from round0 (304 QA total, not ~200)
LOCOMO_N_PER_CAT = {
    "single-hop": 43,
    "temporal": 63,
    "multi-hop": 13,
    "open-domain": 114,
    "adversarial": 71,
}


def should_rollback(
    prev_score: float,
    cur_score: float,
    prev_per_cat: dict,
    cur_per_cat: dict,
) -> tuple[bool, str]:
    """P0.5 — variance-aware rollback decision.

    Returns (should_rollback, reason_str).

    Two layers:
      1. Variance floor: if delta <= max(0.03, 2*sigma), do not roll back.
      2. Small-n protection: if delta is largely explained by a single-sample
         flip in a small-n category (multi-hop n=4 or open-domain n=2), and
         removing that category's contribution brings delta within floor, do
         not roll back.
    """
    delta = prev_score - cur_score
    variance_floor = max(VARIANCE_FLOOR_ABS, 2 * SIGMA_ESTIMATE)

    if delta <= variance_floor:
        return False, f"delta {delta:+.3f} within variance floor {variance_floor:.3f}"

    # Small-n category single-flip protection
    total_n_all = sum(LOCOMO_N_PER_CAT.values()) or 1
    for cat, n in SMALL_N_CATEGORIES.items():
        cat_prev = prev_per_cat.get(cat, 0.0) or 0.0
        cat_cur = cur_per_cat.get(cat, 0.0) or 0.0
        cat_delta = cat_prev - cat_cur
        expected_flip = 1.0 / n
        if abs(cat_delta - expected_flip) < SMALL_N_FLIP_TOLERANCE and cat_delta > 0:
            cat_weight = LOCOMO_N_PER_CAT.get(cat, n) / total_n_all
            delta_from_cat = cat_delta * cat_weight
            delta_without_cat = delta - delta_from_cat
            if delta_without_cat <= variance_floor:
                return (
                    False,
                    (
                        f"delta {delta:+.3f} explained by single flip in {cat} "
                        f"(n={n}, cat_delta={cat_delta:+.3f}); without-cat delta "
                        f"{delta_without_cat:+.3f} within floor {variance_floor:.3f}"
                    ),
                )

    return (
        True,
        f"regression {prev_score:.3f} -> {cur_score:.3f} "
        f"(delta {delta:+.3f}) exceeds variance floor {variance_floor:.3f}",
    )

# P1 — Conditional policy dispatch. When True, MetaOptimizer proposes
# per-query-type overrides and the policy file uses the conditional format:
#   {"default": {...}, "overrides": {"multi-hop": {...}, "temporal": {...}}}
# When False (default), the runner uses flat policy format (backwards compat).
# Leave False until Line A results confirm per-type dispatch is beneficial.
USE_CONDITIONAL_POLICY = False

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


def run_eval_round(
    round_num: int, results_dir: str, policy_path: str, no_leak: bool = False
) -> dict:
    """Run LoCoMo eval over conv-26 and conv-30 (all QA), return per-category results with details.

    When no_leak=True, sets NO_LEAK=1 for the subprocess so the judge emits
    constrained-vocab failure_category instead of implicitly relying on the
    caller to strip gold-answer strings downstream.
    """
    output_file = os.path.join(results_dir, f"round{round_num}_locomo.json")

    cmd = [
        "conda", "run", "--no-capture-output", "-n", "metamem", "python", "eval_pipeline.py",  # F2 FIX: prevent buffering deadlock
        "--data", "data/locomo10.json",
        "--strategy", "v1_memory",
        "--conv-ids", "conv-26", "conv-30",
        "--max-qa", "9999",
        "--output", output_file,
    ]

    env = os.environ.copy()
    env["POLICY_CONFIG_PATH"] = os.path.abspath(policy_path)
    if no_leak:
        env["NO_LEAK"] = "1"

    print(f"  Running LoCoMo eval (conv-26 + conv-30, all QA ~200)...")
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env,
        cwd="/home/kailong/Quant/memory-eval"
    )

    if proc.returncode != 0:
        print(f"  subprocess stderr: {proc.stderr[-500:]}")

    if not os.path.exists(output_file):
        print(f"  FAILED: output file not found: {output_file}")
        return {}

    with open(output_file) as f:
        records = json.load(f)

    # Filter to v1_memory strategy only
    v1_records = [r for r in records if r.get("strategy") == "v1_memory"]

    # Per-category aggregation
    per_cat: dict[str, list] = defaultdict(list)
    for r in v1_records:
        cat = r.get("category", "unknown")
        per_cat[cat].append(r)

    def _build_detail(r: dict, cat_name: str) -> dict:
        return {
            "question": r.get("question", ""),
            "reference": r.get("reference", ""),
            "prediction": r.get("prediction", ""),
            "score": r.get("judge_score", 0),
            "category": cat_name,
            "sample_id": r.get("sample_id", ""),
            # No-leak Phase B signals (empty strings / dicts if NO_LEAK=0)
            "failure_category": r.get("failure_category", ""),
            "retrieval_metrics": r.get("retrieval_metrics", {}) or {},
        }

    cat_results: dict[str, dict] = {}
    for cat in LOCOMO_CATEGORIES:
        cat_records = per_cat.get(cat, [])
        if cat_records:
            score = sum(r.get("judge_score", 0) for r in cat_records) / len(cat_records)
            details = [_build_detail(r, cat) for r in cat_records]
        else:
            score = 0.0
            details = []
        cat_results[cat] = {"score": score, "n": len(cat_records), "details": details}
        print(f"  [{cat}] score={score:.3f} (n={len(cat_records)})")

    # Also include unknown category if present
    for cat, cat_records in per_cat.items():
        if cat not in LOCOMO_CATEGORIES:
            score = sum(r.get("judge_score", 0) for r in cat_records) / len(cat_records)
            cat_results[cat] = {
                "score": score,
                "n": len(cat_records),
                "details": [_build_detail(r, cat) for r in cat_records],
            }

    # Overall score across all v1 records
    if v1_records:
        overall = sum(r.get("judge_score", 0) for r in v1_records) / len(v1_records)
    else:
        overall = 0.0
    print(f"  Round {round_num} overall: {overall:.3f}  (n={len(v1_records)})")

    # Save round summary
    round_file = os.path.join(results_dir, f"round{round_num}_summary.json")
    with open(round_file, "w") as f:
        json.dump(cat_results, f, indent=2, ensure_ascii=False)

    return cat_results


def _category_stddev(per_cat_scores: dict) -> float:
    """Compute population stddev of per-category scores (only categories with n>0)."""
    import math
    vals = [s for s in per_cat_scores.values() if s is not None]
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return math.sqrt(var)


def _aggregate_retrieval_metrics(round_results: dict) -> dict:
    """Mean across all QA of numeric retrieval_metrics fields (no leakage)."""
    keys = (
        "top_k_count",
        "similarity_mean",
        "similarity_std",
        "similarity_min",
        "similarity_max",
        "diversity",
        "unique_sessions",
    )
    sums: dict[str, float] = {k: 0.0 for k in keys}
    counts: dict[str, int] = {k: 0 for k in keys}
    for _cat, data in round_results.items():
        for d in data.get("details", []):
            rm = d.get("retrieval_metrics") or {}
            for k in keys:
                if k in rm and isinstance(rm[k], (int, float)):
                    sums[k] += float(rm[k])
                    counts[k] += 1
    out = {}
    for k in keys:
        out[k] = sums[k] / counts[k] if counts[k] > 0 else 0.0
    out["qa_with_metrics"] = max(counts.values()) if counts else 0
    return out


def build_meta_optimizer_prompt(
    round_results: dict,
    current_policy: dict,
    round_num: int,
    prev_results: dict | None = None,
    baseline_results: dict | None = None,
    banned_proposals: list | None = None,
    no_leak: bool = False,
) -> str:
    """Build the LLM prompt for MetaOptimizer analysis (LoCoMo-specific).

    P0-fix 3.3: per-category reward visibility with delta vs baseline (round 0),
    delta vs previous round, regression warnings, and category stddev.

    P-1 no-leak mode (no_leak=True):
      - Failure lines contain NO `Expected:` (gold answer) line.
      - Each failure carries a constrained-vocab `failure_category`.
      - An aggregate retrieval_metrics section (Option D) is appended.
    """

    summary_lines = []
    failure_details = []

    for cat, data in round_results.items():
        score = data["score"]
        n = data["n"]
        summary_lines.append(f"- {cat}: score={score:.3f} (n={n})")

        for d in data.get("details", []):
            if d["score"] < 1.0:
                if no_leak:
                    # No-leak failure line: NO reference string. failure_category
                    # is the only semantic signal, drawn from a fixed vocabulary.
                    fc = d.get("failure_category", "") or "unknown"
                    failure_details.append(
                        f"  [FAIL {cat}] Q: {str(d['question'])[:100]}\n"
                        f"    System answer: {str(d['prediction'])[:80]}\n"
                        f"    Failure category: {fc}\n"
                        f"    Score: {d['score']}"
                    )
                else:
                    # Legacy prompt (gold-answer-assisted; documented leakage).
                    failure_details.append(
                        f"  [FAIL {cat}] Q: {str(d['question'])[:100]}\n"
                        f"    Expected: {str(d['reference'])[:80]}\n"
                        f"    Got: {str(d['prediction'])[:80]}\n"
                        f"    Score: {d['score']}"
                    )

    failures_text = "\n".join(failure_details[:20])  # cap at 20 failures

    # Option D — retrieval metrics summary (no-leak mode only). These are
    # scalar aggregates of the retrieval pipeline's diagnostics; no text.
    retrieval_summary = ""
    if no_leak:
        rm = _aggregate_retrieval_metrics(round_results)
        if rm.get("qa_with_metrics", 0) > 0:
            retrieval_summary = f"""
## Retrieval Metrics (Option D; averaged across all QA, n={rm['qa_with_metrics']}):
- Mean top-K similarity (precision floor): {rm['similarity_mean']:.3f}
- Similarity std within top-K:             {rm['similarity_std']:.3f}
- Similarity range (min / max):            {rm['similarity_min']:.3f} / {rm['similarity_max']:.3f}
- Retrieval diversity (1 - mean pairwise Jaccard): {rm['diversity']:.3f}
- Mean top-K count returned:               {rm['top_k_count']:.1f}
- Mean unique session_dates in top-K:      {rm['unique_sessions']:.2f}

Interpretation hints for the optimizer:
- Low similarity_mean → retrieval match quality is weak; consider larger card_pool_size,
  lower similarity_threshold, or enabling BM25 (bm25_weight > 0) to capture exact-keyword
  matches.
- High similarity_std → top-K is noisy / mixed-quality; CE rerank can sharpen precision.
- Low diversity → top-K is redundant; episode_top_k may be too small or results too
  clustered; consider lowering similarity_threshold and/or diversification.
- unique_sessions==1 with multi-hop failures suggests retrieval is trapped in one session;
  entity_boost + larger episode_top_k helps cross-session recall.
"""

    # P0-fix 3.3: Per-category delta section (vs round 0 baseline AND vs previous round)
    delta_section = ""
    if round_num > 0 and (prev_results or baseline_results):
        delta_lines = []
        regression_cats = []
        for cat, data in round_results.items():
            curr_score = data["score"]
            n = data["n"]
            if n == 0:
                continue
            # Baseline (round 0) delta
            base_score = baseline_results.get(cat, {}).get("score") if baseline_results else None
            prev_score = prev_results.get(cat, {}).get("score") if prev_results else None

            parts = [f"- {cat}: {curr_score:.3f}"]
            if base_score is not None:
                base_delta = curr_score - base_score
                base_arrow = f"+{base_delta:.3f}" if base_delta >= 0 else f"{base_delta:.3f}"
                parts.append(f"(Δ vs round 0: {base_arrow})")
                if base_delta < -0.10:
                    regression_cats.append(f"{cat} ({base_arrow} vs baseline)")
                    parts.append("WARNING REGRESSION")
            if prev_score is not None and prev_score != base_score:
                prev_delta = curr_score - prev_score
                prev_arrow = f"+{prev_delta:.3f}" if prev_delta >= 0 else f"{prev_delta:.3f}"
                parts.append(f"[Δ vs round {round_num-1}: {prev_arrow}]")
            parts.append(f"[n={n}]")
            delta_lines.append(" ".join(parts))

        # Category stddev (overfitting indicator)
        cur_scores = {c: d["score"] for c, d in round_results.items() if d["n"] > 0}
        cur_stddev = _category_stddev(cur_scores)
        prev_stddev_line = ""
        if prev_results:
            prev_scores = {c: d["score"] for c, d in prev_results.items() if d["n"] > 0}
            prev_stddev = _category_stddev(prev_scores)
            trend = "rising" if cur_stddev > prev_stddev else "falling"
            prev_stddev_line = f" (prev round: {prev_stddev:.3f}, {trend})"

        warn_line = ""
        if regression_cats:
            warn_line = (
                "\n\n**CRITICAL**: The following categories regressed by >0.10 vs round 0 baseline: "
                + ", ".join(regression_cats)
                + ". Propose changes that RECOVER these categories — do NOT regress any category by >0.10."
            )
        stddev_warn = ""
        if cur_stddev > 0.25:
            stddev_warn = " — HIGH variance suggests overfitting to majority class; propose changes that balance all categories."

        delta_section = f"""
## Changes Since Last Round:
{chr(10).join(delta_lines)}

Category score stddev: {cur_stddev:.3f}{prev_stddev_line}{stddev_warn}{warn_line}
"""

    # P0-fix 3.1 support: list banned proposals so LLM does not re-propose rolled-back atoms
    banned_section = ""
    if banned_proposals:
        banned_lines = []
        for b in banned_proposals:
            banned_lines.append(f"- {b['param']} = {b['value']!r}  (regressed {b.get('from_score', 0):.3f} -> {b.get('to_score', 0):.3f})")
        banned_section = f"""
## Previously Rolled-Back Proposals (do NOT re-propose these exact atoms):
{chr(10).join(banned_lines)}
"""

    prompt = f"""You are a MetaOptimizer for a hierarchical memory retrieval system (v0.1) evaluated on the LoCoMo benchmark. Your job is to analyze evaluation failures and propose global policy parameter changes to improve performance.

## Current Round: {round_num}

## Per-Category Results (LoCoMo):
{chr(10).join(summary_lines)}
{delta_section}
## Current Policy:
{json.dumps(current_policy, indent=2)}
{banned_section}
## Failed Questions (up to 20):
{failures_text}
{retrieval_summary}
## v0.1 Pipeline Architecture

The retrieval pipeline has exactly these stages in order:

**Stage 1 — Card Search:**
- `card_pool_size` candidates are retrieved from the card store.
- `bm25_weight` blends BM25 keyword score with dense embedding score (0.0 = dense-only, 0.5 = equal blend). BM25 helps with exact-name / keyword queries.
- `similarity_threshold` filters out cards below this cosine similarity (lower = more recall, higher = more precision).

**Stage 2 — Episode Expand:**
- Top `episode_top_k` episodes are fetched from the L0 episode store for each shortlisted card.
- If `use_entity_boost=True`: episodes whose text contains query entities receive +0.2 score boost per matching entity — helps cross-session and multi-hop queries.
- If `use_temporal_boost=True`: episodes whose stored date matches a date mentioned in the query receive +0.3 boost — critical for temporal and date-anchored queries.
- `recency_weight`: shifts final episode scores toward newer episodes (0.0 = no recency bias; higher = more recent episodes preferred).

**Stage 3 — CE Rerank:**
- If `use_ce_rerank=True`: a CrossEncoder model reranks expanded episodes. Very effective (+9pp in ablation). Recommended for most query types. Only skip if counting/aggregation recall is more important than precision.

**Stage 4 — Context Assembly:**
- `use_l1_enrichment`: appends L1 fact units to context. Currently has NO effect because facts are not ingested (extract_facts=False during ingest). Leave False unless ingest pipeline is updated.

## LoCoMo Category-Specific Hints:
- **temporal**: Date-anchored questions ("when did X happen?"). Needs `use_temporal_boost=True` + `recency_weight > 0` (0.1-0.2). BM25 can help find exact date strings.
- **multi-hop**: Requires linking information across sessions. Needs `use_entity_boost=True` + larger `episode_top_k` (6-10). CE rerank helps precision.
- **single-hop**: Dense retrieval usually sufficient. CE rerank helps with precision. BM25 rarely needed.
- **open-domain**: Broader recall needed; lower `similarity_threshold`, larger `card_pool_size`.
- **adversarial**: High recall needed to find the correct fact vs. distractor. Increase `card_pool_size`, keep `similarity_threshold` low.

## Common LoCoMo Failure Modes:
- "I don't know" or hallucination → retrieval miss: increase `card_pool_size` or `episode_top_k`, enable `use_ce_rerank`
- Temporal questions wrong (e.g. "when did X?") → enable `use_temporal_boost`; consider small `recency_weight` (0.1-0.2)
- Multi-hop / cross-session queries failing → enable `use_entity_boost`; increase `episode_top_k`
- Adversarial questions (distractor answers) → lower `similarity_threshold` for more recall
- Open-domain missing context → increase `card_pool_size`, lower `similarity_threshold`

## Tunable Parameter Ranges:
{json.dumps(PARAM_RANGES, indent=2)}

## Your Task:
Analyze the LoCoMo failures and propose GLOBAL policy changes (this system has no per-category routing).

For parameters you want to change, explain:
1. Why the current value is causing failures
2. What the new value should be and why
3. Your confidence (0.0-1.0) — only high-confidence changes will be applied (threshold: 0.5)

**IMPORTANT — Sequential atom trial**: The runner will apply ONLY the single highest-confidence proposal this round (others are queued). So rank your proposals by confidence carefully — your top-confidence proposal is the only change that will actually take effect. List proposals in priority order.

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


def _validate_schema(parsed: dict) -> None:
    """Raise AssertionError if schema is invalid."""
    assert isinstance(parsed, dict), "response must be a JSON object"
    assert "analysis" in parsed, "missing 'analysis' field"
    assert "proposals" in parsed, "missing 'proposals' field"
    assert isinstance(parsed["proposals"], list), "'proposals' must be a list"
    for i, p in enumerate(parsed["proposals"]):
        assert isinstance(p, dict), f"proposal[{i}] must be an object"
        for k in ("param", "value", "rationale", "confidence"):
            assert k in p, f"proposal[{i}] missing '{k}'"
        assert isinstance(p["confidence"], (int, float)), f"proposal[{i}].confidence must be numeric"


def _llm_once(prompt: str) -> str:
    """Single LLM call with rate-limit retry. Returns raw text or raises."""
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
            return response.content
        except Exception as e:
            last_error = e
            if "429" in str(e) or "rate" in str(e).lower():
                continue
            raise
    raise RuntimeError(f"LLM call failed after 3 rate-limit retries: {last_error}")


def call_llm(prompt: str) -> dict:
    """Call LLM to get MetaOptimizer proposals.

    P0-fix 3.4: schema retry — if response doesn't parse or fails schema validation,
    retry up to 3 times appending an error hint to the prompt.
    """
    cur_prompt = prompt
    last_err = None
    for parse_attempt in range(3):
        try:
            text = _llm_once(cur_prompt)
        except Exception as e:
            print(f"  LLM call failed (parse attempt {parse_attempt+1}/3): {e}")
            return {"analysis": f"LLM call failed: {e}", "proposals": []}

        # Parse JSON from response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            last_err = "no JSON object found in response"
            print(f"  status: parse retry {parse_attempt+1}/3 — {last_err}")
            cur_prompt = (
                prompt
                + f"\n\n## Previous attempt #{parse_attempt+1} failed: {last_err}\n"
                + "Please respond with ONLY a valid JSON object (no markdown, no commentary) matching the schema shown above."
            )
            continue

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            last_err = f"JSON decode error: {e}"
            print(f"  status: parse retry {parse_attempt+1}/3 — {last_err}")
            cur_prompt = (
                prompt
                + f"\n\n## Previous attempt #{parse_attempt+1} failed: {last_err}\n"
                + "Please respond with ONLY a valid JSON object (no markdown, no commentary) matching the schema shown above."
            )
            continue

        try:
            _validate_schema(parsed)
            if parse_attempt > 0:
                print(f"  status: parse retry {parse_attempt+1}/3 succeeded")
            return parsed
        except AssertionError as e:
            last_err = f"schema validation: {e}"
            print(f"  status: parse retry {parse_attempt+1}/3 — {last_err}")
            cur_prompt = (
                prompt
                + f"\n\n## Previous attempt #{parse_attempt+1} failed schema validation: {e}\n"
                + 'Required schema: {"analysis": str, "proposals": [{"param": str, "value": any, "rationale": str, "confidence": float}, ...]}\n'
                + "Please respond with ONLY a valid JSON object matching this schema."
            )
            continue

    print(f"  status: parse failed after 3 retries — {last_err}")
    return {"analysis": f"Failed to parse LLM response after 3 retries: {last_err}", "proposals": []}


def apply_proposals(
    current_policy: dict,
    proposals: list,
    min_confidence: float = 0.5,
    banned: list | None = None,
) -> tuple[dict, dict | None]:
    """Apply ONLY the top-1 proposal (sequential atom trial — P0-fix 3.2).

    Returns (new_policy, applied_proposal_or_None).
    Skips proposals that are: below min_confidence, unknown param, no-op (same value),
    or in the banned list (already rolled-back).
    """
    new_policy = dict(current_policy)
    banned = banned or []
    banned_keys = {(b["param"], json.dumps(b["value"], sort_keys=True)) for b in banned}

    # Filter and rank by confidence
    candidates = []
    for p in proposals:
        param = p.get("param", "")
        value = p.get("value")
        conf = p.get("confidence", 0)
        if conf < min_confidence:
            print(f"  Skipping '{param}' (confidence={conf:.2f} < {min_confidence})")
            continue
        if param not in new_policy:
            print(f"  Skipping unknown param '{param}'")
            continue
        if new_policy[param] == value:
            print(f"  Skipping no-op '{param}={value!r}' (already current)")
            continue
        key = (param, json.dumps(value, sort_keys=True))
        if key in banned_keys:
            print(f"  Skipping banned (rolled-back) proposal '{param}={value!r}'")
            continue
        candidates.append(p)

    if not candidates:
        print("  No applicable proposals (after filtering); policy unchanged.")
        return new_policy, None

    candidates.sort(key=lambda p: -p.get("confidence", 0))
    top = candidates[0]
    new_policy[top["param"]] = top["value"]

    queued = [f"{p['param']}={p['value']!r}@{p.get('confidence',0):.2f}" for p in candidates[1:]]
    print(
        f"  Applied TOP-1 proposal: {top['param']}={top['value']!r} "
        f"(confidence={top.get('confidence', 0):.2f})"
    )
    if queued:
        print(f"  Queued for future rounds (not applied this round): {queued}")
    return new_policy, top


def main():
    parser = argparse.ArgumentParser(description="Phase B Self-Evolution Runner for v0.1 — LoCoMo benchmark")
    parser.add_argument("--rounds", type=int, default=5, help="Number of evolution rounds")
    # --n-per-conv removed: now uses all QA from conv-26 + conv-30 (~200 QA)
    parser.add_argument("--results-dir", default="results/self_evolution_v1_locomo", help="Output directory")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Min confidence to apply a proposal")
    parser.add_argument("--policy-path", default="locomo_evolve_policy_v1.json", help="Path to write/read policy JSON")
    parser.add_argument(
        "--no-leak",
        action="store_true",
        default=os.environ.get("NO_LEAK", "0") == "1",
        help=(
            "Enable No-Leakage Phase B (P-1). Judge emits constrained-vocab "
            "failure_category; MetaOptimizer prompt omits gold reference. "
            "Also toggleable via NO_LEAK=1 env. Default: OFF (legacy gold-leak)."
        ),
    )
    args = parser.parse_args()
    if args.no_leak:
        print("[P-1] NO-LEAK MODE: Judge commentary + retrieval metrics replace gold answer.")

    os.makedirs(args.results_dir, exist_ok=True)

    print("=" * 60)
    print("Phase B Self-Evolution — v0.1 Hierarchical Memory (LoCoMo)")
    print(f"Rounds: {args.rounds}, QA: all from conv-26 + conv-30 (~200)")
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
    baseline_results: dict | None = None
    # P0-fix 3.1: track last applied proposal so we can roll it back on regression
    last_applied_proposal: dict | None = None
    # P0-fix 3.1 mitigation: banned set of atoms that already caused a regression
    banned_proposals: list = []

    for round_num in range(args.rounds):
        print(f"\n{'='*60}")
        print(f"Round {round_num}")
        print(f"{'='*60}")

        # Step 2a: Run eval (all QA from conv-26 + conv-30, ~200 QA)
        print("Running LoCoMo eval...")
        results = run_eval_round(round_num, args.results_dir, args.policy_path, no_leak=args.no_leak)

        if not results:
            print(f"  Round {round_num} produced no results — skipping MetaOptimizer")
            prev_results = results
            continue

        scored_cats = [r for r in results.values() if r["n"] > 0]
        avg = sum(r["score"] for r in scored_cats) / len(scored_cats) if scored_cats else 0.0

        # P0.5: Variance-aware regression rollback
        # If this round regressed vs the previous accepted round AND the regression
        # exceeds the variance floor (and is not explained by a small-n single-sample
        # flip), roll back the policy file and ban the last-applied atom.
        rolled_back = False
        variance_decision: str | None = None
        cur_per_cat_scores = {cat: r["score"] for cat, r in results.items()}
        if round_num > 0 and history:
            # Find the most recent non-rolled-back history entry (the current "best known" state)
            prev_entry = None
            for h in reversed(history):
                if h.get("status") != "rolled_back":
                    prev_entry = h
                    break
            if prev_entry is not None:
                should_rb, variance_decision = should_rollback(
                    prev_score=prev_entry["avg_score"],
                    cur_score=avg,
                    prev_per_cat=prev_entry.get("per_cat", {}),
                    cur_per_cat=cur_per_cat_scores,
                )
                print(f"  variance_decision: {variance_decision}")
                if should_rb:
                    # Regression exceeds variance floor: roll back
                    prev_policy = prev_entry["policy"]
                    print(
                        f"  REGRESSION DETECTED: {prev_entry['avg_score']:.3f} -> {avg:.3f}. "
                        f"Rolling back policy to round {prev_entry['round']}."
                    )
                    with open(args.policy_path, "w") as f:
                        json.dump(prev_policy, f, indent=2)
                    # Record the failed round as rolled_back
                    history.append({
                        "round": round_num,
                        "avg_score": avg,
                        "per_cat": cur_per_cat_scores,
                        "policy": dict(current_policy),
                        "status": "rolled_back",
                        "reason": f"regression {prev_entry['avg_score']:.3f} -> {avg:.3f}",
                        "variance_decision": variance_decision,
                        "rolled_back_proposal": last_applied_proposal,
                    })
                    # Ban the atom that caused the regression
                    if last_applied_proposal is not None:
                        banned_proposals.append({
                            "param": last_applied_proposal["param"],
                            "value": last_applied_proposal["value"],
                            "from_score": prev_entry["avg_score"],
                            "to_score": avg,
                        })
                        print(f"  Banned proposal added: {last_applied_proposal['param']}={last_applied_proposal['value']!r}")
                    # Restore in-memory policy to prev_policy — MetaOptimizer next round
                    # should operate against the known-good policy, not the bad one.
                    current_policy = dict(prev_policy)
                    rolled_back = True
                    # Save rollback history immediately so partial runs are inspectable
                    with open(os.path.join(args.results_dir, "evolution_history.json"), "w") as f:
                        json.dump(history, f, indent=2, ensure_ascii=False)

        if not rolled_back:
            history.append({
                "round": round_num,
                "avg_score": avg,
                "per_cat": cur_per_cat_scores,
                "policy": dict(current_policy),
                "status": "accepted",
                "variance_decision": variance_decision,
                "applied_proposal": last_applied_proposal,
            })
            # Save history after every round for crash-safety
            with open(os.path.join(args.results_dir, "evolution_history.json"), "w") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            # Track baseline (round 0) for per-category delta display
            if round_num == 0:
                baseline_results = results

        # Step 2c: Convergence check
        if not rolled_back and avg >= 0.60:
            print(f"\nConverged at round {round_num}! avg={avg:.3f} >= 0.60")

        if round_num < args.rounds - 1:
            # Step 2d: Build MetaOptimizer prompt
            print("\nCalling MetaOptimizer...")
            prompt = build_meta_optimizer_prompt(
                results,
                current_policy,
                round_num,
                prev_results=prev_results,
                baseline_results=baseline_results,
                banned_proposals=banned_proposals,
                no_leak=args.no_leak,
            )

            # Save prompt for debugging
            with open(os.path.join(args.results_dir, f"round{round_num}_prompt.txt"), "w") as f:
                f.write(prompt)

            print("  Waiting 30s before MetaOptimizer call (rate limit cooldown)...")
            time.sleep(30)

            # Step 2e: Call LLM (with schema retry — P0-fix 3.4)
            llm_response = call_llm(prompt)

            # Save LLM response
            with open(os.path.join(args.results_dir, f"round{round_num}_response.json"), "w") as f:
                json.dump(llm_response, f, indent=2, ensure_ascii=False)

            print(f"  Analysis: {llm_response.get('analysis', 'N/A')[:200]}")

            # Step 2f: Apply proposals (top-1 only — P0-fix 3.2)
            proposals = llm_response.get("proposals", [])
            current_policy, applied = apply_proposals(
                current_policy, proposals, args.min_confidence, banned=banned_proposals
            )
            last_applied_proposal = applied

            # Step 2g: Write updated policy JSON
            with open(args.policy_path, "w") as f:
                json.dump(current_policy, f, indent=2)
            print(f"  Updated policy written to {args.policy_path}")
            print(f"  New policy: {json.dumps(current_policy)}")

        # Update prev_results: use this round's results if accepted; otherwise keep the last good
        if not rolled_back:
            prev_results = results

    # Final summary table
    print(f"\n{'='*60}")
    print("Evolution History")
    print(f"{'='*60}")
    header = "Round | Avg   | " + " | ".join(f"{cat[:12]:12}" for cat in LOCOMO_CATEGORIES)
    print(header)
    print("-" * len(header))
    for h in history:
        row = f"  {h['round']:3d} | {h['avg_score']:.3f} | "
        row += " | ".join(f"{h['per_cat'].get(cat, 0.0):.3f}        " for cat in LOCOMO_CATEGORIES)
        print(row)

    # Save full history
    with open(os.path.join(args.results_dir, "evolution_history.json"), "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {args.results_dir}/")
    print(f"Final policy: {args.policy_path}")


if __name__ == "__main__":
    main()
