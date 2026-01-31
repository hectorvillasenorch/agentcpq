import base64
import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests
from django.conf import settings

from salesforce.endpoints import build_metadata_soap_url
from salesforce.utils import (
    SF_API_VERSION,
    ensure_valid_access_token,
    get_metadata_server_url,
)

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
METADATA_NS = "http://soap.sforce.com/2006/04/metadata"
NSMAP = {"env": SOAP_ENV_NS, "met": METADATA_NS}


def _metadata_version():
    return SF_API_VERSION.lstrip("v")


def _soap_envelope(body_xml, session_id):
    safe_session = escape(session_id or "")
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<env:Envelope xmlns:env=\"http://schemas.xmlsoap.org/soap/envelope/\" "
        "xmlns:tns=\"http://soap.sforce.com/2006/04/metadata\">"
        "<env:Header>"
        "<tns:SessionHeader>"
        f"<tns:sessionId>{safe_session}</tns:sessionId>"
        "</tns:SessionHeader>"
        "</env:Header>"
        "<env:Body>"
        f"{body_xml}"
        "</env:Body>"
        "</env:Envelope>"
    )


def _parse_soap_fault(root):
    fault = root.find(".//env:Fault", NSMAP)
    if fault is None:
        return None
    fault_string = fault.findtext("faultstring")
    return {"fault": fault_string or "Unknown SOAP fault"}


def _extract_text(node, tag):
    child = node.find(f"met:{tag}", NSMAP)
    return child.text if child is not None else None


def _metadata_endpoint(token, timeout=6):
    metadata_url = get_metadata_server_url(token, timeout=timeout)
    if metadata_url:
        return metadata_url
    version = _metadata_version()
    return build_metadata_soap_url(token.instance_url, version)


def _ensure_metadata_session(token, timeout=6):
    if not token:
        return None
    token = ensure_valid_access_token(token, timeout=timeout, allow_limits_cache=False)
    return token


def describe_metadata(token, timeout=30):
    endpoint = _metadata_endpoint(token, timeout=timeout)
    version = _metadata_version()
    body = (
        "<tns:describeMetadata>"
        f"<tns:asOfVersion>{version}</tns:asOfVersion>"
        "</tns:describeMetadata>"
    )
    envelope = _soap_envelope(body, token.access_token)
    response = requests.post(
        endpoint,
        data=envelope,
        headers={"Content-Type": "text/xml", "SOAPAction": "describeMetadata"},
        timeout=timeout,
    )
    if response.status_code != 200:
        return None, {"http_status": response.status_code, "body": response.text}

    root = ET.fromstring(response.text)
    fault = _parse_soap_fault(root)
    if fault:
        return None, fault

    metadata_objects = []
    for node in root.findall(".//met:metadataObjects", NSMAP):
        entry = {
            "xmlName": _extract_text(node, "xmlName"),
            "directoryName": _extract_text(node, "directoryName"),
            "suffix": _extract_text(node, "suffix"),
            "metaFile": _extract_text(node, "metaFile"),
        }
        metadata_objects.append(entry)
    return metadata_objects, None


def get_metadata_type_info(token, type_name, timeout=30):
    objects, error = describe_metadata(token, timeout=timeout)
    if error or not objects:
        return None, error
    for entry in objects:
        if entry.get("xmlName") == type_name:
            return entry, None
    return None, {"error": f"Metadata type {type_name} not found."}


def _build_lwc_package_xml(bundle_name):
    version = _metadata_version()
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<Package xmlns=\"http://soap.sforce.com/2006/04/metadata\">"
        "<types>"
        f"<members>{bundle_name}</members>"
        "<name>LightningComponentBundle</name>"
        "</types>"
        f"<version>{version}</version>"
        "</Package>"
    )


def _build_package_xml(type_members):
    version = _metadata_version()
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<Package xmlns=\"http://soap.sforce.com/2006/04/metadata\">"]
    for type_name, members in type_members.items():
        if not members:
            continue
        body.append("<types>")
        for member in members:
            body.append(f"<members>{escape(member)}</members>")
        body.append(f"<name>{escape(type_name)}</name>")
        body.append("</types>")
    body.append(f"<version>{version}</version>")
    body.append("</Package>")
    return "".join(body)


