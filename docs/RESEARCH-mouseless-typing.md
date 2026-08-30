# Research: Mouseless Typing & Clicking for Sheru

**Goal:** hands-free control of text fields and buttons — dictate into any app's
text box, trigger buttons/links by voice, no mouse/trackpad.

**Target:** macOS 26 Tahoe, Apple Silicon. pyobjc **12.2.2** (already in
`.venv`). Every API name and constant below was verified against the installed
`ApplicationServices` / `HIServices` / `Quartz` modules in this repo's venv.

**Import note:** `ApplicationServices` re-exports the whole `AXUIElement*` API
*and* the `kAX*` constants, and it's what Sheru's `permissions.py` already
imports. Use `import ApplicationServices as AX` everywhere for consistency.

---

## TL;DR — top recommendation

For WhatsApp specifically (Electron), the most reliable path is **not** blind
keystroke. Ranked:

1. **URL prefill + AX-verify focus + AXPress the Send button.** Sheru already
   prefills via `whatsapp://send?text=`. Replace the blind `sleep`+Return with:
   poll the AX tree until the message `AXTextArea` is focused, then `AXPress` the
   Send `AXButton` (fallback: Return). Kills the timing guesswork.
2. **Enable Chromium a11y (`AXManualAccessibility`), locate the message box,
   insert text via `kAXSelectedTextAttribute`, AXPress Send.** Best for a live
   "typing mode" that streams multiple dictated messages. Medium reliability —
   the tree builds asynchronously, so poll.
3. **Blind CGEvent / System Events keystroke into the focused window** (current
   approach) — keep as the universal last-resort fallback.

Everything below is gated by **one** thing: the Sheru **.app** must hold the
**Accessibility** TCC grant. Read section 0 first.

---

## 0. THE GATE: TCC Accessibility (read this first)

A single permission gates *all* of this feature:

- Reading **another app's** AX tree (`AXUIElementCopyAttributeValue` on anything
  but your own process) → returns `kAXErrorAPIDisabled` (**-25211**) without it.
- Setting AX values / performing actions (`AXUIElementSetAttributeValue`,
  `AXUIElementPerformAction`).
- Posting synthetic events (`CGEventPost`) and `System Events` keystrokes
  (`osascript` → error **-1719 / -25211**, "not allowed assistive access").

The grant lives in **System Settings ▸ Privacy & Security ▸ Accessibility** and
is tied to the **signed binary that hosts the Python** — i.e. `Sheru.app`, *not*
the terminal. macOS 26 notes:

- Grant is keyed to the code signature. **Re-signing / repackaging Sheru resets
  it** — the app reappears unchecked. Onboarding must re-check every launch.
- `claude -p` and terminal-launched dev runs have a *different* TCC identity than
  the packaged app (this is already noted in `permissions.py`).

Sheru already has the plumbing — reuse it, don't reinvent:

```python
# src/sheru/permissions.py (existing)
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
def accessibility_trusted() -> bool: return bool(AXIsProcessTrusted())
def request_accessibility(prompt=True):
    AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": prompt})  # adds Sheru to the list + prompts
```

**Preflight every AX/CGEvent op** with `permissions.accessibility_trusted()`; on
`False`, degrade gracefully (fall back to URL prefill only) and surface the
one-time `request_accessibility()` prompt.

---

## 1. Text-box recognition via the Accessibility API

### pyobjc call convention (important)

pyobjc bridges the C out-parameters into the **return tuple**. Pass `None` for
the out-pointer and read the result back:

```python
import ApplicationServices as AX

err, value = AX.AXUIElementCopyAttributeValue(element, AX.kAXValueAttribute, None)
#  err == AX.kAXErrorSuccess (0)  →  value is valid
seterr = AX.AXUIElementSetAttributeValue(element, AX.kAXValueAttribute, "hello")  # returns int err
err, names = AX.AXUIElementCopyActionNames(element, None)                          # list[str]
err = AX.AXUIElementPerformAction(element, AX.kAXPressAction)
```

### Find the currently focused text field

