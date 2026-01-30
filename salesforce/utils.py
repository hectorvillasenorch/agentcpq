from __future__ import annotations

import datetime
import logging
import os
import urllib.parse

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from salesforce.models import SalesforceToken
from salesforce.endpoints import (
    apply_instance_url as _apply_instance_url_base,
    build_rest_url,
    is_login_host as _is_login_host,
    join_instance_url as _join_instance_url_base,
    normalize_instance_url as _normalize_instance_url,
)

logger = logging.getLogger(__name__)

SF_API_VERSION = "v57.0"


def _is_valid_instance_url(value):
    normalized = _normalize_instance_url(value)
    if not normalized:
        return False
    return not _is_login_host(normalized)


def _join_instance_url(token, path, query=None):
    return _join_instance_url_base(getattr(token, "instance_url", None), path, query)


def _apply_instance_url(token, url):
    return _apply_instance_url_base(getattr(token, "instance_url", None), url)


def _limits_cache_key(token):
    token_id = token.pk or token.user_id
    updated_at = int(token.updated_at.timestamp()) if token.updated_at else 0
    return f"salesforce:limits:{token_id}:{updated_at}"


def _use_salesforce_userinfo():
    scopes = (settings.SALESFORCE_OAUTH_SCOPES or "").split()
    if "openid" not in scopes:
        return False
    return bool(getattr(settings, "SALESFORCE_USE_USERINFO", False))


def _salesforce_headers(token):
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Content-Type": "application/json",
    }


def refresh_salesforce_token(token, timeout=6):
    if not token or not token.refresh_token:
        return None

    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.SALESFORCE_CLIENT_ID,
        "refresh_token": token.refresh_token,
    }
    if settings.SALESFORCE_CLIENT_SECRET:
        payload["client_secret"] = settings.SALESFORCE_CLIENT_SECRET
    try:
        response = requests.post(settings.SALESFORCE_TOKEN_URL, data=payload, timeout=timeout)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        return None

    issued_at_raw = data.get("issued_at")
    issued_at = None
    expires_at = None
    if issued_at_raw:
        issued_at_ts = int(issued_at_raw) / 1000
        issued_at = datetime.datetime.fromtimestamp(issued_at_ts, tz=datetime.timezone.utc)
        expires_at = issued_at + datetime.timedelta(hours=1)

    token.access_token = access_token
    instance_url = _normalize_instance_url(data.get("instance_url") or token.instance_url)
    if instance_url:
        token.instance_url = instance_url
    token.issued_at_raw = issued_at_raw or token.issued_at_raw
    token.issued_at = issued_at or token.issued_at
    token.expires_at = expires_at or token.expires_at
    token.save(
        update_fields=["access_token", "instance_url", "issued_at_raw", "issued_at", "expires_at", "updated_at"]
    )
    return token


def get_valid_salesforce_token(timeout=6):
    token = SalesforceToken.objects.first()
    if not token:
        return None
    if token.instance_url:
        normalized = _normalize_instance_url(token.instance_url)
        if normalized and normalized != token.instance_url:
            token.instance_url = normalized
            token.save(update_fields=["instance_url"])
    if not token.instance_url and token.refresh_token:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        token = refreshed or token
    if not token.instance_url:
        return None
    if token.expires_at and token.expires_at <= timezone.now():
        if token.refresh_token:
            refreshed = refresh_salesforce_token(token, timeout=timeout)
            token = refreshed or token
        else:
            return None
    if token.refresh_token and not token.expires_at:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        token = refreshed or token
    enforce_instance = getattr(settings, "SALESFORCE_ENFORCE_INSTANCE_URL", True)
    if enforce_instance and not _is_valid_instance_url(token.instance_url):
        if token.refresh_token:
            refreshed = refresh_salesforce_token(token, timeout=timeout)
            token = refreshed or token
        if not _is_valid_instance_url(token.instance_url):
            return None
    return token


