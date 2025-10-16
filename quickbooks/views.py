import logging
import secrets
from decimal import Decimal
from typing import Dict, Optional, Tuple

import requests
from urllib.parse import urlencode
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from cpq.models import Account, Product, Quote, Tenant

from .models import QuickbooksToken
from .utils import (
    QuickbooksIntegrationError,
    get_quickbooks_token,
    quickbooks_request,
)


logger = logging.getLogger(__name__)


@login_required
def quickbooks_connect(request):
    client_id = settings.QUICKBOOKS_CLIENT_ID
    redirect_uri = settings.QUICKBOOKS_REDIRECT_URI
    if not client_id or not redirect_uri:
        messages.error(request, "QuickBooks client credentials are not configured.")
        return redirect(f"{reverse('dashboard')}?view=setup")

    state = secrets.token_urlsafe(16)
    request.session["quickbooks_oauth_state"] = state

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting openid profile email",  # minimal + user info
        "redirect_uri": redirect_uri,
        "state": state,
    }

    auth_url = f"{settings.QUICKBOOKS_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)


@login_required
def quickbooks_callback(request):
    error = request.GET.get("error")
    if error:
        messages.error(request, f"QuickBooks authorization failed: {error}")
        return redirect(f"{reverse('dashboard')}?view=setup")

    expected_state = request.session.pop("quickbooks_oauth_state", None)
    state = request.GET.get("state")
    if not expected_state or state != expected_state:
        return HttpResponseBadRequest("Invalid OAuth state. Please retry the QuickBooks connection.")

    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    if not code or not realm_id:
        return HttpResponseBadRequest("Missing authorization code or realmId from QuickBooks callback.")

    token_response = requests.post(
        settings.QUICKBOOKS_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.QUICKBOOKS_REDIRECT_URI,
        },
        auth=(settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=30,
    )

    if token_response.status_code >= 400:
        logger.error("QuickBooks token exchange failed: %s", token_response.text)
        messages.error(request, "Unable to complete QuickBooks authorization. Check server logs for details.")
        return redirect(f"{reverse('dashboard')}?view=setup")

    data = token_response.json()

    expires_in = data.get("expires_in")
    refresh_expires_in = data.get("x_refresh_token_expires_in")

    expires_at = timezone.now() + timedelta(seconds=int(expires_in)) if expires_in else None
    refresh_expires_at = (
        timezone.now() + timedelta(seconds=int(refresh_expires_in))
        if refresh_expires_in
        else None
    )

    QuickbooksToken.objects.update_or_create(
        user_id="default",
        defaults={
            "realm_id": realm_id,
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "token_type": data.get("token_type", "bearer"),
            "expires_at": expires_at,
            "refresh_token_expires_at": refresh_expires_at,
        },
    )

    messages.success(request, "QuickBooks sandbox company connected successfully.")
    return redirect(f"{reverse('dashboard')}?view=setup")


def _auth_from_headers(request) -> Optional[Tenant]:
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return None
    try:
        return Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        return None


def _build_customer_payload(account: Account) -> Dict[str, object]:
    display_name = _customer_display_name(account)
    payload: Dict[str, object] = {
        "DisplayName": display_name,
        "CompanyName": account.name,
    }

    if account.phone:
        payload["PrimaryPhone"] = {"FreeFormNumber": account.phone}

    if account.owner and account.owner.email:
        payload["PrimaryEmailAddr"] = {"Address": account.owner.email}

    mailing_address = {
        key: value
        for key, value in {
            "Line1": account.street,
            "City": account.city,
            "CountrySubDivisionCode": account.state,
            "PostalCode": account.zip_code,
        }.items()
        if value
    }
    if mailing_address:
        payload["BillAddr"] = mailing_address

    return payload


def _customer_display_name(account: Account) -> str:
    name = account.name or "Account"
    return f"{name} ({account.accid})"


def _find_customer_id(token, display_name: str) -> Optional[str]:
    safe_name = display_name.replace("'", "\\'")
    query = f"select Id from Customer where DisplayName = '{safe_name}'"
    response = quickbooks_request(token, "GET", "query", params={"query": query})
    customers = response.get("QueryResponse", {}).get("Customer", [])
    if customers:
        return customers[0].get("Id")
    return None


