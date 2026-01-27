from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.core.files.storage import default_storage
from .sidebar import (
    STANDARD_SIDENAV_ITEMS,
    SIDEBAR_STANDARD_COOKIE,
    default_standard_sidebar_keys,
    parse_standard_sidebar_cookie,
)
from .models import (
    Product,
    SystemFieldMapping,
    Quote,
    QuoteLine,
    CustomField,
    Tenant,
    QuoteDocumentSettings,
    CustomObject,
    BusinessRule,
    RuleCondition,
    CustomRecord,
    CustomFieldValue,
    ActionUsage,
    Option,
    TenantUsageReport,
    Account,
    Opportunity,
    Contract,
    Subscription,
    QuoteDocument,
    QuotePendingAttachment,
    Contact,
    Lead,
    Activity,
    PicklistValue,
    CPQSettings,
)
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.apps import apps
from salesforce.utils import (
    ensure_salesforce_buttons,
    ensure_salesforce_fields,
    fetch_salesforce_object_fields,
    get_salesforce_userinfo,
    get_valid_salesforce_token,
    validate_salesforce_connection,
)
from hubspot.models import HubspotToken
from quickbooks.models import QuickbooksToken
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ObjectDoesNotExist
import json
import importlib.util
from .forms import (
    CPQSettingsForm,
    CustomFieldForm,
    CustomObjectForm,
    EmailAlertForm,
    generate_dynamic_form,
    resolve_lookup_model,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
import logging
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Count, Prefetch, Q, Subquery
from django.utils.timezone import now
from django.utils.text import slugify
from django.db.models.functions import TruncMonth
from datetime import datetime
from django.utils.timezone import make_aware
from django.utils.dateparse import parse_date
from .forms import BusinessRuleForm, get_rule_condition_formset
from .forms import QUOTE_FIELDS, QUOTE_LINE_FIELDS, PRODUCT_FIELDS
from django.utils.safestring import mark_safe
import uuid, os
from django.views.decorators.http import require_POST, require_http_methods
from decimal import Decimal, InvalidOperation
from collections import defaultdict, OrderedDict
from django.contrib.auth.models import User, Group, Permission
from django.conf import settings
from django.utils import timezone
from .models import EmailAlert
from cpq.models import default_rendered_fields_for_quote_document_settings, default_omitted_fields_for_quote_document_settings
from django.utils.html import escape
from django.utils.http import urlencode
from cpq.renewals.renewals import make_opportunity_renewal
from django.core.management import call_command
from salesforce.models import SalesforceToken
from io import StringIO
import boto3
from botocore.config import Config
import stripe
import requests
from django.db import transaction
from cpq.cache_utils import bump_custom_record_list_version
from cpq.permissions import (
    apply_partner_access_filter,
    get_custom_object_perms,
    is_partner_user,
    partner_can_access_record,
    perms_to_template_dict,
    user_can_access_custom_object,
)

# HubSpot sync
from hubspot.views import sync_opportunity_to_hubspot

# Agents General Helpers
from agents.utils.quote_agent.general_helpers import (
    restrict_quote_document_settings_to_line_item_object_types,
    set_custom_fields_into_quote_document_settings,
)
from agents.models import ChatSession, ChatMessage
from agents.utils.analytics_agent.handle_helpers import get_object_metadata
from agents.utils.quote_agent.general_helpers import get_quote_details
from agents.utils.record_agent.handle_helpers import serialize_record
from cpq.field_mapping_utils import CONFIDENCE_THRESHOLD, suggest_field_mappings


@login_required
def manage_users(request):
    if not (request.user.is_superuser or request.user.has_perm("auth.view_user")):
        return HttpResponseForbidden("You do not have permission to view users.")

    can_add = request.user.is_superuser or request.user.has_perm("auth.add_user")
    can_change = request.user.is_superuser or request.user.has_perm("auth.change_user")
    can_assign_access = request.user.is_superuser or request.user.has_perm("auth.change_user")
    can_add_group = request.user.is_superuser or request.user.has_perm("auth.add_group")
    can_change_group = request.user.is_superuser or request.user.has_perm("auth.change_group")
    can_delete_group = request.user.is_superuser or request.user.has_perm("auth.delete_group")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            if not can_add:
                return HttpResponseForbidden("You do not have permission to add users.")

            username = (request.POST.get("username") or "").strip()
            email = (request.POST.get("email") or "").strip()
            password = request.POST.get("password") or ""
            password_confirm = request.POST.get("password_confirm") or ""
            first_name = (request.POST.get("first_name") or "").strip()
            last_name = (request.POST.get("last_name") or "").strip()
            is_staff = bool(request.POST.get("is_staff"))
            is_active = bool(request.POST.get("is_active"))
            is_superuser = bool(request.POST.get("is_superuser")) if request.user.is_superuser else False

            if not username:
                messages.error(request, "Username is required.")
            elif not password:
                messages.error(request, "Password is required.")
            elif password != password_confirm:
                messages.error(request, "Passwords do not match.")
            elif User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists.")
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    is_staff=is_staff,
                    is_active=is_active,
                )
                if is_superuser and request.user.is_superuser:
                    user.is_superuser = True
                    user.save(update_fields=["is_superuser"])
                if can_assign_access:
                    group_ids = request.POST.getlist("group_ids")
                    perm_ids = request.POST.getlist("permission_ids")
                    user.groups.set(Group.objects.filter(id__in=group_ids))
                    user.user_permissions.set(Permission.objects.filter(id__in=perm_ids))
                messages.success(request, f"User '{username}' created.")

        elif action == "update":
            if not can_change:
                return HttpResponseForbidden("You do not have permission to change users.")

            user_id = request.POST.get("user_id")
            target_user = get_object_or_404(User, pk=user_id)

            if target_user.is_superuser and not request.user.is_superuser:
                return HttpResponseForbidden("You cannot modify a superuser.")

            new_password = request.POST.get("password") or ""
            password_confirm = request.POST.get("password_confirm") or ""
            if new_password.strip() and new_password != password_confirm:
                messages.error(request, "Passwords do not match.")
                return redirect("cpq:manage_users")

            target_user.first_name = (request.POST.get("first_name") or "").strip()
            target_user.last_name = (request.POST.get("last_name") or "").strip()
            target_user.email = (request.POST.get("email") or "").strip()
            target_user.is_staff = bool(request.POST.get("is_staff"))
            requested_active = bool(request.POST.get("is_active")) if "is_active" in request.POST else False

            if target_user == request.user and not requested_active:
                messages.error(request, "You cannot deactivate your own account.")
            else:
                target_user.is_active = requested_active

            if request.user.is_superuser:
                target_user.is_superuser = bool(request.POST.get("is_superuser"))

            password_changed = False
            if new_password.strip():
                target_user.set_password(new_password.strip())
                password_changed = True

            target_user.save()
            if password_changed and target_user == request.user:
                update_session_auth_hash(request, target_user)
            if can_assign_access:
                group_ids = request.POST.getlist("group_ids")
                perm_ids = request.POST.getlist("permission_ids")
                target_user.groups.set(Group.objects.filter(id__in=group_ids))
                target_user.user_permissions.set(Permission.objects.filter(id__in=perm_ids))
            messages.success(request, f"User '{target_user.username}' updated.")

        elif action == "create_group":
            if not can_add_group:
                return HttpResponseForbidden("You do not have permission to add groups.")

            group_name = (request.POST.get("group_name") or "").strip()
            if not group_name:
                messages.error(request, "Group name is required.")
                return redirect("cpq:manage_users")

            if Group.objects.filter(name__iexact=group_name).exists():
                messages.error(request, "Group name already exists.")
                return redirect("cpq:manage_users")

            group = Group.objects.create(name=group_name)
            if can_change_group:
                perm_ids = request.POST.getlist("group_permission_ids")
                group.permissions.set(Permission.objects.filter(id__in=perm_ids))
            messages.success(request, f"Group '{group_name}' created.")

        elif action == "update_group":
            if not can_change_group:
                return HttpResponseForbidden("You do not have permission to change groups.")

            group_id = request.POST.get("group_id")
            group = get_object_or_404(Group, pk=group_id)
            group_name = (request.POST.get("group_name") or "").strip()
            if not group_name:
                messages.error(request, "Group name is required.")
                return redirect("cpq:manage_users")

            if Group.objects.filter(name__iexact=group_name).exclude(pk=group.pk).exists():
                messages.error(request, "Group name already exists.")
                return redirect("cpq:manage_users")

            group.name = group_name
            group.save(update_fields=["name"])
            perm_ids = request.POST.getlist("group_permission_ids")
            group.permissions.set(Permission.objects.filter(id__in=perm_ids))
            messages.success(request, f"Group '{group_name}' updated.")

        elif action == "delete_group":
            if not can_delete_group:
                return HttpResponseForbidden("You do not have permission to delete groups.")

            group_id = request.POST.get("group_id")
            group = get_object_or_404(Group, pk=group_id)
            group_name = group.name
            group.delete()
            messages.success(request, f"Group '{group_name}' deleted.")

        return redirect("cpq:manage_users")

    users = User.objects.prefetch_related("groups", "user_permissions").order_by("username")
    groups = Group.objects.prefetch_related("permissions", "user_set").order_by("name")
    permissions_by_app = OrderedDict()
    permissions = Permission.objects.select_related("content_type").order_by("content_type__app_label", "name")
    for perm in permissions:
        app_label = perm.content_type.app_label
        permissions_by_app.setdefault(app_label, []).append(perm)
    return render(request, "user_management.html", {
        "users": users,
        "can_add": can_add,
        "can_change": can_change,
        "can_assign_access": can_assign_access,
        "can_add_group": can_add_group,
        "can_change_group": can_change_group,
        "can_delete_group": can_delete_group,
        "groups": groups,
        "permissions_by_app": permissions_by_app,
    })

def _estimate_queryset_size(qs, field_names=None, chunk_size=250):
    """Approximate the size in bytes of all rows returned by a queryset."""

    if field_names is None:
        field_names = [f.name for f in qs.model._meta.concrete_fields]

    total = 0
    for row in qs.values(*field_names).iterator(chunk_size=chunk_size):
        total += len(json.dumps(row, default=str))
    return total


def _sum_file_field_sizes(qs, field_name):
    total = 0
    for instance in qs.iterator(chunk_size=100):
        file_field = getattr(instance, field_name, None)
        if not file_field or not getattr(file_field, "name", None):
            continue
        try:
            total += default_storage.size(file_field.name)
        except (OSError, FileNotFoundError):
            continue
    return total


def _get_r2_client():
    required_settings = (
        getattr(settings, "AWS_S3_ENDPOINT_URL", None),
        getattr(settings, "AWS_ACCESS_KEY_ID", None),
        getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
        getattr(settings, "AWS_STORAGE_BUCKET_NAME", None),
    )

    if not all(required_settings):
        return None

    try:
        client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )
    except Exception as exc:  # noqa: BLE001
        logging.warning("Unable to create R2 client: %s", exc)
        return None

    return client


def _get_r2_storage_usage(tenant):
    if not tenant or not getattr(tenant, "tenant_id", None):
        return 0

    client = _get_r2_client()
    if client is None:
        return 0

    prefix = f"tenant_{tenant.tenant_id}/"
    total = 0

    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Prefix=prefix,
        ):
            for obj in page.get("Contents", []):
                total += obj.get("Size", 0)

    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "Unable to fetch R2 usage for tenant %s: %s",
            tenant.tenant_id,
            exc,
        )
        return 0

    return total


def _list_r2_objects(tenant):
    if not tenant or not getattr(tenant, "tenant_id", None):
        return []

    client = _get_r2_client()
    if client is None:
        return []

    prefix = f"tenant_{tenant.tenant_id}/"
    objects = []

    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Prefix=prefix,
        ):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                item = {
                    "key": key,
                    "size": obj.get("Size", 0),
                    "last_modified": obj.get("LastModified"),
                }

                if key:
                    try:
                        item["preview_url"] = client.generate_presigned_url(
                            "get_object",
                            Params={
                                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                                "Key": key,
                            },
                            ExpiresIn=300,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logging.warning("Unable to generate preview URL for %s: %s", key, exc)
                        item["preview_url"] = None
                else:
                    item["preview_url"] = None

                objects.append(item)
    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "Unable to list R2 objects for tenant %s: %s",
            tenant.tenant_id,
            exc,
        )

    return objects


def _delete_r2_objects(tenant, keys):
    if not tenant or not keys:
        return False, "No tenant or keys provided"

    client = _get_r2_client()
    if client is None:
        return False, "Cloudflare R2 is not configured"

    deleted = 0
    errors = []

    for key in keys:
        try:
            client.delete_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=key,
            )
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to delete R2 object %s: %s", key, exc)
            errors.append(key)

    if errors:
        return False, f"Failed to delete {len(errors)} object(s)."

    return True, f"Deleted {deleted} object(s)."


def _calculate_tenant_storage_usage(tenant):
    if not tenant:
        return None

    tenant_id = getattr(tenant, "tenant_id", None)

    account_qs = Account.objects.all()
    if tenant_id:
        tenant_accounts = account_qs.filter(tenant_id=tenant_id)
        if tenant_accounts.exists():
            account_qs = tenant_accounts

    contact_qs = Contact.objects.filter(account__in=account_qs)
    opportunity_qs = Opportunity.objects.filter(account__in=account_qs)
    quote_qs = Quote.objects.filter(account__in=account_qs)
    quote_line_qs = QuoteLine.objects.filter(quote__in=quote_qs)

    document_qs = QuoteDocument.objects.filter(quote__in=quote_qs)
    attachment_qs = QuotePendingAttachment.objects.filter(quote__in=quote_qs)
    activity_qs = Activity.objects.filter(opportunity__in=opportunity_qs)

    lead_qs = Lead.objects.all()
    if tenant_id:
        tenant_leads = lead_qs.filter(contact__account__tenant_id=tenant_id)
        if tenant_leads.exists():
            lead_qs = tenant_leads

    records_bytes = 0
    records_bytes += _estimate_queryset_size(account_qs)
    records_bytes += _estimate_queryset_size(contact_qs)
    records_bytes += _estimate_queryset_size(opportunity_qs)
    records_bytes += _estimate_queryset_size(quote_qs)
    records_bytes += _estimate_queryset_size(quote_line_qs)
    records_bytes += _estimate_queryset_size(document_qs)
    records_bytes += _estimate_queryset_size(
        attachment_qs,
        field_names=[
            "id",
            "quote_id",
            "original_name",
            "mime_type",
            "uploaded_at",
            "consumed",
        ],
    )
    records_bytes += _estimate_queryset_size(activity_qs)
    records_bytes += _estimate_queryset_size(lead_qs)

    files_bytes_local = _sum_file_field_sizes(document_qs, "file")
    files_bytes_local += _sum_file_field_sizes(attachment_qs, "file")
    files_bytes_r2 = _get_r2_storage_usage(tenant)
    files_bytes = files_bytes_local + files_bytes_r2

    total_bytes = records_bytes + files_bytes

    mb_divisor = 1024 * 1024
    records_mb = round(records_bytes / mb_divisor, 2) if records_bytes else 0.0
    files_mb = round(files_bytes / mb_divisor, 2) if files_bytes else 0.0
    storage_mb = round(total_bytes / mb_divisor, 2) if total_bytes else 0.0

    records_percent = 0.0
    documents_percent = 0.0
    if records_bytes:
        records_percent = min((records_bytes / (10 * mb_divisor)) * 100, 100)
    if files_bytes:
        documents_percent = min((files_bytes / (50 * mb_divisor)) * 100, 100)

    return {
        "tenant": tenant,
        "storage_bytes": total_bytes,
        "storage_mb": storage_mb,
        "records_bytes": records_bytes,
        "files_bytes": files_bytes,
        "records_mb": records_mb,
        "files_mb": files_mb,
        "records_percent": round(records_percent, 2),
        "documents_percent": round(documents_percent, 2),
    }


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect('dashboard')  # or any logged-in home view
    return redirect('login')


