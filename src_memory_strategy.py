"""SrcMemoryStrategy — wraps meta-memory src/ MemoryService for eval_pipeline.

Implements the MemoryStrategy ABC using the full MemoryService from the
meta-memory production codebase (src/service.py).  This exercises the complete
write pipeline (LLM fact extraction, entity graph, vector+FTS storage) and
query pipeline (Router-selected arms, vector+BM25+graph retrieval, hybrid merge).

Unlike MetaSkillStrategy which uses the eval-prototype retrieval code, this
adapter routes through the actual src/ implementation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# Enable logging for Bandit/MetaOptimizer instrumentation
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

# Add meta-memory to Python path
_META_ROOT = Path("/home/kailong/Mem/workspace/meta-memory")
if str(_META_ROOT) not in sys.path:
    sys.path.insert(0, str(_META_ROOT))

# Set up env for meta-memory LLM — MiniMax (OpenAI-compatible, fast, no thinking overhead)
# Force-set (not setdefault) because meta_skill_strategy.py import chain may have
# already set ANTHROPIC_* vars to GLM values before this module loads.
_env_file = "/home/kailong/Quant/memory-eval/.env"
_minimax_url = ""
_minimax_key = ""
try:
    with open(_env_file) as _f:
        for _line in _f:
            if _line.startswith("OPENAI_BASE_URL="):
                _minimax_url = _line.split("=", 1)[1].strip()
            elif _line.startswith("OPENAI_API_KEY="):
                _minimax_key = _line.split("=", 1)[1].strip()
except FileNotFoundError:
    pass
os.environ["ANTHROPIC_BASE_URL"] = _minimax_url
os.environ["ANTHROPIC_AUTH_TOKEN"] = _minimax_key
os.environ["ANTHROPIC_MODEL"] = "MiniMax-M2.5"
os.environ["LLM_API_FORMAT"] = "openai"

from src.service import MemoryService
from src.llm.client import LLMClient as _OrigLLMClient

# Monkey-patch LLMClient.complete_json to strip <think> tags from MiniMax responses
# before JSON parsing. MiniMax-M2.5 embeds reasoning in content as <think>...</think>.
import json as _json
import re as _re

_orig_complete_json = _OrigLLMClient.complete_json

async def _patched_complete_json(self, messages, system_prompt="", max_tokens=2000, extra_body=None):
    # Boost max_tokens: MiniMax-M2.5 embeds <think>...</think> reasoning in content,
    # consuming ~500-800 tokens before the actual JSON. Original max_tokens=1000 from
    # ExtractFactsSkill leaves too little room for the JSON payload.
    boosted_max = max(max_tokens, 4000)
    resp = await self.complete(messages, system_prompt, boosted_max, temperature=0.0, extra_body=extra_body)
    text = resp.content.strip()
    # Strip <think>...</think> reasoning tags
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return _json.loads(text)

_OrigLLMClient.complete_json = _patched_complete_json

# Retry config for LLM-dependent operations (write pipeline).
# GLM-4.7 reasoning model intermittently returns empty content or malformed JSON,
# especially under rapid sequential calls (rate limiting side-effect).
_WRITE_MAX_RETRIES = 5
_WRITE_RETRY_DELAY = 5.0
_INTER_CHUNK_DELAY = 2.0  # seconds between successful chunk writes


class SrcMemoryStrategy:
    """MemoryStrategy that wraps the full meta-memory src/ MemoryService.

    Per-conversation state is fully reset (fresh DB + fresh MemoryService).
    Sessions are buffered during observe() and batch-written on flush().

    All async MemoryService calls are wrapped in a single asyncio.run() call
    per conversation to keep httpx connections and SQLite in the same thread/loop.
    """

    # Max turns per write call — keeps LLM input small enough that the GLM
    # reasoning model has token budget left for actual JSON output.
    _CHUNK_SIZE = 8

    def __init__(self) -> None:
        self._service: MemoryService | None = None
        self._sessions: dict[int, dict] = {}
        self._tmp_dir: str | None = None

    @property
    def name(self) -> str:
        return "src_memory_service"

    def reset(self) -> None:
        """Clear per-conversation state: create a fresh MemoryService with temp DB."""
        if self._service is not None:
            try:
                asyncio.run(self._service.close())
            except Exception:
                pass

        self._sessions = {}
        self._tmp_dir = tempfile.mkdtemp(prefix="src_eval_")
        db_path = os.path.join(self._tmp_dir, "memory.db")
        self._service = MemoryService(db_path=db_path)

    def observe(
        self,
        speaker: str,
        text: str,
        session_date: str = "",
        session_idx: int = -1,
        blip_caption: str = "",
    ) -> None:
        """Buffer a conversation turn into the appropriate session slot."""
        if session_idx not in self._sessions:
            self._sessions[session_idx] = {"date": session_date, "turns": []}
        entry = f"{speaker}: {text}"
        self._sessions[session_idx]["turns"].append(entry)

    def flush(self) -> None:
        """Batch-write all buffered sessions into MemoryService.

        Runs all writes inside a single asyncio.run() call so the httpx
        client and SQLite connection stay in the same event loop and thread.
        """
        if not self._sessions or self._service is None:
            return

        # Build all chunks up front
        chunks: list[tuple[int, int, str]] = []  # (session_idx, chunk_idx, text)
        for idx in sorted(self._sessions.keys()):
            sess = self._sessions[idx]
            date = sess["date"]
            turns = sess["turns"]
            for i in range(0, len(turns), self._CHUNK_SIZE):
                sub_turns = turns[i : i + self._CHUNK_SIZE]
                if date:
                    chunk = f"[{date}]\n" + "\n".join(sub_turns)
                else:
                    chunk = "\n".join(sub_turns)
                chunks.append((idx, i // self._CHUNK_SIZE, chunk))

        svc = self._service

        async def _write_all():
            total = 0
            errors = 0
            for ci, (sess_idx, chunk_idx, chunk_text) in enumerate(chunks):
                for attempt in range(_WRITE_MAX_RETRIES):
                    try:
                        # Extract session_date from chunk header [YYYY-MM-DD]
                        _chunk_date = ""
                        if chunk_text.startswith("["):
                            _end = chunk_text.find("]")
                            if _end > 0:
                                _chunk_date = chunk_text[1:_end]
                        result = await svc.write(chunk_text, session_date=_chunk_date)
                        n_written = len(result.get("written", []))
                        total += 1
                        print(f"[SrcMemory] s{sess_idx}c{chunk_idx} ok: {n_written} facts "
                              f"({ci+1}/{len(chunks)})")
                        # Brief pause between chunks to avoid API rate limiting
                        if ci < len(chunks) - 1:
                            await asyncio.sleep(_INTER_CHUNK_DELAY)
                        break
                    except Exception as e:
                        if attempt < _WRITE_MAX_RETRIES - 1:
                            # Exponential backoff: 5, 10, 20, 40s
                            delay = _WRITE_RETRY_DELAY * (2 ** attempt)
                            print(f"[SrcMemory] s{sess_idx}c{chunk_idx} retry {attempt+1}: {e}")
                            await asyncio.sleep(delay)
                        else:
                            errors += 1
                            print(f"[SrcMemory] s{sess_idx}c{chunk_idx} FAILED after "
                                  f"{_WRITE_MAX_RETRIES} attempts: {e}")
            return total, errors

        total, errors = asyncio.run(_write_all())
        n_sessions = len(self._sessions)
        n_records = self._service._count_records()
        print(f"[SrcMemory] flush: {n_sessions} sessions, {total}/{len(chunks)} chunks ok, "
              f"{errors} errors, {n_records} records in store")
        self._sessions = {}

    def retrieve(self, query: str, client=None) -> str:
        """Retrieve memory context using the full MemoryService query pipeline."""
        if self._service is None:
            return ""

        self._query_count = getattr(self, '_query_count', 0) + 1

        try:
            hits = asyncio.run(self._service.query(query))
        except Exception as e:
            print(f"[SrcMemory] query error: {e}")
            return ""

        # Expose last arm for eval_pipeline logging
        try:
            self._last_arm_id_used = self._service.router._bandit.last_arm
        except Exception:
            self._last_arm_id_used = -1

        if not hits:
            return ""

        parts = []
        for h in hits:
            if isinstance(h, dict):
                content = h.get("content", "") or h.get("text", "") or str(h)
            else:
                content = getattr(h, "content", None) or getattr(h, "text", None) or str(h)
            if content and content.strip():
                parts.append(content.strip())

        return "\n\n---\n\n".join(parts)

    def record_feedback(self, answer: str) -> None:
        """Pass LLM answer back to MemoryService for Bandit reward recording."""
        if self._service is None or not answer:
            return
        try:
            asyncio.run(self._service.record_reward_for_last_query(answer))
        except Exception as e:
            print(f"[SrcMemory] record_feedback error: {e}")

    def get_stats(self) -> dict:
        """Return MemoryService stats (for diagnostics)."""
        if self._service is None:
            return {}
        return self._service.get_stats()