def _resolve_item_ref(quote_line) -> Dict[str, str]:
    product = quote_line.product
    if product and product.external_id:
        return {"value": str(product.external_id)}

    from django.conf import settings

    fallback = getattr(settings, "QUICKBOOKS_DEFAULT_ITEM_ID", "")
    if fallback:
        return {"value": str(fallback)}

    raise QuickbooksIntegrationError(
        "Product is missing QuickBooks ItemRef (external_id) and QUICKBOOKS_DEFAULT_ITEM_ID is not configured."
    )


def _decimal_to_float(value: Decimal) -> float:
    return float(value or 0)


def _build_invoice_payload(quote: Quote, customer_id: str) -> Dict[str, object]:
    lines = []

    for line in quote.quote_lines.select_related("product").all():
        item_ref = _resolve_item_ref(line)
        description = line.description or (line.product.description if line.product else None) or line.product_name or "Quote Line"

        qty = line.quantity if line.quantity else 1
        qty_decimal = Decimal(qty)
        try:
            effective_unit = (Decimal(str(line.total_price)) / qty_decimal).quantize(Decimal("0.01"))
        except Exception:
            effective_unit = Decimal(str(line.unit_price or 0))

        line_amount = (effective_unit * qty_decimal).quantize(Decimal("0.01"))

        line_payload = {
            "Amount": _decimal_to_float(line_amount),
            "DetailType": "SalesItemLineDetail",
            "Description": description[:4000],
            "SalesItemLineDetail": {
                "Qty": float(qty_decimal),
                "UnitPrice": _decimal_to_float(effective_unit),
                "ItemRef": item_ref,
            },
        }

        lines.append(line_payload)

    if not lines:
        raise QuickbooksIntegrationError("Quote does not have any lines to create a QuickBooks invoice.")

    payload = {
        "TxnDate": timezone.now().date().isoformat(),
        "CustomerRef": {"value": customer_id},
        "Line": lines,
    }

    if quote.notes:
        payload["PrivateNote"] = quote.notes[:4000]

    return payload


def _ensure_customer_in_quickbooks(token, account: Account) -> str:
    if account.quickbooks_customer_id:
        return account.quickbooks_customer_id

    display_name = _customer_display_name(account)
    existing_id = _find_customer_id(token, display_name)
    if existing_id:
        account.quickbooks_customer_id = existing_id
        account.save(update_fields=["quickbooks_customer_id", "updated_at"])
        return existing_id

    customer_payload = _build_customer_payload(account)
    response = quickbooks_request(token, "POST", "customer", payload=customer_payload)

    try:
        customer = response["Customer"]
        customer_id = customer["Id"]
    except KeyError as exc:  # pragma: no cover - defensive
        raise QuickbooksIntegrationError("Unexpected response when creating QuickBooks customer.") from exc

    account.quickbooks_customer_id = customer_id
    account.save(update_fields=["quickbooks_customer_id", "updated_at"])

    return customer_id


def _sync_quote_to_quickbooks(quote: Quote, token=None) -> Tuple[str, Optional[str]]:
    if quote.quickbooks_invoice_id:
        raise QuickbooksIntegrationError("Quote already synced to QuickBooks.")

    if token is None:
        token = get_quickbooks_token()

    with transaction.atomic():
        customer_id = _ensure_customer_in_quickbooks(token, quote.account)
        invoice_payload = _build_invoice_payload(quote, customer_id)

        response = quickbooks_request(token, "POST", "invoice", payload=invoice_payload)
        invoice = response.get("Invoice")
        if not invoice:
            raise QuickbooksIntegrationError("QuickBooks response missing Invoice data.")

        invoice_id = invoice.get("Id")
        doc_number = invoice.get("DocNumber")

        quote.quickbooks_invoice_id = invoice_id
        quote.quickbooks_invoice_number = doc_number
        quote.synced = True
        quote.last_synced_at = timezone.now()
        quote.save(update_fields=[
            "quickbooks_invoice_id",
            "quickbooks_invoice_number",
            "synced",
            "last_synced_at",
            "updated_at",
        ])

    return invoice_id, doc_number


