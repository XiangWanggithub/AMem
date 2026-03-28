# Synthetic Maintenance Testset v0

## Goal

This document defines a small, structured synthetic testset framework for validating the current memory-maintenance pipeline.

It is designed to test:
- skill boundaries,
- maintenance correctness,
- schema/transition compatibility,
- edge cases that are hard to isolate in full dialogue benchmarks.

The testset is intentionally **small and controlled**, rather than large and benchmark-like.

---

## 1. Current validation target

The current testset is designed primarily for the following skills:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`
- `score_memory`

It is **not yet** designed as a full answer-time benchmark.

---

## 2. Test case philosophy

Each case should be:
- small
- controlled
- interpretable
- diagnostic

The goal is not to test broad performance, but to expose:
- wrong boundaries
- wrong decisions
- hidden ambiguity
- schema mismatches
- over-aggressive merge/update behavior

---

## 3. Test case families

### A. Extract cases
Focus:
- memory-worthiness
- candidate granularity
- multi-candidate extraction
- attribution-sensitive extraction

### B. Categorize cases
Focus:
- final type assignment
- ambiguity resolution
- pragmatic type choice

### C. Normalize cases
Focus:
- time normalization
- coreference resolution
- entity normalization
- statement stabilization
- noise reduction

### D. Merge cases
Focus:
- duplicate merge
- complementary merge
- repeated-confirmation merge
- non-merge despite relatedness

### E. Update cases
Focus:
- state change
- plan revision
- fact correction
- preference/profile/relation change
- non-update despite relatedness

### F. Score cases
Focus:
- salience
- stability
- future utility
- relative ranking sanity

---

## 4. Recommended test case schema

A test case can use the following structure.

```json
{
  "case_id": "merge_001",
  "family": "merge",
  "description": "Complementary plan details should merge",
  "inputs": {
    "dialogue_delta": [],
    "source_memory": {},
    "candidate_memories": []
  },
  "expected": {
    "expected_extract": null,
    "expected_final_type": null,
    "expected_normalized_content": null,
    "expected_merge_decision": "merge",
    "expected_update_decision": null,
    "expected_score_pattern": null
  },
  "notes": "Second memory adds time detail to the same plan."
}
```

Not every field must be used in every case.
Different families will use different subsets.

---

## 5. Common fields

### Metadata fields
- `case_id`
- `family`
- `description`
- `notes`

### Input fields
- `dialogue_delta`
- `source_memory`
- `candidate_memories`
- `optional_context`

### Expected fields
- `expected_extract`
- `expected_final_type`
- `expected_recommended_route`
- `expected_normalized_content`
- `expected_merge_decision`
- `expected_update_decision`
- `expected_update_type`
- `expected_score_pattern`

---

## 6. Family-specific templates

## A. Extract case template

Use when testing:
- whether a memory should be extracted
- how many candidates should be produced
- whether candidate boundaries are correct

```json
{
  "case_id": "extract_001",
  "family": "extract",
  "description": "One sentence contains two memory-worthy facts",
  "inputs": {
    "dialogue_delta": [
      {
        "turn_id": "t1",
        "speaker": "user",
        "text": "Caroline started piano lessons last June and now feels much calmer."
      }
    ]
  },
  "expected": {
    "expected_extract": [
      "Caroline started piano lessons in June 2023.",
      "Caroline feels calmer now."
    ]
  }
}
```

---

## B. Categorize case template

Use when testing final type assignment.

```json
{
  "case_id": "categorize_001",
  "family": "categorize",
  "description": "Future intent should be categorized as plan",
  "inputs": {
    "source_memory": {
      "content": "Melanie plans to move next year.",
      "suggested_type": "event"
    }
  },
  "expected": {
    "expected_final_type": "plan",
    "expected_recommended_route": "plan_memory"
  }
}
```

---

## C. Normalize case template

Use when testing canonicalization.

```json
{
  "case_id": "normalize_001",
  "family": "normalize",
  "description": "Relative time should be normalized",
  "inputs": {
    "source_memory": {
      "content": "Caroline started piano lessons last June.",
      "final_type": "event",
      "evidence": [
        {
          "turn_id": "t1",
          "text_span": "started piano lessons last June"
        }
      ]
    },
    "optional_context": {
      "dialogue_timestamp": "2024-03-15"
    }
  },
  "expected": {
    "expected_normalized_content": "Caroline started piano lessons in June 2023."
  }
}
```

---

## D. Merge case template

Use when testing merge vs no-merge.

```json
{
  "case_id": "merge_001",
  "family": "merge",
  "description": "Complementary plan memories should merge",
  "inputs": {
    "source_memory": {
      "normalized_content": "Jon plans to open a dance studio.",
      "final_type": "plan"
    },
    "candidate_memories": [
      {
        "memory_id": "m_old_1",
        "normalized_content": "Jon plans to open a dance studio in the fall.",
        "final_type": "plan"
      }
    ]
  },
  "expected": {
    "expected_merge_decision": "merge"
  }
}
```

### Example no-merge case

```json
{
  "case_id": "merge_002",
  "family": "merge",
  "description": "Related but different memory objects should not merge",
  "inputs": {
    "source_memory": {
      "normalized_content": "Caroline started piano lessons in June 2023.",
      "final_type": "event"
    },
    "candidate_memories": [
      {
        "memory_id": "m_old_2",
        "normalized_content": "Caroline feels calmer after starting piano lessons.",
        "final_type": "state"
      }
    ]
  },
  "expected": {
    "expected_merge_decision": "no_merge"
  }
}
```

---

## E. Update case template

Use when testing update vs no-update.

```json
{
  "case_id": "update_001",
  "family": "update",
  "description": "Changed relocation plan should trigger update",
  "inputs": {
    "source_memory": {
      "normalized_content": "Jon decided to stay in Chicago.",
      "final_type": "plan"
    },
    "candidate_memories": [
      {
        "memory_id": "m_old_plan_1",
        "normalized_content": "Jon plans to move to Boston.",
        "final_type": "plan"
      }
    ]
  },
  "expected": {
    "expected_update_decision": "update",
    "expected_update_type": "plan_revision"
  }
}
```

### Example no-update case

```json
{
  "case_id": "update_002",
  "family": "update",
  "description": "Related but different semantic slot should not update",
  "inputs": {
    "source_memory": {
      "normalized_content": "Melanie likes sunrise paintings.",
      "final_type": "preference"
    },
    "candidate_memories": [
      {
        "memory_id": "m_old_state_1",
        "normalized_content": "Melanie paints in the morning.",
        "final_type": "habit"
      }
    ]
  },
  "expected": {
    "expected_update_decision": "no_update"
  }
}
```

---

## F. Score case template

Use when testing whether score outputs are intuitively aligned.

```json
{
  "case_id": "score_001",
  "family": "score",
  "description": "Stable profile fact should score higher on stability than transient state",
  "inputs": {
    "source_memory": {
      "normalized_content": "Jon runs a dance studio.",
      "final_type": "profile"
    }
  },
  "expected": {
    "expected_score_pattern": {
      "salience": "high",
      "stability": "high",
      "future_utility": "high"
    }
  }
}
```

---

## 7. Expected value styles

Not all expected outputs need to be exact strings.
We can support multiple styles of expectation:

### A. Exact output
Useful for:
- normalized content
- merge/update decision

### B. Categorical expectation
Useful for:
- score pattern (`high`, `medium`, `low`)
- type assignment

### C. Relative expectation
Useful for score comparison cases.

Example:
- profile stability > transient state stability
- major future plan salience > minor disposable fact salience

---

## 8. Suggested first batch size

To keep the first validation tractable, a good v0 target is:

- 3–5 cases per family

That would give roughly:
- extract: 3–5
- categorize: 3–5
- normalize: 3–5
- merge: 3–5
- update: 3–5
- score: 3–5

Total:
- about 18–30 synthetic cases

This is enough to expose many design issues without becoming a full benchmark.

---

## 9. Recommended next step

After agreeing on this template, the next useful step is:

1. create a small first batch of concrete cases,
2. ensure each case is tied to one clear failure mode or boundary,
3. start with merge/update-heavy cases, since those are most error-prone.

---

## 10. Current working summary

Current working assumptions for the synthetic maintenance testset:
- it is for maintenance-side validation, not full benchmark evaluation
- it should be small, controlled, and diagnostic
- it should explicitly cover extract / categorize / normalize / merge / update / score
- different case families should reuse a common schema where possible
- the first version should stay compact and interpretable