def build_weblink_metadata_xml(button_spec):
    label = button_spec.get("label") or button_spec["api_name"].replace("_", " ")
    display_type = button_spec.get("display_type", "detailPageButton")
    open_type = button_spec.get("open_type", "newWindow")
    url = button_spec["url"]
    full_name = f"{button_spec['object']}.{button_spec['api_name']}"
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<WebLink xmlns=\"http://soap.sforce.com/2006/04/metadata\">"
        f"<fullName>{escape(full_name)}</fullName>"
        "<availability>online</availability>"
        f"<displayType>{escape(display_type)}</displayType>"
        "<encodingKey>UTF-8</encodingKey>"
        "<linkType>url</linkType>"
        f"<masterLabel>{escape(label)}</masterLabel>"
        f"<openType>{escape(open_type)}</openType>"
        f"<url>{escape(url)}</url>"
        "</WebLink>"
    )


def build_weblink_zip(token, button_specs, timeout=30):
    metadata_info, error = get_metadata_type_info(token, "WebLink", timeout=timeout)
    if error or not metadata_info:
        # Fall back to standard WebLink metadata folder/suffix.
        directory = "webLinks"
        suffix = "webLink"
    else:
        directory = metadata_info.get("directoryName")
        suffix = metadata_info.get("suffix")
        if not directory or not suffix:
            return None, {"error": "WebLink metadata directory/suffix unavailable."}

    members = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for button_spec in button_specs:
            full_name = f"{button_spec['object']}.{button_spec['api_name']}"
            members.append(full_name)
            filename = f"{directory}/{full_name}.{suffix}"
            zf.writestr(filename, build_weblink_metadata_xml(button_spec))

        package_xml = _build_package_xml({"WebLink": members})
        zf.writestr("package.xml", package_xml)

    return buffer.getvalue(), None


def deploy_salesforce_weblinks(token, button_specs, timeout=60, poll_interval=3, max_polls=8):
    if not token or not token.access_token:
        return [{
            "object": "WebLink",
            "api_name": spec["api_name"],
            "status": "error",
            "details": "Missing Salesforce access token.",
        } for spec in button_specs]

    token = _ensure_metadata_session(token, timeout=timeout)
    if not token:
        return [{
            "object": "WebLink",
            "api_name": spec["api_name"],
            "status": "error",
            "details": "Salesforce session invalid. Reconnect Salesforce.",
        } for spec in button_specs]

    zip_bytes, error = build_weblink_zip(token, button_specs, timeout=timeout)
    if error:
        return [{
            "object": "WebLink",
            "api_name": spec["api_name"],
            "status": "error",
            "details": error,
        } for spec in button_specs]

    endpoint = _metadata_endpoint(token, timeout=timeout)
    async_id, deploy_error = deploy_metadata_zip(token, zip_bytes, timeout=timeout, endpoint=endpoint)
    if deploy_error:
        fault_message = str(deploy_error.get("fault") or "")
        if "INVALID_SESSION_ID" in fault_message and getattr(
            settings,
            "SALESFORCE_REFRESH_ON_INVALID_SESSION",
            True,
        ):
            token = _ensure_metadata_session(token, timeout=timeout)
            endpoint = _metadata_endpoint(token, timeout=timeout)
            async_id, deploy_error = deploy_metadata_zip(token, zip_bytes, timeout=timeout, endpoint=endpoint)
        if deploy_error:
            return [{
                "object": "WebLink",
                "api_name": spec["api_name"],
                "status": "error",
                "details": deploy_error,
            } for spec in button_specs]

    last_status = {"status": "pending", "details": {"status": "Queued"}}
    for _ in range(max_polls):
        last_status = check_deploy_status(token, async_id, timeout=timeout, endpoint=endpoint)
        if last_status["status"] in {"success", "error"}:
            break
        time.sleep(poll_interval)

    results = []
    if last_status["status"] == "success":
        for spec in button_specs:
            results.append({
                "object": "WebLink",
                "api_name": spec["api_name"],
                "status": "created",
                "details": "deployed",
            })
        return results

    failures = (last_status.get("details") or {}).get("component_failures", [])
    failure_map = {
        (entry.get("componentType"), entry.get("fullName")): entry
        for entry in failures
        if entry.get("fullName")
    }
    for spec in button_specs:
        full_name = f"{spec['object']}.{spec['api_name']}"
        failure = failure_map.get(("WebLink", full_name))
        if failure:
            results.append({
                "object": "WebLink",
                "api_name": spec["api_name"],
                "status": "error",
                "details": failure.get("problem") or failure,
            })
        else:
            results.append({
                "object": "WebLink",
                "api_name": spec["api_name"],
                "status": last_status["status"],
                "details": last_status.get("details"),
            })
    return results


