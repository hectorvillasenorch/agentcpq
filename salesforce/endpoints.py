from urllib.parse import urlparse


def normalize_instance_url(value):
    if not value:
        return None
    return str(value).strip().rstrip("/")


def is_login_host(url):
    host = urlparse(url or "").hostname or ""
    return host in {"login.salesforce.com", "test.salesforce.com"}


def join_instance_url(instance_url, path, query=None):
    base = normalize_instance_url(instance_url)
    if not base:
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    suffix = f"?{query}" if query else ""
    return f"{base}{path}{suffix}"


def apply_instance_url(instance_url, url):
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        return join_instance_url(instance_url, url)
    base = normalize_instance_url(instance_url)
    if not base:
        return url
    base_host = urlparse(base).hostname or ""
    request_host = parsed.hostname or ""
    if base_host and request_host and request_host != base_host:
        return join_instance_url(base, parsed.path, parsed.query)
    return url


def build_rest_url(instance_url, api_version, path):
    path_value = path or ""
    if not path_value.startswith("/"):
        path_value = f"/{path_value}"
    if not path_value.startswith("/services/data/"):
        path_value = f"/services/data/{api_version}{path_value}"
    return join_instance_url(instance_url, path_value)


def build_metadata_soap_url(instance_url, api_version):
    return join_instance_url(instance_url, f"/services/Soap/m/{api_version}")


def build_oauth_identity_url(identity_url):
    return identity_url
