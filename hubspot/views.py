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
    scope = "crm.objects.contacts.read crm.objects.deals.read"  # change as needed
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
        token = HubspotToken.objects.get(user_id="default")  # or request.user.id
        if token.expires_at and token.expires_at > now():
            # Optional: test token by calling HubSpot API
            headers = {
                "Authorization": f"Bearer {token.access_token}"
            }
            res = requests.get("https://api.hubapi.com/integrations/v1/me", headers=headers)
            if res.status_code == 200:
                hubspot_connected = True
    except HubspotToken.DoesNotExist:
        pass

    return render(request, "setup.html", {
        "hubspot_connected": hubspot_connected,
    })
# def hubspot_webhook(request):
#     return JsonResponse({"message": "HubSpot webhook received."})


# def start_hubspot_auth(request):
#     base_url = "https://app.hubspot.com/oauth/authorize"
#     client_id = HUBSPOT_CLIENT_ID  

#     redirect_uri = request.build_absolute_uri('/hubspot/oauth/callback/')

#     params = {
#         "client_id": client_id,
#         "redirect_uri": redirect_uri,
#         "scope": "crm.objects.contacts.read crm.objects.deals.read"
#     }

#     auth_url = f"{base_url}?{urlencode(params)}"
#     return HttpResponseRedirect(auth_url)



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


def sync_quote_to_hubspot(quote):
    token = HubspotToken.objects.get(user_id="default")
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


def sync_opportunities_from_hubspot():
    from hubspot.models import HubspotToken
    from cpq.models import Opportunity, Account

    token = HubspotToken.objects.get(user_id="default")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    
    url = "https://api.hubapi.com/crm/v3/objects/deals"
    res = requests.get(url, headers=headers)

    for item in res.json().get("results", []):
        deal_id = item["id"]
        props = item["properties"]
        name = props.get("dealname", f"Deal {deal_id}")
        amount = props.get("amount", "0")
        account_name = props.get("company", "Unknown")

        account, _ = Account.objects.get_or_create(name=account_name)
        Opportunity.objects.update_or_create(
            hs_deal_id=deal_id,
            defaults={
                "name": name,
                "account": account,
                "amount": amount,
            }
        )

@csrf_exempt
def get_hubspot_schema(request):
    object_type = request.GET.get("object_type")

    hs_object_map = {
        "Opportunity": "deals",
        "Account": "companies",
        "Contact": "contacts",
        "Product": "products"
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