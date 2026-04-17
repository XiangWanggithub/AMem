
# ─────────────────────────────────────────────
# Retry decorator for rate limit errors
# ─────────────────────────────────────────────

def retry_on_rate_limit(max_retries=3, delays=None):
    """Retry decorator for rate limit errors (429). delays=[10,20,30] for fixed schedule."""
    from functools import wraps
    import time
    if delays is None:
        delays = [10, 20, 30]
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "rate_limit" in error_str.lower():
                        if attempt < max_retries:
                            wait = delays[attempt] if attempt < len(delays) else delays[-1]
                            print(f"[retry] Rate limit hit, retry {attempt+1}/{max_retries} after {wait}s")
                            time.sleep(wait)
                            continue
                    raise
            return None
        return wrapper
    return decorator

"""
Memory Eval Pipeline
====================
Agent 记忆系统评测框架

支持的 Memory 策略:
  - NoMemory       : 无记忆，纯上下文 baseline
  - FullHistory    : 全量历史 replay baseline
  - RAGMemory      : 向量检索记忆
  - Mem0Memory     : Mem0 记忆系统

评测数据集: LoCoMo-10
  下载: https://github.com/snap-research/locomo
  文件: data/locomo10.json

用法:
  python eval_pipeline.py --data locomo10.json --strategy all --model gpt-4o
  python eval_pipeline.py --data locomo10.json --strategy mem0 --model gpt-4o
  python eval_pipeline.py --data locomo10.json --strategy rag --top-k 5
"""

import json
import argparse
import time
import os
import re
import string
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from openai import OpenAI

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 没装 python-dotenv 时直接跳过，依赖环境变量

# MetaSkill strategy (optional import — skipped if meta-memory not available)
try:
    from meta_skill_strategy import MetaSkillStrategy
    _METASKILL_AVAILABLE = True
except ImportError:
    _METASKILL_AVAILABLE = False

# SrcMemory strategy (optional — wraps src/ MemoryService for fair comparison)
try:
    from src_memory_strategy import SrcMemoryStrategy
    _SRC_MEMORY_AVAILABLE = True
except ImportError:
    _SRC_MEMORY_AVAILABLE = False

# V1Memory strategy (optional — wraps src/ v0.1 hierarchical memory substrate)
try:
    from v1_memory_strategy import V1MemoryStrategy
    _V1_MEMORY_AVAILABLE = True
except ImportError:
    _V1_MEMORY_AVAILABLE = False

# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────

@dataclass
class Turn:
    speaker: str
    text: str
    session_idx: int
    session_date: str = ""   # session 的时间戳，如 "1:56 pm on 8 May, 2023"
    blip_caption: str = ""  # 图片的 BLIP 描述（无图片时为空）

@dataclass
class QA:
    question: str
    answer: str
    category: str          # single-hop / temporal / multi-hop / open-domain
    evidence_ids: list[str]

# LoCoMo category 映射（官方）
# 1:single-hop 2:temporal 3:multi-hop 4:open-domain 5:adversarial
CATEGORY_MAP = {1: "single-hop", 2: "temporal", 3: "multi-hop", 4: "open-domain", 5: "adversarial"}

@dataclass
class Conversation:
    sample_id: str
    turns: list[Turn]
    qa_list: list[QA]

@dataclass
class EvalResult:
    strategy_name: str
    sample_id: str
    category: str
    question: str
    reference: str
    prediction: str
    judge_score: float     # 0 ~ 1，由 LLM judge 给出
    f1_score: float        # token-level F1，与 LoCoMo 官方对齐
    latency_ms: float
    tokens_used: int
    arm_id: int = -1
    # No-leak Phase B (P-1): failure category from constrained vocabulary,
    # emitted only when judge_score < 1.0. Used by MetaOptimizer as a
    # production-realistic signal in place of raw gold-answer strings.
    failure_category: str = ""
    # Retrieval diagnostics (Option D): per-QA metrics exposed by the strategy
    # via ._last_retrieval_metrics. Empty dict if strategy does not expose it.
    retrieval_metrics: dict = field(default_factory=dict)

# ─────────────────────────────────────────────
# LoCoMo 数据加载
# ─────────────────────────────────────────────

def load_locomo(path: str) -> list[Conversation]:
    with open(path) as f:
        raw = json.load(f)

    conversations = []
    # locomo10.json 是一个 list，每个元素是一条长程对话
    if isinstance(raw, list):
        samples = raw
    else:
        # 有些版本是 dict，key 是 sample_id
        samples = list(raw.values())

    for sample in samples:
        sample_id = sample.get("sample_id", "unknown")

        # 解析对话轮次（多个 session）
        turns = []
        conversation = sample.get("conversation", {})
        # session 键名格式：session_1, session_2, ...
        session_keys = sorted(
            [k for k in conversation.keys() if k.startswith("session_") and not k.endswith("_date_time")],
            key=lambda x: int(x.split("_")[1])
        )
        for idx, sk in enumerate(session_keys):
            dt_key = sk + "_date_time"
            session_date = conversation.get(dt_key, "")
            for turn in conversation[sk]:
                speaker = turn.get("name", turn.get("speaker", "unknown"))
                text = turn.get("text", turn.get("dialog", ""))
                if text:
                    blip_caption = turn.get("blip_caption", "")
                    turns.append(Turn(speaker=speaker, text=text, session_idx=idx,
                                      session_date=session_date, blip_caption=blip_caption))

        # 解析 QA
        qa_list = []
        for qa in sample.get("qa", []):
            qa_list.append(QA(
                question=qa.get("question", ""),
                answer=str(qa.get("answer", "")),
                category=CATEGORY_MAP.get(qa.get("category", 0), str(qa.get("category", "unknown"))),
                evidence_ids=qa.get("evidence", []),
            ))

        conversations.append(Conversation(
            sample_id=sample_id,
            turns=turns,
            qa_list=qa_list,
        ))

    return conversations

# ─────────────────────────────────────────────
# Memory 策略基类
# ─────────────────────────────────────────────

