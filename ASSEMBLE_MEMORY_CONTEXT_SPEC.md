# assemble_memory_context Spec (Draft v0)

## Goal

`assemble_memory_context` is responsible for turning retrieved memory candidates into an answer-ready memory context for the downstream answer model.

It does not retrieve memories itself and does not answer the question. Instead, it selects, orders, prunes, and formats the retrieved memory candidates into a context block that is suitable for answering.

In one sentence:

> `assemble_memory_context` turns retrieved memory candidates into a structured, budget-aware, answer-ready memory context.

---

## Role in the retrieve-side pipeline

A minimal retrieve-side path is:

1. `analyze_query`
2. `retrieve_answer_candidates`
3. `assemble_memory_context`
4. answer model

This means `assemble_memory_context` is the last retrieve-side preparation layer before answer generation.

---

## Inputs

### Required
- `query`
- `retrieval_intent`
- `candidate_memories`

### Optional
- `budget_profile`
- `max_context_tokens`
- `context_style_hint`
- `model_profile`

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

The output should be a structured answer-ready context object.

### Required fields
- `assembled_context`
- `selected_memory_ids`
- `dropped_memory_ids`
- `assembly_reason`

### Example

```json
{
  "assembled_context": [
    "Caroline started piano lessons in June 2023.",
    "She feels calmer now after starting piano lessons."
  ],
  "selected_memory_ids": ["m_12", "m_19"],
  "dropped_memory_ids": ["m_04"],
  "assembly_reason": "selected the most relevant event and immediate consequence"
}
```

---

## Core responsibilities

`assemble_memory_context` is responsible for:
1. selecting which retrieved candidates should be included
2. ordering the selected memories
3. pruning low-value or redundant candidates
4. shaping the final context according to granularity and budget
5. formatting the selected memories into answer-ready context

---

## Non-responsibilities

`assemble_memory_context` is **not** responsible for:
1. understanding the query from scratch
2. retrieving memories from the store
3. performing merge/update/score operations
4. generating the final answer
5. modifying the memory store

These belong more naturally to:
- `analyze_query`
- `retrieve_answer_candidates`
- maintenance-side skills
- answer model

---

## Core assembly principles

### 1. Relevance-first selection
Only include memories that are likely useful for answering the current query.

### 2. Respect retrieval intent
The final context should reflect the intent signals, especially:
- `needs_multi_memory`
- `preferred_granularity`
- `query_type`
- `target_memory_types`

### 3. Budget-aware pruning
Do not pass every retrieved memory forward.
The context should stay concise enough for the answer model.

### 4. Avoid unnecessary redundancy
Highly overlapping candidates should not all survive into the final context unless they each add meaningful value.

---

## Granularity handling

`assemble_memory_context` should use `preferred_granularity` as a shaping hint.

### Suggested v0 interpretations
- `brief` → select concise factual items
- `detailed` → preserve richer event details
- `overview` → prefer broader or more summary-like items
- `mixed` → allow multiple complementary styles

This skill should shape the final context, but it should not become a heavy summarizer in v0.

---

## Multi-memory handling

If `needs_multi_memory=true`, the skill should allow multiple complementary memories to remain.

Examples:
- relation + supporting event
- profile + plan
- multiple relation memories answering a social/support question

If `needs_multi_memory=false`, the skill may aggressively prune toward a smaller context.

---

## Example 1: temporal query

### Query
“When did Caroline start piano lessons?”

### Retrieved candidates
- Caroline started piano lessons in June 2023.
- Caroline feels calmer now after starting piano lessons.
- Caroline enjoys creative hobbies.

### Expected assembly tendency
Keep only the most relevant time-anchored event memory.

### Possible output

```json
{
  "assembled_context": [
    "Caroline started piano lessons in June 2023."
  ],
  "selected_memory_ids": ["m_event_1"],
  "dropped_memory_ids": ["m_state_2", "m_pref_3"],
  "assembly_reason": "kept the time-anchored event memory most relevant to the temporal query"
}
```

---

## Example 2: relation query

### Query
“How did Caroline and Melanie support each other?”

### Retrieved candidates
- Caroline encouraged Melanie’s art practice.
- Melanie shared books and emotional support with Caroline.
- Caroline started piano lessons in June 2023.

### Expected assembly tendency
Keep multiple complementary relation memories; remove unrelated event detail.

### Possible output

```json
{
  "assembled_context": [
    "Caroline encouraged Melanie’s art practice.",
    "Melanie shared books and emotional support with Caroline."
  ],
  "selected_memory_ids": ["m_rel_1", "m_rel_2"],
  "dropped_memory_ids": ["m_event_7"],
  "assembly_reason": "selected complementary relation memories and removed unrelated event detail"
}
```

---

## Relationship with future retrieve-side policy

A future retrieve-side policy may decide:
- how large the final context may be,
- whether context should be brief or rich,
- whether multiple candidate groups should be assembled,
- whether an overview-style context is acceptable.

But `assemble_memory_context` should remain the concrete layer that performs the final candidate-to-context transformation.

---

## Relationship with answer model

The answer model should consume the output of this skill rather than the raw retrieval candidate list.

This is important because:
- retrieved candidates may be redundant,
- retrieved candidates may vary in granularity,
- raw retrieval output is not yet shaped for final answering.

---

## Design rationale

This design helps because:

### 1. It separates retrieval from answer-time context preparation
Finding candidates and preparing final context are different operations.

### 2. It improves budget control
Selection and pruning reduce unnecessary context cost.

### 3. It supports cleaner answer-time behavior
A smaller, better-organized context is easier for the answer model to use well.

### 4. It preserves modularity
Question analysis, candidate retrieval, context assembly, and answer generation remain distinct.

---

## Open questions

### 1. Should `assembled_context` be a list of strings or one composed block?
Current leaning:
- a list is easier for structured inspection
- a later step may join them into a final prompt block

### 2. Should this skill ever summarize multiple memories into a shorter synthetic statement?
Current leaning:
- probably not in v0
- keep assembly lighter and more transparent first

### 3. Should evidence or provenance be retained in assembled context?
Current leaning:
- maybe optionally
- but not necessarily in the main answer-facing context string

### 4. Should context ordering be optimized by recency, relevance, or type grouping?
Current leaning:
- primarily relevance first in v0
- other ordering heuristics can come later

### 5. Should brief queries always force aggressive pruning?
Current leaning:
- often yes
- but not blindly if the query clearly needs multiple supporting memories

---

## Current working summary

Current working assumptions for `assemble_memory_context`:
- it is the final retrieve-side context preparation skill before the answer model
- it takes query + retrieval intent + candidate memories
- it performs selection, ordering, pruning, and formatting
- it is budget-aware and granularity-aware
- it does not answer the question itself
- it completes the current minimal retrieve-side pipeline
