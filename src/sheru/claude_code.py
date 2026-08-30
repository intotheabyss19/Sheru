"""Tier 2: hand a task to Claude Code headless (`claude -p`, subscription auth) and stream spoken progress."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config

CLAUDE = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
DEFAULT_TOOLS = "WebSearch,WebFetch,Read,Grep,Glob,LS"
_SENTENCE = re.compile(r"(.+?[.!?])(?:\s+|$)")


@dataclass
class ClaudeSession:
    cwd: Path = field(default_factory=Path.home)
    allowed_tools: str = DEFAULT_TOOLS
    permission_mode: str = "default"          # acceptEdits when the user asks for file work
    max_turns: int = 25
    session_id: str | None = None
    _proc: subprocess.Popen | None = None
    _running: bool = False        # True from run() until the pump thread has created _proc (no startup race on `busy`)

    def run(self, task: str, on_sentence: Callable[[str], None], on_done: Callable[[str], None] | None = None,
            on_error: Callable[[str], None] | None = None, resume: bool = False,
            extra_args: list[str] | None = None, max_seconds: float = 150.0) -> threading.Thread:
        """Start `claude -p` in a thread; speak text as sentences complete; call on_done(final_text)."""
        args = [CLAUDE, "-p", task, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--permission-mode", self.permission_mode, "--max-turns", str(self.max_turns),
                "--allowedTools", self.allowed_tools,
                "--append-system-prompt", ("You are speaking to the user through a voice assistant named Sheru. Keep every reply "
                                           "under four short sentences of plain, natural spoken words; no markdown, no lists, no code "
                                           "unless asked to write a file. Do NOT narrate your tools, steps, or process — just give the answer directly."
                                           + config.reply_directive(task))]
        if resume and self.session_id:
            args += ["--resume", self.session_id]
        args += extra_args or []
        # Never look like a nested Claude Code session, but keep CLAUDE_CONFIG_DIR (which login to use).
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith("CLAUDE_CODE") or k == "CLAUDECODE" or k in ("CLAUDE_PID", "CLAUDE_EFFORT"))}
        env.pop("ANTHROPIC_API_KEY", None)  # subscription auth only
        if config.CLAUDE_CONFIG_DIR:        # pin the personal login; default ~/.claude may be an org with Claude Code disabled
            env["CLAUDE_CONFIG_DIR"] = config.CLAUDE_CONFIG_DIR

        errored = [None]
        watchdog = [None]
        self._running = True          # synchronous, so busy is True the instant run() returns (the pump thread sets _proc async)

        def _pump():
            try:
                self._proc = subprocess.Popen(args, cwd=self.cwd, env=env, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, text=True, bufsize=1)
                self._running = False     # _proc now exists; its poll() is the busy signal from here
            except OSError as e:
                self._running = False
                (on_error or on_sentence)(str(e))
                return
            def _timeout():
                if self._proc and self._proc.poll() is None:
                    errored[0] = "timed out"
                    self.cancel()
            watchdog[0] = threading.Timer(max_seconds, _timeout)
            watchdog[0].daemon = True
            watchdog[0].start()
            buf, final, spoke = "", "", False
            for line in self._proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = ev.get("type")
                if t == "stream_event":
                    d = ev.get("event", {}).get("delta", {})
                    if d.get("type") == "text_delta":
                        buf += d["text"]
                        while (m := _SENTENCE.match(buf)):
                            on_sentence(m.group(1).strip()); spoke = True; buf = buf[m.end():]
                elif t == "result":
                    self.session_id = ev.get("session_id", self.session_id)
                    final = ev.get("result") or ""
                    if ev.get("is_error") or ev.get("subtype", "").startswith("error"):
                        errored[0] = final or ev.get("subtype") or "unknown error"
                        final = ""
            if buf.strip():
                on_sentence(buf.strip()); spoke = True
            if watchdog[0]:
                watchdog[0].cancel()
            rc = self._proc.wait()
            if errored[0] == "timed out" and not final:
                self._proc = None
                (on_error or on_sentence)("That took too long, so I stopped it.")
                return
            if (rc not in (0, 130) or errored[0]) and not final:
                detail = errored[0] or (self._proc.stderr.read() or "")[-300:]
                self._proc = None
                if on_error:
                    on_error(detail)
                else:
                    on_sentence("Claude Code ran into a problem.")
                return
            self._proc = None
            if not spoke and final.strip():         # streaming produced no audio -> speak the answer so it's never a silent "success"
                on_sentence(final.strip())
            if on_done:
                on_done(final)

        th = threading.Thread(target=_pump, name="sheru-claude", daemon=True)
        th.start()
        return th

    def cancel(self) -> bool:
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGINT)
            return True
        return False

    @property
    def busy(self) -> bool:
        return self._running or (self._proc is not None and self._proc.poll() is None)


def open_interactive(prompt: str, cwd: Path | None = None, resume: bool = False) -> None:
    """Escape hatch: a Ghostty window running interactive Claude Code with the prompt pre-filled.
    resume=True continues the most recent conversation in `cwd` (so the trainer keeps full Sheru context)."""
    args = ["open", "-na", "Ghostty", "--args", "--window-save-state=never",
            f"--working-directory={cwd or Path.home()}", "-e", CLAUDE]
    if resume:
        args.append("--continue")
    args.append(prompt)
    env = {**os.environ}
    if config.CLAUDE_CONFIG_DIR:            # same personal-login pin for the interactive trainer window
        env["CLAUDE_CONFIG_DIR"] = config.CLAUDE_CONFIG_DIR
    subprocess.Popen(args, env=env)
