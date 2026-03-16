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

    def __init__(self, top_k: int = 3, embedding_model: str = "/home/models/bge-large-en-v1.5"):
        self.top_k = top_k
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
    def name(self): return f"rag_session_top{self.top_k}"

    def reset(self):
        self._session_turns = {}
        self._session_dates = {}
        self.chunks = []
        self.embeddings = []
        self._chunks_built = False

    def _embed(self, text: str):
        return self._st_model.encode(text, normalize_embeddings=True).tolist()

    def _build_chunks(self):
        """把 session_turns 整合成 session 级别 chunk 并做 embedding（只在第一次 retrieve 时触发）"""
        import numpy as np
        self.chunks = []
        self.embeddings = []
        for idx in sorted(self._session_turns.keys()):
            date = self._session_dates.get(idx, "")
            turns = self._session_turns[idx]
            header = f"[{date}]" if date else f"[Session {idx}]"
            chunk = header + "\n" + "\n".join(turns)
            self.chunks.append(chunk)
            self.embeddings.append(self._embed(chunk))
        self._chunks_built = True

    def observe(self, speaker: str, text: str, session_date: str = "", session_idx: int = -1, blip_caption: str = ""):
        # 按 session 分组收集 turn
        if session_idx not in self._session_turns:
            self._session_turns[session_idx] = []
            self._session_dates[session_idx] = session_date
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
        search_query = self._rewrite_query(query, client) if client else query
        q_emb = np.array(self._embed(search_query))
        scores = [
            np.dot(q_emb, np.array(e)) /
            (np.linalg.norm(q_emb) * np.linalg.norm(np.array(e)) + 1e-9)
            for e in self.embeddings
        ]
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:self.top_k]
        top_idx_sorted = sorted(top_idx)  # 按时间顺序返回
        return "\n\n".join(self.chunks[i] for i in top_idx_sorted)

