"""
Gemini client (Google AI Studio / generativelanguage.googleapis.com).

REST API via httpx — generateContent endpoint, no SDK needed. Tried FIRST
in llm_client.generate(), ahead of Groq/NVIDIA/OpenRouter: Gemini's flash
models are fast and reliably good at structured JSON-extraction tasks
like ours (the structuring and item-matching prompts).
"""

import httpx
from loguru import logger
from config import config


async def generate(prompt: str) -> str:
    """Plain text generation — same contract as llm_client.generate()."""
    if not config.gemini_api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set in .env")

    url = f"{config.gemini_base_url}/models/{config.gemini_chat_model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": config.gemini_api_key}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            # Our prompts are structured extraction, not reasoning — thinking
            # mode (on by default on gemini-flash-latest) adds 20-30s+ of
            # latency for no benefit here and was blowing past our timeout.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    logger.debug(f"[Gemini/generate] {len(prompt)} chars — model: {config.gemini_chat_model}")
    async with httpx.AsyncClient(timeout=config.gemini_timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()
