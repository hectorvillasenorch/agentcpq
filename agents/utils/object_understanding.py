"""Central, typo-tolerant understanding of what object/intent a chat message means.

The deterministic routers (record lookups, activities, details, metrics shortcuts…)
used to match object names with exact spellings, so a typo like "opportuntiy" or an
abbreviation like "opp" fell through to the LLM (which replied with gibberish).

This module normalizes user text once:
  • object words  → canonical model name  ("opp", "opportuntiy", "deal" → Opportunity)
  • intent words  → canonical verb/noun  ("shwo", "deatils", "activites" → show/details/activities)

Design rules (keep it safe):
  • never touch tokens containing digits (ids like 0004ACPQJTXKLIW7GC are preserved)
  • never touch tokens shorter than MIN_TOKEN_LEN (avoids mangling "is", "on", names)
  • only replace when difflib finds a confident match (>= CUTOFF) or an exact alias
"""
from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Dict, List, Optional, Tuple

MIN_TOKEN_LEN = 3

# canonical → plural (plurals matter for the "list all X" routing)
PLURALS: Dict[str, str] = {
    "Opportunity": "Opportunities",
    "Account": "Accounts",
    "Lead": "Leads",
    "Contact": "Contacts",
    "Quote": "Quotes",
    "QuoteLine": "QuoteLines",
    "Product": "Products",
    "Contract": "Contracts",
    "Subscription": "Subscriptions",
    "Tenant": "Tenants",
    "Knowledge": "Knowledge",
    "Option": "Options",
}
_ALL_FORMS: Dict[str, str] = {}
for _canon, _plural in PLURALS.items():
    _ALL_FORMS[_canon.lower()] = _canon
    _ALL_FORMS[_plural.lower()] = _plural
CUTOFF = 0.72

# ---------------------------------------------------------------------------
# Objects: canonical name → aliases (custom objects are added at runtime)
# ---------------------------------------------------------------------------
OBJECT_ALIASES: Dict[str, List[str]] = {
    # Keep this list to *clear object words and abbreviations only* — generic nouns
    # (company, person, deal, item…) must stay untouched so record-creation text
    # is never rewritten.
    "Opportunity": ["opportunity", "opportunities", "oppty", "opptys", "opp", "opps"],
    "Account": ["account", "accounts", "acct", "accts"],
    "Lead": ["lead", "leads"],
    "Contact": ["contact", "contacts"],
    "Quote": ["quote", "quotes"],
    "QuoteLine": ["quote line", "quote lines", "quoteline"],
    "Product": ["product", "products", "sku", "skus"],
    "Contract": ["contract", "contracts"],
    "Subscription": ["subscription", "subscriptions", "subs"],
    "Tenant": ["tenant", "tenants"],
    "Knowledge": ["knowledge"],
    "Option": ["option", "options"],
}

# ---------------------------------------------------------------------------
# Intent / command vocabulary (verb + noun words we pattern-match on)
# ---------------------------------------------------------------------------
INTENT_WORDS: List[str] = [
    "show", "list", "view", "display", "get", "find", "open", "give",
    "details", "summary", "activities", "activity", "related", "linked",
    "create", "add", "new", "update", "change", "edit", "modify", "delete",
    "remove", "quote", "product", "invoice", "pdf", "document", "export",
    "remind", "metrics", "revenue", "pipeline", "forecast", "count",
    "activities", "activity", "tasks", "calls", "meetings", "log",
]

_STOPWORDS = {
    "the", "for", "all", "me", "of", "on", "in", "to", "and", "with", "from",
    "my", "any", "at", "by", "is", "are", "was", "were", "be", "it", "this",
    "that", "a", "an", "please", "can", "you", "could", "would", "id", "ids",
}

_token_re = re.compile(r"[A-Za-z][A-Za-z\-']*")


def _looks_like_id(token: str) -> bool:
    """AgentCPQ ids / codes: any digit inside, or long all-caps alphanumerics."""
    if any(ch.isdigit() for ch in token):
        return True
    return len(token) >= 12 and token.isupper()


