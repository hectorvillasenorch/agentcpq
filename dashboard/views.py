from django.shortcuts import render
from cpq.models import Product, Quote  # ✅ Importing models, NOT views
from salesforce.models import SalesforceToken
from agents.models import ChatSession
from django.contrib.auth.models import User

def dashboard(request):
    """Render different views in the dashboard based on the selected view."""
    view = request.GET.get("view", "agents")
    
    # ✅ Load relevant data based on view selection
    products = Product.objects.all() if view == "products" else None
    quotes = Quote.objects.select_related("opportunity__account").all() if view == "quotes" else None
    
    is_authenticated = SalesforceToken.objects.exists()
    is_setup = view == "setup"

    user = User.objects.get(username="hvillasenor")  # Replace with request.user if available
    chat_sessions = ChatSession.objects.filter(user=user).order_by("-created_at")

    return render(request, "dashboard.html", {
        "products": products,
        "quotes": quotes,
        "is_setup": is_setup,
        "is_authenticated": is_authenticated, 
        "chat_sessions": chat_sessions, 
    })

def setup_view(request):
    """Renders the Setup page"""
    return render(request, "setup.html")