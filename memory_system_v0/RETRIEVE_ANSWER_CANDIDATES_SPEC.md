# retrieve_answer_candidates Spec (Draft v0)

## Goal

`retrieve_answer_candidates` is responsible for retrieving a ranked shortlist of memory items that are most useful for answering the current query.

It uses the structured retrieval intent produced by `analyze_query` to guide what kinds of memories to retrieve and which signals to prioritize.

In one sentence:

> `retrieve_answer_candidates` turns retrieval intent into an answer-oriented shortlist of memory candidates.

---

## Role in the retrieve-side pipeline

A minimal retrieve-side path is:

1. `analyze_query`
2. `retrieve_answer_candidates`
3. `assemble_memory_context`
4. answer model

This means `retrieve_answer_candidates` is the main candidate-retrieval layer for answer-time memory use.

---

## Difference from maintenance-side retrieval

This skill should not be confused with:
- `retrieve_merge_candidates`
- `retrieve_update_candidates`

### Maintenance retrieval
Targets:
- same memory object
- same semantic slot
- maintenance relevance

### Answer-time retrieval
Targets:
- usefulness for answering the current query
- relevance to the current information need
- suitability for downstream context assembly

So this skill optimizes for:

> **answer usefulness**, not maintenance compatibility.

---

## Inputs

### Required
- `query`
- `retrieval_intent`

### Optional
- `budget_profile`
- `max_candidates`
- `storage_adapter_hint`
- `memory_state_summary`
- lightweight conversation context summary

### Typical `retrieval_intent` fields
Expected from `analyze_query`:
- `query_type`
- `target_memory_types`
- `needs_multi_memory`
- `needs_temporal_reasoning`
- `preferred_granularity`
- `recommended_retrieval_route`

---

## Output

The output is a ranked list of answer-oriented candidate memories.

### Required fields per candidate
- `memory_id`
- `candidate_score`
- `candidate_memory`

### Recommended fields per candidate
- `retrieval_signals`
- `retrieval_reason`

### Example

```json
{
  "memory_id": "m_42",
  "candidate_score": 0.87,
  "candidate_memory": {
    "normalized_content": "Caroline started piano lessons in June 2023.",
    "final_type": "event"
  },
  "retrieval_signals": ["query_type_match", "temporal_match", "entity_match"],
  "retrieval_reason": "matches Caroline + piano lessons + temporal event request"
}
```

---

## Core retrieval principles

### 1. Query usefulness over maintenance similarity
The skill should prefer memories that help answer the current question, even if they are not maintenance-neighbors.

### 2. Intent-guided retrieval
Retrieval should be shaped by the output of `analyze_query`, rather than using blind flat search only.

### 3. Candidate retrieval, not final context assembly
This skill retrieves useful memory candidates, but does not yet decide how they should be arranged into the final answer context.

---

## Candidate retrieval signals

The following signals are plausible in v0.
Different backends may implement different subsets.

### 1. Query type match
Example:
- `profile` query should prefer profile-like memories
- `temporal` query should prioritize event/plan memories with time anchors

### 2. Target memory type match
Uses `target_memory_types` from `retrieval_intent`.

### 3. Entity overlap
Example:
- question about Caroline should prioritize memories about Caroline

### 4. Temporal relevance
Important especially when:
- `needs_temporal_reasoning=true`
- query explicitly asks “when”, “before”, “after”, “how long”, etc.

### 5. Relation relevance
Important when the query asks about:
- interactions
- support
- connections
- social roles

### 6. Multi-memory usefulness
When `needs_multi_memory=true`, retrieval should allow a set of complementary candidates rather than over-focusing on one top hit.

### 7. Granularity preference
The retrieval intent may prefer:
- `brief`
- `detailed`
- `overview`
- `mixed`

This should influence what kinds of memory candidates are surfaced.

---

## Responsibilities

