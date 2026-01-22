import urllib.parse
from django.http import JsonResponse, HttpResponseRedirect
from django.conf import settings
from salesforce.models import SalesforceToken
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.management import call_command
from io import StringIO
from django.contrib.auth.decorators import login_required
from decimal import Decimal
import pkce
import requests
from cpq.models import Pricebook, PricebookEntry, Quote, QuoteLine, SystemFieldMapping
import logging
import datetime
from datetime import timezone as dt_timezone
from salesforce.utils import fetch_salesforce_object_field_metadata, get_valid_salesforce_token, soql_query_all
from agents.utils.session_context_helpers.session_context_helpers import get_session_context

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
        existing_token = SalesforceToken.objects.filter(user_id="default").first()
        refresh_token = token_data.get("refresh_token") or (existing_token.refresh_token if existing_token else None)

        SalesforceToken.objects.update_or_create(
            user_id="default",  # adjust if using auth users
            defaults={
                "access_token": token_data["access_token"],
                "refresh_token": refresh_token,
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
    token_entry = get_valid_salesforce_token(timeout=6)
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
    token_entry = get_valid_salesforce_token(timeout=6)
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

    opportunity_id = (quote.sf_opportunity_id or "").strip()
    if len(opportunity_id) not in {15, 18}:
        opportunity_id = None

    if not opportunity_id:
        account_sf_id = (quote.account.external_id or "").strip() if quote.account_id else ""
        opp_name = (quote.opportunity.name or "").strip() if quote.opportunity_id else ""
        if account_sf_id and opp_name:
            soql_name = opp_name.replace("'", "\\'")
            soql = (
                "SELECT Id FROM Opportunity "
                f"WHERE AccountId = '{account_sf_id}' AND Name = '{soql_name}' "
                "ORDER BY CreatedDate DESC LIMIT 1"
            )
            records, response = soql_query_all(token_entry, soql, timeout=6)
            if records:
                opportunity_id = records[0].get("Id")
                if opportunity_id:
                    quote.sf_opportunity_id = opportunity_id
                    quote.save(update_fields=["sf_opportunity_id"])

    if not opportunity_id:
        return JsonResponse({
            "error": "Missing Salesforce Opportunity ID for this quote.",
            "details": {
                "sf_opportunity_id": quote.sf_opportunity_id,
                "account_external_id": quote.account.external_id if quote.account_id else None,
            },
        }, status=400)

    # ✅ Step 1: Update Opportunity with Quote Data
    quote_id_value = str(quote.public_id or quote.qteid or quote.name)
    opportunity_update_payload = {
        "Amount": str(quote.net_amount),  # ✅ Update Opportunity value
        "AgentCPQ_Quote_Id__c": quote_id_value,
        "AgentCPQ_NACV__c": str(quote.net_amount),
        "AgentCPQ_ACV__c": str(quote.net_amount),
    }

    opportunity_url = f"{instance_url}/services/data/v57.0/sobjects/Opportunity/{opportunity_id}"
    try:
        opp_response = requests.patch(opportunity_url, json=opportunity_update_payload, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })
    except requests.RequestException as exc:
        return JsonResponse({"error": "Failed to update Salesforce Opportunity", "details": str(exc)}, status=502)

    if opp_response.status_code >= 400:
        try:
            details = opp_response.json()
        except ValueError:
            details = opp_response.text
        return JsonResponse({"error": "Failed to update Salesforce Opportunity", "details": details}, status=400)

    # ✅ Ensure Opportunity has a Pricebook2Id
    pricebook_id = None
    soql = f"SELECT Pricebook2Id FROM Opportunity WHERE Id = '{opportunity_id}'"
    opp_records, opp_response = soql_query_all(token_entry, soql, timeout=6)
    if opp_records is None:
        return JsonResponse(
            {"error": "Failed to fetch Salesforce Opportunity pricebook.", "details": opp_response.text},
            status=400,
        )
    if opp_records:
        pricebook_id = opp_records[0].get("Pricebook2Id")

    if not pricebook_id:
        standard_soql = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
        pb_records, pb_response = soql_query_all(token_entry, standard_soql, timeout=6)
        if pb_records:
            pricebook_id = pb_records[0].get("Id")
            pb_payload = {"Pricebook2Id": pricebook_id}
            try:
                pb_update = requests.patch(
                    opportunity_url,
                    json=pb_payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=6,
                )
            except requests.RequestException as exc:
                return JsonResponse(
                    {"error": "Failed to set Salesforce Opportunity pricebook.", "details": str(exc)},
                    status=502,
                )
            if pb_update.status_code >= 400:
                return JsonResponse(
                    {
                        "error": "Failed to set Salesforce Opportunity pricebook.",
                        "details": pb_update.text,
                    },
                    status=400,
                )

    oli_fields, oli_response = fetch_salesforce_object_field_metadata(
        token_entry,
        "OpportunityLineItem",
        timeout=6,
    )
    if oli_fields is None:
        return JsonResponse(
            {"error": "Failed to fetch OpportunityLineItem fields.", "details": oli_response.text},
            status=400,
        )

    def normalize_field_name(value):
        return "".join(ch.lower() for ch in value if ch.isalnum())

    oli_field_map = {}
    oli_createable = set()
    for field in oli_fields:
        field_name = field.get("name")
        if not field_name:
            continue
        if field.get("createable"):
            oli_createable.add(field_name)
            oli_field_map[normalize_field_name(field_name)] = field_name

    mapping_rows = SystemFieldMapping.objects.filter(crm="Salesforce", field_type="QuoteLine")
    mapping_overrides = {row.local_field: row.crm_field for row in mapping_rows}

    skip_fields = {
        "id",
        "quote",
        "product",
        "parent_quote",
        "parent_line",
        "product_option",
        "created_by",
        "created_at",
        "updated_at",
        "synced_to_crm",
        "public_id",
        "total_price",
    }

    # ✅ Step 2: Sync Quote Line Items as Opportunity Line Items
    failed_lines = []
    for line in quote_lines:
        pricebook_entry = None
        if pricebook_id:
            pricebook_entry = (
                PricebookEntry.objects.filter(
                    product=line.product,
                    pricebook__salesforce_id=pricebook_id,
                    salesforce_id__isnull=False,
                )
                .select_related("pricebook")
                .first()
            )

        if not pricebook_entry and pricebook_id:
            product_external_id = (line.product.external_id or "").strip()
            if not product_external_id:
                failed_lines.append({"line_id": line.id, "reason": "missing_product_external_id"})
                continue
            soql = (
                "SELECT Id, UnitPrice FROM PricebookEntry "
                f"WHERE Pricebook2Id = '{pricebook_id}' AND Product2Id = '{product_external_id}' "
                "AND IsActive = true LIMIT 1"
            )
            pb_records, pb_response = soql_query_all(token_entry, soql, timeout=6)
            if pb_records:
                pb_entry_id = pb_records[0].get("Id")
                unit_price_value = pb_records[0].get("UnitPrice")
                if pb_entry_id:
                    local_pricebook = Pricebook.objects.filter(salesforce_id=pricebook_id).first()
                    if not local_pricebook:
                        local_pricebook = Pricebook.objects.create(
                            name="Salesforce Pricebook",
                            salesforce_id=pricebook_id,
                        )
                    pricebook_entry = PricebookEntry.objects.create(
                        product=line.product,
                        pricebook=local_pricebook,
                        salesforce_id=pb_entry_id,
                        unit_price=unit_price_value or line.unit_price,
                    )
            if not pricebook_entry:
                payload = {
                    "Pricebook2Id": pricebook_id,
                    "Product2Id": product_external_id,
                    "UnitPrice": str(line.unit_price),
                    "IsActive": True,
                }
                try:
                    create_response = requests.post(
                        f"{instance_url}/services/data/v57.0/sobjects/PricebookEntry",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        timeout=6,
                    )
                except requests.RequestException as exc:
                    failed_lines.append({"line_id": line.id, "reason": str(exc)})
                    continue
                if create_response.status_code in {200, 201}:
                    pb_entry_id = create_response.json().get("id")
                    if pb_entry_id:
                        local_pricebook = Pricebook.objects.filter(salesforce_id=pricebook_id).first()
                        if not local_pricebook:
                            local_pricebook = Pricebook.objects.create(
                                name="Salesforce Pricebook",
                                salesforce_id=pricebook_id,
                            )
                        pricebook_entry = PricebookEntry.objects.create(
                            product=line.product,
                            pricebook=local_pricebook,
                            salesforce_id=pb_entry_id,
                            unit_price=line.unit_price,
                        )
                else:
                    failed_lines.append({"line_id": line.id, "reason": create_response.text})
                    continue

        if not pricebook_entry and not pricebook_id:
            pricebook_entry = (
                PricebookEntry.objects.filter(
                    product=line.product,
                    salesforce_id__isnull=False,
                )
                .select_related("pricebook")
                .first()
            )

        if not pricebook_entry:
            failed_lines.append({"line_id": line.id, "reason": "missing_pricebook_entry"})
            continue

        line_item_payload = {
            "OpportunityId": opportunity_id,  # ✅ Link to Opportunity
            "PricebookEntryId": pricebook_entry.salesforce_id,
        }

        if "Quantity" in oli_createable:
            line_item_payload["Quantity"] = line.quantity or 1
        if "UnitPrice" in oli_createable:
            line_item_payload["UnitPrice"] = str(line.unit_price)

        for field in line._meta.fields:
            field_name = field.name
            if field_name in skip_fields or field.is_relation:
                continue
            sf_field = mapping_overrides.get(field_name)
            if not sf_field:
                sf_field = oli_field_map.get(normalize_field_name(field_name))
            if not sf_field or sf_field in line_item_payload:
                continue
            if sf_field not in oli_createable:
                continue
            if sf_field == "TotalPrice" and "UnitPrice" in line_item_payload:
                continue
            value = getattr(line, field_name, None)
            if value is None:
                continue
            if isinstance(value, datetime.datetime):
                value = value.isoformat(timespec="seconds")
            elif isinstance(value, datetime.date):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = str(value)
            line_item_payload[sf_field] = value

        line_item_url = f"{instance_url}/services/data/v57.0/sobjects/OpportunityLineItem/"
        line_item_response = requests.post(line_item_url, json=line_item_payload, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        })

        if line_item_response.status_code >= 400:
            try:
                details = line_item_response.json()
            except ValueError:
                details = line_item_response.text
            failed_lines.append({"line_id": line.id, "reason": details})

    # ✅ Step 3: Return Success Response
    message = "Quote synced successfully!"
    if failed_lines:
        message = f"Quote synced with {len(failed_lines)} line item failures."
    return JsonResponse({
        "message": message,
        "synced_opportunity": opportunity_id,
        "failed_line_items": failed_lines
    })


