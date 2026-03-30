# Validation Plan v0

## Goal of this document

This document defines what kinds of validation can already be performed with the current memory-skill design, and what kinds should wait until more skills are specified.

The key idea is:

> we should start validating the current observe / maintenance pipeline now, without waiting for the full end-to-end system to be complete.

---

## 1. Current validation boundary

### What is already mature enough to validate
The current design already has a meaningful **observe / maintenance skeleton**:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`
- `score_memory`

This is enough for:
- module-level validation
- dataflow validation
- maintenance behavior validation
- schema / transition validation

### What is not yet complete enough for full validation
The current design still lacks enough of the **organization** and **answer-time retrieval** side to support full end-to-end benchmark comparison.

In particular, we are still missing or under-specifying:
- `link_memory`
- `reorganize_memory`
- retrieve-side policy / retrieval skills for answering

So we should distinguish between:
- **partial validation now**
- **full benchmark validation later**

---

## 2. Validation phases

## Phase A: Spec-to-module validation

### Objective
Validate whether the current skill specs are implementable as coherent modules.

### Questions to answer
- Are the skill boundaries clear enough to implement?
- Does the shared schema support the current pipeline?
- Are there obvious field conflicts or missing transitions?

### Good first targets
- `extract_memory`
- `categorize_memory`
- `normalize_memory`

### Success criteria
- Each skill can be implemented against the shared schema
- Outputs are compatible with downstream inputs
- The field transition contract is usable in practice

---

## Phase B: Maintenance-only validation

### Objective
Validate the memory maintenance logic without requiring answer-time retrieval.

### Questions to answer
- Can new memory be extracted consistently?
- Can duplicate / complementary memories be merged correctly?
- Can changed memories be updated correctly?
- Do score outputs look sensible?

### Focus
This phase tests whether the system can maintain a good memory base, even before it can fully use that base for question answering.

### Suggested scope
- small dialogue segments
- session-level updates
- hand-selected maintenance cases

---

## Phase C: Synthetic case validation

### Objective
Stress-test tricky skill boundaries with small controlled examples.

### Why this matters
Synthetic cases are ideal for testing:
- merge vs no-merge
- update vs no-update
- weak vs strong memory-worthiness
- ambiguous categorization
- normalization quality

### Example case families
1. exact duplicate memory
2. complementary detail merge
3. related-but-not-mergeable memories
4. state evolution
5. plan revision
6. fact correction
7. ambiguous category assignment
8. noisy colloquial phrasing needing normalization

### Success criteria
- the system behaves according to spec in controlled edge cases
- false merge / false update errors become visible early

---

## Phase D: Small integrated maintenance prototype

### Objective
Run a minimal version of the whole observe / maintenance path on small real examples.

### Current prototype path
1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`
6. `retrieve_update_candidates`
7. `update_memory`
8. `score_memory`

### Questions to answer
- Does the pipeline run end-to-end on small inputs?
- Do stages compose naturally?
- Are outputs interpretable?
- Are maintenance decisions explainable?

---

## 3. What should NOT be treated as ready yet

### Not yet recommended: full benchmark comparison
We should not yet jump directly into comparing this new system against MemOS / OpenViking on full benchmark evaluation.

### Reason
The current design still lacks enough retrieval-side and organization-side functionality.

Without those components, benchmark performance would be hard to interpret:
- poor answer quality might reflect missing retrieval skills,
- not necessarily flaws in the maintenance design.

So full end-to-end evaluation should wait until a minimal read-side pipeline exists.

---

## 4. What can be validated right now

The following can start immediately:

### A. Schema validation
- is `MemoryItem` sufficient?
- are field transitions workable?
- do result objects fit naturally?

### B. Skill boundary validation
- does `extract_memory` stay separate from `categorize_memory`?
- does `normalize_memory` stay separate from merge/update?
- does `merge_memory` stay separate from `update_memory`?

### C. Maintenance logic validation
- are merge candidates retrieved plausibly?
- are update candidates retrieved plausibly?
- are merge vs update decisions distinguishable?

### D. Score sanity validation
- do salience / stability / future utility behave intuitively?

---

## 5. Minimal recommended validation order

If we want an efficient validation path, the recommended order is:

### Step 1
Validate schema + transitions

### Step 2
Implement or simulate:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`

### Step 3
Run synthetic test cases for:
- merge
- update
- no-merge
- no-update

### Step 4
Add `score_memory` to see whether valuation aligns with intuition

### Step 5
Run a small integrated maintenance prototype on selected real dialogue slices

---

## 6. Suggested concrete validation artifacts

Useful validation artifacts could include:

### A. Synthetic maintenance test set
A small hand-built set of examples labeled for:
- merge / no-merge
- update / no-update
- expected category
- expected normalized form

### B. Stage-by-stage trace logs
For each example, record:
- extracted candidate
- category assignment
- normalized form
- merge candidates
- merge decision
- update candidates
- update decision
- score output

### C. Failure taxonomy
Track common failure types such as:
- over-extraction
- under-extraction
- wrong category
- bad normalization
- false merge
- missed merge
- false update
- missed update
- unintuitive scoring

---

## 7. What needs to exist before full end-to-end validation

Before full benchmark-style validation, we likely still need:

### Organization-side skills
- `link_memory`
- `reorganize_memory`

### Retrieve-side skills
At least a minimal answer-time retrieval path, such as:
- query analysis / routing
- answer-oriented retrieval
- retrieval granularity selection
- memory context assembly

### Possibly retrieve-side policy
A read-side counterpart to the current observe-side `memory_policy`

---

## 8. Current recommendation

### Recommendation
Start validating **now**, but validate the **maintenance pipeline first**, not the final system.

### Why
Because the current design is already strong enough for:
- structural validation
- module validation
- maintenance validation

but not yet complete enough for:
- definitive benchmark-level answer quality comparison

---

## 9. Current working summary

Current working view:
- maintenance-side validation is ready to begin
- full answer-time validation should wait
- synthetic and small-scale real-case validation are the best near-term next steps
- the main purpose of validation now is to check whether the current skills and schema compose cleanly