def salesforce_limits_check(token, timeout=6, allow_cache=True):
    enforce_instance = getattr(settings, "SALESFORCE_ENFORCE_INSTANCE_URL", True)
    if not token or not token.instance_url:
        return False, None, token
    if enforce_instance and not _is_valid_instance_url(token.instance_url):
        return False, None, token

    cache_key = _limits_cache_key(token)
    if allow_cache and cache.get(cache_key):
        return True, None, token

    url = build_rest_url(token.instance_url, SF_API_VERSION, "/limits")
    try:
        response = requests.get(url, headers=_salesforce_headers(token), timeout=timeout)
    except requests.RequestException:
        return False, None, token

    refresh_on_invalid = getattr(settings, "SALESFORCE_REFRESH_ON_INVALID_SESSION", True)
    if refresh_on_invalid and (
        response.status_code in {401, 403}
        or _response_has_error_code(response, {"INVALID_SESSION_ID"})
    ):
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        if refreshed:
            token = refreshed
            url = build_rest_url(token.instance_url, SF_API_VERSION, "/limits")
            try:
                response = requests.get(url, headers=_salesforce_headers(token), timeout=timeout)
            except requests.RequestException:
                return False, None, token

    if response.status_code == 200:
        cache.set(
            cache_key,
            True,
            getattr(settings, "SALESFORCE_LIMITS_CACHE_TTL", 120),
        )
        return True, response, token

    return False, response, token


def ensure_valid_access_token(token, timeout=6, allow_limits_cache=True):
    token = get_valid_salesforce_token(timeout=timeout) if token else None
    if not token:
        return None
    enforce_instance = getattr(settings, "SALESFORCE_ENFORCE_INSTANCE_URL", True)
    if not token.instance_url:
        return None
    if enforce_instance and not _is_valid_instance_url(token.instance_url):
        return None

    ok, response, token = salesforce_limits_check(token, timeout=timeout, allow_cache=allow_limits_cache)
    if ok:
        return token

    if response is not None:
        logger.warning(
            "Salesforce limits check failed (HTTP %s).",
            response.status_code,
        )
    return None


def salesforce_request(
    token,
    method,
    url,
    *,
    params=None,
    data=None,
    json=None,
    headers=None,
    timeout=6,
    allow_limits_cache=True,
):
    token = ensure_valid_access_token(token, timeout=timeout, allow_limits_cache=allow_limits_cache)
    if not token:
        return None

    enforce_instance = getattr(settings, "SALESFORCE_ENFORCE_INSTANCE_URL", True)
    request_url = _apply_instance_url(token, url) if enforce_instance else url
    if enforce_instance and _is_login_host(request_url):
        logger.warning("Blocked Salesforce request to login/test host.")
        return None

    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request_headers["Authorization"] = f"Bearer {token.access_token}"

    try:
        response = requests.request(
            method,
            request_url,
            headers=request_headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
        )
    except requests.RequestException:
        return None

    if response.status_code not in {401, 403} and not _response_has_error_code(
        response,
        {"INVALID_SESSION_ID"},
    ):
        return response

    refresh_on_invalid = getattr(settings, "SALESFORCE_REFRESH_ON_INVALID_SESSION", True)
    if not refresh_on_invalid:
        return response

    refreshed = refresh_salesforce_token(token, timeout=timeout)
    if not refreshed:
        return response

    refreshed_url = _apply_instance_url(refreshed, request_url)
    request_headers["Authorization"] = f"Bearer {refreshed.access_token}"
    try:
        return requests.request(
            method,
            refreshed_url,
            headers=request_headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
        )
    except requests.RequestException:
        return response


def _extract_user_id(userinfo):
    user_id = userinfo.get("user_id")
    if user_id:
        return user_id

    identity_url = userinfo.get("id")
    if identity_url:
        parts = identity_url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return None


def _soql_query(token, soql, timeout=6, tooling=False):
    route = "tooling/query" if tooling else "query"
    url = build_rest_url(token.instance_url, SF_API_VERSION, f"/{route}")
    return salesforce_request(
        token,
        "GET",
        url,
        params={"q": soql},
        timeout=timeout,
    )


def soql_query_all(token, soql, timeout=6, tooling=False):
    response = _soql_query(
        token,
        soql,
        timeout=timeout,
        tooling=tooling,
    )
    if response is None:
        return None, response
    if response.status_code != 200:
        return None, response

    payload = response.json()
    records = payload.get("records", [])
    while not payload.get("done", True):
        next_url = payload.get("nextRecordsUrl")
        if not next_url:
            break
        response = salesforce_request(
            token,
            "GET",
            _join_instance_url(token, next_url),
            timeout=timeout,
        )
        if response is None or response.status_code != 200:
            return records, response
        payload = response.json()
        records.extend(payload.get("records", []))

    return records, response


def _custom_field_full_name(object_name, api_name):
    return f"{object_name}.{api_name}"


