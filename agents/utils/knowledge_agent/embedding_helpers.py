"""Embedding utilities for the knowledge agent."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> Optional[OpenAI]:
    if not OPENAI_API_KEY:
        logger.debug("OPENAI_API_KEY not set; embeddings disabled for knowledge agent")
        return None

    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as exc:  # pragma: no cover - defensive in production
        logger.warning("Unable to initialize OpenAI client for embeddings: %s", exc)
        return None


def generate_embedding(text: str) -> Optional[list[float]]:
    """Create an embedding for the provided text, if possible."""

    cleaned = (text or "").strip()
    if not cleaned:
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        response = client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=cleaned,
        )
    except Exception as exc:  # pragma: no cover - runtime guard
        logger.warning("OpenAI embedding request failed: %s", exc)
        return None

    if not response.data:
        return None

    vector = response.data[0].embedding
    # Ensure the value is JSON-serializable and detached from the SDK objects
    return list(vector)