def _redirect_to_custom_fields(object_name=None):
    base_url = reverse('cpq:custom_fields')

    if object_name:
        view_param = 'custom' if CustomObject.objects.filter(name=object_name).exists() else 'standard'
        return redirect(f"{base_url}?view={view_param}&object_name={object_name}")

    return redirect(base_url)

def product_list(request):
    """Fetch all products and display them in a table."""
    if request.method == "POST":
        if not request.user.is_authenticated:
            return HttpResponseForbidden("You must be logged in to manage products.")

        action = (request.POST.get("action") or "").strip().lower()
        next_url = request.POST.get("next") or request.GET.get("next") or request.path

        if action not in {"create", "update"}:
            messages.error(request, "Invalid product action.")
            return redirect(next_url)

        product = None
        if action == "update":
            product_id = request.POST.get("product_id")
            if not product_id:
                messages.error(request, "Missing product ID for update.")
                return redirect(next_url)
            product = get_object_or_404(Product, id=product_id)
            if not (request.user.is_staff or request.user.is_superuser):
                if is_partner_user(request.user) and product.created_by_id != request.user.id:
                    return HttpResponseForbidden("You do not have permission to edit this product.")
        else:
            product = Product(created_by=request.user)

        name = (request.POST.get("name") or "").strip()
        sku = (request.POST.get("sku") or "").strip()
        family = (request.POST.get("family") or "").strip()
        description = (request.POST.get("description") or "").strip()
        price_raw = (request.POST.get("price") or "").strip()
        term_raw = (request.POST.get("term") or "").strip()
        fixed_price_raw = (request.POST.get("fixed_price") or "").strip()
        price_mode = (request.POST.get("price_mode") or "").strip().lower()

        errors = []
        if not name:
            errors.append("Name is required.")
        if not sku:
            errors.append("SKU is required.")
        if not family:
            errors.append("Family is required.")

        price = None
        if price_raw:
            try:
                price = Decimal(price_raw)
            except InvalidOperation:
                errors.append("Price must be a valid number.")
        else:
            errors.append("Price is required.")

        term = None
        if term_raw:
            try:
                term = int(term_raw)
            except (TypeError, ValueError):
                errors.append("Term must be a whole number.")

        fixed_price = None
        if fixed_price_raw:
            try:
                fixed_price = Decimal(fixed_price_raw)
            except InvalidOperation:
                errors.append("Fixed price must be a valid number.")

        if price_mode not in {"fixed", "sum"}:
            price_mode = "fixed"

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect(next_url)

        product.name = name
        product.sku = sku
        product.family = family
        product.description = description
        product.price = price
        product.term = term
        product.is_subscription = request.POST.get("is_subscription") == "on"
        product.is_bundle = request.POST.get("is_bundle") == "on"
        product.is_active = request.POST.get("is_active") == "on"
        product.price_mode = price_mode

        if fixed_price is not None:
            product.fixed_price = fixed_price
        elif price_mode == "fixed":
            product.fixed_price = price

        product.updated_by = request.user

        try:
            product.save()
            messages.success(
                request,
                "Product updated successfully." if action == "update" else "Product created successfully.",
            )
        except Exception as exc:
            messages.error(request, f"Unable to save product: {exc}")

        return redirect(next_url)

    products = Product.objects.all()
    options = Option.objects.all()
    for product in products:
        product.bundle_options = [
            opt for opt in options if opt.parent_product_id == product.id
        ]
    bundles = [product for product in products if product.is_bundle]
    return render(
        request,
        "products.html",
        {
            "products": products,
            "options": options,
            "bundles": bundles,
            "is_partner_user": is_partner_user(request.user),
        },
    )

def product_detail(request, product_id):
    """View detailed product information."""
    print("product detail")
    product = get_object_or_404(Product, id=product_id)
    return render(request, "product_detail.html", {"product": product})

def settings_view(request):
    return render(request, "cpq/settings.html")


@login_required
def cpq_settings_admin(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("You do not have access to CPQ settings.")

    settings_obj = CPQSettings.safe_first() or CPQSettings.objects.create()

    if request.method == "POST":
        form = CPQSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            CPQSettings.load_cached(force_refresh=True)
            messages.success(request, "CPQ settings updated.")
            return redirect("cpq:cpq_settings")
        messages.error(request, "Please fix the errors below.")
    else:
        form = CPQSettingsForm(instance=settings_obj)

    for field in form.fields.values():
        input_type = getattr(field.widget, "input_type", "")
        css_class = "settings-checkbox" if input_type == "checkbox" else "settings-input"
        field.widget.attrs.setdefault("class", css_class)

    return render(request, "cpq_settings.html", {"form": form})

def build_account_quote_hierarchy_for_user(user):
    """Return Account → Opportunity → Quote hierarchy for the given user."""

    if user.is_superuser:
        base_qs = Quote.objects.all()
    else:
        base_qs = Quote.objects.all()
        if not is_partner_user(user):
            base_qs = base_qs.filter(owner=user)

    base_qs = apply_partner_access_filter(user, "Quote", base_qs)

    quotes = (
        base_qs.select_related("account", "opportunity__account")
        .prefetch_related(
            Prefetch(
                "quote_lines",
                queryset=QuoteLine.objects.select_related("product"),
                to_attr="lines",
            )
        )
        .order_by("account__name", "opportunity__name", "name")
    )

    opportunity_ids = {quote.opportunity_id for quote in quotes if quote.opportunity_id}
    contracts_by_opportunity = defaultdict(list)
    active_subscriptions_by_opportunity = defaultdict(list)
    if opportunity_ids:
        contracts = (
            Contract.objects.filter(opportunity_id__in=opportunity_ids)
            .prefetch_related(
                Prefetch(
                    "subscriptions",
                    queryset=Subscription.objects.filter(status="Active").select_related("product"),
                )
            )
            .order_by("-start_date", "-id")
        )
        for contract in contracts:
            contracts_by_opportunity[contract.opportunity_id].append(contract)
            for subscription in contract.subscriptions.all():
                active_subscriptions_by_opportunity[contract.opportunity_id].append(subscription)

    hierarchy = OrderedDict()
    for quote in quotes:
        account_entry = hierarchy.setdefault(
            quote.account_id,
            {"account": quote.account, "opportunities": OrderedDict()},
        )
        opportunity_entry = account_entry["opportunities"].setdefault(
            quote.opportunity_id,
            {
                "opportunity": quote.opportunity,
                "quotes": [],
                "contracts": contracts_by_opportunity.get(quote.opportunity_id, []),
                "active_subscriptions": active_subscriptions_by_opportunity.get(quote.opportunity_id, []),
            },
        )
        opportunity_entry["quotes"].append(quote)

    return [
        {
            "account": data["account"],
            "opportunities": list(data["opportunities"].values()),
        }
        for data in hierarchy.values()
    ]


def accounts_view(request):
    """Render the account-organized hierarchy for the current user."""

    account_groups = build_account_quote_hierarchy_for_user(request.user)
    is_authenticated = bool(get_valid_salesforce_token(timeout=6))

    return render(
        request,
        "accounts.html",
        {
            "account_groups": account_groups,
            "is_authenticated": is_authenticated,  # ✅ Used to show Sync button conditionally
        },
    )


@login_required
def related_opportunities_api(request):
    account_id = request.GET.get("account_id")
    if not account_id:
        return JsonResponse({"error": "account_id is required"}, status=400)

    try:
        account_id_int = int(account_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "account_id must be an integer"}, status=400)

    account = get_object_or_404(Account, pk=account_id_int)
    if not partner_can_access_record(request.user, "Account", account):
        return HttpResponseForbidden("You do not have access to this account.")

    opportunities = Opportunity.objects.filter(account=account).order_by("-created_at")
    opportunities = apply_partner_access_filter(request.user, "Opportunity", opportunities)
    record_id = request.GET.get("record_id")
    if record_id:
        try:
            record_id_int = int(record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "record_id must be an integer"}, status=400)
        opportunities = opportunities.filter(pk=record_id_int)
    total = opportunities.count()

    summary_only = str(request.GET.get("summary") or "").lower() in ("1", "true", "yes")
    preview_only = str(request.GET.get("preview") or "").lower() in ("1", "true", "yes")
    persist_list = str(request.GET.get("persist_list") or "").lower() in ("1", "true", "yes")
    limit_param = request.GET.get("limit")
    limit = None
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), 100))
        except (TypeError, ValueError):
            limit = None

    if limit:
        opportunities = opportunities[:limit]

    stored = False
    if preview_only:
        preview = []
        for opp in opportunities:
            preview.append({
                "record_id": opp.id,
                "record_value": str(opp),
                "object": "Opportunity",
                "name": opp.name,
                "account": account.name if account else None,
                "amount": float(opp.amount) if opp.amount is not None else None,
                "stage": opp.stage,
                "expected_close_date": opp.expected_close_date.isoformat() if opp.expected_close_date else None,
            })
        session_id = request.GET.get("session_id")
        if persist_list and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                list_label = f"Opportunities for {account.name} Account"
                rows = [
                    {
                        "name": entry.get("name") or entry.get("record_value") or "Record",
                        "account": entry.get("account"),
                        "amount": entry.get("amount"),
                        "stage": entry.get("stage"),
                        "expected_close_date": entry.get("expected_close_date"),
                    }
                    for entry in preview
                ]
                payload = {
                    "_meta": {
                        "related_list_role": "related-opportunities",
                        "related_account_id": account.id,
                    },
                    list_label: rows,
                }
                list_marker = "\"related_list_role\":\"related-opportunities\""
                account_marker = f"\"related_account_id\":{account.id}"
                exists = (
                    ChatMessage.objects.filter(session=session, sender="agent")
                    .filter(content__contains=list_marker)
                    .filter(content__contains=account_marker)
                    .exists()
                )
                if not exists:
                    content = f"retrieved_records: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True
        return JsonResponse({
            "account_id": account.id,
            "count": total,
            "records": preview,
            "stored": stored,
            "truncated": bool(limit and total > limit),
        })

    records = []
    if not summary_only:
        metadata = get_object_metadata("Opportunity")
        if not metadata:
            return JsonResponse({"error": "Opportunity metadata not found"}, status=400)

        for opp in opportunities:
            payload = serialize_record(
                opp,
                "Opportunity",
                metadata["custom_object"],
                metadata["custom_fields"],
                user=request.user,
            )
            payload["related_account_id"] = account.id
            records.append(payload)

        persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
        session_id = request.GET.get("session_id")
        if persist and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                account_marker = f"\"related_account_id\":{account.id}"
                for payload in records:
                    record_id = payload.get("record_id")
                    if record_id is None:
                        continue
                    record_marker = f"\"record_id\":{record_id}"
                    exists = (
                        ChatMessage.objects.filter(session=session, sender="agent")
                        .filter(content__contains=account_marker)
                        .filter(content__contains=record_marker)
                        .exists()
                    )
                    if exists:
                        continue
                    content = f"single_record: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True

    return JsonResponse({
        "account_id": account.id,
        "count": total,
        "records": records,
        "stored": stored,
        "truncated": bool(limit and total > limit),
    })


@login_required
def related_quotes_api(request):
    opportunity_id = request.GET.get("opportunity_id")
    if not opportunity_id:
        return JsonResponse({"error": "Missing opportunity_id"}, status=400)

    opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
    if not partner_can_access_record(request.user, "Opportunity", opportunity):
        return HttpResponseForbidden("You do not have access to this opportunity.")

    quotes = Quote.objects.filter(opportunity=opportunity).order_by("-id")
    quotes = apply_partner_access_filter(request.user, "Quote", quotes)
    record_id = request.GET.get("record_id")
    if record_id:
        try:
            record_id_int = int(record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "record_id must be an integer"}, status=400)
        quotes = quotes.filter(pk=record_id_int)
    total = quotes.count()

    summary_only = str(request.GET.get("summary") or "").lower() in ("1", "true", "yes")
    preview_only = str(request.GET.get("preview") or "").lower() in ("1", "true", "yes")
    persist_list = str(request.GET.get("persist_list") or "").lower() in ("1", "true", "yes")
    limit_param = request.GET.get("limit")
    limit = None
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), 100))
        except (TypeError, ValueError):
            limit = None

    if limit:
        quotes = quotes[:limit]

    stored = False
    if preview_only:
        preview = []
        for quote in quotes:
            is_primary = opportunity.primary_quote_id == quote.id
            preview.append({
                "record_id": quote.id,
                "record_value": str(quote),
                "object": "Quote",
                "name": quote.name,
                "status": quote.status,
                "net_amount": float(quote.net_amount) if quote.net_amount is not None else None,
                "expiration_date": quote.expiration_date.isoformat() if quote.expiration_date else None,
                "primary_quote": is_primary,
            })
        session_id = request.GET.get("session_id")
        if persist_list and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                list_label = f"Quotes for {opportunity.name} Opportunity"
                rows = [
                    {
                        "name": entry.get("name") or entry.get("record_value") or "Record",
                        "status": entry.get("status"),
                        "net_amount": entry.get("net_amount"),
                        "expiration_date": entry.get("expiration_date"),
                        "primary_quote": entry.get("primary_quote"),
                        "view_quote": (
                            f"<button type=\"button\" class=\"quote-list-view-btn\" "
                            f"data-quote-id=\"{entry.get('record_id')}\" "
                            f"aria-label=\"View quote details\" "
                            f"title=\"View quote details\">"
                            f"<span class=\"material-icons\" aria-hidden=\"true\">visibility</span>"
                            f"</button>"
                        ),
                    }
                    for entry in preview
                ]
                payload = {
                    "_meta": {
                        "related_list_role": "related-quotes",
                        "related_opportunity_id": opportunity.id,
                    },
                    list_label: rows,
                }
                list_marker = "\"related_list_role\":\"related-quotes\""
                opp_marker = f"\"related_opportunity_id\":{opportunity.id}"
                exists = (
                    ChatMessage.objects.filter(session=session, sender="agent")
                    .filter(content__contains=list_marker)
                    .filter(content__contains=opp_marker)
                    .exists()
                )
                if not exists:
                    content = f"retrieved_records: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True
        return JsonResponse({
            "opportunity_id": opportunity.id,
            "count": total,
            "records": preview,
            "stored": stored,
            "truncated": bool(limit and total > limit),
        })

    records = []
    if not summary_only:
        metadata = get_object_metadata("Quote")
        if not metadata:
            return JsonResponse({"error": "Quote metadata not found"}, status=400)

        for quote in quotes:
            payload = serialize_record(
                quote,
                "Quote",
                metadata["custom_object"],
                metadata["custom_fields"],
                user=request.user,
            )
            payload["related_opportunity_id"] = opportunity.id
            records.append(payload)

        persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
        session_id = request.GET.get("session_id")
        if persist and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                opportunity_marker = f"\"related_opportunity_id\":{opportunity.id}"
                for payload in records:
                    record_id = payload.get("record_id")
                    if record_id is None:
                        continue
                    record_marker = f"\"record_id\":{record_id}"
                    exists = (
                        ChatMessage.objects.filter(session=session, sender="agent")
                        .filter(content__contains=opportunity_marker)
                        .filter(content__contains=record_marker)
                        .exists()
                    )
                    if exists:
                        continue
                    content = f"single_record: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True

    return JsonResponse({
        "opportunity_id": opportunity.id,
        "count": total,
        "records": records,
        "stored": stored,
        "truncated": bool(limit and total > limit),
    })


