from django.urls import path
from .views import quotes_view, settings_view, product_list, product_detail,field_mapping_view,save_field_mappings,set_primary_quote, custom_fields_view,create_custom_field, get_company_information
create_custom_field
from hubspot.views import get_hubspot_schema

from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

app_name = "cpq"  # ✅ Namespacing the app

urlpatterns = [
    path('', RedirectView.as_view(url='dashboard/')),  # <--- redirige '/' a '/dashboard/'
    path('quotes/', quotes_view, name='quotes'),
    path('settings/', settings_view, name='settings'),
    path("products/", product_list, name="product_list"),
    path("products/<int:product_id>/", product_detail, name="product_detail"),
    path("field-mapping/", field_mapping_view, name="field_mapping"),
    path("save-field-mappings/", save_field_mappings, name="save_field_mappings"),  # ✅ Add this line
    path("hubspot/schema/", get_hubspot_schema, name="get_hubspot_schema"),
    path('quotes/<int:quote_id>/set-primary/', set_primary_quote, name='set_primary_quote'),
    path("admin/custom-fields/", custom_fields_view, name="custom_fields"),
    path('admin/custom-fields/create/', create_custom_field, name='create_custom_field'),
    path('admin/company-information', get_company_information, name='get_company_information'),
    path('quotes/<int:quote_id>/set-primary/', set_primary_quote, name='set_primary_quote')
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

