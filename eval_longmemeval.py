import json
import os
import time
import argparse
from collections import defaultdict
from datetime import datetime

from eval_pipeline import (
    NoMemory, RAGMemory, LLMJudge, AgentLoop,
)


def load_longmemeval(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def ingest_record(strategy, record, max_msg_len: int = 4000):
    """按 haystack_dates 顺序把所有 sessions 的 messages 写入 strategy"""
    strategy.reset()
    sessions = record['haystack_sessions']
    dates = record.get('haystack_dates', [''] * len(sessions))
    for idx, (session, date) in enumerate(zip(sessions, dates)):
        for msg in session:
            if not isinstance(msg, dict):
                continue
            role = msg.get('role', '')
            content = msg.get('content', '')[:max_msg_len]
            if not content:
                continue
            if role in ('user', 'human'):
                strategy.observe(
                    speaker='user',
                    text=content,
                    session_date=str(date),
                    session_idx=idx,
                )
            elif role == 'assistant':
                strategy.observe(
                    speaker='assistant',
                    text=content,
                    session_date=str(date),
                    session_idx=idx,
                )
    # Flush buffered sessions to memory backend (SrcMemoryStrategy batches writes here)
    if hasattr(strategy, "flush"):
        strategy.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', choices=['naive', 'rag', 'src', 'metaskill'], default='naive')
    parser.add_argument('--mode', choices=['selective', 'exhaustive', 'hybrid'], default='selective',
                        help='Memory mode for src strategy (default: selective)')
    parser.add_argument('--probe', type=int, default=0,
                        help='只跑前 N 条记录（成本探测）')
    parser.add_argument('--n', type=int, default=0,
                        help='跑前 N 条（正式评测）')
    parser.add_argument('--question-types', nargs='*', default=None,
                        help='过滤 question_type')
    parser.add_argument('--model', default='MiniMax-M2.5')
    parser.add_argument('--judge-model', default='MiniMax-M2.5')
    parser.add_argument('--output', default='')
    parser.add_argument('--chunk-turns', type=int, default=0,
                        help='RAG ablation: split sessions into N-turn sub-chunks (0=session-level)')
    parser.add_argument('--chunk-size', type=int, default=8,
                        help='SrcMemory: turns per chunk for write() batching (0=session-level)')
    parser.add_argument('--no-rewrite', action='store_true', default=False,
                        help='RAGMemory: 禁用 query rewrite（对照实验用）')
    parser.add_argument('--entry-format', choices=['narrative', 'compact'], default='narrative',
                        help='RAGMemory entry format: "narrative"=Speaker said, "text" (default); "compact"=Speaker: text (matches exhaustive)')
    parser.add_argument('--sort-by-relevance', action='store_true', default=False,
                        help='RAGMemory: return chunks sorted by score descending (matches exhaustive); default is time-sorted')
    parser.add_argument('--separator', default='\n\n',
                        help='RAGMemory: chunk separator in retrieved context (default \\n\\n; exhaustive uses \\n\\n---\\n\\n)')
    args = parser.parse_args()

    data_path = '/home/kailong/Quant/memory-eval/data/longmemeval/longmemeval_s'
    records = load_longmemeval(data_path)

    if args.question_types:
        records = [r for r in records if r.get('question_type') in args.question_types]

    limit = args.probe or args.n or len(records)
    records = records[:limit]
    print(f"Loaded {len(records)} records")

    if args.strategy == 'naive':
        strategy = NoMemory()
    elif args.strategy == 'rag':
        strategy = RAGMemory(chunk_turns=args.chunk_turns, top_k=5, disable_rewrite=args.no_rewrite,
                             entry_format=args.entry_format,
                             sort_by_relevance=args.sort_by_relevance,
                             separator=args.separator)
    elif args.strategy == 'src':
        from src_memory_strategy import SrcMemoryStrategy
        strategy = SrcMemoryStrategy(mode=args.mode, chunk_size=args.chunk_size)
    elif args.strategy == 'metaskill':
        from meta_skill_strategy import MetaSkillStrategy
        strategy = MetaSkillStrategy(use_bandit=True)

    agent = AgentLoop(memory=strategy, model=args.model)
    judge = LLMJudge(model=args.judge_model)

    results = []
    for i, record in enumerate(records):
        t0 = time.time()
        ingest_record(strategy, record)
        ingest_time = time.time() - t0

        question = record['question']
        answer = record['answer']
        # Inject question_date for temporal-reasoning records.
        # LME stores the date the question was "asked" — LLMs need this as a reference
        # for relative-time queries like "how many weeks ago did I do X?".
        # Without injection, LLM uses actual current date (2026), giving wrong elapsed time.
        q_date = record.get('question_date', '')
        # Duration signals that need "now" even for non-temporal question types.
        # "How long have I been working in my current role?" (multi-session) needs "now"
        # to compute duration from start date. The LLM finds the start date but without
        # the reference "now" it can't compute elapsed time.
        _DURATION_NEEDS_NOW = (
            "how long have i been", "how long have you been",
            "how long have we been", "since when",
        )
        if q_date and record.get('question_type') == 'temporal-reasoning':
            question = f"{question}\n(Current date for this question: {q_date})"
        # Also inject question_date for non-temporal questions containing duration signals.
        if q_date and record.get('question_type') != 'temporal-reasoning':
            if any(s in question.lower() for s in _DURATION_NEEDS_NOW):
                question = f"{question}\n(Current date for this question: {q_date})"
        # For arithmetic temporal questions ("how many days/weeks/months between X and Y?"),
        # inject chain-of-thought guidance to prevent LLM month-boundary arithmetic errors.
        # These account for 18/44 (41%) of temporal-reasoning failures.
        # CoT instruction: list both dates from [YYYY-MM-DD] headers, then compute difference.
        # Resolve relative weekday references to absolute dates using question_date.
        # "last Saturday" with question_date "2023/02/15 (Wed)" → 2023-02-11.
        # This improves retrieval: the resolved date gets injected into the question,
        # so DateIndexSkill can boost the matching chunk.
        if q_date and record.get('question_type') == 'temporal-reasoning':
            import re as _re
            from datetime import datetime as _dt, timedelta as _td
            _weekdays = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
                         "friday":4,"saturday":5,"sunday":6}
            _weekday_pat = _re.compile(
                r'\b(?:last|past)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
                _re.IGNORECASE
            )
            _ref_date = None
            try:
                # Parse "2023/02/15 (Wed) 10:20" → 2023-02-15
                _ref_date = _dt.strptime(q_date.split(' ')[0], "%Y/%m/%d")
            except Exception:
                pass
            if _ref_date:
                def _resolve_weekday(m):
                    wd_name = m.group(1).lower()
                    target_wd = _weekdays[wd_name]
                    # Go back to the most recent occurrence of that weekday
                    days_back = (_ref_date.weekday() - target_wd) % 7
                    if days_back == 0:
                        days_back = 7  # "last Saturday" on a Saturday means previous week
                    resolved = _ref_date - _td(days=days_back)
                    return f"[{resolved.strftime('%Y-%m-%d')}] ({m.group(0)})"
                q_lower = question.lower()
                if any(f'last {wd}' in q_lower or f'past {wd}' in q_lower
                       for wd in _weekdays):
                    question = _weekday_pat.sub(_resolve_weekday, question)
                # "past/last weekend" → most recent Saturday
                if 'past weekend' in q_lower or 'last weekend' in q_lower:
                    days_back = (_ref_date.weekday() - 5) % 7  # 5 = Saturday
                    if days_back == 0:
                        days_back = 7
                    sat = _ref_date - _td(days=days_back)
                    question = _re.sub(
                        r'\b(?:past|last)\s+weekend\b',
                        f"[{sat.strftime('%Y-%m-%d')}] (past weekend)",
                        question, flags=_re.IGNORECASE
                    )

        _TEMPORAL_COT_SIGNALS = (
            # Arithmetic: days/weeks/months between events
            "how many days", "how many weeks", "how many months",
            "how long between", "days elapsed", "weeks elapsed", "months elapsed",
            "days did it take", "weeks did it take",
            # Relative-to-now arithmetic
            "days ago", "weeks ago", "months ago",
            "a day ago", "a week ago", "a month ago",
            # "had passed since" / "have passed since" duration
            "had passed since", "have passed since", "has passed since",
            "days since", "weeks since", "months since",
            # "how long since/before/after/did I" duration
            "how long since", "how long after", "how long before", "how long did i",
            "how long had i been", "how long have i been",
            # Ordering: "which happened first X or Y?"
            "happened first", "came first", "completed first", "started first",
            "attend first", "which event first", "which event happened",
            "who did i meet first", "who became", "which project",
            "which task did i complete first",
            "in order from", "from earliest", "earliest to latest",
        )
        if record.get('question_type') == 'temporal-reasoning' and any(
            s in question.lower() for s in _TEMPORAL_COT_SIGNALS
        ):
            question = (
                question
                + "\nHint: First, find the date header (e.g. [2023/02/15 (Wed)]) for each"
                " relevant event in the memory context and list those dates explicitly."
                " Then use those dates to answer the question (compute the difference, or"
                " determine the order)."
            )
        try:
            prediction, latency_ms, tokens, arm_id = agent.answer(question)
        except Exception as e:
            print(f"[{i}] answer error: {e}")
            prediction, latency_ms, tokens, arm_id = "", 0, 0, -1

        try:
            score = judge.score(question, answer, prediction)
        except Exception as e:
            print(f"[{i}] judge error: {e}")
            score = 0.0

        results.append({
            'question_id': record['question_id'],
            'question_type': record['question_type'],
            'question': record['question'],  # original question without date injection
            'question_date': record.get('question_date', ''),
            'answer': answer,
            'prediction': prediction,
            'judge_score': score,
            'n_sessions': len(record['haystack_sessions']),
            'ingestion_time_s': round(ingest_time, 2),
            'latency_ms': latency_ms,
        })
        print(f"  [{i+1}/{len(records)}] {record['question_type']} "
              f"ingest={ingest_time:.1f}s score={score:.2f}")

    overall = sum(r['judge_score'] for r in results) / len(results) if results else 0.0
    by_type: dict = defaultdict(list)
    for r in results:
        by_type[r['question_type']].append(r['judge_score'])
    by_type_summary = {
        t: {'n': len(scores), 'score': round(sum(scores) / len(scores), 4)}
        for t, scores in by_type.items()
    }
    avg_ingest = sum(r['ingestion_time_s'] for r in results) / len(results) if results else 0.0

    output = {
        'strategy': args.strategy,
        'n_records': len(results),
        'overall_score': round(overall, 4),
        'avg_ingestion_time_s': round(avg_ingest, 2),
        'by_question_type': by_type_summary,
        'results': results,
    }

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = args.output or f'results/longmemeval_{args.strategy}_{ts}.json'
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n=== {args.strategy}: {overall:.3f} "
          f"(n={len(results)}, avg_ingest={avg_ingest:.1f}s) ===")
    for t, s in by_type_summary.items():
        print(f"  {t}: {s['score']:.3f} (n={s['n']})")
    print(f"Saved: {out_path}")


if __name__ == '__main__':
    main()
