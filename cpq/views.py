from django.shortcuts import render, get_object_or_404
from .models import Product, Quote

def product_list(request):
    """Fetch all products and display them in a table."""
    products = Product.objects.all()
    return render(request, "products.html", {"products": products})

def product_detail(request, product_id):
    """View detailed product information."""
    product = get_object_or_404(Product, id=product_id)
    return render(request, "product_detail.html", {"product": product})

def settings_view(request):
    return render(request, "cpq/settings.html") 

def quotes_view(request):
    """Fix infinite recursion by ensuring only a single call."""
    quotes = Quote.objects.select_related('opportunity__account').all()
    return render(request, "cpq/quotes.html", {"quotes": quotes})

