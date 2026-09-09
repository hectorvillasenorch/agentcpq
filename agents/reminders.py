"""One-off chat reminders ("remind me on Monday to …").

Not event-driven: these enqueue straight into the ScheduledEmail outbox, which the
email scheduler daemon already delivers. Optionally references a Lead/Contact so
the reminder email can name the person.
"""
import logging
import os
import re
from datetime import datetime, time as dtime, timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

DEFAULT_REMIND_HOUR = int(os.getenv("REMINDER_HOUR_UTC", "15"))  # ~10am ET / 7am PT
DEFAULT_REMIND_MINUTE = 0


def reminder_enabled_text() -> str:
    return (
        "One-off reminders work like this in chat:\n"
        "• \"remind me to call Sudhir on Monday\"\n"
        "• \"remind me next Monday to reach out to Sudhir from this lead 0001ACPQQX8BMSVZHL\"\n"
        "• \"remind me in 2 days to follow up on the quote\"\n"
        "• \"remind me tomorrow at 5pm to email Acme\"\n"
        "I'll email you at the scheduled time."
    )


def looks_like_reminder(user_message: str) -> bool:
    return bool(re.match(r"^(?:please\s+)?remind\s+me\b", (user_message or "").strip(), re.IGNORECASE))


def _parse_time_of_day(text: str) -> dtime:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if m.group(3).lower() == "pm" and hour < 12:
            hour += 12
        if m.group(3).lower() == "am" and hour == 12:
            hour = 0
        return dtime(hour=min(hour, 23), minute=min(minute, 59))
    return None


