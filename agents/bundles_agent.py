from cpq.models import Product, Option
from django.db.models import Q
import openai
from dotenv import load_dotenv
import json
import html
import os
import logging
from .utils.quote_agent.db_helpers import log_action_usage
from .utils.message_formatters import SUCCESS_ICON

# FROM QUOTE ANGENT

from .utils.quote_agent.general_helpers import get_active_quote

#LLM Helpers
from .utils.bundles_agent.llm_helpers import extract_bundle_components, extract_delete_options_from_quote, extract_option_updates

# Record Helpers
from .utils.bundles_agent.record_helpers import handle_bundle_components, handle_delete_options_from_quote, handle_option_updates


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"


def _user_is_admin(user) -> bool:
    """Return True when the user can modify bundle structures."""
    try:
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    except Exception:
        return False


def bundles_agent(user, action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "AddProductToBundle": create_bundle_components, # For the future, modify this function name to create_bundle_option
        "UpdateBundleOption": update_bundle_option,
        "DeleteBundleOption": delete_bundle_option,
        #"UpdateBundleComponentInQuote": update_bundle_component_in_quote,
        "DeleteBundleComponentFromQuote": delete_bundle_option_from_quote,
        "ShowBundleStructure": show_bundle_structure,
        # "UpdateBundle": generate_quote_pdf,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request. From Bundles Agent"}



def create_bundle_components(user, user_message, session_data): #Using Option model
    """Handle bundle components."""
    logging.info("🔄 Creating bundle components...")

    if not _user_is_admin(user):
        return {
            "message": "🔒 Only admins can edit bundle structures. You can still view them with 'Show bundle structure <SKU>'."
        }

    extracted_components = extract_bundle_components(user_message)

    if not extracted_components or not isinstance(extracted_components, list):
        return {
            "message": "⚠️ Could not parse the bundle structure. Please include a bundle SKU, name, and a list of components with fields like product SKU, quantity, and required status."
        }

    components_created = []
    response_message = ""

    response_message, components_created = handle_bundle_components(extracted_components, response_message)

    if components_created:
        return {
            "message": response_message
        }
    else:
        return {
            "message": f"⚠️ Error: Something went wrong — no product(s) was added to the bundle. Please try again or verify your input.<br><br>{response_message}"
        }

def delete_bundle_option_from_quote(user, user_message, session_data):
    """Delete Bundle Option From Quote."""
    logging.info("🔄 Deleting bundle components...")

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote

    extracted_delete_options =  extract_delete_options_from_quote(user_message)

    if not extracted_delete_options or not isinstance(extracted_delete_options, list):
        return {
            "message": "⚠️ Failed to extract bundle options correctly. Please try again."
        }


def _extract_bundle_identifier(user_message: str) -> str:
    """
    Simple extractor that prefers SKU-like tokens (letters/numbers/hyphens),
    otherwise returns the raw message trimmed.
    """
    if not user_message:
        return ""
    tokens = [t.strip(",.") for t in user_message.split() if "-" in t or t.isupper()]
    if tokens:
        return tokens[0]
    return user_message.strip()

def _extract_delete_option_request(user_message: str):
    """Extract parent (bundle) and child (option) identifiers from a delete request."""
    if not user_message:
        return None

    import re
    match = re.search(
        r"delete\s+(?:product\s+)?option\s+([A-Za-z0-9\-\_\s]+?)\s+from\s+bundle\s+([A-Za-z0-9\-\_\s]+)",
        user_message,
        re.IGNORECASE,
    )
    if match:
        return {"child": match.group(1).strip(), "parent": match.group(2).strip()}

    tokens = [t.strip(",.") for t in user_message.split() if "-" in t or t.isupper()]
    if len(tokens) >= 2:
        return {"child": tokens[0], "parent": tokens[1]}
    if len(tokens) == 1:
        return {"child": tokens[0], "parent": tokens[0]}
    return None


def show_bundle_structure(user, user_message, session_data):
    """Return the bundle components (options) for a given bundle SKU or name."""
    can_edit = _user_is_admin(user)
    identifier = _extract_bundle_identifier(user_message)
    if not identifier:
        return {"message": "⚠️ Please provide a bundle SKU or name to inspect its structure."}

    try:
        bundle = Product.objects.get(
            Q(is_bundle=True) & (Q(sku__iexact=identifier) | Q(name__iexact=identifier))
        )
    except Product.DoesNotExist:
        return {"message": f"⚠️ No bundle found for '{identifier}'. Please verify the SKU or name."}

    safe_bundle_name = html.escape(bundle.name, quote=True)

    options = (
        Option.objects.filter(parent_product=bundle)
        .select_related("product_option")
        .order_by("group_name", "product_option__name")
    )

    if not options:
        return {"message": f"ℹ️ Bundle <b>{bundle.name} ({bundle.sku})</b> has no components configured."}

    rows = []
    for opt in options:
        child = opt.product_option
        safe_child_name = html.escape(child.name, quote=True)
        safe_group = html.escape(opt.group_name or "", quote=True)
        rows.append(
            f"<tr class='bundle-option-row' "
            f"data-option-id='{opt.id}' "
            f"data-product-sku='{child.sku}' "
            f"data-product-name=\"{safe_child_name}\">"
            f"<td data-field='name' data-value=\"{safe_child_name}\">{safe_child_name}</td>"
            f"<td data-field='sku' data-value='{child.sku}'>{child.sku}</td>"
            f"<td data-field='quantity' data-type='number' data-value='{opt.quantity}' style='text-align:center;padding:8px 10px;'>{opt.quantity}</td>"
            f"<td data-field='required' data-type='boolean' data-value='{str(opt.is_required).lower()}' style='text-align:center;padding:8px 10px;'>{'Yes' if opt.is_required else 'No'}</td>"
            f"<td data-field='default' data-type='boolean' data-value='{str(opt.default_selected).lower()}' style='text-align:center;padding:8px 10px;'>{'Yes' if opt.default_selected else 'No'}</td>"
            f"<td data-field='min' data-type='number' data-value='{opt.min_quantity}' style='text-align:center;padding:8px 10px;'>{opt.min_quantity}</td>"
            f"<td data-field='max' data-type='number' data-value='{opt.max_quantity}' style='text-align:center;padding:8px 10px;'>{opt.max_quantity}</td>"
            f"<td data-field='group' data-type='text' data-value=\"{safe_group}\">{safe_group}</td>"
            f"</tr>"
        )

    note_html = ""
    if not can_edit:
        note_html = (
            "  <div class=\"single-record-actions-footer\">"
            "    <span class=\"single-record-readonly-note\">Admin access is required to edit this bundle structure.</span>"
            "  </div>"
        )

    header_actions = ""
    if can_edit:
        header_actions = (
            "  <div class=\"single-record-header-meta bundle-card-actions\">"
            "    <button type=\"button\" class=\"bundle-edit-btn\" data-role=\"bundle-edit-toggle\" aria-label=\"Edit bundle options\" title=\"Edit bundle options\">"
            "      <span class=\"material-icons\" aria-hidden=\"true\">edit</span>"
            "    </button>"
            "  </div>"
        )

    table = (
        f"<div class=\"single-record-card bundle-structure-card\" data-editable=\"{'true' if can_edit else 'false'}\" data-bundle-sku=\"{bundle.sku}\" data-bundle-name=\"{safe_bundle_name}\">"
        "<div class=\"single-record-header\">"
        "  <div class=\"single-record-header-text\">"
        "    <div class=\"single-record-subtitle\" style=\"display:flex;align-items:center;gap:6px;\">"
        "      <span class=\"material-icons\" aria-hidden=\"true\">category</span>"
        "      Bundle"
        "    </div>"
        f"    <div class=\"single-record-title\" style=\"font-size:1.7rem;color:#fc6a3e;\">{safe_bundle_name}</div>"
        f"    <div class=\"single-record-label\">{bundle.sku}</div>"
        "  </div>"
        + header_actions +
        "</div>"
        "<div class=\"single-record-body\">"
        "  <div class=\"single-record-section\">"
        "    <div class=\"single-record-section-title\">Options</div>"
        "    <div class=\"single-record-grid\" style=\"grid-template-columns: 1fr;\">"
        "      <table style='width:100%;border-collapse:collapse;'>"
        "      <thead><tr>"
        "        <th style='text-align:left;border-bottom:1px solid #ddd;padding:10px;'>Name</th>"
        "        <th style='text-align:left;border-bottom:1px solid #ddd;padding:10px;'>SKU</th>"
        "        <th style='text-align:center;border-bottom:1px solid #ddd;padding:10px;'>Qty</th>"
        "        <th style='text-align:center;border-bottom:1px solid #ddd;padding:10px;'>Required</th>"
        "        <th style='text-align:center;border-bottom:1px solid #ddd;padding:10px;'>Default</th>"
        "        <th style='text-align:center;border-bottom:1px solid #ddd;padding:10px;'>Min</th>"
        "        <th style='text-align:center;border-bottom:1px solid #ddd;padding:10px;'>Max</th>"
        "        <th style='text-align:left;border-bottom:1px solid #ddd;padding:10px;'>Group</th>"
        "      </tr></thead>"
        "      <tbody>"
        + "".join(rows) +
        "      </tbody></table>"
        "    </div>"
        "  </div>"
        "  <div class=\"single-record-feedback\" data-role=\"bundle-feedback\" aria-live=\"polite\"></div>"
        + note_html +
        "</div>"
        "</div>"
    )

    return {"message": table}
    options_deleted = []
    response_message = ""

    response_message, options_deleted = handle_delete_options_from_quote(extracted_delete_options, response_message, quote)

    if options_deleted:
        return {
            "message": response_message
        }
    else:
        return {
            "message": f"⚠️ Error: Something went wrong — no bundle component(s) quote line was deleted from the quote. Please try again or verify your input.<br><br>{response_message}"
        }

def update_bundle_option(user, user_message, session_data):
    """Updatins Bundle Option"""
    logging.info("🔄 Updating bundle option...")

    if not _user_is_admin(user):
        return {
            "message": "🔒 Only admins can edit bundle structures. Please ask an admin to make this change."
        }

    extracted_option_updates = None
    is_ui_request = False

    if user_message.startswith("Update Bundle Option:"):
        try:
            payload_str = user_message.replace("Update Bundle Option:", "", 1).strip()
            payload = json.loads(payload_str)
            if isinstance(payload, dict):
                extracted_option_updates = payload.get("updates") if isinstance(payload.get("updates"), list) else None
            elif isinstance(payload, list):
                extracted_option_updates = payload
            is_ui_request = True
        except json.JSONDecodeError:
            logging.warning("⚠️ Invalid JSON payload for bundle option update; falling back to LLM extraction.")

    if extracted_option_updates is None:
        extracted_option_updates = extract_option_updates(user_message)

    if not extracted_option_updates:

        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }

    response_message = ""

    # ✅ Handle updates option
    response_message, updated_options = handle_option_updates(extracted_option_updates, response_message)

    # ✅ Return
    if not updated_options:
        if is_ui_request:
            return {"message": "No changes to save.", "temporaryMessage": True, "hiddenMessage": True}
        return {
            "message": f"No options were updated. <br><br>{response_message}",
            "temporaryMessage": True
        }

    if is_ui_request:
        return {
            "message": "Saved.",
            "temporaryMessage": True,
            "hiddenMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
    }


