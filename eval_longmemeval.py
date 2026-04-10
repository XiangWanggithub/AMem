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
        strategy = RAGMemory()
    elif args.strategy == 'src':
        from src_memory_strategy import SrcMemoryStrategy
        strategy = SrcMemoryStrategy(mode=args.mode)
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
            'question': question,
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
