"""Tier 1: local Qwen3 via mlx-lm with Hermes-style tool calling. Resident model, thinking off."""
from __future__ import annotations

import json
import re
import threading
import time

from . import config

from .tools import TOOLS

SYSTEM = (
    "You are Sheru — " + config.USER_NAME + "'s AI on their Mac. You handle things locally and privately, on-device, "
    "and you're quietly proud of that; you only bring in Claude when a task truly needs it. You're on "
    + config.USER_NAME + "'s side. "
    "PERSONALITY: warm, sharp, natural — like a capable friend, not a servile voice-bot. A LIGHT touch of character "
    "is good, but keep it SUBTLE: no performing, no catchphrases, no recurring bits or props. In particular do NOT "
    "keep steering to tea, British/butler mannerisms, or any single running motif — just talk like a normal, smart "
    "person. Keep replies short, plain, and to the point; never groveling, never robotic, never over-explaining. "
    "Decide ONE action: either call exactly one tool, or reply in at most two short spoken sentences. "
    "You handle plenty yourself — simple, timeless facts you're truly sure of (basic history, definitions, small "
    "arithmetic — 'India became independent in 1947', 'the factorial of 5 is 120'), and everyday chit-chat with warmth. "
    "But for ANYTHING current, live, or external — weather, news, prices, stocks, scores, anything about 'today'/'now'/"
    "'latest', reading or summarizing a web page or search results, research — and for ANY multi-step task, code, files, "
    "folders, directories, or terminal/bash work, and for anything you'd otherwise have to guess, call ask_claude with the "
    "full task. NEVER refuse with 'I can't browse' or 'I can't see the internet', and NEVER make up live data — reach for "
    "ask_claude instead of guessing (you're proud, not reckless). "
    "Never say you are 'processing' or that you 'will' do something later: act now via a tool, or answer plainly. "
    "Never explain your reasoning."
)

_TOOL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


class LocalLLM:
    def __init__(self, model_id: str = config.LOCAL_LLM, adapter_path: str | None = None) -> None:
        self.model_id = model_id
        self.adapter_path = adapter_path if adapter_path is not None else config.LOCAL_ADAPTER
        self._lock = threading.Lock()
        self._model = self._tok = None

    def load(self) -> "LocalLLM":
        from mlx_lm import load
        from . import mlx_pool
        with self._lock:
            if self._model is None:
                kw = {"adapter_path": self.adapter_path} if self.adapter_path else {}
                self._model, self._tok = mlx_pool.run(load, self.model_id, **kw)
        return self

    def decide(self, text: str, history: list[dict] | None = None, extra_system: str = "") -> dict:
        """-> {"tool": name, "args": {...}} or {"say": text}."""
        from mlx_lm import generate
        self.load()
        sysc = SYSTEM + config.user_preferences() + config.reply_directive(text) + ("\n\n" + extra_system if extra_system else "")
        msgs = [{"role": "system", "content": sysc}, *(history or []), {"role": "user", "content": text}]
        prompt = self._tok.apply_chat_template(msgs, tools=TOOLS, add_generation_prompt=True, enable_thinking=False)
        t0 = time.perf_counter()
        from . import mlx_pool
        with self._lock:
            out = mlx_pool.run(generate, self._model, self._tok, prompt=prompt, max_tokens=256, verbose=False)
        self.last_latency = time.perf_counter() - t0
        m = _TOOL_RE.search(out)
        if m:
            try:
                call = json.loads(m.group(1))
                return {"tool": call.get("name"), "args": call.get("arguments") or {}}
            except json.JSONDecodeError:
                pass
        # tolerant fallback: model emitted a tool call that didn't close cleanly (truncation, stray text)
        loose = re.search(r"<tool_call>\s*(\{.*)", out, re.S)
        if loose:
            frag = loose.group(1).split("</tool_call>")[0]
            brace = frag.rfind("}")
            if brace != -1:
                try:
                    call = json.loads(frag[: brace + 1])
                    return {"tool": call.get("name"), "args": call.get("arguments") or {}}
                except json.JSONDecodeError:
                    pass
            return {"tool": "ask_claude", "args": {"task": text}}   # meant to call a tool; don't speak JSON — escalate
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        out = re.sub(r"</?tool_call>", "", out).strip()            # never let a stray tag reach TTS
        if out.startswith("{") and '"name"' in out:               # bare tool JSON without tags -> escalate, don't speak
            return {"tool": "ask_claude", "args": {"task": text}}
        return {"say": out or "Sorry, I didn't get that."}

    def answer(self, text: str, history: list[dict] | None = None, extra_system: str = "") -> str:
        """Answer from the model's own knowledge, briefly — used offline or when Claude Code is unreachable."""
        from mlx_lm import generate
        self.load()
        sys_p = ("You are Sheru, a voice assistant. Answer in at most three short spoken sentences from your own "
                 "knowledge. Keep any personality light and natural — no catchphrases or recurring motifs (no tea). "
                 "If it truly needs live/current data you don't have, say so in one sentence."
                 + config.user_preferences() + config.reply_directive(text))
        sys_p += ("\n\n" + extra_system if extra_system else "")
        msgs = [{"role": "system", "content": sys_p}, *(history or []), {"role": "user", "content": text}]
        prompt = self._tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False)
        from . import mlx_pool
        with self._lock:
            out = mlx_pool.run(generate, self._model, self._tok, prompt=prompt, max_tokens=220, verbose=False)
        return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip() or "I'm not sure."

    def freeform(self, system: str, user: str, max_tokens: int = 90) -> str:
        """One-off generation with a CUSTOM system prompt (not the assistant persona) — for battle mode etc."""
        from mlx_lm import generate
        from . import mlx_pool
        self.load()
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self._tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False)
        with self._lock:
            out = mlx_pool.run(generate, self._model, self._tok, prompt=prompt, max_tokens=max_tokens, verbose=False)
        return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
