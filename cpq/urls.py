from django.urls import path
from .views import quotes_view, settings_view, product_list, product_detail,field_mapping_view,save_field_mappings,set_primary_quote
from hubspot.views import get_hubspot_schema

app_name = "cpq"  # ✅ Namespacing the app

urlpatterns = [
    path('quotes/', quotes_view, name='quotes'),
    path('settings/', settings_view, name='settings'),
    path("products/", product_list, name="product_list"),
    path("products/<int:product_id>/", product_detail, name="product_detail"),
    path("field-mapping/", field_mapping_view, name="field_mapping"),
    path("save-field-mappings/", save_field_mappings, name="save_field_mappings"),  # ✅ Add this line
    path("hubspot/schema/", get_hubspot_schema, name="get_hubspot_schema"),
    path('quotes/<int:quote_id>/set-primary/', set_primary_quote, name='set_primary_quote')
]