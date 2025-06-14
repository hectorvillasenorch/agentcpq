from django.shortcuts import render, get_object_or_404, redirect
from .models import Product, SystemFieldMapping,Quote,CustomField,Tenant,QuoteDocumentSettings,CustomObject
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt 
from django.apps import apps
from salesforce.models import SalesforceToken
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ObjectDoesNotExist
import json
from .forms import CustomFieldForm, CustomObjectForm

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
    """Render the list of Quotes."""
    
    quotes = Quote.objects.select_related("opportunity__account").all()
    
    is_authenticated = SalesforceToken.objects.exists()

    return render(request, "quotes.html", {
        "quotes": quotes,
        "is_authenticated": is_authenticated,  # ✅ Used to show Sync button conditionally
    })

MODEL_CHOICES = {
    "Opportunity": "Opportunity",  # ✅ Use class name, not table name
    "Quote": "Quote",
    "QuoteLine": "QuoteLine",
    "Product": "Product",
    "Account": "Account",
    "Contact": "Contact",
}

def field_mapping_view(request):
    """Dynamically fetch schema fields for the selected CRM and object type."""

    # ✅ Get the selected CRM and Object Type from request
    selected_crm = request.GET.get("crm", "AgentCPQ")  
    selected_model = request.GET.get("object_type", "Opportunity")

    if selected_model not in MODEL_CHOICES:
        return JsonResponse({"error": "Invalid object type"}, status=400)
    
    print("🔍 >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> selected_model =", selected_model)

    # ✅ Get the correct model class dynamically
    ModelClass = apps.get_model('cpq', MODEL_CHOICES[selected_model])
    local_fields = [field.name for field in ModelClass._meta.fields]  # ✅ Get all fields

    # ✅ Fetch only mappings that match the selected CRM and Object Type
    mappings = {
        m.local_field: m.crm_field
        for m in SystemFieldMapping.objects.filter(crm=selected_crm, field_type=selected_model)
    }
    alias_map = {
        "Deal": "Opportunity",
        "Company": "Account",
        "Contact": "Contact",
        "Product": "Product",
        "Opportunity": "Opportunity",
        "Account": "Account",
        "line_items": "line_items",
    }
    selected_model_raw = request.GET.get("object_type", "Opportunity")
    selected_model = alias_map.get(selected_model_raw, selected_model_raw)

    return render(request, "field_mapping.html", {
        "local_fields": json.dumps(local_fields, cls=DjangoJSONEncoder),
        "mappings": mappings,  # ✅ Raw dict for get_item filter
        "mappings_json": json.dumps(mappings, cls=DjangoJSONEncoder),  # ✅ For JS
        "selected_crm": selected_crm,
        "selected_model": selected_model,
        "available_models": MODEL_CHOICES.keys(),
    })


@csrf_exempt
def save_field_mappings(request):
    """Save field mappings for a selected CRM and object type."""
    if request.method == "POST":
        crm = request.POST.get("crm", "AgentCPQ")  # ✅ Capture CRM selection
        object_type = request.POST.get("object_type", "Opportunity")  # ✅ Capture object type selection

        updated_count = 0
        for key, value in request.POST.items():
            if key in ["crm", "object_type"]:
                continue  # ✅ Skip non-mapping fields

            crm_field = value.strip()
            if crm_field:  # ✅ Ensure it's not empty
                mapping, created = SystemFieldMapping.objects.update_or_create(
                    crm=crm,  
                    local_field=key,  
                    field_type=object_type,  # ✅ Ensure object type is saved correctly
                    defaults={"crm_field": crm_field}
                )
                if created:
                    updated_count += 1

        return JsonResponse({
            "success": True,
            "message": f"Updated {updated_count} mappings for {crm} - {object_type}."
        })

    return JsonResponse({"success": False, "message": "Invalid request."})


@csrf_exempt
def set_primary_quote(request, quote_id):
    if request.method == "POST":
        try:
            quote = Quote.objects.select_related("opportunity").get(id=quote_id)
            opportunity_id = quote.opportunity_id

            # Clear existing primary flags in the same opportunity
            Quote.objects.filter(opportunity_id=opportunity_id).update(hs_primary=False)

            # Set this quote as primary
            quote.hs_primary = True
            quote.save()

            return JsonResponse({"success": True})
        except Quote.DoesNotExist:
            return JsonResponse({"error": "Quote not found"}, status=404)

    return JsonResponse({"error": "Invalid method"}, status=405)



