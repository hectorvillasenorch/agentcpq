import base64
import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET

import requests

from salesforce.utils import SF_API_VERSION, refresh_salesforce_token

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
METADATA_NS = "http://soap.sforce.com/2006/04/metadata"
NSMAP = {"env": SOAP_ENV_NS, "met": METADATA_NS}


def _metadata_version():
    return SF_API_VERSION.lstrip("v")


def _soap_envelope(body_xml, session_id):
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<env:Envelope xmlns:env=\"http://schemas.xmlsoap.org/soap/envelope/\" "
        "xmlns:met=\"http://soap.sforce.com/2006/04/metadata\">"
        "<env:Header>"
        "<met:SessionHeader>"
        f"<met:sessionId>{session_id}</met:sessionId>"
        "</met:SessionHeader>"
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


def _metadata_endpoint(token):
    version = _metadata_version()
    return f"{token.instance_url}/services/Soap/m/{version}"


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


def build_lwc_bundle_zip(bundle_name):
    base_dir = os.path.join(os.path.dirname(__file__), "metadata", "lwc", bundle_name)
    if not os.path.isdir(base_dir):
        return None, f"Missing LWC bundle directory: {base_dir}"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.xml", _build_lwc_package_xml(bundle_name))
        for filename in os.listdir(base_dir):
            file_path = os.path.join(base_dir, filename)
            if not os.path.isfile(file_path):
                continue
            arcname = f"lwc/{bundle_name}/{filename}"
            zf.write(file_path, arcname)

    return buffer.getvalue(), None


def deploy_metadata_zip(token, zip_bytes, timeout=30):
    endpoint = _metadata_endpoint(token)
    zip_payload = base64.b64encode(zip_bytes).decode("ascii")
    body = (
        "<met:deploy>"
        f"<met:ZipFile>{zip_payload}</met:ZipFile>"
        "<met:DeployOptions>"
        "<met:allowMissingFiles>false</met:allowMissingFiles>"
        "<met:autoUpdatePackage>false</met:autoUpdatePackage>"
        "<met:checkOnly>false</met:checkOnly>"
        "<met:ignoreWarnings>true</met:ignoreWarnings>"
        "<met:rollbackOnError>true</met:rollbackOnError>"
        "<met:singlePackage>true</met:singlePackage>"
        "</met:DeployOptions>"
        "</met:deploy>"
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


def check_deploy_status(token, async_id, timeout=30, include_details=True):
    endpoint = _metadata_endpoint(token)
    details_flag = "true" if include_details else "false"
    body = (
        "<met:checkDeployStatus>"
        f"<met:asyncProcessId>{async_id}</met:asyncProcessId>"
        f"<met:includeDetails>{details_flag}</met:includeDetails>"
        "</met:checkDeployStatus>"
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
        return {"status": "error", "details": fault}

    result_node = root.find(".//met:result", NSMAP)
    if result_node is None:
        return {"status": "error", "details": {"error": "Missing deploy result"}}

    done = (_extract_text(result_node, "done") or "").lower() == "true"
    success = (_extract_text(result_node, "success") or "").lower() == "true"
    status = _extract_text(result_node, "status") or "Unknown"
    message = _extract_text(result_node, "errorMessage") or _extract_text(result_node, "errorStatusCode")

    failures = []
    for failure in result_node.findall(".//met:componentFailures", NSMAP):
        problem = _extract_text(failure, "problem") or _extract_text(failure, "problemType")
        filename = _extract_text(failure, "fileName")
        full_name = _extract_text(failure, "fullName")
        line = _extract_text(failure, "lineNumber")
        column = _extract_text(failure, "columnNumber")
        detail = " ".join(
            part for part in [filename or full_name, problem, f"line {line}" if line else None, f"col {column}" if column else None]
            if part
        )
        if detail:
            failures.append(detail)

    details = {
        "status": status,
        "message": message,
        "failures": failures,
    }

    if done and success:
        return {"status": "success", "details": details}
    if done and not success:
        return {"status": "error", "details": details}
    return {"status": "pending", "details": details}


def deploy_agentcpq_lwc(token, timeout=60, poll_interval=3, max_polls=8):
    bundle_name = "agentcpqQuotePanel"
    zip_bytes, error = build_lwc_bundle_zip(bundle_name)
    if error:
        return {
            "object": "LightningComponentBundle",
            "api_name": bundle_name,
            "status": "error",
            "details": error,
        }

    async_id, deploy_error = deploy_metadata_zip(token, zip_bytes, timeout=timeout)
    if deploy_error:
        fault_message = str(deploy_error.get("fault") or "")
        if "INVALID_SESSION_ID" in fault_message:
            refreshed = refresh_salesforce_token(token, timeout=timeout)
            if refreshed:
                async_id, deploy_error = deploy_metadata_zip(refreshed, zip_bytes, timeout=timeout)
                token = refreshed
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
        last_status = check_deploy_status(token, async_id, timeout=timeout)
        if last_status["status"] in {"success", "error"}:
            break
        time.sleep(poll_interval)

    return {
        "object": "LightningComponentBundle",
        "api_name": bundle_name,
        "status": last_status["status"],
        "details": last_status.get("details"),
    }