@require_POST
def sync_salesforce_products_view(request):
    stdout = StringIO()
    try:
        call_command("sync_products", stdout=stdout, stderr=stdout)
        output = stdout.getvalue().strip()
        if output:
            messages.success(request, output)
        else:
            messages.success(request, "Salesforce product sync complete.")
    except Exception as exc:
        messages.error(request, f"Salesforce product sync failed: {exc}")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("dashboard")
    return redirect(next_url)


@login_required
def start_quote_from_salesforce(request):
    sf_opportunity_id = request.GET.get("opportunity_id") or request.GET.get("sf_opportunity_id")
    sf_account_id = request.GET.get("account_id") or request.GET.get("sf_account_id")

    if not sf_opportunity_id and not sf_account_id:
        messages.error(request, "Missing Salesforce Account or Opportunity ID.")
        return redirect("dashboard")

    token = get_valid_salesforce_token(timeout=6)
    if not token:
        messages.error(request, "Salesforce connection missing. Please authenticate first.")
        return redirect("cpq:admin_integrations")

    account_name = None
    opportunity_name = None

    if sf_opportunity_id:
        soql = (
            "SELECT Id, Name, AccountId, Account.Name "
            f"FROM Opportunity WHERE Id = '{sf_opportunity_id}'"
        )
        records, response = soql_query_all(token, soql, timeout=6)
        if records is None or not records:
            messages.error(request, "Salesforce opportunity not found.")
            return redirect("dashboard")
        record = records[0]
        opportunity_name = record.get("Name")
        sf_account_id = record.get("AccountId") or sf_account_id
        account = record.get("Account") or {}
        account_name = account.get("Name")

    if sf_account_id and not account_name:
        soql = (
            "SELECT Id, Name "
            f"FROM Account WHERE Id = '{sf_account_id}'"
        )
        records, response = soql_query_all(token, soql, timeout=6)
        if records is None or not records:
            messages.error(request, "Salesforce account not found.")
            return redirect("dashboard")
        account_name = records[0].get("Name")

    if not account_name:
        messages.error(request, "Could not resolve a Salesforce account name.")
        return redirect("dashboard")

    session_data = request.session.get("session_data", {})
    request.session["sf_launch_context"] = {
        "sf_account_id": sf_account_id,
        "sf_opportunity_id": sf_opportunity_id,
        "account_name": account_name,
        "opportunity_name": opportunity_name,
    }
    current_state, _ = get_session_context("create_quote", session_data)
    if isinstance(current_state, dict):
        data = current_state.setdefault("data", {})
        data["account"] = account_name
        if opportunity_name:
            data["opportunity"] = opportunity_name
    session_data["account"] = account_name
    if opportunity_name:
        session_data["opportunity"] = opportunity_name
    if sf_account_id:
        session_data["sf_account_id"] = sf_account_id
    if sf_opportunity_id:
        session_data["sf_opportunity_id"] = sf_opportunity_id
    request.session["session_data"] = session_data

    if opportunity_name:
        auto_prompt = f"Create a quote for account {account_name} under opportunity {opportunity_name}."
    else:
        auto_prompt = f"Create a quote for account {account_name}."

    return redirect(
        f"{reverse('dashboard')}?view=agents&new_chat=true&sf_launch=1&auto_prompt={urllib.parse.quote(auto_prompt)}"
    )