```python
import ApplicationServices as AX

def _attr(el, name):
    err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
    return val if err == AX.kAXErrorSuccess else None

def focused_text_element():
    system = AX.AXUIElementCreateSystemWide()
    el = _attr(system, AX.kAXFocusedUIElementAttribute)     # 'AXFocusedUIElement'
    if el is None:
        return None
    role    = _attr(el, AX.kAXRoleAttribute)                # 'AXRole'
    subrole = _attr(el, AX.kAXSubroleAttribute)             # 'AXSubrole'
    TEXTY = {AX.kAXTextFieldRole, AX.kAXTextAreaRole, AX.kAXComboBoxRole}  # AXTextField/AXTextArea/AXComboBox
    if role in TEXTY or subrole == AX.kAXSearchFieldSubrole:               # 'AXSearchField'
        return el
    return None
```

Verified constants: `kAXTextFieldRole='AXTextField'`, `kAXTextAreaRole='AXTextArea'`,
`kAXComboBoxRole='AXComboBox'`, `kAXSearchFieldSubrole='AXSearchField'`,
`kAXFocusedUIElementAttribute='AXFocusedUIElement'`.

### Read / set the value, insert at the caret

```python
# READ whole value + placeholder
text        = _attr(el, AX.kAXValueAttribute)               # 'AXValue'
placeholder = _attr(el, AX.kAXPlaceholderValueAttribute)    # 'AXPlaceholderValue' (e.g. "Type a message")

# SET whole value (check it's settable first — many web fields aren't)
err, settable = AX.AXUIElementIsAttributeSettable(el, AX.kAXValueAttribute, None)
if settable:
    AX.AXUIElementSetAttributeValue(el, AX.kAXValueAttribute, "full replacement text")

# INSERT AT CARET — set AXSelectedText: replaces the current selection,
# or inserts at the caret when the selection is empty.
AX.AXUIElementSetAttributeValue(el, AX.kAXSelectedTextAttribute, "inserted")   # 'AXSelectedText'

# REPLACE A SPECIFIC RANGE (the portable "AXReplaceRange" — there is NO literal
# kAXReplaceRange attribute; you select the range, then set selected text):
rng = AX.AXValueCreate(AX.kAXValueTypeCFRange, (location, length))  # kAXValueTypeCFRange == 4
AX.AXUIElementSetAttributeValue(el, AX.kAXSelectedTextRangeAttribute, rng)     # 'AXSelectedTextRange'
AX.AXUIElementSetAttributeValue(el, AX.kAXSelectedTextAttribute, "replacement")

# READ the current caret/selection range back:
err, rng_ref = AX.AXUIElementCopyAttributeValue(el, AX.kAXSelectedTextRangeAttribute, None)
ok, cfrange = AX.AXValueGetValue(rng_ref, AX.kAXValueTypeCFRange, None)  # cfrange.location / cfrange.length
```

`AXValueCreate` for a CFRange takes a `(location, length)` tuple in pyobjc;
`AXValueGetValue(ref, kAXValueTypeCFRange, None)` returns `(bool_ok, struct)`
where the struct has `.location` / `.length`.

### Enumerate every text field in the frontmost app + pick "the message box"

```python
from AppKit import NSWorkspace

def frontmost_app_element():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return AX.AXUIElementCreateApplication(app.processIdentifier()), app

def walk(el, depth=0, out=None, max_depth=40):
    out = [] if out is None else out
    if depth > max_depth:
        return out
    out.append(el)
    kids = _attr(el, AX.kAXChildrenAttribute) or []     # 'AXChildren'
    for k in kids:
        walk(k, depth + 1, out, max_depth)
    return out

def text_fields(app_el):
    TEXTY = {AX.kAXTextFieldRole, AX.kAXTextAreaRole, AX.kAXComboBoxRole}
    hits = []
    for el in walk(app_el):
        role, subrole = _attr(el, AX.kAXRoleAttribute), _attr(el, AX.kAXSubroleAttribute)
        if role in TEXTY or subrole == AX.kAXSearchFieldSubrole:
            hits.append(el)
    return hits

def pick_message_box(fields):
    """Heuristics, in priority order."""
    # 1. placeholder mentions message/type/search
    for el in fields:
        ph = (_attr(el, AX.kAXPlaceholderValueAttribute) or "").lower()
        if any(w in ph for w in ("message", "type a", "send a message")):
            return el
    # 2. search box → AXSearchField subrole
    for el in fields:
        if _attr(el, AX.kAXSubroleAttribute) == AX.kAXSearchFieldSubrole:
            return el
    # 3. chat apps: the bottom-most AXTextArea (largest screen-y)
    areas = [el for el in fields if _attr(el, AX.kAXRoleAttribute) == AX.kAXTextAreaRole]
    def y(el):
        pos = _attr(el, AX.kAXPositionAttribute)          # AXValue<CGPoint>
        ok, p = AX.AXValueGetValue(pos, AX.kAXValueTypeCGPoint, None) if pos else (False, None)
        return p.y if ok else -1
    return max(areas, key=y) if areas else (fields[0] if fields else None)
```

