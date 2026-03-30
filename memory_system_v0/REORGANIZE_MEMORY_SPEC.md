# reorganize_memory Spec (Draft v0)

## Goal

`reorganize_memory` is responsible for detecting and proposing structural reorganization actions over an existing set of memory items, links, and local structure so that the memory system becomes easier to maintain and easier to retrieve from later.

It is not a default per-memory step. Instead, it is a **policy-triggered organization-side maintenance skill**.

In one sentence:

> `reorganize_memory` proposes higher-level structural cleanup and restructuring when a memory region has become large, fragmented, or retrieval-unfriendly.

---

## Core role

`reorganize_memory` operates at a higher structural level than:
- `merge_memory`
- `update_memory`
- `link_memory`

Those skills act on individual items or small local relations.

`reorganize_memory` acts on:
- memory sets
- local clusters
- linked subgraphs
- topic or entity-centered memory regions

Its job is to improve **structure**, not just local correctness.

---

## When it should run

### Current design decision
`reorganize_memory` should be treated as:
- **policy-triggered**
- **conditional**
- **periodic or event-driven**

It should **not** be the default action taken every time a new memory arrives.

---

## Typical trigger conditions

### 1. Accumulation trigger
Run when a memory region has become crowded or fragmented.

Examples:
- too many related memory items about the same person/project/topic
- many small linked fragments forming a coherent cluster
- repeated accumulation of similar project-related or relation-related memories

### 2. Retrieval-quality trigger
Run when retrieval appears noisy, fragmented, or inefficient.

Examples:
- too many small memory pieces are being retrieved together
- answer-time context repeatedly needs many redundant candidates
- existing organization is not helping retrieval enough

### 3. Periodic trigger
Run at periodic maintenance checkpoints.

Examples:
- end of session
- every N new memories
- background daily or weekly maintenance

---

## Inputs

### Required
- `memory_items`

### Optional
- `memory_links`
- `memory_scores`
- cluster metadata
- entity/topic scope
- budget profile
- trigger reason

### Design note
In v0, the input may be a **local memory region** rather than the whole memory store.
This keeps the skill tractable and more interpretable.

---

## Output

The output should be a structured **reorganization proposal**, not a silent black-box mutation.

### Required fields
- `reorganization_decision`
  - `reorganize` or `no_reorganize`
- `reorganization_actions`
- `affected_memory_ids`
- `reorganization_reason`

### Optional fields
- `suggested_clusters`
- `suggested_summary_nodes`
- `reorganization_confidence`

### Example

```json
{
  "reorganization_decision": "reorganize",
  "reorganization_actions": [
    "cluster_memories",
    "suggest_summary_node"
  ],
  "affected_memory_ids": ["m1", "m2", "m3", "m4"],
  "reorganization_reason": "memories form a coherent long-term project cluster",
  "suggested_clusters": [
    {
      "cluster_name": "studio_project",
      "memory_ids": ["m1", "m2", "m3", "m4"]
    }
  ]
}
```

---

## Typical reorganization actions (v0)

### 1. `cluster_memories`
Group related memory items into a more explicit local structure.

### 2. `suggest_summary_node`
Propose creating a summary/overview node for a cluster that has become too large or repetitive.

### 3. `promote_core_memories`
Mark certain items as structurally central within the local region.
This is not the same as final retention policy, but it may influence later retrieval and organization.

### 4. `demote_fragmented_memories`
Mark low-value peripheral fragments as less central in the local structure.
Again, this is structural, not final archival policy.

### 5. `restructure_links`
Suggest better grouping or relation layout among linked memory objects.

---

## Non-responsibilities

`reorganize_memory` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. merging duplicate memory items directly
5. updating replaced memory directly
6. deleting or archiving memory as a final action
7. answering user questions directly

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`
- `score_memory`
- `memory policy`
- retrieve-side skills

---

## Relationship with other organization-side skills

### With `link_memory`
`link_memory` creates explicit local relations between distinct memory objects.
`reorganize_memory` may later use those links to detect larger clusters or more useful structure.

### With `score_memory`
Scores may help determine which memories are central, stable, or worth elevating in the structure.

### With `memory policy`
Policy decides whether reorganization should happen at all, and on what scope.
`reorganize_memory` then proposes how that scope should be reorganized.

---

## Example intuition

Suppose the system has accumulated these memories:
- Jon runs a dance studio.
- Jon plans to expand the studio.
- Jon is saving money for the studio.
- Jon has been rehearsing more often for the studio opening.

These do not necessarily all merge into one item.
But they may clearly form a **studio project cluster**.

In this case, `reorganize_memory` may recommend:
- cluster these memories together
- create a summary node or overview
- mark the project cluster as structurally important

---

## Design rationale

This design helps because:

### 1. It separates local maintenance from higher-level structure optimization
Merge/update/link handle local correctness and relation.
Reorganization handles higher-level structure.

### 2. It supports better long-term retrieval
A more organized memory space should eventually improve downstream retrieval quality.

### 3. It keeps reorganization interpretable
By returning explicit proposals instead of silently mutating everything, the skill stays auditable.

### 4. It matches real memory-system growth patterns
As memory accumulates, the problem shifts from storing one more item to managing a whole region of memory well.

---

## Open questions

### 1. Should `reorganize_memory` directly create summary nodes, or only propose them?
Current leaning:
- propose in v0
- direct execution may come later

### 2. Should reorganization be local-only in v0?
Current leaning:
- yes
- local subgraph / cluster / topic scope is safer than global whole-store reorganization

### 3. Should `reorganize_memory` depend heavily on `score_memory`?
Current leaning:
- score should help, but not dominate entirely

### 4. Should reorganization actions be reversible / logged?
Current leaning:
- yes, as much as possible

### 5. Should reorganization be tested before retrieve-side is fully mature?
Current leaning:
- yes at the structure level
- but retrieval benefits may only be visible later

---

## Current working summary

Current working assumptions for `reorganize_memory`:
- it is an organization-side, policy-triggered maintenance skill
- it is not a default always-on per-memory step
- it works on local memory regions, not necessarily the whole store
- it proposes structural cleanup and clustering actions
- it complements merge/update/link rather than replacing them
