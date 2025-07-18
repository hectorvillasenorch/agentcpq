from django.apps import apps
from django.shortcuts import render, get_object_or_404, redirect
from cpq.models import Product, Quote,QuoteLine, CustomObject, CustomField, CustomFieldValue, CustomRecord,Account, ActionUsage, Tenant, TenantUsageLog, Option
from cpq.views import set_primary_quote
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from cpq.forms import  generate_dynamic_form
from collections import defaultdict
from django.db.models import Prefetch
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.db.models import Count
from django.utils.timezone import now
from django.db.models.functions import TruncMonth
from django.db.models import Prefetch
import hmac
import hashlib
from datetime import date
from django.views.decorators.http import require_GET
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Sum
from cpq.models import Tenant, ActionUsage, TenantUsageReport
from django.utils.dateparse import parse_datetime
import logging
logger = logging.getLogger(__name__)
from datetime import datetime, timezone as dt_timezone

@login_required
def dashboard(request):
    view = request.GET.get("view", "agents")
    object_name = request.GET.get("object_name") 
    session_id = request.GET.get("session_id")
    user = request.user
    accounts = get_user_accounts(user)
    
    custom_object = None
    form = None

    if object_name:
        custom_object = get_object_or_404(CustomObject, name=object_name)
        DynamicForm = generate_dynamic_form(custom_object)
        form = DynamicForm()

    if view == "setup" and not user.is_staff:
        return HttpResponseForbidden("You do not have access to the setup view.")
    
    products = Product.objects.all() if view == "products" else None
    options = Option.objects.all() if view == "products" else None
    bundles = Product.objects.filter(is_bundle=True) 

    if products:
        for product in products:
            product.bundle_options = [opt for opt in options if opt.parent_product == product]

    custom_objects = CustomObject.objects.all()

        # 1) Build the base queryset with all the select_related/prefetchs
    quotes = Quote.objects.select_related("opportunity__account") \
        .prefetch_related(
            Prefetch(
                "quote_lines",
                queryset=QuoteLine.objects.select_related("product"),
                to_attr="lines"
            )
        )

    # 2) If not a superuser, narrow it to only quotes they own
    if not request.user.is_superuser:
        quotes = quotes.filter(owner=request.user)

    # 3) Group as before
    grouped_quotes = defaultdict(list)
    for q in quotes:
        grouped_quotes[q.opportunity].append(q)
    print(f"Grouped Quotes{grouped_quotes}")


    is_authenticated = SalesforceToken.objects.exists()
    is_setup = view == "setup"
    #user = User.objects.get(username="admin") or request.user
    chat_sessions = ChatSession.objects.filter(user=user).order_by("-created_at")

    chat_messages = []
    if session_id:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id, user=user)
            chat_messages = ChatMessage.objects.filter(session=chat_session).order_by("timestamp")
        except ChatSession.DoesNotExist:
            pass

    hubspot_connected = False
    try:
        token = HubspotToken.objects.get(user_id="default")
        if token.expires_at and token.expires_at > now():
            headers = {
                "Authorization": f"Bearer {token.access_token}"
            }
            res = requests.get("https://api.hubapi.com/integrations/v1/me", headers=headers)
            if res.status_code == 200:
                hubspot_connected = True
    except HubspotToken.DoesNotExist:
        pass
    
    records_custom_object, field_values_by_record = get_values_by_record(custom_object)
    lookup_options = get_lookup_data_for_form(custom_object)

    return render(request, "dashboard.html", {
        "products": products,
        "options": options,
        "bundles": bundles,
        "grouped_quotes": grouped_quotes.items(),
        "is_setup": is_setup,
        "is_authenticated": is_authenticated,
        "hubspot_connected": hubspot_connected,
        "chat_sessions": chat_sessions,
        "chat_messages": chat_messages,
        "selected_session_id": session_id,
        "custom_object": custom_object,
        "custom_objects": custom_objects,
        "form": form,
        "accounts": accounts,
        "records_custom_object": records_custom_object,
        'field_values_by_record': field_values_by_record,
        'lookup_options': lookup_options,
})
        

def get_user_accounts(user):
    if user.is_superuser:
        return Account.objects.all()
    return Account.objects.filter(owner=user)

def get_values_by_record(custom_object):
    records_custom_object = CustomRecord.objects.filter(object_type=custom_object).order_by('-created_at')

    field_values_by_record = {}

    for record in records_custom_object:
        values = CustomFieldValue.objects.filter(record=record).select_related("field")
        field_values_by_record[record.record_id] = {
            val.field.label or val.field.name: val.value
            for val in values
        }
    return records_custom_object, field_values_by_record

