from django.apps import apps
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from cpq.models import Product, Quote, CustomObject, CustomField, CustomFieldValue, CustomRecord, Account, ActionUsage, Tenant, TenantUsageLog, Option
from cpq.views import set_primary_quote, build_account_quote_hierarchy_for_user
from cpq.permissions import is_partner_user
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from quickbooks.models import QuickbooksToken
from django.contrib.auth.models import Group, User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from cpq.forms import generate_dynamic_form, resolve_lookup_model
from cpq.permissions import apply_partner_access_filter
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.core.cache import cache
from django.db.models import Count, Prefetch, Q, Subquery, OuterRef, FloatField, CharField
from django.utils.timezone import now
from django.db.models.functions import TruncMonth, Cast
import hmac
import hashlib
from datetime import date, timedelta
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Sum
from cpq.cache_utils import get_custom_record_list_version
from cpq.templatetags.custom_filters import format_custom_value
from cpq.models import Tenant, ActionUsage, TenantUsageReport
from django.utils.dateparse import parse_datetime
import logging
import json
import time
import os
logger = logging.getLogger(__name__)
from datetime import datetime, timezone as dt_timezone
from django.contrib.auth.views import PasswordResetView
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
import smtplib
from django.template.loader import render_to_string
import re, string
from .forms import SignupForm
from django.contrib.auth.views import LogoutView
from cpq.permissions import get_custom_object_perms, perms_to_template_dict, user_can_access_custom_object, visible_custom_objects_for_user
from cpq.sidebar import (
    STANDARD_SIDENAV_ITEMS,
    SIDEBAR_STANDARD_COOKIE,
    default_standard_sidebar_keys,
    parse_standard_sidebar_cookie,
)


def _decode_message_content(raw: str) -> str:
    if not raw:
        return ""

    decoded = raw
    if "\\u" in decoded:
        try:
            decoded = decoded.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass

    decoded = decoded.replace("\r\n", "\n")
    if "\n" in decoded:
        decoded = decoded.replace("\n", "<br>")

    return decoded


DEFAULT_CUSTOM_RECORD_LIST_CONFIG = {
    "default_limit": 50,
    "max_limit": 200,
    "ordering": {
        "field": "created_date",
        "direction": "DESC",
        "allowed_fields": ["created_date"],
    },
    "select_fields_only": [],
    "exclude_fields": [],
    "default_required_days": None,
    "allowed_filters": [],
    "cache_ttl_seconds": 120,
    "lazy_loading": {
        "initial_fetch": 25,
        "batch_size": 25,
        "max_batches": 8,
        "scroll_trigger_percent": 75,
        "fetch_on_scroll": True,
    },
    "ui_rendering": {
        "skeleton_rows": 10,
    },
    "async_features": {
        "background_prefetch": True,
        "prefetch_next_page": True,
        "aggregate_load_trigger": "user_idle_1000ms",
    },
    "telemetry": {
        "query_time_ms_threshold": 800,
        "records_returned_threshold": 200,
    },
}

CUSTOM_RECORD_LIST_CONFIGS = {
    "payment__c": {
        "ordering": {
            "field": "created_date",
            "direction": "DESC",
            "allowed_fields": ["created_date", "amount", "status"],
        },
        "default_required_days": 90,
        "select_fields_only": [
            "account_id",
            "amount",
            "status",
            "payment_method",
        ],
        "exclude_fields": [
            "notes",
            "audit_log",
            "attachments",
            "raw_payload",
        ],
        "allowed_filters": ["status", "payment_method", "account_id"],
    },
}

_ORDER_FIELD_ALIASES = {
    "created_date": "created_at",
    "created_at": "created_at",
}

_NON_FIELD_COLUMNS = {"id", "created_date", "created_at"}


