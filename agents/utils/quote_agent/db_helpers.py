import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from cpq.models import Product, Opportunity, Account, QuoteLine, ActionUsage, QuoteUIRender, CustomField, QuoteDocumentSettings
from django.db.models import Q, Sum
from django.db import transaction

from ..orchestrator.context_handle_helpers import save_or_update_conversation_context
from ..message_formatters import INFO_ICON


def _clean_identifier(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def find_product_and_normalize_variables(sku, name):
    """Return a product matching either SKU or name (case-insensitive)."""

    sku_clean = _clean_identifier(sku)
    name_clean = _clean_identifier(name)

    if not sku_clean and not name_clean:
        return None, sku, name

    filters = Q()

    if sku_clean:
        filters |= Q(sku__iexact=sku_clean) | Q(name__iexact=sku_clean)

    if name_clean:
        filters |= Q(sku__iexact=name_clean) | Q(name__iexact=name_clean)

    try:
        product = Product.objects.filter(filters).first()
    except Product.DoesNotExist:  # pragma: no cover - `.first()` will not raise
        product = None

    if not product:
        return None, sku, name

    return product, product.sku, product.name

def get_or_create_account_and_opportunity(user, extracted_details, session_data):
    """
    Retrieves or creates an Account and Opportunity based on extracted details and session.
    Returns either:
      - A dict with a 'message' key if user input is incomplete or a pending action is required
      - A tuple (account, opportunity) if both are resolved correctly
    """

    if not extracted_details:
        logging.error("❌ extracted_details is None")
        return None, None
    # Reuse account/opportunity captured in session state to honor follow-up messages like
    # "Use the current opportunity TESTING 44" that omit the account name.
    create_quote_state = session_data.get("state", {}).get("create_quote", {})
    state_data = create_quote_state.get("data") if isinstance(create_quote_state, dict) else {}

    account_name = (
        extracted_details.get("account")
        or (state_data.get("account") if isinstance(state_data, dict) else None)
        or session_data.get("account")
        or ""
    )
    account_name = account_name.strip()

    opportunity_name = (
        extracted_details.get("opportunity")
        or (state_data.get("opportunity") if isinstance(state_data, dict) else None)
        or session_data.get("opportunity")
        or ""
    ).strip()


    if not account_name:
        return {
            "message": "🚫 Error: Could not determine the account. Please specify an account name."
        }
    
    # Create or get Account and Opportunity
    account_qs = Account.objects.filter(name__iexact=account_name).order_by("id")
    account = account_qs.first()
    if account is None:
        account = Account.objects.create(name=account_name, created_by=user)
    elif not account.created_by:
        account.created_by = user
        account.save(update_fields=["created_by"])

    if not opportunity_name:
        existing_opps = Opportunity.objects.filter(account=account)

        # 🧠 Caso 1: El account ya tiene oportunidades, pero el usuario no indicó ninguna
        if existing_opps.exists():
            opp_names = [opp.name for opp in existing_opps]
            opp_list_html = "<br>".join([f"• {name}" for name in opp_names])

            # 🔢 Buscar el número más alto existente con el patrón Opportunity {account_name}__N
            base_name = f"Opportunity {account_name}"
            max_num = 0
            for name in opp_names:
                if name == base_name:
                    max_num = max(max_num, 1)
                elif name.startswith(base_name + "__"):
                    try:
                        suffix_num = int(name.split("__")[-1])
                        max_num = max(max_num, suffix_num)
                    except ValueError:
                        pass  # Ignorar si no es número

            # Crear el siguiente nombre sugerido
            suggested_opportunity_name = (
                f"{base_name}__{max_num + 1}" if max_num > 0 else f"{base_name}__1"
            )

            opportunity_message = (
                f"{INFO_ICON} An attempt was made to create a quote for the account {account_name}, "
                f"but this account already has existing opportunities:<br>"
                f"{opp_list_html}<br><br>"
                f"Would you like to use one of these opportunities, "
                f"create a new one named <b>{suggested_opportunity_name}</b>, "
                f"or specify a custom opportunity name?"
            )
        
            return account, suggested_opportunity_name, opportunity_message

        # 🧠 Caso 2: El account no tiene oportunidades → crear una por defecto
        else:
            # Nombre base
            base_name = f"Opportunity {account_name}"
            opportunity_name = base_name

            # Si ya existe (por alguna razón) una con ese nombre, se crea con sufijo incremental
            suffix = 1
            while Opportunity.objects.filter(name=opportunity_name).exists():
                opportunity_name = f"{base_name}__{suffix}"
                suffix += 1

            opportunity = Opportunity.objects.create(
                name=opportunity_name,
                account=account,
                created_by=user
            )

            logging.info(f"🆕 Created new opportunity '{opportunity_name}' for account '{account_name}' (no previous opportunities).")

            # Guardar para uso posterior en la creación de la Quote
            session_data["opportunity"] = opportunity_name

            return account, opportunity, None

    opportunity, opp_created = Opportunity.objects.get_or_create(
        name=opportunity_name,
        account=account,
        defaults={'created_by': user}
    )

    if not opp_created and not opportunity.created_by:
        opportunity.created_by = user
        opportunity.save()

    return account, opportunity, None

def update_opportunity_net_amount(opportunity):
    """Recalculate and update the opportunity's total amount from all related quotes."""
    try:
        # ✅ Add all the net_amounts of the quotes associated with the opportunity
        total_amount = opportunity.quotes.aggregate(
            total=Sum('net_amount')
        )['total']

        # ✅ Ensure we round to 2 decimal places
        opportunity.amount = Decimal(total_amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # ✅ Guardar la oportunidad actualizada
        opportunity.save()

        print(f"✅ Updated Opportunity {opportunity.id} Amount: {opportunity.amount}")
    except Exception as e:
        print(f"⚠️ Error updating amount for Opportunity {opportunity.id}: {str(e)}")

def log_action_usage(action, user=None, related_object_type=None, related_object_id=None):
    try:
        ActionUsage.objects.create(
            action=action,
            user=user,
            related_object_type=related_object_type,
            related_object_id=related_object_id
        )
    except Exception as e:
        # Optional: Add your logging here, or raise if critical
        print(f"⚠️ Failed to log ActionUsage: {e}")

def get_or_create_quote_ui_render():

    quote_document_settings = QuoteDocumentSettings.objects.first()

    if quote_document_settings is None:
        return None, None

    quote_render_settings = QuoteUIRender.objects.first()

    if quote_render_settings is None:
        # Obtener los campos por defecto del modelo
        rendered_fields = quote_document_settings.rendered_fields
        omitted_fields = quote_document_settings.omitted_fields

        # Crear un nuevo registro con esos valores
        quote_render_settings = QuoteUIRender.objects.create(
            rendered_fields=rendered_fields,
            omitted_fields=omitted_fields
        )
    else:
        # Already exist: check and update omitted_fields
        rendered_fields = quote_document_settings.rendered_fields
        omitted_fields = quote_document_settings.omitted_fields

        quote_render_settings.rendered_fields = rendered_fields
        quote_render_settings.omitted_fields = omitted_fields
        quote_render_settings.save()

    return quote_render_settings, quote_document_settings
