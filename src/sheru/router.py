"""Route a transcribed command: Tier 0 regex grammar -> Tier 1 local LLM -> Tier 2 Claude Code."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .actions import apps, browser, browser_agent, files, location, music, system, weather, web


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


# The local model sometimes REFUSES ("I can't browse the internet") and then guesses, instead of escalating.
# Catch that shape in its spoken reply and hand off to Claude (which can actually browse) rather than speak it.
_REFUSAL = re.compile(
    r"\b(?:can'?t|cannot|unable to|not able to|don'?t have)\b[^.?!]*"
    r"\b(?:browse|access|internet|web|real[\s-]?time|current|live|up[\s-]?to[\s-]?date|latest|search|look\s?up)\b"
    r"|\b(?:can'?t|cannot|not able to|unable to)\b[^.?!]*\b(?:provide|give|offer)\b[^.?!]*\badvice\b",
    re.I)

# An 'ask_claude' task that's really just an info question -> handle it LOCALLY (web-search + summarize) instead of
# escalating. Excludes coding/file/action tasks, which genuinely need Claude.
_INFO_Q = re.compile(r"\b(who|what|when|where|which|whose|how much|how many|how old|how tall|how far|how long|"
                     r"price|cost|news|score|latest|current|today|population|capital|exchange rate|worth|"
                     r"define|definition|meaning of|stock|share price)\b", re.I)
_ACTION_Q = re.compile(r"\b(write|create|make|build|code|script|program|file|folder|directory|open|run|execute|"
                       r"fix|refactor|install|delete|remove|move|rename|edit|generate|plot|draw|animate|compile)\b", re.I)


def _looks_informational(task: str) -> bool:
    return bool(_INFO_Q.search(task)) and not _ACTION_Q.search(task)


@dataclass
class Result:
    speech: str = ""              # what to say now
    handoff: str | None = None    # task for Claude Code (Tier 2)
    followup: bool = False        # keep mic open without wake word
    tier: int = 0
    tool: str | None = None       # tool chosen (for the journal)
    args: dict | None = None
    search: str | None = None     # query -> LOCAL web-search + summarize (on-device); escalate to Claude only if it can't answer
    draft: dict | None = None     # {recipient, gist, app} -> app starts a draft/confirm flow
    call: dict | None = None      # {recipient, video, app} -> app starts a CALL confirm flow (never auto-dials)
    open_panel: bool = False      # ask the app to reveal the chat panel (for input impractical by voice, e.g. a link)
    typing: dict | None = None    # {on, recipient, app} -> app enters TYPING mode (speak -> type into the active field)
    resolve_song: str | None = None  # query the app should resolve via Claude, then play
    played: str | None = None        # the song query just played (so "no, wrong song" can re-resolve)
    feedback: str | None = None      # explicit good/bad rating on the PREVIOUS action (judges Sheru's workings)
    artifact: dict | None = None     # {path, request} -> after Claude writes it, offer to run/move it


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
        (re.compile(r"^(?:stop|pause|halt)\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:music|song|playback|track|video|audio)\b.*$"), "media_pause"),
        (re.compile(r"^(?:stop|cancel|never ?mind|shut up|quiet|enough)\b(?!\s+(?:do not disturb|dnd|focus))|^that'?s enough\b|^okay,? that'?s enough\b"), "stop"),
        # TYPING / dictation mode — speak and Sheru types it into the active field (before the generic 'open' rule)
        (re.compile(r"^(?:open|go to|pull up|start)\s+(.+?)(?:'?s)?\s+(?:chat|conversation|whats\s?app|messages?)\s+and\s+(?:then\s+)?(?:activate|enable|start|turn on|begin|go into)\s+(?:the\s+)?(?:typing|dictation|type|hands\s?free)\s+mode$"), "typing_open"),
        (re.compile(r"^(?:activate|enable|start|turn on|begin|go into|switch to)\s+(?:the\s+)?(?:typing|dictation|type|hands\s?free)\s+mode$"), "typing_on"),
        # natural ways to END the conversation — a brief warm ack, and NO follow-up armed so the mic loop stops
        (re.compile(r"^(?:no(?:pe)?|no thanks|no thank you|nothing(?:\s+else)?|that(?:'?s| is| will be| would be) (?:all|it|everything)|i'?m (?:good|done|fine|set|all set)|all good|we'?re good|that (?:will|would) be all|thank you(?:\s+sheru)?|thanks(?:\s+sheru)?|thanks a lot|thank you so much|bye(?:\s+sheru)?|goodbye|see (?:you|ya)|good ?night(?:\s+sheru)?)[.! ]*$"), "end_convo"),
        (re.compile(r"^(?:that (?:was|is)\s+|you (?:did|were)\s+)?(?:very |really |so )?(good|great|perfect|nice|excellent|awesome|well done|correct)\b\.?$"), "feedback_good"),
        (re.compile(r"^(?:that (?:was|is)\s+|you (?:did|were)\s+)?(?:very |really |so )?(bad|wrong|terrible|awful|nope|useless|not good)\b\.?$"), "feedback_bad"),
        (re.compile(r"^(?:set ?up|configure|connect|run setup|start setup)(?:\s+(?:my\s+)?(?:spotify|permissions?|access|sheru|everything|you))?\b.*$"), "setup"),

        (re.compile(r"^(?:go to|open|visit)\s+(?:https?://)?((?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)$"), "url"),
        # start an INTERACTIVE claude session in a directory (zoxide-resolved) — before the trainer rules, which
        # otherwise swallow "start a claude session …"
        (re.compile(r".*\bclaude(?:\s+code)?\s+session\b.*?\b(?:in|at|inside|under|for)\b\s+(.+)$"), "term_claude"),
        (re.compile(r"^(?:open|start|launch|run|fire up)\s+(?:a\s+|an\s+)?claude(?:\s+code)?\b.*?\b(?:in|at|inside|under|for)\b\s+(.+)$"), "term_claude"),
        # self-improvement: open a Claude Code "trainer" session on Sheru's own code (explicit request only)
        (re.compile(r"^(?:get|have|ask|tell|make)\s+(?:your\s+|the\s+)?(?:trainer|claude(?:\s+code)?)\s+(?:to\s+)?(?:fix|improve|debug|change|update|patch|look at|work on|sort out|handle|figure out|look into|retrain)\s+(.+)$"), "trainer"),
        (re.compile(r"^(?:fix|improve|debug|retrain|patch|update)\s+(?:your\s?self|sheru)(?:['’]s)?(?:\s+(.+))?$"), "trainer"),
        (re.compile(r"^(?:fix|improve|debug|change|update|patch)\s+your\s+(.+)$"), "trainer"),
        (re.compile(r"^(?:open|launch|start|bring|fire)\s+(?:up\s+)?(?:your\s+|the\s+|a\s+)?trainer\b.*$"), "trainer"),
        (re.compile(r"^(?:open|launch|start|call|get|bring)\s+(?:up\s+)?(?:a\s+|the\s+|your\s+|new\s+)?(?:new\s+)?(?:dev(?:eloper)?|trainer|training|claude|cloud|this)\s+session\b.*$"), "trainer"),
        # local filesystem (no Claude needed): open a terminal in a dir, make folders/files
        (re.compile(r"^open\s+(?:a\s+|the\s+)?(?:terminal|ghostty|shell|command line|iterm)\s+(?:in|at|inside|here)\b\s*(.*)$"), "terminal_in"),
        (re.compile(r"^(?:make|create|new|touch|add)\s+(?:me\s+)?(?:a\s+|an\s+)?(?:new\s+)?((?:folder|directory|dir|file|text\s*file|txt\s*file|document|\.txt)\b.*)$"), "fs_make"),
        # browser actions (Brave/piyush by default) — BEFORE the generic 'open' so 'open gmail' isn't an app-open
        (re.compile(r"^(?:play|put on|start|search)\s+(.+?)\s+on\s+(?:you ?tube music|yt music)\b.*$"), "yt_music"),
        (re.compile(r"^(?:play|put on|start)\s+(.+?)\s+on\s+(?:you ?tube|yt)\b.*$"), "youtube"),
        (re.compile(r"^(?:you ?tube|yt)\s+(.+)$"), "youtube"),
        (re.compile(r"^(?:play|put on|start)\s+(.+?)\s+(?:on|in)\s+(?:the\s+)?(?:browser|web|zen|brave)$"), "youtube"),
        (re.compile(r"^(?:message|dm|text|write to)\s+(.+?)\s+on\s+linked ?in(?:\s+(?:that|saying|to say)\s+(.+))?$"), "linkedin"),
        (re.compile(r"^(?:open|check|show me|go to)\s+(?:my\s+)?(?:g ?mail|email|inbox)\b.*$"), "gmail_open"),
        (re.compile(r"^(?:email|e-?mail|send an email to|compose an email to)\s+(.+?)(?:\s+(?:that|saying|to say|about)\s+(.+))?$"), "gmail_compose"),
        (re.compile(r"^(?:use|switch to|change to)\s+(?:the\s+)?(sarvam|kokoro|local|apple|system)\s+voice\b.*$"), "set_voice"),
        (re.compile(r"^(?:reply|answer|talk|speak|respond)\s+(?:to me\s+|back\s+)?(?:in|only in)\s+(hindi|english|both|hinglish)\b.*$"), "set_reply_lang"),
        (re.compile(r"^(?:use|switch to|open)\s+(brave|google chrome|chrome|zen|firefox)(?:\s+browser)?$"), "use_browser"),
        (re.compile(r"^(?:use|switch to|go to|open)\s+(?:the\s+)?(.+?)(?:['’]s)?\s+profile\b.*$"), "profile"),
        (re.compile(r"^(?:open|show(?:\s+me)?|pull up|bring up|go to)\s+(?:a\s+|an\s+|the\s+)?wikipedia\s+(?:page\s+|article\s+|entry\s+)?(?:on|about|for|of|regarding)\s+(.+)$"), "wiki_open"),
        # local dictionary (macOS built-in) — instant, offline definition
        (re.compile(r"^(?:define|definition of|meaning of|what'?s\s+(?:the\s+)?(?:meaning|definition)\s+of|what is the meaning of)\s+(.+?)$"), "define"),
        (re.compile(r"^what\s+does\s+(?:the\s+word\s+)?(.+?)\s+mean$"), "define"),
        (re.compile(r"^run(?:\s+the)?\s+shortcut\s+(.+)$|^run(?:\s+the)?\s+(.+?)\s+shortcut$"), "run_shortcut"),
        (re.compile(r"^(?:turn on|enable|start|activate|switch on)\s+(?:do not disturb|dnd)$"), "dnd_on"),
        (re.compile(r"^(?:turn off|disable|stop|end|clear|switch off)\s+(?:do not disturb|dnd|(?:my\s+)?focus|focus mode)$"), "focus_off"),
        (re.compile(r"^set\s+(?:my\s+)?focus\s+to\s+(.+)$|^(?:turn on|enable|switch to|activate|go into)\s+(?:my\s+)?(.+?)\s+focus(?:\s+mode)?$"), "focus_set"),
        (re.compile(r"^(?:what'?s|whats)\s+my\s+(?:current\s+)?focus\??$|^(?:which|what)\s+focus\s+am\s+i\s+in\??$|^am\s+i\s+in\s+(?:a\s+)?focus\??$"), "focus_get"),
        (re.compile(r"^(?:set\s+)?(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(\d{1,3})(?:\s*percent)?$"), "brightness_set"),
        (re.compile(r"^(?:maximi[sz]e|max|full|full ?screen)\s+(?:the\s+)?(?:screen\s+)?brightness$|^(?:set\s+)?(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(?:full|max(?:imum)?|hundred|100)$|^(?:make\s+)?(?:the\s+)?screen\s+brightest$"), "brightness_max"),
        (re.compile(r"^(?:dim|lower|minimi[sz]e|reduce)\s+(?:the\s+)?(?:screen\s+)?brightness$|^dim\s+(?:the\s+)?screen$"), "brightness_min"),
        (re.compile(r"^(?:move|snap|put|shove)\s+(?:this\s+|the\s+|it\s+)?window\s+(?:to\s+the\s+|to\s+)?(left|right|top|bottom)$|^(left|right|top|bottom)\s+half$|^snap\s+(?:it\s+)?(left|right|top|bottom)$"), "window_half"),
        (re.compile(r"^(?:maximi[sz]e|full[\s-]?screen)\s+(?:this\s+|the\s+|it\s+)?window$|^(?:make\s+)?(?:this\s+|it\s+)?(?:window\s+)?full[\s-]?screen$|^maximi[sz]e\s+(?:this|it)$"), "window_max"),
        (re.compile(r"^cent(?:er|re)\s+(?:this\s+|the\s+)?window$"), "window_center"),
        (re.compile(r"^(?:what'?s|whats|what is)\s+(?:on\s+)?(?:my\s+|the\s+)?screen\??$|^(?:read|read out|tell me what'?s on)\s+(?:my\s+|the\s+)?screen(?:\s+(?:to me|out loud|aloud))?\??$|^what does (?:my|the) screen say\??$"), "read_screen"),
        (re.compile(r"^(?:open|launch|start|run)\s+(?:the\s+)?(?!(?:a\s+|an\s+|my\s+)?(?:timer|alarm|stopwatch|reminder|countdown)\b)(?:a\s+|an\s+|my\s+)?(.+?)(?:\s+(?:app|application|browser))?$"), "open"),
        (re.compile(r"^(?:quit|close|kill)\s+(?!all (?:my|the|your) )(?:the\s+)?(.+?)(?:\s+(?:app|application))?$"), "quit"),
        (re.compile(r"^(?:switch|go|jump)\s+to\s+(?:the\s+)?(.+?)\s+profile$"), "profile"),
        (re.compile(r"^(?:use|switch to|search (?:with|on))\s+(google|duck ?duck ?go|bing)\b.*"), "engine"),
        (re.compile(r"^(?:switch|go|jump)\s+(?:over\s+)?(?:me\s+)?to\s+(?:the\s+)?(.+?)(?:\s+(?:app|application))?$"), "switch"),
        (re.compile(r"^(?:show|find|get|search for|google|look up)\s+(?:me\s+)?(?:some\s+|for\s+)?(?:\w+\s+)?(?:pictures?|images?|photos?|pics?)\s+of\s+(.+)$"), "images"),
        (re.compile(r"^(?:set my location to|my location is|i live in|i'?m based in|i just moved to|i'?m now (?:in|at)|i moved to)\s+(.+)$"), "set_location"),
        (re.compile(r"^(?!play\b)(?!.*\bby\b)(?!(?:message|text|msg|whats\s?app|send|remind me)\b).*\bweather\b.*"), "weather"),
        (re.compile(r"^(?!play\b)(?!.*\bby\b)(?!(?:message|text|msg|whats\s?app|send|remind me)\b).*\b(news|headlines?|stocks?|stock price|share price|bitcoin|crypto|ethereum|nasdaq|dow jones|who won|score of|election results?|prime minister|president of|forecast|is it (?:going to )?rain(?:ing)?|will it rain|need an umbrella|temperature (?:outside|right now)|what'?s happening|going on (?:in the world|with the)|current (?:price|events)|population of|gdp of|net worth of|market cap of|how many people (?:live|are) )\b.*"), "current"),
        # currency conversion / exchange rate -> local search+summarize (was escalating to Claude)
        (re.compile(r"^(?!(?:message|text|msg|whats\s?app|send|remind me)\b)(?:.*\b(?:exchange rate|conversion rate)\b.*|.*\b\d+(?:\.\d+)?\s*(?:euros?|dollars?|pounds?|yen|rupees?|usd|eur|gbp|inr|jpy)\b.*\b(?:in|to|into)\b\s*(?:inr|usd|eur|gbp|jpy|rupees?|dollars?|euros?|pounds?|yen)\b.*)"), "current"),
        (re.compile(r"^(?:search|look up|google|find)\s+(?:for\s+)?(.+?)\s+(?:and|then)\s+summari[sz]e.*$"), "search_summarize"),
        (re.compile(r"^summari[sz]e(?:\s+(?:me|it|that|this|them|the results|the search|those))?(?:\s+(.+))?$"), "summarize"),
        # 'how to X' / 'how do I X' -> a YouTube tutorial (NOT play_song; 'how to play raag yaman' isn't a track)
        (re.compile(r"^how\s+(?:do i|to|can i|does one|should i)\s+(.+?)(?:\s+on\s+you\s?tube)?[?.]*$"), "howto"),
        # teach / play a Spotify PLAYLIST (before play_song, which would treat 'X playlist' as a track)
        (re.compile(r"^(?:remember\s+)?(?:that\s+)?(?:my\s+)?(.+?)\s+playlist\s+is\s+(https?://\S+|spotify:\S+)$"), "remember_playlist"),
        (re.compile(r"^remember\s+(?:my\s+|the\s+)?(.+?)\s+playlist\s+(https?://\S+|spotify:\S+)$"), "remember_playlist"),
        (re.compile(r"^(?:play|put on|start|shuffle)\s+(?:my\s+|the\s+)?(.+?)\s+playlist(?:\s+(?:on|in|using)\s+spotify)?$"), "play_playlist"),
        (re.compile(r"^(?:play|put on|put)\s+(?:some\s+|the\s+|a\s+)?(?:song\s+|track\s+)?(.+?)(?:\s+(?:on|in|using)\s+spotify)?$"), "play_song"),
        (re.compile(r"^(.+?)\s+(?:bajao|baja\s?do|chalao|chala\s?do|sunao|suna\s?do|lagao)$"), "play_song"),   # Hinglish 'play X'
        (re.compile(r"^(?:crank|pump)\s+(?:it|the volume|music)?\s*up$"), "vol_up"),
        (re.compile(r"^skip(?:\s+(?:this|it|song|track|forward))?(?:\s+one)?$"), "skip"),
        (re.compile(r"^(?:pull up|bring up)\s+(?:https?://)?((?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)$"), "url"),
        (re.compile(r"^(?:search|google|look up|look for|find)\s+(?:for\s+)?(.+?)(?:\s+on\s+(google|duck ?duck ?go|bing))?$"), "search"),
        (re.compile(r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})(?:\s*percent)?$"), "volume"),
        (re.compile(r"^(increase|raise|bump|boost|decrease|reduce|lower|drop|turn up|turn down)\s+(?:the\s+)?(?:volume|sound|audio)\s+(?:up\s+|down\s+|further\s+)?(?:by\s+)?(\d{1,3})(?:\s*percent)?$"), "volume_by"),
        (re.compile(r"^(?:turn\s+(?:it\s+)?|volume\s+)?(up|down)(?:\s+the\s+(?:volume|sound|music|audio))?$|^(?:turn\s+)?(?:the\s+)?(?:volume|sound|music|audio)\s+(up|down)$|^make\s+it\s+(louder|quieter|softer|lower|loud|quiet|soft|low)$"), "volume_delta"),
        (re.compile(r"^(mute|unmute)\b"), "mute"),
        (re.compile(r"^(play|pause|resume|next|skip|previous|back)(?:\s+(?:song|track|music))?$"), "media"),
        # "schedule … for/at 3 pm" -> a clock-time alarm (only when a real time token is present, else it falls
        # through to Claude). Journal showed "schedule this movie for 3 PM" misfiring into a 180-minute timer.
        (re.compile(r"^schedule\b.*\b(?:at|for)\s+(.*\b(?:a\.?m\.?|p\.?m\.?|o'?clock|quarter|half|past|noon|midnight|\d)\b.*)$"), "alarm"),
        (re.compile(r"^(?:set|start|create|put|begin)?\s*(?:a\s+)?timer\s+(?:for\s+)?(\S+)\s+(minutes?|mins?|seconds?|secs?|hours?)$"), "timer"),
        (re.compile(r"^(?:set|create|put|start)?\s*(?:an?\s+)?alarm\b(?:\s+(?:for|at)\b)?\s*(.*)$"), "alarm"),
        (re.compile(r"^wake me(?:\s+up)?\b(?:\s+(?:at|in)\b)?\s*(.*)$"), "alarm"),
        (re.compile(r"^(?:what(?:'s| is)(?: the)? )?time(?:\s+(?:is it|now|right now))?\??$|^what time (?:is it|now)|^(?:do you have|got|whats|tell me)(?: the)? time\??$|^what'?s the time"), "time"),
        (re.compile(r".*\bclipboard\b.*|^what did i (?:just\s+)?(?:copy|cut)$|^read (?:me )?(?:my|the) copied text$"), "clipboard"),
        (re.compile(r"^((?:write|create|generate|code|build|make|animate|plot|draw|simulate|render)\s+.*\b(?:python|bash|shell|javascript|script|code|program|function|snippet|manim|animation|plot|chart|graph|figure|simulation|demo|numpy|pandas|matplotlib|visuali[sz]ation|algorithm)\b.*)$"), "claude"),
        # read the on-screen WhatsApp conversation (screenshot + Vision OCR)
        (re.compile(r"^what\s+did\s+(.+?)\s+(?:say|reply|text|send|write|message)\b.*$"), "read_chat"),
        (re.compile(r"^(?:read|check|show me)\s+(?:me\s+)?(?:the\s+|my\s+|her\s+|his\s+|their\s+)?(?:whatsapp\s+)?(?:conversation|chat|replies|reply|messages?|texts?)(?:\s+(?:with|from)\s+(.+))?$"), "read_chat"),
        (re.compile(r"^(?:what'?s|any)\s+(?:her|his|their|the)\s+(?:latest\s+)?(?:reply|response|messages?)\b.*$"), "read_chat"),
        # place a WhatsApp CALL (name only, no message) — app shows a Call/Cancel confirm, never auto-dials
        (re.compile(r"^(?:video[\s-]?call|make a video call to|start a video call with)\s+(?!on\b)([a-z][\w'’.\-]*(?:\s+(?!on\b)[a-z][\w'’.\-]*){0,2})(?:\s+on\s+whats\s?app)?$"), "call_video"),
        (re.compile(r"^(?:call up|voice[\s-]?call|make a call to|call|ring|phone|dial)\s+(?!claude\b|the trainer\b|a trainer\b|back\b|it\b|off\b|me\b|9\d\d\b|1\d\d\b)([a-z][\w'’.\-]*(?:\s+(?!on\b)[a-z][\w'’.\-]*){0,2})(?:\s+on\s+whats\s?app)?$"), "call_voice"),
        (re.compile(r"^give\s+([a-z][\w'’.\-]*(?:\s+[a-z][\w'’.\-]*){0,1})\s+a\s+(?:call|ring|buzz)(?:\s+on\s+whats\s?app)?$"), "call_voice"),
        (re.compile(r"^(?:message|text|msg|whatsapp|whats app|send)\s+(?:a\s+(?:message|text)\s+)?(?:to\s+)?([a-z][\w'’.\-]*(?:\s+[a-z][\w'’.\-]*){0,2})\s+(?:that|saying|to say|to tell (?:him|her|them)|about)\s+(.+)$"), "message"),
        (re.compile(r"^(?:message|text|msg|whatsapp|whats app|send)\s+(?:a\s+(?:message|text)\s+)?to\s+([a-z][\w'’.\-]*(?:\s+[a-z][\w'’.\-]*){0,2}?)\s+(.+)$"), "message"),
        (re.compile(r"^(?:message|text|msg|whatsapp|whats app)\s+(\w+)\s+(.+)$"), "message"),
        (re.compile(r"^remind me (?:to |that )?(.+)$"), "remind"),
        (re.compile(r"^(?:remember|note|keep in mind)(?:\s+that)?\s+(?!when\b)(.+)$"), "remember"),
        (re.compile(r"^(?:ask|tell|have|get)\s+claude(?:\s+code)?\s+(?:to\s+)?(.+)$"), "claude"),
    ])

    def route(self, text: str) -> Result:
        self._orig_text = text                 # case-preserved original (Spotify IDs, URLs are case-sensitive)
        t = re.sub(r"[.!?,]+$", "", text.strip().lower())
        t = re.sub(r"^(?:hey\s+)?sheru[,\s]*", "", t).strip()
        t = re.sub(r"\b([\w-]+)\s+dot\s+(com|org|net|io|co|in|dev|app|ai|gov|edu)\b", r"\1.\2", t)
        prev = None                                    # strip polite / filler prefixes so anchored rules still match
        while prev != t:
            prev = t
            t = re.sub(r"^(?:hey|um+|uh+|so|okay|ok|please|kindly|alright|yeah|well|from now on)[,\s]+", "", t).strip()
            t = re.sub(r"^(?:could|can|will|would)\s+(?:you|u)\s+(?:please\s+|kindly\s+|mind\s+)?", "", t).strip()
            t = re.sub(r"^i\s+(?:need|want|would\s+like|'?d\s+like)\s+(?:you\s+)?to\s+", "", t).strip()
            t = re.sub(r"^(?:i\s+wanna|let'?s|lemme|please)\s+", "", t).strip()
        t = re.sub(r"[,\s]+(?:for me|a bit|a little|real quick|please|right away|if you can|thanks)$", "", t).strip()
        if not t:
            return Result("Yes?", followup=True)
        from .actions import calc                       # fast, EXACT local math (before the grammar/LLM); None if not math
        v = calc.calc(t, getattr(self, "_last_calc", None))
        if v is not None:
            self._last_calc = v                          # remember for continued calc ('times 2', 'plus 10', 'add 5 to that')
            return Result(calc.speak_result(v), tool="calc", followup=True)
        if (re.search(r"\b(?:volume|brightness|sound|audio)\b", t) and len(t) < 60
                and not re.match(r"^(?:message|text|tell|send|whats?app|dm|reply|email|ask|remind|note)\b", t)):   # a device command, not a message that happens to mention 'sound'
            from .numwords import replace_number_words     # 'set volume to twenty' -> '... 20' (device cmds only)
            t = replace_number_words(t)
            t = re.sub(r"\s*%", " percent", t)             # Whisper writes 'percent' as '%'; the grammar wants the word
        for pat, kind in self.RULES:
            m = pat.match(t)
            if m:
                res = self._tier0(kind, m)
                if res.tool is None:
                    res.tool = kind          # so the journal logs WHICH action fired, not None, for grammar hits
                return res
        return self._tier1(t)

    def _run_helper(self, shortcut: str, text: str | None, ok_msg: str | None, is_query: bool = False) -> Result:
        """Run a Sheru helper Shortcut (Focus, brightness, …) with its input; degrade gracefully if the user
        hasn't created it yet (I can't make shortcuts from the CLI). tool='focus' keeps it out of rating prompts."""
        from .actions import shortcuts as _sc
        out = _sc.run_shortcut(shortcut, text=text)
        if out is None:
            return Result(f"I need a '{shortcut}' shortcut for that — create it in the Shortcuts app, "
                          "then ask me again.", tool="focus")
        if is_query:
            return Result(out or "You're not in any focus right now.", tool="focus")
        return Result((ok_msg or "Done.") + (f" {out}" if out else ""), tool="focus")

    def _tier0(self, kind: str, m: re.Match) -> Result:
        g = m.groups()
        if kind == "stop":
            return Result("")
        if kind == "end_convo":                            # a warm sign-off; no follow-up -> the mic loop ends
            import random
            return Result(random.choice(["Anytime.", "Sure thing.", "You got it.", "Happy to help.", "Okay!"]))
        if kind == "typing_open":
            return Result("", typing={"on": True, "recipient": g[0].strip(), "app": "whatsapp"})
        if kind == "typing_on":
            return Result("", typing={"on": True, "recipient": None, "app": None})
        if kind == "feedback_good":
            strong = bool(re.search(r"\bvery\b|\bperfect\b|\bexcellent\b|\bawesome\b", m.group(0)))
            return Result("Awesome, thanks!" if strong else "Thanks!", feedback="positive-strong" if strong else "positive")
        if kind == "feedback_bad":
            strong = bool(re.search(r"\bvery\b|\bterrible\b|\bawful\b|\buseless\b", m.group(0)))
            return Result("Sorry about that — I'll learn from it.", feedback="negative-strong" if strong else "negative")
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
        if kind == "term_claude":
            where = (next((x for x in g if x), "") or "").strip()
            r = files.open_terminal_claude(where or None)
            if r == "__ASK_DIR__":
                return Result(f"I couldn't find the {where or 'that'} directory. Where is it? "
                              "Say the full path, like 'open claude in ~/Projects/Afterquery'.")
            return Result(r)
        if kind == "fs_make":
            return Result(files.make(g[0]), followup=True)
        if kind == "quit":
            return Result(apps.quit_app(g[0]))
        if kind == "switch":
            return Result(apps.switch_to(g[0]))
        if kind == "profile":
            return Result(browser.set_profile(g[0]))     # Brave profiles (piyush/moon/...); the automation browser
        if kind == "use_browser":
            return Result(browser.set_browser(g[0]))
        if kind == "set_voice":
            from . import config
            v = g[0]
            if v in ("kokoro", "local"):
                config.set_tts("kokoro"); return Result("Okay, I'll use the local Kokoro voice.")
            if v in ("apple", "system"):
                config.set_tts("avspeech"); return Result("Okay, I'll use the built-in system voice.")
            config.set_tts("sarvam")
            return Result("Okay, I'll use the Sarvam voice." + ("" if config.SARVAM_API_KEY else " Note: no Sarvam key is set."))
        if kind == "set_reply_lang":
            from . import config
            lang = {"hindi": "hi", "english": "en", "both": "auto", "hinglish": "auto"}.get(g[0], "auto")
            config.set_reply_lang(lang)
            return Result({"hi": "I'll reply in Hindi now.", "en": "I'll reply in English now.",
                           "auto": "I'll reply in whichever language you speak."}[lang])
        if kind == "howto":
            q = g[0].strip()
            return Result(f"Here's a tutorial on {q}." if browser_agent.play_youtube(q + " tutorial")
                          else f"I couldn't find a tutorial on {q}.", followup=True)
        if kind == "youtube":
            return Result(browser_agent.play_youtube(next((x for x in g if x), "").strip()), followup=True)
        if kind == "yt_music":
            return Result(browser_agent.play_music(g[0].strip()), followup=True)
        if kind == "define":
            from .actions import dictionary
            word = g[0].strip().strip("?.!,'\"")
            d = dictionary.define(word)
            if d:                                          # instant, local, offline — then invite a follow-up
                return Result(f"{word}: {d}. Is that enough, or would you like more?", followup=True)
            return Result("Let me look that up.", search=location.localize(f"definition of {word}"),
                          tier=1, followup=True)           # not in the dictionary -> local web search
        if kind == "wiki_open":
            import urllib.parse as _u
            topic = g[0].strip().rstrip("?.!")
            web.open_url("https://en.wikipedia.org/wiki/Special:Search?search=" + _u.quote(topic))
            return Result(f"Opening the Wikipedia page on {topic}.")
        if kind == "gmail_open":
            return Result(apps.open_app("Mail"), followup=True)   # Apple Mail (local) has Yash's Gmail — prefer local over the browser
        if kind == "gmail_compose":
            import urllib.parse as _u, subprocess as _s
            who = g[0].strip(); body = (g[1] or "").strip()
            to = who if "@" in who else ""
            _s.run(["open", "mailto:" + _u.quote(to) + (f"?body={_u.quote(body)}" if body else "")], check=False)
            tail = f" to {who}" if to else (f" — add {who}'s email" if who else "")
            return Result(f"Opened a Mail draft{tail}. Review and send.", followup=True)   # Apple Mail (local, has your Gmail)
        if kind == "linkedin":
            import urllib.parse as _u, subprocess as _s
            who = g[0].strip(); msg = (g[1] or "").strip()
            browser.launch("https://www.linkedin.com/search/results/people/?keywords=" + _u.quote(who))
            if msg:
                # safe prefill: message onto the clipboard to paste — no auto-send to a possibly-wrong person
                _s.run(["pbcopy"], input=msg.encode(), check=False)
                return Result(f"Opened {who} on LinkedIn and copied your message to the clipboard — open the chat "
                              "and paste it (Command-V) to send.", followup=True)
            return Result(f"Opened {who} on LinkedIn.", followup=True)
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
            return Result(system.change_volume(15 if d in ("up", "loud", "louder") else -15))
        if kind == "volume_by":
            verb, amt = g[0], int(g[1])
            down = verb in ("decrease", "reduce", "lower", "drop", "turn down")
            return Result(system.change_volume(-amt if down else amt))
        if kind == "media_pause":
            return Result(system.media("pause"))
        if kind == "mute":
            return Result(system.mute(g[0] == "mute"))
        if kind == "run_shortcut":
            from .actions import shortcuts as _sc
            name = next((x for x in g if x), "").strip()
            resolved = _sc.resolve_name(name)
            if not resolved:
                return Result(f"I don't see a shortcut called {name}. Create it in the Shortcuts app first.",
                              tool="run_shortcut")
            out = _sc.run_shortcut(resolved)
            if out is None:
                return Result(f"I couldn't run the {resolved} shortcut.", tool="run_shortcut")
            return Result((f"Done. {out}" if out else f"Ran {resolved}."), tool="run_shortcut")
        if kind == "dnd_on":
            return self._run_helper("Sheru Set Focus", "Do Not Disturb", "Do Not Disturb on.")
        if kind == "focus_off":
            return self._run_helper("Sheru Focus Off", None, "Focus off.")
        if kind == "focus_set":
            mode = next((x for x in g if x), "").strip().title()
            return self._run_helper("Sheru Set Focus", mode, f"{mode} focus on.")
        if kind == "focus_get":
            return self._run_helper("Sheru Get Focus", None, None, is_query=True)
        if kind == "brightness_set":
            pct = str(max(0, min(100, int(next((x for x in g if x), "0")))))   # clamp 0–100
            return self._run_helper("Sheru Set Brightness", pct, f"Brightness set to {pct} percent.")
        if kind == "brightness_max":
            return self._run_helper("Sheru Set Brightness", "100", "Brightness maxed.")
        if kind == "brightness_min":
            return self._run_helper("Sheru Set Brightness", "20", "Screen dimmed.")
        if kind == "window_half":
            d = next((x for x in g if x), "left")
            return Result(system.window(f"{d}-half", f"Snapped {d}."), tool="window")
        if kind == "window_max":
            return Result(system.window("maximize", "Maximized."), tool="window")
        if kind == "window_center":
            return Result(system.window("center", "Centered."), tool="window")
        if kind == "read_screen":
            from .actions import screen
            txt = screen.read_screen()
            if not txt:
                return Result("I couldn't read the screen — grant Sheru Screen Recording in System Settings → "
                              "Privacy & Security if this keeps happening.", tool="read_screen", followup=True)
            return Result(f"Here's what I can see: {txt}", tool="read_screen", followup=True)
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
            raw = re.sub(r"^(?:like|about|around|approximately|maybe|say|roughly|just)\s+", "", raw).strip()
            raw = re.sub(r"^(?:this\s+\w+\s+)?(?:today|tonight)\s+(?:only\s+)?(?:at|for)\s+", "", raw).strip()
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
            # drop only a trailing TIME phrase — 'in/at <time>' — so 'buy milk at the store in 10 min' keeps the store
            _t = (r"\d|a\b|an\b|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|"
                  r"thirty|forty|fifty|half|quarter|couple|few|noon|midnight")
            task = re.sub(rf"\s*\b(?:in|at)\s+(?:{_t}).*$|\s*\b(?:tonight|tomorrow)\b.*$", "", body, flags=re.I).strip()
            task = re.sub(r"^(?:to|that|about|me to|myself to)\s+", "", task).strip()   # 'to call mom' -> 'call mom'
            reminders.schedule(task or "reminder", secs, self.say_async)
            speech = f"Okay, I'll remind you to {task} {human}." if task else f"Okay, I'll remind you {human}."
            return Result(speech)
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
            return Result("Let me check.", search=location.localize(m.group(0)), tier=1, followup=True)
        if kind == "weather":
            raw = m.group(0)
            city = location.describe() or "your area"
            mc = re.search(r"\b(?:in|at|for)\s+([a-z][\w\s]+?)(?:\s+(?:right now|today|now|currently|please))?$", raw)
            if mc and not re.search(r"\b(my|here|location|area|me)\b", mc.group(1)):
                city = mc.group(1).strip().title()        # "weather in tokyo" -> Tokyo, not the profile location
            self.say_async("Checking the weather.")
            from .actions import structured
            w = weather.fetch(city) or structured.weather(raw)   # wttr.in, then Open-Meteo — both keyless, on-device
            if w:
                return Result(w, followup=True)
            return Result("", handoff=f"What is the current weather in {city} right now? "
                          f"Reply with a brief, natural 1-2 sentence spoken summary.", tier=2, followup=True)
        if kind == "search_summarize":
            return Result("On it.", search=location.localize(g[0].strip()), tier=1, followup=True)
        if kind == "summarize":
            topic = (g[0] or "").strip() if g and len(g) > 0 else ""
            if topic:
                q = location.localize(topic)
            elif web.last_query():
                q = web.last_query()
            else:
                return Result("Summarize what? Say, for example, 'summarize the weather in Ravangla'.")
            return Result("On it.", search=q, tier=1, followup=True)
        if kind == "vol_up":
            return Result(system.change_volume(15))
        if kind == "skip":
            return Result(system.media("next"))
        if kind == "remember_playlist":
            orig = getattr(self, "_orig_text", "") or ""      # link case matters — pull it from the original text
            mlink = re.search(r"(https?://\S+|spotify:\S+)", orig)
            uri = music.remember_playlist(g[0].strip(), mlink.group(0) if mlink else g[1].strip())
            if uri:
                return Result(f"Got it — I'll remember your {g[0].strip()} playlist.")
            return Result("That didn't look like a Spotify playlist link. Paste the playlist's share link (Share → Copy link).")
        if kind == "play_playlist":
            name = g[0].strip()
            r = music.play_playlist(name)
            if r == "__NEED_PLAYLIST__":
                # can't paste a link by voice -> open the chat so it's mode-agnostic (type it once, remembered forever)
                return Result(f"I don't have your {name} playlist saved yet. I'll open the chat — paste its "
                              f"Spotify link there (type: {name} playlist is <link>) and I'll remember it.",
                              open_panel=True, followup=True)
            return Result(r, followup=True)
        if kind == "play_song":
            q = g[0].strip()
            if q in {"music", "the music", "song", "a song", "some music", "something", "it", "the song"}:
                return Result(system.media("play"))
            if q in {"a video", "video", "videos", "some video", "a tutorial", "tutorial", "a clip", "clip"}:
                # "play a video" must NOT be treated as a song title (it used to play a random misheard track)
                return Result("A video of what? Say, for example, 'play a CPR tutorial on YouTube'.", followup=True)
            r = music.play_song(q)
            if r == "__RESOLVE_WITH_CLAUDE__":
                if re.search(r"\bspotify\b", m.group(0)):
                    return Result("Let me find that song…", resolve_song=q, followup=True)   # asked for Spotify -> Claude resolves the exact track
                return Result(browser_agent.play_youtube(q), played=q, followup=True)         # generic 'play X' -> reliable YouTube fallback (no dead-end)
            return Result(r, played=q, followup=True)
        if kind == "trainer":
            from .actions import trainer
            issue = next((x for x in g if x), "")
            return Result(trainer.open_trainer(issue))
        if kind == "read_chat":
            from .actions import messaging, whatsapp_read
            who = next((x.strip() for x in g if x), None)
            if who and who.lower() not in ("i", "you", "we", "they", "u"):
                c = messaging.resolve_contact(who)
                if c and c.get("handle"):
                    return Result(whatsapp_read.read_chat_with(c["handle"]), followup=True)
            return Result(whatsapp_read.read_open_chat(), followup=True)
        if kind in ("call_voice", "call_video"):
            who = re.sub(r"\s+on\s+whats\s?app$", "", g[0].strip(), flags=re.I).strip()
            return Result("", call={"recipient": who, "video": kind == "call_video", "app": "whatsapp"})
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
            task = (g[0] or "").strip()
            from .actions import generate
            if generate.looks_generative(task):
                path = generate.mint_path(task)
                return Result("On it — I'll write the code and let you know when it's ready.",
                              handoff=generate.build_task(task, path), tier=2,
                              artifact={"path": str(path), "request": task})
            return Result("On it.", handoff=task, tier=2)
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
            if _REFUSAL.search(d["say"]):                       # it tried to refuse/guess -> LOCAL search first (falls back to Claude)
                return Result("Let me check that for you.", search=location.localize(t), tier=1, followup=True)
            return Result(d["say"], followup=True, tier=1)     # history is recorded centrally by the app (all tiers)
        tool, a = d["tool"], d["args"]
        try:
            if tool == "open_app":     r = apps.open_app(a["name"])
            elif tool == "quit_app":   r = apps.quit_app(a["name"])
            elif tool in ("web_search", "look_up"):             # keep it LOCAL: web-search + on-device summarize
                return Result("Let me check.", search=location.localize(a.get("query", t)), tier=1, followup=True)
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
            elif tool == "call_contact":
                return Result("", call={"recipient": a.get("recipient", ""), "video": bool(a.get("video")), "app": "whatsapp"})
            elif tool == "set_address":
                from .actions import contacts_book
                contacts_book.set_address(a["name"], a["address"])
                r = f"Got it — I'll address {a['name'].strip().title()} as {a['address'].strip().title()} in messages."
            elif tool == "ask_claude":
                task = a["task"]
                if _looks_informational(task):                  # an info question dressed as ask_claude -> local search
                    return Result("Let me check.", search=location.localize(task), tier=1, followup=True)
                return Result("On it.", handoff=task, tier=2)   # genuine coding/file/multi-step work -> Claude
            else:                      return Result("I'll ask Claude.", handoff=t, tier=2)
        except (KeyError, ValueError, TypeError):
            return Result("I'll ask Claude.", handoff=t, tier=2)
        return Result(r, tier=1, tool=tool)     # carry the tool so FIRE_AND_FORGET (no echo re-arm) + the journal are correct
