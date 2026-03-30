# retrieve_update_candidates Skill v0

## Purpose

Given a new normalized memory item, retrieve a high-recall shortlist of old memory items that may occupy the same semantic slot and are worth checking for update.

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
- same subject / owner
- same final type
- same semantic slot
- plausible temporal succession

Target high recall, not final precision.
Do not decide update here.

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
