# macOS Shortcuts — Power-User Brief (tailored for Yash)

**Machine:** MacBook Air M5, 16 GB, macOS 26 Tahoe. Lives in Ghostty + Claude Code. Building **Sheru** (local voice assistant) which already has a `run_shortcut` bridge (`shortcuts run "<name>"`).

**How to read this:** everything below is checked for **macOS** (not iOS). Confidence is marked:
- **[Mac ✓]** confirmed available on macOS Tahoe
- **[Mac?]** believed available — verify in your Automation/actions list before relying on it
- **[iOS-only]** exists on iPhone/iPad, NOT on Mac — don't build around it

**The one rule that governs "Sheru-bindable":** `shortcuts run` **hangs** if the shortcut pops an interactive dialog — an **Ask for Input**, a confirmation alert, a "Choose from Menu", or a permission prompt. So *Sheru-bindable = no interactive prompt + no alert*. Passing data **in** via `shortcuts run -i` / a **Shortcut Input** parameter is fine — that is NOT a prompt. Keep helper shortcuts silent.

---

## Top 10 worth setting up first

| # | Shortcut / Automation | What it does | Effort | Trigger | Sheru-bindable |
|---|---|---|---|---|---|
| 1 | **Start Work** launcher | Opens Ghostty + Docker + Zen + Obsidian + Spotify, sets **Work** Focus, sets volume | Med | Keyboard / menu-bar / Sheru | **Y** |
| 2 | **Night wind-down** | ~2:30am: **Sleep/DND** Focus on, appearance → Dark, volume down, Low Power on | Low | Automation (Time of Day) | Y (body) |
| 3 | **Sheru Focus** set/off/get | Focus on by name / off / speak current — the top scripting gap | Low | Sheru / menu-bar | **Y** |
| 4 | **NITS-WiFi profile** | On joining the college network: set a Focus + notify (+ optionally flip Sheru to browser tier) | Med | Automation (Wi-Fi) | N (trigger) |
| 5 | **OCR the screen** ("read this") | Self-captures the screen, extracts text, copies/speaks it | Low | Sheru / keyboard | **Y** |
| 6 | **Toggle Dark Mode** | Flip Light/Dark instantly | Low | Keyboard / menu-bar / Sheru | **Y** |
| 7 | **Batch resize/convert images** | Right-click images in Finder → resized/converted copies | Low | Quick Action | N |
| 8 | **Screenshots watcher** | New file in screenshots folder → auto-OCR to clipboard / rename | Med | Automation (Folder) | N |
| 9 | **Run on server (SSH)** | One command over SSH to your box/RunPod, speaks result | Med | Keyboard / Sheru | **Y** |
| 10 | **Now Playing (Spotify)** | Speaks/shows current Spotify track via AppleScript | Low | menu-bar / Sheru | **Y** |

**Standouts that pay off even without Sheru** (self-running or one keypress): #2 night wind-down and #4 NITS-WiFi (run themselves), #8 screenshots watcher (self-running), #6 dark-mode and #1 Start Work (one global keypress), #7 image Quick Action (one right-click).

---

## 1. Personal Automations on Mac

macOS Tahoe ships a **Mac-specific** trigger set (it did not just port the iOS list). **Big Mac advantage:** most Mac automations can be set to **"Run Immediately"** so they fire **silently, no confirmation** — unlike the tap-to-confirm default iOS long had. Set this per automation (and untick "Notify When Run" if you want zero UI).

### Triggers that actually exist on macOS

| Trigger | Status | Fires when… |
|---|---|---|
| **Time of Day** | Mac ✓ | A set time, repeat daily/weekly/monthly |
| **Wi-Fi** | Mac ✓ | Mac joins a named network (home vs NITS-WiFi) |
| **Bluetooth** | Mac ✓ | A device connects/disconnects (e.g. headphones) |
| **Focus** | Mac ✓ | A named Focus turns on / off |
| **Battery Level** | Mac ✓ | Battery rises above / falls below a threshold |
| **Charger** | Mac ✓ | Mac connects to / disconnects from power |
| **External Drive** | Mac ✓ | A drive is connected / disconnected |
| **Display** | Mac ✓ | A display is connected / disconnected |
| **Stage Manager** | Mac ✓ | Stage Manager turns on / off |
| **App** | Mac ✓ | An app **opens or quits** (e.g. Docker Desktop) |
| **Folder** | Mac ✓ | A folder's **contents change** (new/removed file) |
| **File** | Mac ✓ | A specific file is **modified** |
| **Email** | Mac ✓ | You receive mail from chosen senders / matching subject |
| **Message** | Mac ✓ | You receive a message from chosen people / matching text |