@login_required
def related_contract_lines_api(request):
    account_id = request.GET.get("account_id")
    if not account_id:
        return JsonResponse({"error": "Missing account_id"}, status=400)

    account = get_object_or_404(Account, pk=account_id)
    if not partner_can_access_record(request.user, "Account", account):
        return HttpResponseForbidden("You do not have access to this account.")
    custom_object = CustomObject.objects.filter(name__iexact="contractline__c").first()
    if not custom_object:
        return JsonResponse({
            "account_id": account.id,
            "count": 0,
            "records": [],
            "stored": False,
            "truncated": False,
        })

    if not user_can_access_custom_object(request.user, custom_object, "view"):
        return HttpResponseForbidden("You do not have permission to view this custom object.")

    lookup_fields = [field for field in custom_object.custom_fields.all() if field.data_type == "lookup"]
    account_lookup_fields = []
    for field in lookup_fields:
        lookup_model = (field.lookup_model or "").strip().lower()
        if lookup_model.endswith(".account") or lookup_model == "account" or lookup_model.endswith("account"):
            account_lookup_fields.append(field)
            continue
        field_name = (field.name or "").lower()
        field_label = (field.label or "").lower()
        if "account" in field_name or "account" in field_label:
            account_lookup_fields.append(field)

    if not account_lookup_fields:
        return JsonResponse({
            "account_id": account.id,
            "count": 0,
            "records": [],
            "stored": False,
            "truncated": False,
        })

    record_ids = (
        CustomFieldValue.objects.filter(field__in=account_lookup_fields, value=str(account.id))
        .values_list("record_id", flat=True)
        .distinct()
    )
    records_qs = CustomRecord.objects.filter(object_type=custom_object, id__in=record_ids).order_by("-id")
    record_id = request.GET.get("record_id")
    if record_id:
        try:
            record_id_int = int(record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "record_id must be an integer"}, status=400)
        records_qs = records_qs.filter(pk=record_id_int)
    total = records_qs.count()

    summary_only = str(request.GET.get("summary") or "").lower() in ("1", "true", "yes")
    preview_only = str(request.GET.get("preview") or "").lower() in ("1", "true", "yes")
    limit_param = request.GET.get("limit")
    limit = None
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), 100))
        except (TypeError, ValueError):
            limit = None

    if limit:
        records_qs = records_qs[:limit]

    if preview_only:
        preview = [
            {
                "record_id": record.id,
                "record_value": str(record),
                "object": custom_object.name,
            }
            for record in records_qs
        ]
        return JsonResponse({
            "account_id": account.id,
            "count": total,
            "records": preview,
            "truncated": bool(limit and total > limit),
        })

    records = []
    stored = False
    if not summary_only:
        metadata = get_object_metadata(custom_object.name)
        if not metadata:
            return JsonResponse({"error": "Custom object metadata not found"}, status=400)

        for record in records_qs:
            payload = serialize_record(
                record,
                custom_object.name,
                metadata["custom_object"],
                metadata["custom_fields"],
                user=request.user,
            )
            payload["related_account_id"] = account.id
            records.append(payload)

        persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
        session_id = request.GET.get("session_id")
        if persist and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                account_marker = f"\"related_account_id\":{account.id}"
                for payload in records:
                    record_id = payload.get("record_id")
                    if record_id is None:
                        continue
                    record_marker = f"\"record_id\":{record_id}"
                    exists = (
                        ChatMessage.objects.filter(session=session, sender="agent")
                        .filter(content__contains=account_marker)
                        .filter(content__contains=record_marker)
                        .exists()
                    )
                    if exists:
                        continue
                    content = f"single_record: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True

    return JsonResponse({
        "account_id": account.id,
        "count": total,
        "records": records,
        "stored": stored,
        "truncated": bool(limit and total > limit),
    })


@login_required
def related_activities_api(request):
    record_id = request.GET.get("record_id")
    object_name = request.GET.get("object")
    if not record_id or not object_name:
        return JsonResponse({"error": "Missing record_id or object"}, status=400)

    try:
        record_id_int = int(record_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "record_id must be an integer"}, status=400)

    object_key = str(object_name or "").strip().lower()
    activities = Activity.objects.none()
    parent_label = "Record"
    parent_name = ""

    if object_key in {"lead", "leads"}:
        lead = get_object_or_404(Lead, pk=record_id_int)
        if not partner_can_access_record(request.user, "Lead", lead):
            return HttpResponseForbidden("You do not have access to this lead.")
        activities = Activity.objects.filter(lead=lead)
        parent_label = "Lead"
        parent_name = f"{lead.first_name} {lead.last_name}".strip() or str(lead)
    elif object_key in {"contact", "contacts"}:
        contact = get_object_or_404(Contact, pk=record_id_int)
        if not partner_can_access_record(request.user, "Contact", contact):
            return HttpResponseForbidden("You do not have access to this contact.")
        activities = Activity.objects.filter(contact=contact)
        parent_label = "Contact"
        parent_name = str(contact)
    elif object_key in {"opportunity", "opportunities"}:
        opportunity = get_object_or_404(Opportunity, pk=record_id_int)
        if not partner_can_access_record(request.user, "Opportunity", opportunity):
            return HttpResponseForbidden("You do not have access to this opportunity.")
        activities = Activity.objects.filter(opportunity=opportunity)
        parent_label = "Opportunity"
        parent_name = opportunity.name
    elif object_key in {"account", "accounts"}:
        account = get_object_or_404(Account, pk=record_id_int)
        if not partner_can_access_record(request.user, "Account", account):
            return HttpResponseForbidden("You do not have access to this account.")
        account_filter = _activity_account_lookup_filter(account)
        activity_filters = (
            Q(opportunity__account=account)
            | Q(contact__account=account)
            | Q(lead__contact__account=account)
        )
        if account_filter:
            activity_filters |= account_filter
        activities = Activity.objects.filter(activity_filters)
        parent_label = "Account"
        parent_name = account.name
    elif object_key in {"quote", "quotes"}:
        quote = get_object_or_404(Quote, pk=record_id_int)
        if not partner_can_access_record(request.user, "Quote", quote):
            return HttpResponseForbidden("You do not have access to this quote.")
        filters = Q()
        has_filter = False
        if quote.opportunity_id:
            filters |= Q(opportunity_id=quote.opportunity_id)
            has_filter = True
        if quote.account_id:
            filters |= Q(contact__account_id=quote.account_id)
            filters |= Q(lead__contact__account_id=quote.account_id)
            has_filter = True
        activities = Activity.objects.filter(filters) if has_filter else Activity.objects.none()
        parent_label = "Quote"
        parent_name = quote.name
    elif object_key in {"quoteline", "quote_line", "quote lines"}:
        quote_line = get_object_or_404(QuoteLine, pk=record_id_int)
        if not partner_can_access_record(request.user, "QuoteLine", quote_line):
            return HttpResponseForbidden("You do not have access to this quote line.")
        quote = quote_line.quote
        filters = Q()
        has_filter = False
        if quote and quote.opportunity_id:
            filters |= Q(opportunity_id=quote.opportunity_id)
            has_filter = True
        if quote and quote.account_id:
            filters |= Q(contact__account_id=quote.account_id)
            filters |= Q(lead__contact__account_id=quote.account_id)
            has_filter = True
        activities = Activity.objects.filter(filters) if has_filter else Activity.objects.none()
        parent_label = "Quote Line"
        parent_name = str(quote_line)
    elif object_key in {"contract", "contracts"}:
        contract = get_object_or_404(Contract, pk=record_id_int)
        if not partner_can_access_record(request.user, "Contract", contract):
            return HttpResponseForbidden("You do not have access to this contract.")
        activities = Activity.objects.filter(opportunity_id=contract.opportunity_id)
        parent_label = "Contract"
        parent_name = str(contract)
    elif object_key in {"subscription", "subscriptions"}:
        subscription = get_object_or_404(Subscription, pk=record_id_int)
        if not partner_can_access_record(request.user, "Subscription", subscription):
            return HttpResponseForbidden("You do not have access to this subscription.")
        opp_id = None
        account_id = None
        if subscription.contract_id:
            opp_id = subscription.contract.opportunity_id
        if subscription.quote_id:
            opp_id = opp_id or subscription.quote.opportunity_id
            account_id = subscription.quote.account_id
        filters = Q()
        has_filter = False
        if opp_id:
            filters |= Q(opportunity_id=opp_id)
            has_filter = True
        if account_id:
            filters |= Q(contact__account_id=account_id)
            filters |= Q(lead__contact__account_id=account_id)
            has_filter = True
        activities = Activity.objects.filter(filters) if has_filter else Activity.objects.none()
        parent_label = "Subscription"
        parent_name = str(subscription)
    elif object_key.endswith("__c"):
        custom_object = CustomObject.objects.filter(name__iexact=object_key).first()
        if not custom_object:
            logging.getLogger(__name__).warning(
                "activity unsupported_object_detected object=%s record_id=%s",
                object_key,
                record_id_int,
            )
            return JsonResponse({
                "record_id": record_id_int,
                "count": 0,
                "records": [],
                "stored": False,
                "truncated": False,
                "message": "Activities unavailable for this record",
            })
        custom_record = CustomRecord.objects.filter(pk=record_id_int, object_type=custom_object).first()
        if not custom_record:
            logging.getLogger(__name__).warning(
                "activity parent null object=%s record_id=%s",
                custom_object.name,
                record_id_int,
            )
            return JsonResponse({
                "record_id": record_id_int,
                "count": 0,
                "records": [],
                "stored": False,
                "truncated": False,
                "message": "Activities unavailable for this record",
            })
        if not partner_can_access_record(request.user, custom_object.name, custom_record, custom_object=custom_object):
            return HttpResponseForbidden("You do not have access to this record.")

        relation = _resolve_activity_relation_from_custom_record(custom_record, request.user, max_depth=2)
        filters = Q()
        has_filter = False

        if relation.get("opportunity"):
            filters |= Q(opportunity=relation["opportunity"])
            has_filter = True
        if relation.get("contact"):
            filters |= Q(contact=relation["contact"])
            has_filter = True
        if relation.get("lead"):
            filters |= Q(lead=relation["lead"])
            has_filter = True
        if relation.get("account"):
            account_filter = _activity_account_lookup_filter(relation["account"])
            filters |= Q(opportunity__account=relation["account"])
            filters |= Q(contact__account=relation["account"])
            filters |= Q(lead__contact__account=relation["account"])
            if account_filter:
                filters |= account_filter
            has_filter = True

        activities = Activity.objects.filter(filters) if has_filter else Activity.objects.none()
        parent_label = custom_object.label or custom_object.name
        parent_name = custom_record.custom_identifier or str(custom_record)
        if not has_filter:
            logging.getLogger(__name__).warning(
                "activity lookup resolution failed object=%s record_id=%s",
                custom_object.name,
                record_id_int,
            )

    activities = apply_partner_access_filter(request.user, "Activity", activities).order_by("-created_at")

    summary_only = str(request.GET.get("summary") or "").lower() in ("1", "true", "yes")
    preview_only = str(request.GET.get("preview") or "").lower() in ("1", "true", "yes")
    persist_list = str(request.GET.get("persist_list") or "").lower() in ("1", "true", "yes")
    limit_param = request.GET.get("limit")
    limit = None
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), 100))
        except (TypeError, ValueError):
            limit = None

    total = activities.count()

    if limit:
        activities = activities[:limit]

    stored = False
    if preview_only:
        preview = []
        for activity in activities:
            preview.append({
                "record_id": activity.id,
                "record_value": activity.subject,
                "subject": activity.subject,
                "activity_type": activity.get_activity_type_display() or activity.activity_type,
                "status": activity.get_status_display() or activity.status,
                "due_date": activity.due_date.isoformat() if activity.due_date else None,
            })
        session_id = request.GET.get("session_id")
        if persist_list and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                name_text = parent_name or parent_label
                list_label = f"Activities for {name_text}".strip()
                rows = [
                    {
                        "subject": entry.get("subject") or entry.get("record_value") or "Activity",
                        "activity_type": entry.get("activity_type"),
                        "status": entry.get("status"),
                        "due_date": entry.get("due_date"),
                    }
                    for entry in preview
                ]
                payload = {
                    "_meta": {
                        "related_list_role": "related-activities",
                        "related_record_id": record_id_int,
                        "related_object": object_key,
                    },
                    list_label: rows,
                }
                list_marker = "\"related_list_role\":\"related-activities\""
                record_marker = f"\"related_record_id\":{record_id_int}"
                object_marker = f"\"related_object\":\"{object_key}\""
                exists = (
                    ChatMessage.objects.filter(session=session, sender="agent")
                    .filter(content__contains=list_marker)
                    .filter(content__contains=record_marker)
                    .filter(content__contains=object_marker)
                    .exists()
                )
                if not exists:
                    content = f"retrieved_records: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True
        return JsonResponse({
            "record_id": record_id_int,
            "count": total,
            "records": preview,
            "stored": stored,
            "truncated": bool(limit and total > limit),
        })

    records = []
    if not summary_only:
        metadata = get_object_metadata("Activity")
        if not metadata:
            return JsonResponse({"error": "Activity metadata not found"}, status=400)

        for activity in activities:
            payload = serialize_record(
                activity,
                "Activity",
                metadata["custom_object"],
                metadata["custom_fields"],
                user=request.user,
            )
            payload["related_record_id"] = record_id_int
            records.append(payload)

        persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
        session_id = request.GET.get("session_id")
        if persist and session_id:
            session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
            if session:
                record_marker = f"\"related_record_id\":{record_id_int}"
                for payload in records:
                    activity_id = payload.get("record_id")
                    if activity_id is None:
                        continue
                    activity_marker = f"\"record_id\":{activity_id}"
                    exists = (
                        ChatMessage.objects.filter(session=session, sender="agent")
                        .filter(content__contains=record_marker)
                        .filter(content__contains=activity_marker)
                        .exists()
                    )
                    if exists:
                        continue
                    content = f"single_record: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
                    ChatMessage.objects.create(
                        session=session,
                        sender="agent",
                        content=content,
                        hiddenMessage=True,
                    )
                    stored = True

    return JsonResponse({
        "record_id": record_id_int,
        "count": total,
        "records": records,
        "stored": stored,
        "truncated": bool(limit and total > limit),
    })


