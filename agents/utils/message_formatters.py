"""Utility helpers for formatting user-facing agent messages."""

from typing import Any, Dict, Iterable, Tuple


AGENT_MONEY_ICON = (
    '<span class="material-icons" '
    'style="font-size:24px;vertical-align:middle;color:#13e485;margin-right:6px;"'
    '>check</span>'
)

SUCCESS_ICON = (
    '<span class="material-icons" '
    'style="font-size:22px;vertical-align:middle;color:#00c000;margin-right:6px;"'
    '>check</span>'
)

INFO_ICON = (
    '<span class="material-icons" '
    'style="font-size:22px;vertical-align:middle;color:#11213b;margin-right:6px;"'
    '>info</span>'
)

ERROR_ICON = (
    '<span class="material-icons" '
    'style="font-size:22px;vertical-align:middle;color:#ef4444;margin-right:6px;"'
    '>close</span>'
)

WARNING_ICON = (
    '<span class="material-icons" '
    'style="font-size:22px;vertical-align:middle;color:#ffd32e;margin-right:6px;"'
    '>warning</span>'
)


def _normalize_quantity(quantity: Any) -> Tuple[Any, str]:
    """Return the numeric quantity (if possible) and its formatted string."""

    try:
        numeric = int(quantity)
    except (TypeError, ValueError):
        return quantity, str(quantity) if quantity is not None else ""

    return numeric, f"{numeric:,}"


def _compose_product_label(product: Dict[str, Any]) -> str:
    """Build a concise label for the product using name and/or SKU."""

    name = product.get("name")
    sku = product.get("sku")

    if name and sku and str(name).strip() != str(sku).strip():
        return f"{name} ({sku})"

    return str(name or sku or "the requested product")


def _format_product_success_line(product: Dict[str, Any]) -> str:
    """Create the success line for a single product addition."""

    if not isinstance(product, dict):
        return ""

    quantity_value, quantity_display = _normalize_quantity(product.get("quantity", 1))
    if not quantity_display:
        quantity_display = "1"

    product_label = _compose_product_label(product)
    verb = "has" if quantity_value == 1 else "have"

    raw_unit = (
        product.get("unit")
        or product.get("unit_label")
        or product.get("unit_type")
        or product.get("units")
    )

    unit_label = str(raw_unit).strip() if raw_unit else ""
    if unit_label:
        if quantity_value != 1 and not unit_label.endswith("s"):
            unit_label = f"{unit_label}s"
    else:
        unit_label = "unit" if quantity_value == 1 else "units"

    return (
        f"{SUCCESS_ICON} {quantity_display} {unit_label} of {product_label} "
        f"{verb} been successfully added to the quote."
    )


def _format_product_failure_line(result_payload: Dict[str, Any]) -> str:
    """Represent a failed product addition attempt."""

    product = result_payload.get("product", {}) if isinstance(result_payload, dict) else {}
    product_label = _compose_product_label(product)
    error = ""

    if isinstance(result_payload, dict):
        error = result_payload.get("error") or result_payload.get("updated_message") or "Request omitted."

    return f"{ERROR_ICON} {product_label}: {error}"


def format_quote_success_message(
    quote_name: str,
    account_name: str,
    opportunity_name: str,
    successful_products: Iterable[Dict[str, Any]],
    net_amount: Any,
) -> str:
    """Return the success portion of the quote message without follow-up text."""

    lines = [
        (
            f"{SUCCESS_ICON} Quote {quote_name} has been created for {account_name} "
            f"under the opportunity '{opportunity_name}'."
        )
    ]

    product_lines = [
        _format_product_success_line(product)
        for product in successful_products or []
    ]

    lines.extend(filter(None, product_lines))

    try:
        amount_value = float(net_amount)
    except (TypeError, ValueError):
        amount_value = 0.0

    lines.append(f"{AGENT_MONEY_ICON} Net amount updated to {amount_value:,.2f}.")

    return "<br>".join(lines)


