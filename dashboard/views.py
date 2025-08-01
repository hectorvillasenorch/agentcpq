from django.apps import apps
from django.shortcuts import render, get_object_or_404, redirect
from cpq.models import Product, Quote,QuoteLine, CustomObject, CustomField, CustomFieldValue, CustomRecord,Account, ActionUsage, Tenant, Option
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
from django.http import HttpResponseForbidden
from django.db.models import Count
from django.utils.timezone import now
from django.db.models.functions import TruncMonth
from django.contrib.auth.views import PasswordResetView
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

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
    
    products = None
    options = None
    bundles = None
    product_data = []
    account_data = []
    bundle_data = []

    if view == "products":
        products = Product.objects.all().order_by('name')
        options = Option.objects.all()
        bundles = Product.objects.filter(is_bundle=True).order_by('name')
        
        for product in products:
            product.bundle_options = [opt for opt in options if opt.parent_product == product]
    
    elif view == "agents":
        products = Product.objects.filter(is_bundle=False).order_by('name')
        options = Option.objects.all()
        bundles = Product.objects.filter(is_bundle=True).order_by('name')

        accounts = Account.objects.all().order_by('name')

        product_data = list(products.values('id', 'name', 'sku', 'family', 'price', 'description', 'is_subscription', 'term'))
        account_data = list(accounts.values('id', 'name', 'industry', 'website', 'phone'))

        bundle_data = []
        for bundle in bundles:
            related_options = [opt for opt in options if opt.parent_product_id == bundle.id]
            component_list = [
                {
                    'name': opt.product_option.name,
                    'sku': opt.product_option.sku,
                    'price': float(opt.product_option.price or 0),
                    'quantity': opt.quantity,
                }
                for opt in related_options
            ]

            bundle_data.append({
                'id': bundle.id,
                'name': bundle.name,
                'sku': bundle.sku,
                'family': bundle.family,
                'price': float(bundle.price or 0),
                'description': bundle.description,
                'is_subscription': bundle.is_subscription,
                'term': bundle.term,
                'components': component_list,
            })

    custom_objects = CustomObject.objects.all()

    quotes = Quote.objects.select_related("opportunity__account").prefetch_related(
        Prefetch("quote_lines", queryset=QuoteLine.objects.select_related("product"), to_attr="lines")
    )

    grouped_quotes = defaultdict(list)
    for quote in quotes:
        grouped_quotes[quote.opportunity].append(quote)

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
        "product_data": product_data,
        "options": options,
        "bundles": bundles,
        "bundle_data": bundle_data,
        "accounts": accounts,
        "account_data": account_data,
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

class CustomPasswordResetView(PasswordResetView):
    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None):

        subject = render_to_string(subject_template_name, context).strip()
        body = render_to_string(email_template_name, context)

        email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])

        if html_email_template_name:
            html_email = render_to_string(html_email_template_name, context)
            email_message.attach_alternative(html_email, 'text/html')

        email_message.send()