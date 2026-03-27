# Shared Memory Item Schema v0

## Why this document exists

As the memory system becomes more modular, multiple skills now operate over the same evolving memory object:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `update_memory`

Without a shared schema, each skill may drift into its own private format, making the system:
- harder to maintain,
- harder to audit,
- harder to compare,
- harder to extend.

So this document defines the current **shared object-level schema** used across the memory pipeline.

The key design principle is:

> there should be one shared memory-item contract, rather than one separate full schema per skill.

Each skill may still define its own **result schema** when necessary, but they should all operate on top of the same shared memory item structure.

---

## 1. Schema layers

We distinguish two levels of schema:

### A. Shared object schemas
These are reusable objects that persist across multiple skills.

Main examples:
- `MemoryItem`
- `Evidence`
- `SpeakerAttribution`
- `TimeAnchor` (lightweight form in v0)

### B. Skill result schemas
These are operation-specific outputs returned by individual skills.

Examples:
- `MergeResult`
- `UpdateResult`
- `RetrieveMergeCandidatesResult`

So:
- shared object schema = stable memory object format
- skill result schema = action result format

---

## 2. Core object schema: `MemoryItem`

`MemoryItem` is the main object passed across the memory pipeline.

### Conceptual role
A `MemoryItem` is a memory candidate or maintained memory object that progressively accumulates:
- extraction information
- categorization information
- normalization information
- maintenance decisions

It is the central shared carrier between skills.

---

## 3. `MemoryItem` field groups

We organize fields by function rather than by skill.

### A. Identity fields
- `memory_id`
  - stable memory identifier when available

### B. Content fields
- `content`
  - original extracted candidate content
- `normalized_content`
  - canonicalized memory content after normalization

### C. Typing fields
- `suggested_type`
  - weak hint from extraction
- `final_type`
  - stable assigned type from categorization

### D. Confidence fields
- `extraction_confidence`
- `category_confidence`
- `normalization_confidence`

### E. Evidence / grounding fields
- `evidence`
  - structured source grounding
- `source_turn_ids`
  - convenient access to source turn ids

### F. Semantic anchor fields
- `entities`
- `normalized_entities`
- `time_anchor`
- `normalized_time_anchor`
- `speaker_attribution`

### G. Routing / maintenance fields
- `recommended_route`
- `merge_status` (optional in future)
- `update_status` (optional in future)

### H. Provenance / lineage fields
- `created_at`
- `updated_at`
- `consumed_memory_ids`
- `affected_memory_ids`

Not all fields are required in v0.
The point is to define the shared space clearly.

---

## 4. Minimal v0 `MemoryItem`

The minimal practical v0 shape is smaller.

### Required or near-required fields in early stages
- `content`
- `evidence`

### Expected after categorization
- `final_type`
- `category_confidence`
- `recommended_route`

### Expected after normalization
- `normalized_content`
- `normalization_confidence`

### Usually useful throughout
- `entities`
- `time_anchor`
- `speaker_attribution`

So a minimal but useful v0 object might look like:

```json
{
  "content": "Caroline started piano lessons last June.",
  "evidence": [
    {
      "turn_id": "t_17",
      "text_span": "started piano lessons last June"
    }
  ],
  "final_type": "event",
  "category_confidence": 0.92,
  "recommended_route": "event_memory",
  "normalized_content": "Caroline started piano lessons in June 2023.",
  "normalization_confidence": 0.90,
  "entities": ["Caroline", "piano lessons"],
  "time_anchor": "2023-06"
}
```

---

## 5. Supporting object schema: `Evidence`

`Evidence` anchors a memory item back to source dialogue.

### v0 fields
- `turn_id`
- `text_span`

### Notes
- evidence should preferably include turn IDs
- evidence helps auditing, debugging, and alignment with original dialogue
- multiple evidence entries may be allowed

Example:

```json
{
  "turn_id": "t_17",
  "text_span": "Caroline started piano lessons last June"
}
```

---

## 6. Supporting object schema: `SpeakerAttribution`

`SpeakerAttribution` helps distinguish:
- who said the information
- who the memory is about

