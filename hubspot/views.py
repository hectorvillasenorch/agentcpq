import os
import logging
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseRedirect
from urllib.parse import urlencode
from dotenv import load_dotenv
from hubspot.models import HubspotToken
from django.utils.timezone import now, timedelta
import requests
from django.views.decorators.csrf import csrf_exempt
from cpq.models import Opportunity, Account, Product, SystemFieldMapping, Quote
from django.utils import timezone
from decimal import Decimal
import re
import datetime
from math import ceil
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


logger = logging.getLogger(__name__)

# --- Recurring term mapping helpers ---
FREQ_MAP = {
    "month": "monthly", "monthly": "monthly", "m": "monthly",
    "quarter": "quarterly", "quarterly": "quarterly", "q": "quarterly",
    "year": "annually", "annual": "annually", "annually": "annually", "y": "annually",
    "week": "weekly", "weekly": "weekly", "w": "weekly",
    "day": "daily", "daily": "daily", "d": "daily",
}
ALLOWED_FREQ = {"monthly", "quarterly", "annually", "weekly", "daily"}
ONE_TIME_SENTINELS = {"one-time", "one time", "onetime", "single", "once", "none", "no", "n/a", "na"}
MONTHS_PER_PERIOD = {"monthly": 1, "quarterly": 3, "annually": 12, "weekly": None, "daily": None}

def normalize_frequency(val):
    if not val:
        return None
    s = str(val).strip().lower()
    return FREQ_MAP.get(s, s)

def derive_terms_from_months(term_months, freq):
    mpp = MONTHS_PER_PERIOD.get(freq)
    if not mpp or term_months is None:
        return None
    try:
        return max(1, ceil(int(term_months) / mpp))
    except Exception:
        return None

# --- Helpers: consistently get term/frequency from QuoteLine, falling back to Product ---
def get_term_months_from_line_or_product(line):
    """Return term in months from QuoteLine, falling back to its Product if blank."""
    val = getattr(line, "term", None)
    if val in (None, "", 0, "0") and getattr(line, "product", None) is not None:
        val = getattr(line.product, "term", None)
    return val

def get_billing_frequency_from_line_or_product(line):
    """Return billing_frequency from QuoteLine, falling back to its Product if blank."""
    val = getattr(line, "billing_frequency", None)
    if (val is None or str(val).strip() == "") and getattr(line, "product", None) is not None:
        val = getattr(line.product, "billing_frequency", None)
    return val

load_dotenv()
HUBSPOT_CLIENT_ID = os.getenv("HS_CID")
HUBSPOT_CLIENT_SECRET = os.getenv("HS_SECRET")

def start_hubspot_auth(request):
    """
    Redirects the user to HubSpot's OAuth authorization page.
    Dynamically builds the redirect_uri based on the current environment.
    """
    base_url = "https://app.hubspot.com/oauth/authorize"
    client_id = HUBSPOT_CLIENT_ID
    # scope = "crm.objects.contacts.read crm.objects.deals.read"  # change as needed
    scope = "crm.objects.companies.read crm.objects.companies.read crm.objects.companies.write crm.objects.contacts.read crm.objects.contacts.write crm.objects.deals.read crm.objects.deals.write crm.objects.line_items.read crm.objects.line_items.write crm.schemas.companies.read crm.schemas.companies.write crm.schemas.contacts.read crm.schemas.contacts.write crm.schemas.deals.read crm.schemas.deals.write crm.schemas.line_items.read crm.objects.products.read crm.objects.products.write"
    state = "agentcpq123"  # optional: use for security / context

    # Dynamically build redirect_uri (e.g. http://localhost:8000/hubspot/oauth/callback/)
    redirect_uri = request.build_absolute_uri('/hubspot/oauth/callback/')

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    auth_url = f"{base_url}?{urlencode(params)}"
    return HttpResponseRedirect(auth_url)