class MemoryStrategy(ABC):
    """所有 memory 策略的统一接口"""

    @abstractmethod
    def reset(self):
        """开始新对话时清空状态"""
        ...

    @abstractmethod
    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        """记录一轮对话"""
        ...

    @abstractmethod
    def retrieve(self, query: str, client=None) -> str:
        """根据 query 检索相关记忆，返回拼入 prompt 的字符串"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

# ─────────────────────────────────────────────
# Baseline A: NoMemory
# ─────────────────────────────────────────────

class NoMemory(MemoryStrategy):
    """无任何外部记忆，只靠 retrieve 时传入的 query 本身"""

    @property
    def name(self): return "no_memory"

    def reset(self): pass

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""): pass

    def retrieve(self, query: str, client=None) -> str:
        return ""  # 完全没有上下文

# ─────────────────────────────────────────────
# Baseline B: FullHistory
# ─────────────────────────────────────────────

class FullHistory(MemoryStrategy):
    """把所有历史对话全量塞入 prompt，不做截断。依赖模型自身上下文窗口限制。"""

    def __init__(self):
        self.history: list[str] = []
        self._last_session_idx = -1

    @property
    def name(self): return "full_history"

    def reset(self):
        self.history = []
        self._last_session_idx = -1

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        # 每个 session 开头插入时间标记（对齐 LoCoMo 官方格式）
        if session_date and (not self.history or self._last_session_idx != session_idx):
            self.history.append(f"\n[{session_date}]")
            self._last_session_idx = session_idx
        # 对话格式：speaker said, "text" [and shared <blip>]（对齐官方 dialog 格式）
        entry = f'{speaker} said, "{text}"'
        if blip_caption:
            entry += f" and shared {blip_caption}"
        self.history.append(entry)

    def retrieve(self, query: str, client=None) -> str:
        full = "\n".join(self.history)
        return full

# ─────────────────────────────────────────────
# Baseline C: RAGMemory
# ─────────────────────────────────────────────

class RAGMemory(MemoryStrategy):
    """
    向量检索记忆 - session 级别 chunk + query 改写。
    改进：
    - chunk 粒度从单条 turn 改为 session 级别，语义更完整，temporal 题受益
    - 检索前用 LLM 将问题改写为更贴近对话内容的陈述句，提升召回
    - top_k 默认 3（session 级别粒度大，3 个 session 已足够）
    依赖: pip install sentence-transformers numpy
    """

    def __init__(self, top_k: int = 3, embedding_model: str = "/home/models/bge-large-en-v1.5",
                 chunk_turns: int = 0, disable_rewrite: bool = False, entry_format: str = "narrative",
                 sort_by_relevance: bool = False, separator: str = "\n\n"):
        self.top_k = top_k
        self.chunk_turns = chunk_turns  # 0 = session-level (original); >0 = N-turn sub-chunks
        self.disable_rewrite = disable_rewrite
        # "narrative" = 'Speaker said, "text"' (original); "compact" = "Speaker: text" (matches exhaustive)
        self.entry_format = entry_format
        # sort_by_relevance: if True, return chunks sorted by score (exhaustive behavior); else by time
        self.sort_by_relevance = sort_by_relevance
        self.separator = separator
        # session_idx -> list of turn strings
        self._session_turns: dict[int, list[str]] = {}
        self._session_dates: dict[int, str] = {}
        # 最终 chunks（reset 时清空）
        self.chunks: list[str] = []
        self.embeddings: list = []
        self._chunks_built = False
        try:
            from sentence_transformers import SentenceTransformer
            self._st_model = SentenceTransformer(embedding_model)
            print(f"[RAGMemory] loaded embedding model: {embedding_model}")
        except ImportError:
            raise ImportError("pip install sentence-transformers")

    @property
    def name(self):
        if self.chunk_turns > 0:
            return f"rag_{self.chunk_turns}turn_top{self.top_k}"
        return f"rag_session_top{self.top_k}"

    def reset(self):
        self._session_turns = {}
        self._session_dates = {}
        self.chunks = []
        self.embeddings = []
        self._chunks_built = False

    def _embed(self, text: str):
        return self._st_model.encode(text, normalize_embeddings=True).tolist()

    def _build_chunks(self):
        """把 session_turns 整合成 chunk 并做 embedding（只在第一次 retrieve 时触发）。
        chunk_turns=0: session 级别 (原始行为)；chunk_turns>0: N-turn 子块（消融用）"""
        self.chunks = []
        self.embeddings = []
        for idx in sorted(self._session_turns.keys()):
            date = self._session_dates.get(idx, "")
            turns = self._session_turns[idx]
            header = f"[{date}]" if date else f"[Session {idx}]"
            if self.chunk_turns > 0:
                for i in range(0, len(turns), self.chunk_turns):
                    sub = turns[i:i + self.chunk_turns]
                    chunk = header + "\n" + "\n".join(sub)
                    self.chunks.append(chunk)
                    self.embeddings.append(self._embed(chunk))
            else:
                chunk = header + "\n" + "\n".join(turns)
                self.chunks.append(chunk)
                self.embeddings.append(self._embed(chunk))
        self._chunks_built = True

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        # 按 session 分组收集 turn
        if session_idx not in self._session_turns:
            self._session_turns[session_idx] = []
            self._session_dates[session_idx] = session_date
        if self.entry_format == "compact":
            entry = f"{speaker}: {text}"
            if blip_caption:
                entry += f" and shared {blip_caption}"
        else:
            entry = f'{speaker} said, "{text}"'
            if blip_caption:
                entry += f" and shared {blip_caption}"
        self._session_turns[session_idx].append(entry)
        self._chunks_built = False  # 有新数据，需要重新 build

    def _rewrite_query(self, query: str, client) -> str:
        """用 LLM 把问题改写成更贴近对话内容的陈述句，提升 embedding 检索召回"""
        prompt = (
            "Rewrite the following question as a short declarative statement that "
            "describes what information to look for in a conversation. "
            "Output only the rewritten statement, no explanation.\n\n"
            f"Question: {query}\nStatement:"
        )
        try:
            resp = client.chat.completions.create(
                model="MiniMax-M2.5",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=128,
                temperature=0,
                timeout=30,
            )
            raw = resp.choices[0].message.content.strip()
            import re as _re
            # 剥离 think 标签
            cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
            return cleaned if cleaned else query
        except Exception:
            return query

    def retrieve(self, query: str, client=None) -> str:
        if not self._session_turns:
            return ""
        if not self._chunks_built:
            self._build_chunks()
        import numpy as np
        # query 改写
        search_query = self._rewrite_query(query, client) if (client and not self.disable_rewrite) else query
        q_emb = np.array(self._embed(search_query))
        scores = [
            np.dot(q_emb, np.array(e)) /
            (np.linalg.norm(q_emb) * np.linalg.norm(np.array(e)) + 1e-9)
            for e in self.embeddings
        ]
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:self.top_k]
        if self.sort_by_relevance:
            ordered = top_idx  # relevance-descending (matches exhaustive behavior)
        else:
            ordered = sorted(top_idx)  # 按时间顺序返回
        return self.separator.join(self.chunks[i] for i in ordered)

# ─────────────────────────────────────────────
# Baseline D: Mem0Memory
# ─────────────────────────────────────────────


CUSTOM_EXTRACTION_PROMPT = f"""You are a Personal Information Organizer, specialized in accurately storing facts, user memories, and preferences. Your primary role is to extract relevant pieces of information from conversations and organize them into distinct, manageable facts. This allows for easy retrieval and personalization in future interactions. Below are the types of information you need to focus on and the detailed instructions on how to handle the input data.

Types of Information to Remember:

1. Store Personal Preferences: Keep track of likes, dislikes, and specific preferences in various categories such as food, products, activities, and entertainment.
2. Maintain Important Personal Details: Remember significant personal information like names, relationships, and important dates.
3. Track Plans and Intentions: Note upcoming events, trips, goals, and any plans the user has shared.
4. Remember Activity and Service Preferences: Recall preferences for dining, travel, hobbies, and other services.
5. Monitor Health and Wellness Preferences: Keep a record of dietary restrictions, fitness routines, and other wellness-related information.
6. Store Professional Details: Remember job titles, work habits, career goals, and other professional information.
7. Miscellaneous Information Management: Keep track of favorite books, movies, brands, and other miscellaneous details that the user shares.

CRITICAL RULES:
- Each fact MUST include the person's name as the subject. Do NOT use "user" or "the person". Use their actual name (e.g., "Caroline", "Melanie").
- When timestamps like [1:56 pm on 8 May, 2023] appear in messages, use them to resolve relative dates. For example, "yesterday" on May 8 means May 7.
- Include specific dates in facts whenever possible.

Here are some few shot examples:

Input: [8 May, 2023] Caroline: Hi, how are you?
Output: {{{{"facts" : []}}}}

Input: [8 May, 2023] Caroline: I went to a LGBTQ support group yesterday and it was so powerful.
Output: {{{{"facts" : ["Caroline went to a LGBTQ support group on May 7, 2023 and found it powerful"]}}}}

Input: [8 May, 2023] Melanie: I started my new painting class last week.
Output: {{{{"facts" : ["Melanie started a new painting class around May 1, 2023"]}}}}

Input: [15 June, 2023] Caroline: My name is Caroline and I work as a teacher.
Output: {{{{"facts" : ["Caroline's name is Caroline", "Caroline works as a teacher"]}}}}

Input: [15 June, 2023] Melanie: I love hiking and my favourite movie is Inception.
Output: {{{{"facts" : ["Melanie loves hiking", "Melanie's favourite movie is Inception"]}}}}

Return the facts and preferences in a json format as shown above.

Remember the following:
- Today's date is {{datetime.now().strftime("%Y-%m-%d")}}.
- Do not return anything from the custom few shot example prompts provided above.
- If you do not find anything relevant in the below conversation, you can return an empty list corresponding to the "facts" key.
- Create the facts based on the user and assistant messages only. Do not pick anything from the system messages.
- Make sure to return the response in the format mentioned in the examples. The response should be in json with a key as "facts" and corresponding value will be a list of strings.
- ALWAYS include the person's name in each fact. Never use generic terms like "user" or "the person".
- ALWAYS resolve relative dates (yesterday, last week, etc.) to absolute dates using the timestamp prefix.

