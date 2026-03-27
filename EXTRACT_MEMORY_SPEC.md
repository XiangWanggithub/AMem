# extract_memory Spec (Draft v0)

## Goal

`extract_memory` is responsible for extracting **candidate memory items** from the **conversation delta since the last extraction**.

Its role is **not** to generate final stored memories directly, but to produce clean, semantically self-contained candidates that can later be processed by downstream modules such as:
- `categorize_memory`
- `normalize_memory`
- `merge_memory`
- `update_memory`

In one sentence:

> `extract_memory` turns newly arrived context into memory-worthy candidate units that are stable enough for later processing.

---

## Inputs

### Required
- **conversation delta**
  - all new turns since the last extraction

### Optional
- **session metadata**
  - session id
  - dialogue id
  - time range
  - speaker metadata
  - channel / source metadata

### Not required in v0
- full memory store
- full dialogue history
- retrieval results

### Design decision
In v0, `extract_memory` mainly reads **new context only**, instead of directly reasoning over the entire memory base.
This keeps its boundary clean and avoids overlap with `merge_memory` and `update_memory`.

---

## Output

The output is a **list of candidate memory items**.

Each candidate should be:
- memory-worthy
- semantically self-contained
- understandable without re-reading the entire raw dialogue
- traceable back to source evidence

---

## Candidate granularity

### Principle
A candidate should be a:

> **semantically self-contained minimal unit**

That means:
- not too fragmented
- not too overloaded
- small enough to represent one coherent memory point
- complete enough to stand on its own later

### Good examples
- “Caroline started piano lessons in June 2023.”
- “Melanie prefers sunrise paintings to abstract art.”
- “Jon plans to open his dance studio in the fall.”

### Bad examples
- “started piano lessons”
- “in June 2023”
- one long sentence bundling several unrelated facts into one candidate

### Current decision
We do **not** impose a hard upper bound on the number of candidates produced from a long sentence.
If one sentence contains multiple memory-worthy facts, it may legitimately produce multiple candidates.

---

## Memory-worthy criteria

`extract_memory` should only extract content that is worth remembering.

### Candidate types that are generally memory-worthy
1. **important event**
   - a meaningful event that may matter later

2. **stable preference**
   - likes, dislikes, habits, tastes, tendencies

3. **profile / identity fact**
   - long-term identity, background, role, bio-like fact

4. **relationship fact**
   - meaningful relation between people / organizations / places

5. **future plan / intention**
   - explicit plans, goals, commitments, intentions

6. **recurring habit / routine**
   - repeated or stable behavior pattern

7. **meaningful state change**
   - a notable update in status, preference, relationship, belief, or plan

### Generally not memory-worthy by default
- greetings / small talk
- filler content
- isolated fragments without semantic closure
- purely local utterances with very low future recall value
- weak emotional wording unless it reflects a durable state or important change

---

## Candidate schema (v0)

Each candidate memory item should minimally support downstream processing.

### Required fields
- `content`
  - natural-language statement of the candidate memory
- `evidence`
  - source grounding from the original dialogue
- `confidence`
  - extraction confidence

### Recommended fields
- `entities`
  - main entities involved
- `time_anchor`
  - normalized time anchor when available
- `suggested_type`
  - weak type hint, not final type
- `speaker_attribution`
  - who stated or owns the information

### Evidence design decision
`evidence` should preferably include **turn ID** rather than raw text span only.

Reason:
- easier traceability
- easier debugging
- easier alignment with evaluation logs and dialogue structure
- more robust than raw quote fragments alone

A practical format could be:

```json
{
  "turn_id": "t_17",
  "text_span": "Caroline started piano lessons in June 2023"
}
```

---

## Suggested type policy

`extract_memory` may provide **weak type hints**, but should not finalize memory types.

### Principle
- `extract_memory` can output `suggested_type`
- `categorize_memory` is responsible for final type assignment

### Suggested type candidates in v0
- `event`
- `preference`
- `profile`
- `relation`
- `plan`
- `habit`
- `state`
- `unknown`

This keeps extraction lightweight while preserving useful hints for later routing.

---

## Responsibilities

`extract_memory` is responsible for:
1. identifying memory-worthy content in new context
2. turning that content into candidate memory items
3. keeping each candidate semantically self-contained
4. attaching basic evidence / entities / time anchors / weak type hints

---

## Non-responsibilities

`extract_memory` is **not** responsible for:
1. final memory type assignment
2. merge decisions against existing memory store
3. update decisions against existing memory store
4. long-term retention decisions
5. final storage schema or storage location

These belong more naturally to:
- `categorize_memory`
- `merge_memory`
- `update_memory`
- `score_memory`
- higher-level policy

---

## Design rationale

This separation helps because:

### 1. Cleaner boundaries
- `extract_memory` finds candidate memory
- `categorize_memory` assigns final type
- `merge_memory` / `update_memory` handle interaction with old memory

### 2. Better modularity
Future changes in taxonomy do not require fully redesigning extraction.

### 3. Better accounting
We can separately measure:
- extract cost
- categorize cost
- merge/update cost
instead of hiding them inside one black-box memory step.

---

## Open questions

### 1. Should time anchors be standardized during extraction?
**Current decision:** yes, when possible.

Rationale:
- extraction should already try to output normalized time anchors
- `normalize_memory` can later provide an additional guarantee / repair step

So the current view is:
- extraction does first-pass normalization
- normalize does second-pass enforcement / correction

### 2. Should evidence include turn ID?
**Current decision:** yes, preferably.

We currently prefer:
- turn id + supporting text span
rather than raw text only.

### 3. Should candidates carry speaker attribution?
This is still worth discussion.

#### Potential benefits
- distinguish **who said** something
- distinguish **who the memory is about** vs **who stated it**
- useful when speakers mention each other
- useful for attribution-sensitive memories such as:
  - preferences
  - beliefs
  - plans
  - commitments

Example:
- “Caroline said Melanie wants to move next year.”

Here we may want to distinguish:
- speaker: Caroline
- memory subject: Melanie

Without attribution fields, later processing may confuse the owner of the memory.

So I currently lean toward **including speaker attribution** in v0, at least optionally.

### 4. Are composite candidates allowed?
Still open, but probably only in limited cases.

#### Possible example of a composite candidate
- “Caroline started piano lessons in June 2023 and feels calmer because of them.”

This may be represented either as:

**Option A: split into two candidates**
1. Caroline started piano lessons in June 2023.
2. Caroline feels calmer after starting piano lessons.

**Option B: one composite candidate**
- Caroline started piano lessons in June 2023, which made her feel calmer.

My current view:
- default preference should be **split into simpler candidates**
- composite candidates should only be allowed when the relation itself is memory-worthy and splitting would lose important meaning

So v0 should probably prefer:
- simple candidates first
- composite candidates only as an exception

---

## Current working summary

Current working assumptions for `extract_memory`:
- input = conversation delta since last extract
- output = candidate memory items
- candidate granularity = semantically self-contained minimal unit
- no hard cap on candidates from a long sentence
- type distinction = weak hint only, not final categorization
- time anchors should already be normalized when possible
- evidence should preferably include turn IDs
- speaker attribution is likely useful, especially for attribution-sensitive facts
- composite candidates should be exceptions, not the default
