"""
MemOS Strategy adapter for eval_pipeline.py
Connects to MemOS self-hosted API (http://localhost:18001)
"""
import requests
import time
import uuid


MEMOS_BASE_URL = "http://localhost:18001"


class MemOSStrategy:
    """
    MemOS memory strategy.
    Uses MemOS product API:
      - /product/add    to store memories
      - /product/search to retrieve memories
    Each conversation gets a unique mem_cube_id for isolation.
    """

    def __init__(self, base_url: str = MEMOS_BASE_URL, batch_size: int = 2):
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.user_id = f"eval_user_{int(time.time())}"
        self.mem_cube_id = f"eval_cube_{int(time.time())}"
        self._session_buffer: dict[int, list] = {}
        self.available = self._check_health()
        if self.available:
            print(f"[MemOS] connected to {self.base_url}, user={self.user_id}, cube={self.mem_cube_id}")
        else:
            print(f"[MemOS] WARNING: cannot connect to {self.base_url}")

    def _check_health(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/docs", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    @property
    def name(self) -> str:
        return "memos"

    def reset(self):
        """New conversation: use a fresh mem_cube_id for isolation."""
        self.user_id = f"eval_user_{int(time.time())}"
        self.mem_cube_id = f"eval_cube_{int(time.time())}"
        self._session_buffer = {}
        print(f"[MemOS] reset: new user={self.user_id}, cube={self.mem_cube_id}")

    def observe(self, speaker: str, text: str, session_date: str = "",
                session_idx: int = -1, blip_caption: str = ""):
        """Buffer turns for batch add during flush()."""
        if not self.available:
            return
        content = text
        if blip_caption:
            content += f" [shared image: {blip_caption}]"
        # Add date prefix like Mem0 approach
        if session_date:
            content = f"[{session_date}] {speaker}: {content}"
        else:
            content = f"{speaker}: {content}"

        if session_idx not in self._session_buffer:
            self._session_buffer[session_idx] = {
                "messages": [], "date": session_date, "speakers": set()
            }
        buf = self._session_buffer[session_idx]
        buf["speakers"].add(speaker)
        speakers = sorted(buf["speakers"])
        if len(speakers) <= 1 or speaker == speakers[0]:
            role = "user"
        else:
            role = "assistant"
        buf["messages"].append({"role": role, "content": content})

    def flush(self):
        """Batch-add all buffered sessions to MemOS."""
        if not self.available or not self._session_buffer:
            return
        total_sessions = len(self._session_buffer)
        total_added = 0
        for i, idx in enumerate(sorted(self._session_buffer.keys())):
            buf = self._session_buffer[idx]
            messages = buf["messages"]
            session_date = buf["date"]
            session_turns = len(messages)
            session_added = 0

            # Batch add (batch_size=2, same as Mem0 approach)
            for j in range(0, session_turns, self.batch_size):
                batch = messages[j:j + self.batch_size]
                try:
                    t0 = time.time()
                    payload = {
                        "user_id": self.user_id,
                        "mem_cube_id": self.mem_cube_id,
                        "messages": batch,
                        "async_mode": "sync",
                    }
                    # Add session date as metadata if available
                    if session_date:
                        payload["info"] = {"session_date": session_date}

                    r = requests.post(
                        f"{self.base_url}/product/add",
                        json=payload,
                        timeout=120,
                    )
                    elapsed = time.time() - t0
                    resp = r.json()
                    n_mem = len(resp.get("data", []))
                    session_added += n_mem
                    print(f"[MemOS] session {i+1}/{total_sessions} batch {j//self.batch_size+1}: "
                          f"{n_mem} memories, {elapsed:.1f}s")
                except Exception as e:
                    print(f"[MemOS] session {i+1} batch {j//self.batch_size+1} error: {e}")

            total_added += session_added
            print(f"[MemOS] flush session {i+1}/{total_sessions} "
                  f"(idx={idx}, turns={session_turns}): {session_added} memories")

        self._session_buffer = {}
        print(f"[MemOS] flush complete: {total_added} memories across {total_sessions} sessions")

    def retrieve(self, query: str, client=None) -> str:
        """Search MemOS for relevant memories."""
        if not self.available:
            return ""
        try:
            t0 = time.time()
            payload = {
                "query": query,
                "user_id": self.user_id,
                "mem_cube_id": self.mem_cube_id,
            }
            r = requests.post(
                f"{self.base_url}/product/search",
                json=payload,
                timeout=60,
            )
            elapsed = time.time() - t0
            resp = r.json()
            data = resp.get("data", {})

            # Collect memories from all memory types
            all_memories = []
            for mem_type in ["text_mem", "act_mem", "pref_mem", "tool_mem", "skill_mem"]:
                cubes = data.get(mem_type, [])
                if isinstance(cubes, list):
                    for cube in cubes:
                        if isinstance(cube, dict):
                            for m in cube.get("memories", []):
                                mem_text = m.get("memory", "")
                                if mem_text:
                                    all_memories.append(mem_text)
                elif isinstance(cubes, str) and cubes:
                    all_memories.append(cubes)

            # Also check for preference notes
            pref_note = data.get("pref_note", "")
            if pref_note:
                all_memories.append(pref_note)

            print(f"[MemOS] search {query[:40]}...: {len(all_memories)} results, {elapsed:.1f}s")
            for k, m in enumerate(all_memories[:5]):
                print(f"[MemOS]   result {k}: {m[:120]}")

            return "\n".join(all_memories) if all_memories else ""

        except Exception as e:
            print(f"[MemOS] search error: {e}")
            return ""