### NOT on Mac — don't build around these
- **[iOS-only] Arrive / Leave / location** — **no reliable location trigger on Mac.** This is the biggest gap vs iPhone; there's no "when I get to college" automation on the Air. (Approximate it with the **Wi-Fi** trigger instead — see #4.)
- **[iOS-only]** Alarm (Mac has no Clock alarms), CarPlay, Airplane Mode, NFC tag, Sleep/Wake-schedule, Reminders-as-trigger, Wallet transaction, Workout.
- **[Mac?]** "Sunrise/sunset" as a Time-of-Day option — treat as iOS-flavored; use a fixed clock time on Mac.
- There is **no Shortcuts trigger for screen lock/unlock or Mac wake** — use a login item, `sleepwatcher`, or an Automator/EventScripts hook if you need those.

### High-value automations, tailored

**Night wind-down (Time of Day ~2:30am)** — you work late. One shortcut body: **Set Focus** → Sleep (or DND) on · **Set Appearance** → Dark · **Set Volume** → low · (optionally) **Run Shell Script** to enable Low Power. Set the automation to **Run Immediately**. The *body* is Sheru-bindable too, so "goodnight" can trigger it manually.

**Morning boot (Time of Day ~11am, or first Wi-Fi-join of the day)** — Set Focus → Work · open your daily apps · speak/print today's calendar. Overlaps with **Start Work** (§3) — build the launcher once, call it from both.

**NITS-WiFi vs home (Wi-Fi trigger)** — you hop between home Wi-Fi and the firewalled **NITS-WiFi**. Two automations:
- *Join NITS-WiFi* → set a "College" Focus, notify, and (killer combo) run a shortcut/`sheru trigger` that flips Sheru's router to the **browser-fallback tier** you already built for the Sophos CA — so Sheru degrades gracefully the moment you hit campus, automatically.
- *Join home Wi-Fi* → restore normal Focus / model tier / mount anything you only use at home.
This is the Mac stand-in for the location trigger you can't have.

**Docker open (App trigger)** — *When Docker Desktop opens* → set **Work** Focus, and/or `Run Shell Script` to `docker compose up -d` a default stack, and/or start Sheru if not running. *When it quits* → tear down. (New in the Tahoe trigger set — verify it lists Docker Desktop.)

**Battery / charger (you cap charge at 80%)** — because it won't charge past 80, **charge-*up* automations are low value** for you. The useful ones are the other direction: *Battery falls below 20%* → notify (or `sheru trigger` a spoken warning via the socket) + Set Appearance/dim; *Disconnects from power* → dim brightness + Low Power on; *Connects to power* → restore brightness. Battery-level and Charger are separate triggers — use Charger for plug/unplug, Battery Level for thresholds.

**Screenshots / Downloads watcher (Folder trigger — new & underused)** — point a **Folder** automation at your screenshots dir (or `~/Downloads`): on a new file, `Run Shell Script` to auto-rename by date, move by type, or pipe images through **Extract Text from Image** and drop the OCR next to them. Genuinely hands-off; a real power move now that Mac has a Folder trigger.

**External Drive / Display triggers** — *drive connects* → run a `rsync`/`restic` backup shortcut; *external display connects* → set a Focus + a window arrangement (or your Rectangle layout). Both are Mac ✓.

---

## 2. Quick Actions (Finder right-click / Services)

Make one by ticking **"Use as Quick Action"** in a shortcut's info panel → enable **Finder** and/or **Services Menu**, and set **"Receive [Images / Files / Folders / PDFs / Text] from Quick Actions."** It then appears in right-click → **Quick Actions**, in the **Services** menu, and can be dragged onto the Finder toolbar. *Selection-driven, so generally NOT Sheru-bindable — but excellent one-right-click tools.*

