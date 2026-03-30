import json
from pathlib import Path
from openai import OpenAI
from collections import defaultdict

base = Path("/home/kailong/Quant/memory-eval/memory_system_v0")
cases = [json.loads(line) for line in open(base / "synthetic_organization_cases_v0.jsonl")]
client = OpenAI(base_url="https://api.minimaxi.com/v1", api_key="sk-cp-8rjY-rdLgaohfjPxT86FUpq2DFAW_lU8OniwxOveVEIKT6T20oLfZrqJzzgaMzxtdOXMzbnrpHfmOJCdTT3_Ic9uBWDPCpcEV_7pc_o0HNr0U_7NwpavDbo")

RULES = {
    "link": (base / "LINK_MEMORY_SKILL_V0.md").read_text(),
    "reorganize": (base / "REORGANIZE_MEMORY_SKILL_V0.md").read_text(),
}
SCHEMAS = {
    "link": '{"link_decision":"link|no_link","linked_memory_ids":[],"link_type":"...|null","link_reason":"...","link_direction":"...|null","link_confidence":0.0}',
    "reorganize": '{"reorganization_decision":"reorganize|no_reorganize","reorganization_actions":[],"affected_memory_ids":[],"reorganization_reason":"...","suggested_clusters":[]}',
}
results = []

for case in cases:
    family = case["family"]
    rules = RULES[family]
    prompt = (
        f"You are executing the {family}_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
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
        if family == "link":
            ok = parsed.get("link_decision") == exp.get("expected_link_decision")
            if ok and exp.get("expected_link_type") is not None:
                ok = parsed.get("link_type") == exp.get("expected_link_type")
        elif family == "reorganize":
            ok = parsed.get("reorganization_decision") == exp.get("expected_reorganization_decision")
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
with open(base / "results/organization_skill_test_results_round1.json", "w") as f:
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
