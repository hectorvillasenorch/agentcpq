from django.urls import path
<<<<<<< HEAD
from .views import quotes_view, settings_view, product_list, product_detail,field_mapping_view,save_field_mappings,set_primary_quote, custom_fields_view,create_custom_field, get_company_information, create_custom_field , create_custom_object, get_document_template
=======
from .views import quotes_view, settings_view, product_list, product_detail,field_mapping_view,save_field_mappings,set_primary_quote, custom_fields_view,create_custom_field, get_company_information, get_document_template, business_rules_view
from .views import create_business_rule
create_custom_field
>>>>>>> 4facfc273f72ae0f8422e158434ce915e6a459d3
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
    
    # ADMIN URLS
    path("admin/custom-fields/", custom_fields_view, name="custom_fields"),
    path('admin/custom-fields/create/', create_custom_field, name='create_custom_field'),
    path('admin/company-information', get_company_information, name='get_company_information'),
<<<<<<< HEAD
    path('admin/custom-object/create/', create_custom_object, name='create_custom_object'),
    path('admin/document-templates', get_document_template, name='get_document_template'),
=======
    path('admin/manage-document', get_document_template, name='get_document_template'),
    path('admin/manage-rules', business_rules_view, name='business_rules'),
    path("admin/manage-rules/create/", create_business_rule, name="create_business_rule"),
>>>>>>> 4facfc273f72ae0f8422e158434ce915e6a459d3
    path('quotes/<int:quote_id>/set-primary/', set_primary_quote, name='set_primary_quote')
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