Following is a conversation between the user and the assistant. You have to extract the relevant facts and preferences from the conversation and return them in the json format as shown above.
"""

class Mem0Memory(MemoryStrategy):
    """
    Mem0 记忆系统 - 本地模式（MiniMax LLM + bge embedder）。
    依赖: pip install mem0ai
    使用 OPENAI_API_KEY / OPENAI_BASE_URL 环境变量指向 MiniMax API。
    改进：
    - 使用 Memory.from_config() 指定本地 LLM + bge-large embedder
    - observe() 只收集 turns，replay 结束后调 flush() 批量 add（session 级别）
    - reset() 真正删除旧 facts，避免跨对话污染
    """

    def __init__(self, user_id: str = "eval_user",
                 embedding_model: str = "/home/models/bge-large-en-v1.5"):
        import os
        self.user_id = user_id
        self._session_buffer: dict[int, list] = {}
        self.available = False
        try:
            from mem0 import Memory
            config = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": "MiniMax-M2.5",
                        "api_key": os.environ.get("OPENAI_API_KEY", ""),
                        "openai_base_url": os.environ.get("OPENAI_BASE_URL", ""),
                    }
                },
                "embedder": {
                    "provider": "huggingface",
                    "config": {
                        "model": embedding_model,
                    }
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "mem0_eval_bge1024",
                        "path": "/home/w00857628/memory-eval/qdrant_storage",
                        "on_disk": False,
                        "embedding_model_dims": 1024,
                    }
                },
                "custom_fact_extraction_prompt": CUSTOM_EXTRACTION_PROMPT,
            }
            self.mem = Memory.from_config(config)
            # Monkey-patch LLM generate_response to:
            # 1. Add reasoning_split=True so <think> goes to reasoning_details, not content
            # 2. Increase max_tokens to 4096 so thinking doesn't eat all output tokens
            self._patch_mem0_llm()
            self.available = True
            print(f"[Mem0Memory] initialized with MiniMax LLM + {embedding_model}")
        except ImportError:
            print("[Mem0Memory] mem0ai not installed. pip install mem0ai")
        except Exception as e:
            print(f"[Mem0Memory] init failed: {e}")

    @property
    def name(self): return "mem0"

    def reset(self):
        if not self.available:
            return
        # 真正删除旧 user 的 facts，避免跨对话污染
        old_uid = self.user_id
        self.user_id = f"eval_user_{int(time.time())}"
        self._session_buffer = {}
        try:
            self.mem.delete_all(user_id=old_uid)
        except Exception:
            pass

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        # 按官方方式：content 加人名前缀，存 session_date
        if not self.available:
            return
        content = text
        if blip_caption:
            content += f" [shared image: {blip_caption}]"
        # 格式："[session_date] {speaker_name}: {text}"
        if session_date:
            content = f"[{session_date}] {speaker}: {content}"
        else:
            content = f"{speaker}: {content}"
        # 确定 role：speaker_a -> user, speaker_b -> assistant
        if session_idx not in self._session_buffer:
            self._session_buffer[session_idx] = {"messages": [], "date": session_date, "speakers": set()}
        self._session_buffer[session_idx]["speakers"].add(speaker)
        speakers = sorted(self._session_buffer[session_idx]["speakers"])
        # 第一个出现的 speaker 是 user，第二个是 assistant
        if len(speakers) <= 1 or speaker == speakers[0]:
            role = "user"
        else:
            role = "assistant"
        self._session_buffer[session_idx]["messages"].append(
            {"role": role, "content": content}
        )

    def _patch_mem0_llm(self):
        """Patch Mem0's internal LLM to use reasoning_split=True and higher max_tokens."""
        import re as _re
        try:
            llm = self.mem.llm
            original_generate = llm.generate_response

            def patched_generate(messages, response_format=None, tools=None, tool_choice="auto", **kwargs):
                # Inject reasoning_split and bump max_tokens
                kwargs["extra_body"] = {"reasoning_split": True}
                kwargs["max_tokens"] = 128000
                # Retry up to 3 times on empty response (MiniMax API occasional empty returns)
                for attempt in range(3):
                    result = original_generate(
                        messages=messages,
                        response_format=response_format,
                        tools=tools,
                        tool_choice=tool_choice,
                        **kwargs,
                    )
                    # Strip any residual <think> tags (safety net)
                    if isinstance(result, str):
                        result = _re.sub(r"<think>.*?</think>", "", result, flags=_re.DOTALL).strip()
                    if result and result.strip():
                        return result
                    print(f"[Mem0Memory] empty response from LLM (attempt {attempt+1}/3), msg count={len(messages)}")
                    import time as _time
                    _time.sleep(2)
                print(f"[Mem0Memory] WARNING: all 3 attempts returned empty, msg count={len(messages)}")
                return result

            llm.generate_response = patched_generate
            print("[Mem0Memory] LLM patched: reasoning_split=True, max_tokens=4096")
        except Exception as e:
            print(f"[Mem0Memory] LLM patch failed: {e}")

    def flush(self):
        """按官方方式：batch_size=2, 带 timestamp metadata"""
        if not self.available or not self._session_buffer:
            return
        total_sessions = len(self._session_buffer)
        batch_size = 2
        total_batches = 0
        total_facts = 0
        for i, idx in enumerate(sorted(self._session_buffer.keys())):
            buf = self._session_buffer[idx]
            messages = buf["messages"]
            session_date = buf["date"]
            session_turns = len(messages)
            added_count = 0
            # 按 batch_size=2 分批 add（官方方式）
            for j in range(0, session_turns, batch_size):
                batch = messages[j:j+batch_size]
                try:
                    import time as _t0
                    _t1 = _t0.time()
                    result = self.mem.add(
                        messages=batch,
                        user_id=self.user_id,
                        metadata={"timestamp": session_date} if session_date else None,
                    )
                    _elapsed = _t0.time() - _t1
                    n_res = len(result.get("results", []) if isinstance(result, dict) else result)
                    print(f"[Mem0Memory] session {i+1}/{total_sessions} batch {j//batch_size+1}: {n_res} facts, {_elapsed:.1f}s")
                    added_count += n_res
                except Exception as e:
                    print(f"[Mem0Memory] session {i+1} batch {j//batch_size+1} error: {e}")
                total_batches += 1
            total_facts += added_count
            print(f"[Mem0Memory] flush session {i+1}/{total_sessions} (idx={idx}, turns={session_turns}): {added_count} facts extracted")
        self._session_buffer = {}
        print(f"[Mem0Memory] flush complete: {total_batches} batches, {total_facts} facts across {total_sessions} sessions")

    def retrieve(self, query: str, client=None) -> str:
        if not self.available:
            return ""
        try:
            results = self.mem.search(query=query, user_id=self.user_id, limit=5)
            results_list = results.get('results', []) if isinstance(results, dict) else results
            print(f"[Mem0Memory] search for '{query[:30]}...': {len(results_list)} results")
            for i, r in enumerate(results_list):
                mem_text = r.get('memory', r.get('text', str(r)))[:150]
                print(f"[Mem0Memory]   result {i}: {mem_text}")
        except Exception as e:
            print(f"[Mem0Memory] search error: {e}")
            return ""
        if not results:
            return ""
        # mem0ai 1.x 返回 {"results": [...]}，兼容旧版 list
        memories = results.get("results", results) if isinstance(results, dict) else results
        return "\n".join(
            m.get("memory", m.get("text", str(m))) for m in memories
        )

# ─────────────────────────────────────────────
# Agent Loop（固定，不随 memory 变化）
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful assistant. You will be given relevant memory context from a conversation (if available), followed by a question. Answer the question based on the memory context.

CRITICAL: Answer ONLY from information EXPLICITLY stated in the memory context.
- The SPECIFIC DETAIL asked must be directly present in the context — it is NOT enough that the general topic or person is mentioned.
- If related information is present but the exact answer is not stated, respond with ONLY "I don't know".
- You may combine multiple explicitly stated facts to answer (e.g., finding what two people have in common).
- Do NOT infer, guess, or extrapolate details that are not written in the context.
- Do NOT invent events, dates, or facts that are not directly referenced in the provided memory.

