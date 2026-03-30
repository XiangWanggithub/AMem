# extract_memory Skill v0

## Purpose

Extract memory-worthy candidate items from a dialogue delta.

This skill should:
- identify memory-worthy content,
- output semantically self-contained candidate units,
- avoid extracting low-value small talk,
- provide candidate content in a stable natural-language form.

---

## When to use this skill

Use this skill when:
- you have new dialogue turns,
- you want to convert them into candidate memory items for downstream skills.

Do not use this skill to:
- assign final memory type,
- perform merge or update,
- decide retention.

---

## Inputs

### Required input

```json
{
  "dialogue_delta": [
    {
      "turn_id": "t1",
      "speaker": "user",
      "text": "..."
    }
  ]
}
```

### Optional
- dialogue/session timestamp
- lightweight metadata

---

## Decision rules

### Extract when
The content contains memory-worthy information such as:
- important event
- stable preference
- profile / identity fact
- relationship fact
- future plan
- recurring habit
- meaningful state change

### Do not extract when
- pure greeting / small talk
- filler content
- fragments with little future recall value

### Granularity rule
Produce semantically self-contained minimal units.
One sentence may yield multiple candidates if it contains multiple memory-worthy facts.

---

## Output schema

Return JSON only.

```json
{
  "candidates": [
    {
      "content": "..."
    }
  ]
}
```

### Output rules
- If nothing is memory-worthy, return an empty list.
- Do not output explanations outside JSON.

---

## Example 1
Input: Caroline started piano lessons last June and now feels much calmer.
Output candidates:
- Caroline started piano lessons in June 2023.
- Caroline feels calmer now.

## Example 2
Input: Hey, good morning! Hope you're doing well.
Output candidates:
- none