def parse_reminder_when(text: str) -> tuple:
    """Return (send_at_aware_datetime, matched_phrase_length) or (None, 0)."""
    now = timezone.now()
    tz = now.tzinfo
    low = text.lower()
    time_of_day = _parse_time_of_day(text) or dtime(hour=DEFAULT_REMIND_HOUR, minute=DEFAULT_REMIND_MINUTE)

    def at(hour=None, minute=None):
        h = hour if hour is not None else (time_of_day.hour if time_of_day else DEFAULT_REMIND_HOUR)
        m = minute if minute is not None else (time_of_day.minute if time_of_day else 0)
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    def days_from_today(n):
        base = at()
        return base + timedelta(days=n)

    # "tomorrow"
    m = re.match(r"^(?:on\s+)?tomorrow\b", low)
    if m:
        return days_from_today(1), len(m.group(0))

    # "today"
    m = re.match(r"^(?:on\s+)?today\b", low)
    if m:
        send = at()
        return (send if send > now else send + timedelta(days=1)), len(m.group(0))

    # "in N days/hours/weeks"
    m = re.match(r"^(?:in\s+)?(\d+)\s*(day|days|hour|hours|week|weeks|minute|minutes)\b", low)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        base = at()
        if unit.startswith("day"):
            return base + timedelta(days=n), len(m.group(0))
        if unit.startswith("week"):
            return base + timedelta(weeks=n), len(m.group(0))
        if unit.startswith("hour"):
            send = now + timedelta(hours=n)
            return send, len(m.group(0))
        send = now + timedelta(minutes=n)
        return send, len(m.group(0))

    # "(next) <weekday>" — always the NEXT occurrence, strictly in the future;
    # "next week on <weekday>" / "next week <weekday>" → next occurrence in the
    # coming week (e.g. "next week on Monday" from Wed = the Monday 5 days later)
    m = re.match(r"^next\s+week\s+(?:on\s+)?(%s)\b" % "|".join(_WEEKDAYS), low)
    if m:
        target_wd = _WEEKDAYS[m.group(1)]
        base = at()
        days_ahead = (target_wd - base.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        send = base + timedelta(days=days_ahead)
        return send, len(m.group(0))

    # "next <weekday>" forces next week's occurrence.
    m = re.match(r"^(?:(?:on\s+)?(next|this)\s+)?(%s)\b" % "|".join(_WEEKDAYS), low)
    if m:
        qualifier, day = m.group(1), m.group(2)
        target_wd = _WEEKDAYS[day]
        base = at()
        days_ahead = (target_wd - base.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # "monday" on a monday → next monday
        send = base + timedelta(days=days_ahead)
        return send, len(m.group(0))

    # "(next/on) <Month> <day>" or "<Month> <day>"
    m = re.match(r"^(?:(?:on\s+)?(?:next\s+)?(%s)\s+(\d{1,2})(?:st|nd|rd|th)?)\b" % "|".join(_MONTHS), low)
    if m:
        month = _MONTHS[m.group(1)]
        day = int(m.group(2))
        year = base_year = now.year
        try:
            send = at().replace(year=year, month=month, day=day)
        except ValueError:
            try:
                send = at().replace(year=year + 1, month=month, day=day)
            except ValueError:
                return None, 0
        if send <= now:
            try:
                send = at().replace(year=year + 1, month=month, day=day)
            except ValueError:
                return None, 0
        return send, len(m.group(0))

    # ISO date YYYY-MM-DD
    m = re.match(r"^(?:on\s+)?(\d{4})-(\d{1,2})-(\d{1,2})\b", low)
    if m:
        try:
            send = at().replace(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
        except ValueError:
            return None, 0
        if send <= now:
            send += timedelta(days=365)
        return send, len(m.group(0))

    return None, 0


def reminder_email_recipient(user) -> str:
    env_to = os.getenv("REMINDER_EMAIL", "").strip()
    if env_to:
        return env_to
    if user and getattr(user, "email", "").strip():
        return user.email.strip()
    if user and getattr(user, "username", "").strip() and "@" in user.username:
        return user.username.strip()
    return ""


def create_one_off_reminder(user, user_message: str, session_data: dict) -> dict:
    """Handle 'remind me <when> to <todo>' → schedule a one-off reminder email."""
    from cpq.models import ScheduledEmail, Lead

    text = (user_message or "").strip()
    # normalize: drop the leading 'remind me'
    after = re.sub(r"^(?:please\s+)?remind\s+me\b", "", text, flags=re.IGNORECASE).strip(" .,;:-")

    # find 'to <task>' boundary — the task is everything from 'to ' onward
    to_match = re.search(r"\bto\s+(.+)$", after, re.IGNORECASE)
    if not to_match:
        return {"message": "Tell me what to remind you about, e.g. \"remind me next Monday to call Sudhir\"."}
    task = to_match.group(1).strip(" .,;:-")

    when_text = after[: to_match.start()].strip(" .,;:,")
    send_at, _used = parse_reminder_when(when_text)
    if send_at is None:
        # maybe the user wrote "remind me to X on <when>" — retry parsing task phrase's tail
        m = re.search(r"\b(on|at|next|in|tomorrow|%s)\b" % "|".join(_WEEKDAYS), task, re.IGNORECASE)
        if m:
            tail = task[m.start():]
            task2 = task[:m.start()].strip(" .,;")
            if task2:
                task = task2
                send_at, _used = parse_reminder_when(tail)
    if send_at is None:
        return {
            "message": (
                "I couldn't figure out when. Try: \"remind me <next Monday> to <task>\", "
                "\"remind me to <task> on March 15\", or \"remind me in 3 days to <task>\"."
            )
        }

    recipient = reminder_email_recipient(user)
    if not recipient:
        return {
            "message": "I need an email address for reminders — set the REMINDER_EMAIL config var or add an email to your user profile."
        }

    # Optional context: a lead/contact named in the message (Sudhir… lead <id>)
    instance_model = "auth.User"
    instance_id = user.pk
    lead = None
    lead_id_m = re.search(r"\blead\s+([0-9A-Za-z_\-]{6,})\b", text, re.IGNORECASE)
    if lead_id_m:
        candidate = lead_id_m.group(1)
        lead = Lead.objects.filter(leadId__iexact=candidate).first()
        if lead is None:
            lead = Lead.objects.filter(external_id__iexact=candidate).first()
    if lead is not None:
        instance_model = "cpq.Lead"
        instance_id = lead.pk
        person = f"{lead.first_name} {lead.last_name}".strip() or lead.company or f"Lead {lead.leadId}"
        subject = "Reminder: " + task
        message_body = f"⏰ Reminder:\n\n{task}\n\nRelated lead: {person} ({lead.leadId})"
    else:
        subject = "Reminder: " + task
        message_body = f"⏰ Reminder:\n\n{task}"

    action = {
        "email": {
            "subject": {"type": "static", "value": subject},
            "message": message_body,
            "template": "default",
            "recipients": {"external": [recipient]},
        }
    }
    ScheduledEmail.objects.create(
        trigger=None,
        instance_model=instance_model,
        instance_id=instance_id,
        action=action,
        send_at=send_at,
        status="pending",
    )

    local_str = timezone.localtime(send_at).strftime("%A, %b %d, %Y at %I:%M %p")
    return {
        "message": (
            f"✅ Reminder set for <b>{local_str}</b> — I'll email you at {recipient}: \"{task}\""
            + (f" (lead: {person})" if lead is not None else "")
        )
    }
