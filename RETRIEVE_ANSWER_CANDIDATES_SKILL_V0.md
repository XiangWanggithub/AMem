# retrieve_answer_candidates Skill v0

## Purpose

Given a query and retrieval intent, retrieve a ranked shortlist of memory items most useful for answering the query.

---

## Output schema

Return JSON only.

```json
{
  "candidate_memories": [
    {
      "memory_id": "...",
      "candidate_score": 0.0,
      "candidate_memory": {
        "normalized_content": "...",
        "final_type": "..."
      }
    }
  ]
}
```

---

## Rules

- Optimize for answer usefulness, not maintenance compatibility.
- Use retrieval_intent as guidance.
- Prefer type match, entity match, temporal relevance, relation relevance, and granularity fit.
- Return a bounded shortlist.
- Do not answer the question.
- Return JSON only.
