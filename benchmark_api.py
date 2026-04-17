"""Benchmark API providers for judge-like workload.

Measures per-call latency + concurrency throughput for:
- MiniMax M2.5 (OPENAI_BASE_URL / OPENAI_API_KEY)
- GLM-4 (GLM_BASE_URL / GLM_API_KEY)

Usage:
    python benchmark_api.py
"""
import asyncio
import os
import statistics
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Test payload mimicking judge workload (~200-300 tokens)
JUDGE_TEST_PROMPT = """You are a judge. Score the prediction against the reference.

Question: What did Caroline research?
Reference: Adoption agencies
Prediction: Caroline researched counseling or mental health work.

Output JSON only: {"score": 0.0|0.5|1.0}"""


@dataclass
class ProviderCfg:
    name: str
    base_url: str
    api_key: str
    model: str


PROVIDERS = [
    ProviderCfg(
        name="MiniMax-M2",
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        model="MiniMax-M2",
    ),
    ProviderCfg(
        name="GLM-4.5",
        base_url=os.environ.get("GLM_BASE_URL", ""),
        api_key=os.environ.get("GLM_API_KEY", ""),
        model="glm-4.5",
    ),
]


async def _one_call(client, model: str) -> tuple[float, Optional[str]]:
    """Fire one chat completion, return (latency_sec, error_or_None)."""
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": JUDGE_TEST_PROMPT}],
            max_tokens=50,
            temperature=0.0,
        )
        _ = resp.choices[0].message.content
        return (time.perf_counter() - t0, None)
    except Exception as e:
        return (time.perf_counter() - t0, f"{type(e).__name__}: {str(e)[:80]}")


async def sequential_test(cfg: ProviderCfg, n: int = 10) -> dict:
    """n sequential calls, measure per-call latency."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=30.0)
    latencies = []
    errors = []
    t0 = time.perf_counter()
    for i in range(n):
        lat, err = await _one_call(client, cfg.model)
        if err:
            errors.append(err)
        else:
            latencies.append(lat)
    total = time.perf_counter() - t0
    return {
        "total_sec": total,
        "successful_calls": len(latencies),
        "errors": errors,
        "p50": statistics.median(latencies) if latencies else 0.0,
        "p95": statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0),
        "mean": statistics.mean(latencies) if latencies else 0.0,
        "min": min(latencies) if latencies else 0.0,
        "max": max(latencies) if latencies else 0.0,
    }


async def concurrent_test(cfg: ProviderCfg, concurrency: int = 10) -> dict:
    """concurrency parallel calls, measure wall time + detect 429."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=30.0)
    t0 = time.perf_counter()
    results = await asyncio.gather(*[_one_call(client, cfg.model) for _ in range(concurrency)], return_exceptions=True)
    total = time.perf_counter() - t0
    latencies = [r[0] for r in results if isinstance(r, tuple) and r[1] is None]
    errors = [r[1] for r in results if isinstance(r, tuple) and r[1] is not None]
    rate_limit = [e for e in errors if "429" in e or "rate" in e.lower()]
    return {
        "wall_sec": total,
        "successful": len(latencies),
        "failed": len(errors),
        "rate_limited": len(rate_limit),
        "errors_sample": errors[:3],
        "throughput_qps": len(latencies) / total if total > 0 else 0.0,
        "p50_lat": statistics.median(latencies) if latencies else 0.0,
    }


async def burst_test(cfg: ProviderCfg, total_calls: int = 30, concurrency: int = 20) -> dict:
    """Fire total_calls with concurrency limit, detect 429 under sustained load."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=30.0)
    sem = asyncio.Semaphore(concurrency)

    async def bounded_call():
        async with sem:
            return await _one_call(client, cfg.model)

    t0 = time.perf_counter()
    results = await asyncio.gather(*[bounded_call() for _ in range(total_calls)], return_exceptions=True)
    total = time.perf_counter() - t0
    latencies = [r[0] for r in results if isinstance(r, tuple) and r[1] is None]
    errors = [r[1] for r in results if isinstance(r, tuple) and r[1] is not None]
    rate_limit = [e for e in errors if "429" in e or "rate" in e.lower()]
    return {
        "wall_sec": total,
        "total_attempted": total_calls,
        "successful": len(latencies),
        "rate_limited": len(rate_limit),
        "other_errors": len(errors) - len(rate_limit),
        "sustained_qps": len(latencies) / total if total > 0 else 0.0,
    }


async def main():
    for cfg in PROVIDERS:
        print(f"\n{'=' * 60}")
        print(f"Provider: {cfg.name}")
        print(f"Base URL: {cfg.base_url or '[NOT SET]'}")
        print(f"Model:    {cfg.model}")
        print(f"{'=' * 60}")

        if not cfg.base_url or not cfg.api_key:
            print(f"  SKIP: missing credentials")
            continue

        print("\n--- Sequential 10 calls ---")
        seq = await sequential_test(cfg, n=10)
        print(f"  Total: {seq['total_sec']:.1f}s | Success: {seq['successful_calls']}/10")
        print(f"  Per-call latency: mean={seq['mean']:.2f}s  p50={seq['p50']:.2f}s  max={seq['max']:.2f}s")
        if seq['errors']:
            print(f"  Errors: {seq['errors'][:2]}")

        print("\n--- Concurrent 10 calls ---")
        par = await concurrent_test(cfg, concurrency=10)
        print(f"  Wall: {par['wall_sec']:.1f}s | Success: {par['successful']}/10 | Rate-limited: {par['rate_limited']}")
        print(f"  Throughput: {par['throughput_qps']:.2f} QPS | p50 lat: {par['p50_lat']:.2f}s")
        if par['errors_sample']:
            print(f"  Errors: {par['errors_sample']}")

        print("\n--- Burst 30 calls @ concurrency=20 ---")
        burst = await burst_test(cfg, total_calls=30, concurrency=20)
        print(f"  Wall: {burst['wall_sec']:.1f}s | Success: {burst['successful']}/30 | 429: {burst['rate_limited']} | Other err: {burst['other_errors']}")
        print(f"  Sustained QPS: {burst['sustained_qps']:.2f}")

    print("\n\nDONE.")


if __name__ == "__main__":
    asyncio.run(main())