def _merge_custom_record_config(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = {**base[key], **value}
        else:
            merged[key] = value
    return merged


def _get_custom_record_list_config(custom_object):
    config = DEFAULT_CUSTOM_RECORD_LIST_CONFIG
    if custom_object and custom_object.name in CUSTOM_RECORD_LIST_CONFIGS:
        config = _merge_custom_record_config(config, CUSTOM_RECORD_LIST_CONFIGS[custom_object.name])
    return config


def _build_field_lookup(fields):
    lookup = {}
    for field in fields:
        if field.name:
            lookup[field.name.lower()] = field
        if field.label:
            lookup[field.label.lower()] = field
    return lookup


def _resolve_custom_list_fields(fields, config):
    if not fields:
        return []
    select_fields = [
        name for name in (config.get("select_fields_only") or [])
        if name and name.lower() not in _NON_FIELD_COLUMNS
    ]
    exclude_fields = {name.lower() for name in (config.get("exclude_fields") or []) if name}

    selected = fields
    if select_fields:
        normalized = []
        for name in select_fields:
            lowered = name.lower()
            normalized.append(lowered)
            if lowered.endswith("_id"):
                normalized.append(lowered[:-3])
        allowed = set(normalized)
        selected = [
            field for field in fields
            if field.name.lower() in allowed or (field.label or "").lower() in allowed
        ]
        if not selected:
            selected = fields
        else:
            order_index = {name.lower(): idx for idx, name in enumerate(select_fields)}
            selected.sort(
                key=lambda field: order_index.get(
                    field.name.lower(),
                    order_index.get((field.label or "").lower(), len(order_index)),
                )
            )

    if exclude_fields:
        selected = [
            field for field in selected
            if field.name.lower() not in exclude_fields
            and (field.label or "").lower() not in exclude_fields
        ]

    return selected


def _normalize_ordering(requested_field, requested_direction, config, field_lookup):
    allowed_fields = config.get("ordering", {}).get("allowed_fields") or []
    default_field = config.get("ordering", {}).get("field") or "created_date"
    default_direction = config.get("ordering", {}).get("direction") or "DESC"

    raw_field = (requested_field or default_field or "").strip().lower()
    raw_direction = (requested_direction or default_direction or "DESC").strip().upper()
    if raw_field not in {name.lower() for name in allowed_fields}:
        raw_field = (default_field or "created_date").strip().lower()

    if raw_direction not in {"ASC", "DESC"}:
        raw_direction = "DESC"

    aliased = _ORDER_FIELD_ALIASES.get(raw_field, raw_field)
    if aliased == "created_at":
        return {"type": "created_at", "direction": raw_direction, "field": None, "field_key": raw_field}

    field_obj = field_lookup.get(raw_field)
    if not field_obj and raw_field.endswith("_id"):
        field_obj = field_lookup.get(raw_field[:-3])
    if not field_obj:
        return {"type": "created_at", "direction": raw_direction, "field": None, "field_key": raw_field}

    return {"type": "custom_field", "direction": raw_direction, "field": field_obj, "field_key": raw_field}


def _apply_custom_record_ordering(queryset, ordering):
    direction = ordering["direction"]
    if ordering["type"] == "created_at":
        order_key = "-created_at" if direction == "DESC" else "created_at"
        tie_breaker = "-id" if direction == "DESC" else "id"
        return queryset.order_by(order_key, tie_breaker)

    field = ordering["field"]
    value_subquery = (
        CustomFieldValue.objects
        .filter(record_id=OuterRef("pk"), field=field)
        .values("value")[:1]
    )
    output_field = FloatField() if (field.data_type or "").lower() in {"number", "currency", "percent"} else CharField()
    queryset = queryset.annotate(order_value=Cast(Subquery(value_subquery), output_field=output_field))
    order_key = "-order_value" if direction == "DESC" else "order_value"
    return queryset.order_by(order_key, "-created_at", "-id")


def _parse_cursor(cursor_text):
    if not cursor_text:
        return None
    try:
        ts_part, id_part = cursor_text.split("|", 1)
    except ValueError:
        return None
    parsed_ts = parse_datetime(ts_part) or None
    if parsed_ts and timezone.is_naive(parsed_ts):
        parsed_ts = timezone.make_aware(parsed_ts, timezone.utc)
    try:
        record_id = int(id_part)
    except (TypeError, ValueError):
        return None
    if not parsed_ts:
        return None
    return parsed_ts, record_id


def _build_cursor(record):
    if not record:
        return None
    return f"{record.created_at.isoformat()}|{record.id}"


def _extract_filter_values(request, allowed_filters):
    filters = {}
    for name in allowed_filters:
        values = request.GET.getlist(name)
        if not values:
            raw = request.GET.get(name)
            if raw:
                values = [v.strip() for v in raw.split(",") if v.strip()]
        if values:
            filters[name] = sorted(values)
    return filters


def _lookup_label_map(field, raw_values, user):
    cleaned = [str(v) for v in raw_values if v not in (None, "", "None")]
    if not cleaned:
        return {}
    ids = []
    for value in cleaned:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}

    model = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)
    if model:
        queryset = model.objects.filter(pk__in=ids)
        if user:
            queryset = apply_partner_access_filter(user, model.__name__, queryset)
        return {str(obj.pk): str(obj) for obj in queryset}

    if field.lookup_model:
        try:
            target_co = CustomObject.objects.get(name=field.lookup_model)
        except CustomObject.DoesNotExist:
            return {}
        queryset = CustomRecord.objects.filter(object_type=target_co, pk__in=ids)
        if user:
            queryset = apply_partner_access_filter(
                user,
                target_co.name,
                queryset,
                custom_object=target_co,
            )
        return {str(obj.pk): str(obj) for obj in queryset}

    return {}