### AX-set vs. synthesizing keystrokes — trade-offs

| | AX set (`kAXValue`/`kAXSelectedText`) | Keystroke (CGEvent / System Events) |
|---|---|---|
| Needs field focused-by-click | **No** (target any element directly) | **Yes** (goes to whatever has focus) |
| Speed | Instant, atomic | Per-character, slower |
| Autocomplete/IME/onChange fired | Often **not** (some apps miss the JS event) | Yes — real key events |
| Works on Electron/web contenteditable | Unreliable (see §2) | **Yes, everywhere** |
| Works when app rejects programmatic set | Fails silently | Still works |

**Per-app reliability:**

- **Messages (native AppKit):** AX-set works well; `kAXSelectedTextAttribute`
  insert is reliable. AX-set preferred.
- **Slack / Discord / WhatsApp (Electron):** AX-set into the contenteditable is
  hit-or-miss and often doesn't fire the app's input handler → **keystroke is
  more reliable**, or URL prefill for WhatsApp.
- **Browser inputs (Chrome/Zen/Safari):** Safari exposes a real AX web tree;
  Chromium needs the enable trick (§2). Even then, `kAXValue` set frequently
  doesn't trigger the page's JS → **CGEvent keystroke into the focused field is
  the safe default**.

---

## 2. Electron / browser apps (WhatsApp, Discord, Slack, Chrome/Zen)

### Why their AX trees look empty

Chromium (Chrome, Edge, **and every Electron app** — WhatsApp, Slack, Discord,
VS Code) builds its accessibility tree **lazily**. It stays collapsed to a stub
until it detects an assistive-technology client. Two documented levers:

1. **Set `AXManualAccessibility` = True** on the *application* element
   (`AXUIElementCreateApplication(pid)`). This is Chromium's explicit opt-in
   flag. (Historically apps also watched `AXEnhancedUserInterface`, which
   VoiceOver sets.) Neither is exported as a named `kAX…` constant in pyobjc —
   **pass the literal string.**
2. Any running screen reader (VoiceOver) flips it globally.

```python
def enable_electron_ax(pid):
    app_el = AX.AXUIElementCreateApplication(pid)
    # literal strings — pyobjc does not export these as kAX constants
    AX.AXUIElementSetAttributeValue(app_el, "AXManualAccessibility", True)
    AX.AXUIElementSetAttributeValue(app_el, "AXEnhancedUserInterface", True)
    return app_el
    # THEN POLL — the web/DOM subtree (AXWebArea → AXTextArea/AXTextField)
    # populates asynchronously; give it up to ~1–2 s of ret/retry.
```

### WhatsApp Desktop specifically

Recent WhatsApp Desktop is **Electron**. With `AXManualAccessibility` set and
after the tree builds, the message composer *usually* surfaces as an
`AXTextArea` (occasionally `AXTextField`) inside an `AXWebArea`, sometimes with
placeholder "Type a message". **But it is version-dependent and not guaranteed.**
Fallback order when AX enumeration comes back empty:

1. **Keystroke into the focused window** (the composer already has focus right
   after `whatsapp://send`), or
2. **`whatsapp://send?...&text=` URL prefill** — the path Sheru already uses;
   the most robust for a fully pre-composed message.

### Browser text fields

- **Safari** always exposes a real AX web tree (`AXWebArea` → fields).
- **Chrome / Zen (Chromium):** only after the enable trick above.
- In all cases, **`kAXValue` set often doesn't fire the page's JS onChange**, so
  for browsers prefer **CGEvent keystroke into the focused field**. Use the AX
  tree to *find/focus* the field, use keystroke to *fill* it.

