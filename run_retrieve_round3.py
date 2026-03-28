import json
from pathlib import Path
from openai import OpenAI
from collections import defaultdict

base = Path("/home/kailong/Quant/memory-eval")
cases = [json.loads(line) for line in open(base / "synthetic_retrieve_cases_v0.jsonl")]
client = OpenAI(base_url="https://api.minimaxi.com/v1", api_key="sk-cp-8rjY-rdLgaohfjPxT86FUpq2DFAW_lU8OniwxOveVEIKT6T20oLfZrqJzzgaMzxtdOXMzbnrpHfmOJCdTT3_Ic9uBWDPCpcEV_7pc_o0HNr0U_7NwpavDbo")

ALLOWED_TYPES = ["event", "profile", "relation", "preference", "plan", "habit", "state", "mixed", "unknown"]
ALLOWED_TARGET_MEMORY_TYPES = ["event", "profile", "relation", "preference", "plan", "habit", "state"]
ALLOWED_GRANULARITY = ["brief", "detailed", "overview", "mixed"]
ALLOWED_ROUTES = [
    "time_aware_event_retrieval",
    "profile_memory_retrieval",
    "relation_aware_multi_memory_retrieval",
    "type_aware_retrieval",
    "hybrid_retrieval",
]

RULES = {
    "analyze_query": (
        "You are executing the analyze_query skill. Convert the query into a structured retrieval intent. "
        f"query_type must be exactly one of: {ALLOWED_TYPES}. "
        "Do not use temporal as query_type. Temporal is a reasoning dimension, not a query_type label. "
        f"target_memory_types must contain only values from: {ALLOWED_TARGET_MEMORY_TYPES}. "
        f"preferred_granularity must be exactly one of: {ALLOWED_GRANULARITY}. "
        f"recommended_retrieval_route must be exactly one of: {ALLOWED_ROUTES}. "
        "Use needs_temporal_reasoning=true when time-based reasoning is needed, while keeping query_type as the target information type. "
        "Return JSON only."
    ),
    "retrieve_answer_candidates": (base / "RETRIEVE_ANSWER_CANDIDATES_SKILL_V0.md").read_text(),
    "assemble_memory_context": (base / "ASSEMBLE_MEMORY_CONTEXT_SKILL_V0.md").read_text(),
}
SCHEMAS = {
    "analyze_query": '{"query_type":"event|profile|relation|preference|plan|habit|state|mixed|unknown","target_memory_types":["event|profile|relation|preference|plan|habit|state"],"needs_multi_memory":false,"needs_temporal_reasoning":false,"preferred_granularity":"brief|detailed|overview|mixed","recommended_retrieval_route":"time_aware_event_retrieval|profile_memory_retrieval|relation_aware_multi_memory_retrieval|type_aware_retrieval|hybrid_retrieval"}',
    "retrieve_answer_candidates": '{"candidate_memories":[{"memory_id":"...","candidate_score":0.0,"candidate_memory":{"normalized_content":"...","final_type":"..."}}]}',
    "assemble_memory_context": '{"assembled_context":["..."],"selected_memory_ids":["..."],"dropped_memory_ids":["..."],"assembly_reason":"..."}',
}
results = []

for case in cases:
    family = case["family"]
    rules = RULES[family]
    prompt = (
        f"You are executing the {family} skill. Follow the skill definition exactly. Return JSON only.\n\n"
        f"{rules}\n\n"
        f"Output schema:\n```json\n{SCHEMAS[family]}\n```\n\n"
        f"Task input:\n```json\n{json.dumps(case['inputs'], ensure_ascii=False, indent=2)}\n```\n"
    )

    resp = client.chat.completions.create(
        model="MiniMax-M2.5",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1024,
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
        if family == "analyze_query":
            ok = parsed.get("query_type") == exp.get("expected_query_type")
            if ok and exp.get("expected_target_memory_types") is not None:
                ok = parsed.get("target_memory_types") == exp.get("expected_target_memory_types")
            if ok and exp.get("expected_needs_multi_memory") is not None:
                ok = parsed.get("needs_multi_memory") == exp.get("expected_needs_multi_memory")
            if ok and exp.get("expected_needs_temporal_reasoning") is not None:
                ok = parsed.get("needs_temporal_reasoning") == exp.get("expected_needs_temporal_reasoning")
        elif family == "retrieve_answer_candidates":
            got = [x.get("memory_id") for x in parsed.get("candidate_memories", [])[:len(exp.get("expected_top_memory_ids", []))]]
            ok = got == exp.get("expected_top_memory_ids")
        elif family == "assemble_memory_context":
            ok = parsed.get("selected_memory_ids") == exp.get("expected_selected_memory_ids")
    except Exception as e:
        error = str(e)

    results.append({
        "family": family,
        "case_id": case["case_id"],
        "pass": ok,
        "tokens": resp.usage.total_tokens,
        "raw_output": content,
        "parsed": parsed,
        "error": error,
    })
    print(family, case["case_id"], "pass=", ok, "tokens=", resp.usage.total_tokens)

(base / "results").mkdir(exist_ok=True)
with open(base / "results/retrieve_skill_test_results_round3.json", "w") as f:
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
