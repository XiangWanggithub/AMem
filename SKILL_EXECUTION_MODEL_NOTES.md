# Skill Execution Model Notes

This document records current practical conventions for running memory-skill executors with different LLMs.

It is meant to prevent repeated re-discovery of model-specific quirks when testing skill-style prompts.

---

## Goal

When using an LLM as the executor behind a skill such as:
- `merge_memory`
- `update_memory`
- `categorize_memory`
- `normalize_memory`

we want the model to:
- follow the skill contract,
- produce clean structured output,
- avoid polluting the result with reasoning text.

So this document focuses on **execution-time model settings**, not on the skill spec itself.

---

## 1. MiniMax M2.5

### Current convention
Use:

```python
extra_body={"reasoning_split": True}
```

### Why
MiniMax M2.5 often produces reasoning content.
For structured skill execution, especially when requiring strict JSON output, it is safer to split reasoning away from the final visible content.

### Expected handling
- reasoning is separated from final output
- caller should consume only the final content field
- structured JSON output becomes more stable

### Recommended use cases
- skill executor testing
- structured output tasks
- JSON-only result tasks

### Notes
This convention comes from prior project experience in `memory-eval`, not from the skill docs themselves.
It has already been validated as a practical setting for MiniMax in our project context.

---

## 2. GLM-4.7

### Current convention
Use:

```python
extra_body={"thinking": {"type": "disabled"}}
```

### Why
GLM-4.7 has a different reasoning / thinking mechanism from MiniMax.
Disabling thinking is the simplest way to reduce risk of chain-of-thought interfering with strict structured output.

### Expected handling
- no visible thinking content in final output
- cleaner structured response behavior

### Recommended use cases
- skill executor testing
- answer model testing where strict output control matters
- JSON-only output tasks

---

## 3. Common execution preference for skill testing

### General rule
When testing a skill executor, prefer:
- low temperature
- explicit JSON-only instruction
- strict output schema
- model settings that suppress or separate reasoning output

### Recommended defaults
- `temperature=0`
- strong output schema in prompt
- avoid natural-language explanation outside JSON

---

## 4. Why this matters

Skill execution is more fragile than ordinary chat generation.
A useful skill executor should:
- follow contract boundaries,
- produce valid structured output,
- avoid leaking extra reasoning into user-facing or machine-consumed fields.

So these model-specific settings are part of the execution discipline.

---

## 5. Current working summary

### MiniMax M2.5
- use `reasoning_split=True`
- consume final content, not reasoning content

### GLM-4.7
- use `thinking disabled`
- prefer cleaner structured output path

### Shared principle
- skill execution should minimize reasoning pollution in structured outputs
