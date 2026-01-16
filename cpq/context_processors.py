from __future__ import annotations

from typing import Dict

from django.db.utils import OperationalError
from django.core.files.storage import default_storage

from .models import Tenant


def _hex_to_rgb(hex_value: str):
    if not hex_value:
        return None
    value = hex_value.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
        return r, g, b
    except ValueError:
        return None


def _is_light(hex_value: str) -> bool:
    rgb = _hex_to_rgb(hex_value)
    if not rgb:
        return False
    r, g, b = rgb
    # Relative luminance (sRGB approx)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 160


def tenant_theme(request) -> Dict[str, Dict[str, str]]:  # noqa: ARG001
    defaults = {
        "sidenav_bg_1": "#041530",
        "sidenav_bg_2": "#233049",
        "sidenav_text": "#ffffff",
        "sidenav_hover_bg": "rgba(255, 255, 255, 0.08)",
        "sidenav_divider": "rgba(255, 255, 255, 0.08)",
        "sidenav_muted": "#bdbdbd",
        "sidenav_icon_muted": "#9e9e9e",
        "sidenav_card_bg": "rgba(0, 0, 0, 0.47)",
    }

    try:
        tenant = Tenant.safe_first()
    except OperationalError:
        tenant = None
    except Exception:
        tenant = None

    if not tenant:
        return {
            "tenant_theme": defaults,
            "tenant_version": "",
            "tenant_name": "",
            "tenant_logo_url": "",
        }

    logo_url = ""
    if getattr(tenant, "logo", None) and getattr(tenant.logo, "name", None):
        try:
            logo_url = default_storage.url(tenant.logo.name)
        except Exception:
            try:
                logo_url = tenant.logo.url  # type: ignore[attr-defined]
            except Exception:
                logo_url = ""

    bg1 = tenant.sidebar_bg_color_1 or defaults["sidenav_bg_1"]
    bg2 = tenant.sidebar_bg_color_2 or defaults["sidenav_bg_2"]
    fg = tenant.sidebar_text_color or defaults["sidenav_text"]

    if _is_light(bg1):
        hover = "rgba(15, 23, 42, 0.06)"
        divider = "rgba(15, 23, 42, 0.08)"
        muted = "#6b7280"
        icon_muted = "#6b7280"
        card_bg = "rgba(15, 23, 42, 0.06)"
    else:
        hover = defaults["sidenav_hover_bg"]
        divider = defaults["sidenav_divider"]
        muted = defaults["sidenav_muted"]
        icon_muted = defaults["sidenav_icon_muted"]
        card_bg = defaults["sidenav_card_bg"]

    return {
        "tenant_theme": {
            **defaults,
            "sidenav_bg_1": bg1,
            "sidenav_bg_2": bg2,
            "sidenav_text": fg,
            "sidenav_hover_bg": hover,
            "sidenav_divider": divider,
            "sidenav_muted": muted,
            "sidenav_icon_muted": icon_muted,
            "sidenav_card_bg": card_bg,
        },
        "tenant_version": tenant.version or "",
        "tenant_name": tenant.name or "",
        "tenant_logo_url": logo_url,
    }
