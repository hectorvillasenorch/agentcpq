from django.apps import apps
from django.shortcuts import render, get_object_or_404, redirect
from cpq.models import Product, Quote,QuoteLine, CustomObject, CustomField, CustomFieldValue, CustomRecord,Account, ActionUsage, Tenant
from cpq.views import set_primary_quote
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from cpq.forms import  generate_dynamic_form
from django.db.models import Prefetch
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.db.models import Count
from django.utils.timezone import now
from django.db.models.functions import TruncMonth

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

    custom_objects = CustomObject.objects.all()

    # Fetch only this user's quotes, grouped by opportunity
    grouped_quotes = get_grouped_user_quotes(request)

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


def get_grouped_user_quotes(request):
    user = request.user

    # Base queryset: if superuser, all quotes; otherwise only quotes
    # whose opportunity.account.owner is this user
    if user.is_superuser:
        base_qs = Quote.objects.all()
    else:
        base_qs = Quote.objects.filter(
            opportunity__account__owner=user
        )

    # Eager-load opportunity → account and quote_lines → product,
    # and stash lines in a .lines attribute
    quotes = base_qs.select_related(
        "opportunity__account"
    ).prefetch_related(
        Prefetch(
            "quote_lines",
            queryset=QuoteLine.objects.select_related("product"),
            to_attr="lines"
        )
    )

    # Group by opportunity
    grouped_quotes = {}
    for quote in quotes:
        grouped_quotes.setdefault(quote.opportunity, []).append(quote)

    return grouped_quotes