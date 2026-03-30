# Memory Item Field Transitions v0

## Why this document exists

`SHARED_MEMORY_ITEM_SCHEMA_V0.md` defines **what fields exist** on the shared `MemoryItem` object.

This document complements it by defining:
- which fields each skill reads,
- which fields each skill writes,
- which fields each skill should preserve,
- which fields each skill must not modify.

So this is a **dataflow contract** for the current memory-maintenance pipeline.

---

## Current pipeline scope

This document currently covers:
1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`
6. `update_memory`

---

## 1. `extract_memory`

### Input form
Not yet a full `MemoryItem`.
Input is raw conversation delta + optional metadata.

### Reads
- conversation delta
- optional session metadata
- optional dialogue timestamps

### Writes
Creates initial `MemoryItem` candidates with fields such as:
- `content`
- `evidence`
- `source_turn_ids`
- `suggested_type` (optional)
- `entities` (optional)
- `time_anchor` (optional)
- `speaker_attribution` (optional)
- `extraction_confidence`

### Preserves
Not applicable in the usual sense, since this is the creation stage.

### Must not write (in v0)
- `final_type`
- `category_confidence`
- `recommended_route`
- `normalized_content`
- `normalization_confidence`
- `consumed_memory_ids`
- `affected_memory_ids`

### Output expectation
Produces candidate `MemoryItem`s suitable for categorization.

---

## 2. `categorize_memory`

### Reads
- `content`
- `suggested_type` (optional)
- `evidence`
- `entities` (optional)
- `time_anchor` (optional)
- `speaker_attribution` (optional)
- `extraction_confidence` (optional)

### Writes
- `final_type`
- `category_confidence`
- `recommended_route`

### Preserves
Should preserve without rewriting:
- `content`
- `evidence`
- `source_turn_ids`
- `entities`
- `time_anchor`
- `speaker_attribution`
- `extraction_confidence`

### Must not modify (in v0)
- `evidence`
- `source_turn_ids`
- `content`

### Output expectation
Produces typed `MemoryItem`s ready for normalization.

---

## 3. `normalize_memory`

### Reads
- `content`
- `final_type`
- `evidence`
- `entities` (optional)
- `time_anchor` (optional)
- `speaker_attribution` (optional)
- `category_confidence` (optional)
- `recommended_route` (optional)

### Writes
- `normalized_content`
- `normalized_entities` (optional)
- `normalized_time_anchor` (optional)
- `normalization_confidence`
- `normalization_notes` (optional)

### Preserves
Should preserve:
- `content`
- `evidence`
- `source_turn_ids`
- `final_type`
- `category_confidence`
- `recommended_route`
- `speaker_attribution`

### Must not modify (in v0)
- `final_type`
- `category_confidence`
- `recommended_route`
- `evidence`

### Output expectation
Produces normalized `MemoryItem`s suitable for maintenance retrieval.

---

## 4. `retrieve_merge_candidates`

### Reads
From `source_memory`:
- `normalized_content`
- `final_type`
- `normalized_entities` (optional)
- `normalized_time_anchor` (optional)
- `recommended_route` (optional)
- provenance metadata (optional)

### Writes
This skill does **not primarily mutate** the source `MemoryItem`.
Instead, it produces a retrieval result object containing:
- candidate memory references
- candidate scores
- retrieval signals (optional)
- retrieval reasons (optional)

### Preserves
Should preserve the source memory unchanged.

### Must not modify (in v0)
Any core `MemoryItem` fields on the source object.

### Output expectation
Produces a shortlist of existing memory candidates for `merge_memory`.

---

## 5. `merge_memory`

### Reads
From `source_memory`:
- `normalized_content`
- `final_type`
- `normalized_entities` (optional)
- `normalized_time_anchor` (optional)
- provenance / evidence (optional)

From `candidate_memories`:
- `normalized_content`
- `final_type`
- anchors / evidence / provenance as needed

### Writes
Typically writes into a **MergeResult** rather than directly overwriting the source object.

Possible written fields in result layer:
- `merge_decision`
- `merge_confidence`
- `merge_reason`
- `merged_memory`
- `consumed_memory_ids`

### Preserves
Should preserve original source memory and candidate memories as auditable inputs.

### Must not modify (in v0)
Should not silently mutate or erase old memory objects in-place.
Any actual merge consequence should be explicit in the result object.

### Output expectation
Produces either:
- `merge`
- `no_merge`

with explicit provenance.

---

## 6. `update_memory`

### Reads
From `source_memory`:
- `normalized_content`
- `final_type`
- semantic anchors
- evidence / provenance (optional)

From `candidate_memories`:
- existing memory items in the same semantic slot

### Writes
Typically writes into an **UpdateResult** rather than directly mutating the original object.

Possible written fields in result layer:
- `update_decision`
- `update_confidence`
- `update_reason`
- `update_type`
- `updated_memory`
- `affected_memory_ids`
- `change_summary` (optional)

### Preserves
Should preserve source and old-memory provenance for auditability.

### Must not modify (in v0)
Should not directly decide archive/downweight/timeline consequences for superseded memory.
Those remain outside this skill.

### Output expectation
Produces either:
- `update`
- `no_update`

with explicit affected memory references.

---

## Cross-stage invariants

These are important field-level invariants across the current pipeline.

### Invariant 1: `evidence` should remain stable
Once created by extraction, evidence should usually be preserved, not rewritten casually.

### Invariant 2: `final_type` is owned by categorization
After `categorize_memory`, later stages should treat `final_type` as stable in v0.

### Invariant 3: `normalized_content` is owned by normalization
After `normalize_memory`, later stages may use it, but should not casually rewrite it inside ordinary maintenance logic.

### Invariant 4: maintenance decisions should be explicit
Merge/update consequences should appear in result schemas, not as silent in-place mutations.

### Invariant 5: provenance should be preserved
Maintenance should improve memory quality without destroying explainability.

---

## Transition summary table

| Skill | Reads | Writes | Must not modify |
|---|---|---|---|
| `extract_memory` | raw dialogue delta | initial `MemoryItem` fields | downstream fields |
| `categorize_memory` | candidate fields | `final_type`, `category_confidence`, `recommended_route` | `content`, `evidence` |
| `normalize_memory` | typed candidate | `normalized_content`, normalized anchors, normalization confidence | `final_type`, `recommended_route`, `evidence` |
| `retrieve_merge_candidates` | normalized source memory | retrieval result object | source `MemoryItem` |
| `merge_memory` | normalized source + candidate memories | `MergeResult` | silent in-place memory overwrite |
| `update_memory` | normalized source + update candidates | `UpdateResult` | archive/downweight decisions |

---

## Design rationale

This transition layer matters because it turns the current design from:
- a set of independent skill specs
into
- a coherent object transformation pipeline.

It helps us answer implementation-critical questions such as:
- what fields are guaranteed after each stage,
- what later skills may safely depend on,
- what boundaries must remain clean.

---

## Current working summary

Current working assumptions for field transitions v0:
- `extract_memory` creates the initial `MemoryItem`
- `categorize_memory` owns stable type assignment
- `normalize_memory` owns canonical representation
- retrieval skills should usually not mutate the shared object
- maintenance actions should return explicit result schemas rather than silent mutation
- key fields such as evidence, final type, and normalized content should remain stable once established

---

## Suggested next steps

Natural next steps after this document include:

### A. Continue extending the skill graph
Possible next skills:
- `score_memory`
- `link_memory`
- `retrieve_update_candidates`

### B. Add more formal implementation-facing schema
Possible future artifacts:
- JSON schema
- Pydantic model
- dataclass definitions
- result object definitions for merge/update/retrieval

### C. Add branching / orchestration layer
Eventually the linear transition view will need to be expanded into a policy-controlled graph.
