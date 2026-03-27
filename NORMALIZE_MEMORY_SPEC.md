# normalize_memory Spec (Draft v0)

## Goal

`normalize_memory` is responsible for converting categorized memory items into a more canonical, less ambiguous, and more comparable representation.

Its role is to make memory items easier for downstream modules to:
- compare
- merge
- update
- store
- retrieve

In one sentence:

> `normalize_memory` turns typed memory items into more stable memory representations without changing their semantic category.

---

## Inputs

### Required
- **categorized memory items**
  - output from `categorize_memory`

These items should already contain at least:
- `content`
- `final_type`
- `category_confidence`
- `recommended_route`

### Optional
- `evidence`
- `speaker_attribution`
- `session metadata`
- `dialogue timestamp`
- `entity hints`

### Not required in v0
- full memory store
- retrieval results
- global policy state

### Design decision
In v0, `normalize_memory` should operate primarily on the memory item itself and its local evidence/context, rather than over the whole memory base.
This keeps it distinct from `merge_memory` and `update_memory`.

---

## Output

The output is a list of **normalized memory items**.

The main output should still be centered on:
- `normalized_content`

with a small number of supporting structured fields when helpful.

---

## Core normalization targets (v0)

`normalize_memory` currently focuses on the following five types of normalization:

### 1. Time normalization
Convert relative or vague time expressions into more stable standardized anchors when possible.

Examples:
- “last June” → `2023-06`
- “next month” → inferred from session time
- “two years ago” → normalized relative to dialogue timestamp

### 2. Coreference / subject disambiguation
Resolve references such as:
- she
- he
- they
- my sister
- her friend

when recoverable from local context.

Goal:
- make the memory subject clearer
- reduce ambiguity for later merge/update/retrieval

### 3. Entity normalization
Unify different surface forms that refer to the same entity.

Examples:
- “my sister Anna” / “Anna” / “my sister”
- “Jon’s studio” / “the dance studio”

Goal:
- keep entity references more stable across memory items

### 4. Statement stabilization
Rewrite colloquial or unstable phrasing into a cleaner memory-friendly statement.

Examples:
- “kind of likes sunrise paintings” → “Melanie likes sunrise paintings.”
- “thinking about moving next year” → “Melanie plans to move next year.”

Goal:
- make the memory easier to compare and reuse later

### 5. Noise reduction
Remove filler, hedging, and irrelevant phrasing when this does not change the core fact.

Goal:
- preserve semantic meaning
- reduce downstream clutter

---

## Type preservation

### Current decision
`normalize_memory` should **not change `final_type`**.

That means:
- if the input is categorized as `event`, normalization should keep it as `event`
- if the input is categorized as `plan`, normalization should keep it as `plan`

### Rationale
Changing type would overlap too much with `categorize_memory`.
If type revision is needed in the future, it should happen via an explicit re-categorization mechanism, not inside normalization by default.

---

## Output schema (v0)

### Required fields
- `normalized_content`
  - canonicalized memory statement
- `final_type`
  - preserved from input
- `normalization_confidence`
  - confidence that normalization preserved the intended meaning

### Recommended fields
- `source_content`
  - original pre-normalized content
- `normalized_time_anchor`
  - normalized time anchor when applicable
- `normalized_entities`
  - normalized entity references when applicable
- `normalization_notes`
  - optional note(s) about what was normalized

### Design decision
In v0, the output should be centered on **`normalized_content` first**, with only a **small number of structured fields** such as time and entities.
We are **not** trying to fully convert every memory item into a rich structured schema at this stage.

---

## Responsibilities

`normalize_memory` is responsible for:
1. canonicalizing memory wording
2. standardizing time expressions when possible
3. resolving local references when possible
4. stabilizing entity naming when possible
5. reducing phrasing noise while preserving semantic meaning

---

## Non-responsibilities

`normalize_memory` is **not** responsible for:
1. extracting new memory from dialogue
2. assigning final type
3. changing final type
4. merging with existing memory
5. updating existing memory
6. deciding retention / promotion
7. making final routing or orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `merge_memory`
- `update_memory`
- `score_memory`
- `memory policy`

---

## Relationship with other skills

### With `extract_memory`
`extract_memory` may already perform first-pass normalization, especially for obvious time expressions.
`normalize_memory` acts as a second-pass stabilizer and correctness layer.

So the current view is:
- `extract_memory` does lightweight first-pass cleanup
- `normalize_memory` does systematic canonicalization

### With `categorize_memory`
`categorize_memory` defines what semantic role the memory item plays in the system.
`normalize_memory` does not change that role; it only stabilizes the expression.

### With `merge_memory` / `update_memory`
`normalize_memory` is an important precursor for later merge/update.
A major purpose of normalization is to make later comparison easier and more reliable.

---

## Example

### Input

```json
{
  "content": "Caroline said she started piano lessons last June and has been calmer ever since.",
  "final_type": "event",
  "category_confidence": 0.91,
  "recommended_route": "event_memory"
}
```

### Possible normalized output

```json
{
  "source_content": "Caroline said she started piano lessons last June and has been calmer ever since.",
  "normalized_content": "Caroline started piano lessons in June 2023.",
  "final_type": "event",
  "normalized_time_anchor": "2023-06",
  "normalized_entities": ["Caroline", "piano lessons"],
  "normalization_confidence": 0.89,
  "normalization_notes": [
    "resolved relative time expression",
    "removed reporting frame"
  ]
}
```

If the “has been calmer ever since” part was extracted as a separate candidate, it would be normalized separately.

---

## Design rationale

This design helps because:

### 1. It reduces ambiguity before merge/update
Memory items become more comparable and easier to align.

### 2. It avoids overloading extraction
Extraction focuses on finding candidates; normalization focuses on canonicalization.

### 3. It preserves modularity
Taxonomy, normalization, merge/update, and policy remain distinct layers.

### 4. It supports fair accounting
Normalization cost can be measured separately from extraction, categorization, and maintenance.

---

## Open questions

### 1. How aggressive should normalization be?
Current leaning:
- strong enough to improve comparability
- conservative enough not to rewrite facts into something unintended

### 2. Should normalization preserve reporting frames?
Example:
- “Caroline said Melanie wants to move next year.”

Open issue:
- do we normalize to the underlying claim?
- or preserve the fact that it was reported speech?

This may depend on memory type and attribution sensitivity.

### 3. Should entity normalization create canonical IDs or just stable names?
Current leaning in v0:
- stable names first
- canonical IDs can be added later

### 4. Should all memory types share the same normalization rules?
Probably not fully.
For example:
- `plan` may need stronger future-time normalization
- `relation` may need stronger entity-role normalization
- `state` may require more caution to avoid over-reification

### 5. Should normalization ever split or merge candidate boundaries?
Current leaning: no in v0.
Boundary changes should remain outside this skill.

---

## Current working summary

Current working assumptions for `normalize_memory`:
- it performs canonicalization, not categorization
- it does not change `final_type`
- it focuses on five areas:
  - time normalization
  - coreference / subject disambiguation
  - entity normalization
  - statement stabilization
  - noise reduction
- output is centered on `normalized_content`
- only a small number of structured fields are added in v0 (especially time and entities)
- it sits between categorization and later merge/update operations
