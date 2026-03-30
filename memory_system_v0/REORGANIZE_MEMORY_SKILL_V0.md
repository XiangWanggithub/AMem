# reorganize_memory Skill v0

## Purpose
Determine whether a local memory region should be reorganized and propose high-level structural actions.

## Rules
- Reorganize only when the memory region has become large, fragmented, or structurally inefficient.
- Prefer local reorganization over whole-store reorganization.
- Propose actions such as cluster_memories, suggest_summary_node, promote_core_memories, demote_fragmented_memories, restructure_links.
- Do not silently mutate memory structures.
- Return JSON only.

## Output schema
```json
{
  "reorganization_decision": "reorganize|no_reorganize",
  "reorganization_actions": ["cluster_memories|suggest_summary_node|promote_core_memories|demote_fragmented_memories|restructure_links"],
  "affected_memory_ids": ["..."],
  "reorganization_reason": "short reason",
  "suggested_clusters": []
}
```