def collect_lwc_bundle_files(bundle_name):
    base_dir = os.path.join(os.path.dirname(__file__), "metadata", "lwc", bundle_name)
    if not os.path.isdir(base_dir):
        return None, f"Missing LWC bundle directory: {base_dir}"

    files = []
    for filename in os.listdir(base_dir):
        file_path = os.path.join(base_dir, filename)
        if not os.path.isfile(file_path):
            continue
        arcname = f"lwc/{bundle_name}/{filename}"
        with open(file_path, "rb") as handle:
            files.append((arcname, handle.read()))
    return files, None


def build_lwc_bundle_zip(bundle_name):
    files, error = collect_lwc_bundle_files(bundle_name)
    if error:
        return None, error

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.xml", _build_lwc_package_xml(bundle_name))
        for path, content in files:
            zf.writestr(path, content)

    return buffer.getvalue(), None


def deploy_metadata_zip(token, zip_bytes, timeout=30, endpoint=None):
    endpoint = endpoint or _metadata_endpoint(token, timeout=timeout)
    zip_payload = base64.b64encode(zip_bytes).decode("ascii")
    body = (
        "<tns:deploy>"
        f"<tns:ZipFile>{zip_payload}</tns:ZipFile>"
        "<tns:DeployOptions>"
        "<tns:allowMissingFiles>false</tns:allowMissingFiles>"
        "<tns:autoUpdatePackage>false</tns:autoUpdatePackage>"
        "<tns:checkOnly>false</tns:checkOnly>"
        "<tns:ignoreWarnings>true</tns:ignoreWarnings>"
        "<tns:rollbackOnError>true</tns:rollbackOnError>"
        "<tns:singlePackage>true</tns:singlePackage>"
        "</tns:DeployOptions>"
        "</tns:deploy>"
    )

    envelope = _soap_envelope(body, token.access_token)
    response = requests.post(
        endpoint,
        data=envelope,
        headers={"Content-Type": "text/xml", "SOAPAction": "deploy"},
        timeout=timeout,
    )

    if response.status_code != 200:
        return None, {"http_status": response.status_code, "body": response.text}

    root = ET.fromstring(response.text)
    fault = _parse_soap_fault(root)
    if fault:
        return None, fault

    async_id = root.findtext(".//met:id", namespaces=NSMAP)
    if not async_id:
        return None, {"error": "Missing async deploy id", "body": response.text}

    return async_id, None