@csrf_exempt
def create_invoice_from_quote(request, quote_id: int):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST is allowed."}, status=405)

    tenant = _auth_from_headers(request)
    if tenant is None:
        return JsonResponse({"error": "Missing or invalid X-API-KEY header."}, status=403)

    try:
        quote = (
            Quote.objects.select_related("account", "opportunity")
            .prefetch_related("quote_lines__product")
            .get(id=quote_id)
        )
    except Quote.DoesNotExist:
        return JsonResponse({"error": "Quote not found."}, status=404)

    account = quote.account
    if account.tenant_id and account.tenant_id != tenant.tenant_id:
        return JsonResponse({"error": "Quote does not belong to the authenticated tenant."}, status=403)

    if quote.quickbooks_invoice_id:
        return JsonResponse(
            {
                "error": "Quote already synced to QuickBooks.",
                "invoiceId": quote.quickbooks_invoice_id,
            },
            status=409,
        )

    try:
        token = get_quickbooks_token()
    except QuickbooksIntegrationError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    try:
        invoice_id, doc_number = _sync_quote_to_quickbooks(quote, token=token)

    except QuickbooksIntegrationError as exc:
        logger.warning("QuickBooks sync failed (API): %s", exc)
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "message": "Quote synced to QuickBooks invoice successfully.",
            "invoiceId": invoice_id,
            "docNumber": doc_number,
        },
        status=201,
    )


@login_required
def create_invoice_from_quote_internal(request, quote_id: int):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST is allowed."}, status=405)

    if not request.user.is_staff:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        quote = (
            Quote.objects.select_related("account", "opportunity")
            .prefetch_related("quote_lines__product")
            .get(id=quote_id)
        )
    except Quote.DoesNotExist:
        return JsonResponse({"error": "Quote not found."}, status=404)

    if quote.quickbooks_invoice_id:
        return JsonResponse(
            {
                "message": "Quote already synced to QuickBooks.",
                "invoiceId": quote.quickbooks_invoice_id,
            },
            status=200,
        )

    try:
        invoice_id, doc_number = _sync_quote_to_quickbooks(quote)
    except QuickbooksIntegrationError as exc:
        logger.warning("QuickBooks sync failed (internal): %s", exc)
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "message": "QuickBooks invoice created successfully.",
            "invoiceId": invoice_id,
            "docNumber": doc_number,
        },
        status=201,
    )


@login_required
def sync_quickbooks_products(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST is allowed.")

    if not request.user.is_staff:
        return HttpResponseForbidden("Permission denied.")

    next_url = request.POST.get("next") or f"{reverse('dashboard')}?view=products"

    try:
        token = get_quickbooks_token()
    except QuickbooksIntegrationError as exc:
        messages.error(request, str(exc))
        return redirect(next_url)

    products = (
        Product.objects.filter(external_id__isnull=True)
        .exclude(sku__isnull=True)
        .exclude(sku="")
    )

    matched = 0
    missing = []

    for product in products:
        query = f"select Id from Item where Sku = '{product.sku}'"
        try:
            response = quickbooks_request(
                token,
                "GET",
                "query",
                params={"query": query},
            )
        except QuickbooksIntegrationError as exc:
            messages.error(request, f"QuickBooks query failed for SKU {product.sku}: {exc}")
            return redirect(next_url)

        items = response.get("QueryResponse", {}).get("Item", [])
        if items:
            item_id = items[0].get("Id")
            if item_id:
                product.external_id = item_id
                product.save(update_fields=["external_id"])
                matched += 1
            else:
                missing.append(product.sku)
        else:
            missing.append(product.sku)

    if matched:
        messages.success(request, f"Mapped {matched} product(s) to QuickBooks Item IDs.")

    if missing:
        messages.warning(request, "No QuickBooks Item found for SKU(s): " + ", ".join(missing))

    if not matched and not missing:
        messages.info(request, "All products already have QuickBooks Item IDs.")

    return redirect(next_url)
