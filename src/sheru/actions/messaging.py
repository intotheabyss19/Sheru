"""Send messages: resolve a name via Contacts, send via Messages (iMessage/SMS) or WhatsApp.

Auto-send via AppleScript is best-effort (tightened on recent macOS); the reliable, safe fallback is to
open the conversation PRE-FILLED so the final send is one keypress. Sheru already voice-confirms before this.
"""
from __future__ import annotations

import re
import subprocess
import time
from urllib.parse import quote


def _osa(script: str, timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)


def _all_names() -> list[str]:
    """Every contact's name, one per line (for fuzzy matching when exact lookup misses)."""
    subprocess.run(["open", "-gj", "-a", "Contacts"], check=False)
    script = ('tell application "Contacts"\n launch\n'
              "set AppleScript's text item delimiters to linefeed\n"
              "return (name of every person) as text\nend tell")
    r = _osa(script, timeout=20)
    for _ in range(3):
        if "-600" not in r.stderr:
            break
        time.sleep(0.5)
        r = _osa(script, timeout=20)
    return [n.strip() for n in r.stdout.split("\n") if n.strip()]


def resolve_contact(name: str) -> dict | None:
    """Resolve a name to a WhatsApp handle. Sheru's own contact book first (the primary source — no macOS
    Contacts needed), then macOS Contacts as a silent fallback for numbers already synced there.
    Exact match first; on a miss, fuzzy-match the spoken name (STT drops letters)."""
    from . import contacts_book
    own = contacts_book.get(name)
    if own:
        return own
    hit = _lookup_by_name(name)
    if hit:
        return hit
    best = _fuzzy_name(name, _all_names())
    return _lookup_by_name(best) if best else None


def _fuzzy_name(query: str, names: list[str], cutoff: int = 82) -> str | None:
    """Closest contact name to a (possibly STT-garbled) spoken name. Scores against the full name AND each
    token (first/last name) with plain ratio — rewards close spellings, rejects unrelated substrings."""
    from rapidfuzz import fuzz
    ql = query.lower()
    best, best_score = None, 0.0
    for full in names:
        fl = full.lower()
        s = max([fuzz.ratio(ql, fl)] + [fuzz.ratio(ql, tok) for tok in fl.split()])
        if s > best_score:
            best, best_score = full, s
    return best if best_score >= cutoff else None


def _lookup_by_name(name: str) -> dict | None:
    subprocess.run(["open", "-gj", "-a", "Contacts"], check=False)   # `whose` queries need Contacts running
    safe = name.replace("\\", "\\\\").replace('"', '\\"')
    # NOTE: do NOT name a var `full` here — it collides with Contacts' `full name` term -> -10003 access error.
    script = f'''
    tell application "Contacts"
      launch
      set matches to (every person whose name contains "{safe}")
      if (count of matches) is 0 then return "NONE"
      set p to item 1 of matches
      set theName to name of p
      set handle to ""
      if (count of phones of p) > 0 then
        set handle to value of item 1 of phones of p
        return theName & "|phone|" & handle
      else if (count of emails of p) > 0 then
        set handle to value of item 1 of emails of p
        return theName & "|email|" & handle
      end if
      return theName & "|none|"
    end tell'''
    for _ in range(4):                    # Contacts can throw -600 for ~1 s right after launch
        r = _osa(script)
        if "-600" not in r.stderr:
            break
        time.sleep(0.5)
    out = r.stdout.strip()
    if not out or out == "NONE" or "|" not in out:
        return None
    full, kind, handle = (out.split("|", 2) + ["", ""])[:3]
    if not handle:
        return None
    return {"name": full, "kind": kind, "handle": handle.strip()}


def send_imessage(handle: str, text: str, dry_run: bool = False) -> bool:
    """Best-effort auto-send via Messages. Returns True if AppleScript reported success."""
    if dry_run:
        return True
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Messages"
      set svc to 1st account whose service type = iMessage
      set buddy to participant "{handle}" of svc
      send "{esc}" to buddy
    end tell'''
    return _osa(script).returncode == 0


def _frontmost() -> str:
    return _osa('tell application "System Events" to name of first application process whose frontmost is true').stdout.strip()


def send_whatsapp(handle: str, text: str, dry_run: bool = False) -> bool:
    """Open the WhatsApp chat pre-filled, then press Return to send. Returns True only if the send fired.
    Safety: presses Return ONLY while WhatsApp is confirmed frontmost, so it can't send into the wrong window.
    On any doubt returns False with the chat left pre-filled for a manual Return."""
    digits = re.sub(r"\D", "", handle)
    url = f"whatsapp://send?phone={digits}&text={quote(text)}"
    if dry_run:
        return True
    subprocess.run(["open", url], check=False)
    for _ in range(25):                       # wait up to ~5 s for WhatsApp to come forward with the draft
        time.sleep(0.2)
        if _frontmost() == "WhatsApp":
            break
    else:
        return False                          # never became frontmost — don't risk sending elsewhere
    time.sleep(1.3)                           # navigating to a fresh chat + focusing the box takes ~1 s
    if _frontmost() != "WhatsApp":            # re-verify immediately before the keypress
        return False
    subprocess.run(["osascript", "-e", 'tell application "WhatsApp" to activate'], capture_output=True)
    _osa('tell application "System Events" to key code 36')          # Return -> send
    time.sleep(0.6)
    if _frontmost() == "WhatsApp":            # backup Return (harmless no-op if the first already sent)
        _osa('tell application "System Events" to key code 36')
    return True


def prefill(handle: str, text: str, app: str = "messages", dry_run: bool = False) -> str:
    """Open the conversation pre-filled (user presses send). Returns the URL used."""
    if app == "whatsapp":
        digits = re.sub(r"\D", "", handle)   # WhatsApp needs country code + number, digits only (no +, spaces)
        url = f"whatsapp://send?phone={digits}&text={quote(text)}"
    else:
        url = f"sms:{quote(handle)}&body={quote(text)}"
    if not dry_run:
        subprocess.run(["open", url], check=False)
    return url
