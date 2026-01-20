import urllib.parse
import requests
from django.http import JsonResponse, HttpResponseRedirect
from django.conf import settings
from salesforce.models import SalesforceToken
from django.shortcuts import redirect
import pkce
import requests
from cpq.models import Quote, QuoteLine
import logging
import datetime
from datetime import timezone as dt_timezone

def salesforce_login(request):
    """Redirect the user to Salesforce OAuth login using PKCE."""

    # ✅ Generate PKCE values
    code_verifier = pkce.generate_code_verifier()
    code_challenge = pkce.get_code_challenge(code_verifier)

    # ✅ Store code_verifier in session for later token exchange
    request.session["code_verifier"] = code_verifier

    params = {
        "response_type": "code",
        "client_id": settings.SALESFORCE_CLIENT_ID,
        "redirect_uri": settings.SALESFORCE_REDIRECT_URI,
        "code_challenge": code_challenge,  # ✅ Add PKCE challenge
        "code_challenge_method": "S256",  # ✅ Specify S256 hashing method
    }
    scopes = (settings.SALESFORCE_OAUTH_SCOPES or "").strip()
    if scopes:
        params["scope"] = scopes

    auth_url = f"{settings.SALESFORCE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

def salesforce_callback(request):
    code = request.GET.get("code")
    if not code:
        return JsonResponse({"error": "Missing authorization code"}, status=400)

    # ✅ Retrieve stored code_verifier from session
    code_verifier = request.session.get("code_verifier")
    if not code_verifier:
        return JsonResponse({"error": "Missing PKCE code verifier"}, status=400)

    # ✅ Exchange the code for tokens
    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.SALESFORCE_CLIENT_ID,
        "redirect_uri": settings.SALESFORCE_REDIRECT_URI,
        "code": code,
        "code_verifier": code_verifier,
    }
    if settings.SALESFORCE_CLIENT_SECRET:
        payload["client_secret"] = settings.SALESFORCE_CLIENT_SECRET

    token_response = requests.post(settings.SALESFORCE_TOKEN_URL, data=payload)
    token_data = token_response.json()
    logging.info(f"🔍 TOKEN SF: {token_data}")

    if "access_token" in token_data:
        # ✅ Parse issued_at
        issued_at_raw = token_data.get("issued_at")
        issued_at = None
        expires_at = None

        if issued_at_raw:
            issued_at_ts = int(issued_at_raw) / 1000
            issued_at = datetime.datetime.fromtimestamp(issued_at_ts, tz=dt_timezone.utc)
            expires_at = issued_at + datetime.timedelta(hours=1)

        # ✅ Save to DB
        SalesforceToken.objects.update_or_create(
            user_id="default",  # adjust if using auth users
            defaults={
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "instance_url": token_data["instance_url"],
                "issued_at_raw": issued_at_raw,
                "issued_at": issued_at,
                "expires_at": expires_at,
            }
        )

        return redirect("cpq:admin_integrations")

    return JsonResponse({
        "error": "Salesforce authentication failed",
        "details": token_data
    }, status=400)

def token_receiver(request):
    """Receives the token as a query parameter and stores it."""
    access_token = request.GET.get("access_token")
    instance_url = request.GET.get("instance_url")
    if not access_token or not instance_url:
        return JsonResponse({"error": "Missing token data"}, status=400)

    # Store the token (for simplicity, using a default user_id)
    SalesforceToken.objects.update_or_create(
        user_id="default",
        defaults={"access_token": access_token, "instance_url": instance_url}
    )
    # Redirect to the dashboard (or setup view)
    return redirect("cpq:admin_integrations")


def test_salesforce_api(request):
    """Calls Salesforce API to fetch basic Account data."""

    # ✅ Get stored Salesforce token
    token_entry = SalesforceToken.objects.first()
    if not token_entry:
        return JsonResponse({"error": "No valid Salesforce authentication found"}, status=401)

    access_token = token_entry.access_token
    instance_url = token_entry.instance_url

    # ✅ Construct the request URL
    url = f"{instance_url}/services/data/v57.0/sobjects/Account/"  # Example: Fetch Account data

    # ✅ Set the authorization headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # ✅ Make the GET request
    response = requests.get(url, headers=headers)

    # ✅ Return the response JSON
    try:
        return JsonResponse(response.json(), safe=False)
    except Exception as e:
        return JsonResponse({"error": "Invalid response from Salesforce", "details": str(e)}, status=500)

# def get_salesforce_token():
#     token = SalesforceToken.objects.first()
#     if not token:
#         return None

#     # Check expiration
#     expires_at = token.issued_at + timedelta(seconds=token.expires_in)
#     if timezone.now() >= expires_at:
#         print("🔄 Access token expired — refreshing...")
#         refreshed = refresh_salesforce_token(token)
#         if refreshed:
#             token = SalesforceToken.objects.first()
#         else:
#             print("❌ Token refresh failed.")
#             return None

#     return token

def sync_quote_to_salesforce(request, quote_id):
    """Syncs a Quote’s value and Line Items to a Salesforce Opportunity."""

    # ✅ Retrieve Salesforce authentication token
    token_entry = SalesforceToken.objects.first()
    if not token_entry:
        return JsonResponse({"error": "Salesforce authentication not found"}, status=401)

    access_token = token_entry.access_token
    instance_url = token_entry.instance_url

    # ✅ Fetch the Quote and related Line Items
    try:
        quote = Quote.objects.get(id=quote_id)
        quote_lines = QuoteLine.objects.filter(quote=quote)
    except Quote.DoesNotExist:
        return JsonResponse({"error": "Quote not found"}, status=404)

    # ✅ Ensure the Quote is linked to a valid Opportunity
    if not quote.opportunity:
        return JsonResponse({"error": "Quote is not linked to an Opportunity"}, status=400)

    opportunity_id = quote.sf_opportunity_id  # Ensure we store the Salesforce ID in AgentCPQ

    # ✅ Step 1: Update Opportunity with Quote Data
    opportunity_update_payload = {
        "Amount": str(quote.net_amount),  # ✅ Update Opportunity value
        "AgentCPQ_Quote__c": f"Synced - {quote.name}",  # ✅ Track synced Quote
        "AgentCPQ_Status__c": "In Sync"
    }

    opportunity_url = f"{instance_url}/services/data/v57.0/sobjects/Opportunity/{opportunity_id}"
    opp_response = requests.patch(opportunity_url, json=opportunity_update_payload, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    })

    if opp_response.status_code >= 400:
        return JsonResponse({"error": "Failed to update Salesforce Opportunity", "details": opp_response.json()}, status=400)

    # ✅ Step 2: Sync Quote Line Items as Opportunity Line Items
    failed_lines = []
    for line in quote_lines:
        line_item_payload = {
            "OpportunityId": opportunity_id,  # ✅ Link to Opportunity
            "PricebookEntryId": line.product.salesforce_pricebook_entry_id,  # ✅ Must be mapped in SF
            "Quantity": line.quantity,
            "UnitPrice": str(line.unit_price),
            "TotalPrice": str(line.total_price),
        }

        line_item_url = f"{instance_url}/services/data/v57.0/sobjects/OpportunityLineItem/"
        line_item_response = requests.post(line_item_url, json=line_item_payload, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })

        if line_item_response.status_code >= 400:
            failed_lines.append(line.id)

    # ✅ Step 3: Return Success Response
    return JsonResponse({
        "message": "Quote synced successfully!",
        "synced_opportunity": opportunity_id,
        "failed_line_items": failed_lines
    })
