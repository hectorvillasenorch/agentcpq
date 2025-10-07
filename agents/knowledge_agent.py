"""Knowledge agent for FAQ and training lookups."""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import numpy as np
from django.utils.html import escape

from cpq.models import Knowledge
from agents.utils.knowledge_agent.embedding_helpers import generate_embedding

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
        message_parts.append(_render_image_preview(entry.image_url))

    if entry.has_video and entry.video_url:
        message_parts.append(_render_video_embed(entry.video_url))
        session_data.pop("pending_knowledge_id", None)
        if session_data.get("pending_action") == "knowledge_video_follow_up":
            session_data.pop("pending_action", None)
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

    entries = list(queryset.all())
    if not entries:
        return None

    semantic_entry = _find_semantic_match(entries, text)
    if semantic_entry is not None:
        return semantic_entry

    candidates = list(_generate_candidate_phrases(text))
    keywords = list({
        word
        for phrase in candidates
        for word in re.split(r"\W+", phrase.lower())
        if len(word) > 2
    })

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


def _find_semantic_match(entries: Iterable[Knowledge], text: str) -> Optional[Knowledge]:
    """Return the best semantic match if embeddings are available."""

    embedding = generate_embedding(text)
    if not embedding:
        return None

    try:
        query_vec = np.asarray(embedding, dtype=float)
    except (TypeError, ValueError):
        logger.debug("Query embedding contained invalid values; falling back to keyword match")
        return None

    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return None

    best_entry: Optional[Knowledge] = None
    best_similarity = -1.0

    for entry in entries:
        entry_embedding = getattr(entry, "embedding", None)
        if not entry_embedding:
            continue

        try:
            entry_vec = np.asarray(entry_embedding, dtype=float)
        except (TypeError, ValueError):
            continue

        entry_norm = np.linalg.norm(entry_vec)
        if entry_norm == 0:
            continue

        similarity = float(np.dot(query_vec, entry_vec) / (query_norm * entry_norm))
        if similarity > best_similarity:
            best_similarity = similarity
            best_entry = entry

    if best_entry is not None and best_similarity >= 0.7:
        logger.debug(
            "Semantic match selected entry %s with similarity %.3f",
            best_entry.id,
            best_similarity,
        )
        return best_entry

    return None


def _render_image_preview(image_url: str) -> str:
    """Return inline HTML to preview an image while keeping a link fallback."""

    embed_url, fallback_url = _make_image_embed_url(image_url)
    safe_fallback = escape(fallback_url)

    if not embed_url:
        return (
            "<br><br>🖼️ Related visual: "
            f"<a href='{safe_fallback}' target='_blank' rel='noopener'>{safe_fallback}</a>"
        )

    safe_embed = escape(embed_url)
    return (
        "<br><br>🖼️ Related visual:<br>"
        f"<a href='{safe_fallback}' target='_blank' rel='noopener'>"
        f"<img src='{safe_embed}' alt='Knowledge diagram' "
        "style='max-width:100%;height:auto;border-radius:8px;margin-top:8px;'/>"
        "</a>"
    )


def _render_video_embed(video_url: str) -> str:
    """Return inline HTML to embed a video with a fallback link."""

    embed_url, fallback_url = _make_video_embed_url(video_url)
    safe_fallback = escape(fallback_url)

    if not embed_url:
        return (
            "<br><br>🎥 Video walkthrough: "
            f"<a href='{safe_fallback}' target='_blank' rel='noopener'>{safe_fallback}</a>"
        )

    safe_embed = escape(embed_url)
    return (
        "<br><br>🎥 Video walkthrough:<br>"
        "<div style='position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px;margin-top:8px;'>"
        f"<iframe src='{safe_embed}' allowfullscreen "
        "style='position:absolute;top:0;left:0;width:100%;height:100%;border:0;'"
        " title='Knowledge video'></iframe>"
        "</div>"
        f"<br><a href='{safe_fallback}' target='_blank' rel='noopener'>Open video in a new tab</a>"
    )


def _make_image_embed_url(original_url: str) -> Tuple[Optional[str], str]:
    """Return an embeddable image URL when possible and the fallback link."""

    fallback = original_url
    parsed = urlparse(original_url)
    host = parsed.netloc.lower()

    if parsed.scheme in {"http", "https"}:
        path_lower = parsed.path.lower()
        for suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
            if path_lower.endswith(suffix):
                return original_url, fallback

    if "drive.google.com" in host:
        qs = parse_qs(parsed.query)
        image_id = None
        if parsed.path.startswith("/file/d/"):
            parts = parsed.path.split("/")
            if len(parts) >= 4:
                image_id = parts[3]
        elif parsed.path == "/uc" and "id" in qs:
            image_id = qs["id"][0]

        if image_id:
            params = {"export": "view", "id": image_id}
            resource_key = qs.get("resourcekey", [None])[0]
            if resource_key:
                params["resourcekey"] = resource_key
            return f"https://drive.google.com/uc?{urlencode(params)}", fallback

    return None, fallback


def _make_video_embed_url(original_url: str) -> Tuple[Optional[str], str]:
    """Return an embeddable video URL when possible and the fallback link."""

    fallback = original_url
    parsed = urlparse(original_url)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query)

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = path.lstrip("/")
        if video_id:
            start = query.get("t") or query.get("start")
            start_param = f"?start={_extract_seconds(start[0])}" if start else ""
            return f"https://www.youtube.com/embed/{video_id}{start_param}", fallback

    if "youtube.com" in host:
        if path == "/watch":
            video_id = query.get("v", [None])[0]
            if video_id:
                start = query.get("t") or query.get("start")
                start_param = f"?start={_extract_seconds(start[0])}" if start else ""
                return f"https://www.youtube.com/embed/{video_id}{start_param}", fallback
        elif path.startswith("/embed/"):
            return original_url, fallback

    if "drive.google.com" in host:
        if parsed.path.startswith("/file/d/"):
            parts = parsed.path.split("/")
            if len(parts) >= 4:
                file_id = parts[3]
                resource_key = query.get("resourcekey", [None])[0]
                preview_params = f"?resourcekey={resource_key}" if resource_key else ""
                return (
                    f"https://drive.google.com/file/d/{file_id}/preview{preview_params}",
                    fallback,
                )

    return None, fallback


def _extract_seconds(raw_value: str) -> int:
    """Convert common YouTube time formats to seconds for embed start."""

    if not raw_value:
        return 0
    if raw_value.isdigit():
        return int(raw_value)

    match = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw_value)
    if not match:
        return 0
    hours, minutes, seconds = match.groups(default="0")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