def _default_label(api_name):
    label_base = api_name
    if label_base.endswith("__c"):
        label_base = label_base[:-3]
    return label_base.replace("_", " ")


def _custom_field_metadata(field_spec):
    field_type = field_spec["type"]
    label = field_spec.get("label") or _default_label(field_spec["api_name"])
    metadata = {
        "label": label,
        "type": field_type,
    }

    if field_type == "Text":
        metadata["length"] = int(field_spec.get("length", 255))
        if field_spec.get("external_id"):
            metadata["externalId"] = True
    elif field_type == "Currency":
        metadata["precision"] = int(field_spec.get("precision", 18))
        metadata["scale"] = int(field_spec.get("scale", 2))
    elif field_type == "Number":
        metadata["precision"] = int(field_spec.get("precision", 18))
        metadata["scale"] = int(field_spec.get("scale", 0))
    elif field_type == "Checkbox":
        metadata["defaultValue"] = bool(field_spec.get("default_value", False))
    elif field_type == "Picklist":
        values = field_spec.get("values") or []
        metadata["valueSet"] = {
            "valueSetDefinition": {
                "sorted": False,
                "value": [
                    {
                        "fullName": value,
                        "label": value,
                        "default": False,
                    }
                    for value in values
                ],
            }
        }
    elif field_type == "Url":
        display_format = field_spec.get("display_format")
        if display_format:
            metadata["displayFormat"] = display_format
    else:
        raise ValueError(f"Unsupported Salesforce field type: {field_type}")

    return metadata


def _custom_button_full_name(object_name, api_name):
    return f"{object_name}.{api_name}"


def _custom_button_metadata(button_spec):
    label = button_spec.get("label") or button_spec["api_name"].replace("_", " ")
    return {
        "masterLabel": label,
        "linkType": "url",
        "displayType": button_spec.get("display_type", "detailPageButton"),
        "openType": button_spec.get("open_type", "newWindow"),
        "url": button_spec["url"],
        "availability": "online",
    }


def get_agentcpq_base_url(request=None):
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    for key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "BASE_URL", "SITE_URL"):
        value = getattr(settings, key, None) or os.getenv(key)
        if value:
            return str(value).rstrip("/")
    return None


def get_salesforce_userinfo(token, timeout=6):
    if not token or not _use_salesforce_userinfo():
        return None, None
    url = _join_instance_url(token, "/services/oauth2/userinfo")
    response = salesforce_request(
        token,
        "GET",
        url,
        timeout=timeout,
    )
    if response is None or response.status_code != 200:
        return None, response
    return response.json(), response


def get_metadata_server_url(token, timeout=6):
    if not token or not getattr(token, "instance_url", None):
        return None

    userinfo, response = get_salesforce_userinfo(token, timeout=timeout)
    org_id = None
    if userinfo:
        org_id = userinfo.get("organization_id") or userinfo.get("org_id")

    def _format_metadata_url(url_template, org_id):
        if not url_template:
            return None
        version = SF_API_VERSION.lstrip("v")
        url = url_template.replace("{version}", version).replace("v{version}", f"v{version}")
        if org_id:
            url = (
                url.replace("{orgId}", org_id)
                .replace("{organization_id}", org_id)
                .replace("{organizationId}", org_id)
            )
        return url

    if userinfo:
        urls = userinfo.get("urls") or {}
        metadata_url = urls.get("metadata") or userinfo.get("metadataServerUrl") or urls.get("metadataServerUrl")
        if metadata_url:
            formatted = _format_metadata_url(metadata_url, org_id)
            if formatted:
                return formatted

        identity_url = userinfo.get("id")
        if identity_url and not _is_login_host(identity_url):
            headers = _salesforce_headers(token)
            identity_response = requests.get(identity_url, headers=headers, timeout=timeout)
            if identity_response.status_code == 200:
                identity = identity_response.json()
                org_id = identity.get("organization_id") or org_id
                identity_urls = identity.get("urls") or {}
                metadata_url = identity_urls.get("metadata")
                formatted = _format_metadata_url(metadata_url, org_id)
                if formatted:
                    return formatted

    if not org_id:
        cache_key = _limits_cache_key(token).replace("limits", "org")
        org_id = cache.get(cache_key)
        if not org_id:
            query = "SELECT Id FROM Organization LIMIT 1"
            url = build_rest_url(token.instance_url, SF_API_VERSION, "/query")
            response = salesforce_request(
                token,
                "GET",
                url,
                params={"q": query},
                timeout=timeout,
                allow_limits_cache=True,
            )
            if response is not None and response.status_code == 200:
                records = response.json().get("records", [])
                org_id = records[0].get("Id") if records else None
                if org_id:
                    cache.set(cache_key, org_id, 3600)

    if org_id:
        version = SF_API_VERSION.lstrip("v")
        return f"{_normalize_instance_url(token.instance_url)}/services/Soap/m/{version}/{org_id}"

    return None


