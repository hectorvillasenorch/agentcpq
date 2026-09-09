"""Centralized LLM configuration for AgentCPQ.

Every agent should obtain its OpenAI-compatible client and model through this
module instead of hardcoding `openai.OpenAI(...)` / a model string. That way the
provider and model can be swapped via environment variables (OpenAI, DeepSeek,
OpenRouter, Together, or any OpenAI-compatible endpoint) without touching code.

Environment variables
---------------------
LLM_API_KEY          API key for the chat/JSON provider.
                     Falls back to OPENAI_API_KEY.
LLM_BASE_URL         OpenAI-compatible base URL (e.g. "https://api.deepseek.com").
                     Falls back to OPENAI_BASE_URL, then the OpenAI default.
LLM_MODEL            Base model used when a more specific tier is not set.
                     Default: "gpt-4o-mini".
LLM_MODEL_CLASSIFIER Model for intent routing/classification (fast + cheap).
LLM_MODEL_STRUCTURED Model for JSON extraction (must emit well-formed JSON).
LLM_MODEL_REASONING  Model for general answers / higher-quality reasoning.

Example (.env) to run everything on DeepSeek:
    LLM_BASE_URL=https://api.deepseek.com
    LLM_API_KEY=<your deepseek key>
    LLM_MODEL=deepseek-chat
    # Optional: keep classification cheap, give JSON extraction a stronger model
    # LLM_MODEL_CLASSIFIER=deepseek-chat
    # LLM_MODEL_STRUCTURED=deepseek-chat
"""

from __future__ import annotations

import functools
import os

import openai
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"

# Valid tiers understood by get_model(). Everything falls back to LLM_MODEL.
_TIERS = ("classifier", "structured", "reasoning")


def _read_env(name: str, default: str | None = None) -> str | None:
    """Return a stripped env value, or ``default`` when unset/blank."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


@functools.lru_cache(maxsize=1)
def get_llm_client():
    """Return a configured OpenAI-compatible client.

    Honors ``LLM_BASE_URL`` / ``LLM_API_KEY`` (then ``OPENAI_BASE_URL`` /
    ``OPENAI_API_KEY``) so any compatible provider can be used.
    """
    api_key = _read_env("LLM_API_KEY") or _read_env("OPENAI_API_KEY")
    base_url = _read_env("LLM_BASE_URL") or _read_env("OPENAI_BASE_URL")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def get_model(tier: str = "default") -> str:
    """Resolve the model name for a given tier.

    Tiers: ``default``, ``classifier``, ``structured``, ``reasoning``.
    Each tier reads ``LLM_MODEL_<TIER>`` and falls back to ``LLM_MODEL``,
    which itself falls back to the built-in default.
    """
    if tier in _TIERS:
        return _read_env(f"LLM_MODEL_{tier.upper()}", get_model("default"))
    return _read_env("LLM_MODEL", DEFAULT_MODEL)


def json_mode_enabled() -> bool:
    """Whether JSON mode (``response_format={"type": "json_object"}``) is on.

    Enabled by default; set ``LLM_JSON_MODE=0`` to disable for providers that
    don't implement JSON mode.
    """
    value = _read_env("LLM_JSON_MODE", "1")
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _ensure_json_hint(messages):
    """Guarantee the prompt mentions JSON.

    Several providers (DeepSeek, and others) reject ``response_format="json_object"``
    with a 400 unless the word "json" appears somewhere in the prompt. Returns the
    (possibly adjusted) message list.
    """
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and "json" in content.lower():
            return messages

    adjusted = [dict(message) for message in messages]
    for message in adjusted:
        if message.get("role") == "system":
            message["content"] = (message.get("content") or "") + "\n\nReturn your answer as valid JSON."
            return adjusted
    adjusted.insert(0, {"role": "system", "content": "Return your answer as valid JSON."})
    return adjusted


def temperature_supported(model: str | None) -> bool:
    """Whether the model accepts an explicit ``temperature``.

    OpenAI's reasoning line (gpt-5 family, o1/o3/o4/…) only allows the default
    temperature (1) and rejects any explicit value with a 400. DeepSeek and
    older chat models (gpt-4o*, gpt-4.1*) accept it.
    """
    m = str(model or "").lower()
    return not (
        m.startswith("gpt-5")
        or m.startswith("o1")
        or m.startswith("o3")
        or m.startswith("o4")
        or m.startswith("o5")
    )


def chat_json(client, model, messages, temperature=0.2, **kwargs):
    """``chat.completions.create`` constrained to emit valid JSON.

    Used by the structured-extraction paths. JSON mode is added automatically
    unless disabled via ``LLM_JSON_MODE``. Keep ``clean_llm_json`` as a parser
    fallback on the result regardless.
    """
    if temperature_supported(model):
        kwargs.setdefault("temperature", temperature)
    else:
        kwargs.pop("temperature", None)  # reasoning models reject explicit temperature
    if json_mode_enabled():
        kwargs["response_format"] = {"type": "json_object"}
        messages = _ensure_json_hint(messages)
    return client.chat.completions.create(model=model, messages=messages, **kwargs)


def chat_stream(client, model, messages, temperature=0.2, **kwargs):
    """``chat.completions.create`` that streams tokens via the active sink.

    Used for the user-facing text answers (general queries, final summaries).
    When no :class:`agents.streaming.StreamSink` is active it behaves exactly
    like ``chat_json`` (no streaming). Returns an object exposing
    ``.choices[0].message.content`` so call sites can use it unchanged.
    """
    from .streaming import get_sink, emit

    if temperature_supported(model):
        kwargs.setdefault("temperature", temperature)
    else:
        kwargs.pop("temperature", None)  # reasoning models reject explicit temperature
    sink = get_sink()
    if sink is None:
        return client.chat.completions.create(model=model, messages=messages, **kwargs)

    stream = client.chat.completions.create(
        model=model, messages=messages, stream=True, **kwargs
    )
    parts: list[str] = []
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            parts.append(delta)
            emit("token", {"content": delta})
    full_text = "".join(parts)

    class _Msg:
        content = full_text

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    return _Resp()
