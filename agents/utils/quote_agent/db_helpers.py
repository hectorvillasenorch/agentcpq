import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from cpq.models import Product, Opportunity, Account, QuoteLine,ActionUsage
from django.db.models import Q, Sum


def find_product_and_normalize_variables(sku, name):
    try:
        product = Product.objects.get(Q(sku=sku) | Q(name=sku) | Q(sku=name) | Q(name=name))
    except Product.DoesNotExist:
        return None, sku, name

    return product, product.sku, product.name

def get_or_create_account_and_opportunity(extracted_details, session_data):
    """
    Retrieves or creates an Account and Opportunity based on extracted details and session.
    Returns either:
      - A dict with a 'message' key if user input is incomplete or a pending action is required
      - A tuple (account, opportunity) if both are resolved correctly
    """
    if not extracted_details:
        logging.error("❌ extracted_details is None")
        return None, None
    account_name = extracted_details.get("account", session_data.get("account", "")).strip()
    # opportunity_name = extracted_details.get("opportunity", session_data.get("opportunity", "")).strip()
    opportunity_name = (extracted_details.get("opportunity") or session_data.get("opportunity") or "").strip()

    if not account_name:
        return {
            "message": "🚫 Error: Could not determine the account. Please specify an account name."
        }

    # Search and opportunity with name and account
    opportunity = Opportunity.objects.filter(name=opportunity_name, account__name=account_name).first()

    # If not found, use name by default
    if not opportunity:
        opportunity_name = f"Opportunity {account_name}"

    if session_data.get("pending_action") == "confirm_opportunity":
        session_data["opportunity"] = opportunity_name
        session_data["pending_action"] = "add_product"
        return {
            "message": f"✅ Opportunity {opportunity_name} added. Would you like to add more products now?"
        }

    if not opportunity_name:
        return {
            "message": "📝 Please provide an opportunity name before creating the quote."
        }

    # Create or get Account and Opportunity
    account, _ = Account.objects.get_or_create(name=account_name)
    opportunity, _ = Opportunity.objects.get_or_create(name=opportunity_name, account=account)

    return account, opportunity

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