---

## 3. Mouseless clicking ("click the Send button" / "click X")

### Enumerate clickables + AXPress (no mouse movement)

`AXPress` invokes an element's default action in-process — the cursor never
moves. Discover pressable elements by their **action list**, not just role
(canvas widgets, custom controls, and links all differ):

```python
def label_of(el):
    for a in (AX.kAXTitleAttribute, AX.kAXDescriptionAttribute,   # AXTitle / AXDescription
              AX.kAXHelpAttribute, AX.kAXValueAttribute):          # AXHelp / AXValue
        v = _attr(el, a)
        if v:
            return str(v)
    return ""

def pressables(app_el):
    out = []
    for el in walk(app_el):
        err, actions = AX.AXUIElementCopyActionNames(el, None)
        if err == AX.kAXErrorSuccess and actions and AX.kAXPressAction in actions:  # 'AXPress'
            out.append((label_of(el), el))
    return out

def click_by_label(spoken, app_el, cutoff=70):
    from rapidfuzz import fuzz            # already a Sheru dependency
    cands = [(lbl, el) for lbl, el in pressables(app_el) if lbl]
    if not cands:
        return False
    lbl, el = max(cands, key=lambda t: fuzz.WRatio(spoken.lower(), t[0].lower()))
    if fuzz.WRatio(spoken.lower(), lbl.lower()) < cutoff:
        return False
    return AX.AXUIElementPerformAction(el, AX.kAXPressAction) == AX.kAXErrorSuccess
```

Notes: `AXButton`/`AXLink`/`AXMenuItem` are the common pressables. `kAXButtonRole`
is exported; **`AXLink` and `AXWebArea` are NOT exported as named constants** —
match on the literal `"AXLink"` if you filter by role. Filtering by the presence
of `AXPress` in the action list (above) sidesteps role naming entirely.

### Existing tools — what to learn from, what to shell out to

| Tool | License | Maintained | CLI / scriptable? | Takeaway for Sheru |
|---|---|---|---|---|
| **Homerow** (homerow.app) | Closed, **$49.99** one-time, macOS 13+ | Yes (successor to Vimac) | **No** CLI / URL scheme / AppleScript | Best *label-picking UX* reference only; can't be driven programmatically. |
| **Vimac** (github.com/dexterleng/vimac) | **GPL-3.0**, Swift | Archived — "Vimac is now Homerow" | No | **Best readable AX-hinting reference impl** (hint-mode over AX clickables). Read the source. |
| **Shortcat** (shortcat.app) | Closed, macOS 13+ (v0.12.2, Jul 2025) | Yes | No public CLI | Fuzzy command-palette over AX (buttons/fields/menus incl. Electron & browsers) — mirrors exactly Sheru's `click_by_label` design. |
| **Scoot** (github.com/mjrusso/scoot) | **BSD-3-Clause**, Swift/AppKit | **Active (2021–2026)**, `brew install` | No | Element **+ grid + freestyle** modes; BSD = freely reusable reference for the coordinate-click fallback. |

**Conclusion:** none expose a scripting/CLI hook, so Sheru must implement AX
directly. **Vimac (GPL, readable)** and **Scoot (BSD, permissive)** are the two
source references to mine — Vimac for AX hint enumeration, Scoot for the
grid/coordinate fallback.

### Fallback when there's no pressable element (canvas / stubborn Electron)

Compute the element's on-screen center from `AXPosition` + `AXSize` (there's no
exported `kAXFrameAttribute` — read the two, or use the literal `"AXFrame"`), and
synthesize a **real** click there with CGEvent (this *does* move the cursor):

```python
import Quartz as Q

def frame_center(el):
    pos, size = _attr(el, AX.kAXPositionAttribute), _attr(el, AX.kAXSizeAttribute)
    okp, p = AX.AXValueGetValue(pos,  AX.kAXValueTypeCGPoint, None)
    oks, s = AX.AXValueGetValue(size, AX.kAXValueTypeCGSize,  None)
    return (p.x + s.width / 2, p.y + s.height / 2) if (okp and oks) else None

def click_at(x, y):
    src  = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
    down = Q.CGEventCreateMouseEvent(src, Q.kCGEventLeftMouseDown, (x, y), Q.kCGMouseButtonLeft)
    up   = Q.CGEventCreateMouseEvent(src, Q.kCGEventLeftMouseUp,   (x, y), Q.kCGMouseButtonLeft)
    Q.CGEventPost(Q.kCGHIDEventTap, down)
    Q.CGEventPost(Q.kCGHIDEventTap, up)
```

