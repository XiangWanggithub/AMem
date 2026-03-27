# retrieve_merge_candidates Spec (Draft v0)

## Goal

`retrieve_merge_candidates` is responsible for retrieving a **high-recall shortlist of existing memory items** that may describe the **same memory object** as a new normalized memory item.

Its purpose is to support memory maintenance, especially `merge_memory`, by narrowing the search space from the whole memory store to a manageable candidate set.

In one sentence:

> `retrieve_merge_candidates` finds plausible old memories that are worth checking for merge with a new memory item.

---

## Position in the pipeline

Current expected position:

1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`

This skill sits between normalization and merge decision.

---

## Key design principle

`retrieve_merge_candidates` is a:

> **storage-agnostic, backend-adaptive skill**

That means:
- the skill contract should stay stable
- the backend retrieval implementation may vary depending on the memory architecture

Examples of possible backends:
- vector-based retriever
- graph-based retriever
- hierarchical / directory-based retriever
- hybrid retriever
- symbolic / key-based retriever

So the skill defines **what** should be retrieved, while the backend determines **how** retrieval happens.

---

## Difference from answer-time retrieval

This skill should not be confused with retrieval used to answer user questions.

### Answer-time retrieval
Goal:
- retrieve memory relevant to answering the current query

### Merge-candidate retrieval
Goal:
- retrieve memory likely to overlap with, complement, or duplicate the new memory item

So its optimization target is different.
It is primarily for **memory maintenance**, not question answering.

---

## Inputs

### Required
- `source_memory`
  - the new normalized memory item currently under maintenance

### Optional
- `max_candidates`
  - upper bound on returned candidate count
- `allowed_signals`
  - which retrieval signals may be used
- `retrieval_budget`
  - budget hint from higher-level policy
- `storage_adapter_hint`
  - hint about which backend or store partition to use

### Typical source_memory fields
The source item may include:
- `normalized_content`
- `final_type`
- `normalized_entities`
- `normalized_time_anchor`
- `recommended_route`
- provenance metadata

---

## Output

The output is a ranked list of **candidate memory items** that may be mergeable with `source_memory`.

### Required fields per candidate
- `memory_id`
- `candidate_score`
- `candidate_memory`

### Recommended fields per candidate
- `retrieval_signals`
  - which signals caused this item to be retrieved
- `retrieval_reason`
  - short textual explanation

### Example

```json
{
  "memory_id": "m_42",
  "candidate_score": 0.83,
  "candidate_memory": {
    "normalized_content": "Jon plans to open a dance studio in the fall.",
    "final_type": "plan"
  },
  "retrieval_signals": ["same_type", "shared_entity", "semantic_similarity"],
  "retrieval_reason": "same subject and overlapping plan description"
}
```

---

## Retrieval target

The skill should prefer candidates that are likely to be:
- near-duplicates
- complementary descriptions of the same memory object
- repeated confirmations of the same memory

It should not aim for perfect precision.
Its role is to provide a **high-recall shortlist** for later evaluation by `merge_memory`.

### Current principle
In v0, this skill should prioritize:

> **high recall over high precision**

Reason:
- false positives can be filtered by `merge_memory`
- false negatives may permanently prevent useful consolidation

---

## Candidate retrieval signals

The following signals are plausible in v0.
Different backends may implement different subsets of them.

### 1. Same final type
Example:
- `plan` should first search among other plan-like memories

### 2. Shared entities
Example:
- same person, object, place, organization

### 3. Time alignment or temporal proximity
Example:
- same normalized month/year
- same future plan period

### 4. Semantic similarity
Example:
- similar normalized meaning despite wording differences

### 5. Same subject / owner
Example:
- both memories are about Melanie

### 6. Shared target / object
Example:
- both refer to opening a dance studio
- both refer to liking sunrise paintings

### 7. Relation overlap
Example:
- same relation pair or relation tuple

### 8. Namespace / partition proximity
Example:
- same type bucket
- same directory / same storage shard

---

## Responsibilities

`retrieve_merge_candidates` is responsible for:
1. finding plausible old memories that may be mergeable with `source_memory`
2. producing a bounded shortlist instead of exposing the whole memory store
3. supporting downstream `merge_memory` with a recall-oriented candidate set
4. optionally exposing signals and reasoning for auditability

---

## Non-responsibilities

`retrieve_merge_candidates` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. deciding whether a candidate should actually be merged
5. resolving contradictions or state changes
6. making final global orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`
- `memory policy`

---

## Relationship with storage architecture

This skill is intentionally defined at the **interface level**, not at the backend-specific implementation level.

### Stable contract
The contract stays the same:
- input: one source memory item
- output: candidate memories for merge checking

### Variable implementation
The backend may differ depending on memory architecture:

#### Vector-based architecture
Possible strategy:
- semantic nearest neighbors
- filtered by type / entity / time

#### Graph-based architecture
Possible strategy:
- neighborhood traversal
- relation-aware candidate retrieval

#### Hierarchical architecture
Possible strategy:
- type bucket → directory / namespace → local candidate search

#### Hybrid architecture
Possible strategy:
- combine semantic similarity, symbolic filters, and structural locality

### Current design decision
We treat `retrieve_merge_candidates` as a **single skill abstraction with backend-adaptive implementations**, rather than defining separate top-level skills for each storage architecture.

---

## Role of memory policy

Higher-level `memory policy` may decide:
- whether merge-candidate retrieval is needed for this memory item
- what budget to allocate
- which retrieval backend or signal set to use
- how many candidates to request

But `memory policy` should not necessarily perform the retrieval itself.

So the division is:
- `memory policy` decides **whether / how** candidate retrieval is invoked
- `retrieve_merge_candidates` performs the retrieval
- `merge_memory` makes the final merge decision

---

## Design rationale

This design helps because:

### 1. It separates retrieval from merge decision
Candidate generation and merge judgment are different operations.

### 2. It supports multiple storage backends
The same skill contract can adapt to vector, graph, hierarchy, or hybrid stores.

### 3. It preserves explainability
Signals and retrieval reasons can be logged and inspected.

### 4. It supports fair accounting
Candidate retrieval cost can be measured separately from merge decision cost.

---

## Open questions

### 1. How many candidates should be returned in v0?
Current leaning:
- small bounded shortlist (e.g. top-k)
- actual k may be policy-controlled

### 2. Should retrieval be type-constrained by default?
Current leaning:
- usually yes
- but some cases may benefit from cross-type retrieval

### 3. Should candidate retrieval ever surface conflicting memories, or only merge-like memories?
Current leaning:
- primarily merge-like candidates
- conflict-focused retrieval may belong to `update_memory` or a separate retrieval mode

### 4. Should retrieval signals be exposed in user-facing memory objects?
Current leaning:
- no
- they are mainly for system-side auditing and debugging

### 5. Should backends be explicitly named in output?
Current leaning:
- optional
- useful for analysis, but not required in the core schema

---

## Current working summary

Current working assumptions for `retrieve_merge_candidates`:
- it is an explicit skill in v0
- it retrieves old memories that may be mergeable with a new normalized memory
- it is storage-agnostic at the interface level
- it is backend-adaptive at the implementation level
- it aims for high recall, not final precision
- it does not decide merge; that is the responsibility of `merge_memory`
- policy may control whether and how it is invoked, but does not have to perform retrieval itself
