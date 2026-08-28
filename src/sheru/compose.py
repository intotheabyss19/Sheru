"""Draft and rephrase short personal messages from a rough intent, via the local LLM."""
from __future__ import annotations

import re


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    # models often wrap the message in quotes or add "Here's...:" — strip that
    text = re.sub(r'^\s*(?:here(?:\'s| is)[^:]*:|sure[!,. ]*|draft:?)\s*', "", text, flags=re.I).strip()
    text = text.strip().strip('"').strip("'").strip()
    return text


def draft(llm, recipient: str, gist: str, revision: str = "", previous: str = "") -> str:
    """Compose a friendly, natural message. `revision` = change instruction on `previous`."""
    if revision and previous:
        prompt = (f"Here is a message to {recipient}:\n\"{previous}\"\n\n"
                  f"Rewrite it with this change: {revision}\n"
                  f"Reply with ONLY the rewritten message text, nothing else.")
    else:
        prompt = (f"Write a short, warm, natural text message to {recipient}. "
                  f"Intent: {gist}. Greet them by name. Keep it casual and human, 1-3 sentences. "
                  f"Reply with ONLY the message text, no preamble, no quotes.")
    from mlx_lm import generate
    llm.load()
    msgs = [{"role": "system", "content": "You write brief, friendly personal text messages. Output only the message."},
            {"role": "user", "content": prompt}]
    tmpl = llm._tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False)
    from . import mlx_pool
    with llm._lock:
        out = mlx_pool.run(generate, llm._model, llm._tok, prompt=tmpl, max_tokens=200, verbose=False)
    return _clean(out)