def _resolve_activity_relation_from_custom_record(custom_record, user, max_depth=2):
    relation = {
        "account": None,
        "opportunity": None,
        "contact": None,
        "lead": None,
    }
    activity_models = {Account, Opportunity, Contact, Lead}
    visited = set()

    def _resolve_lookup_instance(model_class, raw_value):
        if raw_value is None:
            return None
        raw = str(raw_value).strip()
        if not raw:
            return None
        if raw.isdigit():
            try:
                return model_class.objects.filter(pk=int(raw)).first()
            except (TypeError, ValueError):
                pass

        if model_class is Account:
            return (
                Account.objects.filter(
                    Q(accid__iexact=raw)
                    | Q(external_id__iexact=raw)
                    | Q(name__iexact=raw)
                    | Q(name__icontains=raw)
                )
                .order_by("-id")
                .first()
            )
        if model_class is Opportunity:
            return (
                Opportunity.objects.filter(
                    Q(oppid__iexact=raw)
                    | Q(name__iexact=raw)
                    | Q(name__icontains=raw)
                )
                .order_by("-id")
                .first()
            )
        if model_class is Contact:
            contact_q = Q(contactId__iexact=raw) | Q(email__iexact=raw)
            if " " in raw:
                parts = [part for part in raw.split(" ") if part]
                if len(parts) >= 2:
                    contact_q |= Q(first_name__iexact=parts[0], last_name__iexact=" ".join(parts[1:]))
            contact_q |= Q(first_name__iexact=raw) | Q(last_name__iexact=raw)
            return Contact.objects.filter(contact_q).order_by("-id").first()
        if model_class is Lead:
            lead_q = Q(leadId__iexact=raw) | Q(email__iexact=raw)
            if " " in raw:
                parts = [part for part in raw.split(" ") if part]
                if len(parts) >= 2:
                    lead_q |= Q(first_name__iexact=parts[0], last_name__iexact=" ".join(parts[1:]))
            lead_q |= Q(first_name__iexact=raw) | Q(last_name__iexact=raw)
            return Lead.objects.filter(lead_q).order_by("-id").first()
        return None

    def _resolve_custom_record(target_object, raw_value):
        if raw_value is None:
            return None
        raw = str(raw_value).strip()
        if not raw:
            return None
        if raw.isdigit():
            try:
                return CustomRecord.objects.filter(pk=int(raw), object_type=target_object).first()
            except (TypeError, ValueError):
                pass
        try:
            uuid_value = uuid.UUID(raw)
        except (TypeError, ValueError):
            uuid_value = None
        if uuid_value:
            record = CustomRecord.objects.filter(record_id=uuid_value, object_type=target_object).first()
            if record:
                return record
        return CustomRecord.objects.filter(
            custom_identifier__iexact=raw,
            object_type=target_object,
        ).first()

    def _apply_relation(model_class, related_obj):
        if not related_obj:
            return
        if model_class is Opportunity and not relation["opportunity"]:
            if partner_can_access_record(user, "Opportunity", related_obj):
                relation["opportunity"] = related_obj
        elif model_class is Contact and not relation["contact"]:
            if partner_can_access_record(user, "Contact", related_obj):
                relation["contact"] = related_obj
        elif model_class is Lead and not relation["lead"]:
            if partner_can_access_record(user, "Lead", related_obj):
                relation["lead"] = related_obj
        elif model_class is Account and not relation["account"]:
            if partner_can_access_record(user, "Account", related_obj):
                relation["account"] = related_obj

    def _explore_record(record, depth):
        if depth > max_depth:
            return
        record_key = (record.object_type_id, record.id)
        if record_key in visited:
            return
        visited.add(record_key)

        field_values = record.custom_field_values.select_related("field")
        for value in field_values:
            field = value.field
            if not field:
                continue
            raw_value = value.value
            if raw_value in (None, "", "---"):
                continue

            if field.data_type == "lookup":
                model_class = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)
                target_custom_object = None
                if not model_class and field.lookup_model:
                    target_custom_object = CustomObject.objects.filter(name__iexact=field.lookup_model).first()
                    if target_custom_object:
                        model_class = CustomRecord

                if model_class in activity_models:
                    related_obj = _resolve_lookup_instance(model_class, raw_value)
                    _apply_relation(model_class, related_obj)
                elif model_class is CustomRecord and target_custom_object and depth < max_depth:
                    related_record = _resolve_custom_record(target_custom_object, raw_value)
                    if related_record and partner_can_access_record(
                        user,
                        target_custom_object.name,
                        related_record,
                        custom_object=target_custom_object,
                    ):
                        _explore_record(related_record, depth + 1)

        if not any(relation.values()):
            for value in field_values:
                field = value.field
                if not field:
                    continue
                field_name = (field.name or "").lower()
                field_label = (field.label or "").lower()
                raw_value = value.value
                if raw_value in (None, "", "---"):
                    continue
                if "account" in field_name or "account" in field_label:
                    _apply_relation(Account, _resolve_lookup_instance(Account, raw_value))
                if "opportunity" in field_name or "opportunity" in field_label:
                    _apply_relation(Opportunity, _resolve_lookup_instance(Opportunity, raw_value))
                if "contact" in field_name or "contact" in field_label:
                    _apply_relation(Contact, _resolve_lookup_instance(Contact, raw_value))
                if "lead" in field_name or "lead" in field_label:
                    _apply_relation(Lead, _resolve_lookup_instance(Lead, raw_value))

    _explore_record(custom_record, 0)

    account = relation["account"]
    if account and not (relation["opportunity"] or relation["contact"] or relation["lead"]):
        contact = Contact.objects.filter(account=account, is_primary=True).first()
        if not contact:
            contact = Contact.objects.filter(account=account).order_by("-id").first()
        if contact and partner_can_access_record(user, "Contact", contact):
            relation["contact"] = contact
        if not relation["contact"]:
            opportunity = Opportunity.objects.filter(account=account).order_by("-id").first()
            if opportunity and partner_can_access_record(user, "Opportunity", opportunity):
                relation["opportunity"] = opportunity

    return relation


def _get_activity_account_lookup_field():
    fields = CustomField.objects.filter(object_type__iexact="Activity", data_type="lookup")
    for field in fields:
        lookup_model = (field.lookup_model or "").lower()
        if lookup_model.endswith(".account") or lookup_model == "account" or lookup_model.endswith("account"):
            return field
    for field in fields:
        name = (field.name or "").lower()
        label = (field.label or "").lower()
        if "account" in name or "account" in label:
            return field
    return None


def _activity_account_lookup_filter(account):
    field = _get_activity_account_lookup_field()
    if not field or not account:
        return None
    values = [str(account.id)]
    if getattr(account, "accid", None):
        values.append(str(account.accid))
    if getattr(account, "external_id", None):
        values.append(str(account.external_id))
    matching_ids = CustomFieldValue.objects.filter(
        field=field,
        value__in=values,
    ).values("object_id")
    return Q(id__in=Subquery(matching_ids))


def _set_activity_account_lookup(activity, account):
    field = _get_activity_account_lookup_field()
    if not field or not activity or not account:
        return False
    content_type = ContentType.objects.get_for_model(Activity)
    CustomFieldValue.objects.update_or_create(
        field=field,
        content_type=content_type,
        object_id=activity.id,
        defaults={"value": str(account.id)},
    )
    return True