def build_agentcpq_quote_link(quote_id=None, quote_label=None, request=None):
    base_url = get_agentcpq_base_url(request=request)
    if not base_url:
        return None
    label_value = quote_label or quote_id
    if not label_value:
        return None
    auto_prompt = f"Show Quote Details {label_value}"
    query = urllib.parse.urlencode(
        {
            "view": "agents",
            "new_chat": "true",
            "auto_prompt": auto_prompt,
        }
    )
    return f"{base_url}/dashboard/?{query}"


def get_custom_button(token, object_name, api_name, timeout=6):
    full_name = _custom_button_full_name(object_name, api_name)
    soql = (
        "SELECT Id, Name, FullName "
        f"FROM WebLink WHERE Name = '{api_name}'"
    )
    response = _soql_query(
        token,
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response is None or response.status_code != 200:
        return None, response
    records = response.json().get("records", [])
    for record in records:
        if record.get("FullName") == full_name:
            return record, response
    return None, response


def create_custom_button(token, button_spec, timeout=6):
    payload = {
        "FullName": _custom_button_full_name(button_spec["object"], button_spec["api_name"]),
        "Metadata": _custom_button_metadata(button_spec),
    }
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/tooling/sobjects/WebLink")
    return salesforce_request(
        token,
        "POST",
        url,
        json=payload,
        timeout=timeout,
    )


def _response_error_payload(response):
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _response_has_error_code(response, codes):
    payload = _response_error_payload(response)
    if isinstance(payload, list):
        return any(
            isinstance(entry, dict) and entry.get("errorCode") in codes
            for entry in payload
        )
    if isinstance(payload, dict):
        return payload.get("errorCode") in codes
    return False


def fetch_tooling_object_field_metadata(token, object_name, timeout=6):
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/tooling/sobjects/{object_name}/describe")
    response = salesforce_request(token, "GET", url, timeout=timeout)
    if response is None or response.status_code != 200:
        return None, response
    payload = response.json()
    return payload.get("fields", []), response


def build_weblink_fallback_payload(token, button_spec, timeout=6):
    fields, response = fetch_tooling_object_field_metadata(token, "WebLink", timeout=timeout)
    if fields is None:
        return None, response

    createable = {
        field.get("name", "").lower(): field.get("name")
        for field in fields
        if field.get("name") and field.get("createable")
    }
    payload = {}

    label = button_spec.get("label") or button_spec["api_name"].replace("_", " ")
    full_name = _custom_button_full_name(button_spec["object"], button_spec["api_name"])

    metadata_field = createable.get("metadata") or "Metadata"
    full_name_field = createable.get("fullname") or "FullName"
    developer_field = createable.get("developername") or createable.get("name")
    sobject_field = (
        createable.get("sobjecttype")
        or createable.get("tableenumorid")
        or createable.get("entitydefinitionid")
    )

    payload[metadata_field] = _custom_button_metadata(button_spec)
    payload[full_name_field] = full_name
    if developer_field:
        payload[developer_field] = button_spec["api_name"]
    if sobject_field:
        payload[sobject_field] = button_spec["object"]

    # Preserve label for older orgs that require it outside Metadata.
    if "masterlabel" in createable:
        payload[createable["masterlabel"]] = label

    return payload, None


def create_custom_button_fallback(token, button_spec, timeout=6):
    payload, error = build_weblink_fallback_payload(token, button_spec, timeout=timeout)
    if error:
        return None, error
    if not payload:
        return None, {"error": "No createable WebLink fields found for fallback payload."}
    logger.debug("WebLink tooling fallback payload for %s.%s: %s", button_spec["object"], button_spec["api_name"], payload)
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/tooling/sobjects/WebLink")
    response = salesforce_request(
        token,
        "POST",
        url,
        json=payload,
        timeout=timeout,
    )
    return response, None


def ensure_salesforce_buttons(token, button_specs, timeout=6, dry_run=False):
    results = []
    for button_spec in button_specs:
        object_name = button_spec["object"]
        api_name = button_spec["api_name"]
        existing_button, response = get_custom_button(
            token,
            object_name,
            api_name,
            timeout=timeout,
        )
        if response is None or response.status_code != 200:
            details = None
            if response is None:
                details = "request_failed"
            else:
                try:
                    details = response.json()
                except ValueError:
                    details = response.text
            if dry_run:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "error",
                    "details": details or f"query_http_{getattr(response, 'status_code', 'unknown')}",
                })
                continue

            create_response = create_custom_button(
                token,
                button_spec,
                timeout=timeout,
            )
            if create_response is None:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "error",
                    "details": "create_request_failed",
                })
                continue
            if create_response.status_code in {200, 201}:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "created",
                    "details": create_response.json().get("id"),
                })
                continue

            create_details = None
            try:
                create_details = create_response.json()
            except ValueError:
                create_details = create_response.text

            duplicate = False
            if isinstance(create_details, list):
                duplicate = any(
                    entry.get("errorCode") in {"DUPLICATE_VALUE", "ALREADY_EXISTS"}
                    for entry in create_details
                    if isinstance(entry, dict)
                )
            if duplicate:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "exists",
                    "details": "duplicate_on_create",
                })
            else:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "error",
                    "details": create_details or f"create_http_{create_response.status_code}",
                })
            continue

        if existing_button:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "exists",
                "details": existing_button.get("Id"),
            })
            continue

        if dry_run:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "missing",
                "details": "dry_run",
            })
            continue

        create_response = create_custom_button(
            token,
            button_spec,
            timeout=timeout,
        )
        if create_response is None:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": "create_request_failed",
            })
            continue
        if create_response.status_code >= 400 and _response_has_error_code(
            create_response,
            {"JSON_PARSER_ERROR"},
        ):
            fallback_response, fallback_error = create_custom_button_fallback(
                token,
                button_spec,
                timeout=timeout,
            )
            if fallback_error:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "error",
                    "details": fallback_error,
                })
                continue
            create_response = fallback_response
            if create_response is None:
                results.append({
                    "object": object_name,
                    "api_name": api_name,
                    "status": "error",
                    "details": "fallback_request_failed",
                })
                continue
        if create_response.status_code in {200, 201}:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "created",
                "details": create_response.json().get("id"),
            })
        else:
            details = _response_error_payload(create_response)
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": details or f"create_http_{create_response.status_code}",
            })

    return results


