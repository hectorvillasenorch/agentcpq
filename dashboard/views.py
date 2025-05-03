from django.shortcuts import render
from cpq.models import Product, Quote  # ✅ Importing models, NOT views
from salesforce.models import SalesforceToken
from agents.models import ChatSession
from django.contrib.auth.models import User
from agents.models import ChatSession, ChatMessage

# def dashboard(request):
#     """Render different views in the dashboard based on the selected view."""
#     view = request.GET.get("view", "agents")
    
#     # ✅ Load relevant data based on view selection
#     products = Product.objects.all() if view == "products" else None
#     quotes = Quote.objects.select_related("opportunity__account").all() if view == "quotes" else None
    
#     is_authenticated = SalesforceToken.objects.exists()
#     is_setup = view == "setup"

#     user = User.objects.get(username="hvillasenor")  # Replace with request.user if available
#     chat_sessions = ChatSession.objects.filter(user=user).order_by("-created_at")

#     return render(request, "dashboard.html", {
#         "products": products,
#         "quotes": quotes,
#         "is_setup": is_setup,
#         "is_authenticated": is_authenticated, 
#         "chat_sessions": chat_sessions, 
#     })

# def setup_view(request):
#     """Renders the Setup page"""
#     return render(request, "setup.html")

def dashboard(request):
    view = request.GET.get("view", "agents")
    session_id = request.GET.get("session_id")

    # Products and quotes context
    products = Product.objects.all() if view == "products" else None
    quotes = Quote.objects.select_related("opportunity__account").all() if view == "quotes" else None

    is_authenticated = SalesforceToken.objects.exists()
    is_setup = view == "setup"

    user = User.objects.get(username="hvillasenor")  # Replace with request.user if available
    chat_sessions = ChatSession.objects.filter(user=user).order_by("-created_at")

    # ✅ Load messages if a session is selected
    chat_messages = []
    if session_id:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id, user=user)
            chat_messages = ChatMessage.objects.filter(session=chat_session).order_by("timestamp")
        except ChatSession.DoesNotExist:
            pass

    return render(request, "dashboard.html", {
        "products": products,
        "quotes": quotes,
        "is_setup": is_setup,
        "is_authenticated": is_authenticated, 
        "chat_sessions": chat_sessions, 
        "chat_messages": chat_messages,
        "selected_session_id": session_id,
    })