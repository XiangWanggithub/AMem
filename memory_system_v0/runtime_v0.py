from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from openai import OpenAI


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_json_block(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return json.loads(cleaned)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class RuntimeState:
    run_id: str
    dialogue_id: str
    runtime_dir: Path
    memory_items: list[dict[str, Any]] = field(default_factory=list)
    memory_links: list[dict[str, Any]] = field(default_factory=list)
    memory_events: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    last_processed_turn_id: str | None = None
    policy_mode: str = "standard"
    next_memory_id: int = 1

    def persist(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

        write_jsonl(self.runtime_dir / "memory_items.jsonl", self.memory_items)
        write_jsonl(self.runtime_dir / "memory_links.jsonl", self.memory_links)
        write_jsonl(self.runtime_dir / "memory_events.jsonl", self.memory_events)
        write_jsonl(self.runtime_dir / "answers.jsonl", self.answers)

        summary = {
            "run_id": self.run_id,
            "dialogue_id": self.dialogue_id,
            "last_processed_turn_id": self.last_processed_turn_id,
            "memory_count": len(self.memory_items),
            "link_count": len(self.memory_links),
            "event_count": len(self.memory_events),
            "answer_count": len(self.answers),
            "policy_mode": self.policy_mode,
            "next_memory_id": self.next_memory_id,
            "updated_at": now_iso(),
        }
        (self.runtime_dir / "runtime_state.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class RuntimeV0:
    def __init__(self, runtime_dir: str | Path, dialogue_id: str, run_id: str = "run_001") -> None:
        self.state = RuntimeState(
            run_id=run_id,
            dialogue_id=dialogue_id,
            runtime_dir=Path(runtime_dir),
        )
        self.client = OpenAI(
            base_url="https://api.minimaxi.com/v1",
            api_key="sk-cp-8rjY-rdLgaohfjPxT86FUpq2DFAW_lU8OniwxOveVEIKT6T20oLfZrqJzzgaMzxtdOXMzbnrpHfmOJCdTT3_Ic9uBWDPCpcEV_7pc_o0HNr0U_7NwpavDbo",
        )
        self.extract_skill = (Path(__file__).resolve().parent / "EXTRACT_MEMORY_SKILL_V0.md").read_text(encoding="utf-8")
        self.categorize_skill = (Path(__file__).resolve().parent / "CATEGORIZE_MEMORY_SPEC.md").read_text(encoding="utf-8")
        self.normalize_skill = (Path(__file__).resolve().parent / "NORMALIZE_MEMORY_SPEC.md").read_text(encoding="utf-8")
        self.merge_skill = (Path(__file__).resolve().parent / "MERGE_MEMORY_SKILL_V0.md").read_text(encoding="utf-8")
        self.update_skill = (Path(__file__).resolve().parent / "UPDATE_MEMORY_SPEC.md").read_text(encoding="utf-8")
        self.score_skill = (Path(__file__).resolve().parent / "SCORE_MEMORY_SPEC.md").read_text(encoding="utf-8")
        self.analyze_query_skill = (Path(__file__).resolve().parent / "ANALYZE_QUERY_SKILL_V0.md").read_text(encoding="utf-8")
        self.retrieve_answer_candidates_skill = (Path(__file__).resolve().parent / "RETRIEVE_ANSWER_CANDIDATES_SKILL_V0.md").read_text(encoding="utf-8")
        self.assemble_memory_context_skill = (Path(__file__).resolve().parent / "ASSEMBLE_MEMORY_CONTEXT_SKILL_V0.md").read_text(encoding="utf-8")
        self.trace_path = self.state.runtime_dir / "debug_trace.log"
        self.trace("runtime_init")
        self.state.persist()

    def trace(self, msg: str) -> None:
        append_jsonl(self.trace_path, {"timestamp": now_iso(), "msg": msg})

    def _llm_json(self, prompt: str, label: str) -> dict[str, Any]:
        self.trace(f"llm_start:{label}")
        resp = self.client.chat.completions.create(
            model="MiniMax-M2.5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=1024,
            timeout=180,
            extra_body={"reasoning_split": True},
        )
        self.trace(f"llm_end:{label}")
        return parse_json_block(resp.choices[0].message.content)

    def run_extract(self, turn: dict[str, Any]) -> list[dict[str, Any]]:
        payload = {"dialogue_delta": [turn]}
        schema = '{"candidates":[{"content":"..."}]}'
        prompt = (
            "You are executing the extract_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.extract_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        out = self._llm_json(prompt, f"extract:{turn.get('turn_id')}")
        return out.get("candidates", [])

    def run_categorize(self, item: dict[str, Any]) -> dict[str, Any]:
        schema = '{"final_type":"...","category_confidence":0.0,"recommended_route":"..."}'
        prompt = (
            "You are executing the categorize_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.categorize_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(item, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"categorize:{item.get('memory_id')}")

    def run_normalize(self, item: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "source_memory": item,
            "optional_context": {"dialogue_timestamp": turn.get("timestamp")},
        }
        schema = '{"normalized_content":"...","final_type":"...","normalization_confidence":0.0}'
        prompt = (
            "You are executing the normalize_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.normalize_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"normalize:{item.get('memory_id')}")

    def run_merge(self, item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"source_memory": item, "candidate_memories": candidates}
        schema = '{"merge_decision":"merge|no_merge","merge_confidence":0.0,"merge_reason":"...","merged_memory":null,"consumed_memory_ids":[]}'
        prompt = (
            "You are executing the merge_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.merge_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"merge:{item.get('memory_id')}")

    def run_update(self, item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"source_memory": item, "candidate_memories": candidates}
        schema = '{"update_decision":"update|no_update","update_confidence":0.0,"update_reason":"...","update_type":"... or null","updated_memory":null,"affected_memory_ids":[]}'
        prompt = (
            "You are executing the update_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.update_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"update:{item.get('memory_id')}")

    def run_score(self, item: dict[str, Any]) -> dict[str, Any]:
        schema = '{"salience_score":0.0,"stability_score":0.0,"future_utility_score":0.0,"overall_score":0.0,"score_reason":"..."}'
        prompt = (
            "You are executing the score_memory skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.score_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(item, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"score:{item.get('memory_id')}")

    def run_analyze_query(self, question: dict[str, Any]) -> dict[str, Any]:
        schema = '{"query_type":"...","needs_temporal_reasoning":false,"entities":[],"time_constraints":[],"search_hints":[]}'
        prompt = (
            "You are executing the analyze_query skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.analyze_query_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(question, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"analyze_query:{question.get('question_id')}")

    def run_retrieve_answer_candidates(self, query_analysis: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "query_analysis": query_analysis,
            "memory_items": self.state.memory_items,
        }
        schema = '{"candidates":[{"memory_id":"...","relevance_score":0.0,"reason":"..."}]}'
        prompt = (
            "You are executing the retrieve_answer_candidates skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.retrieve_answer_candidates_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"retrieve_answer_candidates:{query_analysis.get('question_id', 'q')}")

    def run_assemble_memory_context(self, question: dict[str, Any], query_analysis: dict[str, Any], retrieved_candidates: dict[str, Any]) -> dict[str, Any]:
        candidate_ids = [c.get("memory_id") for c in retrieved_candidates.get("candidates", []) if c.get("memory_id")]
        selected_items = [item for item in self.state.memory_items if item.get("memory_id") in candidate_ids]
        payload = {
            "question": question,
            "query_analysis": query_analysis,
            "retrieved_candidates": retrieved_candidates,
            "selected_memory_items": selected_items,
        }
        schema = '{"memory_context":[{"memory_id":"...","content":"...","use_for":"..."}],"answer_strategy":"..."}'
        prompt = (
            "You are executing the assemble_memory_context skill. Follow the skill definition exactly. Return JSON only.\n\n"
            + self.assemble_memory_context_skill
            + "\n\nOutput schema:\n```json\n"
            + schema
            + "\n```\n\nTask input:\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        return self._llm_json(prompt, f"assemble_memory_context:{question.get('question_id')}")

    def answer_question(self, question: dict[str, Any]) -> dict[str, Any]:
        self.trace(f"question_start:{question.get('question_id')}")

        query_analysis = self.run_analyze_query(question)
        query_analysis["question_id"] = question.get("question_id")
        self.state.memory_events.append({
            "event_id": f"evt_{len(self.state.memory_events)+1}",
            "kind": "analyze_query",
            "question_id": question.get("question_id"),
            "result": query_analysis,
            "timestamp": now_iso(),
        })
        self.state.persist()

        retrieved = self.run_retrieve_answer_candidates(query_analysis)
        self.state.memory_events.append({
            "event_id": f"evt_{len(self.state.memory_events)+1}",
            "kind": "retrieve_answer_candidates",
            "question_id": question.get("question_id"),
            "result": retrieved,
            "timestamp": now_iso(),
        })
        self.state.persist()

        assembled = self.run_assemble_memory_context(question, query_analysis, retrieved)
        self.state.memory_events.append({
            "event_id": f"evt_{len(self.state.memory_events)+1}",
            "kind": "assemble_memory_context",
            "question_id": question.get("question_id"),
            "result": assembled,
            "timestamp": now_iso(),
        })

        answer = {
            "question_id": question.get("question_id"),
            "question": question.get("question"),
            "query_analysis": query_analysis,
            "retrieved_candidates": retrieved.get("candidates", []),
            "memory_context": assembled.get("memory_context", []),
            "answer_strategy": assembled.get("answer_strategy"),
            "timestamp": now_iso(),
        }
        self.state.answers.append(answer)
        self.state.persist()
        self.trace(f"question_end:{question.get('question_id')}")
        return answer

    def process_turn(self, turn: dict[str, Any]) -> None:
        self.trace(f"turn_start:{turn.get('turn_id')}")
        self.state.last_processed_turn_id = turn.get("turn_id")

        candidates = self.run_extract(turn)
        self.state.memory_events.append({
            "event_id": f"evt_{len(self.state.memory_events)+1}",
            "kind": "extract",
            "source_turn_id": turn.get("turn_id"),
            "result": candidates,
            "timestamp": now_iso(),
        })
        self.state.persist()

        for cand in candidates:
            base_item = {
                "memory_id": f"m_{self.state.next_memory_id:03d}",
                "content": cand.get("content"),
                "evidence": [{"turn_id": turn.get("turn_id"), "text_span": turn.get("text", "")}],
            }
            self.state.next_memory_id += 1

            cat = self.run_categorize(base_item)
            categorized = {**base_item, **cat}
            self.state.memory_events.append({
                "event_id": f"evt_{len(self.state.memory_events)+1}",
                "kind": "categorize",
                "source_memory_id": categorized["memory_id"],
                "result": cat,
                "timestamp": now_iso(),
            })
            self.state.persist()

            norm = self.run_normalize(categorized, turn)
            normalized = {**categorized, **norm}
            self.state.memory_events.append({
                "event_id": f"evt_{len(self.state.memory_events)+1}",
                "kind": "normalize",
                "source_memory_id": normalized["memory_id"],
                "result": norm,
                "timestamp": now_iso(),
            })
            self.state.persist()

            prior_items = self.state.memory_items[-3:]
            merge_result = self.run_merge(normalized, prior_items) if prior_items else {
                "merge_decision": "no_merge",
                "merge_confidence": 1.0,
                "merge_reason": "no prior memories",
                "merged_memory": None,
                "consumed_memory_ids": [],
            }
            self.state.memory_events.append({
                "event_id": f"evt_{len(self.state.memory_events)+1}",
                "kind": "merge",
                "source_memory_id": normalized["memory_id"],
                "result": merge_result,
                "timestamp": now_iso(),
            })
            self.state.persist()

            update_result = self.run_update(normalized, prior_items) if prior_items else {
                "update_decision": "no_update",
                "update_confidence": 1.0,
                "update_reason": "no prior memories",
                "update_type": None,
                "updated_memory": None,
                "affected_memory_ids": [],
            }
            self.state.memory_events.append({
                "event_id": f"evt_{len(self.state.memory_events)+1}",
                "kind": "update",
                "source_memory_id": normalized["memory_id"],
                "result": update_result,
                "timestamp": now_iso(),
            })
            self.state.persist()

            score_result = self.run_score(normalized)
            normalized = {**normalized, **score_result}
            self.state.memory_events.append({
                "event_id": f"evt_{len(self.state.memory_events)+1}",
                "kind": "score",
                "source_memory_id": normalized["memory_id"],
                "result": score_result,
                "timestamp": now_iso(),
            })

            self.state.memory_items.append(normalized)
            self.state.persist()

        self.trace(f"turn_end:{turn.get('turn_id')}")

    def run_conversation(self, turns: list[dict[str, Any]]) -> None:
        for turn in turns:
            self.process_turn(turn)


if __name__ == "__main__":
    runtime = RuntimeV0(runtime_dir="./runtime_state/demo_run_v5", dialogue_id="demo_conv")
    runtime.run_conversation([
        {"turn_id": "t1", "speaker": "user", "text": "Caroline started piano lessons last June and now feels much calmer.", "timestamp": "2024-03-15"},
        {"turn_id": "t2", "speaker": "user", "text": "Melanie plans to move next year.", "timestamp": "2024-03-15"},
    ])
    answer = runtime.answer_question({
        "question_id": "q1",
        "question": "Who plans to move next year?",
    })
    print(json.dumps(answer, ensure_ascii=False, indent=2))
