# analyze_query Skill v0

## Purpose

Turn a natural-language query into a structured retrieval intent.

---

## Output schema

Return JSON only.

```json
{
  "query_type": "...",
  "target_memory_types": ["..."],
  "needs_multi_memory": false,
  "needs_temporal_reasoning": false,
  "preferred_granularity": "brief|detailed|overview|mixed",
  "recommended_retrieval_route": "..."
}
```

---

## Rules

- Identify the main information need of the query.
- Distinguish temporal, profile, relation, preference, plan, habit, state, or mixed queries.
- Decide whether one memory or multiple memories are likely needed.
- Decide whether temporal reasoning is needed.
- Recommend a coarse retrieval route.
- Return JSON only.
