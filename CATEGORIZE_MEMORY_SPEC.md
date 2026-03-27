# categorize_memory Spec (Draft v0)

## Goal

`categorize_memory` is responsible for assigning a **stable memory type** and a **coarse handling recommendation** to candidate memory items produced by `extract_memory`.

Its role is not to extract new memory from raw dialogue, and not to make final global orchestration decisions. Instead, it performs a **local semantic decision**:
- what type of memory this candidate most likely is,
- how it should generally be handled downstream.

In one sentence:

> `categorize_memory` turns candidate memory items into typed memory objects with a recommended downstream route.

---

## Inputs

### Required
- **candidate memory items**
  - output from `extract_memory`

### Optional
- **taxonomy definition**
  - the currently supported memory categories
- **light context**
  - session metadata
  - evidence context
  - speaker attribution
- **category rules / examples**
  - definitions or examples of memory classes

### Not required in v0
- full memory store
- full dialogue history
- retrieval results
- global budget state

### Design decision
In v0, `categorize_memory` should mainly operate on the extracted candidates themselves, rather than on the whole memory base.
This keeps it distinct from:
- `merge_memory`
- `update_memory`
- higher-level `memory policy`

---

## Output

The output is a list of **categorized memory items**.

Each item should at least contain:
- a stable final type
- a confidence score
- a recommended downstream route

---

## Taxonomy (v0)

The current working taxonomy is:
- `event`
- `preference`
- `profile`
- `relation`
- `plan`
- `habit`
- `state`

### Type intuition

#### `event`
A discrete or relatively bounded occurrence.

Examples:
- started piano lessons
- attended a meeting
- moved to a new city

#### `preference`
A relatively stable like / dislike / taste / inclination.

Examples:
- prefers sunrise paintings
- likes tea more than coffee

#### `profile`
A long-term identity, background, role, or bio-like fact.

Examples:
- works as a designer
- is a graduate student

#### `relation`
A meaningful relation between people, organizations, or places.

Examples:
- is close friends with X
- collaborates with Y

#### `plan`
A future intention, goal, commitment, or explicit plan.

Examples:
- plans to open a studio
- intends to travel next month

#### `habit`
A repeated or routine behavior pattern.

Examples:
- goes biking every weekend
- journals at night

#### `state`
A current or ongoing condition, feeling, stance, or status.

Examples:
- feels calmer now
- is stressed about work

---

## Output schema (v0)

### Required fields
- `content`
  - inherited or carried over candidate content
- `final_type`
  - final assigned type from the v0 taxonomy
- `category_confidence`
  - confidence of the final type assignment
- `recommended_route`
  - coarse downstream handling recommendation

### Optional fields
- `alternative_types`
  - plausible backup categories when ambiguity is meaningful
- `reason`
  - short explanation of why this category was chosen
- `schema_hint`
  - optional hint for downstream storage schema

---

## Route design

### Key principle
`categorize_memory` should output a **recommended route**, not a final route.

That means:
- `categorize_memory` provides a local, semantically grounded recommendation
- higher-level `memory policy` keeps the right to accept, revise, or override it

### Why this split matters
If route is decided fully inside `categorize_memory`, it overlaps too much with policy.
If route is omitted entirely, policy must redo too much local semantic work.

So we use a middle ground:

> categorize gives a **coarse route recommendation**, while policy makes the **final orchestration decision**.

### Recommended route examples (v0)
- `event_memory`
- `preference_memory`
- `profile_memory`
- `relation_memory`
- `plan_memory`
- `habit_memory`
- `state_memory`

These are intentionally coarse and should not yet encode a full skill graph.

---

## Responsibilities

`categorize_memory` is responsible for:
1. assigning a stable final type to each candidate memory item
2. resolving weak ambiguity from extraction-time hints
3. producing a coarse recommended route for downstream handling
4. making candidate memories more ready for normalization, merge/update, and storage

---

## Non-responsibilities

`categorize_memory` is **not** responsible for:
1. extracting memory from raw dialogue
2. merging candidates with old memory
3. updating old memory with new evidence
4. deciding long-term retention
5. making final global routing decisions
6. deciding budget-aware orchestration

These belong more naturally to:
- `extract_memory`
- `merge_memory`
- `update_memory`
- `score_memory`
- `memory policy`

---

## Ambiguity handling

Some candidate memories naturally fit more than one category.

Examples:
- “Caroline feels calmer after starting piano lessons.”
  - could be `state`
  - could also be interpreted as an event consequence

- “She is preparing to move next month.”
  - could be `plan`
  - could also contain ongoing `state` or process information

### Current decision
In v0:
- each candidate should receive **one final type**
- but may optionally include `alternative_types`

### Practical principle
When ambiguity exists, prefer the category that is:

> most useful for downstream storage, merge/update, and retrieval

This is a **pragmatic taxonomy**, not a purely philosophical one.

---

## Relationship with extract_memory

The boundary between `extract_memory` and `categorize_memory` is:

### `extract_memory`
- identifies memory-worthy content
- creates candidate items
- may provide weak type hints

### `categorize_memory`
- finalizes stable memory type
- converts weak hints into explicit category assignments
- provides recommended downstream route

So:
- `extract_memory` finds candidate memory
- `categorize_memory` stabilizes its semantic role in the system

---

## Design rationale

This design helps because:

### 1. It preserves modularity
Extraction and categorization are separated.
Changes in taxonomy do not require redesigning extraction from scratch.

### 2. It supports policy layering
Categorization gives local semantic recommendations, while policy handles final global orchestration.

### 3. It enables fair accounting
We can separately measure the cost of:
- extraction
- categorization
- normalization
- merge/update
- policy decisions

---

## Open questions

### 1. Should `alternative_types` be included in v0 output?
Current leaning: optional, only when ambiguity is meaningful.

### 2. Should `reason` be retained in structured output?
It may help debugging and analysis, but might be unnecessary overhead in production. Current leaning: optional.

### 3. Should `recommended_route` always be a simple type-aligned bucket?
Current leaning: yes in v0.

That is:
- `event` -> `event_memory`
- `preference` -> `preference_memory`
- etc.

Later versions may allow richer route recommendations.

### 4. Should one category map to multiple downstream schemas?
Possibly yes in the future, but v0 should keep the mapping simple.

### 5. Should categorization be allowed to revise candidate boundaries?
Current leaning: no in v0.

Boundary revision should remain outside this skill, otherwise it starts overlapping too much with extraction and normalization.

---

## Current working summary

Current working assumptions for `categorize_memory`:
- input = candidate memory items from `extract_memory`
- output = typed memory items
- v0 taxonomy = event / preference / profile / relation / plan / habit / state
- output should include:
  - `final_type`
  - `category_confidence`
  - `recommended_route`
- route here means **recommended route**, not final route
- final orchestration remains the responsibility of higher-level `memory policy`
- ambiguity is allowed, but v0 still prefers one final type per item