Reliability: coordinate clicks are brittle (break on scroll/resize/Retina point
vs. pixel confusion). **Last resort** before a vision model (screenshot → locate
→ click), which is slow and heavier. Prefer AXPress whenever an element exists.

---

## 4. Focus a specific text field by voice ("focus the search box")

Set `kAXFocusedAttribute = True` on the chosen element. Check it's settable
first; `AXRaise` only raises the *window*, it does not focus a control.

```python
def focus_element(el):
    err, settable = AX.AXUIElementIsAttributeSettable(el, AX.kAXFocusedAttribute, None)  # 'AXFocused'
    if settable and AX.AXUIElementSetAttributeValue(el, AX.kAXFocusedAttribute, True) == AX.kAXErrorSuccess:
        return True
    # fallbacks, in order
    if AX.kAXPressAction in (AX.AXUIElementCopyActionNames(el, None)[1] or []):
        return AX.AXUIElementPerformAction(el, AX.kAXPressAction) == AX.kAXErrorSuccess
    c = frame_center(el)                 # heavy fallback: synthesize a click
    if c:
        click_at(*c); return True
    return False
```

**Reliability:** native AppKit controls honor `kAXFocusedAttribute` reliably.
Some Electron/web fields **ignore it** → fall through to `AXPress`, then to a
coordinate click. So: try focused-set → AXPress → click, in that order.

---

## 5. Recommendation for Sheru's hands-free typing use case

**Scenario:** "open Gaurav's chat and activate typing mode", then speak messages
that get typed + sent. Current code (`messaging.send_whatsapp`) opens
`whatsapp://send?phone=` then does a **blind** `sleep(1.3)` + `System Events`
Return, guarded only by a `frontmost == "WhatsApp"` check. That's fragile: the
wait is a guess, and it can send an empty/half-loaded draft.

WhatsApp is Electron, so ranked approaches by reliability:

1. **URL prefill + AX-verify + AXPress Send (RECOMMENDED for pre-composed
   messages).** Keep the `whatsapp://send?...&text=` prefill Sheru already does.
   Then, instead of `sleep`+Return: poll the AX tree (after `enable_electron_ax`)
   until the message `AXTextArea` exists and its `AXValue` equals the prefilled
   text (proof the draft loaded), then `AXPress` the **Send** `AXButton` found by
   label; fall back to a Return keystroke only if the button isn't found.
   Deterministic — no timing guess.
2. **AX insert + AXPress Send (RECOMMENDED for streaming "typing mode").** For
   dictating *several* messages into an already-open chat: cache the message-box
   element once, and per utterance either set `kAXSelectedTextAttribute`
   (instant) *or* keystroke the text, then `AXPress` Send. Use **AXPress on the
   Send button, not Return** — Return can insert a newline in some composer
   states. Medium reliability; must poll for the box after enabling a11y.
3. **Blind keystroke into the focused window (current) — keep as fallback.**
   Universal; use it whenever AX comes back empty or TCC is not granted.

**TCC call-out (repeat):** all three need the **Sheru.app** Accessibility grant.
Preflight `permissions.accessibility_trusted()` at the top of the typing-mode
entry point; if `False`, do URL-prefill-only and trigger
`permissions.request_accessibility()`. On macOS 26 the grant resets on re-sign,
so re-check every launch.

---

## Recommended implementation order for Sheru