def create_custom_field(request):
    if request.method == "POST":
        crm = request.POST["crm"]
        object_type = request.POST["object_type"]
        name = request.POST["name"]
        label = request.POST["label"]
        data_type = request.POST["data_type"]
        required = "required" in request.POST

        # ✅ Save to DB
        field = CustomField.objects.create(
            crm=crm, object_type=object_type,
            name=name, label=label,
            data_type=data_type, required=required,
            created_by=request.user
        )

        return redirect("custom_fields")

    fields = CustomField.objects.all().order_by("-created_at")
    return render(request, "custom_fields.html", {"fields": fields})

def get_standard_fields(model_name):
    mapping = {
        "Lead": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Contact": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Account": [{"name": "name", "data_type": "Text"}],
        "Opportunity": [{"name": "stage", "data_type": "Picklist"}, {"name": "amount", "data_type": "Currency"}],
        "Product": [{"name": "name", "data_type": "Text"}, {"name": "price", "data_type": "Number"}],
        "Quote": [{"name": "net_amount", "data_type": "Currency"}, {"name": "status", "data_type": "Picklist"}],
        "QuoteLine": [{"name": "net_amount", "data_type": "Currency"}, {"name": "status", "data_type": "Picklist"}]
    }
    return mapping.get(model_name, [])

# def custom_fields_view(request):
#     object_types = ['Lead', 'Contact', 'Account', 'Opportunity', 'Product', 'Quote', 'QuoteLine']

#     fields_by_object_type = {}

#     for obj_type in object_types:
#         model_class = apps.get_model('cpq', obj_type)  # Adjust app name if needed
#         standard_fields = [
#             {"name": f.name, "data_type": f.get_internal_type()}
#             for f in model_class._meta.get_fields()
#             if not f.is_relation and not f.auto_created
#         ]

#         custom_fields = CustomField.objects.filter(object_type=obj_type)

#         fields_by_object_type[obj_type] = {
#             "standard": standard_fields,
#             "custom": custom_fields,
#         }

#     return render(request, "custom_fields.html", {
#         "fields_by_object_type": fields_by_object_type,
#         "models": object_types,
#     })

# def custom_fields_view(request):
#     # 1. Start with core CRM object types
#     object_types = ['Lead', 'Contact', 'Account', 'Opportunity', 'Product', 'Quote', 'QuoteLine']

#     # 2. Fetch custom objects from the DB and extend the list
#     custom_objects = CustomObject.objects.all()
#     custom_object_names = [obj.name for obj in custom_objects]
#     all_object_types = object_types + custom_object_names

#     fields_by_object_type = {}

#     # 3. Loop through all types (built-in and custom)
#     for obj_type in all_object_types:
#         try:
#             model_class = apps.get_model('cpq', obj_type)
#             standard_fields = [
#                 {"name": f.name, "data_type": f.get_internal_type()}
#                 for f in model_class._meta.get_fields()
#                 if not f.is_relation and not f.auto_created
#             ]
#         except LookupError:
#             standard_fields = []

#         # 4. Get all custom fields attached to this object type
#         custom_fields = CustomField.objects.filter(object_type=obj_type)

#         fields_by_object_type[obj_type] = {
#             "standard": standard_fields,
#             "custom": custom_fields,
#         }

#     return render(request, "custom_fields.html", {
#         "fields_by_object_type": fields_by_object_type,
#         "models": all_object_types,
#     })
def custom_fields_view(request):
    # Built-in models
    object_types = ['Lead', 'Contact', 'Account', 'Opportunity', 'Product', 'Quote', 'QuoteLine']

    # Custom objects
    custom_objects = CustomObject.objects.all()
    custom_object_names = [obj.name for obj in custom_objects]
    all_object_types = object_types + custom_object_names

    fields_by_object_type = {}

    for obj_type in all_object_types:
        # Try to fetch standard fields for built-in models
        try:
            model_class = apps.get_model('cpq', obj_type)
            standard_fields = [
                {"name": f.name, "data_type": f.get_internal_type()}
                for f in model_class._meta.get_fields()
                if not f.is_relation and not f.auto_created
            ]
        except LookupError:
            standard_fields = []

        # 🔥 FIXED: Get custom fields by object_type OR linked custom_object
        if obj_type in object_types:
            custom_fields = CustomField.objects.filter(object_type=obj_type, custom_object__isnull=True)
        else:
            # Match the custom object by name
            try:
                custom_obj = CustomObject.objects.get(name=obj_type)
                custom_fields = CustomField.objects.filter(custom_object=custom_obj)
            except CustomObject.DoesNotExist:
                custom_fields = []

        fields_by_object_type[obj_type] = {
            "standard": standard_fields,
            "custom": custom_fields,
        }

    return render(request, "custom_fields.html", {
        "fields_by_object_type": fields_by_object_type,
        "models": all_object_types,
    })

