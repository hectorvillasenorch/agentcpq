from django.urls import path
from .views import quotes_view, settings_view, product_list, product_detail

app_name = "cpq"  # ✅ Namespacing the app

urlpatterns = [
    path('quotes/', quotes_view, name='quotes'),
    path('settings/', settings_view, name='settings'),
    path("products/", product_list, name="product_list"),
    path("products/<int:product_id>/", product_detail, name="product_detail"),
]