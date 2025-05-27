from django.shortcuts import render
from cpq.models import Product, Quote,QuoteLine # ✅ Importing models, NOT views
from cpq.views import set_primary_quote
from salesforce.models import SalesforceToken
from hubspot.models import HubspotToken
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage
from django.utils.timezone import now
import requests
from collections import defaultdict
from django.db.models import Prefetch

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

    # ✅ Load chat messages for a selected session
    chat_messages = []
    if session_id:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id, user=user)
            chat_messages = ChatMessage.objects.filter(session=chat_session).order_by("timestamp")
        except ChatSession.DoesNotExist:
            pass

    # ✅ HubSpot connection status check
    hubspot_connected = False
    try:
        token = HubspotToken.objects.get(user_id="default")  # or user.id if multi-user
        if token.expires_at and token.expires_at > now():
            headers = {
                "Authorization": f"Bearer {token.access_token}"
            }
            res = requests.get("https://api.hubapi.com/integrations/v1/me", headers=headers)
            if res.status_code == 200:
                hubspot_connected = True
    except HubspotToken.DoesNotExist:
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
    })