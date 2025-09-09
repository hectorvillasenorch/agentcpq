from django.http import HttpResponse
from django.urls import path
from .views import quotes_view, settings_view, product_list, product_detail,field_mapping_view,save_field_mappings,set_primary_quote, custom_fields_view,create_custom_field, get_company_information, create_custom_object, get_document_template, business_rules_view
from .views import create_notification, create_custom_record, search_accounts,create_custom_field, usage_dashboard, edit_custom_object, edit_custom_field, delete_custom_field, delete_custom_object, manage_notifications_view, edit_notification, delete_email_alert
from hubspot.views import get_hubspot_schema
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from . import views

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
    path('records/create/<str:object_name>/<str:user_id>', create_custom_record, name='create_custom_record'),
    path('records/success/', lambda r: HttpResponse("Record created."), name='custom_record_success'),
    path("search/accounts/", search_accounts, name="search_accounts"),

    #EDIT CUSTOM RECORD
    path('records/<int:record_id>/form/', views.get_custom_record_form, name='get_custom_record_form'),
    path('records/<int:record_id>/edit/', views.edit_custom_record, name='edit_custom_record'),
    path('records/<int:record_id>/delete/', views.delete_custom_record, name='delete_custom_record'),

    # ADMIN URLS
    path("admin/custom-fields/", custom_fields_view, name="custom_fields"),
    path('admin/custom-fields/create/<str:object_name>/', create_custom_field, name='create_custom_field'),
    path('admin/custom-fields/edit/<str:field_id>/', edit_custom_field, name='edit_custom_field'),
    path('admin/custom-fields/delete/<str:field_id>/', delete_custom_field, name='delete_custom_field'),
    path('admin/company-information', get_company_information, name='get_company_information'),
    path('admin/custom-object/create/<str:object_name>/', create_custom_object, name='create_custom_object'),
    path('admin/custom-fields/edit-custom-object/<str:object_name>/', edit_custom_object, name='edit_custom_object'),
    path('admin/custom-fields/delete-custom-object/<str:object_name>', delete_custom_object, name='delete_custom_object'),
    path('admin/manage-document', get_document_template, name='get_document_template'),
    path('admin/manage-rules', business_rules_view, name='business_rules'),
    path('admin/manage-notifications', manage_notifications_view, name='manage_notifications'),
    path('admin/manage-notifications/edit/<str:alert_name>/', edit_notification, name='edit_notification'),
    path("admin/manage-notifications/delete/<str:alert_name>/", delete_email_alert, name="delete_email_alert"),
    path('admin/create-notification', create_notification, name='create_notification'),
    #path("admin/manage-rules/create/", create_business_rule, name="create_business_rule"),
    path('quotes/<int:quote_id>/set-primary/', set_primary_quote, name='set_primary_quote'),
    path('admin/usage/', usage_dashboard, name='usage_dashboard'),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