def check_deploy_status(token, async_id, timeout=30, include_details=True, endpoint=None, retry_on_invalid_session=True):
    endpoint = endpoint or _metadata_endpoint(token, timeout=timeout)
    details_flag = "true" if include_details else "false"
    body = (
        "<tns:checkDeployStatus>"
        f"<tns:asyncProcessId>{async_id}</tns:asyncProcessId>"
        f"<tns:includeDetails>{details_flag}</tns:includeDetails>"
        "</tns:checkDeployStatus>"
    )
    envelope = _soap_envelope(body, token.access_token)
    response = requests.post(
        endpoint,
        data=envelope,
        headers={"Content-Type": "text/xml", "SOAPAction": "checkDeployStatus"},
        timeout=timeout,
    )

    if response.status_code != 200:
        return {"status": "error", "details": {"http_status": response.status_code, "body": response.text}}

    root = ET.fromstring(response.text)
    fault = _parse_soap_fault(root)
    if fault:
        if (
            retry_on_invalid_session
            and "INVALID_SESSION_ID" in (fault.get("fault") or "")
            and getattr(settings, "SALESFORCE_REFRESH_ON_INVALID_SESSION", True)
        ):
            refreshed = _ensure_metadata_session(token, timeout=timeout)
            if refreshed:
                return check_deploy_status(
                    refreshed,
                    async_id,
                    timeout=timeout,
                    include_details=include_details,
                    endpoint=_metadata_endpoint(refreshed, timeout=timeout),
                    retry_on_invalid_session=False,
                )
        return {"status": "error", "details": fault}

    result_node = root.find(".//met:result", NSMAP)
    if result_node is None:
        return {"status": "error", "details": {"error": "Missing deploy result"}}

    done = (_extract_text(result_node, "done") or "").lower() == "true"
    success = (_extract_text(result_node, "success") or "").lower() == "true"
    status = _extract_text(result_node, "status") or "Unknown"
    message = _extract_text(result_node, "errorMessage") or _extract_text(result_node, "errorStatusCode")

    failures = []
    component_failures = []
    for failure in result_node.findall(".//met:componentFailures", NSMAP):
        problem = _extract_text(failure, "problem") or _extract_text(failure, "problemType")
        filename = _extract_text(failure, "fileName")
        full_name = _extract_text(failure, "fullName")
        component_type = _extract_text(failure, "componentType")
        line = _extract_text(failure, "lineNumber")
        column = _extract_text(failure, "columnNumber")
        detail = " ".join(
            part for part in [filename or full_name, problem, f"line {line}" if line else None, f"col {column}" if column else None]
            if part
        )
        if detail:
            failures.append(detail)
        component_failures.append({
            "componentType": component_type,
            "fullName": full_name,
            "problem": problem,
            "fileName": filename,
            "line": line,
            "column": column,
        })

    details = {
        "status": status,
        "message": message,
        "failures": failures,
        "component_failures": component_failures,
    }

    if done and success:
        return {"status": "success", "details": details}
    if done and not success:
        return {"status": "error", "details": details}
    return {"status": "pending", "details": details}


def deploy_agentcpq_lwc(token, timeout=60, poll_interval=3, max_polls=8):
    bundle_name = "agentcpqQuotePanel"
    if not token or not token.access_token:
        return {
            "object": "LightningComponentBundle",
            "api_name": bundle_name,
            "status": "error",
            "details": "Missing Salesforce access token.",
        }

    token = _ensure_metadata_session(token, timeout=timeout)
    if not token:
        return {
            "object": "LightningComponentBundle",
            "api_name": bundle_name,
            "status": "error",
            "details": "Salesforce session invalid. Reconnect Salesforce.",
        }
    zip_bytes, error = build_lwc_bundle_zip(bundle_name)
    if error:
        return {
            "object": "LightningComponentBundle",
            "api_name": bundle_name,
            "status": "error",
            "details": error,
        }

    endpoint = _metadata_endpoint(token, timeout=timeout)
    async_id, deploy_error = deploy_metadata_zip(token, zip_bytes, timeout=timeout, endpoint=endpoint)
    if deploy_error:
        fault_message = str(deploy_error.get("fault") or "")
        if "INVALID_SESSION_ID" in fault_message and getattr(
            settings,
            "SALESFORCE_REFRESH_ON_INVALID_SESSION",
            True,
        ):
            token = _ensure_metadata_session(token, timeout=timeout)
            endpoint = _metadata_endpoint(token, timeout=timeout)
            async_id, deploy_error = deploy_metadata_zip(token, zip_bytes, timeout=timeout, endpoint=endpoint)
        if deploy_error:
            return {
                "object": "LightningComponentBundle",
                "api_name": bundle_name,
                "status": "error",
                "details": deploy_error,
            }
    if not async_id:
        return {
            "object": "LightningComponentBundle",
            "api_name": bundle_name,
            "status": "error",
            "details": deploy_error or "Missing deploy id",
        }

    last_status = {"status": "pending", "details": {"status": "Queued"}}
    for _ in range(max_polls):
        last_status = check_deploy_status(token, async_id, timeout=timeout, endpoint=endpoint)
        if last_status["status"] in {"success", "error"}:
            break
        time.sleep(poll_interval)

    return {
        "object": "LightningComponentBundle",
        "api_name": bundle_name,
        "status": last_status["status"],
        "details": last_status.get("details"),
    }
