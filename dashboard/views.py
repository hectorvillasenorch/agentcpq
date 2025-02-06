from django.shortcuts import render
from cpq.models import Product, Quote  # ✅ Importing models, NOT views

def dashboard(request):
    """Render different views in the dashboard based on the selected view."""
    view = request.GET.get("view", "agents")
    
    # ✅ Load relevant data based on view selection
    products = Product.objects.all() if view == "products" else None
    quotes = Quote.objects.select_related("opportunity__account").all() if view == "quotes" else None

    return render(request, "dashboard.html", {
        "products": products,
        "quotes": quotes,  # ✅ Pass Quotes data
    })