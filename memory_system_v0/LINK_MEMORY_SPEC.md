# link_memory Spec (Draft v0)

## Goal

`link_memory` is responsible for establishing an explicit relation between memory items that are meaningfully related but should remain distinct memory objects.

It should not merge them, and it should not update one into another. Instead, it should record that a meaningful connection exists.

In one sentence:

> `link_memory` connects distinct but meaningfully related memory objects without collapsing them into one.

---

## Core distinction: link vs merge vs update

### `merge_memory`
Use when two memory items describe the **same memory object** and should be fused.

### `update_memory`
Use when new memory revises, corrects, or replaces an old memory in the **same semantic slot**.

### `link_memory`
Use when two memory items are:
- meaningfully related,
- not the same memory object,
- not in a direct overwrite/replacement relation,
- still worth explicitly connecting.

### Current principle

> link when memories are meaningfully related but should remain distinct objects.

---

## Typical link cases (v0)

### 1. Event ↔ outcome/state
Example:
- “Caroline started piano lessons in June 2023.”
- “Caroline feels calmer after starting piano lessons.”

These should not merge, but they should likely be linked.

### 2. Plan ↔ prerequisite / reason
Example:
- “Jon plans to open a dance studio in the fall.”
- “Jon is saving money for the studio.”

The second memory may support or explain the first.

### 3. Relation ↔ supporting event
Example:
- “Caroline encouraged Melanie’s art practice.”
- “Melanie shared books and emotional support with Caroline.”

These may be separate relation/event memories that still belong together in retrieval and organization.

### 4. Profile ↔ plan
Example:
- “Jon runs a dance studio.”
- “Jon plans to expand the studio.”

### 5. Preference ↔ reason
Example:
- “Melanie prefers sunrise paintings.”
- “She says sunrise paintings feel more calming.”

---

## Non-link cases (v0)

### 1. Same memory object
If two memories should actually be fused, use `merge_memory` instead.

### 2. Same semantic slot with replacement
If a new memory replaces an old one, use `update_memory` instead.

### 3. Superficial co-occurrence
If two memories are merely topical neighbors but not meaningfully related, do not link them.

---

## Inputs

### Required
- `source_memory`
- `candidate_memories`

### Optional
- evidence
- entities
- time anchors
- relation hints
- existing graph / link context

### Design note
In v0, candidate memories may be provided by upstream logic.
We do not yet require a dedicated `retrieve_link_candidates` skill, though one may be added later.

---

## Output

The output should explicitly state whether a link should be created.

### Required fields
- `link_decision`
  - `link` or `no_link`
- `linked_memory_ids`
- `link_type`
- `link_reason`

### Optional
- `link_direction`
- `link_confidence`

### Example

```json
{
  "link_decision": "link",
  "linked_memory_ids": ["m_old_2"],
  "link_type": "event_outcome",
  "link_reason": "state memory is a consequence of the event memory",
  "link_direction": "source_to_candidate",
  "link_confidence": 0.88
}
```

### No-link example

```json
{
  "link_decision": "no_link",
  "linked_memory_ids": [],
  "link_type": null,
  "link_reason": "no meaningful persistent relation between the memories",
  "link_direction": null,
  "link_confidence": 0.71
}
```

---

## Link types (v0)

Suggested coarse link types:
- `event_outcome`
- `event_participant`
- `plan_prerequisite`
- `plan_reason`
- `relation_support`
- `profile_plan`
- `preference_reason`
- `general_related`

These are intentionally coarse in v0.
They are meant to preserve useful structure without over-engineering the ontology too early.

---

## Responsibilities

`link_memory` is responsible for:
1. deciding whether two distinct memories should be explicitly connected
2. assigning a useful coarse relation type
3. preserving structure without collapsing separate memories into one
4. enabling later retrieval and organization to exploit these links

---

## Non-responsibilities

`link_memory` is **not** responsible for:
1. extracting memory from dialogue
2. categorizing memory
3. normalizing memory
4. merging duplicate/complementary memories
5. updating or replacing memories in the same semantic slot
6. deciding retention or long-term archival actions
7. answering questions directly

These belong more naturally to:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`
- `score_memory`
- retrieve-side skills
- `memory policy`

---

## Relationship with future organization-side skills

`link_memory` is one of the first true organization-side skills.

Its purpose is to preserve relationships that are too meaningful to ignore, but not suitable for merge/update.

This makes it likely to support later skills such as:
- `reorganize_memory`
- graph-aware retrieval
- multi-memory context assembly

---

## Design rationale

This design helps because:

### 1. It fills the gap between merge and update
Some memories are related but should neither be fused nor replaced.

### 2. It supports better retrieval structure
Linked memories can later be jointly surfaced or traversed.

### 3. It preserves semantic richness
Important dependencies, reasons, and consequences do not need to be flattened into one item.

### 4. It stays modular
Linking remains distinct from maintenance and retrieval decisions.

---

## Open questions

### 1. Should `link_memory` later get its own candidate retrieval skill?
Current leaning:
- likely yes later
- not required in v0

### 2. Should links be directional by default?
Current leaning:
- often useful
- but v0 can keep direction simple/coarse

### 3. Should one pair of memories support multiple link types?
Current leaning:
- maybe later
- single coarse link is enough in v0

### 4. Should link confidence be mandatory?
Current leaning:
- optional but useful

### 5. Should relation types be kept coarse or expanded later?
Current leaning:
- coarse first
- expand only when retrieval/organization needs it

---

## Current working summary

Current working assumptions for `link_memory`:
- it is an organization-side skill
- it connects related but distinct memory objects
- it should be used when merge/update are both wrong
- it outputs explicit link decisions and coarse link types
- it preserves useful structure for later retrieval and reorganization