def _format_field_display(raw_value, field, lookup_labels):
    if raw_value in (None, "", "None", "---"):
        return "—"
    if (field.data_type or "").lower() == "lookup":
        label = lookup_labels.get(str(raw_value))
        return label or str(raw_value)
    formatted = format_custom_value(raw_value, field.data_type)
    if formatted in (None, ""):
        return "—"
    return str(formatted)


def _display_user_name(user):
    if not user:
        return ""
    name = user.get_full_name()
    return name or getattr(user, "username", "") or str(user)

@login_required
def dashboard(request):
    if (
        "view" not in request.GET
        and "session_id" not in request.GET
        and "new_chat" not in request.GET
    ):
        return redirect(f"{reverse('dashboard')}?view=agents&new_chat=true")

    view = request.GET.get("view", "agents")
    if view == "setup":
        return redirect("cpq:admin_integrations")
    if view == "agents":
        # The chat is now served by the React SPA — preserve session deep-links.
        spa_url = reverse("agents_spa")
        session_id = request.GET.get("session_id")
        if session_id:
            spa_url = f"{spa_url}?session_id={session_id}"
        return redirect(spa_url)
    object_name = request.GET.get("object_name")
    session_id = request.GET.get("session_id")
    user = request.user
    accounts = get_user_accounts(user)

    custom_object = None
    form = None

    new_chat = request.GET.get("new_chat") == "true"
    if new_chat:
        sf_launch = request.GET.get("sf_launch") == "1"
        sf_context = request.session.get("sf_launch_context") if sf_launch else None
        request.session.pop("session_data", None)
        session_id = None
        if sf_context:
            request.session["session_data"] = {
                "account": sf_context.get("account_name"),
                "opportunity": sf_context.get("opportunity_name"),
                "sf_account_id": sf_context.get("sf_account_id"),
                "sf_opportunity_id": sf_context.get("sf_opportunity_id"),
            }

    custom_object_perms = {"can_view": True, "can_add": True, "can_change": True, "can_delete": True}
    if object_name:
        custom_object = get_object_or_404(CustomObject, name=object_name)
        custom_object_perms = perms_to_template_dict(get_custom_object_perms(user, custom_object))
        if not user_can_access_custom_object(user, custom_object, "view"):
            return HttpResponseForbidden("You do not have permission to view this custom object.")

        DynamicForm = generate_dynamic_form(custom_object)
        form = DynamicForm()

    next_identifier = None
    if custom_object:
        last_record = custom_object.records.order_by('-created_at').first()
        if last_record and last_record.custom_identifier:
            next_identifier = get_next_custom_identifier(last_record.custom_identifier)
        else:
            # Puedes definir un valor por defecto para nuevos objetos sin registros
            label = custom_object.label if hasattr(custom_object, 'label') else custom_object.name
            prefix = label[:3].upper() if len(label) >= 3 else label[:1].upper()
            next_identifier = f"{prefix}-00001"


    products = None
    options = None
    bundles = None

    if view == "products":
        product_queryset = Product.objects.filter(is_active=True)
        product_queryset = apply_partner_access_filter(user, "Product", product_queryset)

        products = list(product_queryset)
        product_ids = [product.id for product in products]

        if product_ids:
            options = list(
                Option.objects.filter(parent_product_id__in=product_ids)
                .select_related("product_option", "parent_product")
            )
        else:
            options = []

        for product in products:
            product.bundle_options = [
                opt for opt in options if opt.parent_product_id == product.id
            ]

        bundles = [product for product in products if product.is_bundle]

    custom_objects = visible_custom_objects_for_user(user)

    # Fetch only this user's account/opportunity/quote hierarchy
    account_groups = get_grouped_user_quotes(user)
    print("📦 Account groups:", account_groups)

    is_authenticated = SalesforceToken.objects.exists()
    #user = User.objects.get(username="admin") or request.user
    chat_sessions = ChatSession.objects.filter(user=user).order_by("-created_at")

    chat_messages = []
    if session_id:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id, user=user)
            chat_messages = list(
                ChatMessage.objects.filter(session=chat_session).order_by("timestamp")
            )
            for message in chat_messages:
                message.rendered_content = mark_safe(_decode_message_content(message.content))
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

    quickbooks_connected = QuickbooksToken.objects.exists()

    tenant = Tenant.safe_first()
    tenant_version = tenant.version if tenant and tenant.version else ""
    standard_keys = tenant.sidebar_standard_objects if tenant else None
    if standard_keys is None or not isinstance(standard_keys, list):
        cookie_keys = parse_standard_sidebar_cookie(
            request.COOKIES.get(SIDEBAR_STANDARD_COOKIE, "")
        )
        standard_keys = cookie_keys or default_standard_sidebar_keys()
    allowed_standard_keys = {item["key"] for item in STANDARD_SIDENAV_ITEMS}
    standard_keys = [key for key in standard_keys if key in allowed_standard_keys]
    standard_nav_items = [
        item for item in STANDARD_SIDENAV_ITEMS if item["key"] in standard_keys
    ]

    records_custom_object = CustomRecord.objects.none()
    field_values_by_record = {}
    lookup_options = {}
    custom_fields = []
    custom_record_list_config_json = ""
    custom_fields_meta_json = ""
    if custom_object:
        list_config = _get_custom_record_list_config(custom_object)
        all_fields = list(CustomField.objects.filter(custom_object=custom_object))
        custom_fields = _resolve_custom_list_fields(all_fields, list_config)
        custom_fields_meta = [
            {
                "id": field.id,
                "name": field.name,
                "label": field.label or field.name,
                "data_type": field.data_type,
            }
            for field in custom_fields
        ]
        custom_record_list_config = {
            "objectName": custom_object.name,
            "apiEndpoint": reverse("dashboard-custom-records"),
            "defaultLimit": list_config["default_limit"],
            "maxLimit": list_config["max_limit"],
            "ordering": list_config["ordering"],
            "lazyLoading": list_config["lazy_loading"],
            "ui": list_config["ui_rendering"],
            "async": list_config.get("async_features", {}),
            "canEdit": custom_object_perms.get("can_change") or custom_object_perms.get("can_delete"),
            "canDelete": custom_object_perms.get("can_delete"),
        }
        custom_record_list_config_json = json.dumps(custom_record_list_config, ensure_ascii=True)
        custom_fields_meta_json = json.dumps(custom_fields_meta, ensure_ascii=True)


    return render(request, "dashboard.html", {
        "products": products,
        "options": options,
        "bundles": bundles,
        "account_groups": account_groups,
        "is_authenticated": is_authenticated,
        "hubspot_connected": hubspot_connected,
        "quickbooks_connected": quickbooks_connected,
        "chat_sessions": chat_sessions,
        "chat_messages": chat_messages,
        "selected_session_id": session_id,
        "custom_object": custom_object,
        "custom_objects": custom_objects,
        "custom_object_perms": custom_object_perms,
        "next_identifier": next_identifier,
        "form": form,
        "accounts": accounts,
        "records_custom_object": records_custom_object,
        'field_values_by_record': field_values_by_record,
        'lookup_options': lookup_options,
        "custom_fields": custom_fields,
        "custom_record_list_config_json": custom_record_list_config_json,
        "custom_fields_meta_json": custom_fields_meta_json,
        'tenant_version': tenant_version,
        "standard_nav_items": standard_nav_items,
        "is_partner_user": is_partner_user(user),
})