def format_quote_outcome_message(
    quote_name: str,
    account_name: str,
    opportunity_name: str,
    successful_products: Iterable[Dict[str, Any]],
    failed_results: Iterable[Dict[str, Any]],
    net_amount: Any,
    approval_suffix: str = "",
    include_follow_up: bool = True,
) -> str:
    """Compose the full quote response including successes, failures, and approvals."""

    message = format_quote_success_message(
        quote_name,
        account_name,
        opportunity_name,
        successful_products,
        net_amount,
    )

    failure_lines = [
        _format_product_failure_line(item)
        for item in failed_results or []
        if isinstance(item, dict)
    ]

    if failure_lines:
        message += "<br>" + "<br>".join(filter(None, failure_lines))

    if approval_suffix:
        formatted_suffix = _format_approval_suffix(approval_suffix)
        if formatted_suffix:
            message += f"<br>{formatted_suffix}"

    if include_follow_up:
        message += "<br><br>Would you like to add more products now?"

    return message


def _format_approval_suffix(raw_suffix: str) -> str:
    """Insert icons into approval/status lines."""

    if not raw_suffix:
        return ""

    formatted_lines = []

    for segment in raw_suffix.split("<br>"):
        line = segment.strip()
        if not line:
            continue

        formatted_lines.append(_apply_status_icon(line))

    return "<br>".join(formatted_lines)


def _apply_status_icon(line: str) -> str:
    """Prepend success or info icons when keywords are detected."""

    if not line or line.startswith("<span"):
        return line

    if line.startswith("🔷"):
        line = line[len("🔷"):].lstrip()

    lowered = line.lower()
    for prefix in ("great news!", "good news!", "fantastic news!", "awesome news!", "amazing news!"):
        if lowered.startswith(prefix):
            line = line[len(prefix):].lstrip()
            lowered = line.lower()
            break

    forced_success = False

    if "✅" in line:
        line = line.replace("✅", "").strip()
        forced_success = True

    if line.lower().startswith("the") and "successfully" in line.lower():
        forced_success = True

    if line.startswith("ℹ️"):
        content = line.lstrip("ℹ️ ")
        return f"{INFO_ICON} {content}"

    normalized = line.lower()

    if (
        forced_success
        or ("success" in normalized and "not success" not in normalized and "unsuccess" not in normalized)
        or normalized.startswith("success")
        or any(keyword in normalized for keyword in (
            "successfully updated",
            "successfully created",
            "successfully deleted",
            "successfully removed"
        ))
        or any(keyword in normalized for keyword in ("created", "updated", "deleted", "removed"))
    ):
        return f"{SUCCESS_ICON} {line}"

    if "not successful" in normalized or "failed" in normalized or "could not" in normalized:
        return f"{ERROR_ICON} {line}"

    if (
        "no pending updates" in normalized
        or "no updates are pending" in normalized
        or "no incomplete" in normalized
    ):
        return f"{INFO_ICON} {line}"

    if "status" in normalized:
        return f"{INFO_ICON} {line}"

    if "info" in normalized and not line.startswith(INFO_ICON):
        return f"{INFO_ICON} {line}"

    return line


def format_message_with_standard_icons(message: str) -> str:
    """Apply consistent icons to each line in a multiline agent message."""

    if not message:
        return message

    normalized_message = (
        message.replace("\r\n", "<br>")
        .replace("\n", "<br>")
    )

    segments = normalized_message.split("<br>")
    processed = []

    for segment in segments:
        stripped = segment.strip()
        if not stripped:
            continue

        if stripped.startswith("<p>") and stripped.endswith("</p>"):
            stripped = stripped[3:-4].strip()
            if not stripped:
                continue

        if "🛑" in stripped:
            before, after = stripped.split("🛑", 1)
            if before.strip():
                processed.append(_apply_status_icon(before.strip()))
            if after.strip():
                processed.append(f"{WARNING_ICON} {after.strip()}")
            continue

        lowered = stripped.lower()
        if lowered.startswith("if there are any"):
            continue

        if lowered.startswith("is there anything else"):
            continue

        if (
            lowered.startswith("would you like to adjust")
            or lowered.startswith("would you like to update")
            or lowered.startswith("if you need any further")
            or lowered.startswith("if you need further")
            or lowered.startswith("if you need any other")
        ):
            continue

        applied = _apply_status_icon(stripped)

        if applied == stripped and not stripped.startswith((SUCCESS_ICON, INFO_ICON, ERROR_ICON, WARNING_ICON)):
            applied = f"{SUCCESS_ICON} {stripped}"

        processed.append(applied)

    return "<br>".join(processed)
