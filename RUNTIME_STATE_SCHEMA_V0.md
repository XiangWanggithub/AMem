# Runtime State Schema v0

## Goal

Define the minimum persistent state structure for the first runnable version of the memory-skill system.

This schema is designed for:
- simplicity,
- inspectability,
- easy debugging,
- compatibility with LoCoMo-style evaluation.

The v0 design favors **JSON / JSONL storage** rather than a database.

---

## Design principle

v0 runtime state should be:
- easy to read by humans,
- easy to append to,
- easy to replay,
- easy to analyze after a run.

So we use:
- `jsonl` for growing collections / logs
- `json` for compact summary state

---

## Proposed directory structure

```text
runtime_state/
├── memory_items.jsonl
├── memory_links.jsonl
├── memory_events.jsonl
├── answers.jsonl
└── runtime_state.json
```

---

## 1. `memory_items.jsonl`

Stores the current memory objects.
One line = one `MemoryItem`.

### Typical fields
- `memory_id`
- `content`
- `normalized_content`
- `final_type`
- `entities`
- `normalized_entities`
- `time_anchor`
- `normalized_time_anchor`
- `speaker_attribution`
- `evidence`
- `score` (optional grouped field)
- provenance fields

### Example

```json
{
  "memory_id": "m_001",
  "content": "Caroline started piano lessons last June.",
  "normalized_content": "Caroline started piano lessons in June 2023.",
  "final_type": "event",
  "entities": ["Caroline", "piano lessons"],
  "normalized_entities": ["Caroline", "piano lessons"],
  "time_anchor": "2023-06",
  "evidence": [
    {
      "turn_id": "t_17",
      "text_span": "started piano lessons last June"
    }
  ]
}
```

---

## 2. `memory_links.jsonl`

Stores explicit links between memory objects.
One line = one link.

### Typical fields
- `link_id`
- `source_memory_id`
- `target_memory_id`
- `link_type`
- `link_confidence`
- `link_direction`

### Example

```json
{
  "link_id": "l_001",
  "source_memory_id": "m_001",
  "target_memory_id": "m_002",
  "link_type": "event_outcome",
  "link_confidence": 0.88,
  "link_direction": "source_to_candidate"
}
```

---

## 3. `memory_events.jsonl`

Stores maintenance-side actions and notable state transitions.
One line = one runtime event.

### Possible event kinds
- `extract`
- `categorize`
- `normalize`
- `merge`
- `update`
- `score`
- `link`
- `reorganize`

### Typical fields
- `event_id`
- `kind`
- `source_memory_id`
- `affected_memory_ids`
- `result_memory_id`
- `reason`
- `timestamp`

### Example

```json
{
  "event_id": "e_001",
  "kind": "merge",
  "source_memory_id": "m_new_1",
  "affected_memory_ids": ["m_old_4"],
  "result_memory_id": "m_009",
  "reason": "same plan with complementary temporal detail",
  "timestamp": "2026-03-30T17:00:00+08:00"
}
```

---

## 4. `answers.jsonl`

Stores answer-time outputs and traces.
One line = one answered QA.

### Typical fields
- `question_id`
- `query`
- `retrieval_intent`
- `retrieved_memory_ids`
- `assembled_context`
- `answer`
- `reference_answer` (optional if available)
- `timestamp`

---

## 5. `runtime_state.json`

Stores compact summary state for the current run.

### Typical fields
- `run_id`
- `dialogue_id`
- `last_processed_turn_id`
- `memory_count`
- `link_count`
- `event_count`
- `answer_count`
- `policy_mode`
- `created_at`
- `updated_at`

### Example

```json
{
  "run_id": "run_001",
  "dialogue_id": "conv-26",
  "last_processed_turn_id": "t_54",
  "memory_count": 27,
  "link_count": 8,
  "event_count": 63,
  "answer_count": 0,
  "policy_mode": "standard",
  "created_at": "2026-03-30T16:00:00+08:00",
  "updated_at": "2026-03-30T16:12:00+08:00"
}
```

---

## Initialization

At the beginning of a run:
- `memory_items` = empty
- `memory_links` = empty
- `memory_events` = empty
- `answers` = empty
- `runtime_state.json` created with zero counts

This matches the LoCoMo setting where memory is built progressively from conversation history.

---

## Current working summary

Current working assumptions for runtime state v0:
- runtime state should be file-based and human-readable
- JSONL is preferred for append-only collections and trace logs
- JSON is preferred for compact summary state
- memory objects, links, maintenance events, and answer traces should all be stored explicitly
- v0 favors inspectability over backend sophistication