def _custom_object_keywords() -> Dict[str, str]:
    """API name / label → API name, for custom objects (best-effort, cached cheaply)."""
    try:
        from cpq.models import CustomObject

        mapping: Dict[str, str] = {}
        for custom in CustomObject.objects.all():
            for key in (custom.name, custom.label):
                if key and len(str(key)) >= MIN_TOKEN_LEN:
                    mapping[str(key).lower()] = custom.name
        return mapping
    except Exception:
        return {}


def _alias_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for canonical, aliases in OBJECT_ALIASES.items():
        for alias in aliases:
            index[alias] = canonical
    index.update(_custom_object_keywords())
    return index


def normalize_text(text: str, *, include_intents: bool = True) -> str:
    """Return text with object/intent words normalized (typos + abbreviations)."""
    if not text:
        return text

    alias_index = _alias_index()
    intent_index = {w: w for w in INTENT_WORDS}
    vocabulary = list(alias_index.keys()) + list(intent_index.keys())

    def replace_token(match: re.Match) -> str:
        token = match.group(0)
        lowered = token.lower()
        if lowered in _STOPWORDS or _looks_like_id(token):
            return token
        if len(lowered) < MIN_TOKEN_LEN:
            return token

        # 1) exact alias / intent
        if lowered in alias_index:
            canonical = alias_index[lowered]
            is_plural = lowered.endswith("s") or lowered in {"people", "children"}
            if is_plural and canonical in PLURALS:
                return PLURALS[canonical]
            return canonical
        if include_intents and lowered in intent_index:
            return lowered

        # 2) fuzzy match against the vocabulary
        candidates = get_close_matches(lowered, vocabulary, n=1, cutoff=CUTOFF)
        if not candidates:
            return token
        best = candidates[0]
        # Guard against false positives: accept fuzzy matches that keep the first
        # letter (shwo→show, deatils→details, accout→account) or are very close.
        if best[0] != lowered[0] and best != lowered:
            return token
        if best in alias_index:
            canonical = alias_index[best]
            if best.endswith("s") and canonical in PLURALS:
                return PLURALS[canonical]
            return canonical
        return best

    return _token_re.sub(replace_token, text)


def find_object(text: str) -> Optional[str]:
    """Return the canonical object name mentioned in the text (typo tolerant)."""
    normalized = normalize_text(text)
    lowered = normalized.lower()
    # Longest alias first so "quote line" wins over "quote".
    for alias, canonical in sorted(_alias_index().items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return canonical
    for form, canonical in sorted(_ALL_FORMS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(form)}\b", lowered):
            return canonical
    return None


def parse_object_identifier(text: str, object_names: Optional[List[str]] = None) -> Tuple[Optional[str], Optional[str]]:
    """Split '<object> <identifier>' from free text, tolerating typos in the object word.

    Returns (canonical_object_name, identifier_text) or (None, None).
    """
    if not text:
        return None, None

    normalized = normalize_text(text)
    candidates = object_names or sorted(OBJECT_ALIASES.keys(), key=lambda n: -len(n))
    if object_names:
        candidates = sorted(candidates, key=lambda n: -len(n))
    else:
        # include custom objects (api names) in the candidate list
        try:
            from cpq.models import CustomObject

            candidates = list(dict.fromkeys(candidates + [c.name for c in CustomObject.objects.all()]))
        except Exception:
            pass

    for obj_name in candidates:
        plural = PLURALS.get(obj_name)
        pattern = rf"\b(?:{re.escape(obj_name)}{('|' + re.escape(plural)) if plural else ''})s?\b"
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        # Cut the identifier out of the NORMALIZED text so typos in the object word
        # don't leak into the identifier.
        identifier = (normalized[: match.start()] + " " + normalized[match.end():]).strip(" ,:-")
        # Drop filler words users put before the value: "with id = 0004…", "number 12"
        previous = None
        while identifier and identifier != previous:
            previous = identifier
            identifier = re.sub(
                r"^(?:with|the|is|id|ids|number|no\.?|named|called|for)\b[\s:=#-]*",
                "",
                identifier,
                flags=re.IGNORECASE,
            ).strip(" ,:=#-")
        if identifier or obj_name:
            return obj_name, identifier or ""
    return None, None
