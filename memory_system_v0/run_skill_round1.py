import json
from pathlib import Path
from openai import OpenAI

base = Path("/home/kailong/Quant/memory-eval/memory_system_v0")
cases = [json.loads(line) for line in open(base / "synthetic_maintenance_cases_v0.jsonl")]
client = OpenAI(base_url="https://api.minimaxi.com/v1", api_key="sk-cp-8rjY-rdLgaohfjPxT86FUpq2DFAW_lU8OniwxOveVEIKT6T20oLfZrqJzzgaMzxtdOXMzbnrpHfmOJCdTT3_Ic9uBWDPCpcEV_7pc_o0HNr0U_7NwpavDbo")

skill_files = {
    "categorize": "CATEGORIZE_MEMORY_SPEC.md",
    "normalize": "NORMALIZE_MEMORY_SPEC.md",
    "update": "UPDATE_MEMORY_SPEC.md",
    "score": "SCORE_MEMORY_SPEC.md",
}

schema_examples = {
    "categorize": '{"final_type":"...","category_confidence":0.0,"recommended_route":"..."}',
    "normalize": '{"normalized_content":"...","final_type":"...","normalization_confidence":0.0}',
    "update": '{"update_decision":"update|no_update","update_confidence":0.0,"update_reason":"...","update_type":"... or null","updated_memory":null,"affected_memory_ids":[]}',
    "score": '{"salience_score":0.0,"stability_score":0.0,"future_utility_score":0.0,"overall_score":0.0,"score_reason":"..."}',
}

families = ["categorize", "normalize", "update", "score"]
results = []

for family in families:
    skill_text = (base / skill_files[family]).read_text()
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
            f"You are executing the {family}_memory skill.\n\n"
            f"Follow the skill definition exactly. Return JSON only.\n\n"
            f"{skill_text}\n\n"
            f"Output schema example:\n```json\n{schema_examples[family]}\n```\n\n"
            f"Task input:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
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
            if family == "categorize":
                ok = parsed.get("final_type") == exp.get("expected_final_type") and parsed.get("recommended_route") == exp.get("expected_recommended_route")
            elif family == "normalize":
                ok = parsed.get("normalized_content") == exp.get("expected_normalized_content")
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
with open(base / "results/skill_test_results_round1.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