When answering about dates or times, compute absolute dates from relative expressions (yesterday, last week, next month, etc.) using the [YYYY-MM-DD] date shown at the start of each memory segment. This date computation is part of answering correctly, not inventing information.
Answer concisely in plain natural language. Do not output anything extra."""

# V5: Separate prompt for inference-type multi-hop ("Would X do Y?")
# These questions require reasoning from stated facts rather than direct lookup.
# The strict "Do NOT infer" rule breaks them — they NEED inference to answer correctly.
SYSTEM_PROMPT_INFERENCE = """You are a helpful assistant. You will be given relevant memory context from a conversation (if available), followed by a question. Answer the question based on the memory context.

Answer based on the memory context. You may reason from explicitly stated facts to answer questions about what someone would likely do, feel, or experience (e.g., "Would X pursue Y given Z?"). Combine stated facts and preferences to infer reasonable answers.
If NO relevant information about the person or topic is in the context, respond with ONLY "I don't know".
Do NOT invent facts — base all reasoning on what is explicitly written in the context.

When answering about dates or times, compute absolute dates from relative expressions (yesterday, last week, next month, etc.) using the [YYYY-MM-DD] date shown at the start of each memory segment.
Answer concisely in plain natural language. Do not output anything extra."""

# O4: Confidence-gated IDK instruction (replaces O1 blanket IDK)
_IDK_INSTRUCTION = 'If the question asks about something not present in the provided memory context, respond with ONLY "I don\'t know".'
_O4_COSINE_THRESHOLD = 0.45   # for non-CE arms (cosine similarity)
_O4_TEMPORAL_THRESHOLD = 0.25 # lower threshold for temporal queries (dates have low cosine sim)
_O4_MULTIHOP_THRESHOLD = -1.0 # V5: inference queries — NEVER add IDK (entity context always relevant)
_O4_CE_THRESHOLD = 0.0        # for CE arms (cross-encoder logit; <0 means <50% relevance)
_O5B_CE_THRESHOLD = 0.0      # O5b: CE answerability gate threshold (logit < 0 → IDK instruction)

import re as _re
def _is_temporal_query(q: str) -> bool:
    return bool(_re.search(r'\b(when|what date|what time|how long ago|which year|which month|which day|how old|since when)\b', q.lower()))

def _is_multihop_inference_query(q: str) -> bool:
    """Detect multi-hop inference questions that require reasoning from context."""
    q_lower = q.lower().strip()
    return (
        q_lower.startswith("would ") or
        q_lower.startswith("is it likely") or
        _re.search(r"\bwould .+\b(be|have|likely|consider|pursue|want)\b", q_lower) is not None or
        "be considered" in q_lower or
        "likely to" in q_lower
    )

class AgentLoop:
    def __init__(self, memory: MemoryStrategy, model: str = "MiniMax-M2.5",
                 answer_base_url: str = "", answer_api_key: str = ""):
        self.memory = memory
        self.model = model
        # If separate answer model API provided, create dedicated client
        if answer_base_url and answer_api_key:
            self.client = OpenAI(base_url=answer_base_url, api_key=answer_api_key)
            self._is_glm = "glm" in model.lower()
        else:
            self.client = OpenAI()
            self._is_glm = False
        self.total_tokens = 0

    def replay_conversation(self, turns: list[Turn], max_sessions: int = 9999):
        """重放对话历史，让 memory 系统学习"""
        self.memory.reset()
        for turn in turns:
            if turn.session_idx < max_sessions:
                self.memory.observe(turn.speaker, turn.text, turn.session_date, turn.session_idx, turn.blip_caption)
        # Mem0Memory: observe only collects turns, flush() batch-adds after replay
        if hasattr(self.memory, "flush"):
            self.memory.flush()

    def answer(self, question: str) -> tuple[str, float, int, int]:
        """回答一个 probe 问题，返回 (answer, latency_ms, tokens, arm_id)"""
        # RAGMemory supports client param for query rewriting; others ignore it
        if hasattr(self.memory, "_rewrite_query"):
            context = self.memory.retrieve(question, client=self.client)
        else:
            context = self.memory.retrieve(question)

        # Capture arm_id after retrieve
        arm_id = getattr(self.memory, '_last_arm_id_used', -1)

        # V5: category-aware system prompt — inference queries use permissive prompt
        is_inference = _is_multihop_inference_query(question)
        active_system_prompt = SYSTEM_PROMPT_INFERENCE if is_inference else SYSTEM_PROMPT

        # O5b: CE answerability gate (preferred, takes precedence over O4 cosine gate).
        # CE score (MS-MARCO logit) measures "does this chunk directly answer the question?"
        # Catches partial-topic adversarial failures: entity context is present (high cosine)
        # but specific event is NOT in the conversation (low CE answerability).
        if hasattr(self.memory, 'get_ce_answerability') and not is_inference:
            ce_score = self.memory.get_ce_answerability()
            if ce_score is not None and ce_score < _O5B_CE_THRESHOLD:
                active_system_prompt = SYSTEM_PROMPT + "\n" + _IDK_INSTRUCTION
        # O4: cosine-confidence IDK gate fallback (used when O5b CE model unavailable)
        elif hasattr(self.memory, 'get_retrieval_confidence') and not is_inference:
            conf = self.memory.get_retrieval_confidence()
            arm_id = getattr(self.memory, '_last_arm_id_used', None)
            is_ce_arm = arm_id is not None and arm_id >= 3
            if _is_temporal_query(question):
                cosine_thresh = _O4_TEMPORAL_THRESHOLD
            else:
                cosine_thresh = _O4_COSINE_THRESHOLD
            threshold = _O4_CE_THRESHOLD if is_ce_arm else cosine_thresh
            if conf < threshold:
                active_system_prompt = SYSTEM_PROMPT + "\n" + _IDK_INSTRUCTION

        messages = [{"role": "system", "content": active_system_prompt}]
        if context:
            messages.append({
                "role": "user",
                "content": f"[Memory Context]\n{context}\n\n[Question]\n{question}"
            })
        else:
            messages.append({"role": "user", "content": f"[Question]\n{question}"})

        t0 = time.time()
        create_kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=1024,
            timeout=60,
        )
        if self._is_glm:
            # Disable thinking mode for GLM-4.7
            create_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        @retry_on_rate_limit(max_retries=3, delays=[2, 5, 10])
        def _call_llm():
            return self.client.chat.completions.create(**create_kwargs)
        resp = _call_llm()
        latency_ms = (time.time() - t0) * 1000
        tokens = resp.usage.total_tokens
        self.total_tokens += tokens
        raw = resp.choices[0].message.content.strip()
        # 去掉 <think>...</think> 推理过程，只保留最终答案
        import re as _re
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        prediction = cleaned if cleaned else raw
        return prediction, latency_ms, tokens, arm_id

# ─────────────────────────────────────────────
# LLM Judge
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
# Token-level F1（与 LoCoMo 官方对齐）
# ─────────────────────────────────────────────

def _normalize_answer(s: str) -> str:
    """小写、去标点、去冠词、去多余空格"""
    s = str(s)
    s = unicodedata.normalize("NFD", s)
    s = s.lower()
    s = s.replace(",", "")
    # 去标点
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    # 去冠词
    s = re.sub(r"\b(a|an|the|and)\b", " ", s)
    # 合并空格
    s = " ".join(s.split())
    return s


def compute_f1(prediction: str, reference: str) -> float:
    """
    计算 token-level F1，与 LoCoMo 官方 evaluation.py 对齐。
    F1 = 2 * precision * recall / (precision + recall)
    """
    pred_tokens = _normalize_answer(prediction).split()
    ref_tokens = _normalize_answer(reference).split()
    if not pred_tokens or not ref_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(ref_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(ref_tokens)
    return (2 * precision * recall) / (precision + recall)

JUDGE_PROMPT = """Score the prediction against the reference answer. Output only a number: 0.0, 0.5, or 1.0.

