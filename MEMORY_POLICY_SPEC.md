# memory_policy Spec (Draft v0)

## Goal

`memory_policy` is the orchestration layer that decides how the memory system should operate under the current task, context, and budget.

It does not replace individual memory skills. Instead, it decides:
- which skills to invoke,
- in what order,
- with what operating constraints.

In one sentence:

> `memory_policy` generates an explicit memory-operation plan for the current phase, context, and budget.

---

## Scope of v0

In v0, we define **observe-side memory policy** first.

That means this policy is responsible for deciding how to handle newly arrived context on the write / maintenance side.

It is **not yet** the full retrieve-side policy.

---

## Core design principle

`memory_policy` should output a **plan**, not directly manipulate memory content.

That means it may decide:
- call `extract_memory`
- skip `merge_memory`
- use minimal budget mode
- limit candidate retrieval to top-3

But it should **not directly**:
- rewrite memory content
- perform merge/update judgment itself
- replace individual skill logic

---

## Input

### Required
- `current_phase`
- `current_context`
- `budget_profile`

### Optional
- `model_profile`
- `task_type`
- `memory_state_summary`
- `recent_maintenance_results`
- `policy_history`

---

## Current phase

### Design decision
`current_phase` should be an **explicit runtime input**, not something the policy has to infer by itself.

This keeps boundaries cleaner and makes evaluation/debugging easier.

### v0 phase support
In v0, the main intended phase is:
- `observe`

Future phases may include:
- `retrieve`
- `maintenance`

But we do not need to fully design those yet.

---

## Budget profile

### Current v0 budget levels
- `minimal`
- `standard`
- `rich`

These are intentionally coarse.

### Intuition
- `minimal` = cheaper, lighter path
- `standard` = default path
- `rich` = more complete / expensive path

This is easier to work with in v0 than a fully numeric budget controller.

---

## Output

The output is a **policy plan**.

### Required fields
- `phase`
- `selected_skills`
- `skipped_skills`
- `budget_profile`
- `policy_reason`

### Optional fields
- `skill_params`
  - per-skill configuration hints
- `policy_confidence`
- `fallback_mode`

### Example

```json
{
  "phase": "observe",
  "selected_skills": [
    "extract_memory",
    "categorize_memory",
    "normalize_memory",
    "retrieve_merge_candidates",
    "merge_memory",
    "retrieve_update_candidates",
    "update_memory",
    "score_memory"
  ],
  "skipped_skills": [],
  "budget_profile": "standard",
  "policy_reason": "new context likely contains durable and update-sensitive memory"
}
```

---

## Core responsibilities

`memory_policy` is responsible for four kinds of decisions.

### 1. Skill selection
Which skills should be invoked for the current context.

### 2. Skill ordering
What sequence should be used.

### 3. Budget allocation
How expensive the chosen path should be.

### 4. Mode / parameter selection
What operating constraints or parameters should be used for specific skills.

---

## Non-responsibilities

`memory_policy` is **not** responsible for:
1. extracting memory content itself
2. categorizing memory itself
3. normalizing memory itself
4. making merge decisions itself
5. making update decisions itself
6. scoring memory itself
7. directly mutating memory objects

These belong to the underlying skills.

---

## Observe-side decision examples

### Example 1: rich observe path
If the incoming context is likely high-value and budget is available, policy may choose:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `retrieve_merge_candidates`
- `merge_memory`
- `retrieve_update_candidates`
- `update_memory`
- `score_memory`

### Example 2: cheap observe path
If the incoming context appears low-value or budget is tight, policy may choose:
- `extract_memory`
- maybe `categorize_memory`
- skip merge/update retrieval
- skip score

This is exactly the kind of routing logic the policy layer should own.

---

## Policy inputs that may matter

In v0, these factors may influence policy decisions:

### 1. Context richness
- does the new context appear memory-worthy?
- does it likely contain durable facts, plans, or changes?

### 2. Expected maintenance value
- is merge/update likely worth checking?
- or is the context probably too lightweight?

### 3. Budget profile
- minimal / standard / rich

### 4. Model profile
Future policy may adapt to the strengths/weaknesses of the underlying model.
For example, a weaker model may need more structured support.

---

## Relationship with skills

`memory_policy` sits above the skill layer.

### Skills make local decisions
Examples:
- `categorize_memory` assigns type
- `merge_memory` decides merge vs no-merge
- `update_memory` decides update vs no-update
- `score_memory` produces valuation

### Policy makes global orchestration decisions
Examples:
- whether those skills are invoked at all
- whether the system uses a cheap or rich path
- whether maintenance retrieval is worth the cost

---

## Relationship with future retrieve-side policy

In the future, retrieve-side policy may also exist.

That would decide things like:
- whether memory retrieval is needed for answering
- what granularity to use
- what retrieval backend to use
- how much context to spend

But in v0, we keep the focus narrow:
- **observe-side policy only**

---

## Design rationale

This design helps because:

### 1. It preserves modularity
Skills stay responsible for their own local logic.

### 2. It makes the system adaptive
Different contexts can trigger different maintenance paths.

### 3. It improves fairness and accounting
Policy cost and skill cost can be measured separately.

### 4. It keeps policy explainable
Explicit plans and reasons are easier to audit than hidden orchestration.

---

## Open questions

### 1. Should v0 policy be rule-based, model-based, or hybrid?
Current leaning:
- likely start simple
- rule-based or hybrid may be easier to control and analyze

### 2. Should `selected_skills` be enough, or should policy output a more formal execution graph?
Current leaning:
- selected skills + order is enough in v0
- richer graphs can come later

### 3. Should policy always include `categorize_memory` after extraction?
Current leaning:
- probably yes in most standard paths
- but minimal mode may allow early exit in some cases

### 4. Should policy control candidate retrieval parameters like top-k?
Current leaning:
- yes
- this is one of the most natural places for policy to shape cost/quality tradeoffs

### 5. Should policy ever override a skill’s recommendation (e.g. recommended_route)?
Current leaning:
- yes, policy should retain final orchestration authority
- but such overrides should be explicit and auditable

---

## Current working summary

Current working assumptions for `memory_policy` v0:
- it is an orchestration layer, not a content-processing skill
- v0 focuses on observe-side policy
- `current_phase` is provided explicitly by runtime/orchestrator
- output is an explicit plan with selected skills, skipped skills, budget, and reason
- it should remain explainable
- it should decide whether and how to invoke lower-level skills, without replacing them