def get_entity_definition_id(token, object_name, timeout=6):
    soql = (
        "SELECT Id, DurableId "
        f"FROM EntityDefinition WHERE QualifiedApiName = '{object_name}' "
        "LIMIT 1"
    )
    response = _soql_query(
        token,
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response is None or response.status_code != 200:
        return None
    records = response.json().get("records", [])
    if not records:
        return None
    record = records[0]
    return record.get("Id") or record.get("DurableId")


def get_custom_field(token, object_name, api_name, timeout=6):
    developer_name = api_name[:-3] if api_name.endswith("__c") else api_name
    soql = (
        "SELECT Id, DeveloperName, TableEnumOrId, FullName"
        f" FROM CustomField WHERE TableEnumOrId = '{object_name}'"
        f" AND DeveloperName = '{developer_name}'"
    )
    response = _soql_query(
        token,
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response is None or response.status_code != 200:
        return None, response

    records = response.json().get("records", [])
    return (records[0] if records else None), response


def create_custom_field(token, object_name, field_spec, timeout=6):
    payload = {
        "FullName": _custom_field_full_name(object_name, field_spec["api_name"]),
        "Metadata": _custom_field_metadata(field_spec),
    }
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/tooling/sobjects/CustomField")
    return salesforce_request(
        token,
        "POST",
        url,
        json=payload,
        timeout=timeout,
    )


def ensure_salesforce_fields(token, required_fields, timeout=6, dry_run=False):
    results = []
    for field_spec in required_fields:
        object_name = field_spec["object"]
        api_name = field_spec["api_name"]
        existing_field, response = get_custom_field(
            token,
            object_name,
            api_name,
            timeout=timeout,
        )
        if response is None or response.status_code != 200:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": f"query_http_{getattr(response, 'status_code', 'unknown')}",
            })
            continue

        if existing_field:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "exists",
                "details": existing_field.get("Id"),
            })
            continue

        if dry_run:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "missing",
                "details": "dry_run",
            })
            continue

        create_response = create_custom_field(
            token,
            object_name,
            field_spec,
            timeout=timeout,
        )
        if create_response is None:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": "create_request_failed",
            })
            continue
        if create_response.status_code in {200, 201}:
            try:
                from cpq.events import emit_domain_event
                emit_domain_event(
                    "SALESFORCE.FIELD.CREATED",
                    payload={
                        "object": object_name,
                        "api_name": api_name,
                        "salesforce_id": create_response.json().get("id"),
                    },
                    object_type=object_name,
                    object_id=api_name,
                    source="salesforce_tooling",
                    idempotency_key=f"{object_name}:{api_name}",
                )
            except Exception:
                pass
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "created",
                "details": create_response.json().get("id"),
            })
        else:
            details = None
            try:
                details = create_response.json()
            except ValueError:
                details = create_response.text
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": details or f"create_http_{create_response.status_code}",
            })

    return results