Rules:
- 1.0: Prediction is semantically correct (e.g. "May 7, 2023" = "7 May 2023", minor wording OK)
- 0.5: Prediction is partially correct (contains some but not all key info)
- 0.0: Prediction is wrong, irrelevant, or says "I don't know" / "no information" / "not provided"

Important: If the prediction says it does not know or has no information, score is always 0.0.

Question: {question}
Reference: {reference}
Prediction: {prediction}

Score (0.0, 0.5, or 1.0):"""

# No-leak Phase B (P-1): judge prompt that also emits a constrained-vocabulary
# failure_category. Optimizer downstream sees ONLY the category name — never the
# reference string — so gold-answer leakage is prevented by construction.
JUDGE_PROMPT_WITH_COMMENTARY = """Score the prediction against the reference answer AND categorize any failure. Output ONLY a valid JSON object — no prose, no markdown.

Scoring rules:
- 1.0: Prediction is semantically correct (e.g. "May 7, 2023" = "7 May 2023", minor wording OK)
- 0.5: Prediction is partially correct (contains some but not all key info)
- 0.0: Prediction is wrong, irrelevant, or says "I don't know" / "no information" / "not provided"

If score < 1.0, ALSO return failure_category from this FIXED vocabulary (do NOT invent new ones):
- retrieval_miss: system failed to retrieve the relevant context at all
- grounding_error: retrieved context exists but answer not anchored to it
- temporal_misalignment: wrong date/time reference (e.g. predicted wrong month/year)
- aggregation_incomplete: partial answer — missing one or more required elements
- reasoning_error: context present but wrong inference / wrong hop
- hallucination: prediction is a specific fabricated answer unsupported by context
- ambiguous: failure type unclear

If score == 1.0, set failure_category to null.

CRITICAL LEAKAGE CONSTRAINTS — your output is consumed by an automated optimizer that must NEVER see the gold answer:
- Do NOT repeat or paraphrase the reference answer anywhere in your output.
- Do NOT mention specific entities, names, dates, numbers, or places from the reference.
- Do NOT explain "the correct answer is …" — only emit the category token.
- Output ONLY the fixed JSON schema; any extra prose risks leaking gold information.

Question: {question}
Reference: {reference}
Prediction: {prediction}

Output JSON (no other text):
{{"score": 0.0|0.5|1.0, "failure_category": "<one-of-vocab-or-null>"}}"""

# adversarial 类别专用 prompt：
# 标准答案是空字符串——这类问题在对话里根本没有答案
# 模型回答 "I don't know" / "not mentioned" / "no information" 应该得满分
# 模型编造出一个具体答案应该得 0 分
JUDGE_PROMPT_ADVERSARIAL = """This question has NO correct answer in the conversation. Do not think, do not explain. Output only the number.

- 1.0: Prediction says it doesn't know / not mentioned / no information
- 0.5: Prediction is vague or uncertain
- 0.0: Prediction gives a specific fabricated answer

Question: {question}
Prediction: {prediction}

Output only: 0.0, 0.5, or 1.0"""

JUDGE_PROMPT_ADVERSARIAL_WITH_COMMENTARY = """This question has NO correct answer in the conversation. Score the prediction and (if it failed) emit a failure_category.

- 1.0: Prediction says it doesn't know / not mentioned / no information
- 0.5: Prediction is vague or uncertain
- 0.0: Prediction gives a specific fabricated answer (hallucination)

If score < 1.0, failure_category must be one of: hallucination, grounding_error, ambiguous.
If score == 1.0, failure_category is null.

CRITICAL: Do NOT mention specific entities/dates/names; do NOT explain the correct answer.
Output ONLY JSON — no prose, no markdown.

Question: {question}
Prediction: {prediction}