@login_required
@csrf_exempt
@require_POST
def update_chat_session_title(request, session_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    new_title = (payload.get("title") or "").strip()
    if not new_title:
        new_title = "Untitled Session"

    chat_session = get_object_or_404(ChatSession, session_id=session_id, user=request.user)
    chat_session.title = new_title[:255]
    chat_session.save(update_fields=["title"])

    return JsonResponse({"title": chat_session.title})


@login_required
@csrf_exempt
@require_POST
def delete_chat_session(request, session_id):
    chat_session = get_object_or_404(ChatSession, session_id=session_id, user=request.user)
    existing_session_data = request.session.get("session_data")
    active_session_id = existing_session_data.get("session_id") if existing_session_data else None

    chat_session.delete()

    if active_session_id == session_id:
        request.session.pop("session_data", None)

    return JsonResponse({
        "success": True,
        "deleted_session_id": session_id,
        "was_active": active_session_id == session_id,
    })

def get_user_accounts(user):
    queryset = Account.objects.all()
    return apply_partner_access_filter(user, "Account", queryset)


@login_required
@require_GET
def custom_records_api(request):
    object_name = request.GET.get("object_name")
    if not object_name:
        return JsonResponse({"error": "object_name is required"}, status=400)

    custom_object = get_object_or_404(CustomObject, name=object_name)
    if not user_can_access_custom_object(request.user, custom_object, "view"):
        return HttpResponseForbidden("You do not have permission to view this custom object.")

    config = _get_custom_record_list_config(custom_object)
    all_fields = list(CustomField.objects.filter(custom_object=custom_object))
    field_lookup = _build_field_lookup(all_fields)
    selected_fields = _resolve_custom_list_fields(all_fields, config)

    remediation_key = f"custom_records_remediation:{request.user.id}:{custom_object.name}"
    remediation = cache.get(remediation_key)
    if remediation and remediation.get("disable_nonessential_columns"):
        if config.get("select_fields_only"):
            selected_fields = _resolve_custom_list_fields(all_fields, config)
        elif selected_fields:
            selected_fields = selected_fields[:6]

    requested_limit = request.GET.get("limit")
    try:
        limit = int(requested_limit) if requested_limit else config["default_limit"]
    except (TypeError, ValueError):
        limit = config["default_limit"]
    limit = max(1, min(limit, config["max_limit"]))
    if remediation and remediation.get("reduce_limit"):
        limit = min(limit, config["lazy_loading"]["initial_fetch"])

    filters = _extract_filter_values(request, config.get("allowed_filters") or [])
    filter_sig = hashlib.md5(json.dumps(filters, sort_keys=True).encode("utf-8")).hexdigest()
    fields_sig = ",".join(str(field.id) for field in selected_fields)

    ordering = _normalize_ordering(
        request.GET.get("order_field"),
        request.GET.get("order_dir"),
        config,
        field_lookup,
    )

    cursor = request.GET.get("cursor") or ""
    offset_param = request.GET.get("offset")
    version = get_custom_record_list_version(request.user.id, custom_object.name)
    cache_key = (
        f"custom_records:{request.user.id}:{custom_object.name}:v{version}"
        f":{limit}:{cursor}:{offset_param}:{ordering['field_key']}:{ordering['direction']}:{filter_sig}:{fields_sig}"
    )

    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    start_time = time.monotonic()
    queryset = CustomRecord.objects.filter(object_type=custom_object).select_related("created_by", "updated_by")

    required_days = config.get("default_required_days")
    if required_days:
        cutoff = timezone.now() - timedelta(days=required_days)
        queryset = queryset.filter(created_at__gte=cutoff)

    queryset = apply_partner_access_filter(
        request.user,
        custom_object.name,
        queryset,
        custom_object=custom_object,
    )

    for field_name, values in filters.items():
        normalized_name = field_name.lower()
        field_obj = field_lookup.get(normalized_name)
        if not field_obj and normalized_name.endswith("_id"):
            field_obj = field_lookup.get(normalized_name[:-3])
        if not field_obj:
            continue
        value_list = [str(val) for val in values if val is not None]
        subquery = CustomFieldValue.objects.filter(
            field=field_obj,
            value__in=value_list,
        ).values("record_id")
        queryset = queryset.filter(id__in=Subquery(subquery))

    queryset = _apply_custom_record_ordering(queryset, ordering)

    cursor_info = _parse_cursor(cursor) if ordering["type"] == "created_at" else None
    if cursor_info:
        cursor_ts, cursor_id = cursor_info
        if ordering["direction"] == "DESC":
            queryset = queryset.filter(
                Q(created_at__lt=cursor_ts) | Q(created_at=cursor_ts, id__lt=cursor_id)
            )
        else:
            queryset = queryset.filter(
                Q(created_at__gt=cursor_ts) | Q(created_at=cursor_ts, id__gt=cursor_id)
            )
    elif offset_param:
        try:
            offset = max(0, int(offset_param))
        except (TypeError, ValueError):
            offset = 0
        if offset:
            queryset = queryset[offset:]

    values_qs = CustomFieldValue.objects.filter(field__in=selected_fields).select_related("field")
    queryset = queryset.prefetch_related(Prefetch("custom_field_values", queryset=values_qs))

    records = list(queryset[: limit + 1])
    has_more = len(records) > limit
    if has_more:
        records = records[:limit]

    lookup_fields = [field for field in selected_fields if (field.data_type or "").lower() == "lookup"]
    lookup_labels = {}
    if lookup_fields:
        values_by_field = {field.id: set() for field in lookup_fields}
        for record in records:
            for value in record.custom_field_values.all():
                if value.field_id in values_by_field and value.value not in (None, ""):
                    values_by_field[value.field_id].add(value.value)
        for field in lookup_fields:
            lookup_labels[field.id] = _lookup_label_map(field, values_by_field[field.id], request.user)

    payload_records = []
    for record in records:
        record_values = {val.field_id: val.value for val in record.custom_field_values.all()}
        field_payload = {
            str(field.id): _format_field_display(
                record_values.get(field.id),
                field,
                lookup_labels.get(field.id, {}),
            )
            for field in selected_fields
        }
        payload_records.append({
            "id": record.id,
            "custom_identifier": record.custom_identifier or "",
            "created_at": record.created_at.isoformat() if record.created_at else "",
            "updated_at": record.updated_at.isoformat() if record.updated_at else "",
            "created_by": _display_user_name(record.created_by),
            "updated_by": _display_user_name(record.updated_by),
            "fields": field_payload,
        })

    next_cursor = _build_cursor(records[-1]) if has_more and ordering["type"] == "created_at" else ""
    query_time_ms = int((time.monotonic() - start_time) * 1000)
    telemetry = {
        "query_time_ms": query_time_ms,
        "records_returned": len(payload_records),
    }

    thresholds = config.get("telemetry", {})
    slow_query = query_time_ms > thresholds.get("query_time_ms_threshold", 800)
    heavy_result = len(payload_records) > thresholds.get("records_returned_threshold", 200)
    remediation_applied = {}
    if slow_query or heavy_result:
        remediation_applied = {
            "reduce_limit": True,
            "disable_nonessential_columns": True,
            "increase_cache_ttl": True,
        }
        cache.set(remediation_key, remediation_applied, config.get("cache_ttl_seconds", 120))
        logger.warning(
            "Custom records slow/large response object=%s query_time_ms=%s records=%s",
            custom_object.name,
            query_time_ms,
            len(payload_records),
        )

    response = {
        "records": payload_records,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "telemetry": telemetry,
        "remediation": remediation_applied,
    }

    cache_ttl = config.get("cache_ttl_seconds", 120)
    if remediation_applied.get("increase_cache_ttl"):
        cache_ttl = max(cache_ttl, 240)
    cache.set(cache_key, response, cache_ttl)

    return JsonResponse(response)

def get_values_by_record(custom_object, user=None):
    if not custom_object:
        return CustomRecord.objects.none(), {}
    records_custom_object = (
        CustomRecord.objects.filter(object_type=custom_object)
        .prefetch_related("custom_field_values__field")
        .order_by('-created_at')
    )
    if user:
        records_custom_object = apply_partner_access_filter(
            user,
            custom_object.name,
            records_custom_object,
            custom_object=custom_object,
        )

    field_values_by_record = {}

    for record in records_custom_object:
        field_values_by_record[record.id] = {
            val.field.id: val.value
            for val in record.custom_field_values.all()
        }

    return records_custom_object, field_values_by_record

def get_lookup_data_for_form(custom_object, user=None):
    lookup_data = {}
    for field in CustomField.objects.filter(custom_object=custom_object, data_type="lookup"):
        try:
            model = apps.get_model(field.lookup_model)
            # Only grab id and name or string version
            instances = model.objects.all()
            if user:
                instances = apply_partner_access_filter(user, model.__name__, instances)
            lookup_data[field.name] = [{"id": i.id, "label": str(i)} for i in instances]
        except Exception as e:
            lookup_data[field.name] = []
    return lookup_data


def get_grouped_user_quotes(user):
    return build_account_quote_hierarchy_for_user(user)

@require_GET
def get_tenant_usage(request):
    api_key   = request.headers.get("X-API-KEY")
    ts_header = request.headers.get("X-Timestamp")
    sig       = request.headers.get("X-Signature")

    # Parse billing window early
    start_str = request.GET.get("start")
    end_str   = request.GET.get("end")
    try:
        start = timezone.datetime.fromisoformat(start_str).date() if start_str else None
        end   = timezone.datetime.fromisoformat(end_str).date() if end_str else None
    except Exception:
        start, end = None, None

    billing_period = start.replace(day=1) if start else None

    if not (api_key and ts_header and sig):
        TenantUsageLog.objects.create(
            tenant_id=None,
            billing_period=billing_period,
            status="failure",
            http_status=403,
            message="Missing authentication headers"
        )
        return HttpResponseForbidden("Missing authentication headers")

    try:
        tenant = Tenant.objects.get(api_key=api_key)
        logger.debug("******** TENANT ********************: %s", tenant.tenant_id)
    except Tenant.DoesNotExist:
        TenantUsageLog.objects.create(
            tenant_id=None,
            billing_period=billing_period,
            status="failure",
            http_status=403,
            message=f"Invalid API key: {api_key}"
        )
        return HttpResponseForbidden("Invalid API key")

    try:
        iso_ts = ts_header.replace("Z", "+00:00")
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt_timezone.utc)
        if timezone.is_naive(ts):
            ts = timezone.make_aware(ts, timezone.utc)
    except ValueError:
        TenantUsageLog.objects.create(
            tenant_id=tenant.tenant_id,
            billing_period=billing_period,
            status="failure",
            http_status=403,
            message="Bad timestamp format"
        )
        return HttpResponseForbidden("Bad timestamp format")

    if abs((timezone.now() - ts).total_seconds()) > 300:
        TenantUsageLog.objects.create(
            tenant_id=tenant.tenant_id,
            billing_period=billing_period,
            status="failure",
            http_status=403,
            message="Stale timestamp"
        )
        return HttpResponseForbidden("Stale timestamp")

    if not (start and end):
        TenantUsageLog.objects.create(
            tenant_id=tenant.tenant_id,
            billing_period=billing_period,
            status="failure",
            http_status=400,
            message="start and end parameters required or invalid format"
        )
        return HttpResponseBadRequest("start and end parameters required")

    # HMAC verification
    path = request.get_full_path()
    raw = f"{request.method}{path}{request.body.decode()}{ts_header}"
    message = raw.encode()
    expected = hmac.new(tenant.api_secret.encode(), message, hashlib.sha256).hexdigest()

    logger.debug("📫 Path+query: %s", path)
    logger.debug("📝 Raw message: %r", raw)
    logger.debug("✅ Expected: %s", expected)
    logger.debug("🔑 Provided: %s", sig)

    # TODO: Optionally check if `sig != expected`

    # 6) Aggregate usage
    total_actions = (
        ActionUsage.objects
        .filter(timestamp__date__gte=start, timestamp__date__lte=end)
        .aggregate(total=Count("id"))["total"]
        or 0
    )
    overflow = max(0, total_actions - (tenant.actions_limit or 0))

    # 7) Upsert
    TenantUsageReport.objects.update_or_create(
        tenant_id=tenant.id,
        tenant_long_id=tenant.tenant_id,
        billing_period=billing_period,
        defaults={
            "total_actions": total_actions,
            "overflow_actions": overflow,
        }
    )

    TenantUsageLog.objects.create(
        tenant_id=tenant.tenant_id,
        billing_period=billing_period,
        status="success",
        http_status=200,
        message="Fetched successfully"
    )

    return JsonResponse({
        "tenant_id":        tenant.tenant_id,
        "billing_period":   billing_period.isoformat(),
        "total_actions":    total_actions,
        "overflow_actions": overflow,
    })