**Genuinely useful for you:**
- **Batch resize / convert images** — actions **Resize Image** + **Convert Image** (JPEG/PNG/HEIF/WebP) [Mac ✓]. Perfect for shrinking screenshots before they go into docs. → top-3 Quick Action.
- **Combine images → PDF / Make PDF** — **Make PDF** [Mac ✓]. Merge is native; **split** and **compress** have **no dedicated action** → do those with **Run Shell Script** (`qpdf`, or Ghostscript for compress). [Mac? for a built-in compress — assume no, use shell.]
- **OCR image → clipboard** — **Extract Text from Image** [Mac ✓] then **Copy to Clipboard**. Right-click any screenshot to lift its text. Also the engine behind Sheru's "read this" (§5).
- **Convert audio/video** — **Encode Media** / **Trim Media** [Mac ✓] handle basic re-encodes. For real ffmpeg control, **Run Shell Script** with `ffmpeg`.
- **New Ghostty / VS Code here** — **Run Shell Script** receiving *folders*: `open -a Ghostty "$@"` or `open -a "Visual Studio Code" "$@"` (or `code "$1"`). macOS also ships a built-in **"New Terminal at Folder"** Service (enable in System Settings → Keyboard → Keyboard Shortcuts → Services).
- **Strip metadata (EXIF)** — **no native action**; **Run Shell Script** with `exiftool -all= "$@"` (or `sips` for a partial strip). [Mac? native — no.]

**Skip — the OS already does these better:**
- **Batch rename** — Finder's built-in *Select → right-click → Rename* is better than anything Shortcuts offers (Shortcuts has no solid rename-file action on Mac).
- **Copy path** — Finder already has **Option-right-click → "Copy … as Pathname"**. Don't rebuild it.

---

## 3. Menu-bar + keyboard-shortcut Shortcuts

In a shortcut's info panel you can tick **"Pin in Menu Bar"** and **"Add Keyboard Shortcut"** (global hotkey). Same shortcut can be all three (menu-bar + hotkey + Quick Action). These are the "one keypress" wins.

- **Start Work** [Mac ✓, **Sheru-bindable Y**] — **Open App** ×(Ghostty, Docker, Zen, Obsidian, Spotify) + **Set Focus** Work + **Set Volume**. Give it a hotkey *and* pin it. This is your #1 build.
- **Toggle Dark Mode** [Mac ✓, **Y**] — **Set Appearance** → Toggle (or Get Appearance → conditional). Global hotkey. [Set Appearance is a real macOS action even though some action lists omit it.]
- **Set Focus / Focus Off / Get Focus** [Mac ✓, **Y**] — the `Sheru Set Focus` / `Sheru Focus Off` / `Sheru Get Focus` helpers already in your integration plan. Pin **Get Focus** to the menu bar for an at-a-glance readout.
- **Set Brightness / Set Volume** [Mac ✓, **Y**] — you already spec'd `Sheru Set Brightness` (brightness has no clean CLI path, so the Shortcut is the way). Same pattern for volume.
- **Now Playing (Spotify)** [Mac ✓ via AppleScript, **Y**] — no native Spotify action; **Run AppleScript**: `tell application "Spotify" to return name of current track & " — " & artist of current track`. Pin it / bind it. (Music.app has a native "Get Current Song"; Spotify needs the AppleScript.)
- **Join next meeting** [Mac? partial] — **Find Calendar Events** (next event) → extract the URL from notes/location → **Open URLs**. Works if your invites carry a link; flaky otherwise. Don't over-invest.
- **Window arrangements** — you already use **Rectangle** (with its URL scheme enabled) for this and it's better than Shortcuts' window actions. Keep window layout in Rectangle, not Shortcuts.

---

## 4. Developer-specific

All confirmed on macOS. **Gotcha:** Run Shell Script needs **Settings → Shortcuts → Advanced → Allow Running Scripts = ON** (you noted this already). Each shortcut also asks once, the first time, to permit its script — after that it's silent (so still Sheru-bindable once approved).

