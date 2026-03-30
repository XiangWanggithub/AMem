# Memory Skill Mapping Draft

> Goal: abstract reusable memory skills from existing frameworks (currently MemOS and OpenViking),
> and use them as the foundation for designing a new skill-based memory system.

## Why this document exists

Current memory frameworks often hide substantial LLM decision-making inside internal stages such as:
- extraction
- summarization
- merge / reorganization
- overview generation
- intent analysis
- retrieval routing

These stages consume tokens and latency, but are often not fully accounted for in benchmark comparisons.

This document tries to:
1. expose those hidden stages,
2. map them into explicit reusable **memory skills**,
3. prepare a cleaner foundation for a future skill-based memory system.

---

## High-level skill families

We currently group candidate skills into three major families:

### 1. Formation Skills
Skills that convert raw conversation into memory units.

Examples:
- `extract_memory`
- `categorize_memory`
- `normalize_memory`
- `update_memory`
- `merge_memory`

### 2. Organization Skills
Skills that restructure, compress, relate, or summarize stored memory.

Examples:
- `summarize_session`
- `generate_memory_abstract`
- `generate_directory_overview`
- `link_memory`
- `reorganize_memory`

### 3. Retrieval Skills
Skills that analyze the query and retrieve memory at the right granularity.

Examples:
- `intent_analyze_query`
- `route_query`
- `hierarchical_retrieve`
- `select_retrieval_granularity`
- `read_memory_content`
- `expand_directory`

---

## Part I. MemOS → Skill Mapping

### MemOS overall character

MemOS is best viewed as a **memory formation + maintenance oriented system**.
Its strengths are less about fancy retrieval interfaces and more about transforming raw conversation into more structured, merged, and maintainable memory objects.

### MemOS mapping table

| Framework | Internal step / concept | What it does | Abstracted skill | Phase | Notes |
|---|---|---|---|---|---|
| MemOS | memory extraction | Extract candidate memory from raw dialogue | `extract_memory` | observe | Core observe-side skill |
| MemOS | memory typing / cube organization | Put memory into different categories / containers | `categorize_memory` | observe | Could later map to event / preference / entity / profile |
| MemOS | canonicalization / cleanup | Rewrite memory into cleaner and more stable form | `normalize_memory` | observe | Important for reducing ambiguity and improving later merge/update |
| MemOS | duplicate consolidation / enrichment | Merge repeated or overlapping memory items | `merge_memory` | maintenance | Broader than exact deduplication |
| MemOS | state update | Modify existing memory when new evidence arrives | `update_memory` | maintenance | Different from simple append and different from merge |
| MemOS | relation construction | Build relations among memory objects | `link_memory` | maintenance / organization | Could later support graph-style memory |
| MemOS | salience estimation | Judge which memories are important | `score_memory` | maintenance | Can support later retention / promotion policy |
| MemOS | reorganizer | Reorganize stored memory structures for better maintainability | `reorganize_memory` | maintenance | One of the most characteristic MemOS-style steps |

### MemOS-inspired observations

1. MemOS is strong at **turning conversation into memory objects**.
2. MemOS emphasizes **maintenance after storage**, not just extraction.
3. We currently treat the following as the **MemOS core skills v1**:
   - `extract_memory`
   - `categorize_memory`
   - `normalize_memory`
   - `merge_memory`
   - `update_memory`
   - `link_memory`
   - `score_memory`
   - `reorganize_memory`
4. `promote_to_long_term_memory` is currently **not treated as a core atomic skill**.
   For now, we treat it as a possible **policy consequence** of scoring / retention decisions, and may revisit it later in higher-level system design.

---

## Part II. OpenViking → Skill Mapping

### OpenViking overall character

OpenViking is best viewed as a **hierarchical organization + retrieval oriented system**.
Its most distinctive traits are:
- multi-level representations (L0 / L1 / L2),
- session compression,
- overview / abstract generation,
- hierarchical retrieval,
- intent-aware query planning.

### OpenViking mapping table