@xframe_options_exempt
def signup(request):
    def _clean(value):
        return (value or "").strip()

    def _valid_email(value):
        return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value or ""))

    values = {
        "firstName": "",
        "lastName": "",
        "companyEmail": "",
        "companyName": "",
    }
    context = {
        "values": values,
        "message": "",
        "message_type": "",
    }

    if request.method == "POST":
        values = {
            "firstName": _clean(request.POST.get("firstName")),
            "lastName": _clean(request.POST.get("lastName")),
            "companyEmail": _clean(request.POST.get("companyEmail")).lower(),
            "companyName": _clean(request.POST.get("companyName")),
        }
        context["values"] = values

        if _clean(request.POST.get("website")):
            context.update(
                {
                    "values": {
                        "firstName": "",
                        "lastName": "",
                        "companyEmail": "",
                        "companyName": "",
                    },
                    "message": "Thanks. We received your information.",
                    "message_type": "success",
                }
            )
            return render(request, "auth/signup.html", context)

        if not values["firstName"] or not values["lastName"] or not values["companyEmail"]:
            context.update(
                {
                    "message": "First name, last name, and company email are required.",
                    "message_type": "error",
                }
            )
            return render(request, "auth/signup.html", context, status=400)

        if not _valid_email(values["companyEmail"]):
            context.update(
                {
                    "message": "Enter a valid company email address.",
                    "message_type": "error",
                }
            )
            return render(request, "auth/signup.html", context, status=400)

        webhook_key = os.getenv("WEBHOOK_KEY")
        webhook_url = os.getenv("WEBHOOK_URL", "https://sympletech.agentcpq.ai/api/v1/leads/")

        if not webhook_key:
            logger.error("Signup request form missing WEBHOOK_KEY")
            context.update(
                {
                    "message": "This request form is not configured yet.",
                    "message_type": "error",
                }
            )
            return render(request, "auth/signup.html", context, status=500)

        payload = {
            "firstName": values["firstName"],
            "lastName": values["lastName"],
            "companyEmail": values["companyEmail"],
            "companyName": values["companyName"] or None,
            "first_name": values["firstName"],
            "last_name": values["lastName"],
            "company_email": values["companyEmail"],
            "company_name": values["companyName"] or None,
            "source": "agentcpq-playground-signup",
            "submitted_at": datetime.now(dt_timezone.utc).isoformat(),
        }

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {webhook_key}",
                    "X-API-Key": webhook_key,
                    "X-Webhook-Key": webhook_key,
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Signup request webhook failed")
            context.update(
                {
                    "message": "The request could not be sent. Please try again.",
                    "message_type": "error",
                }
            )
            return render(request, "auth/signup.html", context, status=502)

        context.update(
            {
                "values": {
                    "firstName": "",
                    "lastName": "",
                    "companyEmail": "",
                    "companyName": "",
                },
                "message": "Thanks. We received your information.",
                "message_type": "success",
            }
        )

    return render(request, "auth/signup.html", context)

