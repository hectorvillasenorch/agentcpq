import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.utils import timezone

from .models import QuickbooksToken


logger = logging.getLogger(__name__)


class QuickbooksIntegrationError(Exception):
    """Raised whenever the QuickBooks API cannot be reached or returns an error."""


def _get_setting(name: str, default: Optional[str] = None) -> str:
    value = getattr(settings, name, default)
    if value is None:
        raise QuickbooksIntegrationError(f"Missing Django setting: {name}")
    return value


def get_quickbooks_token(user_id: str = "default") -> QuickbooksToken:
    token = QuickbooksToken.objects.filter(user_id=user_id).first()
    if not token:
        raise QuickbooksIntegrationError("QuickBooks credentials are not configured.")

    if token.is_expired:
        refresh_quickbooks_token(token)

    return token


def refresh_quickbooks_token(token: QuickbooksToken) -> QuickbooksToken:
    if not token.refresh_token:
        raise QuickbooksIntegrationError("QuickBooks refresh token is missing; re-authentication required.")

    client_id = _get_setting("QUICKBOOKS_CLIENT_ID", "")
    client_secret = _get_setting("QUICKBOOKS_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise QuickbooksIntegrationError("QuickBooks client credentials are not configured.")

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
    }

    response = requests.post(
        _get_setting("QUICKBOOKS_TOKEN_URL", "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"),
        data=payload,
        auth=(client_id, client_secret),
        timeout=30,
    )

    if response.status_code >= 400:
        logger.error("QuickBooks token refresh failed: %s", response.text)
        raise QuickbooksIntegrationError("Unable to refresh QuickBooks access token.")

    data = response.json()

    expires_in = data.get("expires_in")
    refresh_expires_in = data.get("x_refresh_token_expires_in")

    token.access_token = data.get("access_token", token.access_token)
    token.refresh_token = data.get("refresh_token", token.refresh_token)
    token.token_type = data.get("token_type", token.token_type)

    if expires_in:
        token.expires_at = timezone.now() + timedelta(seconds=int(expires_in))
    if refresh_expires_in:
        token.refresh_token_expires_at = timezone.now() + timedelta(seconds=int(refresh_expires_in))

    token.save(update_fields=[
        "access_token",
        "refresh_token",
        "token_type",
        "expires_at",
        "refresh_token_expires_at",
        "updated_at",
    ])

    return token


def build_quickbooks_url(token: QuickbooksToken, resource: str) -> str:
    base_url = _get_setting(
        "QUICKBOOKS_BASE_URL",
        "https://quickbooks.api.intuit.com/v3/company",
    )
    return f"{base_url}/{token.realm_id}/{resource}"


def quickbooks_headers(token: QuickbooksToken) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def quickbooks_request(
    token: QuickbooksToken,
    method: str,
    resource: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = build_quickbooks_url(token, resource)
    params = params.copy() if params else {}

    minor_version = getattr(settings, "QUICKBOOKS_MINOR_VERSION", None)
    if minor_version:
        params.setdefault("minorversion", minor_version)

    response = requests.request(
        method=method.upper(),
        url=url,
        headers=quickbooks_headers(token),
        json=payload,
        params=params or None,
        timeout=30,
    )

    if response.status_code >= 400:
        logger.error(
            "QuickBooks API error (%s %s): %s", method.upper(), resource, response.text
        )
        raise QuickbooksIntegrationError(
            "QuickBooks API returned an error; see logs for details."
        )

    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise QuickbooksIntegrationError("Invalid JSON response from QuickBooks.") from exc