# ─────────────────────────────────────────────
# Baseline D: Mem0Memory
# ─────────────────────────────────────────────

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
                        "on_disk": False,
                        "embedding_model_dims": 1024,
                    }
                }
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
        # 只收集 turns，不调 LLM；replay 结束后调 flush() 批量处理
        if not self.available:
            return
        content = text
        if blip_caption:
            content += f" [shared image: {blip_caption}]"
        prefix = f"[{session_date}] " if session_date else ""
        role = "assistant" if speaker == "agent" else "user"
        if session_idx not in self._session_buffer:
            self._session_buffer[session_idx] = []
        self._session_buffer[session_idx].append(
            {"role": role, "content": prefix + content}
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
                kwargs["max_tokens"] = 4096
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
        """replay 结束后调用：按 session 批量 add，每个 session 一次 LLM 调用提取 facts"""
        if not self.available or not self._session_buffer:
            return
        total = len(self._session_buffer)
        for i, idx in enumerate(sorted(self._session_buffer.keys())):
            messages = self._session_buffer[idx]
            try:
                self.mem.add(messages=messages, user_id=self.user_id)
                print(f"[Mem0Memory] flush session {i+1}/{total} (idx={idx}, turns={len(messages)})")
            except Exception as e:
                print(f"[Mem0Memory] flush session {idx} error: {e}")
        self._session_buffer = {}

    def retrieve(self, query: str, client=None) -> str:
        if not self.available:
            return ""
        try:
            results = self.mem.search(query=query, user_id=self.user_id, limit=5)
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
If the answer is not found in the memory, say "I don't know" honestly. Do not make up information.
Answer concisely in plain natural language. Do not output anything extra."""

class AgentLoop:
    def __init__(self, memory: MemoryStrategy, model: str = "MiniMax-M2.5"):
        self.memory = memory
        self.model = model
        self.client = OpenAI()
        self.total_tokens = 0

    def replay_conversation(self, turns: list[Turn]):
        """重放对话历史，让 memory 系统学习"""
        self.memory.reset()
        for turn in turns:
            self.memory.observe(turn.speaker, turn.text, turn.session_date, turn.session_idx, turn.blip_caption)
        # Mem0Memory: observe only collects turns, flush() batch-adds after replay
        if hasattr(self.memory, "flush"):
            self.memory.flush()

    def answer(self, question: str) -> tuple[str, float, int]:
        """回答一个 probe 问题，返回 (answer, latency_ms, tokens)"""
        # RAGMemory supports client param for query rewriting; others ignore it
        if hasattr(self.memory, "_rewrite_query"):
            context = self.memory.retrieve(question, client=self.client)
        else:
            context = self.memory.retrieve(question)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({
                "role": "user",
                "content": f"[Memory Context]\n{context}\n\n[Question]\n{question}"
            })
        else:
            messages.append({"role": "user", "content": f"[Question]\n{question}"})

        t0 = time.time()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=1024,  # enough for answer + think
            timeout=60,
        )
        latency_ms = (time.time() - t0) * 1000
        tokens = resp.usage.total_tokens
        self.total_tokens += tokens
        raw = resp.choices[0].message.content.strip()
        # 去掉 <think>...</think> 推理过程，只保留最终答案
        import re as _re
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        prediction = cleaned if cleaned else raw
        return prediction, latency_ms, tokens

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

class LLMJudge:
    def __init__(self, model: str = "MiniMax-M2.5"):
        self.client = OpenAI()
        self.model = model

    def score(self, question: str, reference: str, prediction: str, category: str = "") -> float:
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
) -> list[EvalResult]:

    judge = LLMJudge(model=judge_model)
    all_results: list[EvalResult] = []

    for strategy in strategies:
        print(f"\n{'='*50}")
        print(f"策略: {strategy.name}")
        print(f"{'='*50}")
        agent = AgentLoop(memory=strategy, model=model)

        for conv in conversations:
            print(f"\n  对话: {conv.sample_id}（{len(conv.turns)} 轮, {len(conv.qa_list)} 个 QA）")

            # 重放对话历史
            agent.replay_conversation(conv.turns)

            # 筛选要测的 QA
            qa_subset = conv.qa_list
            if categories:
                qa_subset = [q for q in qa_subset if q.category in categories]
            qa_subset = qa_subset[:max_qa_per_conv]

            for i, qa in enumerate(qa_subset):
                try:
                    prediction, latency_ms, tokens = agent.answer(qa.question)
                except Exception as e:
                    print(f"    [answer error] {type(e).__name__}: {str(e)[:60]}, skipping")
                    prediction, latency_ms, tokens = "", 0.0, 0
                try:
                    score = judge.score(qa.question, qa.answer, prediction, category=qa.category)
                except Exception as e:
                    print(f"    [judge error] {type(e).__name__}: {str(e)[:60]}, defaulting 0.0")
                    score = 0.0

                f1 = compute_f1(prediction, qa.answer)
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
                )
                all_results.append(result)

                status = "✓" if score >= 0.5 else "✗"
                print(f"    [{i+1}/{len(qa_subset)}] {status} judge={score:.1f} f1={f1:.2f} [{qa.category}] {qa.question[:40]}...")

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
        }
        for r in results
    ]
    with open(output_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_path}")

# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Memory Eval Pipeline")
    parser.add_argument("--data", required=True, help="LoCoMo 数据路径 (locomo10.json)")
    parser.add_argument(
        "--strategy", default="all",
        choices=["all", "no_memory", "full_history", "rag", "mem0"],
        help="要评测的 memory 策略"
    )
    parser.add_argument("--model", default="MiniMax-M2.5", help="答题模型")
    parser.add_argument("--judge-model", default="MiniMax-M2.5", help="评分模型")
    parser.add_argument("--top-k", type=int, default=5, help="RAG 检索 top-k")
    parser.add_argument("--embedding-model", default="/home/models/bge-large-en-v1.5",
                        help="RAG 使用的 embedding 模型路径或 HuggingFace 模型名")
    parser.add_argument("--max-qa", type=int, default=20, help="每条对话最多测几个 QA")
    parser.add_argument("--categories", nargs="*", help="只测指定类别 (single-hop temporal multi-hop open-domain)")
    parser.add_argument("--conv-ids", nargs="*", default=None,
                        help="只跑指定对话 ID，例如: --conv-ids conv-26 conv-30（不传则跑全部）")
    parser.add_argument("--output", default="results/results.json", help="结果输出路径")
    args = parser.parse_args()

    # 加载数据
    print(f"加载数据: {args.data}")
    conversations = load_locomo(args.data)
    print(f"共 {len(conversations)} 条对话")

    # 按需初始化策略（避免不必要的模型加载占用显存）
    def build_strategy(name):
        if name == "no_memory":   return NoMemory()
        if name == "full_history": return FullHistory()
        if name == "rag":         return RAGMemory(top_k=args.top_k, embedding_model=args.embedding_model)
        if name == "mem0":        return Mem0Memory()
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

    # 运行评测
    results = run_eval(
        conversations=conversations,
        strategies=strategies,
        model=args.model,
        judge_model=args.judge_model,
        max_qa_per_conv=args.max_qa,
        categories=args.categories,
    )

    # 汇总 & 保存
    summarize(results)
    save_results(results, args.output)

if __name__ == "__main__":
    main()
