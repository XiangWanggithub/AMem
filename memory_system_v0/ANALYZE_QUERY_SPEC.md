# analyze_query Spec (Draft v0)

## Goal

`analyze_query` is responsible for converting a user question into a structured retrieval intent that can guide downstream answer-time memory retrieval.

It does not answer the question itself. Instead, it identifies:
- what kind of information is being asked for,
- what kind of reasoning is needed,
- what retrieval route is likely most appropriate.

In one sentence:

> `analyze_query` turns a natural-language question into a structured retrieval intent for downstream answer-side memory access.

---

## Role in the retrieve-side pipeline

A likely minimal retrieve-side path is:

1. `analyze_query`
2. `retrieve_answer_candidates`
3. `assemble_memory_context`
4. answer model

This means `analyze_query` is the front-end interpretation layer for retrieve-side memory use.

---

## Input

### Required
- `query`
  - the user question to be answered

### Optional
- lightweight conversation context summary
- task metadata
- budget profile
- model profile

### Design decision
In v0, `analyze_query` may work primarily from the **query itself**, with only light optional context.

---

## Output

The output should be a structured **retrieval intent object**.

### Required fields
- `query_type`
- `target_memory_types`
- `needs_multi_memory`
- `needs_temporal_reasoning`
- `preferred_granularity`
- `recommended_retrieval_route`

### Example

```json
{
  "query_type": "temporal",
  "target_memory_types": ["event", "plan"],
  "needs_multi_memory": false,
  "needs_temporal_reasoning": true,
  "preferred_granularity": "detailed",
  "recommended_retrieval_route": "time_aware_event_retrieval"
}
```

---

## Query type taxonomy (v0)

Current suggested v0 query types:
- `event`
- `profile`
- `relation`
- `preference`
- `plan`
- `habit`
- `state`
- `mixed`
- `unknown`

### Notes
This taxonomy overlaps with memory types, but is not identical to them.

For example:
- a question may target `event` memories while also requiring temporal reasoning.
- `query_type` should capture the target information type, while temporal reasoning should be expressed separately via `needs_temporal_reasoning`.

---

## Responsibilities

`analyze_query` is responsible for:
1. identifying the main information need of the query
2. identifying whether the query is likely temporal, relational, profile-oriented, preference-oriented, etc.
3. identifying whether the query likely requires one memory or multiple memories
4. suggesting the most appropriate retrieval route and granularity

---

## Non-responsibilities

`analyze_query` is **not** responsible for:
1. answering the question
2. retrieving memory directly
3. assembling the final memory context
4. making final global orchestration decisions outside the retrieve path

These belong more naturally to:
- `retrieve_answer_candidates`
- `assemble_memory_context`
- retrieve-side policy (future)
- answer model

---

## Key decision dimensions

### 1. Target information type
What kind of memory is most likely needed?

Examples:
- event
- profile
- relation
- preference
- plan
- habit
- state

### 2. Reasoning shape
What kind of reasoning is likely required?

Important distinction:
- `query_type` = target information type
- `needs_temporal_reasoning` = whether time-based reasoning is needed

Examples:
- single-memory lookup
- multi-memory combination
- temporal ordering
- relation composition

### 3. Preferred granularity
What level of detail is likely needed?

Suggested v0 values:
- `brief`
- `detailed`
- `overview`
- `mixed`

### 4. Retrieval route hint
What retrieval route seems most suitable?

Examples:
- type-aware retrieval
- time-aware retrieval
- relation-aware retrieval
- profile-oriented retrieval
- hybrid retrieval

---

## Heuristic examples

### Example 1
Query:
- “When did Caroline start piano lessons?”

Likely output:
- `query_type`: `temporal`
- `target_memory_types`: [`event`]
- `needs_multi_memory`: `false`
- `needs_temporal_reasoning`: `true`
- `preferred_granularity`: `detailed`
- `recommended_retrieval_route`: `time_aware_event_retrieval`

### Example 2
Query:
- “What does Jon do for work?”

Likely output:
- `query_type`: `profile`
- `target_memory_types`: [`profile`]
- `needs_multi_memory`: `false`
- `needs_temporal_reasoning`: `false`
- `preferred_granularity`: `brief`
- `recommended_retrieval_route`: `profile_memory_retrieval`

### Example 3
Query:
- “How did Caroline and Melanie support each other?”

Likely output:
- `query_type`: `relation`
- `target_memory_types`: [`relation`, `event`]
- `needs_multi_memory`: `true`
- `needs_temporal_reasoning`: `false`
- `preferred_granularity`: `mixed`
- `recommended_retrieval_route`: `relation_aware_multi_memory_retrieval`

---

## Design rationale

This design helps because:

### 1. It prevents blind retrieval
Without query analysis, downstream retrieval would be much less targeted.

### 2. It allows query-aware retrieval
Different questions need different retrieval behaviors.

### 3. It supports a future retrieve-side policy layer
This skill provides the structured signal that policy or retrieval orchestration can later build upon.

### 4. It keeps responsibilities clean
Question understanding, candidate retrieval, context assembly, and answering remain separate.

---

## Open questions

### 1. Should `analyze_query` output one `query_type` or a ranked list?
Current leaning:
- one primary type in v0
- but `target_memory_types` may already capture some mixture

### 2. Should `recommended_retrieval_route` be very coarse or more explicit?
Current leaning:
- moderately explicit in v0
- enough to guide retrieval, not so detailed that it becomes a full execution graph

### 3. How much should model profile influence analysis?
Current leaning:
- optional in v0
- may grow in importance later

### 4. Should query rewriting happen here or later?
Current leaning:
- probably later or in a separate step
- keep `analyze_query` focused on structured intent, not rewriting

### 5. Should temporal queries always imply `needs_temporal_reasoning=true`?
Current leaning:
- usually yes
- but there may be simple date lookup cases later

---

## Current working summary

Current working assumptions for `analyze_query`:
- it is the retrieve-side query interpretation layer
- it does not answer the question
- it outputs a structured retrieval intent
- it should identify query type, target memory types, reasoning shape, granularity, and retrieval route hint
- it is the natural first step in the future retrieve-side pipeline