def get_lookup_data_for_form(custom_object):
    lookup_data = {}
    for field in CustomField.objects.filter(custom_object=custom_object, data_type="lookup"):
        try:
            model = apps.get_model(field.lookup_model)
            # Only grab id and name or string version
            instances = model.objects.all()
            lookup_data[field.name] = [{"id": i.id, "label": str(i)} for i in instances]
        except Exception as e:
            lookup_data[field.name] = []
    return lookup_data



@require_GET
def get_tenant_usage(request):
    # 1) Authentication headers
    api_key   = request.headers.get("X-API-KEY")
    ts_header = request.headers.get("X-Timestamp")
    sig       = request.headers.get("X-Signature")

    if not (api_key and ts_header and sig):
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Missing authentication headers")
        return HttpResponseForbidden("Missing authentication headers")

    # 2) Tenant lookup
    try:
        tenant = Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Invalid API key")
        return HttpResponseForbidden("Invalid API key")

    # 3) Parse & validate the X-Timestamp header
    ts_header = request.headers.get("X-Timestamp")
    if not ts_header:
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Missing timestamp")
        return HttpResponseForbidden("Missing timestamp")

    # Normalize “Z” to “+00:00” and attempt ISO‐8601 parse
    try:
        # e.g. "2025-07-15T19:04:07Z" → "2025-07-15T19:04:07+00:00"
        iso_ts = ts_header.replace("Z", "+00:00")
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Bad timestamp format")
        return HttpResponseForbidden("Bad timestamp format")

    # Ensure it’s timezone‐aware in UTC
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt_timezone.utc)

    # Reject if older than 5 minutes
    if abs((timezone.now() - ts).total_seconds()) > 300:
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Stale timestamp")
        return HttpResponseForbidden("Stale timestamp")
    # Ensure it's timezone-aware in UTC
    if timezone.is_naive(ts):
        ts = timezone.make_aware(ts, timezone.utc)

    # Reject if older than 5 minutes
    if abs((timezone.now() - ts).total_seconds()) > 300:
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=403,message="Stale timestamp")
        return HttpResponseForbidden("Stale timestamp")

    # 4) Build the string to sign
    path = request.get_full_path()                # e.g. "/api/usage/?start=…&end=…"
    ts_header = request.headers.get("X-Timestamp")
    # NOTE: request.body.decode() is "" for GET
    raw = f"{request.method}{path}{request.body.decode()}{ts_header}"
    message = raw.encode()

    # 5) Log both sides
    logger.debug("📫 Django sees path+query: %s", path)
    logger.debug("📝 Raw message string: %r", raw)
    expected = hmac.new(tenant.api_secret.encode(), message, hashlib.sha256).hexdigest()
    logger.debug("✅ Expected signature: %s", expected)
    logger.debug("🔑 Incoming X-Signature header: %s", request.headers.get("X-Signature"))

    # 5) Parse billing window
    start_str = request.GET.get("start")
    end_str   = request.GET.get("end")
    if not (start_str and end_str):
        TenantUsageLog.objects.create(tenant_id=tenant.tenant_id,billing_period=start,status="failure",http_status=400,message="start and end parameters required")
        return HttpResponseBadRequest("start and end parameters required")
    try:
        start = timezone.datetime.fromisoformat(start_str).date()
        end   = timezone.datetime.fromisoformat(end_str).date()
    except Exception:
        TenantUsageLog.objects.create(
            tenant_id=tenant.tenant_id,
            billing_period=start,
            status="failure",
            http_status=400,
            message="Invalid date format for start/end"
        )
        return HttpResponseBadRequest("Invalid date format for start/end")
    
        

    # 6) Aggregate usage
    total_actions = (
        ActionUsage.objects
        .filter(timestamp__date__gte=start, timestamp__date__lte=end)
        .aggregate(total=Count("id"))["total"]
        or 0
    )
    overflow = max(0, total_actions - (tenant.actions_limit or 0))

    # 7) Upsert the usage report
    billing_period = start.replace(day=1)
    TenantUsageReport.objects.update_or_create(
        tenant=tenant,
        tenant_long_id=tenant.tenant_id,
        billing_period=billing_period,
        defaults={
            "total_actions":    total_actions,
            "overflow_actions": overflow,
        }
    )
    # After each request
    TenantUsageLog.objects.create(
        tenant_id=tenant.tenant_id,
        billing_period=start,
        status="success",
        http_status=200,
        message="Fetched successfully"
    )
    # 8) Return JSON
    return JsonResponse({
        "tenant_id":        tenant.tenant_id,
        "billing_period":   billing_period.isoformat(),
        "total_actions":    total_actions,
        "overflow_actions": overflow,
    })