1. **Add `src/sheru/ax.py`** — a thin, verified AX helper layer: `_attr`,
   `set_attr`, `walk`, `focused_text_element`, `text_fields`/`pick_message_box`,
   `insert_at_caret` (`kAXSelectedText`), `pressables`/`click_by_label`,
   `focus_element`, `enable_electron_ax`, `frame_center`/`click_at`. Gate every
   entry point on `permissions.accessibility_trusted()`. (All symbols in this doc
   are verified against the venv's pyobjc 12.2.2.)

2. **Harden `messaging.send_whatsapp`** — after the URL prefill, call
   `enable_electron_ax(pid)`, poll for the message `AXTextArea` whose `AXValue`
   matches the prefilled text, then `AXPress` the Send `AXButton` (fallback:
   Return). Removes the blind `sleep(1.3)` + frontmost guessing.

3. **Add "typing mode"** — `enable_electron_ax` once, cache the composer element,
   and per spoken utterance: insert via `kAXSelectedText` (or keystroke), then
   `AXPress` Send. Keep a keystroke fallback when the AX box can't be found.

4. **Add generic `click_by_label()`** over the frontmost window's AX tree for
   "click Send / click X" voice commands, reusing `rapidfuzz` (already a dep) for
   spoken-label → element matching; coordinate-click fallback via `frame_center`.

5. **Wire TCC preflight + one-time onboarding** — surface
   `permissions.request_accessibility()` from the typing-mode/click entry points
   so the feature degrades to URL-prefill-only (never a hard crash) when the app
   isn't yet trusted, and re-checks on every launch (macOS 26 resets on re-sign).

---

### Appendix — verified constants / symbols (pyobjc 12.2.2, this venv)

- Functions (in `ApplicationServices`, re-exported from `HIServices`):
  `AXUIElementCreateSystemWide`, `AXUIElementCreateApplication`,
  `AXUIElementCopyAttributeValue`, `AXUIElementSetAttributeValue`,
  `AXUIElementIsAttributeSettable`, `AXUIElementPerformAction`,
  `AXUIElementCopyActionNames`, `AXUIElementCopyAttributeNames`,
  `AXUIElementCopyElementAtPosition`, `AXValueCreate`, `AXValueGetValue`,
  `AXIsProcessTrusted`, `AXIsProcessTrustedWithOptions`.
- Attributes: `kAXValueAttribute='AXValue'`, `kAXSelectedTextAttribute='AXSelectedText'`,
  `kAXSelectedTextRangeAttribute='AXSelectedTextRange'`,
  `kAXPlaceholderValueAttribute='AXPlaceholderValue'`,
  `kAXFocusedUIElementAttribute='AXFocusedUIElement'`, `kAXFocusedAttribute='AXFocused'`,
  `kAXRoleAttribute='AXRole'`, `kAXSubroleAttribute='AXSubrole'`,
  `kAXTitleAttribute='AXTitle'`, `kAXDescriptionAttribute='AXDescription'`,
  `kAXHelpAttribute='AXHelp'`, `kAXChildrenAttribute='AXChildren'`,
  `kAXPositionAttribute='AXPosition'`, `kAXSizeAttribute='AXSize'`,
  `kAXEnabledAttribute='AXEnabled'`, `kAXURLAttribute='AXURL'`.
- Roles/subroles: `kAXTextFieldRole='AXTextField'`, `kAXTextAreaRole='AXTextArea'`,
  `kAXComboBoxRole='AXComboBox'`, `kAXButtonRole='AXButton'`,
  `kAXSearchFieldSubrole='AXSearchField'`.
- Actions: `kAXPressAction='AXPress'`, `kAXRaiseAction='AXRaise'`, `kAXConfirmAction='AXConfirm'`.
- Value types: `kAXValueTypeCFRange=4`, `kAXValueTypeCGPoint=1`, `kAXValueTypeCGSize=2`,
  `kAXValueTypeCGRect=3`. Errors: `kAXErrorSuccess=0`, `kAXErrorAPIDisabled=-25211`.
- **Not exported — use string literals:** `"AXFrame"`, `"AXLink"`, `"AXWebArea"`,
  `"AXManualAccessibility"`, `"AXEnhancedUserInterface"`.
- Quartz (CGEvent): `CGEventSourceCreate`, `CGEventCreateMouseEvent`,
  `CGEventCreateKeyboardEvent`, `CGEventKeyboardSetUnicodeString`, `CGEventPost`,
  `CGEventSetFlags`; `kCGHIDEventTap=0`, `kCGEventSourceStateHIDSystemState=1`,
  `kCGMouseButtonLeft=0`, `kCGEventLeftMouseDown=1`, `kCGEventLeftMouseUp=2`.
