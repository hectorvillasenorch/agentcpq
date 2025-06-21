from venv import logger
from django.shortcuts import render
from cpq.models import Product, Quote,QuoteLine, CustomObject, CustomField, CustomFieldValue, CustomRecord,Account # ✅ Importing models, NOT views
from cpq.views import set_primary_quote
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from collections import defaultdict
from django.db.models import Prefetch
from django.contrib.contenttypes.models import ContentType

def dashboard(request):
    view = request.GET.get("view", "agents")
    session_id = request.GET.get("session_id")

    products = Product.objects.all() if view == "products" else None

    quotes = Quote.objects.select_related("opportunity__account").prefetch_related(
        Prefetch("quote_lines", queryset=QuoteLine.objects.select_related("product"), to_attr="lines")
    )

    grouped_quotes = defaultdict(list)
    for quote in quotes:
        grouped_quotes[quote.opportunity].append(quote)

    is_authenticated = SalesforceToken.objects.exists()
    is_setup = view == "setup"

    user = User.objects.get(username="admin")  # or request.user
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

    custom_list_view = None
    try:
        custom_object = CustomObject.objects.get(name=view)
        fields = CustomField.objects.filter(custom_object=custom_object)
        records = CustomRecord.objects.all().order_by("-created_at")

        logger.info("🧠 records:", records)

        content_type = ContentType.objects.get_for_model(CustomRecord)
        record_data = []

        for record in records:
            field_values = {}
            for field in fields:
                value_obj = CustomFieldValue.objects.filter(
                    field=field,
                    content_type=content_type,
                    object_id=record.id
                ).first()
                field_values[field.name] = value_obj.value if value_obj else ''
            record_data.append({
                "id": record.id,
                "created_at": record.created_at,
                "fields": field_values
            })

        # ✅ Group records by account_id__c
        grouped = defaultdict(list)
        for rec in record_data:
            acc_id = rec["fields"].get("account_id__c")
            grouped[acc_id].append(rec)

        groups = []
        for acc_id, records in grouped.items():
            total = sum(
                float(r["fields"].get("payment_amount__c", 0)) for r in records
            )
            try:
                account = Account.objects.get(id=acc_id)
            except (Account.DoesNotExist, ValueError, TypeError):
                account = None

            groups.append({
                "account": account,
                "records": records,
                "total_amount": total,
            })

        custom_list_view = {
            "label": custom_object.label,
            "fields": fields,
            "records": record_data,
            "groups": groups,
            "is_grouped_by_account": True,
        }
    except CustomObject.DoesNotExist:
        pass

    return render(request, "dashboard.html", {
        "products": products,
        "grouped_quotes": grouped_quotes.items(),
        "is_setup": is_setup,
        "is_authenticated": is_authenticated,
        "hubspot_connected": hubspot_connected,
        "chat_sessions": chat_sessions,
        "chat_messages": chat_messages,
        "selected_session_id": session_id,
        "custom_list_view": custom_list_view,
})