class CustomPasswordResetView(PasswordResetView):
    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None):
        # Render and clean subject
        subject = render_to_string(subject_template_name, context).strip()
        subject = subject.replace('\xa0', ' ')  # Remove non-breaking spaces

        # Render and clean plain body
        body = render_to_string(email_template_name, context)
        body = body.replace('\xa0', ' ')

        email_message = EmailMultiAlternatives(
            subject, body, from_email, [to_email]
        )

        # Render and clean HTML version if provided
        if html_email_template_name:
            html_email = render_to_string(html_email_template_name, context)
            html_email = html_email.replace('\xa0', ' ')
            email_message.attach_alternative(html_email, 'text/html')
        email_message.encoding = 'utf-8'
        email_message.send()


def get_next_custom_identifier(last_identifier):
    if not last_identifier:
        return None
    # Extraer prefijo y número
    match = re.match(r"^([A-Z]+)-(\d{5})$", last_identifier)
    if not match:
        return None  # O manejar el error de formato

    prefix = match.group(1)
    number = int(match.group(2))

    next_number = number + 1
    next_number_str = str(next_number).zfill(5)
    
    return f"{prefix}-{next_number_str}"


class CustomLogoutView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        # 🧹 Limpiar datos de sesión personalizados antes de cerrar sesión
        for key in ['last_session_id', 'last_view', 'last_object_name']:
            request.session.pop(key, None)
        return super().dispatch(request, *args, **kwargs)