@login_required
@require_POST
def create_activity_api(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    subject = str(data.get("subject") or "").strip()
    if not subject:
        return JsonResponse({"error": "Subject is required."}, status=400)

    def normalize_choice(value, choices):
        if not value:
            return None
        choice_map = {key: label for key, label in choices}
        if value in choice_map:
            return value
        value_lower = str(value).strip().lower()
        for key, label in choices:
            if str(label).strip().lower() == value_lower:
                return key
        return None

    activity_type = normalize_choice(
        data.get("activity_type"),
        Activity.ACTIVITY_TYPE_CHOICES,
    ) or Activity.ACTIVITY_TYPE_CHOICES[0][0]

    status = normalize_choice(
        data.get("status"),
        Activity.STATUS_CHOICES,
    ) or Activity.STATUS_CHOICES[0][0]

    due_date_raw = data.get("due_date")
    due_date = parse_date(due_date_raw) if due_date_raw else None
    if due_date_raw and due_date is None:
        return JsonResponse({"error": "Invalid due date."}, status=400)

    parent_object = str(data.get("object") or "").strip().lower()
    parent_record_id = data.get("record_id")
    relation_object = str(data.get("relation_object") or "").strip().lower()
    relation_identifier = str(data.get("relation_identifier") or "").strip()

    lead_ref = None
    contact_ref = None
    opportunity_ref = None

    if parent_object in {"lead", "contact", "opportunity"}:
        try:
            parent_id = int(parent_record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid parent record id."}, status=400)

        if parent_object == "lead":
            lead_ref = get_object_or_404(Lead, pk=parent_id)
            if not partner_can_access_record(request.user, "Lead", lead_ref):
                return HttpResponseForbidden("You do not have access to this lead.")
        elif parent_object == "contact":
            contact_ref = get_object_or_404(Contact, pk=parent_id)
            if not partner_can_access_record(request.user, "Contact", contact_ref):
                return HttpResponseForbidden("You do not have access to this contact.")
        else:
            opportunity_ref = get_object_or_404(Opportunity, pk=parent_id)
            if not partner_can_access_record(request.user, "Opportunity", opportunity_ref):
                return HttpResponseForbidden("You do not have access to this opportunity.")
    elif parent_object == "account":
        try:
            parent_id = int(parent_record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid parent record id."}, status=400)

        account = get_object_or_404(Account, pk=parent_id)
        if not partner_can_access_record(request.user, "Account", account):
            return HttpResponseForbidden("You do not have access to this account.")

        if relation_object in {"lead", "contact", "opportunity"} and relation_identifier:
            from agents.standard_record_agent import _find_lead, _find_contact, _find_opportunity

            if relation_object == "lead":
                lead_ref = _find_lead(relation_identifier)
                if not lead_ref:
                    return JsonResponse({"error": "Lead not found for this activity."}, status=404)
                if not partner_can_access_record(request.user, "Lead", lead_ref):
                    return HttpResponseForbidden("You do not have access to this lead.")
            elif relation_object == "contact":
                contact_ref = _find_contact(relation_identifier)
                if not contact_ref:
                    contact_ref = Contact.objects.filter(account=account, is_primary=True).first()
                    if not contact_ref:
                        contact_ref = Contact.objects.filter(account=account).order_by("-id").first()
                if not contact_ref:
                    return JsonResponse({"error": "Contact not found for this activity."}, status=404)
                if not partner_can_access_record(request.user, "Contact", contact_ref):
                    return HttpResponseForbidden("You do not have access to this contact.")
            else:
                opportunity_ref = _find_opportunity(relation_identifier)
                if not opportunity_ref:
                    return JsonResponse({"error": "Opportunity not found for this activity."}, status=404)
                if not partner_can_access_record(request.user, "Opportunity", opportunity_ref):
                    return HttpResponseForbidden("You do not have access to this opportunity.")
        else:
            account_field = _get_activity_account_lookup_field()
            if not account_field:
                return JsonResponse({"error": "Account lookup field not configured for activities."}, status=400)
    elif parent_object.endswith("__c"):
        try:
            parent_id = int(parent_record_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid parent record id."}, status=400)

        custom_object = CustomObject.objects.filter(name__iexact=parent_object).first()
        if not custom_object:
            return JsonResponse({"error": "Custom object not found."}, status=404)
        custom_record = get_object_or_404(CustomRecord, pk=parent_id, object_type=custom_object)
        if not partner_can_access_record(request.user, custom_object.name, custom_record, custom_object=custom_object):
            return HttpResponseForbidden("You do not have access to this record.")

        relation = _resolve_activity_relation_from_custom_record(custom_record, request.user)
        lead_ref = relation.get("lead")
        contact_ref = relation.get("contact")
        opportunity_ref = relation.get("opportunity")
        account_ref = relation.get("account")
        if not any([lead_ref, contact_ref, opportunity_ref, account_ref]):
            return JsonResponse({"error": "No related Lead, Contact, Opportunity, or Account found for this record."}, status=400)
    else:
        if relation_object not in {"lead", "contact", "opportunity"} or not relation_identifier:
            return JsonResponse({"error": "Select a Lead, Contact, or Opportunity to relate this activity."}, status=400)

        from agents.standard_record_agent import _find_lead, _find_contact, _find_opportunity

        if relation_object == "lead":
            lead_ref = _find_lead(relation_identifier)
            if not lead_ref:
                return JsonResponse({"error": "Lead not found for this activity."}, status=404)
            if not partner_can_access_record(request.user, "Lead", lead_ref):
                return HttpResponseForbidden("You do not have access to this lead.")
        elif relation_object == "contact":
            contact_ref = _find_contact(relation_identifier)
            # If contact not found and parent is account, try to find contact from account
            if not contact_ref and parent_object == "account" and parent_record_id:
                try:
                    account_id = int(parent_record_id)
                    account = Account.objects.filter(pk=account_id).first()
                    if account and partner_can_access_record(request.user, "Account", account):
                        # Try primary contact first, then first contact
                        contact_ref = Contact.objects.filter(account=account, is_primary=True).first()
                        if not contact_ref:
                            contact_ref = Contact.objects.filter(account=account).order_by("-id").first()
                        if contact_ref and not partner_can_access_record(request.user, "Contact", contact_ref):
                            contact_ref = None
                except (TypeError, ValueError):
                    pass
            if not contact_ref:
                return JsonResponse({"error": "Contact not found for this activity."}, status=404)
            if not partner_can_access_record(request.user, "Contact", contact_ref):
                return HttpResponseForbidden("You do not have access to this contact.")
        else:
            opportunity_ref = _find_opportunity(relation_identifier)
            if not opportunity_ref:
                return JsonResponse({"error": "Opportunity not found for this activity."}, status=404)
            if not partner_can_access_record(request.user, "Opportunity", opportunity_ref):
                return HttpResponseForbidden("You do not have access to this opportunity.")

    activity = Activity.objects.create(
        subject=subject,
        activity_type=activity_type,
        status=status,
        due_date=due_date,
        lead=lead_ref,
        contact=contact_ref,
        opportunity=opportunity_ref,
        notes=str(data.get("notes") or ""),
        created_by=request.user,
    )
    if parent_object == "account":
        if not _set_activity_account_lookup(activity, account):
            return JsonResponse({"error": "Account lookup field not configured for activities."}, status=400)
    if parent_object.endswith("__c") and account_ref:
        _set_activity_account_lookup(activity, account_ref)

    metadata = get_object_metadata("Activity")
    payload = serialize_record(
        activity,
        "Activity",
        metadata["custom_object"] if metadata else None,
        metadata["custom_fields"] if metadata else [],
        user=request.user,
    )

    return JsonResponse({
        "record_id": activity.id,
        "record_value": activity.subject,
        "subject": activity.subject,
        "activity_type": activity.get_activity_type_display() or activity.activity_type,
        "status": activity.get_status_display() or activity.status,
        "due_date": activity.due_date.isoformat() if activity.due_date else None,
        "payload": payload,
    })


@login_required
def quote_details_api(request):
    quote_id = request.GET.get("quote_id")
    if not quote_id:
        return JsonResponse({"error": "quote_id is required"}, status=400)

    try:
        quote_id_int = int(quote_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "quote_id must be an integer"}, status=400)

    quote = get_object_or_404(Quote, pk=quote_id_int)
    if not partner_can_access_record(request.user, "Quote", quote):
        return HttpResponseForbidden("You do not have access to this quote.")
    details = get_quote_details(quote)
    if isinstance(details, dict) and details.get("error"):
        return JsonResponse({"quote_details": details}, status=400, encoder=DjangoJSONEncoder)

    persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
    session_id = request.GET.get("session_id")
    if persist and session_id:
        session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
        if session:
            marker = f"\"quote_id\":{quote.id}"
            exists = (
                ChatMessage.objects.filter(session=session, sender="agent")
                .filter(content__contains=marker)
                .filter(content__contains="quote_details")
                .exists()
            )
            if not exists:
                content = f"quote_details: {json.dumps(details, ensure_ascii=False, separators=(',', ':'))}"
                ChatMessage.objects.create(
                    session=session,
                    sender="agent",
                    content=content,
                    hiddenMessage=True,
                )
    return JsonResponse({"quote_details": details}, encoder=DjangoJSONEncoder)


@login_required
def single_record_api(request):
    object_name = request.GET.get("object")
    record_id = request.GET.get("record_id")
    if not object_name or not record_id:
        return JsonResponse({"error": "object and record_id are required"}, status=400)

    record_id_int = None
    try:
        record_id_int = int(record_id)
    except (TypeError, ValueError):
        record_id_int = None

    metadata = get_object_metadata(object_name)
    if not metadata:
        return JsonResponse({"error": f"Unknown object '{object_name}'."}, status=404)

    model = metadata["model"]
    custom_object = metadata["custom_object"]
    custom_fields = metadata["custom_fields"]

    record_queryset = model.objects.all()
    if custom_object:
        record_queryset = record_queryset.filter(object_type=custom_object)

    record = None
    if record_id_int is not None:
        try:
            record = record_queryset.get(pk=record_id_int)
        except model.DoesNotExist:
            record = None
    else:
        alt_lookup_fields = []
        if custom_object:
            alt_lookup_fields = ["record_id", "custom_identifier"]
        else:
            alt_lookup_fields = {
                "Lead": ["leadId", "external_id"],
                "Account": ["accid", "external_id"],
                "Contact": ["contactId", "external_id"],
                "Opportunity": ["oppid", "hs_deal_id", "external_id"],
                "Quote": ["qteid", "external_id"],
                "Product": ["prdid", "external_id"],
                "Activity": ["activityid", "external_id"],
                "Contract": ["external_id"],
                "Subscription": ["external_id"],
                "Tenant": ["tenant_id"],
            }.get(model.__name__, [])

        for field_name in alt_lookup_fields:
            try:
                record = record_queryset.get(**{field_name: record_id})
                break
            except model.DoesNotExist:
                continue
            except Exception:
                continue

    if record is None:
        return JsonResponse({"error": "Record not found."}, status=404)

    if not partner_can_access_record(request.user, object_name, record, custom_object=custom_object):
        return HttpResponseForbidden("You do not have access to this record.")

    payload = serialize_record(record, object_name, custom_object, custom_fields, user=request.user)

    persist = str(request.GET.get("persist") or "").lower() in ("1", "true", "yes")
    session_id = request.GET.get("session_id")
    if persist and session_id:
        session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
        if session:
            marker = f"\"record_id\":{record_id_int}"
            exists = (
                ChatMessage.objects.filter(session=session, sender="agent")
                .filter(content__contains=marker)
                .filter(content__contains="single_record")
                .exists()
            )
            if not exists:
                content = f"single_record: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'), cls=DjangoJSONEncoder)}"
                ChatMessage.objects.create(
                    session=session,
                    sender="agent",
                    content=content,
                    hiddenMessage=True,
                )

    return JsonResponse({"single_record": payload}, encoder=DjangoJSONEncoder)


@login_required
@require_http_methods(["POST"])
def delete_single_record_api(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    object_name = payload.get("object") or payload.get("object_name")
    record_id = payload.get("record_id")
    if not object_name or not record_id:
        return JsonResponse({"error": "object and record_id are required"}, status=400)

    try:
        record_id_int = int(record_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "record_id must be an integer"}, status=400)

    metadata = get_object_metadata(object_name)
    if not metadata:
        return JsonResponse({"error": f"Unknown object '{object_name}'."}, status=404)

    model = metadata["model"]
    custom_object = metadata["custom_object"]

    record_queryset = model.objects.all()
    if custom_object:
        record_queryset = record_queryset.filter(object_type=custom_object)

    try:
        record = record_queryset.get(pk=record_id_int)
    except model.DoesNotExist:
        return JsonResponse({"error": "Record not found."}, status=404)

    if not partner_can_access_record(request.user, object_name, record, custom_object=custom_object):
        return HttpResponseForbidden("You do not have access to this record.")

    if custom_object:
        if not user_can_access_custom_object(request.user, custom_object, "delete"):
            return JsonResponse({"error": "You do not have permission to delete this record."}, status=403)
    else:
        perm_name = f"{model._meta.app_label}.delete_{model._meta.model_name}"
        if not request.user.has_perm(perm_name):
            return JsonResponse({"error": "You do not have permission to delete this record."}, status=403)

    deleted_count, deleted_map = record.delete()
    return JsonResponse({
        "success": True,
        "object": object_name,
        "record_id": record_id_int,
        "deleted_count": deleted_count,
        "deleted_map": deleted_map,
    }, encoder=DjangoJSONEncoder)


@login_required
@require_http_methods(["POST"])
def delete_single_record_chatlog_api(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    session_id = payload.get("session_id")
    object_name = payload.get("object") or payload.get("object_name")
    record_id = payload.get("record_id")
    if not session_id or not object_name or not record_id:
        return JsonResponse({"error": "session_id, object, and record_id are required"}, status=400)

    session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
    if not session:
        return JsonResponse({"error": "Chat session not found"}, status=404)

    try:
        record_id_int = int(record_id)
    except (TypeError, ValueError):
        record_id_int = None

    object_marker = f"\"object\":{json.dumps(str(object_name))}"
    messages = ChatMessage.objects.filter(session=session, sender="agent", content__contains="single_record:")
    messages = messages.filter(content__contains=object_marker)
    if record_id_int is not None:
        messages = messages.filter(content__contains=f"\"record_id\":{record_id_int}")
    else:
        messages = messages.filter(content__contains=f"\"record_id\":\"{record_id}\"")

    deleted_count, _ = messages.delete()
    return JsonResponse({"success": True, "deleted_count": deleted_count}, encoder=DjangoJSONEncoder)

MODEL_CHOICES = {
    "Opportunity": "Opportunity",  # ✅ Use class name, not table name
    "Quote": "Quote",
    "QuoteLine": "QuoteLine",
    "Product": "Product",
    "Account": "Account",
    "Contact": "Contact",
}

HUBSPOT_OBJECT_MAP = {
    "Opportunity": "deals",
    "Account": "companies",
    "Contact": "contacts",
    "Product": "products",
    "Quote": "quotes",
    "QuoteLine": "line_items",
}

SALESFORCE_OBJECT_MAP = {
    "Opportunity": "Opportunity",
    "Account": "Account",
    "Contact": "Contact",
    "Product": "Product2",
    "Quote": "Quote",
    "QuoteLine": "QuoteLineItem",
}


def _get_local_fields_for_object_type(object_type):
    if object_type not in MODEL_CHOICES:
        return None
    model = apps.get_model("cpq", MODEL_CHOICES[object_type])
    return [field.name for field in model._meta.fields]


@login_required
def crm_schema_api(request):
    crm = request.GET.get("crm", "AgentCPQ")
    object_type = request.GET.get("object_type", "Opportunity")
    crm_object = request.GET.get("crm_object")
    local_fields = _get_local_fields_for_object_type(object_type)
    if local_fields is None:
        return JsonResponse({"error": "Invalid object type"}, status=400)

    fields = []
    if crm == "HubSpot":
        hs_object = HUBSPOT_OBJECT_MAP.get(object_type)
        if not hs_object:
            return JsonResponse({"error": "Unsupported object"}, status=400)
        try:
            token = HubspotToken.objects.get(user_id="default")
            headers = {"Authorization": f"Bearer {token.access_token}"}
            url = f"https://api.hubapi.com/crm/v3/properties/{hs_object}"
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code != 200:
                return JsonResponse({"error": "HubSpot schema fetch failed"}, status=502)
            props = res.json().get("results", [])
            fields = [
                {"name": p.get("name"), "label": p.get("label") or p.get("name")}
                for p in props
                if p.get("name") and not p.get("hidden")
            ]
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=500)
    elif crm == "Salesforce":
        sf_object = crm_object or SALESFORCE_OBJECT_MAP.get(object_type)
        if not sf_object:
            return JsonResponse({"error": "Unsupported object"}, status=400)
        token = get_valid_salesforce_token(timeout=8)
        if not token:
            return JsonResponse({"error": "Salesforce authentication not found"}, status=401)
        fields, response = fetch_salesforce_object_fields(token, sf_object, timeout=8)
        if fields is None:
            return JsonResponse({"error": "Salesforce schema fetch failed"}, status=502)
    else:
        fields = []

    suggestions = suggest_field_mappings(local_fields, fields)
    return JsonResponse({
        "fields": fields,
        "suggestions": suggestions,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
    })

def field_mapping_view(request):
    """Dynamically fetch schema fields for the selected CRM and object type."""

    # ✅ Get the selected CRM and Object Type from request
    selected_crm = request.GET.get("crm", "AgentCPQ")
    selected_model = request.GET.get("object_type", "Opportunity")
    selected_crm_object = request.GET.get("crm_object") or None

    if selected_model not in MODEL_CHOICES:
        return JsonResponse({"error": "Invalid object type"}, status=400)

    print("🔍 >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> selected_model =", selected_model)

    # ✅ Get the correct model class dynamically
    ModelClass = apps.get_model('cpq', MODEL_CHOICES[selected_model])
    local_fields = [field.name for field in ModelClass._meta.fields]  # ✅ Get all fields

    # ✅ Fetch only mappings that match the selected CRM and Object Type
    mappings = {
        m.local_field: m.crm_field
        for m in SystemFieldMapping.objects.filter(crm=selected_crm, field_type=selected_model)
    }
    alias_map = {
        "Deal": "Opportunity",
        "Company": "Account",
        "Contact": "Contact",
        "Product": "Product",
        "Opportunity": "Opportunity",
        "Account": "Account",
        "line_items": "line_items",
    }
    selected_model_raw = request.GET.get("object_type", "Opportunity")
    selected_model = alias_map.get(selected_model_raw, selected_model_raw)

    crm_object_choices = []
    if selected_crm == "Salesforce":
        crm_object_choices = [
            "Account",
            "Contact",
            "Opportunity",
            "OpportunityLineItem",
            "PricebookEntry",
            "Product2",
            "Quote",
            "QuoteLineItem",
        ]
        if not selected_crm_object:
            default_crm_object = SALESFORCE_OBJECT_MAP.get(selected_model, "Opportunity")
            if selected_model == "QuoteLine":
                default_crm_object = "OpportunityLineItem"
            selected_crm_object = default_crm_object

    button_base_url = request.build_absolute_uri(reverse("start_quote_from_salesforce"))
    salesforce_button_urls = {
        "opportunity": f"{button_base_url}?opportunity_id={{!Opportunity.Id}}",
        "account": f"{button_base_url}?account_id={{!Account.Id}}",
    }

    return render(request, "field_mapping.html", {
        "local_fields": json.dumps(local_fields, cls=DjangoJSONEncoder),
        "mappings": mappings,  # ✅ Raw dict for get_item filter
        "mappings_json": json.dumps(mappings, cls=DjangoJSONEncoder),  # ✅ For JS
        "selected_crm": selected_crm,
        "selected_model": selected_model,
        "available_models": MODEL_CHOICES.keys(),
        "crm_object_choices": crm_object_choices,
        "selected_crm_object": selected_crm_object,
        "salesforce_button_urls": salesforce_button_urls,
    })


@login_required
@require_POST
def run_salesforce_setup(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("You do not have access to this action.")

    token = get_valid_salesforce_token(timeout=8)
    if not token:
        return JsonResponse({"success": False, "error": "Salesforce not authenticated."}, status=401)

    userinfo, userinfo_response = get_salesforce_userinfo(token, timeout=8)
    if not userinfo:
        status_code = getattr(userinfo_response, "status_code", 401)
        return JsonResponse(
            {"success": False, "error": f"Salesforce authentication failed (userinfo_http_{status_code})."},
            status=401,
        )

    status = validate_salesforce_connection(token, timeout=8)
    if not status.get("authenticated"):
        return JsonResponse({"success": False, "error": "Salesforce authentication failed."}, status=401)

    try:
        from salesforce.management.commands.create_fields_needed import REQUIRED_FIELDS
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=500)

    results = ensure_salesforce_fields(token, REQUIRED_FIELDS, timeout=8, dry_run=False)

    button_base_url = request.build_absolute_uri(reverse("start_quote_from_salesforce"))
    button_urls = {
        "opportunity": f"{button_base_url}?opportunity_id={{!Opportunity.Id}}",
        "account": f"{button_base_url}?account_id={{!Account.Id}}",
    }
    button_specs = [
        {
            "object": "Opportunity",
            "api_name": "AgentCPQ_Start_Quote",
            "label": "Start Quote",
            "url": button_urls["opportunity"],
            "display_type": "detailPageButton",
            "open_type": "newWindow",
        },
        {
            "object": "Account",
            "api_name": "AgentCPQ_Start_Quote",
            "label": "Start Quote",
            "url": button_urls["account"],
            "display_type": "detailPageButton",
            "open_type": "newWindow",
        },
    ]
    button_results = []
    lwc_result = None
    deploy_agentcpq_lwc = None
    deploy_salesforce_weblinks = None
    try:
        from salesforce.metadata_api import (
            deploy_agentcpq_lwc as _deploy_agentcpq_lwc,
            deploy_salesforce_weblinks as _deploy_salesforce_weblinks,
        )
        deploy_agentcpq_lwc = _deploy_agentcpq_lwc
        deploy_salesforce_weblinks = _deploy_salesforce_weblinks
    except Exception as exc:
        module_path = os.path.join(settings.BASE_DIR, "salesforce", "metadata_api.py")
        if os.path.exists(module_path):
            spec = importlib.util.spec_from_file_location("agentcpq_salesforce_metadata_api", module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                deploy_agentcpq_lwc = getattr(module, "deploy_agentcpq_lwc", None)
                deploy_salesforce_weblinks = getattr(module, "deploy_salesforce_weblinks", None)
        if not deploy_agentcpq_lwc:
            lwc_result = {
                "object": "LightningComponentBundle",
                "api_name": "agentcpqQuotePanel",
                "status": "error",
                "details": str(exc),
            }

    if deploy_salesforce_weblinks:
        try:
            button_results = deploy_salesforce_weblinks(token, button_specs, timeout=60)
        except Exception as exc:
            button_results = [{
                "object": "WebLink",
                "api_name": spec["api_name"],
                "status": "error",
                "details": str(exc),
            } for spec in button_specs]

    if deploy_agentcpq_lwc:
        try:
            lwc_result = deploy_agentcpq_lwc(token, timeout=60)
        except Exception as exc:
            lwc_result = {
                "object": "LightningComponentBundle",
                "api_name": "agentcpqQuotePanel",
                "status": "error",
                "details": str(exc),
            }

    product_sync_summary = None
    try:
        stdout = StringIO()
        call_command(
            "sync_products",
            use_standard_pricebook=True,
            update_existing=True,
            stdout=stdout,
            stderr=stdout,
        )
        product_sync_summary = stdout.getvalue().strip() or "Product sync complete."
    except Exception as exc:
        product_sync_summary = f"Product sync failed: {exc}"

    return JsonResponse({
        "success": True,
        "results": results + button_results + ([lwc_result] if lwc_result else []),
        "button_urls": button_urls,
        "product_sync": product_sync_summary,
    })


@csrf_exempt
def save_field_mappings(request):
    """Save field mappings for a selected CRM and object type."""
    if request.method == "POST":
        crm = request.POST.get("crm", "AgentCPQ")  # ✅ Capture CRM selection
        object_type = request.POST.get("object_type", "Opportunity")  # ✅ Capture object type selection

        updated_count = 0
        for key, value in request.POST.items():
            if key in ["crm", "object_type"]:
                continue  # ✅ Skip non-mapping fields

            crm_field = value.strip()
            if crm_field:  # ✅ Ensure it's not empty
                mapping, created = SystemFieldMapping.objects.update_or_create(
                    crm=crm,
                    local_field=key,
                    field_type=object_type,  # ✅ Ensure object type is saved correctly
                    defaults={"crm_field": crm_field}
                )
                if created:
                    updated_count += 1

        return JsonResponse({
            "success": True,
            "message": f"Updated {updated_count} mappings for {crm} - {object_type}."
        })

    return JsonResponse({"success": False, "message": "Invalid request."})


@csrf_exempt
def set_primary_quote(request, quote_id):
    if request.method == "POST":
        try:
            quote = Quote.objects.select_related("opportunity").get(id=quote_id)
            opportunity_id = quote.opportunity_id

            # Clear existing primary flags in the same opportunity
            Quote.objects.filter(opportunity_id=opportunity_id).update(hs_primary=False)

            # Set this quote as primary
            quote.hs_primary = True
            quote.save()
            if quote.opportunity_id:
                quote.opportunity.primary_quote = quote
                quote.opportunity.save(update_fields=["primary_quote"])
                try:
                    from agents.utils.quote_agent.db_helpers import update_opportunity_net_amount
                    update_opportunity_net_amount(quote.opportunity)
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "⚠️ Opportunity amount refresh failed after set-primary: %s", exc
                    )

            # Trigger HubSpot sync when a primary quote is set
            try:
                if getattr(quote.opportunity, "hs_deal_id", None):
                    sync_opportunity_to_hubspot(quote.opportunity_id, user_id="default")
                else:
                    logging.getLogger(__name__).info(
                        "[HS SYNC] Skipping sync after set-primary: Opportunity %s has no hs_deal_id",
                        quote.opportunity_id
                    )
            except Exception as e:
                logging.getLogger(__name__).exception("[HS SYNC] Failed after set-primary: %s", e)

            return JsonResponse({"success": True})
        except Quote.DoesNotExist:
            return JsonResponse({"error": "Quote not found"}, status=404)

    return JsonResponse({"error": "Invalid method"}, status=405)


@login_required
@require_POST
def create_renewal_quote(request, opportunity_id):
    opportunity = get_object_or_404(Opportunity, id=opportunity_id)
    if not partner_can_access_record(request.user, "Opportunity", opportunity):
        return HttpResponseForbidden("You do not have access to this opportunity.")

    result = make_opportunity_renewal(opportunity)
    if result is True:
        messages.success(request, "Renewal quote created.")
    elif isinstance(result, tuple) and result and result[0] is False:
        messages.error(request, f"Renewal creation failed: {result[1]}")
    else:
        messages.warning(request, "Unable to create renewal. Ensure a primary quote exists.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("cpq:accounts")
    return redirect(next_url)


# Maybe it is not used
#def create_custom_field(request):
#    if request.method == "POST":
#        crm = request.POST["crm"]
#        object_type = request.POST["object_type"]
#        name = request.POST["name"]
#        label = request.POST["label"]
#        data_type = request.POST["data_type"]
#        required = "required" in request.POST
#        options = request.POST.getlist("options[]")

        # ✅ Save to DB
#        field = CustomField.objects.create(
#            crm=crm,
#            object_type=object_type,
#            name=name,
#            label=label,
#            data_type=data_type,
#            required=required,
#            options=options if options else None,
#            created_by=request.user
#        )
#
#        if field:
#            quote_document_settings = QuoteDocumentSettings.objects.first()
#            if quote_document_settings:
#                # Add label at the end of omitted_fields
#                omitted = quote_document_settings.omitted_fields or []
#
#                if label not in omitted:  # Avoid duplicated
#                    omitted.append(label)
#                    quote_document_settings.omitted_fields = omitted
#                    quote_document_settings.save()
#
#        return redirect("custom_fields")
#
#    fields = CustomField.objects.all().order_by("-created_at")
#    return render(request, "custom_fields.html", {"fields": fields})

def get_standard_fields(model_name):
    mapping = {
        "Lead": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Contact": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Account": [{"name": "name", "data_type": "Text"}],
        "Opportunity": [{"name": "stage", "data_type": "Picklist"}, {"name": "amount", "data_type": "Currency"}],
        "Product": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Quote": [{"name": "net_amount", "data_type": "Currency"}, {"name": "status", "data_type": "Picklist"}],
        "QuoteLine": [{"name": "net_amount", "data_type": "Currency"}, {"name": "status", "data_type": "Picklist"}]
    }
    return mapping.get(model_name, [])

@login_required
def custom_fields_view(request):

    if request.method == 'POST':
        form = CustomObjectForm(request.POST)
        if form.is_valid():
            custom_object = form.save(commit=False)
            custom_object.created_by = request.user
            custom_object.updated_by = request.user
            custom_object.save()
            request.session['custom_object_success'] = True
            return _redirect_to_custom_fields(custom_object.name)
    else:
        form = CustomObjectForm()

    # Built-in models
    # NOTE: Keep these as CPQ model class names so apps.get_model('cpq', obj_type) works.
    object_types = [
        "Activity",
        "Lead",
        "Contact",
        "Account",
        "Opportunity",
        "Product",
        "Quote",
        "QuoteLine",
        # Extended standard objects
        "Contract",
        "Subscription",
        "Option",
        "Tenant",
        "Knowledge",
    ]

    # Custom objects
    custom_objects = CustomObject.objects.all()
    custom_object_names = [obj.name for obj in custom_objects]
    all_object_types = object_types + custom_object_names

    fields_by_object_type = {}

    for obj_type in all_object_types:
        try:
            model_class = apps.get_model('cpq', obj_type)
            standard_fields = []
            for field in model_class._meta.get_fields():
                # Skip reverse relations / autogenerated accessors.
                if getattr(field, "auto_created", False):
                    continue

                # Prefer user-editable forward fields (including FK/O2O/M2M).
                if not getattr(field, "editable", True):
                    continue

                data_type = field.get_internal_type()

                if getattr(field, "is_relation", False):
                    related = getattr(getattr(field, "remote_field", None), "model", None)
                    related_label = getattr(related, "__name__", None)
                    if related_label:
                        data_type = f"{data_type} → {related_label}"

                standard_fields.append({"name": field.name, "data_type": data_type})
        except LookupError:
            standard_fields = []

        if obj_type in object_types:
            custom_fields = CustomField.objects.filter(object_type=obj_type, custom_object__isnull=True)
        else:
            try:
                custom_obj = CustomObject.objects.get(name=obj_type)
                custom_fields = CustomField.objects.filter(object_type=custom_obj.name)
            except CustomObject.DoesNotExist:
                custom_fields = []

        fields_by_object_type[obj_type] = {
            "standard": standard_fields,
            "custom": custom_fields,
        }

    # New dictionary for real data of custom objects
    custom_objects_data = {}

    for custom_obj in custom_objects:
        custom_objects_data[custom_obj.name] = [{
            "label": custom_obj.label,
            "name": custom_obj.name,
            "description": custom_obj.description,
            "created_at": custom_obj.created_at,
            "created_by": custom_obj.created_by.username if custom_obj.created_by else "",
            "updated_at": custom_obj.updated_at,
            "updated_by": custom_obj.updated_by.username if custom_obj.updated_by else ""
        }]

    object_type_kinds = {}
    for obj in all_object_types:
        if obj in object_types:
            object_type_kinds[obj] = 'standard'
        else:
            object_type_kinds[obj] = 'custom'

    success = request.session.pop('custom_object_success', False)
    return render(request, "custom_fields.html", {
        "fields_by_object_type": fields_by_object_type,
        "models": all_object_types,
        "standard_models": object_types,
        "custom_models": custom_object_names,
        "custom_object_records": custom_objects_data,
        "object_type_kinds": object_type_kinds,
        "form": form,  # ✅ Pass the form to the template
        "success": success  # ✅ Add to context
    })

def edit_custom_object(request, object_name):
    custom_object = get_object_or_404(CustomObject, name=object_name)

    if request.method == 'POST':
        form = CustomObjectForm(request.POST, instance=custom_object)
        if form.is_valid():
            updated_object = form.save(commit=False)
            updated_object.updated_by = request.user
            updated_object.save()
            return _redirect_to_custom_fields(object_name)
    else:
        form = CustomObjectForm(instance=custom_object)

        # Get related values
        related_customfields = custom_object.custom_fields.all()

        related_data = defaultdict(list)

        for custom_field in related_customfields:
            related_values = custom_field.values.all()
            related_data[custom_field.label].extend(related_values)

        related_data = dict(related_data)

    return render(request, 'edit_custom_object.html', {
        'form': form,
        'object_name': object_name,
        'related_data': related_data
    })

@require_POST
def delete_custom_object(request, object_name):
    custom_object = get_object_or_404(CustomObject, name=object_name)

    if not request.user.is_superuser and not request.user.is_staff:
        return HttpResponseForbidden("You do not have permission to delete this custom object.")

    custom_object.delete()
    return _redirect_to_custom_fields(object_name)

def create_custom_field(request, object_name):
    if request.method == 'POST':
        form = CustomFieldForm(request.POST)

        if form.is_valid():
            # Buscamos si el object_type es un objeto custom

            field = form.save(commit=False)
            field.created_by = request.user
            field.updated_by = request.user

            # Get options if exists
            options = request.POST.getlist("options[]")
            field.options = options if options else None

            field.save()

            # 🔧 Lógica personalizada aquí
            #quote_document_settings = QuoteDocumentSettings.objects.first()
            #if quote_document_settings:
            #    full_label = f"{field.object_type}.{field.label}"
            #    omitted = quote_document_settings.omitted_fields or []

            #    if full_label not in omitted:
            #        omitted.append(full_label)
            #        quote_document_settings.omitted_fields = omitted
            #        quote_document_settings.save()

            return _redirect_to_custom_fields(field.object_type)
        else:
            print("Form errors:", form.errors)
    else:
        # Buscar si object_type es un objeto custom
        try:
            custom_obj = CustomObject.objects.get(name=object_name)
            form = CustomFieldForm(initial={'crm': 'AgentCPQ', 'object_type': object_name, 'custom_object': custom_obj})
        except ObjectDoesNotExist:
            form = CustomFieldForm(initial={'crm': 'AgentCPQ', 'object_type': object_name})

    return render(request, 'create_custom_field.html', {'form': form, 'object_name': object_name})


def edit_custom_field(request, field_id):
    custom_field = get_object_or_404(CustomField, id=field_id)

    if request.method == 'POST':
        form = CustomFieldForm(request.POST, instance=custom_field)
        if form.is_valid():
            updated_field = form.save(commit=False)
            updated_field.updated_by = request.user

            # Guardar las opciones del dropdown si el tipo es 'dropdown'
            if form.cleaned_data['data_type'] == 'dropdown':
                # request.POST.getlist('options[]') obtiene todos los inputs de opciones
                options = request.POST.getlist('options[]')
                # Filtrar valores vacíos
                updated_field.options = [opt for opt in options if opt.strip()]
            else:
                updated_field.options = []  # Limpiar si ya no es dropdown

            updated_field.save()
            return _redirect_to_custom_fields(updated_field.object_type)
    else:
        form = CustomFieldForm(instance=custom_field)
        related_values = custom_field.values.all()

    object_name = custom_field.object_type
    object_view = 'custom' if CustomObject.objects.filter(name=object_name).exists() else 'standard'

    return render(request, 'edit_custom_field.html', {
        'form': form,
        'field_id': field_id,
        'related_values': related_values,
        'object_name': object_name,
        'object_view': object_view,
    })


@require_POST
def delete_custom_field(request, field_id):
    custom_field = get_object_or_404(CustomField, id=field_id)

    # Only admins can delete custom fields
    if not request.user.is_superuser and not request.user.is_staff:
        return HttpResponseForbidden("You do not have permission to delete this custom field.")


    object_name = custom_field.object_type
    custom_field.delete()
    return _redirect_to_custom_fields(object_name)


@login_required
def get_company_information(request):
    company = Tenant.safe_first()  # Always work with the first (or only) tenant

    if request.method == 'POST':
        if not company:
            company = Tenant()

        company.name = request.POST.get('name', '')
        company.contact_email = request.POST.get('contact_email', '')
        company.phone_number = request.POST.get('phone_number', '')
        company.primary_color = request.POST.get('primary_color', '')
        company.secondary_color = request.POST.get('secondary_color', '')
        company.sidebar_bg_color_1 = request.POST.get('sidebar_bg_color_1', '') or company.sidebar_bg_color_1
        company.sidebar_bg_color_2 = request.POST.get('sidebar_bg_color_2', '') or company.sidebar_bg_color_2
        company.sidebar_text_color = request.POST.get('sidebar_text_color', '') or company.sidebar_text_color
        allowed_standard_keys = {item["key"] for item in STANDARD_SIDENAV_ITEMS}
        selected_standard_keys = [
            key
            for key in request.POST.getlist("sidebar_standard_objects")
            if key in allowed_standard_keys
        ]
        company.sidebar_standard_objects = selected_standard_keys
        company.street_address = request.POST.get('street_address', '')
        company.city = request.POST.get('city', '')
        company.state = request.POST.get('state', '')
        fiscal_start_raw = (request.POST.get('fiscal_year_start_month', '') or "").strip()
        if fiscal_start_raw:
            try:
                fiscal_start = int(fiscal_start_raw)
                if 1 <= fiscal_start <= 12:
                    company.fiscal_year_start_month = fiscal_start
            except ValueError:
                pass
        fiscal_label_mode = (request.POST.get('fiscal_year_label_mode', '') or "").strip().lower()
        if fiscal_label_mode in {"start", "end"}:
            company.fiscal_year_label_mode = fiscal_label_mode

        # company.plan = request.POST.get('plan', '')

        # actions_limit_raw = request.POST.get('actions_limit', '')
        # try:
        #     company.actions_limit = int(actions_limit_raw) if actions_limit_raw else None
        # except ValueError:
        #     company.actions_limit = None

        if 'logo' in request.FILES:
            company.logo = request.FILES['logo']

        update_fields = [
            "name",
            "contact_email",
            "phone_number",
            "primary_color",
            "secondary_color",
            "sidebar_bg_color_1",
            "sidebar_bg_color_2",
            "sidebar_text_color",
            "sidebar_standard_objects",
            "street_address",
            "city",
            "state",
            "fiscal_year_start_month",
            "fiscal_year_label_mode",
        ]
        if "logo" in request.FILES:
            update_fields.append("logo")

        table_columns = None
        if company.pk:
            try:
                with connection.cursor() as cursor:
                    table_columns = {
                        col.name
                        for col in connection.introspection.get_table_description(
                            cursor, company._meta.db_table
                        )
                    }
                update_fields = [
                    field
                    for field in update_fields
                    if company._meta.get_field(field).column in table_columns
                ]
            except (OperationalError, ProgrammingError):
                update_fields = []

            if update_fields:
                company.save(update_fields=update_fields)
            else:
                company.save()
        else:
            company.save()
        response = redirect('cpq:get_company_information')
        cookie_value = ",".join(selected_standard_keys)
        response.set_cookie(SIDEBAR_STANDARD_COOKIE, cookie_value, max_age=60 * 60 * 24 * 90, samesite="Lax")
        return response

    # Determine logo URL (public link)
    logo_url = ''
    if company and company.logo:
        logo_url = default_storage.url(company.logo.name)
    current_fiscal_quarter = None
    if company:
        try:
            fiscal_start = int(getattr(company, "fiscal_year_start_month", 1) or 1)
            if fiscal_start < 1 or fiscal_start > 12:
                fiscal_start = 1
            current_date = now().date()
            month = current_date.month
            year = current_date.year
            fiscal_year = year if month >= fiscal_start else year - 1
            offset = (month - fiscal_start) % 12
            quarter = (offset // 3) + 1
            label_mode = getattr(company, "fiscal_year_label_mode", "start")
            label_mode = label_mode if label_mode in {"start", "end"} else "start"
            label_year = fiscal_year + (1 if label_mode == "end" else 0)
            label_year_short = str(label_year % 100).zfill(2)
            current_fiscal_quarter = f"FY{label_year_short} Q{quarter}"
        except Exception:
            current_fiscal_quarter = None

    allowed_standard_keys = {item["key"] for item in STANDARD_SIDENAV_ITEMS}
    selected_standard_keys = None
    if company:
        selected_standard_keys = company.sidebar_standard_objects
    if selected_standard_keys is None or not isinstance(selected_standard_keys, list):
        cookie_keys = parse_standard_sidebar_cookie(request.COOKIES.get(SIDEBAR_STANDARD_COOKIE, ""))
        selected_standard_keys = cookie_keys or default_standard_sidebar_keys()
    selected_standard_keys = [key for key in selected_standard_keys if key in allowed_standard_keys]

    return render(request, 'company_information.html', {
        'company': company or Tenant(),
        'logo_url': logo_url,
        'current_fiscal_quarter': current_fiscal_quarter,
        "standard_sidenav_items": STANDARD_SIDENAV_ITEMS,
        "selected_standard_sidenav_keys": selected_standard_keys,
    })


@login_required
def admin_integrations(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("You do not have access to integrations.")

    hubspot_connected = False
    try:
        token = HubspotToken.objects.get(user_id="default")
        if token.expires_at and token.expires_at > now():
            headers = {
                "Authorization": f"Bearer {token.access_token}"
            }
            response = requests.get(
                "https://api.hubapi.com/integrations/v1/me",
                headers=headers,
                timeout=6,
            )
            if response.status_code == 200:
                hubspot_connected = True
    except HubspotToken.DoesNotExist:
        pass
    except requests.RequestException:
        hubspot_connected = False

    salesforce_token = get_valid_salesforce_token(timeout=6)
    if salesforce_token:
        salesforce_status = validate_salesforce_connection(salesforce_token, timeout=6)
        salesforce_connected = salesforce_status.get("authenticated", False)
        salesforce_permissions_ok = all(
            salesforce_status.get("permissions", {}).values()
        )
        salesforce_tooling_ok = salesforce_status.get("tooling_api_enabled", False)
    else:
        salesforce_status = {
            "authenticated": False,
            "permissions": {
                "CustomizeApplication": False,
                "ModifyAllData": False,
            },
            "tooling_api_enabled": False,
            "errors": ["missing_token"],
        }
        salesforce_connected = False
        salesforce_permissions_ok = False
        salesforce_tooling_ok = False
    quickbooks_connected = QuickbooksToken.objects.exists()
    docusign_connected = False

    company = Tenant.safe_first()

    return render(request, "admin_integrations.html", {
        "company": company or Tenant(),
        "hubspot_connected": hubspot_connected,
        "salesforce_connected": salesforce_connected,
        "salesforce_permissions_ok": salesforce_permissions_ok,
        "salesforce_tooling_ok": salesforce_tooling_ok,
        "salesforce_status": salesforce_status,
        "quickbooks_connected": quickbooks_connected,
        "docusign_connected": docusign_connected,
    })


@login_required
@require_POST
def disconnect_salesforce(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("You do not have access to integrations.")

    SalesforceToken.objects.all().delete()
    messages.success(request, "Salesforce connection removed.")
    return redirect("cpq:admin_integrations")


# No dont require this function (apparently)
def create_custom_object(request):
    if request.method == 'POST':
        form = CustomObjectForm(request.POST)
        if form.is_valid():
            custom_object = form.save(commit=False)
            custom_object.created_by = request.user
            print(f"User: {request.user}")
            custom_object.save()
            return redirect('cpq:custom_object_list')  # or some success view
    else:
        form = CustomObjectForm()

    return render(request, 'create_custom_object.html', {'form': form})

@login_required
def get_custom_record_form(request, record_id):
    record = get_object_or_404(CustomRecord, id=record_id)
    if not user_can_access_custom_object(request.user, record.object_type, "change"):
        return HttpResponseForbidden("You do not have permission to edit records for this object.")
    if not partner_can_access_record(request.user, record.object_type.name, record, custom_object=record.object_type):
        return HttpResponseForbidden("You do not have access to this record.")
    DynamicForm = generate_dynamic_form(record.object_type)

    initial_data = {}
    for value in record.custom_field_values.select_related("field"):
        field = value.field
        if field.data_type == "lookup" and field.lookup_model and value.value:
            model_class = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)
            related_obj = None
            if model_class:
                related_obj = model_class.objects.filter(pk=value.value).first()

            # Allow lookups to custom objects by name (stored as CustomRecord)
            if related_obj is None and field.lookup_model:
                try:
                    target_co = CustomObject.objects.get(name=field.lookup_model)
                    related_obj = CustomRecord.objects.filter(object_type=target_co, pk=value.value).first()
                except CustomObject.DoesNotExist:
                    related_obj = None

            initial_data[field.name] = related_obj or value.value
        else:
            initial_data[field.name] = value.value
    form = DynamicForm(initial=initial_data)

    # Solo retornamos el HTML parcial
    return render(request, 'custom_objects/partial_edit_form_fields.html', {'form': form})

@login_required
def edit_custom_record(request, record_id):
    record = get_object_or_404(CustomRecord, id=record_id)
    if not user_can_access_custom_object(request.user, record.object_type, "change"):
        return HttpResponseForbidden("You do not have permission to edit records for this object.")
    if not partner_can_access_record(request.user, record.object_type.name, record, custom_object=record.object_type):
        return HttpResponseForbidden("You do not have access to this record.")
    DynamicForm = generate_dynamic_form(record.object_type)

    if request.method == "POST":
        form = DynamicForm(request.POST)
        if form.is_valid():
            content_type = ContentType.objects.get_for_model(record)
            for field_name, value in form.cleaned_data.items():
                custom_field = CustomField.objects.get(
                    name=field_name,
                    custom_object=record.object_type
                )

                cfv, created = CustomFieldValue.objects.get_or_create(
                    record=record,
                    field=custom_field,
                    defaults={
                        'content_type': content_type,
                        'object_id': record.id,
                        'value': value if value not in (None, "", []) else "---"
                    }
                )
                if custom_field.data_type == "lookup" and value:
                    value_to_store = str(value.pk)
                elif isinstance(value, bool):
                    value_to_store = str(value)
                else:
                    value_to_store = "" if value is None else str(value)

                cfv.value = value_to_store
                if not cfv.content_type_id:
                    cfv.content_type = content_type
                if not cfv.object_id:
                    cfv.object_id = record.id
                cfv.save()

                # 🔒 PROTECCIÓN CONTRA NULL / PISADO DE TRIGGERS
                if not created:
                    # Si el form no envió valor, NO pises lo existente
                    if value in (None, "", []):
                        continue

                    if custom_field.data_type == "lookup" and value:
                        cfv.value = str(value.pk)
                    elif isinstance(value, bool):
                        cfv.value = str(value)
                    else:
                        cfv.value = "" if value is None else str(value)
                    cfv.save(update_fields=["value"])
            messages.success(request, f"{record.object_type.label} record updated successfully.")

            # Actualizar usuario y fecha
            record.updated_by = request.user
            record.updated_at = timezone.now()
            record.save()
            if request.user.is_authenticated:
                bump_custom_record_list_version(request.user.id, record.object_type.name)

            # Redirigir o retornar JSON
            return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))
        else:
            messages.error(request, "Form contains errors. Please fix them.")
    return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))

@csrf_exempt
def delete_custom_record(request, record_id):
    if request.method == "POST":
        record = get_object_or_404(CustomRecord, id=record_id)
        if not user_can_access_custom_object(request.user, record.object_type, "delete"):
            return JsonResponse({"status": "error", "error": "You do not have permission to delete this record."}, status=403)
        if not partner_can_access_record(request.user, record.object_type.name, record, custom_object=record.object_type):
            return JsonResponse({"status": "error", "error": "You do not have access to this record."}, status=403)
        record.delete()
        if request.user.is_authenticated:
            bump_custom_record_list_version(request.user.id, record.object_type.name)
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

def get_document_template(request):

    try:
        company = Tenant.safe_first()
    except ObjectDoesNotExist:
        company = None

    if company is None:
        return render(request, 'document_template.html', {
            'company': None,
            'settings': None,
            'rendered_fields': [],
            'ommited_fields': [],
        })

    try:
        document_settings = QuoteDocumentSettings.objects.first()

    except ObjectDoesNotExist:
        document_settings = None

    if request.method == 'POST':
        settings = document_settings or QuoteDocumentSettings()

        #Template Style
        template_style = 'modern' if request.POST.get('template_style') == 'on' else 'classic'
        settings.template_style = template_style

        #Description Detail Level
        description_detail = 'long' if request.POST.get('description_detail_level') == 'on' else 'short'
        settings.line_description_detail_level = description_detail

        # Checkboxes
        boolean_fields = [
            'show_company_name', 'show_company_email', 'show_company_phone', 'show_company_domain',
            'show_company_logo', 'show_company_address',
            'show_account_name', 'show_account_website', 'show_account_phone',
            'show_quote_opportunity', 'show_quote_status', 'show_quote_created_at',
            'show_quote_expires_at', 'show_quote_notes',
            'show_line_discount', 'show_subscription_term', 'show_sign', 'show_quote_tax_percentage', 'show_quote_tax_amount'
        ]

        for field in boolean_fields:
            setattr(settings, field, field in request.POST)

        # Rendered & omitted fields
        rendered_fields_raw = request.POST.get("rendered_fields", "[]")
        omitted_fields_raw = request.POST.get("omitted_fields", "[]")
        try:
            settings.rendered_fields = json.loads(rendered_fields_raw)
            settings.omitted_fields = json.loads(omitted_fields_raw)
        except json.JSONDecodeError:
            print("Error decodificando los JSON\n\n")

        # Tax Switch
        tax_switch = True if request.POST.get('tax-information-switch') == 'on' else False
        settings.show_quote_tax_information = tax_switch


        # Tax Rate
        settings.quote_tax = request.POST.get("tax_rate", "")

        # Terms and conditions
        settings.terms_and_conditions = request.POST.get("terms_conditions", "")

        settings.save()

        #Update every quote tax amount
        for quote in Quote.objects.all():
            quote.update_tax()
            quote.save()
        return redirect('cpq:get_document_template')

    if document_settings is None:
        document_settings = QuoteDocumentSettings.objects.create(
            rendered_fields=default_rendered_fields_for_quote_document_settings(),
            omitted_fields=default_omitted_fields_for_quote_document_settings()
        )

    # Line items: only QuoteLine standard + QuoteLine custom fields.
    # (Prevents Product.* / Quote.* custom fields from showing in Line Item columns UI.)
    restrict_quote_document_settings_to_line_item_object_types(["QuoteLine"])
    set_custom_fields_into_quote_document_settings(["QuoteLine"])
    document_settings.refresh_from_db()

    return render(request, 'document_template.html', {
        'company': company,
        'settings': document_settings,
        'rendered_fields': document_settings.rendered_fields if document_settings else [],
        'omitted_fields': document_settings.omitted_fields if document_settings else []
    })

def business_rules_view(request):

    try:
        company = Tenant.safe_first()
    except ObjectDoesNotExist:
        company = None

    rule_types = ['general', 'validation', 'inclusion', 'exclusion']
    rules_by_type = {}

    for rule_type in rule_types:
        rules = BusinessRule.objects.filter(rule_type=rule_type).order_by("priority")
        rules_by_type[rule_type] = rules

    return render(request, 'manage_rules.html', {
        'company': company,
        "rules_by_type": rules_by_type
    })

def manage_notifications_view(request):
    email_alerts = EmailAlert.objects.all()

    # Preparamos helper para "roles" y "external"
    alerts_with_lists = []
    for alert in email_alerts:
        # Convierte roles a lista
        roles_list = []
        if alert.recipients_roles:
            roles_list = [r.strip() for r in alert.recipients_roles.split(",") if r.strip()]

        # Convierte CSV de external en lista
        external_list = []
        if alert.recipients_external:
            external_list = [e.strip() for e in alert.recipients_external.split(",") if e.strip()]

        # Inyectamos atributos extra al objeto
        alert.roles_list = roles_list
        alert.external_list = external_list

        alerts_with_lists.append(alert)

    # Filtrado por objeto

    icon_map = {
        "Lead": "person_add",
        "Account": "account_circle",
        "Opportunity": "trending_up",
        "Quote": "request_quote",
        "Subscription": "autorenew",
        "Product": "inventory_2",
        "QuoteLine": "format_list_bulleted",
        "User": "person",
        "Contract": "description",
        "Contact": "contact_mail",
        "Activity": "history",
    }

    alert_groups = []
    native_objects = dict(EmailAlert.NATIVE_OBJECT_CHOICES)

    for native_key, native_label in native_objects.items():
        alert_groups.append({
            "title": f"{native_label} Notifications",
            "icon": icon_map.get(native_key, "notifications"),
            "alerts": [a for a in alerts_with_lists if a.native_object == native_key],
            "slug": slugify(native_label) or native_key.lower(),
        })

    remaining_alerts = [
        a for a in alerts_with_lists
        if a.native_object and a.native_object not in native_objects
    ]
    for native_key in sorted({a.native_object for a in remaining_alerts}):
        alert_groups.append({
            "title": f"{native_key} Notifications",
            "icon": "notifications",
            "alerts": [a for a in remaining_alerts if a.native_object == native_key],
            "slug": slugify(native_key) or native_key.lower(),
        })

    has_any_alerts = any(group["alerts"] for group in alert_groups)
    total_alerts = sum(len(group["alerts"]) for group in alert_groups)

    return render(request, 'manage_notifications.html', {
        "alert_groups": alert_groups,
        "has_any_alerts": has_any_alerts,
        "total_alerts": total_alerts,
    })

def edit_notification(request, alert_name):
    notification = get_object_or_404(EmailAlert, name=alert_name)

    if request.method == "POST":
        post_data = request.POST.copy()

        # Convertimos los hidden inputs de chips a listas
        if 'recipients_users' in post_data and post_data['recipients_users']:
            post_data.setlist('recipients_users', post_data['recipients_users'].split(','))

        # recipients_roles lo dejamos como JSON enviado desde JS
        form = EmailAlertForm(post_data, instance=notification)

        if form.is_valid():
            notification = form.save(commit=False)

            # recipients_roles ya viene como string limpio desde clean_recipients_roles
            # recipients_external convertimos a string limpio
            notification.recipients_external = ",".join([
                e.strip() for e in form.cleaned_data.get("recipients_external", "").split(",") if e.strip()
            ])

            notification.offset_days = form.cleaned_data.get("offset_days")
            notification.scheduled_cron = form.cleaned_data.get("scheduled_cron")

            if not form.cleaned_data.get("custom_object"):
                notification.custom_object = None


            notification.updated_by = request.user

            notification.save()
            form.save_m2m()  # guarda recipients_users

            return redirect("cpq:manage_notifications")
        else:
            print("Form errors:", form.errors)

    else:
        form = EmailAlertForm(instance=notification)

    # Preparar roles para chips JS
    role_dict = dict(EmailAlert.ROLE_CHOICES)
    initial_roles = []

    if notification.recipients_roles:
        role_keys = [r.strip() for r in notification.recipients_roles.split(",") if r.strip()]
        initial_roles = [{"tag": role_dict.get(key, key), "value": key} for key in role_keys]

    context = {
        "notification": notification,
        "form": form,
        "roles_choices": EmailAlert.ROLE_CHOICES,
        "initial_roles": initial_roles,
        "users": User.objects.all(),
        "emails_external": notification.recipients_external.split(",") if notification.recipients_external else [],
    }

    return render(request, "edit_email_alert.html", context)

def delete_email_alert(request, alert_name):
    """Eliminar un EmailAlert por id"""
    alert = get_object_or_404(EmailAlert, name=alert_name)

    if request.method == "POST":
        try:
            alert.delete()
            messages.success(request, "Email alert deleted successfully.")
            return redirect("cpq:manage_notifications")  # Ajusta a tu vista/listado principal
        except Exception as e:
            print(f"Error: {e}")

    # Si alguien intenta acceder por GET directo, lo regresamos al listado
    return redirect("cpq:manage_notifications")


@require_POST
def create_notification(request):
    notification_type = request.POST.get('notification_type')  # 'account', 'lead', etc.
    when = request.POST.get('account_when')  # coincide con el name del select
    recipient = request.POST.get('account_recipient')  # coincide con el name del select

    print(f"Informacion: {notification_type}")
    print(f"When: {when}")
    print(f"Recipient: {recipient}")

    # Guardar en el modelo
    #Notification.objects.create(
    #    notification_type=notification_type,
    #    when=when,
    #    recipient=recipient,
    #    options={}  # opciones extra si las necesitas
    #)

    return JsonResponse({'status': 'ok'})

def create_business_rule(request):
    rule_id = request.GET.get("rule_id") or request.POST.get("rule_id")
    rule = None
    if rule_id:
        rule = get_object_or_404(BusinessRule, pk=rule_id)

    rule_type = rule.rule_type if rule else request.GET.get("type", "validation")
    target_type = rule.target_type if rule else request.GET.get("target_type", "quote_line")

    if request.method == "POST":
        print(f"\n\nSi llega al POST\n\n")
        form = BusinessRuleForm(request.POST, instance=rule)
        target_type = request.POST.get("target_type", target_type)
        rule_conditions = RuleCondition.objects.filter(rule=rule) if rule else None
        formset = get_rule_condition_formset(target_type, request.POST, queryset=rule_conditions)

        if form.is_valid() and formset.is_valid():
            rule = form.save(commit=False)
            rule.rule_type = rule_type
            rule.save()

            for condition in formset.save(commit=False):
                condition.rule = rule
                condition.save()

            return redirect("cpq:business_rules")
        else:
            print("Form errors:", form.errors)
            print("Formset errors:")
            for f in formset.forms:
                print(f.errors)

    else:
        form = BusinessRuleForm(instance=rule, initial={"rule_type": rule_type})
        target_type = target_type or request.GET.get("target_type", "quote_line")
        rule_conditions = RuleCondition.objects.filter(rule=rule) if rule else None
        formset = get_rule_condition_formset(target_type, queryset=rule_conditions)


    return render(request, "create_business_rule.html", {
        "form": form,
        "formset": formset,
        "rule_type": rule_type,
        "rule": rule,
        "is_edit": bool(rule),
        "QUOTE_FIELDS": mark_safe(json.dumps(QUOTE_FIELDS)), # nosec B703 B308
        "QUOTE_LINE_FIELDS": mark_safe(json.dumps(QUOTE_LINE_FIELDS)), # nosec B703 B308
        "PRODUCT_FIELDS": mark_safe(json.dumps(PRODUCT_FIELDS)), # nosec B703 B308
    })



def create_custom_record(request, object_name, user_id):

    custom_object = get_object_or_404(CustomObject, name=object_name)
    if not user_can_access_custom_object(request.user, custom_object, "add"):
        return HttpResponseForbidden("You do not have permission to create records for this object.")
    DynamicForm = generate_dynamic_form(custom_object)

    if request.method == 'POST':
        form = DynamicForm(request.POST)
        if form.is_valid():
            user = User.objects.get(id=user_id)

            # 🔥 CLAVE: UNA sola transacción para TODO el flujo
            with transaction.atomic():

                record = CustomRecord.objects.create(
                    object_type=custom_object,
                    created_by=user,
                    updated_by=user
                )

                content_type = ContentType.objects.get_for_model(record)

                for field_name, value in form.cleaned_data.items():
                    custom_field = (
                        CustomField.objects.filter(name=field_name, custom_object=custom_object)
                        .order_by("-updated_at", "-id")
                        .first()
                    )
                    if not custom_field:
                        continue

                    if custom_field.data_type == "lookup" and value:
                        value_to_store = str(value.pk)
                    elif isinstance(value, bool):
                        value_to_store = str(value)
                    else:
                        value_to_store = "" if value is None else str(value)

                    CustomFieldValue.objects.create(
                        record=record,
                        field=custom_field,
                        value=value_to_store,
                        content_type=content_type,
                        object_id=record.id
                    )

            # 👈 AQUÍ ocurre el COMMIT ÚNICO
            messages.success(
                request,
                f"{custom_object.label} record created successfully."
            )
            if request.user.is_authenticated:
                bump_custom_record_list_version(request.user.id, custom_object.name)
            return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))

    else:
        form = DynamicForm()

    lookup_options = get_lookup_data_for_form(custom_object, request.user)

    return render(request, 'custom_objects/record_form.html', {
        'form': form,
        'custom_object': custom_object,
        'lookup_options': lookup_options,
        'custom_object_perms': perms_to_template_dict(get_custom_object_perms(request.user, custom_object)),
    })