def delete_bundle_option(user, user_message, session_data):
    """Remove a child option from a bundle."""
    logging.info("🗑️ Deleting bundle option...")

    if not _user_is_admin(user):
        return {
            "message": "🔒 Only admins can edit bundle structures. Please ask an admin to delete this option."
        }

    parsed = _extract_delete_option_request(user_message)
    if not parsed or not parsed.get("child") or not parsed.get("parent"):
        return {
            "message": "⚠️ Please specify the option SKU/name and the bundle SKU/name. Example: Delete product option SYM-CHILD from bundle SYM-BUNDLE."
        }

    parent_identifier = parsed["parent"]
    child_identifier = parsed["child"]

    try:
        bundle = Product.objects.get(
            Q(is_bundle=True) & (Q(sku__iexact=parent_identifier) | Q(name__iexact=parent_identifier))
        )
    except Product.DoesNotExist:
        return {"message": f"⚠️ Bundle '{parent_identifier}' was not found or is not marked as a bundle."}

    try:
        child = Product.objects.get(
            Q(is_bundle=False) & (Q(sku__iexact=child_identifier) | Q(name__iexact=child_identifier))
        )
    except Product.DoesNotExist:
        return {"message": f"⚠️ Option '{child_identifier}' was not found as a standalone product."}

    try:
        option = Option.objects.get(parent_product=bundle, product_option=child)
    except Option.DoesNotExist:
        return {"message": f"⚠️ {child.name} ({child.sku}) is not currently an option in {bundle.name}."}

    option.delete()
    return {
        "message": f"{SUCCESS_ICON} Removed <b>{child.name} ({child.sku})</b> from bundle <b>{bundle.name} ({bundle.sku})</b>."
    }
