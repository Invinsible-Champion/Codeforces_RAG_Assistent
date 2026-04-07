"""
LLM orchestration service: handles OpenAI API calls with streaming support.
"""
import logging
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.prompts import build_prompt, format_context

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)


async def generate_response(
    query: str,
    retrieved_results: list[dict],
    mode: str = "chat",
    conversation_history: Optional[list[dict]] = None,
) -> str:
    """Generate a non-streaming LLM response."""
    context = format_context(retrieved_results)
    messages = build_prompt(query, context, mode, conversation_history)

    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.7,
        max_tokens=2000,
    )

    return response.choices[0].message.content


async def generate_response_stream(
    query: str,
    retrieved_results: list[dict],
    mode: str = "chat",
    conversation_history: Optional[list[dict]] = None,
) -> AsyncGenerator[str, None]:
    """Generate a streaming LLM response (yields text chunks)."""
    context = format_context(retrieved_results)
    messages = build_prompt(query, context, mode, conversation_history)

    stream = await client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.7,
        max_tokens=2000,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