def get_lookup_data_for_form(custom_object, user=None):
    lookup_data = {}
    for field in CustomField.objects.filter(custom_object=custom_object, data_type="lookup"):
        try:
            model = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)
            queryset = None

            if model:
                queryset = model.objects.all()
                if user:
                    queryset = apply_partner_access_filter(user, model.__name__, queryset)
            elif field.lookup_model:
                try:
                    target_co = CustomObject.objects.get(name=field.lookup_model)
                    queryset = CustomRecord.objects.filter(object_type=target_co)
                    if user:
                        queryset = apply_partner_access_filter(
                            user,
                            target_co.name,
                            queryset,
                            custom_object=target_co,
                        )
                except CustomObject.DoesNotExist:
                    queryset = None

            if queryset is None:
                lookup_data[field.name] = []
                continue

            lookup_data[field.name] = [{"id": i.id, "label": str(i)} for i in queryset]
        except Exception:
            lookup_data[field.name] = []
    return lookup_data

def search_accounts(request):
    q = request.GET.get("q", "")
    results = []

    if q:
        matches = Account.objects.filter(name__icontains=q)[:20]
        results = [{"id": acc.id, "name": acc.name} for acc in matches]

    return JsonResponse({"results": results})

@login_required
def usage_dashboard(request):
    current_tenant = Tenant.safe_first()
    usage_logs = ActionUsage.objects.all()

    tenants_usage = TenantUsageReport.objects.select_related('tenant')
    tenant_storage_usage = _calculate_tenant_storage_usage(current_tenant)


    # ---- Total Actions by Month ----
    actions_by_month = (
        usage_logs
        .annotate(month=TruncMonth("timestamp"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )

    # ---- Top 5 Actions (Overall) ----
    top_actions = (
        usage_logs
        .values("action")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )

    # ---- Total Actions by User ----
    actions_by_user = (
        usage_logs
        .values("user__username")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    # ---- Overflow Metric (Current Month Only) ----
    start_of_month = make_aware(datetime(now().year, now().month, 1))
    monthly_count = usage_logs.filter(timestamp__gte=start_of_month).count()
    action_limit = current_tenant.actions_limit or 1000
    overflow = monthly_count - action_limit

    actions_by_month_serialized = [
        {
            "month": entry["month"].strftime("%Y-%m"),
            "total": entry["total"]
        }
        for entry in actions_by_month
    ]

    actions_by_user_serialized = [
        {
            "user": escape(entry.get("user__username") or "Unknown"),
            "total": entry["count"]
        }
        for entry in actions_by_user
    ]


    storage_info = tenant_storage_usage or {}

    context = {
        "tenant": current_tenant,
        "actions_by_month_json": json.dumps(actions_by_month_serialized),
        "actions_by_user_json": json.dumps(actions_by_user_serialized),
        "top_actions": top_actions,
        "monthly_count": monthly_count,
        "limit": action_limit,
        "overflow": max(0, overflow),
        "tenants_usage": tenants_usage,
        "storage_mb": storage_info.get("storage_mb", 0.0),
        "records_mb": storage_info.get("records_mb", 0.0),
        "files_mb": storage_info.get("files_mb", 0.0),
        "records_percent": storage_info.get("records_percent", 0.0),
        "documents_percent": storage_info.get("documents_percent", 0.0),
    }

    return render(request, "usage.html", context)


@login_required
def usage_documents(request):
    current_tenant = Tenant.safe_first()
    documents = []
    total_size = 0

    if current_tenant:
        raw_documents = _list_r2_objects(current_tenant)
        for item in raw_documents:
            size_bytes = item.get("size", 0) or 0
            item["size_mb"] = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0.0
        documents = raw_documents
        total_size = sum(item.get("size", 0) for item in documents)

    if request.method == "POST":
        action = request.POST.get("action")
        keys = []

        if action == "delete_all":
            keys = [item.get("key") for item in documents if item.get("key")]
        elif action == "delete_selected":
            keys = request.POST.getlist("keys")
        elif action == "delete_single":
            key = request.POST.get("key")
            if key:
                keys = [key]

        if keys:
            success, message_text = _delete_r2_objects(current_tenant, keys)
            if success:
                messages.success(request, message_text)
            else:
                messages.error(request, message_text)
        else:
            messages.warning(request, "No documents selected for deletion.")

        return redirect("cpq:usage_documents")

    total_mb = round(total_size / (1024 * 1024), 2) if total_size else 0.0

    context = {
        "tenant": current_tenant,
        "documents": documents,
        "documents_total_bytes": total_size,
        "documents_total_mb": total_mb,
    }

    return render(request, "usage_documents.html", context)


@login_required
def billing_view(request):
    current_tenant = Tenant.safe_first()
    publishable_key = settings.STRIPE_PUBLISHABLE_KEY or ""

    context = {
        "tenant": current_tenant,
        "stripe_publishable_key": publishable_key,
    }

    return render(request, "billing.html", context)


# ------------------------------------------------------------------
# Picklist Values API (admin-side)
# ------------------------------------------------------------------
@csrf_exempt
@login_required
def picklist_values_api(request):
    """
    Simple JSON API to list/create/update/delete picklist values.
    Requires query params: object_name, field_name.
    """
    object_name = request.GET.get("object_name") or request.POST.get("object_name")
    field_name = request.GET.get("field_name") or request.POST.get("field_name")

    if not object_name or not field_name:
        return JsonResponse({"error": "object_name and field_name are required"}, status=400)

    if request.method == "GET":
        values = (
            PicklistValue.objects.filter(object_name=object_name, field_name=field_name)
            .order_by("sort_order", "key")
        )
        data = [
            {
                "id": val.id,
                "key": val.key,
                "label": val.label,
                "active": val.active,
                "is_default": val.is_default,
                "sort_order": val.sort_order,
            }
            for val in values
        ]
        return JsonResponse({"values": data})

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if request.method == "POST":
        val_id = payload.get("id")
        key = (payload.get("key") or "").strip()
        label = (payload.get("label") or "").strip()
        active = bool(payload.get("active", True))
        is_default = bool(payload.get("is_default", False))
        sort_order = payload.get("sort_order")
        try:
            sort_order = int(sort_order) if sort_order is not None else 0
        except (TypeError, ValueError):
            sort_order = 0

        if not key or not label:
            return JsonResponse({"error": "key and label are required"}, status=400)

        if is_default:
            PicklistValue.objects.filter(object_name=object_name, field_name=field_name).update(is_default=False)

        if val_id:
            val = PicklistValue.objects.filter(id=val_id, object_name=object_name, field_name=field_name).first()
            if not val:
                return JsonResponse({"error": "Picklist value not found"}, status=404)
            val.key = key
            val.label = label
            val.active = active
            val.is_default = is_default
            val.sort_order = sort_order
            val.save()
        else:
            val = PicklistValue.objects.create(
                object_name=object_name,
                field_name=field_name,
                key=key,
                label=label,
                active=active,
                is_default=is_default,
                sort_order=sort_order,
            )

        return JsonResponse({"success": True, "id": val.id})

    if request.method == "DELETE":
        val_id = payload.get("id")
        if not val_id:
            return JsonResponse({"error": "id is required to delete"}, status=400)
        PicklistValue.objects.filter(id=val_id, object_name=object_name, field_name=field_name).delete()
        return JsonResponse({"success": True})

    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@require_POST
def billing_create_setup_intent(request):
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PUBLISHABLE_KEY:
        return JsonResponse({"error": "Stripe is not configured."}, status=400)

    stripe.api_key = settings.STRIPE_SECRET_KEY

    tenant = Tenant.safe_first()
    metadata = {}
    if tenant:
        if tenant.tenant_id:
            metadata["tenant_id"] = tenant.tenant_id
        if tenant.name:
            metadata["tenant_name"] = tenant.name

    try:
        intent = stripe.SetupIntent.create(
            payment_method_types=["card"],
            metadata=metadata or None,
        )
        return JsonResponse({"clientSecret": intent.client_secret})
    except stripe.error.StripeError as exc:
        logging.error("Stripe error creating setup intent: %s", exc)
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Unexpected error creating setup intent")
        return JsonResponse({"error": "Unexpected error creating setup intent."}, status=500)
