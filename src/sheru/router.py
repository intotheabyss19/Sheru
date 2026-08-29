"""Route a transcribed command: Tier 0 regex grammar -> Tier 1 local LLM -> Tier 2 Claude Code."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .actions import apps, files, location, music, system, weather, web


def _default_msg_app() -> str:
    """Default messaging channel (profile `message_app`, defaults to WhatsApp)."""
    try:
        from . import config
        return config._profile().get("message_app", "whatsapp")
    except Exception:
        return "whatsapp"

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "half": 0.5, "a": 1, "an": 1}


def _num(s: str) -> float:
    s = s.strip().lower()
    return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else NUM.get(s, 1)


@dataclass
class Result:
    speech: str = ""              # what to say now
    handoff: str | None = None    # task for Claude Code (Tier 2)
    followup: bool = False        # keep mic open without wake word
    tier: int = 0
    tool: str | None = None       # tool chosen (for the journal)
    args: dict | None = None
    draft: dict | None = None     # {recipient, gist, app} -> app starts a draft/confirm flow
    resolve_song: str | None = None  # query the app should resolve via Claude, then play
    played: str | None = None        # the song query just played (so "no, wrong song" can re-resolve)


@dataclass
class Router:
    llm: object | None = None                       # judgement LocalLLM (Tier 1)
    fast: object | None = None                       # optional light LocalLLM tried first
    memory: object | None = None                     # instant fact store (recall + remember)
    say_async: Callable[[str], None] = lambda s: None
    history: list[dict] = field(default_factory=list)

    # ---- Tier 0 grammar -------------------------------------------------------
    RULES: list[tuple[re.Pattern, str]] = field(default_factory=lambda: [
        (re.compile(r"^(?:(?:cancel|scratch|forget|stop) that,?\s+(?:actually,?\s+|and\s+(?:then\s+)?)?|(?:no,?\s+)?(?:wait,?\s+)?(?:actually,?|i meant,?|i said,?|scratch that,?|instead,?)\s+)(.+)$"), "correction"),
        (re.compile(r"^(?:what can you do|what do you do|what are you capable of|help|what can i (?:say|ask))\b.*"), "help"),
        (re.compile(r"^(?:are you (?:listening|recording|there)|is recording (?:on|off)|what are you doing)\b.*"), "status"),
        (re.compile(r"^(?:stop|turn off|disable|pause)\s+recording\b.*|^stop saving\b.*"), "rec_off"),
        (re.compile(r"^(?:start|turn on|enable|resume)\s+recording\b.*"), "rec_on"),
        (re.compile(r"^(?:stop|cancel|never ?mind|shut up|quiet)\b"), "stop"),
        (re.compile(r"^(?:set ?up|configure|connect|run setup|start setup)(?:\s+(?:my\s+)?(?:spotify|permissions?|access|sheru|everything|you))?\b.*$"), "setup"),

        (re.compile(r"^(?:go to|open|visit)\s+(?:https?://)?((?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)$"), "url"),
        # self-improvement: open a Claude Code "trainer" session on Sheru's own code (explicit request only)
        (re.compile(r"^(?:get|have|ask|tell|make)\s+(?:your\s+|the\s+)?(?:trainer|claude(?:\s+code)?)\s+(?:to\s+)?(?:fix|improve|debug|change|update|patch|look at|work on|sort out|handle|figure out|look into|retrain)\s+(.+)$"), "trainer"),
        (re.compile(r"^(?:fix|improve|debug|retrain|patch|update)\s+(?:your\s?self|sheru)(?:['’]s)?(?:\s+(.+))?$"), "trainer"),
        (re.compile(r"^(?:fix|improve|debug|change|update|patch)\s+your\s+(.+)$"), "trainer"),
        (re.compile(r"^(?:open|launch|start|bring|fire)\s+(?:up\s+)?(?:your\s+|the\s+|a\s+)?trainer\b.*$"), "trainer"),
        (re.compile(r"^(?:open|launch|start|call|get|bring)\s+(?:up\s+)?(?:a\s+|the\s+|your\s+|new\s+)?(?:new\s+)?(?:dev(?:eloper)?|trainer|training|claude|cloud|this)\s+session\b.*$"), "trainer"),
        # local filesystem (no Claude needed): open a terminal in a dir, make folders/files
        (re.compile(r"^open\s+(?:a\s+|the\s+)?(?:terminal|ghostty|shell|command line|iterm)\s+(?:in|at|inside|here)\b\s*(.*)$"), "terminal_in"),
        (re.compile(r"^(?:make|create|new|touch|add)\s+(?:me\s+)?(?:a\s+|an\s+)?(?:new\s+)?((?:folder|directory|dir|file|text\s*file|txt\s*file|document|\.txt)\b.*)$"), "fs_make"),
        (re.compile(r"^(?:open|launch|start|run)\s+(?:the\s+)?(.+?)(?:\s+(?:app|application|browser))?$"), "open"),
        (re.compile(r"^(?:quit|close|kill)\s+(?!all (?:my|the|your) )(?:the\s+)?(.+?)(?:\s+(?:app|application))?$"), "quit"),
        (re.compile(r"^(?:switch|go|jump)\s+to\s+(?:the\s+)?(.+?)\s+profile$"), "profile"),
        (re.compile(r"^(?:use|switch to|search (?:with|on))\s+(google|duck ?duck ?go|bing)\b.*"), "engine"),
        (re.compile(r"^(?:switch|go|jump)\s+(?:over\s+)?(?:me\s+)?to\s+(?:the\s+)?(.+?)(?:\s+(?:app|application))?$"), "switch"),
        (re.compile(r"^(?:show|find|get|search for|google|look up)\s+(?:me\s+)?(?:some\s+|for\s+)?(?:\w+\s+)?(?:pictures|images|photos)\s+of\s+(.+)$"), "images"),
        (re.compile(r"^(?:set my location to|my location is|i live in|i'?m based in|i just moved to|i'?m now (?:in|at)|i moved to)\s+(.+)$"), "set_location"),
        (re.compile(r"^(?!play\b)(?!.*\bby\b).*\bweather\b.*"), "weather"),
        (re.compile(r"^(?!play\b)(?!.*\bby\b).*\b(news|headlines?|stocks?|stock price|share price|bitcoin|crypto|ethereum|nasdaq|dow jones|who won|score of|election results?|prime minister|president of|forecast|is it (?:going to )?rain(?:ing)?|will it rain|need an umbrella|temperature (?:outside|right now)|what'?s happening|going on (?:in the world|with the)|current (?:price|events))\b.*"), "current"),
        (re.compile(r"^(?:search|look up|google|find)\s+(?:for\s+)?(.+?)\s+(?:and|then)\s+summari[sz]e.*$"), "search_summarize"),
        (re.compile(r"^summari[sz]e(?:\s+(?:me|it|that|this|them|the results|the search|those))?(?:\s+(.+))?$"), "summarize"),
        (re.compile(r"^(?:play|put on)\s+(?:some\s+)?(.+?)(?:\s+(?:on|in|using)\s+spotify)?$"), "play_song"),
        (re.compile(r"^(?:crank|pump)\s+(?:it|the volume|music)?\s*up$"), "vol_up"),
        (re.compile(r"^skip(?:\s+(?:this|it|song|track|forward))?(?:\s+one)?$"), "skip"),
        (re.compile(r"^(?:pull up|bring up)\s+(?:https?://)?((?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)$"), "url"),
        (re.compile(r"^(?:search|google|look up|look for|find)\s+(?:for\s+)?(.+?)(?:\s+on\s+(google|duck ?duck ?go|bing))?$"), "search"),
        (re.compile(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})(?:\s*percent)?$"), "volume"),
        (re.compile(r"^(?:turn\s+(?:it\s+)?|volume\s+)?(up|down)(?:\s+the\s+volume)?$|^(?:turn\s+)?(?:the\s+)?volume\s+(up|down)$"), "volume_delta"),
        (re.compile(r"^(mute|unmute)\b"), "mute"),
        (re.compile(r"^(play|pause|resume|next|skip|previous|back)(?:\s+(?:song|track|music))?$"), "media"),
        (re.compile(r"^(?:set\s+)?(?:a\s+)?timer\s+(?:for\s+)?(\S+)\s+(minutes?|mins?|seconds?|secs?|hours?)$"), "timer"),
        (re.compile(r"^(?:set|create|put|start)?\s*(?:an?\s+)?alarm\b(?:\s+(?:for|at)\b)?\s*(.*)$"), "alarm"),
        (re.compile(r"^wake me(?:\s+up)?\b(?:\s+(?:at|in)\b)?\s*(.*)$"), "alarm"),
        (re.compile(r"^(?:what(?:'s| is) the )?time(?: is it)?\??$|^what time is it|^(?:do you have|got|whats|tell me) the time\??$|^what'?s the time"), "time"),
        (re.compile(r".*\bclipboard\b.*|^what did i (?:copy|cut)$|^read (?:me )?(?:my|the) copied text$"), "clipboard"),
        (re.compile(r"^((?:write|create|generate|code|build|make)\s+.*\b(?:python|bash|shell|javascript|script|code|program|function|snippet)\b.*)$"), "claude"),
        (re.compile(r"^(?:message|text|msg|whatsapp|whats app|send)\s+(?:a\s+(?:message|text)\s+to\s+)?(.+?)\s+(?:that|saying|to say|to tell (?:him|her|them)|about)\s+(.+)$"), "message"),
        (re.compile(r"^(?:message|text|msg|whatsapp|whats app)\s+(\w+)\s+(.+)$"), "message"),
        (re.compile(r"^remind me (?:to |that )?(.+)$"), "remind"),
        (re.compile(r"^(?:remember|note|keep in mind)(?:\s+that)?\s+(?!when\b)(.+)$"), "remember"),
        (re.compile(r"^(?:ask|tell|have|get)\s+claude(?:\s+code)?\s+(?:to\s+)?(.+)$"), "claude"),
    ])

    def route(self, text: str) -> Result:
        t = re.sub(r"[.!?,]+$", "", text.strip().lower())
        t = re.sub(r"^(?:hey\s+)?sheru[,\s]*", "", t).strip()
        t = re.sub(r"\b([\w-]+)\s+dot\s+(com|org|net|io|co|in|dev|app|ai|gov|edu)\b", r"\1.\2", t)
        prev = None                                    # strip polite / filler prefixes so anchored rules still match
        while prev != t:
            prev = t
            t = re.sub(r"^(?:hey|um+|uh+|so|okay|ok|please|kindly|alright|yeah|well)[,\s]+", "", t).strip()
            t = re.sub(r"^(?:could|can|will|would)\s+(?:you|u)\s+(?:please\s+|kindly\s+|mind\s+)?", "", t).strip()
            t = re.sub(r"^i\s+(?:need|want|would\s+like|'?d\s+like)\s+(?:you\s+)?to\s+", "", t).strip()
            t = re.sub(r"^(?:i\s+wanna|let'?s|lemme|please)\s+", "", t).strip()
        t = re.sub(r"[,\s]+(?:for me|a bit|a little|real quick|please|right away|if you can|thanks)$", "", t).strip()
        if not t:
            return Result("Yes?", followup=True)
        for pat, kind in self.RULES:
            m = pat.match(t)
            if m:
                return self._tier0(kind, m)
        return self._tier1(t)

    def _tier0(self, kind: str, m: re.Match) -> Result:
        g = m.groups()
        if kind == "stop":
            return Result("")
        if kind == "help":
            return Result("I can open apps, search the web and summarize, play music, set timers and reminders, "
                          "draft and send messages, remember things, and hand harder tasks to Claude. "
                          "Press F5 and just tell me what you need.")
        if kind == "status":
            from . import recorder
            return Result(f"I only listen when you press F5. Recording is {'on' if recorder.enabled() else 'off'}.")
        if kind == "rec_off":
            from . import recorder
            recorder.set_enabled(False)
            return Result("Okay, I've stopped saving recordings.")
        if kind == "rec_on":
            from . import recorder
            recorder.set_enabled(True)
            return Result("Recording is back on.")
        if kind == "open":
            return Result(apps.open_app(g[0]))
        if kind == "terminal_in":
            return Result(files.open_terminal((g[0] or "").strip() or None))
        if kind == "fs_make":
            return Result(files.make(g[0]), followup=True)
        if kind == "quit":
            return Result(apps.quit_app(g[0]))
        if kind == "switch":
            return Result(apps.switch_to(g[0]))
        if kind == "profile":
            return Result(web.switch_profile(g[0]))
        if kind == "engine":
            return Result(web.set_search_engine(g[0]))
        if kind == "images":
            return Result(web.image_search(g[0]))
        if kind == "search":
            q = g[0].strip()
            eng = g[1].replace(" ", "") if len(g) > 1 and g[1] else None
            if re.fullmatch(r"(?:the\s+web\s+for\s+)?(?:that|this|it|them|those|the results?)", q):
                if web.last_query():          # "search the web for that" -> summarize last topic silently, not a literal tab
                    return Result("On it.", handoff=f"Search the web for '{web.last_query()}' and give a brief spoken summary of the top results.", tier=2, followup=True)
                return Result("Search for what exactly?")
            return Result(web.search(q, eng), followup=True)
        if kind == "url":
            return Result(web.open_url(g[0]))
        if kind == "volume":
            return Result(system.set_volume(int(g[0])))
        if kind == "volume_delta":
            d = next(x for x in g if x)
            return Result(system.change_volume(15 if d == "up" else -15))
        if kind == "mute":
            return Result(system.mute(g[0] == "mute"))
        if kind == "media":
            cmd = {"resume": "play", "skip": "next", "back": "previous"}.get(g[0], g[0])
            return Result(system.media(cmd))
        if kind == "timer":
            mult = 60 if g[1].startswith("m") else 3600 if g[1].startswith("h") else 1
            secs = int(_num(g[0]) * mult)
            return Result(system.set_timer(secs, self.say_async))
        if kind == "alarm":
            from . import reminders, alarms
            raw = next((x for x in g if x), "").strip().rstrip(".")
            if not raw:
                return Result("When should the alarm be? Say 'set an alarm for 7 a.m.' or 'wake me in 20 minutes'.")
            probe = raw if re.search(r"\b(in|at)\b", raw) else f"at {raw}"
            secs, human = reminders.parse_when("alarm " + probe)
            if secs is None:
                return Result(f"I couldn't work out the time from '{raw}'. Try 'set an alarm for 7 a.m.'.")
            alarms.schedule("Alarm", secs, self.say_async, spoken="This is your alarm.")
            return Result(f"Alarm set {human}.", followup=True)
        if kind == "time":
            return Result(system.now())
        if kind == "clipboard":
            c = system.clipboard().strip()
            return Result(f"Clipboard says: {c[:300]}" if c else "Clipboard is empty.")
        if kind == "setup":
            return Result("To set up, click Setup in my menu bar, or run 'uv run sheru setup' in your terminal.")
        if kind == "correction":
            return self.route(g[0].strip())          # treat the correction as a fresh command
        if kind == "remind":
            from . import reminders
            body = g[0].strip()
            secs, human = reminders.parse_when(body)
            if secs is None:
                return Result("When should I remind you? Try 'remind me to call mom in 10 minutes'.")
            task = re.sub(r"\s*\b(in\s+.+|at\s+.+)$", "", body).strip() or body
            reminders.schedule(task, secs, self.say_async)
            return Result(f"Okay, I'll remind you to {task} {human}.")
        if kind == "set_location":
            from . import config
            raw = g[0].strip().rstrip(".")
            if raw.lower() in {"the moment", "the present", "the now", "the past", "the future", "fear",
                               "hope", "denial", "sin", "peace", "the zone", "style", "luxury", "harmony"}:
                return self._tier1(m.string)          # idiom, not a real location
            loc = raw.title()
            config.update_profile("location", loc)
            return Result(f"Got it — I'll use {loc} as your location.")
        if kind == "current":
            return Result("Let me check.", handoff=location.localize(m.group(0)), tier=2, followup=True)
        if kind == "weather":
            raw = m.group(0)
            city = location.describe() or "your area"
            mc = re.search(r"\b(?:in|at|for)\s+([a-z][\w\s]+?)(?:\s+(?:right now|today|now|currently|please))?$", raw)
            if mc and not re.search(r"\b(my|here|location|area|me)\b", mc.group(1)):
                city = mc.group(1).strip().title()        # "weather in tokyo" -> Tokyo, not the profile location
            self.say_async("Checking the weather.")
            w = weather.fetch(city)                       # silent, direct — no browser, no Claude dependency
            if w:
                return Result(w, followup=True)
            return Result("", handoff=f"What is the current weather in {city} right now? "
                          f"Reply with a brief, natural 1-2 sentence spoken summary.", tier=2, followup=True)
        if kind == "search_summarize":
            topic = location.localize(g[0].strip())
            return Result("On it.", handoff=f"Search the web and give a brief spoken summary of: {topic}", tier=2, followup=True)
        if kind == "summarize":
            topic = (g[0] or "").strip() if g and len(g) > 0 else ""
            if topic:
                task = f"Search the web and give a brief spoken summary of: {location.localize(topic)}"
            elif web.last_query():
                task = f"Search the web for '{web.last_query()}' and give a brief spoken summary of the top results."
            else:
                return Result("Summarize what? Say, for example, 'summarize the weather in Ravangla'.")
            return Result("On it.", handoff=task, tier=2, followup=True)
        if kind == "vol_up":
            return Result(system.change_volume(15))
        if kind == "skip":
            return Result(system.media("next"))
        if kind == "play_song":
            q = g[0].strip()
            if q in {"music", "the music", "song", "a song", "some music", "something", "it", "the song"}:
                return Result(system.media("play"))
            r = music.play_song(q)
            if r == "__RESOLVE_WITH_CLAUDE__":
                return Result("Let me find that song…", resolve_song=q, followup=True)
            return Result(r, played=q, followup=True)
        if kind == "trainer":
            from .actions import trainer
            issue = next((x for x in g if x), "")
            return Result(trainer.open_trainer(issue))
        if kind == "message":
            if re.search(r"whats\s?app", m.group(0)):
                app_kind = "whatsapp"
            elif re.search(r"\b(imessage|sms|text message)\b", m.group(0)):
                app_kind = "messages"
            else:
                app_kind = _default_msg_app()
            return Result("", draft={"recipient": g[0].strip(), "gist": g[1].strip(), "app": app_kind})
        if kind == "remember":
            msg = self.memory.remember(g[0]) if self.memory else "I don't have a memory store yet."
            return Result(msg)
        if kind == "claude":
            return Result("On it.", handoff=g[0], tier=2)
        return Result("Hmm.")

    # ---- Tier 1 local LLM -----------------------------------------------------
    def _tier1(self, t: str) -> Result:
        if self.llm is None and self.fast is None:
            return Result("Let me check.", handoff=t, tier=2)
        hist = self.history[-6:]
        mem_ctx = self.memory.context_block(t) if self.memory else ""
        model = self.fast or self.llm
        d = model.decide(t, hist, extra_system=mem_ctx)
        self._last_tool = None
        # light tier unsure -> let the judgement model decide before escalating to Claude
        if self.fast is not None and self.llm is not None and (d.get("tool") == "ask_claude" or "say" in d):
            d = self.llm.decide(t, hist, extra_system=mem_ctx)
        if "say" in d:
            return Result(d["say"], followup=True, tier=1)     # history is recorded centrally by the app (all tiers)
        tool, a = d["tool"], d["args"]
        try:
            if tool == "open_app":     r = apps.open_app(a["name"])
            elif tool == "quit_app":   r = apps.quit_app(a["name"])
            elif tool == "web_search": r = web.search(a["query"])
            elif tool == "image_search": r = web.image_search(a["query"])
            elif tool == "open_url":   r = web.open_url(a["url"])
            elif tool == "set_volume": r = system.set_volume(int(a["percent"]))
            elif tool == "media":      r = system.media(a["command"])
            elif tool == "set_timer":  r = system.set_timer(int(a["seconds"]), self.say_async, a.get("label", "timer"))
            elif tool == "remember": r = self.memory.remember(a["text"]) if self.memory else "No memory store."
            elif tool == "play_song":
                r = music.play_song(a["query"])
                if r == "__RESOLVE_WITH_CLAUDE__":
                    return Result("Let me find that song…", resolve_song=a["query"], followup=True)
            elif tool == "draft_message":
                return Result("", draft={"recipient": a.get("recipient", ""), "gist": a.get("message", a.get("gist", "")), "app": a.get("app") or _default_msg_app()})
            elif tool == "ask_claude": return Result("On it.", handoff=a["task"], tier=2)
            else:                      return Result("I'll ask Claude.", handoff=t, tier=2)
        except (KeyError, ValueError, TypeError):
            return Result("I'll ask Claude.", handoff=t, tier=2)
        return Result(r, tier=1)