def refresh_hubspot_token(user_id="default"):
    try:
        token_obj = HubspotToken.objects.get(user_id=user_id)
    except HubspotToken.DoesNotExist:
        raise Exception("No token found for user")

    if not token_obj.refresh_token:
        raise Exception("No refresh token available")

    data = {
        "grant_type": "refresh_token",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "refresh_token": token_obj.refresh_token,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post("https://api.hubapi.com/oauth/v1/token", data=data, headers=headers)
    token_data = response.json()

    if "access_token" not in token_data:
        raise Exception(f"Token refresh failed: {token_data}")

    # Save new token values
    token_obj.access_token = token_data["access_token"]
    token_obj.expires_in = token_data.get("expires_in")
    token_obj.expires_at = now() + timedelta(seconds=token_data.get("expires_in", 0))
    token_obj.refresh_token = token_data.get("refresh_token", token_obj.refresh_token)
    token_obj.scope = token_data.get("scope", token_obj.scope)
    token_obj.token_type = token_data.get("token_type", token_obj.token_type)
    token_obj.save()

    return token_obj

def get_valid_hubspot_token(user_id="default"):
    token = HubspotToken.objects.get(user_id=user_id)

    # ✅ Check expiration
    if token.expires_at is None or token.expires_at <= timezone.now():
        print("🔁 Token expired — refreshing...")
        token = refresh_hubspot_token(user_id)

    return token.access_token


def hubspot_callback(request):
    code = request.GET.get("code")
    if not code:
        return JsonResponse({"error": "Missing authorization code"}, status=400)

    token_url = settings.HUBSPOT_TOKEN_URL

    data = {
        "grant_type": "authorization_code",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "redirect_uri": request.build_absolute_uri('/hubspot/oauth/callback/'),
        "code": code,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(token_url, data=data, headers=headers)
    token_data = response.json()

    if "access_token" not in token_data:
        return JsonResponse({"error": "Token exchange failed", "details": token_data}, status=400)

    # Store token in DB
    HubspotToken.objects.update_or_create(
        user_id="default",  # Replace with real user_id if needed
        defaults={
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in"),
            "expires_at": now() + timedelta(seconds=token_data.get("expires_in", 0)),
            "token_type": token_data.get("token_type"),
            "scope": token_data.get("scope"),
        }
    )

    # return JsonResponse({"message": "HubSpot authorization successful"})
    return redirect("cpq:admin_integrations")

def setup_dashboard(request):
    hubspot_connected = False

    try:
        # token = HubspotToken.objects.get(user_id="default")  # or request.user.id
        token = get_valid_hubspot_token("default")
        if token.expires_at and token.expires_at > now():
            # Optional: test token by calling HubSpot API
            headers = {
                "Authorization": f"Bearer {token}"
            }
            res = requests.get("https://api.hubapi.com/integrations/v1/me", headers=headers)
            if res.status_code == 200:
                hubspot_connected = True
    except HubspotToken.DoesNotExist:
        pass

    return render(request, "setup.html", {
        "hubspot_connected": hubspot_connected,
    })

def sync_quote_to_hubspot(quote):
    # token = HubspotToken.objects.get(user_id="default")
    token = get_valid_hubspot_token("default")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    data = {
        "properties": {
            "agentcpq_quote_id": quote.qteid  # ensure this field exists
        }
    }

    url = f"https://api.hubapi.com/crm/v3/objects/deals/{quote.hs_deal_id}"
    res = requests.patch(url, headers=headers, json=data)

    if res.status_code == 200:
        print(f"✅ Synced quote {quote.id} to HubSpot deal {quote.hs_deal_id}")
    else:
        print(f"❌ Sync failed: {res.status_code} — {res.text}")


@csrf_exempt
def get_hubspot_schema(request):

    object_type = request.GET.get("object_type")

    hs_object_map = {
        "Opportunity": "deals",
        "Account": "companies",
        "Contact": "contacts",
        "Product": "products",
        "Quote": "quotes",
        "QuoteLine": "line_items"
    }

    hs_object = hs_object_map.get(object_type)
    if not hs_object:
        return JsonResponse({"error": "Unsupported object"}, status=400)

    try:
        token = HubspotToken.objects.get(user_id="default")
        headers = {"Authorization": f"Bearer {token.access_token}"}
        url = f"https://api.hubapi.com/crm/v3/properties/{hs_object}"

        res = requests.get(url, headers=headers)
        print("HubSpot Response:", res.json())
        props = res.json().get("results", [])

        crm_fields = [p["name"] for p in props if not p.get("hidden")]

        return JsonResponse({"fields": crm_fields})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def get_contacts():
    token = HubspotToken.objects.get(user_id="default")  # adjust if needed

    headers = {
        "Authorization": f"Bearer {token.access_token}"
    }

    response = requests.get(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers=headers
    )

    return response.json()


def sync_hubspot_products(user_id="default", actor_user=None):
    try:
        token = get_valid_hubspot_token(user_id)
    except HubspotToken.DoesNotExist:
        raise Exception("❌ No HubSpot token found for this user.")

    # Get field mappings for Product
    field_mappings = {
        m.crm_field: m.local_field
        for m in SystemFieldMapping.objects.filter(crm="HubSpot", field_type="Product")
    }

    url = "https://api.hubapi.com/crm/v3/objects/products"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {
        "limit": 100,
        "properties": list(field_mappings.keys())
    }

    response = requests.get(url, headers=headers, params=params)
    print("HubSpot Response:", response.json())

    if response.status_code != 200:
        raise Exception(f"❌ Failed to fetch products: {response.status_code} — {response.text}")

    for item in response.json().get("results", []):
        hs_props = item.get("properties", {})
        product_data = {}
        mapped_fields = set()

        for hs_field, local_field in field_mappings.items():
            if hs_field not in hs_props:
                continue

            raw_value = hs_props[hs_field]
            value = raw_value  # default assignment

            # Handle term format like 'P12M'
            if isinstance(raw_value, str) and raw_value.startswith("P") and local_field == "term":
                match = re.search(r'P(\d+)M', raw_value)
                value = int(match.group(1)) if match else None

            # Parse price safely
            elif local_field == "price":
                try:
                    value = Decimal(raw_value)
                except (InvalidOperation, TypeError, ValueError):
                    print(f"⚠️ Failed to parse price: {raw_value} — defaulting to 0.00")
                    value = Decimal("0.00")

            product_data[local_field] = value
            mapped_fields.add(local_field)

        # Ensure subscription fields from HubSpot even if not explicitly mapped
        hs_freq = hs_props.get("recurringbillingfrequency")
        if hs_freq and not product_data.get("billing_frequency"):
            product_data["billing_frequency"] = normalize_frequency(hs_freq)

        hs_period = hs_props.get("hs_recurring_billing_period")
        if hs_period and not product_data.get("term"):
            if isinstance(hs_period, str) and hs_period.startswith("P"):
                match = re.search(r'P(\d+)M', hs_period)
                if match:
                    product_data["term"] = int(match.group(1))

        # Ensure price is present
        if "price" not in mapped_fields:
            print(f"⚠️ Missing price for product {item['id']}. Defaulting to 0.00")
            product_data["price"] = Decimal("0.00")

        # Set is_subscription based on term
        product_data["is_subscription"] = bool(product_data.get("term"))

        # Default consistency: if subscription but missing frequency/term specifics, assume monthly 12
        if product_data.get("is_subscription"):
            if not product_data.get("billing_frequency"):
                product_data["billing_frequency"] = "monthly"
            if not product_data.get("term"):
                product_data["term"] = 12

        if product_data:
            product, _ = Product.objects.update_or_create(
                external_id=item["id"],
                defaults=product_data
            )
            if actor_user and getattr(actor_user, "is_authenticated", False) and not product.created_by_id:
                product.created_by = actor_user
                product.updated_by = actor_user
                product.save(update_fields=["created_by", "updated_by"])

    print("✅ HubSpot product sync complete.")


def sync_opportunity_to_hubspot(opportunity_id, user_id="default"):
    """
    Syncs an AgentCPQ Opportunity to HubSpot: updates or creates a deal,
    then creates associated line items and links them to the deal.
    """
    logger.info("[HS SYNC] Entered sync_opportunity_to_hubspot for opportunity_id=%s user_id=%s", opportunity_id, user_id)
    opportunity = Opportunity.objects.get(id=opportunity_id)
    logger.info("[HS SYNC] Loaded Opportunity id=%s name=%s hs_deal_id=%s", opportunity.id, getattr(opportunity, 'name', None), getattr(opportunity, 'hs_deal_id', None))
    quote = Quote.objects.filter(opportunity=opportunity, hs_primary=True).first()
    logger.info("[HS SYNC] Primary Quote exists? %s", bool(quote))
    print(f"✅ ==========================> Quote {quote} IS THE QUOTE TO SYNC")
    access_token = get_valid_hubspot_token(user_id)
    logger.info("[HS SYNC] Retrieved access token for user_id=%s", user_id)

    # ✅ Field mappings for Opportunity → Deal
    opportunity_field_mappings = {
        m.local_field: m.crm_field
        for m in SystemFieldMapping.objects.filter(crm="HubSpot", field_type="Opportunity")
    }

    deal_properties = {}
    for local_field, crm_field in opportunity_field_mappings.items():
        try:
            value = opportunity
            for attr in local_field.split("."):
                value = getattr(value, attr)

            if isinstance(value, Decimal):
                value = str(value)
            elif isinstance(value, datetime.datetime):
                value = value.isoformat()
            elif hasattr(value, '__dict__'):
                continue  # skip non-serializable objects

            if value is not None:
                deal_properties[crm_field] = value

        except Exception as e:
            print(f"⚠️ Error resolving field '{local_field}': {e}")

    deal_data = {"properties": deal_properties}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # ✅ Create or update the HubSpot Deal
    if opportunity.hs_deal_id:
        url = f"https://api.hubapi.com/crm/v3/objects/deals/{opportunity.hs_deal_id}"
        response = requests.patch(url, headers=headers, json=deal_data)
        action = "updated"
    else:
        url = "https://api.hubapi.com/crm/v3/objects/deals"
        response = requests.post(url, headers=headers, json=deal_data)
        action = "created"

    if response.status_code not in [200, 201]:
        print(f"❌ Failed to sync deal: {response.status_code} — {response.text}")
        return

    hs_deal_id = response.json()["id"]
    opportunity.hs_deal_id = hs_deal_id
    opportunity.save()

    if quote:
        quote.hs_deal_id = hs_deal_id
        quote.synced = True
        quote.last_synced_at = timezone.now()
        quote.save()
        print(f"✅ Quote {quote.qteid} marked as synced to HubSpot")

        # ✅ Field mappings for QuoteLine → Line Item
        quoteline_field_mappings = {
            m.local_field: m.crm_field
            for m in SystemFieldMapping.objects.filter(crm="HubSpot", field_type="QuoteLine")
        }
        delete_existing_line_items(hs_deal_id, headers)
        print(f"✅ DELETING EXISTING LINE ITEMS....")

        for line in quote.quote_lines.all():
            properties = {}

            for local_field, crm_field in quoteline_field_mappings.items():
                try:
                    value = line
                    for attr in local_field.split("."):
                        value = getattr(value, attr)

                    # Do NOT convert term to ISO duration here; we will map to hs_recurring_billing_terms below
                    if isinstance(value, Decimal):
                        value = str(value)
                    elif isinstance(value, datetime.datetime):
                        value = value.isoformat()
                    elif hasattr(value, '__dict__'):
                        continue  # skip non-serializable objects

                    if value is not None:
                        properties[crm_field] = value

                except Exception as e:
                    print(f"⚠️ Error resolving field '{local_field}': {e}")

            # --- Normalize billing frequency & derive terms ---
            freq_raw = properties.get("recurringbillingfrequency") or get_billing_frequency_from_line_or_product(line)
            freq = normalize_frequency(freq_raw) if freq_raw else None

            term_months_source = get_term_months_from_line_or_product(line)
            is_one_time = (
                (freq and str(freq).lower() in ONE_TIME_SENTINELS) or
                (term_months_source in (0, "0", None) and not freq)
            )

            if is_one_time:
                # One-time charges must NOT include recurring fields
                properties.pop("recurringbillingfrequency", None)
                properties.pop("hs_recurring_billing_terms", None)
                properties.pop("hs_recurring_billing_period", None)
            else:
                if not freq and term_months_source:
                    # Default frequency if term is given but no explicit frequency
                    freq = "monthly"
                if freq in ALLOWED_FREQ:
                    properties["recurringbillingfrequency"] = freq
                    if "hs_recurring_billing_terms" not in properties:
                        derived_terms = derive_terms_from_months(term_months_source, freq)
                        if derived_terms is not None:
                            properties["hs_recurring_billing_terms"] = derived_terms
                    # Also set ISO-8601 period (e.g., P12M) expected by HubSpot for the Term property
                    try:
                        term_months_val = term_months_source
                        if term_months_val not in (None, "", 0, "0"):
                            term_int = int(term_months_val)
                            if term_int > 0:
                                properties["hs_recurring_billing_period"] = f"P{term_int}M"
                    except Exception as e:
                        logger.warning(
                            "[HS SYNC] Could not set hs_recurring_billing_period from term=%r: %s",
                            term_months_source, e
                        )
                else:
                    # Invalid or unknown frequency: drop recurring props to avoid HS validation errors
                    properties.pop("recurringbillingfrequency", None)
                    properties.pop("hs_recurring_billing_terms", None)

            # Log what we’re about to send for troubleshooting
            try:
                logger.info(
                    "[HS SYNC] Line %s local(freq=%r, term_months=%r | prod.freq=%r, prod.term=%r) -> final(freq=%r, terms=%r, period=%r)",
                    getattr(line, "id", None), getattr(line, "billing_frequency", None), getattr(line, "term", None),
                    getattr(getattr(line, "product", None), "billing_frequency", None), getattr(getattr(line, "product", None), "term", None),
                    properties.get("recurringbillingfrequency"), properties.get("hs_recurring_billing_terms"), properties.get("hs_recurring_billing_period")
                )
            except Exception:
                logger.exception("[HS SYNC] Failed logging line item term mapping")

            logger.debug(
                "[HS SYNC] Line %s payload subset: %s",
                getattr(line, "id", None),
                {k: properties.get(k) for k in ("name", "price", "quantity", "recurringbillingfrequency", "hs_recurring_billing_terms", "hs_recurring_billing_period")}
            )

            line_item_data = {"properties": properties}
            print(f"✅ line_item_data %%%%%%%%%%%%%%%%%%%%%% {line_item_data}")


            line_item_url = "https://api.hubapi.com/crm/v3/objects/line_items"
            line_item_resp = requests.post(line_item_url, headers=headers, json=line_item_data)



            if line_item_resp.status_code in [200, 201]:
                line_item_id = line_item_resp.json()["id"]
                print(f"✅ Line item created: {line_item_id}")

                assoc_url = f"https://api.hubapi.com/crm/v3/objects/deals/{hs_deal_id}/associations/line_items/{line_item_id}/deal_to_line_item"
                assoc_resp = requests.put(assoc_url, headers=headers)

                if assoc_resp.status_code in [200, 201, 204]:
                    print(f"🔗 Linked line item {line_item_id} to deal {hs_deal_id}")
                else:
                    print(f"❌ Failed to link line item: {assoc_resp.status_code} — {assoc_resp.text}")
            else:
                print(f"❌ Failed to create line item: {line_item_resp.status_code} — {line_item_resp.text}")

    print(f"✅ Successfully {action} HubSpot deal {hs_deal_id} for opportunity {opportunity.id}")

    # 💵 Update HubSpot deal amount from Quote.net_amount only
    try:
        deal_amount = getattr(quote, 'net_amount', None)
        if deal_amount is not None:
            amount_payload = {"properties": {"amount": str(deal_amount)}}
            amount_url = f"https://api.hubapi.com/crm/v3/objects/deals/{hs_deal_id}"
            amount_resp = requests.patch(amount_url, headers=headers, json=amount_payload)
            if amount_resp.status_code in (200, 201):
                logger.info("[HS SYNC] Updated deal %s amount to %s", hs_deal_id, deal_amount)
            else:
                logger.error("[HS SYNC] Failed to update deal amount: %s — %s", amount_resp.status_code, amount_resp.text)
        else:
            logger.warning("[HS SYNC] Quote.net_amount is None; skipping deal amount update")
    except Exception as e:
        logger.exception("[HS SYNC] Exception while updating deal amount: %s", e)


def delete_existing_line_items(deal_id, headers):
    # 🔍 Get associated line items
    assoc_url = f"https://api.hubapi.com/crm/v4/objects/deals/{deal_id}/associations/line_items"
    response = requests.get(assoc_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        for assoc in data.get("results", []):
            line_item_id = assoc["toObjectId"]
            delete_url = f"https://api.hubapi.com/crm/v3/objects/line_items/{line_item_id}"
            delete_resp = requests.delete(delete_url, headers=headers)

            if delete_resp.status_code in [200, 204]:
                print(f"🗑️ Deleted line item {line_item_id}")
            else:
                print(f"⚠️ Failed to delete line item {line_item_id}: {delete_resp.status_code} — {delete_resp.text}")
    else:
        print(f"⚠️ Failed to fetch line item associations: {response.status_code} — {response.text}")


# --- Diagnostic/validation helpers ---
def validate_opportunity_sync_prereqs(opportunity_id, user_id="default"):
    """Validate minimal prerequisites before attempting a HubSpot sync.
    Returns (ok: bool, report: dict)
    """
    report = {"opportunity_id": opportunity_id, "checks": {}, "errors": []}
    ok = True
    # Opportunity exists
    try:
        opp = Opportunity.objects.get(id=opportunity_id)
        report["checks"]["opportunity.exists"] = True
    except Opportunity.DoesNotExist:
        ok = False
        report["checks"]["opportunity.exists"] = False
        report["errors"].append("Opportunity not found")
        return ok, report

    # Primary quote exists
    quote = Quote.objects.filter(opportunity=opp, hs_primary=True).first()
    report["checks"]["quote.primary_exists"] = bool(quote)
    if not quote:
        ok = False
        report["errors"].append("Primary (hs_primary=True) Quote not found")
    else:
        report["checks"]["quote.lines_count"] = quote.quote_lines.count()
        if quote.quote_lines.count() == 0:
            ok = False
            report["errors"].append("Primary Quote has no quote lines")

    # HubSpot token present/valid
    try:
        token = get_valid_hubspot_token(user_id)
        report["checks"]["hubspot.token_available"] = bool(token)
    except Exception as e:
        ok = False
        report["checks"]["hubspot.token_available"] = False
        report["errors"].append(f"HubSpot token issue: {e}")

    # Mappings present
    opp_map_ct = SystemFieldMapping.objects.filter(crm="HubSpot", field_type="Opportunity").count()
    ql_map_ct = SystemFieldMapping.objects.filter(crm="HubSpot", field_type="QuoteLine").count()
    prod_map_ct = SystemFieldMapping.objects.filter(crm="HubSpot", field_type="Product").count()
    report["checks"]["mappings.opportunity_count"] = opp_map_ct
    report["checks"]["mappings.quoteline_count"] = ql_map_ct
    report["checks"]["mappings.product_count"] = prod_map_ct
    if opp_map_ct == 0:
        ok = False
        report["errors"].append("No Opportunity field mappings configured for HubSpot")
    if ql_map_ct == 0:
        ok = False
        report["errors"].append("No QuoteLine field mappings configured for HubSpot")

    # Optional: amount or name present on opportunity
    has_name = bool(getattr(opp, 'name', None))
    report["checks"]["opportunity.has_name"] = has_name
    if not has_name:
        ok = False
        report["errors"].append("Opportunity 'name' is required by most HubSpot deals")

    return ok, report


@csrf_exempt
def debug_validate_sync_view(request):
    """Diagnostic endpoint to validate (and optionally run) a HubSpot sync for an opportunity.
    Usage: POST with form data: opportunity_id=ID, user_id=default, run=1 to execute
    """
    if request.method != 'POST':
        return JsonResponse({"error": "POST only"}, status=405)
    opportunity_id = request.POST.get('opportunity_id')
    user_id = request.POST.get('user_id', 'default')
    run_flag = request.POST.get('run') == '1'
    if not opportunity_id:
        return JsonResponse({"error": "Missing opportunity_id"}, status=400)

    ok, report = validate_opportunity_sync_prereqs(opportunity_id, user_id=user_id)
    report["ok"] = ok

    if ok and run_flag:
        try:
            sync_opportunity_to_hubspot(opportunity_id, user_id=user_id)
            report["executed"] = True
        except Exception as e:
            logger.exception("[HS SYNC] Execution failed")
            report["executed"] = False
            report["errors"].append(str(e))
            ok = False
    return JsonResponse(report, status=200 if ok else 400)



def create_hubspot_property(object_type, name, label, data_type, user_id="default"):
    access_token = get_valid_hubspot_token(user_id)

    url = f"https://api.hubapi.com/crm/v3/properties/{object_type}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    body = {
        "name": name,
        "label": label,
        "groupName": "agentcpq",  # Optional: create a group in HubSpot
        "type": "string" if data_type == "string" else "number",
        "fieldType": "text",
    }

    response = requests.post(url, headers=headers, json=body)
    return response.status_code == 201, response.json()

@login_required
@require_POST
def sync_hubspot_products_view(request):
    try:
        user_id = request.POST.get("user_id", "default")
        sync_hubspot_products(user_id=user_id, actor_user=request.user)
        messages.success(request, "✅ HubSpot product sync complete.")
    except Exception as e:
        messages.error(request, f"❌ HubSpot product sync failed: {e}")

    # Redirect back to where the button was (dashboard products view)
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("dashboard")
    return redirect(next_url)