`retrieve_answer_candidates` is responsible for:
1. retrieving memory candidates useful for answering the current query
2. using retrieval intent as a guide
3. producing a bounded shortlist instead of the whole memory store
4. exposing candidate-level scores and optional reasons/signals

---

## Non-responsibilities

`retrieve_answer_candidates` is **not** responsible for:
1. understanding the query from scratch without `analyze_query`
2. rewriting the query (unless added later as another step)
3. assembling the final answer context
4. generating the final answer
5. performing maintenance-side merge/update retrieval

These belong more naturally to:
- `analyze_query`
- `assemble_memory_context`
- answer model
- maintenance-side retrieval skills

---

## Relationship with granularity

`retrieve_answer_candidates` should be sensitive to `preferred_granularity`, but should not fully solve final context shaping.

### Examples
- `brief` → prefer concise factual memories
- `detailed` → prefer richer event details
- `overview` → prefer summary-like or broader memory candidates
- `mixed` → allow multiple candidate styles

Final arrangement and pruning happen later in `assemble_memory_context`.

---

## Relationship with storage architecture

This skill is defined at the **interface level**, not at the backend-specific implementation level.

### Stable contract
The contract stays the same:
- input: query + retrieval intent
- output: ranked answer-oriented candidate memories

### Variable implementation
Possible backend styles:
- vector-based retrieval
- graph-based retrieval
- hierarchical retrieval
- hybrid retrieval
- namespace / type-aware symbolic retrieval

### Current design decision
We treat `retrieve_answer_candidates` as a **single skill abstraction with backend-adaptive implementations**.

---

## Relationship with future retrieve-side policy

A future retrieve-side policy may decide:
- whether retrieval should be cheap or rich
- how many candidates to request
- which backend or route to use
- whether multiple passes are worth the cost

But `retrieve_answer_candidates` should remain the concrete retrieval executor for answer-side memory candidate generation.

---

## Heuristic examples

### Example 1
Query:
- “When did Caroline start piano lessons?”

Expected retrieval tendency:
- prioritize event memories about Caroline
- strongly prioritize time-anchored candidates
- likely prefer detailed granularity

### Example 2
Query:
- “What does Jon do for work?”

Expected retrieval tendency:
- prioritize profile memories
- likely prefer brief factual candidates

### Example 3
Query:
- “How did Caroline and Melanie support each other?”

Expected retrieval tendency:
- retrieve relation + event memories
- allow multiple complementary candidates
- likely mixed granularity

---

## Design rationale

This design helps because:

### 1. It separates query understanding from retrieval execution
`analyze_query` decides what kind of retrieval is needed; this skill executes that retrieval.

### 2. It avoids blind one-size-fits-all retrieval
Different questions benefit from different candidate profiles.

### 3. It supports modularity
Candidate retrieval stays separate from later context assembly and answering.

### 4. It preserves explainability
Signals and reasons can be logged and inspected.

---

## Open questions

### 1. Should `max_candidates` depend directly on `needs_multi_memory`?
Current leaning:
- probably yes
- but exact mapping can remain open in v0

### 2. Should this skill support multi-pass retrieval later?
Current leaning:
- possible later
- not necessary for v0 spec

### 3. Should different query types use different default backends?
Current leaning:
- likely yes later
- but the abstraction should remain unified

### 4. Should retrieval reasons be mandatory?
Current leaning:
- optional but useful for debugging and analysis

### 5. Should query rewriting be introduced before this skill?
Current leaning:
- possibly later
- keep current v0 design simpler

---

## Current working summary

Current working assumptions for `retrieve_answer_candidates`:
- it is the main answer-time memory candidate retrieval skill
- it consumes `query` + `retrieval_intent`
- it optimizes for answer usefulness, not maintenance compatibility
- it is sensitive to memory type, entities, temporal relevance, relation relevance, and granularity
- it returns a bounded shortlist for later context assembly
- it is the natural second step after `analyze_query` in the retrieve-side pipeline
