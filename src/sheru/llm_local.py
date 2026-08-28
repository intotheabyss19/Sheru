"""Tier 1: local Qwen3 via mlx-lm with Hermes-style tool calling. Resident model, thinking off."""
from __future__ import annotations

import json
import re
import threading
import time

from . import config

from .tools import TOOLS

SYSTEM = (
    "You are Sheru, " + config.USER_NAME + "'s warm, capable assistant on their Mac — a companion, not a robotic voice bot. "
    "Decide ONE action: either call exactly one tool, or reply in at most two short spoken sentences. "
    "Your reasoning is basic — you are NOT a puzzle-solver. Answer directly ONLY simple, timeless facts you are truly sure of "
    "(basic history, definitions, small arithmetic — e.g. 'India became independent in 1947', 'the factorial of 5 is 120'). "
    "For ANYTHING current, live, or external — weather, news, prices, stocks, scores, anything about 'today'/'now'/'latest', "
    "reading or summarizing a web page or search results, research — and for ANY multi-step task, code, files, folders, directories, "
    "or terminal/bash work, and for anything you are even slightly unsure about, you MUST call ask_claude with the full task. "
    "NEVER refuse with 'I can't browse' or 'I can't see the internet', and NEVER guess — when it needs live data or you are unsure, "
    "call ask_claude instead of guessing. "
    "Never say you are 'processing' or that you 'will' do something later: act now via a tool, or answer plainly. "
    "Be friendly and natural; never explain your reasoning."
)

_TOOL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


class LocalLLM:
    def __init__(self, model_id: str = config.LOCAL_LLM) -> None:
        self.model_id = model_id
        self._lock = threading.Lock()
        self._model = self._tok = None

    def load(self) -> "LocalLLM":
        from mlx_lm import load
        from . import mlx_pool
        with self._lock:
            if self._model is None:
                self._model, self._tok = mlx_pool.run(load, self.model_id)
        return self

    def decide(self, text: str, history: list[dict] | None = None, extra_system: str = "") -> dict:
        """-> {"tool": name, "args": {...}} or {"say": text}."""
        from mlx_lm import generate
        self.load()
        sysc = SYSTEM + ("\n\n" + extra_system if extra_system else "")
        msgs = [{"role": "system", "content": sysc}, *(history or []), {"role": "user", "content": text}]
        prompt = self._tok.apply_chat_template(msgs, tools=TOOLS, add_generation_prompt=True, enable_thinking=False)
        t0 = time.perf_counter()
        from . import mlx_pool
        with self._lock:
            out = mlx_pool.run(generate, self._model, self._tok, prompt=prompt, max_tokens=160, verbose=False)
        self.last_latency = time.perf_counter() - t0
        m = _TOOL_RE.search(out)
        if m:
            try:
                call = json.loads(m.group(1))
                return {"tool": call.get("name"), "args": call.get("arguments") or {}}
            except json.JSONDecodeError:
                pass
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        return {"say": out or "Sorry, I didn't get that."}

    def answer(self, text: str, history: list[dict] | None = None, extra_system: str = "") -> str:
        """Answer from the model's own knowledge, briefly — used offline or when Claude Code is unreachable."""
        from mlx_lm import generate
        self.load()
        sys_p = ("You are Sheru, a voice assistant. Answer in at most three short spoken sentences from your own "
                 "knowledge. If it truly needs live/current data you don't have, say so in one sentence.")
        sys_p += ("\n\n" + extra_system if extra_system else "")
        msgs = [{"role": "system", "content": sys_p}, *(history or []), {"role": "user", "content": text}]
        prompt = self._tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False)
        from . import mlx_pool
        with self._lock:
            out = mlx_pool.run(generate, self._model, self._tok, prompt=prompt, max_tokens=220, verbose=False)
        return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip() or "I'm not sure."
