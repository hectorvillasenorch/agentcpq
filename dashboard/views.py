from django.apps import apps
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from cpq.models import Product, Quote, CustomObject, CustomField, CustomFieldValue, CustomRecord, Account, ActionUsage, Tenant, TenantUsageLog, Option
from cpq.views import set_primary_quote, build_account_quote_hierarchy_for_user
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from quickbooks.models import QuickbooksToken
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from cpq.forms import  generate_dynamic_form
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.db.models import Count
from django.utils.timezone import now
from django.db.models.functions import TruncMonth
import hmac
import hashlib
from datetime import date
from django.views.decorators.http import require_GET
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Sum
from cpq.models import Tenant, ActionUsage, TenantUsageReport
from django.utils.dateparse import parse_datetime
import logging
logger = logging.getLogger(__name__)
from datetime import datetime, timezone as dt_timezone
from django.contrib.auth.views import PasswordResetView
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
import smtplib
from django.template.loader import render_to_string
import re
from .forms import SignupForm
from django.contrib.auth.views import LogoutView


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

@login_required
def dashboard(request):
    view = request.GET.get("view", "agents")
    object_name = request.GET.get("object_name")
    session_id = request.GET.get("session_id")
    user = request.user
    accounts = get_user_accounts(user)

    custom_object = None
    form = None

    new_chat = request.GET.get("new_chat") == "true"
    if new_chat:
        request.session.pop("session_data", None)
        session_id = None

    if object_name:
        custom_object = get_object_or_404(CustomObject, name=object_name)
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


    if view == "setup" and not user.is_staff:
        return HttpResponseForbidden("You do not have access to the setup view.")
    
    products = None
    options = None
    bundles = None

    if view == "products":
        product_queryset = Product.objects.all()
        if not user.is_superuser:
            product_queryset = product_queryset.filter(created_by=user)

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

    custom_objects = CustomObject.objects.all()

    # Fetch only this user's account/opportunity/quote hierarchy
    account_groups = get_grouped_user_quotes(user)
    print("📦 Account groups:", account_groups)

    is_authenticated = SalesforceToken.objects.exists()
    is_setup = view == "setup"
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

    records_custom_object, field_values_by_record = get_values_by_record(custom_object)
    lookup_options = get_lookup_data_for_form(custom_object)


    return render(request, "dashboard.html", {
        "products": products,
        "options": options,
        "bundles": bundles,
        "account_groups": account_groups,
        "is_setup": is_setup,
        "is_authenticated": is_authenticated,
        "hubspot_connected": hubspot_connected,
        "quickbooks_connected": quickbooks_connected,
        "chat_sessions": chat_sessions,
        "chat_messages": chat_messages,
        "selected_session_id": session_id,
        "custom_object": custom_object,
        "custom_objects": custom_objects,
        "next_identifier": next_identifier,
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
    def _send_welcome_email(new_user):
        if not new_user.email:
            logger.debug("Signup welcome email skipped: no email for user %s", new_user.pk)
            return

        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None)
        if not from_email:
            logger.debug(
                "Signup welcome email skipped: no from_email configured (user=%s)",
                new_user.pk,
            )
            return

        first_name = (new_user.first_name or new_user.username).replace('\xa0', ' ').strip()
        last_name = (new_user.last_name or '').replace('\xa0', ' ').strip()
        subject = "Welcome to AgentCPQ"
        dashboard_url = request.build_absolute_uri(reverse('dashboard'))
        message = render_to_string(
            'auth/welcome_email.html',
            {
                'first_name': first_name,
                'last_name': last_name,
                'username': new_user.username,
                'dashboard_url': dashboard_url,
                'current_year': datetime.now().year,
            },
        )

        reply_to = getattr(settings, 'DEFAULT_REPLY_TO', None) or from_email
        email = EmailMessage(subject, message, from_email, [new_user.email], reply_to=[reply_to])
        email.encoding = 'utf-8'
        email.content_subtype = 'html'
        email.extra_headers = email.extra_headers or {}
        email.extra_headers.setdefault('Content-Transfer-Encoding', '8bit')

        try:
            sent_count = email.send(fail_silently=True)
            logger.debug(
                "Signup welcome email attempted: user=%s email=%s sent=%s",
                new_user.pk,
                new_user.email,
                bool(sent_count),
            )
        except UnicodeEncodeError:
            logger.exception(
                "Signup welcome email failed due to Unicode error (user=%s, email=%s)",
                new_user.pk,
                new_user.email,
            )
        except smtplib.SMTPException:
            logger.exception(
                "Signup welcome email SMTP failure (user=%s, email=%s)",
                new_user.pk,
                new_user.email,
            )

    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            _send_welcome_email(user)
            login(request, user)
            return redirect('dashboard')
    else:
        form = SignupForm()

    return render(request, 'auth/signup.html', {'form': form})


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