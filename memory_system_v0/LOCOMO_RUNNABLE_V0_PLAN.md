# LoCoMo Runnable v0 Plan

## Goal

Define the minimum system design needed to run the current memory-skill architecture on LoCoMo10 in an end-to-end way.

This document is not about perfecting every skill. It is about deciding:
- what is already good enough to use,
- what should be simplified or temporarily disabled,
- how the current skill set can be assembled into a runnable prototype.

In one sentence:

> This plan turns the current skill design into a minimum viable LoCoMo10-executable memory system.

---

## 1. Current readiness

### Already available
We already have draft or validated pieces for:

#### Maintenance side
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`
- `score_memory`

#### Retrieve side
- `analyze_query`
- `retrieve_answer_candidates`
- `assemble_memory_context`

#### Organization side
- `link_memory`
- `reorganize_memory`

#### Infrastructure-side design
- shared memory schema
- field transitions
- observe-side policy concept
- synthetic validation sets

### Current limitation
What is still missing is not mainly one more skill, but a:

> **runtime + policy + LoCoMo adapter layer**

---

## 2. Runnable v0 objective

The objective of v0 is:

- not to build the final best memory system,
- but to build the **first end-to-end runnable version** on LoCoMo10.

That means the system should:
1. ingest LoCoMo conversation turns,
2. maintain its memory state using current skills,
3. retrieve memory for LoCoMo questions,
4. answer questions,
5. produce outputs that can be evaluated by the existing evaluation pipeline.

---

## 3. Proposed runnable v0 skill subset

## A. Observe / maintenance path

Enable in v0:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`
- `score_memory`

### Notes
These are already the strongest and most validated part of the current system.

---

## B. Retrieve path

Enable in v0:
- `analyze_query`
- `retrieve_answer_candidates`
- `assemble_memory_context`
- answer model

### Notes
This forms the current minimal answer-time retrieval loop.

---

## C. Organization path

### v0 recommendation
- enable `link_memory`
- keep `reorganize_memory` in **restricted mode**

Restricted mode means:
- only triggered under simple policy conditions,
- perhaps only at session boundaries,
- not run after every memory event,
- optionally log reorganization proposals without always applying them.

### Rationale
`link_memory` is local and already conceptually clear.
`reorganize_memory` is structurally valuable but still more policy-sensitive and less validated.

---

## 4. Proposed runtime skeleton

### Observe-time runtime
For each LoCoMo conversation turn:

1. feed turn into observe-side policy
2. select maintenance path
3. run enabled skills in sequence
4. update memory state
5. record trace/logs

### Retrieve-time runtime
For each LoCoMo question:

1. run `analyze_query`
2. run `retrieve_answer_candidates`
3. run `assemble_memory_context`
4. call answer model with assembled context
5. store answer + trace

---

## 5. Proposed policy v0

### Observe-side policy v0
Start simple.
Use a **rule-based or hybrid** policy.

Example strategy:
- default path: extract → categorize → normalize
- if candidate memory seems substantial: attempt merge/update retrieval
- always score after maintenance
- allow `link_memory` only when a clear related-but-distinct relation appears
- allow `reorganize_memory` only at session boundaries or after enough accumulation

### Retrieve-side policy v0
Also start simple.

Example strategy:
- always run `analyze_query`
- always run `retrieve_answer_candidates`
- always run `assemble_memory_context`
- keep retrieve-side budget fixed in v0

---

## 6. LoCoMo adapter requirements

To run on LoCoMo10, we need an adapter layer that converts dataset structure into runtime inputs.

### Observe-side adapter
Convert LoCoMo turns into:
- speaker
- text
- timestamp/session metadata
- dialogue delta units

### Retrieve-side adapter
Convert LoCoMo QA rows into:
- query
- reference answer
- category label
- dialogue linkage

### Evaluation adapter
Plug final answer outputs back into:
- the current judge logic
- F1 computation
- category breakdown

---

## 7. Logging and trace requirements

Runnable v0 should log enough information to debug skill behavior.

### Observe-side trace
At minimum:
- extracted candidates
- categorization outputs
- normalization outputs
- merge candidates + decision
- update candidates + decision
- score outputs
- link decisions (if enabled)
- reorganization actions/proposals (if enabled)

### Retrieve-side trace
At minimum:
- query analysis output
- retrieved answer candidates
- assembled memory context
- final answer

This is important because first runnable versions will fail in messy ways, and we need visibility.

---

## 8. v0 simplifications

To keep the first runnable version tractable, I recommend these simplifications:

### 1. Fixed answer model
Use one answer model consistently in the first runnable pass.

### 2. Fixed maintenance ordering
Do not over-complicate dynamic scheduling in the first runnable version.
Keep the base maintenance path mostly stable.

### 3. Restricted reorganization
Do not let `reorganize_memory` fire too often.
Use conservative triggers.

### 4. Keep organization-side modest
Use `link_memory` where appropriate, but do not depend on a rich graph backend yet.

### 5. Prefer explainability over optimization
The first runnable version should be easy to inspect, even if not yet cheap or fast.

---

## 9. What v0 should NOT try to do

The first LoCoMo-runnable version should not try to:
- optimize every skill prompt for token efficiency,
- solve every organization-side decision perfectly,
- support every possible retrieval backend,
- fully automate complex reorganization policy,
- immediately beat MemOS / OpenViking on quality.

Its job is to become:

> **runnable, inspectable, and fair to analyze**

---

## 10. Success criteria for runnable v0

The system can be considered runnable when it can:

1. ingest at least one LoCoMo conversation end-to-end,
2. maintain internal memory state through the conversation,
3. answer at least a subset of LoCoMo questions through the retrieve-side path,
4. produce outputs compatible with existing evaluation logic,
5. generate useful traces for inspection.

---

## 11. Recommended immediate next build steps

### Step 1
Implement a minimal runtime skeleton that can:
- process turns,
- process questions,
- route through the skill chain.

### Step 2
Implement a LoCoMo adapter for:
- turns
- QA rows

### Step 3
Start with a tiny scope:
- one conversation
- a small subset of QA
- full trace logging

### Step 4
Only after that, scale to more conversations and more QA.

---

## 12. Current working summary

Current working assumptions for LoCoMo runnable v0:
- maintenance-side skills are mature enough to form the core write path
- retrieve-side skills are now sufficient for a minimum answer loop
- organization-side skills should be included cautiously, especially `reorganize_memory`
- the main missing piece is now runtime assembly, not just more isolated skill design
