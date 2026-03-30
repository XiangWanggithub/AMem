# link_memory Skill v0

## Purpose
Determine whether two distinct memory objects should be explicitly linked.

## Rules
- Link when memories are meaningfully related but should remain distinct objects.
- Do not link if they should instead be merged.
- Do not link if they should instead be updated/replaced.
- Do not link if they are only superficially related.
- Return JSON only.

## Output schema
```json
{
  "link_decision": "link|no_link",
  "linked_memory_ids": ["..."],
  "link_type": "event_outcome|event_participant|plan_prerequisite|plan_reason|relation_support|profile_plan|preference_reason|general_related|null",
  "link_reason": "short reason",
  "link_direction": "source_to_candidate|candidate_to_source|null",
  "link_confidence": 0.0
}
```