# score_memory Spec (Draft v0)

## Goal

`score_memory` is responsible for estimating the importance, persistence value, and future utility of a memory item for downstream retention and maintenance decisions.

Its purpose is to provide a **valuation layer** between memory maintenance and higher-level policy decisions.

In one sentence:

> `score_memory` assigns interpretable value signals to a memory item without directly deciding what action should be taken on it.

---

## Role in the pipeline

Current intended position:

1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`
6. `update_memory`
7. `score_memory`
8. `memory policy` (future)

So `score_memory` comes after core maintenance decisions and before retention / promotion / archival policy.

---

## Core design principle

`score_memory` should produce **valuation**, not **action**.

That means it may estimate:
- how important a memory is,
- how stable it is,
- how useful it may be later,

but it should **not directly decide**:
- promote
- archive
- delete
- downweight
- reorganize

Those are policy-level actions.

---

## Input

### Required
- one maintained memory item
  - typically already normalized
  - may already have gone through merge/update decisions

### Optional
- local maintenance context
  - whether this memory was merged
  - whether it updated prior memory
  - mention frequency
  - repetition count
  - provenance richness
  - recency / timestamp info

### Not required in v0
- full memory store
- global policy state
- answer-time retrieval history

### Design decision
In v0, `score_memory` primarily evaluates a **single memory item**, not a cluster or whole subgraph.

---

## Core score dimensions (v0)

We currently define three core dimensions.

### 1. `salience_score`
How important, prominent, or notable the memory is.

Examples of higher salience:
- major life event
- important relationship fact
- central identity/profile fact
- major plan or plan change

### 2. `stability_score`
How likely the memory is to remain valid and stable over time.

Examples of higher stability:
- long-term profile fact
- repeatedly confirmed preference
- enduring relation

Examples of lower stability:
- transient state
- volatile plan
- short-lived emotional condition

### 3. `future_utility_score`
How likely the memory is to be useful for future retrieval, reasoning, or answering.

Examples of higher future utility:
- facts likely to be asked about later
- durable user preferences
- major plans and relationships
- profile information useful across many future contexts

---

## Overall score

### Current decision
In v0, we keep an optional:
- `overall_score`

But it should be treated as a **convenience field**, not the only important output.

The three component scores remain primary.

### Rationale
A single score is useful for:
- ranking
- quick heuristics
- downstream policy simplification

But it should not collapse all meaning into one opaque number.

---

## Output schema (v0)

### Required fields
- `salience_score`
- `stability_score`
- `future_utility_score`

### Recommended fields
- `overall_score`
- `score_reason`
- `score_signals`

### Example

```json
{
  "salience_score": 0.88,
  "stability_score": 0.73,
  "future_utility_score": 0.91,
  "overall_score": 0.84,
  "score_reason": "important future relocation plan with likely future recall value",
  "score_signals": [
    "major life plan",
    "future relevant",
    "cross-session usefulness"
  ]
}
```

---

## Responsibilities

`score_memory` is responsible for:
1. evaluating the value of a memory item along interpretable dimensions
2. exposing score signals that may support downstream policy
3. helping distinguish memories that are likely worth retaining from those that are less important
4. remaining independent from final action decisions

---

## Non-responsibilities

`score_memory` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. merging or updating memory
5. deciding retention / promotion / archival actions directly
6. rewriting memory content
7. making final orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`
- `memory policy`

---

## Example intuition

### Example 1: transient emotional state
“Caroline feels stressed today.”

Possible scores:
- salience: medium
- stability: low
- future utility: medium-low

Interpretation:
- maybe useful short-term
- not obviously a high-value long-term memory

### Example 2: stable profile fact
“Jon runs a dance studio.”

Possible scores:
- salience: high
- stability: high
- future utility: high

Interpretation:
- strong candidate for persistent memory

### Example 3: future plan
“Melanie plans to move next year.”

Possible scores:
- salience: high
- stability: medium
- future utility: high

Interpretation:
- important and likely useful, but somewhat volatile

---

## Relationship with other skills

### With `merge_memory` / `update_memory`
These skills determine what the current memory representation is.
`score_memory` evaluates the resulting memory item after those maintenance decisions.

### With future policy
`score_memory` does not itself decide:
- promote
- archive
- downweight
- reorganize

But it provides the valuation signals that policy may use to make such decisions.

### With future `reorganize_memory`
Score may later influence:
- which memories are worth compressing or clustering
- which memories deserve better structure
- which memories should remain prominent

---

## Design rationale

This design helps because:

### 1. It separates valuation from action
A memory may be scored highly without policy immediately promoting it.

### 2. It keeps scoring interpretable
The split into salience / stability / future utility reduces black-box behavior.

### 3. It supports fair accounting
Scoring cost can be measured separately from extraction, merge/update, and policy.

### 4. It provides a clean bridge to policy
Policy can stay global and strategic, while score remains local and interpretable.

---

## Open questions

### 1. How should `overall_score` be derived?
Current leaning:
- optional weighted combination
- but exact weighting should remain open for now

### 2. Should scores be calibrated globally or only locally?
Current leaning:
- local first in v0
- global calibration may come later

### 3. Should repetition / multiple confirmations directly raise stability or salience?
Current leaning:
- probably yes
- but exact rules remain open

### 4. Should different memory types use different scoring priors?
Current leaning:
- likely yes in future
- but v0 can stay simpler

### 5. Should score be attached directly onto `MemoryItem` or returned as a separate result?
Current leaning:
- attach score fields to the memory item is acceptable in v0
- richer score reports may later become separate result objects

---

## Current working summary

Current working assumptions for `score_memory`:
- it is a valuation skill, not an action skill
- it operates on a single maintained memory item in v0
- it produces three core scores:
  - `salience_score`
  - `stability_score`
  - `future_utility_score`
- it may optionally produce `overall_score`
- it should remain interpretable and support later policy decisions without replacing them
