from django.shortcuts import render
from cpq.models import Product, Quote  # ✅ Importing models, NOT views
from salesforce.models import SalesforceToken

def dashboard(request):
    """Render different views in the dashboard based on the selected view."""
    view = request.GET.get("view", "agents")
    
    # ✅ Load relevant data based on view selection
    products = Product.objects.all() if view == "products" else None
    quotes = Quote.objects.select_related("opportunity__account").all() if view == "quotes" else None

    # ✅ Check if Salesforce is authenticated
    is_authenticated = SalesforceToken.objects.exists()

    # ✅ Handle "Setup" View
    is_setup = view == "setup"

    return render(request, "dashboard.html", {
        "products": products,
        "quotes": quotes,
        "is_setup": is_setup,  # ✅ Used to determine if we should show setup content
        "is_authenticated": is_authenticated,  # ✅ Pass Salesforce authentication status
    })

def setup_view(request):
    """Renders the Setup page"""
    return render(request, "setup.html")