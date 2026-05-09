"""
LLM provider abstraction.

All providers expose a single async method `generate_structured` that takes a
Pydantic model and returns a validated instance of it. The `LLMRouter` wraps a
primary + fallback provider and switches on rate limits, timeouts, or schema
validation failures.
"""

import asyncio
import os
import re
from functools import lru_cache
from typing import Protocol, TypeVar

import groq as groq_sdk
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# --- Defaults ---
DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))


def _strip_fences(text: str) -> str:
    """Strip markdown code fences that models sometimes wrap around JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class LLMProvider(Protocol):
    async def generate_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        temperature: float,
    ) -> T: ...


class GroqProvider:
    """Groq async client. Uses JSON mode for structured output."""

    def __init__(self, api_key: str, model: str = DEFAULT_GROQ_MODEL):
        self.client = groq_sdk.AsyncGroq(api_key=api_key)
        self.model = model

    async def generate_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        temperature: float,
    ) -> T:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=DEFAULT_MAX_TOKENS,
            response_format={"type": "json_object"},
            timeout=DEFAULT_TIMEOUT,
        )
        text = resp.choices[0].message.content or ""
        return response_model.model_validate_json(_strip_fences(text))


class GeminiProvider:
    """Gemini async client (genai.Client(...).aio). Uses response_schema for typed output."""

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL):
        self._client = genai.Client(api_key=api_key).aio
        self.model = model

    async def generate_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        temperature: float,
    ) -> T:
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=response_model,
            temperature=temperature,
        )
        resp = await self._client.models.generate_content(  # type: ignore[arg-type]
            model=self.model,
            contents=user,
            config=config,
        )
        # Prefer the SDK's own parsed Pydantic instance when available
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        return response_model.model_validate_json(_strip_fences(resp.text or ""))


# Errors that should trigger fallback to the secondary provider.
# Covers both Groq and Gemini since either may be primary.
_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    groq_sdk.RateLimitError,
    groq_sdk.APITimeoutError,
    groq_sdk.APIConnectionError,
    genai_errors.APIError,  # base — covers ClientError (incl. 429) + ServerError
    asyncio.TimeoutError,
    ValidationError,
)


def _provider_label(provider: "LLMProvider") -> str:
    return f"{type(provider).__name__}({getattr(provider, 'model', '?')})"


class LLMRouter:
    """Wraps two providers — primary first, fallback on rate-limit / timeout / bad schema."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback

    async def generate_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        temperature: float,
        label: str = "llm_call",
    ) -> T:
        try:
            result = await self.primary.generate_structured(
                system, user, response_model, temperature
            )
            print(f"[{label}] {_provider_label(self.primary)} ok", flush=True)
            return result
        except _FALLBACK_EXCEPTIONS as e:
            print(
                f"[{label}] {_provider_label(self.primary)} failed "
                f"({type(e).__name__}); falling back to {_provider_label(self.fallback)}",
                flush=True,
            )
            result = await self.fallback.generate_structured(
                system, user, response_model, temperature
            )
            print(f"[{label}] {_provider_label(self.fallback)} ok (fallback)", flush=True)
            return result


@lru_cache
def get_llm_router(
    primary: str = "groq",
    gemini_model: str = DEFAULT_GEMINI_MODEL,
) -> LLMRouter:
    """Router with configurable primary. Cached per (primary, gemini_model)."""
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY not set")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    groq = GroqProvider(api_key=groq_key)
    gemini = GeminiProvider(api_key=gemini_key, model=gemini_model)

    if primary == "groq":
        return LLMRouter(primary=groq, fallback=gemini)
    if primary == "gemini":
        return LLMRouter(primary=gemini, fallback=groq)
    raise ValueError(f"Unknown primary provider: {primary!r}")