This is especially useful for reported speech and cross-person references.

### v0 lightweight form
Possible fields:
- `speaker`
- `memory_subject`

### Example

```json
{
  "speaker": "Caroline",
  "memory_subject": "Melanie"
}
```

### Example use case
“Caroline said Melanie wants to move next year.”

Without attribution, later stages may confuse:
- who made the statement
- whose plan it actually is

---

## 7. Supporting object schema: `TimeAnchor`

In v0, time can remain lightweight.
We do not need a full formal temporal ontology yet.

### v0 representation
- string-based normalized anchor

Examples:
- `2023-06`
- `2024-01-15`
- `2024-Q1`

### Design choice
- extraction may do first-pass normalization
- normalization may do second-pass correction or enforcement

---

## 8. Field ownership by skill

This is one of the most important parts of the schema.

### `extract_memory` typically creates
- `content`
- `evidence`
- `source_turn_ids`
- `suggested_type` (optional)
- `entities` (optional)
- `time_anchor` (optional)
- `speaker_attribution` (optional)
- `extraction_confidence`

### `categorize_memory` typically creates
- `final_type`
- `category_confidence`
- `recommended_route`

### `normalize_memory` typically creates
- `normalized_content`
- `normalized_entities`
- `normalized_time_anchor`
- `normalization_confidence`

### `retrieve_merge_candidates` does not mainly mutate `MemoryItem`
It produces candidate sets referencing existing memory items.

### `merge_memory` may create or modify
- `consumed_memory_ids`
- merged provenance relationships
- consolidated `normalized_content` (inside a merge result)

### `update_memory` may create or modify
- `affected_memory_ids`
- update lineage or change summary (in result object)

---

## 9. Mutability rules

Not all fields should be treated the same.

### A. Immutable / mostly immutable fields
Once created, these should usually be preserved rather than rewritten:
- `evidence`
- `source_turn_ids`
- `extraction_confidence` (historical)

### B. Stabilizing fields
These may be added or refined, but should not be casually overwritten:
- `final_type`
- `normalized_content`
- `normalized_entities`
- `normalized_time_anchor`

### C. Maintenance / lineage fields
These are expected to evolve over time:
- `consumed_memory_ids`
- `affected_memory_ids`
- `updated_at`

### D. Optional / stage-local fields
These may exist only for some stages or analyses:
- `suggested_type`
- `normalization_notes`
- intermediate retrieval metadata

---

## 10. Relationship to skill result schemas

Shared object schema should not be confused with result schemas.

### Example: `MemoryItem`
A stable object used across multiple skills.

### Example: `MergeResult`
A skill-specific output such as:
- merge decision
- merged memory
- consumed IDs
- merge reason

### Example: `UpdateResult`
A skill-specific output such as:
- update decision
- update type
- affected IDs
- change summary

So implementation-wise:
- `MemoryItem` is the shared object
- skill-specific results wrap or reference `MemoryItem`

---

## 11. Why not copy the schema into every skill?

Because that would create fragmentation.

Instead, each skill should only specify:
1. which fields it reads
2. which fields it produces
3. which fields it must not modify

This keeps the system cleaner and more extensible.

In other words:

> shared schema = common protocol
> skill spec = local transformation contract

---

## 12. Current working summary

Current working assumptions for shared schema v0:
- there should be one shared `MemoryItem` contract across skills
- skills should not each define their own full private memory format
- supporting objects include at least:
  - `Evidence`
  - `SpeakerAttribution`
  - lightweight `TimeAnchor`
- `MemoryItem` should carry content, type, evidence, anchors, confidence, and later provenance
- each skill is responsible for only part of the field space
- complex actions like merge/update should use separate result schemas on top of shared `MemoryItem`

---

## 13. Suggested next step

Now that the shared schema direction is clearer, one strong next step is to define either:

### A. field-level transitions across the pipeline
For each stage, specify exactly:
- input fields
- output fields
- preserved fields

or

### B. the next missing maintenance skill
Likely candidates:
- `score_memory`
- `link_memory`
- `retrieve_update_candidates`

Both would build naturally on top of this shared schema.
