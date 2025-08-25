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
from cpq.models import Opportunity, Account, Product, SystemFieldMapping, Quote
from django.utils import timezone
from decimal import Decimal
import re
import datetime
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.shortcuts import redirect

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
    """
    Syncs an AgentCPQ Opportunity to HubSpot: updates or creates a deal,
    then creates associated line items and links them to the deal.
    """
    opportunity = Opportunity.objects.get(id=opportunity_id)
    quote = Quote.objects.filter(opportunity=opportunity, hs_primary=True).first()
    print(f"✅ ==========================> Quote {quote} IS THE QUOTE TO SYNC")
    access_token = get_valid_hubspot_token(user_id)

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

                    if local_field == "term" and value:
                        value = f"P{int(value)}M"

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

@require_POST
def sync_hubspot_products_view(request):
    try:
        user_id = request.POST.get("user_id", "default")
        sync_hubspot_products(user_id=user_id)
        messages.success(request, "✅ HubSpot product sync complete.")
    except Exception as e:
        messages.error(request, f"❌ HubSpot product sync failed: {e}")

    # Redirect back to where the button was (dashboard products view)
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("dashboard")
    return redirect(next_url)