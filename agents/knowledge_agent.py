"""Knowledge agent for FAQ and training lookups."""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

from django.db.models import Q
from django.utils.html import escape

from cpq.models import Knowledge

logger = logging.getLogger(__name__)


_POSITIVE_CONFIRMATIONS = {"yes", "y", "yeah", "yep", "sure", "please", "ok", "okay", "affirmative"}
_NEGATIVE_CONFIRMATIONS = {"no", "n", "nope", "nah", "negative"}


def knowledge_agent(user, action, user_message: str, session_data: dict):
    """Entry point invoked by the orchestrator."""

    action_map = {
        "KnowledgeLookup": _handle_knowledge_lookup,
    }

    handler = action_map.get(action)
    if handler is None:
        logger.warning("Knowledge agent received unsupported action '%s'", action)
        return {"message": "⚠️ I couldn't match that knowledge request."}

    return handler(user_message, session_data)


def _handle_knowledge_lookup(user_message: str, session_data: dict) -> dict:
    """Locate the best matching knowledge base entry and craft a response."""

    language_pref = (
        session_data.get("preferred_language")
        or session_data.get("knowledge_language")
        or "en"
    )

    query = Knowledge.objects.filter(is_active=True)

    entry = _find_best_match(query.filter(language=language_pref), user_message)
    if entry is None:
        entry = _find_best_match(query, user_message)

    if entry is None:
        logger.info("Knowledge lookup did not find a match for '%s'", user_message)
        return {
            "message": (
                "I couldn't find a knowledge article for that topic yet. "
                "Try rephrasing your question or ask for another topic."
            )
        }

    message_parts = [
        escape(entry.content_text).replace("\n", "<br>")
    ]

    if entry.image_url:
        image_url = escape(entry.image_url)
        message_parts.append(
            f"<br><br>🖼️ I also have a related diagram here: "
            f"<a href='{image_url}' target='_blank'>{image_url}</a>"
        )

    if entry.has_video and entry.video_url:
        message_parts.append(
            "<br><br>🎥 I can share a quick video walkthrough if you'd like."
            " Would you like the link?"
        )
        session_data["pending_action"] = "knowledge_video_follow_up"
        session_data["pending_knowledge_id"] = entry.id
    else:
        session_data.pop("pending_knowledge_id", None)
        if session_data.get("pending_action") == "knowledge_video_follow_up":
            session_data.pop("pending_action", None)

    session_data.setdefault("state", {})
    session_data["state"]["last_knowledge_id"] = entry.id

    return {
        "message": "".join(message_parts)
    }


def resolve_knowledge_video_request(user_response: str, session_data: dict) -> Optional[dict]:
    """Handle the pending follow-up when the user answers about the video."""

    knowledge_id = session_data.get("pending_knowledge_id")
    if not knowledge_id:
        return {
            "message": "I no longer have a video queued up, but I'm ready if you need anything else."
        }

    entry = Knowledge.objects.filter(pk=knowledge_id, is_active=True).first()
    if entry is None or not entry.video_url:
        session_data.pop("pending_knowledge_id", None)
        session_data.pop("pending_action", None)
        return {
            "message": "I can't find that video anymore, but I'm happy to help with another question."
        }

    normalized = user_response.strip().lower()
    if normalized in _POSITIVE_CONFIRMATIONS:
        session_data.pop("pending_action", None)
        session_data.pop("pending_knowledge_id", None)
        video_url = escape(entry.video_url)
        return {
            "message": f"Here is the video tutorial: <a href='{video_url}' target='_blank'>{video_url}</a>"
        }
    if normalized in _NEGATIVE_CONFIRMATIONS:
        session_data.pop("pending_action", None)
        session_data.pop("pending_knowledge_id", None)
        return {
            "message": "No problem! Let me know if you'd like to see it later."
        }

    return {
        "message": "Just let me know with yes or no if you'd like me to share the video link."
    }


def _find_best_match(queryset, user_message: str) -> Optional[Knowledge]:
    """Find the best matching knowledge entry for the message."""

    text = user_message.strip()
    if not text:
        return None

    candidates = list(_generate_candidate_phrases(text))
    keywords = list({
        word
        for phrase in candidates
        for word in re.split(r"\W+", phrase.lower())
        if len(word) > 2
    })

    entries = list(queryset.all())
    if not entries:
        return None

    best_entry = None
    best_score = 0

    for entry in entries:
        score = _score_entry(entry, candidates, keywords)
        if score > best_score:
            best_entry = entry
            best_score = score

    return best_entry if best_score > 0 else None


def _generate_candidate_phrases(original: str) -> Iterable[str]:
    cleaned = _normalize_question(original)
    phrases = []
    if original:
        phrases.append(original.strip())
    if cleaned and cleaned not in phrases:
        phrases.append(cleaned)
    return phrases


def _normalize_question(question: str) -> str:
    text = question.strip().lower()
    text = re.sub(r"[?!.,]+$", "", text)
    prefixes = [
        r"^(show me|teach me|tell me|give me)",
        r"^(how do i|how to|can you)",
        r"^(what is|what's)",
    ]
    for pattern in prefixes:
        text = re.sub(pattern + r"\s+", "", text)
    return text.strip()


def _score_entry(entry: Knowledge, phrases: Iterable[str], keywords: Iterable[str]) -> int:
    title = (entry.title or "").lower()
    tags = (entry.tags or "").lower()
    content = (entry.content_text or "").lower()

    score = 0

    for phrase in phrases:
        lowered = phrase.lower()
        if not lowered:
            continue

        if title == lowered:
            score += 200
        elif title.startswith(lowered) or lowered.startswith(title):
            score += 120
        elif lowered in title:
            score += 90

        if lowered in tags:
            score += 60
        if lowered in content:
            score += 40

    for word in keywords:
        if word in title:
            score += 15
        if word in tags:
            score += 8
        if word in content:
            score += 4

    if entry.has_video:
        score += 2

    return score
