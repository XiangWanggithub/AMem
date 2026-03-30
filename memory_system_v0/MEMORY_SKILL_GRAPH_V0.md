# Memory Skill Graph v0

This document summarizes the current v0 memory-maintenance skill graph derived from our draft design work.

It is intended to serve as:
- a compact overview of the current skill pipeline,
- a bridge between individual skill specs and future system design,
- a checkpoint before expanding to additional skills such as `score_memory`, `link_memory`, and higher-level memory policy.

---

## 1. Current skill graph (v0)

### Observe / maintenance pipeline

1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`
6. `retrieve_update_candidates`
7. `update_memory`
8. `score_memory`

This is the current core maintenance path for turning new dialogue context into maintained memory objects.

---

## 2. One-line role of each skill

### 1. `extract_memory`
Extract memory-worthy candidate items from the conversation delta since the last extraction.

### 2. `categorize_memory`
Assign stable memory type and a coarse recommended downstream route to each candidate.

### 3. `normalize_memory`
Convert typed memory items into more canonical, less ambiguous, and more comparable representations.

### 4. `retrieve_merge_candidates`
Retrieve a high-recall shortlist of old memory items that may describe the same memory object as the new memory item.

### 5. `merge_memory`
Decide whether the new memory and retrieved candidate memories should be fused into one consolidated memory object.

### 6. `update_memory`
Decide whether the new memory should revise, replace, or supersede an older memory in the same semantic slot.

---

## 3. Current dataflow intuition

### Step 1: extraction
Raw dialogue delta is converted into candidate memory items.

### Step 2: categorization
Candidates receive:
- `final_type`
- `category_confidence`
- `recommended_route`

### Step 3: normalization
Typed items are rewritten into more stable and canonical form.

### Step 4: merge-candidate retrieval
The new normalized item is used to retrieve plausible old memory neighbors for maintenance.

### Step 5: merge decision
If the new memory and an old memory describe the same memory object, they may be merged.

### Step 6: update decision
If the new memory changes or replaces an old memory in the same semantic slot, it may trigger update instead of merge.

---

## 4. Key boundaries between skills

### `extract_memory` vs `categorize_memory`
- `extract_memory` finds memory-worthy candidate content
- `categorize_memory` assigns stable type and route recommendation

### `categorize_memory` vs `normalize_memory`
- `categorize_memory` decides semantic role
- `normalize_memory` stabilizes representation without changing final type

### `normalize_memory` vs `merge_memory`
- `normalize_memory` canonicalizes the new item
- `merge_memory` decides whether it should fuse with old memory

### `merge_memory` vs `update_memory`
- `merge_memory` handles fusion of the same memory object
- `update_memory` handles revision / replacement in the same semantic slot

### `retrieve_merge_candidates` vs answer-time retrieval
- `retrieve_merge_candidates` is for memory maintenance
- answer-time retrieval is for question answering

---

## 5. Current principles that shape the graph

### Principle 1: modularity over hidden black-box processing
We want hidden internal operations (extraction, merge, update, routing, etc.) to become explicit, separately specifiable skills.

### Principle 2: fair accounting
Each skill should eventually be measurable in its own:
- token cost
- latency
- failure mode
- contribution to downstream quality

### Principle 3: local decision vs global policy
Current skills mostly make **local decisions**.
A future `memory policy` layer will make **global orchestration decisions**.

### Principle 4: precision-sensitive maintenance
For `merge_memory` and `update_memory`, incorrect maintenance operations are highly damaging.
So the current design is intentionally conservative.

### Principle 5: backend-adaptive architecture
At least some skills (especially retrieval-like skills) should be defined at the interface level and remain adaptable to different storage architectures.

---

## 6. Current v0 memory taxonomy

The current working taxonomy used by `categorize_memory` is:
- `event`
- `preference`
- `profile`
- `relation`
- `plan`
- `habit`
- `state`

This taxonomy is deliberately pragmatic and intended to support downstream storage, merge/update, and retrieval decisions.

---

## 7. Current skill-specific summary

### `extract_memory`
Core idea:
- extract memory-worthy candidates from new context

Current notable decisions:
- input = conversation delta since last extract
- output = candidate memory items
- candidate granularity = semantically self-contained minimal unit
- no hard cap on candidates from a long sentence
- may provide weak type hints only
- evidence should preferably include turn IDs

### `categorize_memory`
Core idea:
- convert candidates into stable typed memory objects

Current notable decisions:
- output includes:
  - `final_type`
  - `category_confidence`
  - `recommended_route`
- route here is recommendation, not final orchestration
- ambiguity is allowed, but v0 still prefers one final type per item

### `normalize_memory`
Core idea:
- canonicalize without changing semantic type

Current notable decisions:
- does not change `final_type`
- focuses on:
  - time normalization
  - coreference / subject disambiguation
  - entity normalization
  - statement stabilization
  - noise reduction
- output is centered on `normalized_content`

### `retrieve_merge_candidates`
Core idea:
- retrieve plausible merge candidates for maintenance

Current notable decisions:
- explicit skill in v0
- storage-agnostic at interface level
- backend-adaptive at implementation level
- high recall is preferred over final precision
- does not decide merge itself

### `merge_memory`
Core idea:
- fuse duplicate / complementary / repeated-confirmation memory items

Current notable decisions:
- merge is not update
- relatedness alone is not enough
- items must describe the same memory object
- provenance must be preserved explicitly
- candidate retrieval is upstream

### `update_memory`
Core idea:
- revise or replace old memory when new memory indicates change

Current notable decisions:
- update is not merge
- key concept = same semantic slot
- output includes:
  - `update_decision`
  - `update_type`
  - `affected_memory_ids`
- post-update handling of old memory remains outside this skill in v0

---

## 8. What is still missing from the v0 graph

The current graph is already meaningful, but not yet complete.
Recently added or newly specified extensions include:

- `retrieve_update_candidates`
- `score_memory`
- `analyze_query`
- `retrieve_answer_candidates`
- `assemble_memory_context`
- `link_memory`
- `reorganize_memory`
- `memory_policy`

The graph is no longer just a maintenance-only path; it now includes early retrieve-side and organization-side structure.

---

## 9. Current interpretation of system maturity

At this point, the project has moved beyond vague intuition.
We now have:
- a draft skill taxonomy,
- multiple skill-level specs,
- a partial but coherent maintenance pipeline,
- explicit boundaries between extraction, categorization, normalization, retrieval, merge, and update.

This means the work is now in a good position to transition from:
- conceptual sketch
into
- modular system design.

---

## 10. Suggested next steps

Two natural next directions are:

### Direction A: extend the graph
Continue adding missing maintenance / organization skills such as:
- `score_memory`
- `link_memory`
- `reorganize_memory`

### Direction B: consolidate the representation layer
Before adding too many more skills, define:
- a shared memory-item schema,
- shared field naming conventions,
- transitions between each stage.

Both directions are useful.
A reasonable short-term move is:
1. use this graph as the current checkpoint,
2. then either define the shared schema or continue with `score_memory`.
