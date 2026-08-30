"""Single source of truth for Sheru's tool schema (Qwen3/Hermes format). Shared by the LLM,
the journal, and the fine-tuning data pipeline so all three always agree."""
from __future__ import annotations

TOOLS = [
    {"type": "function", "function": {"name": "open_app", "description": "Open or switch to a macOS application",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "quit_app", "description": "Quit a macOS application",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web in the browser",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "image_search", "description": "Show pictures/images of something in the browser",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "open_url", "description": "Open a website URL",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "set_volume", "description": "Set output volume 0-100",
        "parameters": {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]}}},
    {"type": "function", "function": {"name": "media", "description": "Control music playback",
        "parameters": {"type": "object", "properties": {"command": {"type": "string", "enum": ["play", "pause", "next", "previous"]}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "set_timer", "description": "Start a countdown timer",
        "parameters": {"type": "object", "properties": {"seconds": {"type": "integer"}, "label": {"type": "string"}}, "required": ["seconds"]}}},
    {"type": "function", "function": {"name": "look_up", "description": "Answer a question that needs current/live/web info by searching ON-DEVICE and summarizing (news, prices, scores, exchange rates, sports, 'who/what is X now', facts about today). PREFER this over ask_claude for information questions — it keeps things local.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "ask_claude", "description": "Delegate only genuinely hard work to Claude Code: coding, editing/creating files, terminal/bash, or multi-step tasks. Do NOT use for simple info questions — use look_up for those.",
        "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "remember", "description": "Store a fact or preference the user asks you to remember",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "play_song", "description": "Play a specific song or artist on Spotify",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "song and/or artist name"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "draft_message", "description": "Draft and send a text/WhatsApp message to a person; use when the user wants to message/text someone",
        "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "message": {"type": "string", "description": "the gist/intent of what to say"}, "app": {"type": "string", "enum": ["messages", "whatsapp"]}}, "required": ["recipient", "message"]}}},
    {"type": "function", "function": {"name": "call_contact", "description": "Place a WhatsApp voice or video CALL to a person (NOT a text message). Use for 'call X', 'ring X', 'phone X', 'video call X', 'give X a call'. Sheru asks to confirm before it dials.",
        "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}, "video": {"type": "boolean", "description": "true for a video call, false/omit for a voice call"}}, "required": ["recipient"]}}},
    {"type": "function", "function": {"name": "set_address", "description": "Remember how to ADDRESS/greet a specific contact in messages — e.g. a contact saved under a nickname who should be greeted by a different name. Use for 'address X as Y', 'call X Y in messages', 'greet X as Y', 'refer to X as Y'.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "the contact (as the user refers to them)"}, "address": {"type": "string", "description": "how to address them in messages, e.g. Madam"}}, "required": ["name", "address"]}}},
]

TOOL_NAMES = [t["function"]["name"] for t in TOOLS]