Output: {{"score": 0.0|0.5|1.0, "failure_category": "<category-or-null>"}}"""

# Allowed failure categories (enforced server-side — any deviation falls back
# to "ambiguous" so optimizer never sees free-form judge text).
_ALLOWED_FAILURE_CATEGORIES = {
    "retrieval_miss",
    "grounding_error",
    "temporal_misalignment",
    "aggregation_incomplete",
    "reasoning_error",
    "hallucination",
    "ambiguous",
}

class LLMJudge:
    def __init__(self, model: str = "MiniMax-M2.5", emit_commentary: bool = False):
        # Auto-select API config: GLM models use GLM_BASE_URL/GLM_API_KEY,
        # others fall back to OPENAI_* env vars.
        if "glm" in model.lower():
            _base_url = os.environ.get("GLM_BASE_URL", "")
            _api_key = os.environ.get("GLM_API_KEY", "")
            self.client = OpenAI(base_url=_base_url, api_key=_api_key) if _base_url else OpenAI()
        else:
            self.client = OpenAI()
        self.model = model
        # No-leak Phase B: when True, judge emits structured failure_category
        # from a fixed vocabulary alongside the score, with strict prompt-level
        # constraints against leaking gold answer contents.
        self.emit_commentary = emit_commentary

    def score(
        self, question: str, reference: str, prediction: str, category: str = ""
    ) -> float | tuple[float, str]:
        """Score a prediction.

        Returns:
            float when emit_commentary=False (legacy behavior)
            (score, failure_category) when emit_commentary=True.
            failure_category is "" for score==1.0 or when classification fails.
        """
        if self.emit_commentary:
            return self._score_with_commentary(question, reference, prediction, category)
        return self._score_plain(question, reference, prediction, category)

    def _score_plain(self, question: str, reference: str, prediction: str, category: str) -> float:
        if category == "adversarial":
            prompt = JUDGE_PROMPT_ADVERSARIAL.format(
                question=question,
                prediction=prediction,
            )
        else:
            prompt = JUDGE_PROMPT.format(
                question=question,
                reference=reference,
                prediction=prediction,
            )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4096,  # thinking 模型 <think> 内容可能很长
            timeout=90,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip <think>...</think> and extract score
        import re as _re
        # Step 1: strip complete <think>...</think> block, then search
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        match = _re.search(r"\b(1\.0|0\.5|0\.0)\b", cleaned)
        if match:
            return float(match.group(1))
        # Step 2: <think> not closed (truncated output) — take LAST number in raw
        matches = _re.findall(r"\b(1\.0|0\.5|0\.0)\b", raw)
        if matches:
            return float(matches[-1])
        # Failed
        print(f"    [judge warn] cannot parse score: {raw[:80]!r}")
        return 0.0

    def _score_with_commentary(
        self, question: str, reference: str, prediction: str, category: str
    ) -> tuple[float, str]:
        """Score + constrained-vocabulary failure_category (no-leak mode)."""
        import re as _re

        if category == "adversarial":
            prompt = JUDGE_PROMPT_ADVERSARIAL_WITH_COMMENTARY.format(
                question=question,
                prediction=prediction,
            )
        else:
            prompt = JUDGE_PROMPT_WITH_COMMENTARY.format(
                question=question,
                reference=reference,
                prediction=prediction,
            )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4096,
            timeout=90,
        )
        raw = resp.choices[0].message.content.strip()
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()

        # Try structured parse first — we REQUIRE JSON.
        score_val: float | None = None
        failure_cat: str = ""
        json_match = _re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                s_raw = parsed.get("score")
                if isinstance(s_raw, (int, float)):
                    s_f = float(s_raw)
                    if s_f in (0.0, 0.5, 1.0):
                        score_val = s_f
                fc_raw = parsed.get("failure_category")
                if isinstance(fc_raw, str) and fc_raw in _ALLOWED_FAILURE_CATEGORIES:
                    failure_cat = fc_raw
                elif fc_raw in (None, "", "null"):
                    failure_cat = ""
                else:
                    # Judge drifted off vocabulary — coerce to "ambiguous" to
                    # prevent any free-form string from reaching the optimizer.
                    failure_cat = "ambiguous"
            except json.JSONDecodeError:
                pass

        # Fallback: bare number (same as plain path) when JSON parse failed.
        if score_val is None:
            match = _re.search(r"\b(1\.0|0\.5|0\.0)\b", cleaned)
            if match:
                score_val = float(match.group(1))
            else:
                matches = _re.findall(r"\b(1\.0|0\.5|0\.0)\b", raw)
                if matches:
                    score_val = float(matches[-1])
                else:
                    print(f"    [judge warn] cannot parse JSON or score: {raw[:100]!r}")
                    score_val = 0.0

        # Enforce: score 1.0 ⇒ no failure_category; score < 1.0 ⇒ require one.
        if score_val >= 1.0:
            failure_cat = ""
        elif not failure_cat:
            failure_cat = "ambiguous"

        return score_val, failure_cat

# ─────────────────────────────────────────────
# 评测主流程
# ─────────────────────────────────────────────

def run_eval(
    conversations: list[Conversation],
    strategies: list[MemoryStrategy],
    model: str = "MiniMax-M2.5",
    judge_model: str = "MiniMax-M2.5",
    max_qa_per_conv: int = 20,
    categories: Optional[list[str]] = None,
    max_sessions: int = 9999,
    answer_base_url: str = "",
    answer_api_key: str = "",
) -> list[EvalResult]:

    # No-leak Phase B: when NO_LEAK=1 env is set, judge emits a constrained-vocab
    # failure_category so the MetaOptimizer runner can build gold-free prompts.
    _no_leak_mode = os.environ.get("NO_LEAK", "0") == "1"
    judge = LLMJudge(model=judge_model, emit_commentary=_no_leak_mode)
    if _no_leak_mode:
        print("  [NO_LEAK=1] judge will emit constrained-vocab failure_category")
    all_results: list[EvalResult] = []

    for strategy in strategies:
        print(f"\n{'='*50}")
        print(f"策略: {strategy.name}")
        print(f"{'='*50}")
        agent = AgentLoop(memory=strategy, model=model, answer_base_url=answer_base_url, answer_api_key=answer_api_key)

        for conv in conversations:
            print(f"\n  对话: {conv.sample_id}（{len(conv.turns)} 轮, {len(conv.qa_list)} 个 QA）")

            # 重放对话历史
            agent.replay_conversation(conv.turns, max_sessions=max_sessions)

            # 筛选要测的 QA
            qa_subset = conv.qa_list
            if categories:
                qa_subset = [q for q in qa_subset if q.category in categories]
            qa_subset = qa_subset[:max_qa_per_conv]

            _global_q_idx = len(all_results)  # running question index across all convs
            for i, qa in enumerate(qa_subset):
                try:
                    prediction, latency_ms, tokens, arm_id = agent.answer(qa.question)
                except Exception as e:
                    print(f"    [answer error] {type(e).__name__}: {str(e)[:60]}, skipping")
                    prediction, latency_ms, tokens, arm_id = "", 0.0, 0, -1

                # Feed answer back to strategy for Bandit reward
                if hasattr(agent.memory, 'record_feedback'):
                    agent.memory.record_feedback(prediction)

                failure_category = ""
                try:
                    judge_out = judge.score(qa.question, qa.answer, prediction, category=qa.category)
                    if isinstance(judge_out, tuple):
                        score, failure_category = judge_out
                    else:
                        score = judge_out
                except Exception as e:
                    print(f"    [judge error] {type(e).__name__}: {str(e)[:60]}, defaulting 0.0")
                    score = 0.0

                f1 = compute_f1(prediction, qa.answer)

                # Online reward feedback for adaptive strategies
                if hasattr(strategy, 'update_reward'):
                    strategy.update_reward(qa.question, score)

                # Option D: capture per-QA retrieval metrics if the strategy
                # exposed them during retrieve(). Strategy-agnostic — any
                # strategy that sets _last_retrieval_metrics will contribute.
                retrieval_metrics = dict(getattr(strategy, "_last_retrieval_metrics", {}) or {})

                result = EvalResult(
                    strategy_name=strategy.name,
                    sample_id=conv.sample_id,
                    category=qa.category,
                    question=qa.question,
                    reference=qa.answer,
                    prediction=prediction,
                    judge_score=score,
                    f1_score=f1,
                    latency_ms=latency_ms,
                    tokens_used=tokens,
                    arm_id=arm_id if arm_id is not None else -1,
                    failure_category=failure_category,
                    retrieval_metrics=retrieval_metrics,
                )
                all_results.append(result)

                # Bandit snapshot every 50 questions
                question_index = _global_q_idx + i
                if (question_index % 50 == 0) and hasattr(strategy, 'get_bandit_snapshot'):
                    snapshot = strategy.get_bandit_snapshot()
                    snapshot['index'] = question_index
                    snapshot['timestamp'] = time.time()
                    os.makedirs('results', exist_ok=True)
                    with open('results/bandit_evolution.jsonl', 'a') as f:
                        f.write(json.dumps(snapshot) + '\n')

                status = "✓" if score >= 0.5 else "✗"
                print(f"    [{i+1}/{len(qa_subset)}] {status} judge={score:.1f} f1={f1:.2f} arm={arm_id} [{qa.category}] {qa.question[:40]}...")

    return all_results

# ─────────────────────────────────────────────
# 结果汇总
# ─────────────────────────────────────────────

def summarize(results: list[EvalResult]):
    from collections import defaultdict

    # 按策略 + 类别汇总
    stats: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for r in results:
        stats[r.strategy_name]["all"].append(r)
        stats[r.strategy_name][r.category].append(r)

    print(f"\n{'='*60}")
    print("评测结果汇总")
    print(f"{'='*60}")

    for strategy_name, cat_results in stats.items():
        print(f"\n【{strategy_name}】")
        all_r = cat_results["all"]
        avg_judge = sum(r.judge_score for r in all_r) / len(all_r)
        avg_f1 = sum(r.f1_score for r in all_r) / len(all_r)
        avg_latency = sum(r.latency_ms for r in all_r) / len(all_r)
        total_tokens = sum(r.tokens_used for r in all_r)

        print(f"  总体: judge={avg_judge:.3f} f1={avg_f1:.3f} | 延迟: {avg_latency:.0f}ms | Tokens: {total_tokens}")

        for cat in ["single-hop", "temporal", "multi-hop", "open-domain", "adversarial"]:
            cat_r = cat_results.get(cat, [])
            if cat_r:
                cat_judge = sum(r.judge_score for r in cat_r) / len(cat_r)
                cat_f1 = sum(r.f1_score for r in cat_r) / len(cat_r)
                print(f"  {cat:<15}: judge={cat_judge:.3f} f1={cat_f1:.3f}  (n={len(cat_r)})")

    return stats

def save_results(results: list[EvalResult], output_path: str):
    data = [
        {
            "strategy": r.strategy_name,
            "sample_id": r.sample_id,
            "category": r.category,
            "question": r.question,
            "reference": r.reference,
            "prediction": r.prediction,
            "judge_score": r.judge_score,
            "f1_score": r.f1_score,
            "latency_ms": r.latency_ms,
            "tokens_used": r.tokens_used,
            "arm_id": r.arm_id,
            "failure_category": r.failure_category,
            "retrieval_metrics": r.retrieval_metrics,
        }
        for r in results
    ]
    with open(output_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_path}")

# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

# Baseline E: MemOS (MemTensor/MemOS self-hosted)
# ─────────────────────────────────────────────

class MemOSStrategy(MemoryStrategy):
    """
    MemTensor/MemOS self-hosted adapter for eval_pipeline.
    
    API base: http://localhost:18001
    Requires: Neo4j (graph memory) + Qdrant (vector search) + embedding server (port 8002)
    LLM: MiniMax M2.5 (via .env OPENAI_BASE_URL)
    Embedding: bge-large-en-v1.5 (via local embedding server)
    """

    def __init__(self, user_id: str = "eval_user", api_base: str = "http://localhost:18001"):
        self.user_id = user_id
        self.api_base = api_base
        self._session_buffer: dict[int, list] = {}
        self.available = False
        self._checked = False

    def _ensure_available(self):
        if self._checked:
            return
        self._checked = True
        try:
            import requests
            # MemOS 没有 /health，用 /docs 检查服务是否可达
            r = requests.get(f"{self.api_base}/docs", timeout=5)
            if r.status_code == 200:
                self.available = True
                print(f"[MemOSStrategy] connected to {self.api_base}")
            else:
                print(f"[MemOSStrategy] service check failed: {r.status_code}")
        except Exception as e:
            print(f"[MemOSStrategy] unavailable: {e}")

    @property
    def name(self):
        return "memos"

    def reset(self):
        self._ensure_available()
        if not self.available:
            return
        # 换新 user_id + 删除旧 user 数据，实现跨对话隔离
        old_uid = self.user_id
        self._session_buffer = {}
        try:
            import requests
            # Use clear_user endpoint to properly clean Neo4j + Qdrant
            resp = requests.post(
                f"{self.api_base}/product/clear_user",
                json={"user_name": old_uid},
                timeout=30
            )
            if resp.status_code == 200:
                print(f"[MemOSStrategy] reset: cleared all data for {old_uid}, now using {self.user_id}")
            else:
                print(f"[MemOSStrategy] reset: clear_user returned {resp.status_code} - manual cleanup may be needed")
        except Exception as e:
            print(f"[MemOSStrategy] reset delete error: {e}")

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        if not self.available:
            self._ensure_available()
        if not self.available:
            return
        content = text
        if blip_caption:
            content += f" [shared image: {blip_caption}]"
        if session_date:
            content = f"[{session_date}] {speaker}: {content}"
        else:
            content = f"{speaker}: {content}"
        if session_idx not in self._session_buffer:
            self._session_buffer[session_idx] = {"messages": [], "date": session_date}
        self._session_buffer[session_idx]["messages"].append(content)

    def flush(self):
        """批量添加：将每个 session 的 messages 作为 conversation 添加到 MemOS"""
        if not self.available or not self._session_buffer:
            return
        import requests
        total_sessions = len(self._session_buffer)
        total_added = 0
        for i, idx in enumerate(sorted(self._session_buffer.keys())):
            buf = self._session_buffer[idx]
            messages = buf["messages"]
            if not messages:
                continue
            # MemOS add 需要 messages 格式：[{"role": "user"/"assistant", "content": ...}]
            # 假设第一个出现的 speaker 是 user，其余是 assistant
            api_messages = []
            session_speakers = set()
            for msg in messages:
                # msg 格式: "[date] Speaker: content" 或 "Speaker: content"
                # 提取 speaker name 用于判断 role，但 content 保留完整原文（含日期）
                parts = msg.split(": ", 1)
                speaker = parts[0].replace("[", "").replace("]", "").split()[-1] if ":" in msg else "user"
                session_speakers.add(speaker)
                sorted_speakers = sorted(session_speakers)
                role = "user" if (len(sorted_speakers) <= 1 or speaker == sorted_speakers[0]) else "assistant"
                # 保留完整 msg 作为 content，让 MemOS LLM 能看到日期
                api_messages.append({"role": role, "content": msg})
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    t0 = time.time()
                    resp = requests.post(
                        f"{self.api_base}/product/add",
                        json={
                            "user_id": self.user_id,
                            "messages": api_messages,
                            "async_mode": "sync",
                        },
                        timeout=600,
                    )
                    elapsed = time.time() - t0
                    if resp.status_code == 200:
                        data = resp.json()
                        n_added = len(data.get("data", []))
                        total_added += n_added
                        print(f"[MemOSStrategy] session {i+1}/{total_sessions}: {n_added} memories, {elapsed:.1f}s")
                        break  # success
                    else:
                        print(f"[MemOSStrategy] session {i+1} error (attempt {attempt}/{max_retries}): {resp.status_code} {resp.text[:100]}")
                        if attempt < max_retries:
                            time.sleep(5)
                except Exception as e:
                    print(f"[MemOSStrategy] session {i+1} add error (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(10)
        self._session_buffer = {}
        print(f"[MemOSStrategy] flush complete: {total_added} total memories across {total_sessions} sessions")

        # Trigger reorganization (build tree structure) after all sessions are flushed
        try:
            print(f"[MemOSStrategy] triggering reorganization...")
            t0 = time.time()
            resp = requests.post(
                f"{self.api_base}/product/reorganize",
                json={"user_id": self.user_id, "scope": "all"},
                timeout=600,  # reorganize can take a while with LLM calls
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                print(f"[MemOSStrategy] reorganization completed in {elapsed:.1f}s: {resp.json()}")
            else:
                print(f"[MemOSStrategy] reorganization failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[MemOSStrategy] reorganization error (non-fatal): {e}")

    def retrieve(self, query: str, client=None) -> str:
        if not self.available:
            self._ensure_available()
        if not self.available:
            return ""
        try:
            import requests
            resp = requests.post(
                f"{self.api_base}/product/search",
                json={
                    "query": query,
                    "user_id": self.user_id,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[MemOSStrategy] search error: {resp.status_code}")
                return ""
            data = resp.json()
            memories = []
            result_data = data.get("data", {})
            # 收集所有类型的 memory text
            for key in ["text_mem", "act_mem", "para_mem", "pref_mem"]:
                for cube_data in result_data.get(key, []):
                    for mem in cube_data.get("memories", []):
                        text = mem.get("memory", "")
                        if text:
                            memories.append(text)
            n_results = len(memories)
            print(f"[MemOSStrategy] search for '{query[:40]}': {n_results} results")
            for i, m in enumerate(memories[:5]):
                print(f"[MemOSStrategy]   [{i}]: {m[:120]}")
            return "\n\n".join(memories)
        except Exception as e:
            print(f"[MemOSStrategy] retrieve error: {e}")
            return ""



class OpenVikingStrategy(MemoryStrategy):
    """
    OpenViking (ByteDance/Volcengine) adapter for eval_pipeline.
    
    Uses local embedding server (bge-large-en-v1.5, port 8002)
    and MiniMax M2.5 as VLM for memory extraction.
    
    Storage: ~/memory-eval/openviking_workspace
    """

    def __init__(self, user_id: str = "eval_user", workspace: str = "",
                 embedding_api_base: str = "http://localhost:8002/v1",
                 vlm_api_base: str = "https://api.minimaxi.com/v1",
                 vlm_api_key: str = "", vlm_model: str = "MiniMax-M2.5"):
        self.user_id = user_id
        self.ov_module = None  # lazy import
        self.workspace = workspace or "/home/w00857628/memory-eval/openviking_workspace"
        self.embedding_api_base = embedding_api_base
        self.vlm_api_base = vlm_api_base
        self.vlm_api_key = vlm_api_key
        self.vlm_model = vlm_model
        self._client = None
        self._session = None
        self._conv_id = ""
        self._available = False
        self._checked = False

    def _ensure_client(self):
        if self._client is not None:
            return
        import os
        cfg = os.path.join("/home/w00857628", ".openviking", "ov.conf")
        if os.path.exists(cfg):
            os.environ.setdefault("OPENVIKING_CONFIG_FILE", cfg)
        from openviking import OpenViking
        self._client = OpenViking(path=self.workspace)
        self._client.initialize()
        self._available = True
        print(f"[OpenVikingStrategy] initialized client at {self.workspace}")

    @property
    def name(self):
        return "openviking"

    def reset(self):
        import os, shutil, asyncio
        # 1. Close client + destroy singleton
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            try:
                from openviking.async_client import AsyncOpenViking as _AOV
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_AOV.reset())
                loop.close()
            except Exception as e:
                print(f"[OpenVikingStrategy] singleton reset warning: {e}")
            self._client = None
            self._available = False
        # 2. Wipe workspace directory
        if os.path.exists(self.workspace):
            shutil.rmtree(self.workspace)
            print(f"[OpenVikingStrategy] deleted workspace: {self.workspace}")
        # 3. Reinitialize
        self._session = None
        self._conv_id = ""
        self._ensure_client()
        print(f"[OpenVikingStrategy] reset complete (fresh workspace)")

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        from openviking.message.part import TextPart
        if not self._available:
            self._ensure_client()
        if not self._available:
            return
        conv_id = f"conv_{session_idx}"
        if self._conv_id != conv_id:
            if self._session is not None:
                try:
                    self._session.commit()
                    print(f"[OpenVikingStrategy] committed previous session {self._conv_id}")
                except Exception as e:
                    print(f"[OpenVikingStrategy] commit on session switch: {e}")
            self._conv_id = conv_id
            self._session = self._client.session(session_id=conv_id)
        content = text
        if blip_caption:
            content += f" [shared image: {blip_caption}]"
        if session_date:
            content = f"[{session_date}] {speaker}: {content}"
        else:
            content = f"{speaker}: {content}"
        role = "user" if speaker.lower() in ("user", "human", "me") else "assistant"
        self._session.add_message(role, [TextPart(text=content)])

    def flush(self):
        if not self._available or self._session is None:
            return
        import time
        t0 = time.time()
        try:
            result = self._session.commit()
            elapsed = time.time() - t0
            memories = result.get("memories_extracted", 0)
            print(f"[OpenVikingStrategy] committed: {memories} memories extracted in {elapsed:.1f}s")
        except Exception as e:
            print(f"[OpenVikingStrategy] flush/commit error: {e}")

    def retrieve(self, query: str, client=None) -> str:
        if not self._available:
            self._ensure_client()
        if not self._available:
            return ""
        try:
            result = self._client.find(query, limit=10)
            memories = []
            for match in result.memories[:5]:
                content = ""
                uri = match.uri or ""
                # L2 full text > L1 overview > L0 abstract
                if uri:
                    try:
                        content = self._client.read(uri) or ""
                    except Exception:
                        pass
                    if not content:
                        try:
                            content = self._client.overview(uri) or ""
                        except Exception:
                            pass
                if not content:
                    content = match.abstract or ""
                    if not content and uri:
                        try:
                            content = self._client.abstract(uri) or ""
                        except Exception:
                            pass
                if content:
                    memories.append(content)
            n = len(memories)
            print(f"[OpenVikingStrategy] find: {n} memory results for query: {query[:40]}")
            for i, m in enumerate(memories[:3]):
                level = "L2" if len(m) > 500 else ("L1" if len(m) > 150 else "L0")
                print(f"[OpenVikingStrategy]   [{i}] ({level}, {len(m)}ch): {m[:100]}")
            return "\n\n".join(memories)
        except Exception as e:
            print(f"[OpenVikingStrategy] retrieve error: {e}")
            return ""


def main():
    parser = argparse.ArgumentParser(description="Memory Eval Pipeline")
    parser.add_argument("--data", required=True, help="LoCoMo 数据路径 (locomo10.json)")
    parser.add_argument(
        "--strategy", default="all",
        choices=["all", "no_memory", "full_history", "rag", "mem0", "memos", "openviking", "meta_skill", "src_memory", "v1_memory"],
        help="要评测的 memory 策略"
    )
    parser.add_argument("--model", default="MiniMax-M2.5", help="答题模型")
    parser.add_argument("--answer-base-url", default="", help="答题模型的 API base URL（不填则用 OPENAI_BASE_URL）")
    parser.add_argument("--answer-api-key", default="", help="答题模型的 API key（不填则用 OPENAI_API_KEY）")
    parser.add_argument("--judge-model", default="MiniMax-M2.5", help="评分模型")
    parser.add_argument("--top-k", type=int, default=5, help="RAG 检索 top-k")
    parser.add_argument("--embedding-model", default="/home/models/bge-large-en-v1.5",
                        help="RAG 使用的 embedding 模型路径或 HuggingFace 模型名")
    parser.add_argument("--max-qa", type=int, default=20, help="每条对话最多测几个 QA")
    parser.add_argument("--max-sessions", type=int, default=9999, help="Mem0: 最多 flush 多少个 session（调试用）")
    
    parser.add_argument("--categories", nargs="*", help="只测指定类别 (single-hop temporal multi-hop open-domain)")
    parser.add_argument("--conv-ids", nargs="*", default=None,
                        help="只跑指定对话 ID，例如: --conv-ids conv-26 conv-30（不传则跑全部）")
    parser.add_argument("--mode", choices=["selective", "exhaustive", "hybrid"], default="selective",
                        help="Memory mode for src_memory strategy (default: selective)")
    parser.add_argument("--no-rewrite", action="store_true", default=False,
                        help="RAGMemory: 禁用 query rewrite（对照实验用）")
    parser.add_argument("--chunk-turns", type=int, default=0,
                        help="RAG ablation: split sessions into N-turn sub-chunks (0=session-level, default)")
    parser.add_argument("--chunk-size", type=int, default=8,
                        help="SrcMemory chunk size (N-turn sub-chunks; 0=session-level)")
    parser.add_argument("--output", default="results/results.json", help="结果输出路径")
    parser.add_argument("--save-bandit", default="", help="Exp3: save final bandit state to this SQLite path")
    parser.add_argument("--load-bandit", default="", help="Exp3: load bandit state from this SQLite path (warm start)")
    args = parser.parse_args()

    # 加载数据
    print(f"加载数据: {args.data}")
    conversations = load_locomo(args.data)
    print(f"共 {len(conversations)} 条对话")

    # 按需初始化策略（避免不必要的模型加载占用显存）
    def build_strategy(name):
        if name == "no_memory":   return NoMemory()
        if name == "full_history": return FullHistory()
        if name == "rag":         return RAGMemory(top_k=args.top_k, embedding_model=args.embedding_model,
                                                   chunk_turns=args.chunk_turns,
                                                   disable_rewrite=args.no_rewrite)
        if name == "mem0":        return Mem0Memory()
        if name == "memos":       return MemOSStrategy()
        if name == "openviking":  return OpenVikingStrategy()
        if name == "meta_skill" and _METASKILL_AVAILABLE:
            bandit_db = args.load_bandit or args.save_bandit or None
            return MetaSkillStrategy(use_bandit=True, db_path=bandit_db)
        if name == "src_memory":
            if not _SRC_MEMORY_AVAILABLE:
                raise RuntimeError("SrcMemoryStrategy not available — check sys.path")
            return SrcMemoryStrategy(mode=args.mode, chunk_size=args.chunk_size)
        if name == "v1_memory":
            if not _V1_MEMORY_AVAILABLE:
                raise RuntimeError("V1MemoryStrategy not available — check sys.path")
            return V1MemoryStrategy()
        raise ValueError(f"未知策略: {name}")

    strategy_names = ["no_memory", "full_history", "rag", "mem0"] if args.strategy == "all" else [args.strategy]
    strategies = [build_strategy(n) for n in strategy_names]

    # 过滤对话 ID
    if args.conv_ids:
        conversations = [c for c in conversations if c.sample_id in args.conv_ids]
        if not conversations:
            print(f"错误：指定的 conv-ids {args.conv_ids} 在数据集中不存在")
            print(f"可用的 ID: {[c.sample_id for c in load_locomo(args.data)]}")
            exit(1)
        print(f"过滤后：只跑 {[c.sample_id for c in conversations]}")

    # Auto-detect GLM config from .env if --model contains "glm" and no explicit base_url
    answer_base_url = args.answer_base_url
    answer_api_key = args.answer_api_key
    if "glm" in args.model.lower() and not answer_base_url:
        answer_base_url = os.environ.get("GLM_BASE_URL", "")
        answer_api_key = os.environ.get("GLM_API_KEY", "")
        if answer_base_url and answer_api_key:
            print(f"自动检测到 GLM 配置: base_url={answer_base_url}")
        else:
            print("警告: 模型名包含 'glm' 但未找到 GLM_BASE_URL/GLM_API_KEY 环境变量")

    # 运行评测
    results = run_eval(
        conversations=conversations,
        strategies=strategies,
        model=args.model,
        judge_model=args.judge_model,
        max_qa_per_conv=args.max_qa,
        categories=args.categories,
        max_sessions=args.max_sessions,
        answer_base_url=answer_base_url,
        answer_api_key=answer_api_key,
    )

    # Force-save bandit state if --save-bandit was specified
    if args.save_bandit:
        for s in strategies:
            if hasattr(s, 'force_save_bandit'):
                s.force_save_bandit()
                print(f"[exp3] Bandit state saved to {args.save_bandit}")

    # 汇总 & 保存
    summarize(results)
    save_results(results, args.output)

    # Dump per-QA phase log if strategy supports it
    for s in strategies:
        if hasattr(s, 'dump_phase_log'):
            s.dump_phase_log()

if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# OpenViking Memory Strategy
# ─────────────────────────────────────────────
