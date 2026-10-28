"""
Groq client (console.groq.com) — tried FIRST, before NVIDIA/OpenRouter.

OpenAI-compatible /chat/completions API via httpx. Groq runs open models
(Llama 3.3 70B by default here) on its own fast inference hardware —
typically well under 1s for prompts this size, vs. the 20-70s we've
measured from NVIDIA's reasoning model for the same prompt size. Used
for the same plain-text extraction/matching calls llm_client.generate()
serves; no vision/tool-calling support needed here since the Petpooja
structuring/matching prompts are plain-text-in, JSON-text-out.

Free tier: generous per-minute/per-day request caps, no cost. Returns 429
when throttled — one retry, same pattern as nvidia_client.py.
"""

import asyncio
import httpx
from loguru import logger
from config import config


async def _chat_completions(payload: dict) -> dict:
    if not config.groq_api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in .env")

    headers = {"Authorization": f"Bearer {config.groq_api_key}"}
    url = f"{config.groq_base_url}/chat/completions"

    async with httpx.AsyncClient(timeout=config.groq_timeout) as client:
        for attempt in (1, 2):
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429 and attempt == 1:
                logger.warning("[Groq] 429 rate limited — retrying in 3s")
                await asyncio.sleep(3)
                continue
            resp.raise_for_status()
            return resp.json()


def _extract_content(data: dict) -> str:
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


async def generate(prompt: str) -> str:
    """Plain text generation — same contract as llm_client.generate()."""
    logger.debug(f"[Groq/generate] {len(prompt)} chars — model: {config.groq_chat_model}")
    data = await _chat_completions({
        "model": config.groq_chat_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    })
    return _extract_content(data)