| Framework | Internal step / concept | What it does | Abstracted skill | Phase | Notes |
|---|---|---|---|---|---|
| OpenViking | session archive / compression | Compress session messages into a more manageable representation | `summarize_session` | observe / maintenance | Intermediate representation before deeper extraction |
| OpenViking | memory extraction from archive | Extract memory from archived session content | `extract_memory` | observe | Similar high-level role to MemOS extraction |
| OpenViking | L0 abstract | Create lightweight abstract for a memory item | `generate_memory_abstract` | organization | Supports cheap first-pass retrieval |
| OpenViking | L1 overview | Create directory-level overview | `generate_directory_overview` | organization | One of OpenViking's distinctive strengths |
| OpenViking | L2 raw/full read | Read full content for detailed retrieval | `read_memory_content` | retrieve | Highest detail, highest token cost |
| OpenViking | hierarchical retriever | Retrieve through multi-level structure rather than flat vector search | `hierarchical_retrieve` | retrieve | Central OpenViking retrieval skill |
| OpenViking | level selection | Choose among L0 / L1 / L2 representations | `select_retrieval_granularity` | retrieve | Budget-aware / query-aware retrieval skill |
| OpenViking | intent analyzer | Infer query intent before retrieval | `intent_analyze_query` | retrieve | Used in `search()`-style retrieval path |
| OpenViking | query routing | Route query to relevant directories / context types / levels | `route_query` | retrieve | Decides which retrieval path to use |
| OpenViking | directory expansion (`ls`) | Expand a directory when higher-level match is promising | `expand_directory` | retrieve | Useful for coarse-to-fine retrieval |
| OpenViking | abstract / overview / file hierarchy | Represent memory at multiple abstraction levels | `multi_resolution_memory_representation` | organization | More representation-level than action-level |

### OpenViking-inspired observations

1. OpenViking is strong at **representing memory at different granularities**.
2. OpenViking's biggest contribution is likely on the **retrieve side**, not the formation side.
3. OpenViking likely contributes most to a future system in the areas of:
   - hierarchical retrieval,
   - query intent analysis,
   - retrieval routing,
   - overview / abstract generation,
   - adaptive granularity selection.

---

## Part III. Shared skills between MemOS and OpenViking

These are the most likely candidates for framework-agnostic reusable skills.

| Shared skill | Meaning | Likely importance |
|---|---|---|
| `extract_memory` | Extract memory candidates from conversation | Very high |
| `normalize_memory` | Rewrite memory into canonical, less ambiguous form | High |
| `merge_memory` | Merge overlapping or repeated memory | High |
| `update_memory` | Modify prior memory using new evidence | High |
| `summarize_session` | Compress a session into a shorter representation | Medium-High |
| `link_memory` | Connect memory items by entity/event/topic/time | Medium-High |
| `intent_analyze_query` | Infer what kind of retrieval the current question needs | High |
| `route_query` | Select retrieval path based on query intent and budget | High |
| `select_retrieval_granularity` | Decide whether to use abstract / overview / full content | Very high |
| `read_memory_content` | Fetch detailed memory content for answering | Very high |

---

## Part IV. Skills that seem more framework-specific

### More MemOS-specific
- `reorganize_memory`
- `score_memory`
- `promote_to_long_term_memory` (currently treated as policy-level consequence, not core atomic skill)
- `structure_memory_artifacts`

These seem tied to memory maintenance, long-term consolidation, and structured memory object management.

### More OpenViking-specific
- `generate_directory_overview`
- `generate_memory_abstract`
- `hierarchical_retrieve`
- `expand_directory`
- `multi_resolution_memory_representation`

These seem tied to hierarchical filespace-like organization and multi-level access.

---

## Part V. Initial synthesis for a new system

A future unified system might borrow from both sides:

### Learn from MemOS
- how to form cleaner memory units,
- how to merge / update them,
- how to periodically reorganize them,
- how to preserve important memory over time.

### Learn from OpenViking
- how to maintain multiple resolutions of memory,
- how to route retrieval queries,
- how to select the right level of detail,
- how to do coarse-to-fine retrieval.

### Possible synthesis direction
A new system could be organized as:

1. **Formation layer**
   - extract
   - normalize
   - categorize
   - merge
   - update

2. **Organization layer**
   - abstract
   - overview
   - summarize
   - link
   - reorganize
   - promote

3. **Retrieval layer**
   - analyze query
   - route query
   - choose granularity
   - retrieve / expand / read

4. **Policy layer** (future)
   - decide which skills to invoke,
   - decide how much budget to spend,
   - adapt memory behavior to task type and model capability.

---

## Part VI. Open questions for discussion

These questions should be discussed before we lock the new system design:

1. Which of these should count as true atomic skills, and which are composite skills?
2. Should `summarize_session` be considered formation or organization?
3. Should memory skills operate on raw text only, or on structured memory artifacts?
4. Which skills should be cheap default actions, and which should be expensive optional actions?
5. How should token accounting be done fairly across:
   - observe
   - maintenance
   - retrieval
   - answer
   - policy/orchestration
6. Which skills should remain deterministic / non-LLM, and which should remain LLM-driven?
7. Should the future controller be called a **meta-skill**, **memory policy**, or **memory controller**?

---

## Part VII. Current working hypothesis

Current working hypothesis:

- **MemOS contributes stronger formation / maintenance skills.**
- **OpenViking contributes stronger organization / retrieval skills.**
- A stronger next-generation memory system may come from combining:
  - MemOS-style memory formation and consolidation,
  - OpenViking-style multi-resolution organization and hierarchical retrieval,
  - plus a new policy layer that decides when and how to use these skills.
