# retrieve_update_candidates Spec (Draft v0)

## Goal

`retrieve_update_candidates` is responsible for retrieving a **high-recall shortlist of existing memory items** that may occupy the **same semantic slot** as a new normalized memory item, and therefore may need revision, replacement, or correction.

Its purpose is to support `update_memory` by narrowing the search space from the full memory store to a manageable set of plausible update targets.

In one sentence:

> `retrieve_update_candidates` finds old memories that may be revised or replaced by a new memory item.

---

## Position in the pipeline

Current expected role:

1. `extract_memory`
2. `categorize_memory`
3. `normalize_memory`
4. `retrieve_merge_candidates`
5. `merge_memory`
6. `retrieve_update_candidates`
7. `update_memory`

This skill provides the upstream candidate set for update decisions.

---

## Key design principle

`retrieve_update_candidates` is a:

> **storage-agnostic, backend-adaptive skill**

Like `retrieve_merge_candidates`, the interface should remain stable while backend implementations may vary depending on the underlying memory architecture.

Examples of possible backends:
- vector-based retriever
- graph-based retriever
- hierarchical retriever
- symbolic / slot-based retriever
- hybrid retriever

---

## Difference from related retrieval skills

### vs answer-time retrieval
Answer-time retrieval looks for memory useful for answering a question.

`retrieve_update_candidates` instead looks for memory that may be **revised or replaced** by the new item.

### vs `retrieve_merge_candidates`
- `retrieve_merge_candidates` optimizes for **same memory object**
- `retrieve_update_candidates` optimizes for **same semantic slot / replaceable target**

This is the most important distinction.

---

## Inputs

### Required
- `source_memory`
  - the new normalized memory item currently under maintenance

### Optional
- `max_candidates`
- `retrieval_budget`
- `allowed_signals`
- `storage_adapter_hint`

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

The output is a ranked list of **candidate memory items** that may be potential update targets.

### Required fields per candidate
- `memory_id`
- `candidate_score`
- `candidate_memory`

### Recommended fields per candidate
- `retrieval_signals`
- `retrieval_reason`

### Example

```json
{
  "memory_id": "m_18",
  "candidate_score": 0.86,
  "candidate_memory": {
    "normalized_content": "Jon plans to move to Boston.",
    "final_type": "plan"
  },
  "retrieval_signals": ["same_subject", "same_type", "same_semantic_slot"],
  "retrieval_reason": "same person and same relocation-plan slot"
}
```

---

## Retrieval target

The skill should prioritize candidates that are likely to:
- represent an earlier value in the same semantic slot
- be corrected by the new item
- be replaced by the new item
- reflect a prior state, plan, profile, relation, or preference that may have changed

### Current principle
In v0, this skill should prioritize:

> **high recall over high precision**

Reason:
- false positives can be filtered by `update_memory`
- false negatives may prevent important change tracking

---

## Candidate retrieval signals

The following signals are plausible in v0.
Different backends may implement different subsets of them.

### 1. Same subject / owner
Example:
- both memories are about Jon
- both memories are about Melanie

### 2. Same final type
Especially useful for:
- `state`
- `plan`
- `profile`
- `relation`
- `preference`

### 3. Same semantic slot
Examples:
- current emotional state
- future relocation plan
- job affiliation
- living place
- relationship status
- art preference

### 4. Temporal succession possibility
Example:
- the new item appears later and may supersede the old one
- the new item has a more recent time anchor or stronger currentness signal

### 5. Shared target / object
Examples:
- both about moving cities
- both about working for an employer
- both about a specific preference domain

### 6. Shared entity-role structure
Examples:
- same person + same relation counterpart
- same person + same plan target

### 7. Namespace / partition proximity
Examples:
- same type bucket
- same structured slot namespace

---

## Responsibilities

`retrieve_update_candidates` is responsible for:
1. finding plausible old memories that may be revised or replaced by `source_memory`
2. producing a bounded shortlist rather than exposing the whole memory store
3. supporting downstream `update_memory` with a recall-oriented candidate set
4. optionally exposing retrieval signals and reasons for auditability

---

## Non-responsibilities

`retrieve_update_candidates` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. deciding whether an update should actually happen
5. deciding whether the case is really merge instead of update
6. making final orchestration decisions

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`
- `memory policy`

---

## Relationship with storage architecture

This skill is defined at the **interface level**, not at the backend-specific implementation level.

### Stable contract
The contract stays the same:
- input: one source memory item
- output: candidate memories that may be update targets

### Variable implementation
The backend may differ depending on memory architecture.

#### Vector-based architecture
Possible strategy:
- nearest neighbors
- filtered by subject / type / slot cues

#### Graph-based architecture
Possible strategy:
- traverse subject-centered local neighborhood
- focus on slot-relevant relation edges

#### Hierarchical architecture
Possible strategy:
- search within same type bucket or slot-oriented namespace
- then narrow to likely predecessors

#### Symbolic / slot-based architecture
Possible strategy:
- direct lookup by subject + slot key

#### Hybrid architecture
Possible strategy:
- combine semantic similarity, entity filters, time signals, and slot structure

### Current design decision
We treat `retrieve_update_candidates` as a **single skill abstraction with backend-adaptive implementations**.

---

## Role of memory policy

Higher-level `memory policy` may decide:
- whether update-candidate retrieval is needed
- what budget to allocate
- which retrieval backend or signal set to use
- how many candidates to request

But `memory policy` should not necessarily perform retrieval itself.

So the division is:
- `memory policy` decides **whether / how** update-candidate retrieval is invoked
- `retrieve_update_candidates` performs the retrieval
- `update_memory` makes the final update decision

---

## Design rationale

This design helps because:

### 1. It separates candidate generation from update judgment
Retrieval and update decision are different operations.

### 2. It supports multiple storage backends
The same skill can adapt to flat, structured, graph, or hybrid memory systems.

### 3. It preserves explainability
Signals and retrieval reasons can be logged and inspected.

### 4. It supports fair accounting
Update-candidate retrieval cost can be measured separately from update decision cost.

---

## Open questions

### 1. Should update retrieval be more type-constrained than merge retrieval?
Current leaning:
- often yes
- because slot alignment matters more than broad similarity

### 2. Should conflicting old memories always be surfaced if they share the same slot?
Current leaning:
- usually yes
- especially when they are plausible replacement targets

### 3. Should `retrieve_update_candidates` ever return memories with different `final_type`?
Current leaning:
- mostly avoid in v0
- but may allow exceptions when slot overlap is strong

### 4. Should candidate ranking prefer recency?
Current leaning:
- probably yes for many update cases
- but not blindly, since older canonical memory may still be the one being revised

### 5. Should this skill later be unified with `retrieve_merge_candidates` under a more general maintenance retrieval layer?
Current leaning:
- possible later
- but separate skills are clearer in v0

---

## Current working summary

Current working assumptions for `retrieve_update_candidates`:
- it is an explicit skill in v0
- it retrieves old memories that may be revised or replaced by a new normalized memory
- it is storage-agnostic at the interface level
- it is backend-adaptive at the implementation level
- it aims for high recall, not final precision
- it optimizes for same semantic slot, not same memory object
- it does not decide update; that is the responsibility of `update_memory`
- policy may control whether and how it is invoked, but does not have to perform retrieval itself
