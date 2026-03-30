# retrieve_merge_candidates Skill v0

## Purpose

Given a new normalized memory item, retrieve a high-recall shortlist of old memory items that may describe the same memory object and are worth checking for merge.

---

## Inputs

```json
{
  "source_memory": {
    "normalized_content": "...",
    "final_type": "..."
  },
  "memory_store": [
    {
      "memory_id": "...",
      "normalized_content": "...",
      "final_type": "..."
    }
  ],
  "max_candidates": 3
}
```

---

## Decision rules

Prefer candidates with:
- same final type
- shared entities / subject
- semantic similarity
- time alignment when relevant

Target high recall, not final precision.
Do not decide merge here.

---

## Output schema

Return JSON only.

```json
{
  "candidate_memories": [
    {
      "memory_id": "...",
      "normalized_content": "...",
      "final_type": "..."
    }
  ]
}
```
