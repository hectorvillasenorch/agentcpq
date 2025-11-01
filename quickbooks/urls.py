from django.urls import path

from . import views


app_name = "quickbooks"


urlpatterns = [
    path("connect/", views.quickbooks_connect, name="quickbooks_connect"),
    path("callback/", views.quickbooks_callback, name="quickbooks_callback"),
    path("sync-products/", views.sync_quickbooks_products, name="sync_quickbooks_products"),
    path(
        "invoices/<int:quote_id>/",
        views.create_invoice_from_quote,
        name="create_invoice_from_quote",
    ),
    path(
        "internal/invoices/<int:quote_id>/",
        views.create_invoice_from_quote_internal,
        name="create_invoice_from_quote_internal",
    ),
]
