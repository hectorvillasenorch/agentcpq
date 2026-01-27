from __future__ import annotations

import datetime
import os
import urllib.parse
import requests
from django.conf import settings
from django.utils import timezone

from salesforce.models import SalesforceToken

SF_API_VERSION = "v57.0"


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
    token.instance_url = data.get("instance_url", token.instance_url)
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
    if token.expires_at and token.expires_at <= timezone.now():
        if token.refresh_token:
            refreshed = refresh_salesforce_token(token, timeout=timeout)
            return refreshed
        return None
    if token.refresh_token and not token.expires_at:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        return refreshed or token
    return token


def salesforce_request(token, method, url, *, params=None, data=None, json=None, headers=None, timeout=6):
    if not token:
        return None

    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request_headers["Authorization"] = f"Bearer {token.access_token}"

    try:
        response = requests.request(
            method,
            url,
            headers=request_headers,
            params=params,
            data=data,
            json=json,
            timeout=timeout,
        )
    except requests.RequestException:
        return None

    if response.status_code != 401:
        return response

    refreshed = refresh_salesforce_token(token, timeout=timeout)
    if not refreshed:
        return response

    refreshed_url = url
    if token.instance_url and refreshed.instance_url and url.startswith(token.instance_url):
        refreshed_url = f"{refreshed.instance_url}{url[len(token.instance_url):]}"

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


def _soql_query(instance_url, headers, soql, timeout=6, tooling=False):
    route = "tooling/query" if tooling else "query"
    url = f"{instance_url}/services/data/{SF_API_VERSION}/{route}"
    return requests.get(url, headers=headers, params={"q": soql}, timeout=timeout)


def soql_query_all(token, soql, timeout=6, tooling=False):
    headers = _salesforce_headers(token)
    response = _soql_query(
        token.instance_url,
        headers,
        soql,
        timeout=timeout,
        tooling=tooling,
    )
    if response.status_code == 401:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        if refreshed:
            headers = _salesforce_headers(refreshed)
            response = _soql_query(
                refreshed.instance_url,
                headers,
                soql,
                timeout=timeout,
                tooling=tooling,
            )
    if response.status_code != 200:
        return None, response

    payload = response.json()
    records = payload.get("records", [])
    while not payload.get("done", True):
        next_url = payload.get("nextRecordsUrl")
        if not next_url:
            break
        response = requests.get(
            f"{token.instance_url}{next_url}",
            headers=headers,
            timeout=timeout,
        )
        if response.status_code != 200:
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
        f"FROM WebLink WHERE FullName = '{full_name}'"
    )
    response = _soql_query(
        token.instance_url,
        _salesforce_headers(token),
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response.status_code != 200:
        return None, response
    records = response.json().get("records", [])
    return (records[0] if records else None), response


def create_custom_button(token, button_spec, timeout=6):
    payload = {
        "FullName": _custom_button_full_name(button_spec["object"], button_spec["api_name"]),
        "Metadata": _custom_button_metadata(button_spec),
    }
    url = f"{token.instance_url}/services/data/{SF_API_VERSION}/tooling/sobjects/WebLink"
    return requests.post(
        url,
        headers=_salesforce_headers(token),
        json=payload,
        timeout=timeout,
    )


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
        if response.status_code != 200:
            details = None
            try:
                details = response.json()
            except ValueError:
                details = response.text
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": details or f"query_http_{response.status_code}",
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
        if create_response.status_code in {200, 201}:
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


def get_entity_definition_id(token, object_name, timeout=6):
    soql = (
        "SELECT Id, DurableId "
        f"FROM EntityDefinition WHERE QualifiedApiName = '{object_name}' "
        "LIMIT 1"
    )
    response = _soql_query(
        token.instance_url,
        _salesforce_headers(token),
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response.status_code != 200:
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
        token.instance_url,
        _salesforce_headers(token),
        soql,
        timeout=timeout,
        tooling=True,
    )
    if response.status_code != 200:
        return None, response

    records = response.json().get("records", [])
    return (records[0] if records else None), response


def create_custom_field(token, object_name, field_spec, timeout=6):
    payload = {
        "FullName": _custom_field_full_name(object_name, field_spec["api_name"]),
        "Metadata": _custom_field_metadata(field_spec),
    }
    url = f"{token.instance_url}/services/data/{SF_API_VERSION}/tooling/sobjects/CustomField"
    return requests.post(
        url,
        headers=_salesforce_headers(token),
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
        if response.status_code != 200:
            results.append({
                "object": object_name,
                "api_name": api_name,
                "status": "error",
                "details": f"query_http_{response.status_code}",
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

    if token.expires_at and token.expires_at <= timezone.now():
        token = refresh_salesforce_token(token, timeout=timeout)
        if not token:
            status["errors"].append("token_expired")
            return status

    headers = _salesforce_headers(token)
    try:
        userinfo_response = requests.get(
            f"{token.instance_url}/services/oauth2/userinfo",
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException:
        status["errors"].append("userinfo_request_failed")
        return status

    if userinfo_response.status_code != 200:
        status["errors"].append(f"userinfo_http_{userinfo_response.status_code}")
        return status

    status["authenticated"] = True
    userinfo = userinfo_response.json() if userinfo_response.content else {}
    user_id = _extract_user_id(userinfo)
    status["user_id"] = user_id

    if user_id:
        soql = (
            "SELECT UserPermissionsCustomizeApplication,"
            " UserPermissionsModifyAllData"
            f" FROM User WHERE Id = '{user_id}'"
        )
        try:
            perm_response = _soql_query(
                token.instance_url,
                headers,
                soql,
                timeout=timeout,
                tooling=False,
            )
            if perm_response.status_code == 200:
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
        except requests.RequestException:
            status["errors"].append("permissions_request_failed")

    try:
        tooling_response = _soql_query(
            token.instance_url,
            headers,
            "SELECT Id FROM EntityDefinition LIMIT 1",
            timeout=timeout,
            tooling=True,
        )
        if tooling_response.status_code == 200:
            status["tooling_api_enabled"] = True
        else:
            status["errors"].append(f"tooling_http_{tooling_response.status_code}")
    except requests.RequestException:
        status["errors"].append("tooling_request_failed")

    return status


def fetch_salesforce_object_fields(token, object_name, timeout=6):
    url = f"{token.instance_url}/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe"
    response = requests.get(url, headers=_salesforce_headers(token), timeout=timeout)
    if response.status_code == 401:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        if refreshed:
            url = f"{refreshed.instance_url}/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe"
            response = requests.get(url, headers=_salesforce_headers(refreshed), timeout=timeout)
    if response.status_code != 200:
        return None, response
    payload = response.json()
    fields = [
        {"name": field.get("name"), "label": field.get("label")}
        for field in payload.get("fields", [])
        if field.get("name")
    ]
    return fields, response


def fetch_salesforce_object_field_metadata(token, object_name, timeout=6):
    url = f"{token.instance_url}/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe"
    response = requests.get(url, headers=_salesforce_headers(token), timeout=timeout)
    if response.status_code == 401:
        refreshed = refresh_salesforce_token(token, timeout=timeout)
        if refreshed:
            url = f"{refreshed.instance_url}/services/data/{SF_API_VERSION}/sobjects/{object_name}/describe"
            response = requests.get(url, headers=_salesforce_headers(refreshed), timeout=timeout)
    if response.status_code != 200:
        return None, response
    payload = response.json()
    return payload.get("fields", []), response