def create_custom_field(request):
    if request.method == 'POST':
        form = CustomFieldForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('cpq:custom_fields')  # or wherever you want to go after save
    else:
        form = CustomFieldForm()
    return render(request, 'create_custom_field.html', {'form': form})

def get_company_information(request):
    company = Tenant.objects.first()  # Always work with the first (or only) tenant

    if request.method == 'POST':
        if not company:
            company = Tenant()

        company.name = request.POST.get('name', '')
        company.contact_email = request.POST.get('contact_email', '')
        company.phone_number = request.POST.get('phone_number', '')
        company.primary_color = request.POST.get('primary_color', '')
        company.secondary_color = request.POST.get('secondary_color', '')
        company.street_address = request.POST.get('street_address', '')
        company.city = request.POST.get('city', '')
        company.state = request.POST.get('state', '')
        
        # company.plan = request.POST.get('plan', '')

        # actions_limit_raw = request.POST.get('actions_limit', '')
        # try:
        #     company.actions_limit = int(actions_limit_raw) if actions_limit_raw else None
        # except ValueError:
        #     company.actions_limit = None

        if 'logo' in request.FILES:
            company.logo = request.FILES['logo']

        company.save()
        return redirect('cpq:get_company_information')

    return render(request, 'company_information.html', {
        'company': company or Tenant()
    })


def create_custom_object(request):
    if request.method == 'POST':
        form = CustomObjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('cpq:custom_object_list')  # or some success view
    else:
        form = CustomObjectForm()
    
    return render(request, 'create_custom_object.html', {'form': form})

def get_document_templates(request):

    try:
        company = Tenant.objects.first()
    except ObjectDoesNotExist:
        company = None

    if company is None:
        return render(request, 'document_template.html', {
            'company': None,
            'settings': None,
            'rendered_fields': [],
            'ommited_fields': [],
        })
    
    try:
        document_settings = QuoteDocumentSettings.objects.first()
    except ObjectDoesNotExist:
        document_settings = None

    if request.method == 'POST':
        settings = document_settings or QuoteDocumentSettings()

        #Template Style
        template_style = 'modern' if request.POST.get('template_style') == 'on' else 'classic'
        settings.template_style = template_style

        # Checkboxes
        boolean_fields = [
            'show_company_name', 'show_company_email', 'show_company_phone', 'show_company_domain',
            'show_company_logo', 'show_company_address',
            'show_account_name', 'show_account_website', 'show_account_phone',
            'show_quote_opportunity', 'show_quote_status', 'show_quote_created_at',
            'show_quote_expires_at', 'show_quote_notes',
            'show_line_discount', 'show_subscription_term', 'show_sign'
        ]
        
        for field in boolean_fields:
            setattr(settings, field, field in request.POST)

        # Rendered & omitted fields
        rendered_fields_raw = request.POST.get("rendered_fields", "[]")
        omitted_fields_raw = request.POST.get("omitted_fields", "[]")
        try:
            settings.rendered_fields = json.loads(rendered_fields_raw)
            settings.omitted_fields = json.loads(omitted_fields_raw)
        except json.JSONDecodeError:
            settings.rendered_fields = []
            settings.omitted_fields = []
        
        # Terms and conditions
        settings.terms_and_conditions = request.POST.get("terms_conditions", "")

        settings.save()
        return redirect('cpq:get_document_template')
    
    if document_settings is None:
        document_settings = QuoteDocumentSettings.objects.create(
            rendered_fields=QuoteDocumentSettings.default_rendered_fields(),
            omitted_fields=QuoteDocumentSettings.default_omitted_fields()
        )

    return render(request, 'document_template.html', {
        'company': company,
        'settings': document_settings,
        'rendered_fields': document_settings.rendered_fields if document_settings else [],
        'omitted_fields': document_settings.omitted_fields if document_settings else []
    })
