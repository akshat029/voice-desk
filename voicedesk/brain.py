import json
import logging

import httpx

from voicedesk.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_URL,
    LLM_BACKEND,
    MAX_HISTORY,
    OLLAMA_MODEL,
    OLLAMA_URL,
    REQUEST_TIMEOUT,
    supports_vision,
)

SYSTEM_PROMPT = (
    "You are VoiceDesk, a personal desktop automation assistant like Jarvis. "
    "The user gives voice commands. You may receive OCR text or a "
    "screenshot of the current screen as context.\n"
    "Return ONLY a valid JSON array of actions. Never return "
    "explanations or markdown.\n"
    "IMPORTANT: You MUST always include at least one 'speak' action "
    "so the user hears your response. For questions, speak the answer. "
    "For tasks, confirm what you are doing (e.g. 'Opening Chrome for you'). "
    "Be conversational, friendly, and concise.\n\n"
    "Supported actions:\n"
    '  {"action":"click","x":N,"y":N}\n'
    '  {"action":"double_click","x":N,"y":N}\n'
    '  {"action":"right_click","x":N,"y":N}\n'
    '  {"action":"move","x":N,"y":N}\n'
    '  {"action":"scroll","x":N,"y":N,"clicks":N}\n'
    '  {"action":"drag","x":N,"y":N,"duration":N}\n'
    '  {"action":"type","text":"..."}\n'
    '  {"action":"press","keys":["enter"]}\n'
    '  {"action":"hotkey","keys":["ctrl","c"]}\n'
    '  {"action":"open_app","name":"chrome"}\n'
    '  {"action":"speak","text":"..."}\n'
    '  {"action":"wait","seconds":N}\n\n'
    "Respond with ONLY a JSON array. Be precise with coordinates "
    "using screen context."
)

# ── Conversational Memory ────────────────────────────────────

_chat_history: list[dict] = []


def _trim_history() -> None:
    global _chat_history
    if len(_chat_history) > MAX_HISTORY * 2:
        _chat_history = _chat_history[-(MAX_HISTORY * 2):]


# ── JSON Extraction ──────────────────────────────────────────


def _extract_actions(raw_text: str) -> list[dict]:
    """Parse a JSON action array from potentially messy LLM output."""
    text = raw_text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"LLM did not return valid JSON: {text[:200]}")
        parsed = json.loads(text[start : end + 1])
    if isinstance(parsed, dict):
        if isinstance(parsed.get("actions"), list):
            parsed = parsed["actions"]
        else:
            parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("LLM response was not a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


# ── Message Building ─────────────────────────────────────────


def _build_messages(command_text: str, context: dict) -> list[dict]:
    """Build the message list for the LLM, adapting to the active backend."""
    import voicedesk.config as cfg
    backend = cfg.LLM_BACKEND

    system_msg = {"role": "system", "content": SYSTEM_PROMPT}
    parts = [f"Command: {command_text}"]
    screen_text = context.get("screen_text")
    if screen_text:
        parts.append(f"Screen text (OCR):\n{screen_text}")
    user_text = "\n\n".join(parts)

    screenshot_b64 = context.get("screenshot_base64") if supports_vision() else None

    if backend == "gemini":
        # Gemini messages are handled separately in _post_gemini
        user_msg = {"role": "user", "content": user_text, "_screenshot_b64": screenshot_b64}
    elif backend == "groq" and screenshot_b64:
        user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                },
            ],
        }
    else:
        user_msg = {"role": "user", "content": user_text}
        if screenshot_b64:
            user_msg["images"] = [screenshot_b64]

    # Include conversation history
    all_messages = [system_msg] + list(_chat_history) + [user_msg]
    return all_messages


# ── Backend POST Helpers ─────────────────────────────────────


def _post_ollama(messages: list[dict]) -> str:
    clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
    resp = httpx.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": clean,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _post_groq(messages: list[dict]) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set in .env")
    import voicedesk.config as cfg
    clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body: dict = {
        "model": cfg.GROQ_MODEL,
        "messages": clean,
        "temperature": 0,
        "max_tokens": 1024,
    }
    resp = httpx.post(GROQ_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _post_gemini(messages: list[dict]) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set in .env")
    import base64
    import voicedesk.config as cfg

    # Build Gemini content parts
    contents = []
    for msg in messages:
        role = msg["role"]
        if role == "system":
            contents.append({"role": "user", "parts": [{"text": f"[System] {msg['content']}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        elif role == "user":
            parts = []
            text = msg.get("content", "")
            if isinstance(text, str):
                parts.append({"text": text})
            screenshot = msg.get("_screenshot_b64")
            if screenshot:
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": screenshot,
                    }
                })
            contents.append({"role": "user", "parts": parts})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg.get("content", "")}]})

    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
        json={"contents": contents, "generationConfig": {"temperature": 0}},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _post(messages: list[dict]) -> str:
    import voicedesk.config as cfg
    backend = cfg.LLM_BACKEND
    if backend == "gemini":
        return _post_gemini(messages)
    if backend == "groq":
        return _post_groq(messages)
    return _post_ollama(messages)


# ── Public API ───────────────────────────────────────────────


def plan_actions(command_text: str, context: dict) -> list[dict]:
    """Send command + context to the LLM and return an action list."""
    messages = _build_messages(command_text, context)
    first = _post(messages)
    logging.info(f"LLM Response: {first}")

    # Store in history (text-only, no images)
    _chat_history.append({"role": "user", "content": command_text})

    try:
        actions = _extract_actions(first)
    except ValueError:
        repair = [
            messages[0],
            {
                "role": "user",
                "content": (
                    "Return only a valid JSON array of actions. "
                    f"Fix this invalid output:\n{first}"
                ),
            },
        ]
        second = _post(repair)
        logging.warning(f"Repaired LLM Response: {second}")
        actions = _extract_actions(second)
        first = second

    _chat_history.append({"role": "assistant", "content": first})
    _trim_history()
    return actions
