# merge_memory Spec (Draft v0)

## Goal

`merge_memory` is responsible for consolidating overlapping or highly related memory items into a less redundant and more complete representation, **without treating new memory as a state override by default**.

Its role is to determine whether a new normalized memory item and one or more existing memory items are describing the **same memory object**, and if so, to produce a merged representation.

In one sentence:

> `merge_memory` decides whether related memory items should be fused into one consolidated memory object, while keeping merge distinct from state update.

---

## Core distinction: merge vs update

### `merge_memory`
Use when multiple memory items are:
- near-duplicates,
- complementary descriptions of the same memory object,
- repeated confirmations of the same fact / preference / plan.

Goal:
- reduce redundancy
- improve completeness
- preserve one underlying memory object

### `update_memory`
Use when newer memory changes, replaces, or invalidates older memory.

Goal:
- handle state evolution
- resolve conflicts
- represent replacement rather than fusion

### Current decision
`merge_memory` should **not** be used for:
- state overwrite
- plan reversal
- contradiction resolution
- timeline replacement

---

## Inputs

### Required
- `source_memory`
  - the new normalized memory item currently under maintenance
- `candidate_memories`
  - existing memory items that are plausible merge candidates

### Optional
- provenance metadata
- evidence
- timestamps
- confidence fields
- entity alignment hints

### Important design note
In v0, `candidate_memories` are assumed to be supplied by an **upstream retrieval step**, which may later be formalized as a separate skill (e.g. `retrieve_merge_candidates`).

So:
- `merge_memory` does **not** search the entire memory store by itself
- it only evaluates and consolidates the candidate set provided to it

---

## Output

The output should explicitly include a merge decision.

### Required fields
- `merge_decision`
  - `merge` or `no_merge`
- `merge_confidence`
  - confidence in the decision
- `merge_reason`
  - short rationale for the decision

### If merged
- `merged_memory`
  - consolidated memory representation
- `consumed_memory_ids`
  - source IDs absorbed into the merged memory

### If not merged
- `preserved_memory_ids`
  - memory IDs that remain separate

### Design principle
`merge_memory` should be **auditable**.
It should not silently overwrite or erase memory objects without explicit merge output.

---

## Merge-worthy cases (v0)

### 1. Near-duplicate merge
Multiple memory items express essentially the same fact with different wording.

Example:
- “Melanie likes sunrise paintings.”
- “Melanie prefers sunrise artwork.”

### 2. Complementary merge
Two memory items describe the same underlying memory object, but one adds useful detail.

Example:
- “Jon plans to open a dance studio.”
- “Jon plans to open a dance studio in the fall.”

### 3. Repeated-confirmation merge
The same information is independently mentioned multiple times, increasing confidence or stability.

Example:
- repeated mentions that someone prefers tea over coffee

---

## Non-merge cases (v0)

### 1. State change
Example:
- “she is stressed”
- “she feels calmer now”

These suggest evolution or update, not merge.

### 2. Plan change or contradiction
Example:
- “plans to move to Boston”
- “decided to stay in Chicago”

These should not be merged.

### 3. Related but not same memory object
Example:
- “Caroline started piano lessons in June 2023.”
- “Caroline feels calmer after starting piano lessons.”

These are related, but not the same memory object.
Likely action:
- `no_merge`
- possibly later linked by `link_memory`

### Current principle
Relatedness alone is **not sufficient** for merge.
The key question is:

> Are these items describing the same memory object?

---

## Output schema for merged memory (v0)

A merged memory should usually preserve:
- consolidated `normalized_content`
- preserved `final_type`
- provenance / source references
- optional combined evidence

### Example

```json
{
  "merge_decision": "merge",
  "merge_confidence": 0.94,
  "merge_reason": "same plan, second memory adds complementary temporal detail",
  "merged_memory": {
    "normalized_content": "Jon plans to open a dance studio in the fall.",
    "final_type": "plan"
  },
  "consumed_memory_ids": ["m_old_1", "m_new_9"]
}
```

---

## Responsibilities

`merge_memory` is responsible for:
1. evaluating whether `source_memory` and `candidate_memories` describe the same memory object
2. deciding merge vs no-merge
3. producing a less redundant and more complete merged representation when appropriate
4. preserving provenance for auditability

---

## Non-responsibilities

`merge_memory` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory content
4. retrieving the full memory store
5. updating or overwriting changed states
6. deciding retention / promotion
7. making final global orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates` (future / upstream skill)
- `update_memory`
- `score_memory`
- `memory policy`

---

## Relationship with other skills

### With `retrieve_merge_candidates`
This is the upstream step that proposes plausible old memory neighbors for the new memory item.

### With `normalize_memory`
Normalization should happen before merge so that merge decisions are made on more canonicalized memory items.

### With `update_memory`
If the new item changes the old one rather than complements it, the correct next step is likely `update_memory`, not `merge_memory`.

### With `link_memory`
If two memory items are related but not the same memory object, they should remain separate and may later be linked.

---

## Design rationale

This design helps because:

### 1. It keeps merge precise
We prefer **high precision over high recall** in v0.
Bad merges are more damaging than missed merges.

### 2. It preserves explainability
Explicit provenance and merge decisions make the memory system auditable.

### 3. It separates maintenance operations cleanly
Merge, update, and link are different operations and should not be collapsed into one vague step.

### 4. It enables fair accounting
The cost of candidate retrieval, merge decision, update, and linking can be measured separately.

---

## Open questions

### 1. Should `merge_memory` support many-to-one merge in v0?
Current leaning: yes, but conservatively.

### 2. Should confidence increase after repeated-confirmation merge?
Current leaning: probably yes, but the exact rule is still open.

### 3. Should merge ever change `final_type`?
Current leaning: no in v0.
If types disagree, the safer default is likely `no_merge` or escalation.

### 4. Should merged memory preserve all source evidence or only the strongest evidence?
Current leaning: preserve provenance broadly, even if the user-facing representation is compact.

### 5. What should happen when one item is broader and another is narrower?
Example:
- “Jon plans to open a studio.”
- “Jon plans to open a dance studio in the fall.”

Current leaning: merge if the broader one can be safely refined by the narrower one.

---

## Current working summary

Current working assumptions for `merge_memory`:
- input = one new normalized memory item + upstream-retrieved candidate old memories
- output = explicit merge decision
- merge is for redundancy reduction and complementary consolidation
- merge is **not** for contradiction or state replacement
- relatedness is not enough; items must describe the same memory object
- provenance should be preserved explicitly
- candidate retrieval is treated as an upstream step / future skill, not internalized into `merge_memory`
