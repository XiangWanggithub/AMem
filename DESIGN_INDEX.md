# Design Index

This document is a compact index of the current memory-system design documents in the `memory-eval` project.

Its goals are:
- help humans and agents quickly find the right document,
- provide a recommended reading order,
- clarify how the current docs relate to each other.

---

## 1. High-level overview docs

### `MEMORY_SKILL_MAPPING.md`
Use this to understand the original abstraction step:
- what we learned from MemOS
- what we learned from OpenViking
- how those framework internals were mapped into reusable memory skills

### `MEMORY_SKILL_GRAPH_V0.md`
Use this to understand the current v0 skill graph:
- which skills currently exist
- how they connect in the maintenance pipeline
- what is still missing

---

## 2. Shared structure docs

### `SHARED_MEMORY_ITEM_SCHEMA_V0.md`
Defines the shared object-level schema:
- what a `MemoryItem` is
- what supporting objects exist
- what field groups are shared across skills

### `MEMORY_ITEM_FIELD_TRANSITIONS_V0.md`
Defines the dataflow contract:
- which fields each skill reads
- which fields each skill writes
- which fields must remain stable

Read this together with the shared schema document.

---

## 3. Skill specs

### Formation / early maintenance
- `EXTRACT_MEMORY_SPEC.md`
- `CATEGORIZE_MEMORY_SPEC.md`
- `NORMALIZE_MEMORY_SPEC.md`

These define how raw dialogue becomes a typed and normalized memory item.

### Maintenance retrieval + action
- `RETRIEVE_MERGE_CANDIDATES_SPEC.md`
- `MERGE_MEMORY_SPEC.md`
- `RETRIEVE_UPDATE_CANDIDATES_SPEC.md`
- `UPDATE_MEMORY_SPEC.md`

These define how new memory interacts with old memory.

### Valuation
- `SCORE_MEMORY_SPEC.md`

This defines how memory items are evaluated before future retention/policy decisions.

---

## 4. Orchestration doc

### `MEMORY_POLICY_SPEC.md`
Defines the current v0 policy layer:
- observe-side policy only
- explicit phase input
- explicit plan output
- selected / skipped skills
- budget profile and reason

This is the current top-level orchestration document.

---

## 5. Suggested reading order

If someone wants the fastest path to understanding the current design, use this order:

1. `MEMORY_SKILL_MAPPING.md`
2. `MEMORY_SKILL_GRAPH_V0.md`
3. `SHARED_MEMORY_ITEM_SCHEMA_V0.md`
4. `MEMORY_ITEM_FIELD_TRANSITIONS_V0.md`
5. `EXTRACT_MEMORY_SPEC.md`
6. `CATEGORIZE_MEMORY_SPEC.md`
7. `NORMALIZE_MEMORY_SPEC.md`
8. `RETRIEVE_MERGE_CANDIDATES_SPEC.md`
9. `MERGE_MEMORY_SPEC.md`
10. `RETRIEVE_UPDATE_CANDIDATES_SPEC.md`
11. `UPDATE_MEMORY_SPEC.md`
12. `SCORE_MEMORY_SPEC.md`
13. `MEMORY_POLICY_SPEC.md`

---

## 6. Current system shape

The current design can be read as three layers:

### A. Maintenance pipeline
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`

### B. Valuation layer
- `score_memory`

### C. Orchestration layer
- `memory_policy`

---

## 7. What is still missing

Important likely next additions:
- `link_memory`
- `reorganize_memory`
- possibly stronger retrieve-side policy
- implementation-facing schemas / dataclasses / JSON schema
- prototype execution layer

---

## 8. Intended use of this index

This index is not a replacement for the detailed documents.
It is only meant to help answer:
- where should I start reading?
- which doc explains this concept?
- what is the current top-level structure?
