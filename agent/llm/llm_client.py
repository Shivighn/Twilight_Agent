"""
LLM client dispatcher.

generate() uses Gemini (gemini_client.py) only — no Groq/NVIDIA/OpenRouter
fallback for plain text generation; a Gemini failure is a real failure the
caller should handle (e.g. needs_review), not something to silently paper
over with a weaker free model. generate_from_image/chat_with_tools stay
NVIDIA-first since Gemini isn't used for vision/tool-calling here.

Tools import from this module — their code never changes when switching providers.
"""

from config import config
from llm import nvidia_client, openrouter_client, gemini_client


async def generate(prompt: str) -> str:
    """Plain text generation — used for PDF/text-based extraction."""
    if not config.gemini_api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set in .env")
    return await gemini_client.generate(prompt)


async def generate_from_image(prompt: str, image_path: str) -> str:
    """Vision extraction — NVIDIA with OpenRouter fallback."""
    try:
        return await nvidia_client.generate_from_image(prompt, image_path)
    except Exception as err:
        logger.warning(f"[LLM] NVIDIA vision failed ({err}) — falling back to OpenRouter")
    return await openrouter_client.generate_from_image(prompt, image_path)


async def chat_with_tools(system_prompt: str, user_message: str, tools: list) -> dict:
    """
    Sends a chat request with tool definitions.
    Returns {"tool_name": str, "tool_params": dict} if LLM picked a tool,
    or {"text": str} if it replied in plain text.
    """
    try:
        return await nvidia_client.chat_with_tools(system_prompt, user_message, tools)
    except Exception as err:
        logger.warning(f"[LLM] NVIDIA chat failed ({err}) — falling back to OpenRouter")
    return await openrouter_client.chat_with_tools(system_prompt, user_message, tools)
