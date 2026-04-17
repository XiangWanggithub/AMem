"""V1MemoryStrategy — v0.1 hierarchical memory adapter for eval harness.

Wraps the new 4-layer substrate (L0 episode → L0.5 card → L1 fact → L2 index)
with unified RetrievalPipelineV1 (no keyword rules, no query classification).

Exercises:
  - IngestPipeline: hybrid boundary detection + LLM card generation + L2 indexing
  - RetrievalPipelineV1: cards → episodes → soft boosts → CE rerank

Follows SrcMemoryStrategy's async integration pattern: one asyncio.run() per
flush() / retrieve() call.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

_META_ROOT = Path("/home/kailong/Mem/workspace/meta-memory")
if str(_META_ROOT) not in sys.path:
    sys.path.insert(0, str(_META_ROOT))

# GLM env setup — match src_memory_strategy.py. Force-set (not setdefault) so we
# win against anything earlier in the import chain.
_env_file = "/home/kailong/Quant/memory-eval/.env"
_glm_url = ""
_glm_key = ""
try:
    with open(_env_file) as _f:
        for _line in _f:
            if _line.startswith("GLM_BASE_URL="):
                _glm_url = _line.split("=", 1)[1].strip()
            elif _line.startswith("GLM_API_KEY="):
                _glm_key = _line.split("=", 1)[1].strip()
except FileNotFoundError:
    pass
os.environ["ANTHROPIC_BASE_URL"] = _glm_url
os.environ["ANTHROPIC_AUTH_TOKEN"] = _glm_key
os.environ["ANTHROPIC_MODEL"] = "glm-4-flash"
os.environ["LLM_API_FORMAT"] = "openai"

from src.ingest.card_generator import CardGenerator
from src.ingest.episode_segmenter import EpisodeSegmenter, TurnData
from src.ingest.pipeline import IngestPipeline
from src.llm.client import LLMClient
from src.policy.retrieval_policy import ConditionalPolicy, RetrievalPolicy
from src.retrieval.v1_pipeline import RetrievalPipelineV1
from src.storage.hierarchical_store import HierarchicalStore


def _compute_retrieval_metrics(results: list[dict]) -> dict:
    """Derive scalar retrieval diagnostics from the pipeline's top-K output.

    All values are aggregate numbers (counts, means, stddevs, Jaccard-like
    diversity) — no textual content is leaked. Used by the no-leak Phase B
    MetaOptimizer as an Option D auxiliary signal.
    """
    if not results:
        return {
            "top_k_count": 0,
            "similarity_mean": 0.0,
            "similarity_std": 0.0,
            "similarity_min": 0.0,
            "similarity_max": 0.0,
            "diversity": 0.0,
            "unique_sessions": 0,
        }
    scores = [float(r.get("score", 0.0)) for r in results]
    n = len(scores)
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / n
    std = var ** 0.5

    # Cheap diversity proxy: 1 - mean pairwise Jaccard over content token sets.
    # Higher → more diverse retrieved content. Bounded to [0, 1].
    contents = [str(r.get("content", "")) for r in results]
    token_sets = [set(c.lower().split()) for c in contents]
    if n >= 2:
        sims = []
        for i in range(n):
            for j in range(i + 1, n):
                a, b = token_sets[i], token_sets[j]
                if not a and not b:
                    sims.append(0.0)
                    continue
                union = a | b
                if not union:
                    sims.append(0.0)
                    continue
                sims.append(len(a & b) / len(union))
        mean_sim = sum(sims) / len(sims) if sims else 0.0
        diversity = max(0.0, 1.0 - mean_sim)
    else:
        diversity = 0.0

    unique_sessions = len({r.get("session_date", "") for r in results if r.get("session_date")})

    return {
        "top_k_count": n,
        "similarity_mean": float(mean),
        "similarity_std": float(std),
        "similarity_min": float(min(scores)),
        "similarity_max": float(max(scores)),
        "diversity": float(diversity),
        "unique_sessions": int(unique_sessions),
    }


_EMBEDDING_MODEL_PATH = os.environ.get(
    "V1_EMBEDDING_MODEL", "/home/models/bge-large-en-v1.5"
)
_CE_MODEL_NAME = os.environ.get(
    "V1_CE_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)


# Lazy module-level singletons so repeated strategy instantiations (one per
# conversation in eval loops) don't reload the models.
_st_model = None
_ce_model = None


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer(_EMBEDDING_MODEL_PATH)
        print(f"[V1Memory] loaded embedding model: {_EMBEDDING_MODEL_PATH}")
    return _st_model


def _get_ce_model():
    global _ce_model
    if _ce_model is None:
        try:
            from sentence_transformers.cross_encoder import CrossEncoder
            _ce_model = CrossEncoder(_CE_MODEL_NAME, max_length=512)
            print(f"[V1Memory] loaded CE model: {_CE_MODEL_NAME}")
        except Exception as e:
            print(f"[V1Memory] CE model unavailable ({e}); rerank disabled")
            _ce_model = False  # sentinel: don't retry
    return _ce_model if _ce_model is not False else None


class V1MemoryStrategy:
    """Eval adapter for the v0.1 hierarchical memory system."""

    def __init__(
        self,
        policy: RetrievalPolicy | None = None,
        *,
        disable_llm: bool = False,
        fast_ingest: bool = True,
    ) -> None:
        # disable_llm=True → fall back to regex boundary detection + template
        # cards. Useful for smoke-testing the substrate without LLM spend.
        # fast_ingest=True → skip LLM for ingest-side components only
        # (EpisodeSegmenter + CardGenerator get llm_fn=None), leaving
        # disable_llm as the more aggressive flag that also suppresses the
        # LLMClient itself. The two knobs are orthogonal.
        # Load policy from file if POLICY_CONFIG_PATH is set (used by self-evolution runner)
        self._conditional_policy: ConditionalPolicy | None = None
        if policy is None:
            _policy_path = os.environ.get("POLICY_CONFIG_PATH")
            if _policy_path and os.path.exists(_policy_path):
                import json as _json
                try:
                    with open(_policy_path) as _pf:
                        _pdata = _json.load(_pf)
                    if "default" in _pdata:
                        # ConditionalPolicy format: {"default": {...}, "overrides": {...}}
                        _default = RetrievalPolicy(**_pdata["default"])
                        _overrides = {
                            k: RetrievalPolicy(**v)
                            for k, v in _pdata.get("overrides", {}).items()
                        }
                        self._conditional_policy = ConditionalPolicy(
                            default=_default, overrides=_overrides,
                        )
                        policy = _default  # backwards compat: _policy is still the default
                        print(
                            f"[V1Memory] loaded conditional policy from {_policy_path} "
                            f"(overrides: {list(_overrides.keys())})"
                        )
                    else:
                        # Flat format (backwards compat)
                        policy = RetrievalPolicy(**_pdata)
                        print(f"[V1Memory] loaded policy from {_policy_path}")
                except Exception as _pe:
                    print(f"[V1Memory] policy load failed ({_pe}), using default")
        self._policy = policy or RetrievalPolicy()
        # Ensure _conditional_policy always exists (wraps flat policy as default-only)
        if self._conditional_policy is None:
            self._conditional_policy = ConditionalPolicy(default=self._policy)
        self._disable_llm = disable_llm
        self._fast_ingest = fast_ingest

        self._store: HierarchicalStore | None = None
        self._llm_client: LLMClient | None = None
        self._ingest_pipeline: IngestPipeline | None = None
        self._retrieval_pipeline: RetrievalPipelineV1 | None = None
        self._initialized = False

        # Session buffer: session_idx → ordered TurnData list
        self._session_turns: dict[int, list[TurnData]] = {}
        self._session_dates: dict[int, str] = {}
        self._turn_counter: dict[int, int] = {}

        self._qa_count: int = 0
        # Option D (no-leak Phase B): per-QA retrieval diagnostics captured by
        # retrieve(). Strategy-agnostic field name consumed by eval_pipeline.
        self._last_retrieval_metrics: dict = {}

    @property
    def name(self) -> str:
        return "v1_memory"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _ensure_init(self) -> None:
        if self._initialized:
            return

        st_model = _get_st_model()
        ce_model = _get_ce_model()

        async def embed_fn(texts: list[str]) -> list[list[float]]:
            if not texts:
                return []
            vecs = st_model.encode(texts, normalize_embeddings=True)
            return [list(v.tolist()) for v in vecs]

        # LLM wrapper: segmenter/card-gen expect Callable[[str], Awaitable[str]].
        # Route through LLMClient.complete(); return plain text (they parse JSON).
        llm_fn = None
        if not self._disable_llm:
            self._llm_client = LLMClient()
            _client = self._llm_client

            async def llm_fn_impl(prompt: str) -> str:
                resp = await _client.complete(
                    [{"role": "user", "content": prompt}],
                    max_tokens=2048,
                    temperature=0.0,
                )
                return resp.content or ""

            llm_fn = llm_fn_impl

        ce_fn = None
        if ce_model is not None:
            async def ce_fn_impl(query: str, texts: list[str]) -> list[float]:
                if not texts:
                    return []
                pairs = [[query, t] for t in texts]
                scores = ce_model.predict(pairs, show_progress_bar=False)
                return [float(s) for s in scores.tolist()]

            ce_fn = ce_fn_impl

        # Ingest-specific LLM reference: suppressed when either fast_ingest or
        # disable_llm is True, keeping the two flags orthogonal.
        ingest_llm_fn = None if (self._disable_llm or self._fast_ingest) else llm_fn

        self._store = HierarchicalStore()
        segmenter = EpisodeSegmenter(
            embed_fn=embed_fn,
            llm_fn=ingest_llm_fn,
            similarity_threshold=self._policy.similarity_threshold,
        )
        card_gen = CardGenerator(llm_fn=ingest_llm_fn, embed_fn=embed_fn)
        self._ingest_pipeline = IngestPipeline(
            store=self._store,
            segmenter=segmenter,
            card_gen=card_gen,
            embed_fn=embed_fn,
            llm_fn=llm_fn,
        )
        self._retrieval_pipeline = RetrievalPipelineV1(
            store=self._store,
            policy=self._policy,
            embed_fn=embed_fn,
            ce_fn=ce_fn,
        )
        self._initialized = True

    def reset(self) -> None:
        """Clear all memory for a new conversation. Drops store + pipelines.

        The embedding / CE models persist at module scope so we don't pay
        the load cost on every record.
        """
        # Close the prior LLM client if we had one.
        if self._llm_client is not None:
            try:
                asyncio.run(self._llm_client.close())
            except Exception:
                pass
            self._llm_client = None

        self._store = None
        self._ingest_pipeline = None
        self._retrieval_pipeline = None
        self._initialized = False

        self._session_turns.clear()
        self._session_dates.clear()
        self._turn_counter.clear()
        self._last_retrieval_metrics = {}

    # ── Ingest side ──────────────────────────────────────────────────────────

    def observe(
        self,
        speaker: str,
        text: str,
        session_date: str = "",
        session_idx: int = -1,
        blip_caption: str = "",
    ) -> None:
        """Buffer a single conversation turn for its session."""
        if not text:
            return
        body = text
        if blip_caption:
            body = f"{text} [image: {blip_caption}]"

        turn_idx = self._turn_counter.get(session_idx, 0)
        self._turn_counter[session_idx] = turn_idx + 1

        turn = TurnData(
            speaker=speaker,
            text=body,
            turn_idx=turn_idx,
            session_date=session_date,
        )
        self._session_turns.setdefault(session_idx, []).append(turn)
        if session_date and session_idx not in self._session_dates:
            self._session_dates[session_idx] = session_date

    def flush(self) -> None:
        """Ingest all buffered sessions in one asyncio.run() call."""
        if not self._session_turns:
            return
        self._ensure_init()
        assert self._ingest_pipeline is not None

        sessions = sorted(self._session_turns.items())
        ingest = self._ingest_pipeline

        async def _ingest_all() -> list[dict]:
            stats: list[dict] = []
            for session_idx, turns in sessions:
                if not turns:
                    continue
                session_id = f"session_{session_idx}"
                space_id = "default"
                try:
                    result = await ingest.ingest_session(
                        turns, space_id=space_id, session_id=session_id
                    )
                    stats.append({"session_idx": session_idx, **result})
                except Exception as e:
                    print(f"[V1Memory] ingest s{session_idx} failed: {e}")
            return stats

        stats = asyncio.run(_ingest_all())
        total_ep = sum(s.get("n_episodes", 0) for s in stats)
        total_cards = sum(s.get("n_cards", 0) for s in stats)
        assert self._store is not None
        store_stats = self._store.stats()
        print(
            f"[V1Memory] flush: {len(stats)} sessions, "
            f"{total_ep} episodes, {total_cards} cards; store={store_stats}"
        )

        self._session_turns.clear()
        self._session_dates.clear()
        self._turn_counter.clear()

    # ── Retrieve side ────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        client=None,
        question_date: str = "",
        query_type: str = "",
    ) -> str:
        """Run a single query through RetrievalPipelineV1, return joined context.

        When question_date is provided, prepends a `[Current date: ...]` header
        so the LLM can resolve relative-time references in the question against
        an absolute reference point. No instruction is added — only the fact.

        query_type: optional query category (e.g. "multi-hop", "temporal").
        When provided AND a ConditionalPolicy with matching override is loaded,
        the override policy is used for this query instead of the default.
        """
        if not query:
            self._last_retrieval_metrics = {}
            return ""
        self._ensure_init()
        assert self._retrieval_pipeline is not None

        # Select policy based on query_type (conditional policy dispatch)
        assert self._conditional_policy is not None
        policy = self._conditional_policy.get_policy(query_type)
        if policy is not self._policy:
            # Hot-swap the pipeline's policy for this query
            self._retrieval_pipeline.policy = policy

        pipeline = self._retrieval_pipeline
        try:
            results = asyncio.run(pipeline.query(query))
        except Exception as e:
            print(f"[V1Memory] query error: {e}")
            self._last_retrieval_metrics = {}
            return ""
        finally:
            # Restore default policy after query (avoid leaking override state)
            if policy is not self._policy:
                self._retrieval_pipeline.policy = self._policy

        self._qa_count += 1
        # Option D: compute retrieval diagnostics from the returned top-K results.
        # These are scalar statistics — no entity strings, no gold info. Safe to
        # feed into the MetaOptimizer prompt as a non-leaking auxiliary signal.
        self._last_retrieval_metrics = _compute_retrieval_metrics(results)
        date_header = f"[Current date: {question_date}]\n\n" if question_date else ""

        if not results:
            return date_header.rstrip() if date_header else ""

        parts: list[str] = []
        for r in results:
            content = (r.get("content") or "").strip()
            if content:
                parts.append(content)
        return date_header + "\n\n---\n\n".join(parts)

    # Eval harness compat: no-op hooks so update_reward / record_feedback
    # calls don't crash. v0.1 has no Bandit/MetaOptimizer yet.
    def record_feedback(self, answer: str) -> None:
        return None

    def update_reward(self, question: str, score: float) -> None:
        return None

    def get_stats(self) -> dict:
        if self._store is None:
            return {}
        return self._store.stats()
