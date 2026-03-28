# merge_memory Skill v0

## Purpose

Determine whether a new memory item (`source_memory`) and one or more existing memory items (`candidate_memories`) should be merged into one consolidated memory object.

This skill should:
- merge duplicate memories,
- merge complementary descriptions of the same memory object,
- merge repeated confirmations of the same memory,
- avoid treating state replacement or plan revision as merge.

---

## When to use this skill

Use this skill when:
- you already have a normalized new memory item,
- you already have a shortlist of old candidate memories,
- you want to decide whether they describe the same memory object.

Do **not** use this skill to:
- retrieve candidates from the full memory store,
- handle state change,
- handle plan revision,
- resolve contradiction by replacement.

Those belong elsewhere.

---

## Inputs

### Required input

```json
{
  "source_memory": {
    "normalized_content": "...",
    "final_type": "..."
  },
  "candidate_memories": [
    {
      "memory_id": "...",
      "normalized_content": "...",
      "final_type": "..."
    }
  ]
}
```

### Optional fields
Optional input fields may include:
- `normalized_entities`
- `normalized_time_anchor`
- provenance / evidence metadata

---

## Decision rules

### Merge when
A candidate and the source memory describe the **same memory object**, for example:
1. they are near-duplicates,
2. one adds complementary detail to the other,
3. they are repeated confirmations of the same fact / preference / plan.

### Do not merge when
1. the new memory reflects a changed state,
2. the new memory revises or replaces an old plan,
3. the two items are related but not the same memory object,
4. the two items belong to clearly different semantic roles.

### Important principle
Relatedness alone is **not enough**.
The key question is:

> Do these memories describe the same memory object?

---

## Output schema

Return **JSON only**.
Do not output markdown.
Do not output explanation outside JSON.

### Required output format

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

### Output rules
- If `merge_decision` is `no_merge`, then `merged_memory` should be `null`.
- If `merge_decision` is `merge`, then `merged_memory` should contain the merged representation.
- `consumed_memory_ids` should contain the IDs of old memories absorbed into the merged memory.
- `merge_reason` should be short and concrete.

---

## Behavioral constraints

- Be conservative.
- Prefer false negatives over false positive merges.
- Do not invent details not supported by the inputs.
- Do not change memory type unless absolutely necessary; in v0, assume final type should remain stable.
- If uncertain, prefer `no_merge`.

---

## Example 1: should merge

### Input

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

### Output

```json
{
  "merge_decision": "merge",
  "merge_confidence": 0.94,
  "merge_reason": "same plan, candidate adds complementary temporal detail",
  "merged_memory": {
    "normalized_content": "Jon plans to open a dance studio in the fall.",
    "final_type": "plan"
  },
  "consumed_memory_ids": ["m_old_1"]
}
```

---

## Example 2: should not merge

### Input

```json
{
  "source_memory": {
    "normalized_content": "Caroline started piano lessons in June 2023.",
    "final_type": "event"
  },
  "candidate_memories": [
    {
      "memory_id": "m_old_2",
      "normalized_content": "Caroline feels calmer after starting piano lessons.",
      "final_type": "state"
    }
  ]
}
```

### Output

```json
{
  "merge_decision": "no_merge",
  "merge_confidence": 0.9,
  "merge_reason": "related but not the same memory object",
  "merged_memory": null,
  "consumed_memory_ids": []
}
```

---

## Invocation template

Use the following prompt pattern when asking an LLM to execute this skill:

### System / instruction
You are executing the `merge_memory` skill.
Follow the skill definition exactly.
Return JSON only.

### Skill definition
[Insert this skill document, or a compacted executor version of it]

### Task input
[Insert the concrete `source_memory` and `candidate_memories` JSON]

### Expected output
Return one JSON object matching the required output schema.

---

## Notes

This v0 skill is intended for **manual invocation** first.
That means:
- the caller explicitly decides to use `merge_memory`,
- the model does not yet need to learn when to invoke it automatically.

This is useful for validating whether the skill contract itself is executable before building a larger policy-driven runtime.
