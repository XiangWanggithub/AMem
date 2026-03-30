# update_memory Spec (Draft v0)

## Goal

`update_memory` is responsible for revising existing memory when new memory indicates **change, correction, replacement, or conflict**, rather than simple duplication or complementarity.

Its purpose is to handle memory evolution over time.

In one sentence:

> `update_memory` determines whether a new memory item should revise or replace an existing memory representation in the same semantic slot.

---

## Core distinction: update vs merge

### `merge_memory`
Use when multiple memories describe the **same memory object** and should be fused.

Goal:
- reduce redundancy
- increase completeness
- keep one underlying object

### `update_memory`
Use when new memory indicates that an existing memory should be revised, corrected, or superseded.

Goal:
- represent change over time
- handle correction / replacement
- preserve semantic evolution

### Current decision
`update_memory` should be used for:
- state change
- plan revision
- fact correction
- preference change
- profile change
- relation change

It should **not** be used for simple fusion of duplicate or complementary information.

---

## Inputs

### Required
- `source_memory`
  - the new normalized memory item currently under maintenance
- `candidate_memories`
  - existing memory items that may need revision, replacement, or correction

### Optional
- evidence
- timestamps
- provenance metadata
- entity alignment hints
- confidence fields

### Important design note
As with merge, `candidate_memories` are assumed to be supplied by an upstream retrieval step.
So `update_memory` itself does **not** search the whole memory store.

---

## Core judgment principle

The central question for `update_memory` is:

> Does the new memory provide credible evidence that an older memory in the same semantic slot should be revised, corrected, or replaced?

### Key idea: semantic slot
A **semantic slot** is the conceptual field being updated.

Examples:
- current emotional state
- future relocation plan
- current job affiliation
- current living place
- stable preference
- relationship status

If two memories are not about the same semantic slot, they should usually not trigger update.

---

## Typical update cases (v0)

### 1. State evolution
Example:
- “Caroline is stressed about work.”
- “Caroline feels much calmer now.”

### 2. Plan revision
Example:
- “Jon plans to move to Boston.”
- “Jon decided to stay in Chicago.”

### 3. Fact correction
Example:
- “The meeting is on Tuesday.”
- “Actually, the meeting is on Wednesday.”

### 4. Preference change
Example:
- “Melanie likes abstract art.”
- “Melanie now prefers sunrise paintings.”

### 5. Profile change
Example:
- “Jon works at company A.”
- “Jon recently joined company B.”

### 6. Relation change
Example:
- “They are just coworkers.”
- “They are now close friends.”

---

## Non-update cases (v0)

### 1. Duplicate or complementary information
Example:
- “Jon plans to open a dance studio.”
- “Jon plans to open a dance studio in the fall.”

This should usually be handled by `merge_memory`, not `update_memory`.

### 2. Related but different semantic slots
Example:
- “Melanie likes sunrise paintings.”
- “Melanie paints in the morning.”

These may be related, but they are not the same semantic slot.

### 3. Mere co-occurrence
Example:
- two facts appear in the same topic area but do not revise each other

---

## Output

The output should explicitly state whether an update occurs.

### Required fields
- `update_decision`
  - `update` or `no_update`
- `update_confidence`
  - confidence in the decision
- `update_reason`
  - short rationale for the decision

### If updated
- `update_type`
  - coarse type of update
- `updated_memory`
  - resulting memory representation
- `affected_memory_ids`
  - old memories revised / superseded by this update

### Optional
- `previous_memory_snapshot`
  - compact representation of the prior version
- `change_summary`
  - human-readable summary of what changed

---

## Update types (v0)

Suggested `update_type` values:
- `state_change`
- `plan_revision`
- `fact_correction`
- `preference_change`
- `profile_change`
- `relation_change`

These are intended to make downstream handling and auditing easier.

---

## Example

### Input
source:
- “Jon decided to stay in Chicago.”

candidate:
- “Jon plans to move to Boston.”

### Output

```json
{
  "update_decision": "update",
  "update_type": "plan_revision",
  "update_confidence": 0.95,
  "update_reason": "new memory replaces prior relocation plan",
  "updated_memory": {
    "normalized_content": "Jon decided to stay in Chicago.",
    "final_type": "plan"
  },
  "affected_memory_ids": ["m_old_plan_4"]
}
```

### Non-update example

```json
{
  "update_decision": "no_update",
  "update_confidence": 0.82,
  "update_reason": "related but not the same semantic slot"
}
```

---

## Responsibilities

`update_memory` is responsible for:
1. identifying whether a new memory should revise an old memory
2. determining whether the relation is change/correction/replacement rather than merge
3. producing an updated representation when appropriate
4. making the update auditable via explicit decision and affected IDs

---

## Non-responsibilities

`update_memory` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. retrieving the full memory store
5. merging duplicate or complementary memory
6. deciding long-term retention
7. deciding how superseded memories are archived, downweighted, or displayed
8. making final global orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_update_candidates` (future / upstream skill)
- `merge_memory`
- `score_memory`
- `memory policy`

---

## Relationship with other skills

### With `merge_memory`
If two memories describe the same object and should be fused, use `merge_memory`.
If the new one changes or replaces the old one, use `update_memory`.

### With `retrieve_update_candidates`
This is the likely upstream step that surfaces existing memories in the same semantic slot.

### With `score_memory` / policy
Old memories affected by an update may later be:
- archived
- downweighted
- marked as superseded
- preserved for timeline/history

But these consequences are **not** handled inside `update_memory` itself in v0.

---

## Design rationale

This design helps because:

### 1. It separates fusion from revision
Merge and update are not the same operation and should remain distinct.

### 2. It preserves temporal evolution
A memory system should capture that things change over time, not just accumulate facts.

### 3. It supports explainability
Explicit update types and change summaries make system behavior more understandable.

### 4. It supports fair accounting
Update cost can be measured separately from candidate retrieval, merge, and retention decisions.

---

## Open questions

### 1. Should `update_memory` always preserve the old memory as a snapshot?
Current leaning:
- often useful
- but may be policy-controlled rather than mandatory

### 2. Should update ever change `final_type`?
Current leaning:
- no by default in v0
- if type changes are needed, they may require a more explicit re-categorization step

### 3. Should update support many-to-one or one-to-many revision patterns?
Current leaning:
- possible in the future
- v0 can start simpler

### 4. How strict should semantic-slot matching be?
Current leaning:
- fairly strict in v0
- precision matters more than aggressive updating

### 5. Should correction and evolution be handled by one skill or split later?
Current leaning:
- keep unified in v0 under `update_memory`
- may split later if needed

---

## Current working summary

Current working assumptions for `update_memory`:
- it handles change, correction, replacement, and conflict-like revision
- it is distinct from merge
- its core judgment is whether the new memory should revise an older memory in the same semantic slot
- output should explicitly include update decision, update type, and affected memory IDs
- candidate retrieval is upstream and not internalized into `update_memory`
- post-update handling of old memory remains outside this skill in v0
