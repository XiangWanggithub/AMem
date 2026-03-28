# merge_memory Skill Example Prompt

Below is a minimal example of how an LLM can be asked to execute the `merge_memory` skill manually.

---

You are executing the `merge_memory` skill.

Your job is to determine whether `source_memory` and `candidate_memories` should be merged.

Rules:
- Merge only if they describe the same memory object.
- Merge duplicates, complementary descriptions, or repeated confirmations.
- Do NOT merge if the new item reflects a changed state or revised plan.
- Relatedness alone is not enough.
- Be conservative.
- Return JSON only.

Required output schema:

```json
{
  "merge_decision": "merge" | "no_merge",
  "merge_confidence": 0.0,
  "merge_reason": "...",
  "merged_memory": {
    "normalized_content": "...",
    "final_type": "..."
  } | null,
  "consumed_memory_ids": ["..."]
}
```

Input:

```json
{
  "source_memory": {
    "normalized_content": "Jon plans to open a dance studio.",
    "final_type": "plan"
  },
  "candidate_memories": [
    {
      "memory_id": "m_old_1",
      "normalized_content": "Jon plans to open a dance studio in the fall.",
      "final_type": "plan"
    }
  ]
}
```