def validate_salesforce_connection(token, timeout=6):
    status = {
        "authenticated": False,
        "permissions": {
            "CustomizeApplication": False,
            "ModifyAllData": False,
        },
        "tooling_api_enabled": False,
        "user_id": None,
        "errors": [],
    }

    if not token:
        status["errors"].append("missing_token")
        return status

    token = get_valid_salesforce_token(timeout=timeout) or token
    if not _is_valid_instance_url(token.instance_url):
        status["errors"].append("invalid_instance_url")
        return status

    limits_ok, limits_response, token = salesforce_limits_check(
        token,
        timeout=timeout,
        allow_cache=False,
    )
    if not limits_ok:
        if limits_response is None:
            status["errors"].append("limits_request_failed")
        else:
            status["errors"].append(f"limits_http_{limits_response.status_code}")
        return status

    status["authenticated"] = True

    userinfo, userinfo_response = get_salesforce_userinfo(token, timeout=timeout)
    if userinfo:
        user_id = _extract_user_id(userinfo)
        status["user_id"] = user_id
    elif userinfo_response is not None:
        status["errors"].append(f"userinfo_http_{userinfo_response.status_code}")
    else:
        status["errors"].append("userinfo_skipped")

    if status["user_id"]:
        soql = (
            "SELECT UserPermissionsCustomizeApplication,"
            " UserPermissionsModifyAllData"
            f" FROM User WHERE Id = '{status['user_id']}'"
        )
        perm_response = _soql_query(
            token,
            soql,
            timeout=timeout,
            tooling=False,
        )
        if perm_response is None:
            status["errors"].append("permissions_request_failed")
        elif perm_response.status_code == 200:
            records = perm_response.json().get("records", [])
            if records:
                record = records[0]
                status["permissions"]["CustomizeApplication"] = bool(
                    record.get("UserPermissionsCustomizeApplication")
                )
                status["permissions"]["ModifyAllData"] = bool(
                    record.get("UserPermissionsModifyAllData")
                )
            else:
                status["errors"].append("permission_record_missing")
        else:
            status["errors"].append(f"permissions_http_{perm_response.status_code}")
    else:
        status["errors"].append("permissions_unchecked")

    tooling_response = _soql_query(
        token,
        "SELECT Id FROM EntityDefinition LIMIT 1",
        timeout=timeout,
        tooling=True,
    )
    if tooling_response is None:
        status["errors"].append("tooling_request_failed")
    elif tooling_response.status_code == 200:
        status["tooling_api_enabled"] = True
    else:
        status["errors"].append(f"tooling_http_{tooling_response.status_code}")

    return status


def fetch_salesforce_object_fields(token, object_name, timeout=6):
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe")
    response = salesforce_request(token, "GET", url, timeout=timeout)
    if response is None or response.status_code != 200:
        return None, response
    payload = response.json()
    fields = [
        {"name": field.get("name"), "label": field.get("label")}
        for field in payload.get("fields", [])
        if field.get("name")
    ]
    return fields, response


def fetch_salesforce_object_field_metadata(token, object_name, timeout=6):
    url = _join_instance_url(token, f"/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe")
    response = salesforce_request(token, "GET", url, timeout=timeout)
    if response is None or response.status_code != 200:
        return None, response
    payload = response.json()
    return payload.get("fields", []), response
