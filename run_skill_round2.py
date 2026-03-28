import json
from pathlib import Path
from openai import OpenAI
from collections import defaultdict

base = Path("/home/kailong/Quant/memory-eval")
cases = [json.loads(line) for line in open(base / "synthetic_maintenance_cases_v0.jsonl")]
client = OpenAI(base_url="https://api.minimaxi.com/v1", api_key="sk-cp-8rjY-rdLgaohfjPxT86FUpq2DFAW_lU8OniwxOveVEIKT6T20oLfZrqJzzgaMzxtdOXMzbnrpHfmOJCdTT3_Ic9uBWDPCpcEV_7pc_o0HNr0U_7NwpavDbo")

families = ["merge", "categorize", "normalize", "update", "score"]
results = []

SKILL_RULES = {
    "merge": "You are executing the merge_memory skill. Decide whether source_memory and candidate_memories describe the same memory object. Merge duplicates, complementary descriptions, or repeated confirmations. Do not merge state replacement or plan revision. Relatedness alone is not enough. Be conservative. Return JSON only. merge_reason must be one short sentence, max 20 words.",
    "categorize": "You are executing the categorize_memory skill. Assign a stable final_type and recommended_route to the given memory item. Use the pragmatic taxonomy: event, preference, profile, relation, plan, habit, state. Return JSON only.",
    "normalize": "You are executing the normalize_memory skill. Rewrite the memory into a canonical, less ambiguous, and comparable form. Normalize time when possible, resolve local references when possible, reduce noise, and preserve meaning. Do not change final_type. Return JSON only.",
    "update": "You are executing the update_memory skill. Decide whether source_memory should revise or replace an older memory in the same semantic slot. Use update for change, correction, or replacement; do not use update for simple duplication or complementary detail. Return JSON only. update_reason must be one short sentence, max 20 words.",
    "score": "You are executing the score_memory skill. Estimate salience, stability, and future utility for the memory item. Provide interpretable scores only; do not decide actions. Return JSON only. score_reason must be one short sentence, max 20 words."
}

SCHEMAS = {
    "merge": '{"merge_decision":"merge|no_merge","merge_confidence":0.0,"merge_reason":"short reason","merged_memory":null,"consumed_memory_ids":[]}',
    "categorize": '{"final_type":"...","category_confidence":0.0,"recommended_route":"..."}',
    "normalize": '{"normalized_content":"...","final_type":"...","normalization_confidence":0.0}',
    "update": '{"update_decision":"update|no_update","update_confidence":0.0,"update_reason":"short reason","update_type":"... or null","updated_memory":null,"affected_memory_ids":[]}',
    "score": '{"salience_score":0.0,"stability_score":0.0,"future_utility_score":0.0,"overall_score":0.0,"score_reason":"short reason"}',
}

for family in families:
    fam_cases = [c for c in cases if c["family"] == family]
    for case in fam_cases:
        if family in ("categorize", "normalize", "score"):
            payload = case["inputs"]["source_memory"]
            if "optional_context" in case["inputs"]:
                payload = {"source_memory": case["inputs"]["source_memory"], "optional_context": case["inputs"]["optional_context"]}
        else:
            payload = {
                "source_memory": case["inputs"]["source_memory"],
                "candidate_memories": case["inputs"]["candidate_memories"],
            }

        prompt = (
            f"{SKILL_RULES[family]}\n\n"
            f"Output schema:\n```json\n{SCHEMAS[family]}\n```\n\n"
            f"Task input:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
        )

        resp = client.chat.completions.create(
            model="MiniMax-M2.5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=512,
            extra_body={"reasoning_split": True},
        )
        content = resp.choices[0].message.content.strip()
        parsed = None
        ok = False
        error = None
        try:
            cleaned = content
            if cleaned.startswith("```json"):
                cleaned = cleaned[len("```json"):].strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[len("```"):].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            parsed = json.loads(cleaned)
            exp = case["expected"]
            if family == "categorize":
                ok = parsed.get("final_type") == exp.get("expected_final_type") and parsed.get("recommended_route") == exp.get("expected_recommended_route")
            elif family == "normalize":
                ok = parsed.get("normalized_content") == exp.get("expected_normalized_content")
            elif family == "merge":
                ok = parsed.get("merge_decision") == exp.get("expected_merge_decision")
            elif family == "update":
                ok = parsed.get("update_decision") == exp.get("expected_update_decision")
                if ok and exp.get("expected_update_type") is not None:
                    ok = parsed.get("update_type") == exp.get("expected_update_type")
            elif family == "score":
                ok = all(k in parsed for k in ["salience_score", "stability_score", "future_utility_score"])
        except Exception as e:
            error = str(e)

        results.append({
            "family": family,
            "case_id": case["case_id"],
            "expected": case["expected"],
            "raw_output": content,
            "parsed": parsed,
            "pass": ok,
            "error": error,
            "tokens": resp.usage.total_tokens,
        })
        print(family, case["case_id"], "pass=", ok, "tokens=", resp.usage.total_tokens)

(base / "results").mkdir(exist_ok=True)
with open(base / "results/skill_test_results_round2.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

agg = defaultdict(lambda: {"pass": 0, "total": 0, "tokens": []})
for r in results:
    agg[r["family"]]["total"] += 1
    agg[r["family"]]["pass"] += 1 if r["pass"] else 0
    agg[r["family"]]["tokens"].append(r["tokens"])
print("---SUMMARY---")
for fam, d in agg.items():
    avg = sum(d["tokens"]) / len(d["tokens"])
    print(fam, f"{d['pass']}/{d['total']}", f"avg_tokens={avg:.1f}")
