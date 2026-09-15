"""Centralized LLM configuration for AgentCPQ.

Every agent should obtain its OpenAI-compatible client and model through this
module instead of hardcoding ``openai.OpenAI(...)`` / a model string.

Configuration precedence
------------------------
1. ``LLMConfig`` row(s) in the database whose ``is_active`` is True (managed
   from the Django admin). The newest active row wins.
2. Environment variables (``LLM_*``, then ``OPENAI_*``).

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
"""

from __future__ import annotations

import os
import time

import openai
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"

# Valid tiers understood by get_model(). Everything falls back to LLM_MODEL.
_TIERS = ("classifier", "structured", "reasoning")

# How long a worker caches the active DB config before re-reading it.
_DB_CONFIG_TTL_SECONDS = 5.0

_db_config_cache: dict = {"primed": False, "ts": 0.0, "value": None}
_client_cache: dict = {"signature": None, "client": None}


def _read_env(name: str, default: str | None = None) -> str | None:
    """Return a stripped env value, or ``default`` when unset/blank."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _fetch_db_config():
    """Return the newest active ``LLMConfig`` row, or ``None``.

    Never raises: if the table is missing (migrations pending) or the DB is
    unreachable we simply fall back to environment variables.
    """
    try:
        from agents.models import LLMConfig

        return LLMConfig.objects.filter(is_active=True).order_by("-id").first()
    except Exception:
        return None


def _get_db_config():
    """Return the active DB config, cached for a few seconds per worker."""
    now = time.monotonic()
    if _db_config_cache["primed"] and (now - _db_config_cache["ts"]) < _DB_CONFIG_TTL_SECONDS:
        return _db_config_cache["value"]

    config = _fetch_db_config()
    _db_config_cache["value"] = config
    _db_config_cache["ts"] = now
    _db_config_cache["primed"] = True
    return config


def clear_llm_config_cache() -> None:
    """Drop cached DB config / client so the next call re-reads settings.

    Called by the LLMConfig admin after saves and deletes.
    """
    _db_config_cache["primed"] = False
    _db_config_cache["value"] = None
    _client_cache["signature"] = None
    _client_cache["client"] = None


def _resolve_api_key(config) -> str | None:
    if config is not None and getattr(config, "api_key", ""):
        return config.api_key
    return _read_env("LLM_API_KEY") or _read_env("OPENAI_API_KEY")


def _resolve_base_url(config) -> str | None:
    if config is not None and getattr(config, "base_url", ""):
        return config.base_url
    return _read_env("LLM_BASE_URL") or _read_env("OPENAI_BASE_URL")


def llm_configured() -> bool:
    """Whether any API key is available (DB config or environment)."""
    return bool(_resolve_api_key(_get_db_config()))


def _build_client(config):
    kwargs = {"api_key": _resolve_api_key(config)}
    base_url = _resolve_base_url(config)
    if base_url:
        kwargs["base_url"] = base_url
    return openai.OpenAI(**kwargs)


def _get_real_client():
    """Return the real OpenAI-compatible client for the current config."""
    config = _get_db_config()
    signature = (
        "db" if config is not None else "env",
        getattr(config, "pk", None),
        _resolve_api_key(config),
        _resolve_base_url(config),
    )
    if _client_cache["signature"] != signature or _client_cache["client"] is None:
        _client_cache["client"] = _build_client(config)
        _client_cache["signature"] = signature
    return _client_cache["client"]


class _LazyLLMClient:
    """Delegating proxy that always resolves to the current client.

    Module-level ``client = get_llm_client()`` bindings therefore stay valid
    even after the admin changes the provider configuration at runtime.
    """

    def __getattr__(self, name: str):
        return getattr(_get_real_client(), name)


_lazy_client = _LazyLLMClient()


def get_llm_client():
    """Return an OpenAI-compatible client that reflects the latest config.

    The returned object is a lightweight proxy; every ``client.chat...`` /
    ``client.embeddings...`` access resolves the underlying OpenAI client for
    the currently active DB/env configuration.
    """
    return _lazy_client


def get_model(tier: str = "default") -> str:
    """Resolve the model name for a given tier.

    Tiers: ``default``, ``classifier``, ``structured``, ``reasoning``.
    Each tier reads the active ``LLMConfig`` field first, then its
    ``LLM_MODEL_<TIER>`` env var, then ``LLM_MODEL``, then the built-in
    default.
    """
    config = _get_db_config()

    if config is not None:
        if tier in _TIERS:
            db_value = getattr(config, f"model_{tier}", "") or ""
            if db_value:
                return db_value
            if getattr(config, "model", ""):
                return config.model
        elif getattr(config, "model", ""):
            return config.model

    if tier in _TIERS:
        return _read_env(f"LLM_MODEL_{tier.upper()}", get_model("default")) or DEFAULT_MODEL
    return _read_env("LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def json_mode_enabled() -> bool:
    """Whether JSON mode (``response_format={"type": "json_object"}``) is on.

    Enabled by default; set ``LLM_JSON_MODE=0`` to disable for providers that
    don't implement JSON mode.
    """
    config = _get_db_config()
    if config is not None:
        return bool(getattr(config, "json_mode", True))

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
