import os
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseRedirect
from urllib.parse import urlencode
from dotenv import load_dotenv
from hubspot.models import HubspotToken
from django.utils.timezone import now, timedelta
import requests
from django.views.decorators.csrf import csrf_exempt 
from cpq.models import Opportunity, Account, Product, SystemFieldMapping
from django.utils import timezone
from decimal import Decimal
import re
import datetime

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

    token_url = "https://api.hubapi.com/oauth/v1/token"

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
    return HttpResponseRedirect("/dashboard/?view=setup")

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
        "Authorization": f"Bearer {token.access_token}",
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


def sync_hubspot_products(user_id="default"):
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

        # Ensure price is present
        if "price" not in mapped_fields:
            print(f"⚠️ Missing price for product {item['id']}. Defaulting to 0.00")
            product_data["price"] = Decimal("0.00")

        # Set is_subscription based on term
        product_data["is_subscription"] = bool(product_data.get("term"))

        if product_data:
            Product.objects.update_or_create(
                external_id=item["id"],
                defaults=product_data
            )

    print("✅ HubSpot product sync complete.")


def sync_opportunity_to_hubspot(opportunity_id, user_id="default"):
    opportunity = Opportunity.objects.get(id=opportunity_id)
    access_token = get_valid_hubspot_token(user_id)

    # ✅ Get field mappings from AgentCPQ → HubSpot
    field_mappings = {
        m.local_field: m.crm_field
        for m in SystemFieldMapping.objects.filter(crm="HubSpot", field_type="Opportunity")
    }

    data = {"properties": {}}

    for local_field, crm_field in field_mappings.items():
      value = getattr(opportunity, local_field, None)

      if local_field == "quote" and opportunity.quote:
          value = opportunity.quote.qteid

      if isinstance(value, Decimal):
          value = str(value)
      elif isinstance(value, datetime.datetime):
          value = value.isoformat()

      if value is not None:
          data["properties"][crm_field] = value

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    if opportunity.hs_deal_id:
        # ✅ Update existing HubSpot Deal
        url = f"https://api.hubapi.com/crm/v3/objects/deals/{opportunity.hs_deal_id}"
        response = requests.patch(url, headers=headers, json=data)
        action = "updated"
    else:
        # ✅ Create new HubSpot Deal
        url = "https://api.hubapi.com/crm/v3/objects/deals"
        response = requests.post(url, headers=headers, json=data)
        action = "created"

    if response.status_code in [200, 201]:
        hs_deal_id = response.json()["id"]
        opportunity.hs_deal_id = hs_deal_id
        opportunity.save()
        print(f"✅ Successfully {action} HubSpot deal {hs_deal_id} for opportunity {opportunity.id}")
    else:
        print(f"❌ Failed to sync deal: {response.status_code} — {response.text}")
