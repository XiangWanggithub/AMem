# Progress Summary

## Current stage

The project is currently at the end of the **maintenance-side v0 validation** stage.

This means:
- the core memory skills have been decomposed and documented,
- the shared schema and field transitions have been defined,
- a first synthetic maintenance testset has been built,
- first-round executor testing with MiniMax M2.5 has been completed for the current maintenance-side seed set.

We are **not yet** at the stage of full end-to-end benchmark validation.

---

## Completed

### 1. Skill abstraction and mapping
Completed:
- mapping from MemOS and OpenViking into reusable memory skills
- high-level skill graph draft

Key docs:
- `MEMORY_SKILL_MAPPING.md`
- `MEMORY_SKILL_GRAPH_V0.md`

### 2. Shared structure design
Completed:
- shared memory item schema
- field transition contract across stages

Key docs:
- `SHARED_MEMORY_ITEM_SCHEMA_V0.md`
- `MEMORY_ITEM_FIELD_TRANSITIONS_V0.md`

### 3. Core skill specs completed
Completed specs:
- `EXTRACT_MEMORY_SPEC.md`
- `CATEGORIZE_MEMORY_SPEC.md`
- `NORMALIZE_MEMORY_SPEC.md`
- `RETRIEVE_MERGE_CANDIDATES_SPEC.md`
- `MERGE_MEMORY_SPEC.md`
- `RETRIEVE_UPDATE_CANDIDATES_SPEC.md`
- `UPDATE_MEMORY_SPEC.md`
- `SCORE_MEMORY_SPEC.md`
- `MEMORY_POLICY_SPEC.md`

### 4. Documentation structure
Completed:
- design index
- validation plan

Key docs:
- `DESIGN_INDEX.md`
- `VALIDATION_PLAN_V0.md`

### 5. Synthetic maintenance testset
Completed:
- first synthetic seed set built
- current file: `synthetic_maintenance_cases_v0.jsonl`
- current size: **18 cases**

Current family coverage:
- extract × 3
- categorize × 3
- normalize × 3
- merge × 3
- update × 3
- score × 3

### 6. Manual skill-style executor testing started
Completed:
- `merge_memory` was packaged into a manually invokable skill form
- MiniMax M2.5 execution conventions documented
- first-round runner created

Key docs/files:
- `MERGE_MEMORY_SKILL_V0.md`
- `MERGE_MEMORY_SKILL_EXAMPLE_PROMPT.md`
- `SKILL_EXECUTION_MODEL_NOTES.md`
- `run_skill_round1.py`

---

## Current validation results

### Round 1 synthetic executor testing
MiniMax M2.5 was used as the skill executor.

Current known result:
- maintenance-side synthetic executor validation has now reached a stable first checkpoint

Current validated status after adjustment of the `extract_001` expectation:
- extract: effectively aligned after boundary correction
- merge: 3 / 3
- categorize: 3 / 3
- normalize: 3 / 3
- update: 3 / 3
- score: 3 / 3

Interpretation:
- maintenance-side v0 is now considered **initially validated** at the synthetic seed-set level

### What this means
Current interpretation:
- the current skill contracts are executable,
- the maintenance-side boundaries are workable on the seed cases,
- MiniMax M2.5 can act as a structured executor for these skill prompts,
- the shared schema and transition design are at least coherent enough for first-round testing.

---

## Current conclusions

### 1. The maintenance-side design is no longer just conceptual
We now have:
- explicit skill definitions,
- shared object schema,
- transition rules,
- test cases,
- early executor validation.

### 2. Merge and update are successfully separated at the current seed-set level
This is important because the merge/update boundary is one of the most fragile parts of the design.

### 3. MiniMax M2.5 is workable as a skill executor
At least for current synthetic cases, the model can follow the skill prompt and output structured JSON.

### 4. Prompt cost is still relatively high
Even though outputs are good, current executor prompts are still somewhat long and likely need refinement later.

### 5. Maintenance-side v0 has reached a usable checkpoint
The current maintenance-side pipeline is no longer just a design artifact; it has passed an initial synthetic validation loop.

### 6. Full benchmark validation is still premature
We still lack enough of the organization-side and answer-time retrieval-side system to interpret full benchmark results cleanly.

---

## Open issues

### 1. Prompt length / token cost
Current skill prompts are still verbose.
A later refinement pass should likely:
- shorten executor prompts,
- constrain reason fields more tightly,
- reduce repeated instruction text.

### 2. Retrieve-side skill family remains incomplete
We have maintenance-side retrieval (`retrieve_merge_candidates`, `retrieve_update_candidates`), but not yet the full answer-time retrieval path.

### 3. Organization-side skill family remains incomplete
Still missing or underdeveloped:
- `link_memory`
- `reorganize_memory`

### 4. Synthetic testset is still a seed set
Current 18 cases are good enough for v0, but not yet broad enough to claim strong coverage.

### 5. Current validation is still maintenance-side only
We have not yet validated:
- retrieve-side behavior for answering,
- organization-side structure quality,
- full end-to-end QA performance.

---

## Current recommended next steps

### Option A: Prompt refinement
- shorten skill executor prompts
- tighten `reason` constraints
- reduce token cost while preserving behavior

### Option B: Expand synthetic testset carefully
- add more tricky boundary cases
- especially attribution cases
- ambiguous categorize cases
- harder merge/update negatives

### Option C: Start retrieve-side skill design
Design the minimal read-side retrieval path needed before full end-to-end validation.

### Option D: Add missing organization-side skills
Continue with:
- `link_memory`
- `reorganize_memory`

---

## Current recommendation

The project should continue in a staged way:
1. keep maintenance-side validation moving,
2. refine prompts when needed,
3. gradually add retrieval-side and organization-side capabilities,
4. only then move into full benchmark comparison.

This remains the cleanest path for preserving interpretability and fair accounting.
