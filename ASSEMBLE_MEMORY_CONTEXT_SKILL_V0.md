# assemble_memory_context Skill v0

## Purpose

Turn retrieved memory candidates into an answer-ready memory context.

---

## Output schema

Return JSON only.

```json
{
  "assembled_context": ["..."],
  "selected_memory_ids": ["..."],
  "dropped_memory_ids": ["..."],
  "assembly_reason": "..."
}
```

---

## Rules

- Select memories most useful for answering the query.
- Respect retrieval intent, especially granularity and whether multiple memories are needed.
- Remove low-value or redundant candidates.
- Do not answer the question.
- Return JSON only.