- **Run Shell Script** [Mac ✓] — the workhorse. Input as **stdin** or **as arguments** (`$1`, `"$@"`). Defaults to `/bin/zsh`.
- **Run AppleScript** [Mac ✓] and **Run JavaScript for Mac Automation (JXA)** [Mac ✓] — for app control (Spotify, frontmost-window ops, etc.).
- **Run Script Over SSH** [Mac ✓] — **the standout for you.** Connect to a host + run a command, get stdout back — no local ffmpeg/GPU needed. Build "check RunPod GPU", "tail my server log", "restart <service>" as fixed-command shortcuts → **Sheru-bindable Y** (fixed command, no prompt). Store the key/host in the action.
- **Kill a port** [Mac ✓, **Y if port fixed / passed via -i**] — Run Shell Script: `lsof -ti tcp:${1:-3000} | xargs -r kill -9`. Fixed port → Sheru-bindable; variable → have Sheru pass the number as **Shortcut Input**.
- **Project / git launchers** [Mac ✓, **Y**] — Run Shell Script: `cd ~/Projects/Sheru && git fetch && git status -sb` (print to output). Or open-in-editor: `code ~/Projects/<name>`. Fixed path → bindable; pick-from-list → **not** bindable (menu prompt hangs the CLI).
- **Quick capture → Obsidian** [Mac ✓, **Y via Shortcut Input**] — take **Shortcut Input** text and `Run Shell Script`: `printf '\n- %s\n' "$1" >> "/Users/yash/.../DailyNote.md"` (or use Obsidian's `obsidian://` URI via **Open URLs**). Because input arrives via `-i`, not an Ask dialog, Sheru can say "note: <thing>" → bindable.
- **Skip:** the **Use Model** (Apple Intelligence) action — redundant with your local LLM + Claude, as you already flagged.

---

## 5. The Sheru angle — binding cheat-sheet

*Bindable = alert-free + no interactive Ask (input via `-i` / Shortcut Input is fine).*

| Item | Sheru-bindable? | Why |
|---|---|---|
| Set/Off/Get Focus | **Y** | Silent; value passed as input |
| Start Work launcher | **Y** | Opens apps + sets state, no prompt |
| Toggle Dark Mode (Set Appearance) | **Y** | No input, no alert |
| Set Brightness / Set Volume | **Y** | Number via Shortcut Input |
| Now Playing (Spotify AppleScript) | **Y** | Outputs text |
| OCR the screen (self-capture) | **Y** | Shortcut runs `screencapture` itself → no Finder selection needed |
| Run over SSH (fixed command) | **Y** | Deterministic, no prompt |
| Kill port / git status / open project | **Y** *if* path/port fixed or passed via `-i` | A *pick-from-menu* variant hangs the CLI |
| Obsidian quick capture | **Y** | Text via `-i`, no Ask dialog |
| Night wind-down (shortcut body) | **Y** | Runnable manually as "goodnight" |
| Resize/convert image, Make PDF, New-terminal-here | **N** | Need a Finder **selection** — build as **Quick Actions** |
| Any automation *trigger* (Wi-Fi, Folder, Battery…) | **N/A** | Triggers fire themselves; only their *bodies* can be Sheru-run |
| Anything with **Ask for Input / Choose from Menu / alert** | **N** | Interactive dialog hangs `shortcuts run` |

**Design tip for Sheru helpers:** self-source your inputs (screencapture inside the shortcut, fixed hosts/ports/paths) and route any variable data through **Shortcut Input** so Sheru passes it with `-i` — never leave an *Ask* action in a shortcut Sheru will call.

---

## Setup mechanics (quick reference)

- **Make a Quick Action:** shortcut → **ⓘ** info panel → tick **Use as Quick Action** → **Finder** + **Services Menu** → set **Receive … from Quick Actions**.
- **Menu-bar / hotkey:** same info panel → **Pin in Menu Bar** and/or **Add Keyboard Shortcut**.
- **Automation:** Shortcuts → **Automation** tab → **+** → pick a trigger above → set **Run Immediately** (and untick Notify) for silent firing.
- **Run Shell Script:** **Settings → Advanced → Allow Running Scripts = ON** (one-time), then approve each script once.
- **From Sheru / terminal:** `shortcuts run "Name"` · pass input `-i <path|->` · capture `-o <path|->` or pipe with `|` · list names `shortcuts list`. Apple's own note: *"the most efficient shortcuts are ones that don't show alerts or ask for input"* — exactly the Sheru constraint.

---

*Sources: Apple Shortcuts User Guide for Mac (command-line + automation pages), the Tahoe-current Shortcuts action/trigger guide at blakecrosley.com/guides/shortcuts, MacStories/Matthew Cassinelli coverage, plus prior Sheru integration notes (`docs/SHORTCUTS-INTEGRATION.md`). Items marked [Mac?] should be verified in your own Automation/actions list before you depend on them.*
