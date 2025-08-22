from django.shortcuts import render, get_object_or_404, redirect
from .models import Product, SystemFieldMapping,Quote,CustomField,Tenant,QuoteDocumentSettings,CustomObject,BusinessRule,CustomRecord,CustomFieldValue, ActionUsage, Option, Account
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt 
from django.apps import apps
from salesforce.models import SalesforceToken
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ObjectDoesNotExist
import json
from .forms import CustomFieldForm, CustomObjectForm, EmailAlertForm, generate_dynamic_form
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
import logging
from django.db.models import Count
from django.utils.timezone import now
from django.db.models.functions import TruncMonth
from datetime import datetime
from django.utils.timezone import make_aware
from .forms import BusinessRuleForm, get_rule_condition_formset
from .forms import QUOTE_FIELDS, QUOTE_LINE_FIELDS, PRODUCT_FIELDS
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from django.contrib.auth.models import User, Group
from django.utils import timezone
from .models import EmailAlert

# Agents General Helpers
from agents.utils.quote_agent.general_helpers import set_custom_fields_into_quote_document_settings


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect('dashboard')  # or any logged-in home view
    return redirect('login')

def product_list(request):
    """Fetch all products and display them in a table."""
    products = Product.objects.all()
    options = Option.objects.all()
    return render(request, "products.html", {"products": products, "options": options})

def product_detail(request, product_id):
    """View detailed product information."""
    print("product detail")
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


# Maybe it is not used
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
            crm=crm,
            object_type=object_type,
            name=name,
            label=label,
            data_type=data_type,
            required=required,
            created_by=request.user
        )

        if field:
            quote_document_settings = QuoteDocumentSettings.objects.first()
            if quote_document_settings:
                # Add label at the end of omitted_fields
                omitted = quote_document_settings.omitted_fields or []
                
                if label not in omitted:  # Avoid duplicated
                    omitted.append(label)
                    quote_document_settings.omitted_fields = omitted
                    quote_document_settings.save()

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

@login_required
def custom_fields_view(request):

    if request.method == 'POST':
        form = CustomObjectForm(request.POST)
        if form.is_valid():
            custom_object = form.save(commit=False)
            custom_object.created_by = request.user
            custom_object.updated_by = request.user
            custom_object.save()
            request.session['custom_object_success'] = True
            return redirect('cpq:custom_fields')
    else:
        form = CustomObjectForm()

    # Built-in models
    object_types = ['Activity', 'Lead', 'Contact', 'Account', 'Opportunity', 'Product', 'Quote', 'QuoteLine']

    # Custom objects
    custom_objects = CustomObject.objects.all()
    custom_object_names = [obj.name for obj in custom_objects]
    all_object_types = object_types + custom_object_names

    fields_by_object_type = {}

    for obj_type in all_object_types:
        try:
            model_class = apps.get_model('cpq', obj_type)
            standard_fields = [
                {"name": f.name, "data_type": f.get_internal_type()}
                for f in model_class._meta.get_fields()
                if not f.is_relation and not f.auto_created
            ]
        except LookupError:
            standard_fields = []

        if obj_type in object_types:
            custom_fields = CustomField.objects.filter(object_type=obj_type, custom_object__isnull=True)
        else:
            try:
                custom_obj = CustomObject.objects.get(name=obj_type)
                custom_fields = CustomField.objects.filter(object_type=custom_obj.name)
            except CustomObject.DoesNotExist:
                custom_fields = []

        fields_by_object_type[obj_type] = {
            "standard": standard_fields,
            "custom": custom_fields,
        }

    # New dictionary for real data of custom objects
    custom_objects_data = {}

    for custom_obj in custom_objects:
        custom_objects_data[custom_obj.name] = [{
            "label": custom_obj.label,
            "name": custom_obj.name,
            "description": custom_obj.description,
            "created_at": custom_obj.created_at,
            "created_by": custom_obj.created_by.username if custom_obj.created_by else "",
            "updated_at": custom_obj.updated_at,
            "updated_by": custom_obj.updated_by.username if custom_obj.updated_by else ""
        }]

    object_type_kinds = {}
    for obj in all_object_types:
        if obj in object_types:
            object_type_kinds[obj] = 'standard'
        else:
            object_type_kinds[obj] = 'custom'

    success = request.session.pop('custom_object_success', False)
    return render(request, "custom_fields.html", {
        "fields_by_object_type": fields_by_object_type,
        "models": all_object_types,
        "standard_models": object_types,
        "custom_models": custom_object_names,
        "custom_object_records": custom_objects_data,
        "object_type_kinds": object_type_kinds,
        "form": form,  # ✅ Pass the form to the template
        "success": success  # ✅ Add to context
    })

def edit_custom_object(request, object_name):
    custom_object = get_object_or_404(CustomObject, name=object_name)

    if request.method == 'POST':
        form = CustomObjectForm(request.POST, instance=custom_object)
        if form.is_valid():
            updated_object = form.save(commit=False)
            updated_object.updated_by = request.user
            updated_object.save()
            return redirect('cpq:custom_fields')  # O donde quieras regresar
    else:
        form = CustomObjectForm(instance=custom_object)

        # Get related values
        related_customfields = custom_object.custom_fields.all()

        related_data = defaultdict(list)

        for custom_field in related_customfields:
            related_values = custom_field.values.all()
            related_data[custom_field.label].extend(related_values)
        
        related_data = dict(related_data)

    return render(request, 'edit_custom_object.html', {
        'form': form,
        'object_name': object_name,
        'related_data': related_data
    })

@require_POST
def delete_custom_object(request, object_name):
    custom_object = get_object_or_404(CustomObject, name=object_name)

    if not request.user.is_superuser and not request.user.is_staff:
        return HttpResponseForbidden("You do not have permission to delete this custom object.")

    custom_object.delete()
    return redirect('cpq:custom_fields')

def create_custom_field(request, object_name):
    if request.method == 'POST':
        form = CustomFieldForm(request.POST)

        if form.is_valid():
            # Buscamos si el object_type es un objeto custom

            field = form.save(commit=False)
            field.created_by = request.user
            field.updated_by = request.user
            field.save()

            # 🔧 Lógica personalizada aquí
            #quote_document_settings = QuoteDocumentSettings.objects.first()
            #if quote_document_settings:
            #    full_label = f"{field.object_type}.{field.label}"
            #    omitted = quote_document_settings.omitted_fields or []

            #    if full_label not in omitted:
            #        omitted.append(full_label)
            #        quote_document_settings.omitted_fields = omitted
            #        quote_document_settings.save()
            
            return redirect('cpq:custom_fields')  # or wherever you want to go after save
        else:
            print("Form errors:", form.errors)
    else:
        # Buscar si object_type es un objeto custom
        try:
            custom_obj = CustomObject.objects.get(name=object_name)
            form = CustomFieldForm(initial={'crm': 'AgentCPQ', 'object_type': object_name, 'custom_object': custom_obj})
        except ObjectDoesNotExist:
            form = CustomFieldForm(initial={'crm': 'AgentCPQ', 'object_type': object_name})

    return render(request, 'create_custom_field.html', {'form': form, 'object_name': object_name})


def edit_custom_field(request, field_id):
    custom_field = get_object_or_404(CustomField, id=field_id)

    if request.method == 'POST':
        form = CustomFieldForm(request.POST, instance=custom_field)
        if form.is_valid():
            updated_field = form.save(commit=False)
            updated_field.updated_by = request.user
            updated_field.save()
            return redirect('cpq:custom_fields')
    else:
        form = CustomFieldForm(instance=custom_field)
        # Get related values
        related_values = custom_field.values.all()

        print(f"\n\nRelated Values: {related_values}\n\n")

    return render(request, 'edit_custom_field.html', {
        'form': form,
        'field_id': field_id,
        'related_values': related_values
    })

@require_POST
def delete_custom_field(request, field_id):
    custom_field = get_object_or_404(CustomField, id=field_id)

    # Only admins can delete custom fields
    if not request.user.is_superuser and not request.user.is_staff:
        return HttpResponseForbidden("You do not have permission to delete this custom field.")
    
    
    custom_field.delete()
    return redirect('cpq:custom_fields')


@login_required
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


# No dont require this function (apparently)
def create_custom_object(request):
    if request.method == 'POST':
        form = CustomObjectForm(request.POST)
        if form.is_valid():
            custom_object = form.save(commit=False)
            custom_object.created_by = request.user
            print(f"User: {request.user}")
            custom_object.save()
            return redirect('cpq:custom_object_list')  # or some success view
    else:
        form = CustomObjectForm()
    
    return render(request, 'create_custom_object.html', {'form': form})

@login_required
def get_custom_record_form(request, record_id):
    record = get_object_or_404(CustomRecord, id=record_id)
    DynamicForm = generate_dynamic_form(record.object_type)

    initial_data = {v.field.name: v.value for v in record.custom_field_values.all()}
    form = DynamicForm(initial=initial_data)

    # Solo retornamos el HTML parcial
    return render(request, 'custom_objects/partial_edit_form_fields.html', {'form': form})

@login_required
def edit_custom_record(request, record_id):
    record = get_object_or_404(CustomRecord, id=record_id)
    DynamicForm = generate_dynamic_form(record.object_type)

    if request.method == "POST":
        form = DynamicForm(request.POST)
        if form.is_valid():
            content_type = ContentType.objects.get_for_model(record)
            for field_name, value in form.cleaned_data.items():
                custom_field = CustomField.objects.get(name=field_name, custom_object=record.object_type)
                cfv, created = CustomFieldValue.objects.get_or_create(
                    record=record,
                    field=custom_field,
                    defaults={'content_type': content_type, 'object_id': record.id}
                )
                if not created:
                    cfv.value = value
                    cfv.save()
            messages.success(request, f"{record.object_type.label} record updated successfully.")

            # Actualizar usuario y fecha
            record.updated_by = request.user
            record.updated_at = timezone.now()
            record.save()

            # Redirigir o retornar JSON
            return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))
        else:
            messages.error(request, "Form contains errors. Please fix them.")
    return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))

@csrf_exempt
def delete_custom_record(request, record_id):
    if request.method == "POST":
        record = get_object_or_404(CustomRecord, id=record_id)
        record.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

def get_document_template(request):

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

        #Description Detail Level
        description_detail = 'long' if request.POST.get('description_detail_level') == 'on' else 'short'
        settings.line_description_detail_level = description_detail

        # Checkboxes
        boolean_fields = [
            'show_company_name', 'show_company_email', 'show_company_phone', 'show_company_domain',
            'show_company_logo', 'show_company_address',
            'show_account_name', 'show_account_website', 'show_account_phone',
            'show_quote_opportunity', 'show_quote_status', 'show_quote_created_at',
            'show_quote_expires_at', 'show_quote_notes',
            'show_line_discount', 'show_subscription_term', 'show_sign', 'show_quote_tax_percentage', 'show_quote_tax_amount'
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
            print("Error decodificando los JSON\n\n")

        # Tax Switch
        tax_switch = True if request.POST.get('tax-information-switch') == 'on' else False
        settings.show_quote_tax_information = tax_switch


        # Tax Rate
        settings.quote_tax = request.POST.get("tax_rate", "")
        
        # Terms and conditions
        settings.terms_and_conditions = request.POST.get("terms_conditions", "")

        settings.save()

        #Update every quote tax amount
        for quote in Quote.objects.all():
            quote.update_tax()
            quote.save()
        return redirect('cpq:get_document_template')
    
    if document_settings is None:
        document_settings = QuoteDocumentSettings.objects.create(
            rendered_fields=QuoteDocumentSettings.default_rendered_fields(),
            omitted_fields=QuoteDocumentSettings.default_omitted_fields()
        )
    
    # Hardcore for now
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])
    document_settings.refresh_from_db()

    return render(request, 'document_template.html', {
        'company': company,
        'settings': document_settings,
        'rendered_fields': document_settings.rendered_fields if document_settings else [],
        'omitted_fields': document_settings.omitted_fields if document_settings else []
    })

def business_rules_view(request):

    try:
        company = Tenant.objects.first()
    except ObjectDoesNotExist:
        company = None

    rule_types = ['general', 'validation', 'inclusion', 'exclusion']
    rules_by_type = {}

    for rule_type in rule_types:
        rules = BusinessRule.objects.filter(rule_type=rule_type).order_by("priority")
        rules_by_type[rule_type] = rules

    return render(request, 'manage_rules.html', {
        'company': company,
        "rules_by_type": rules_by_type
    })

def manage_notifications_view(request):
    email_alerts = EmailAlert.objects.all()

    # Preparamos helper para "roles" y "external"
    alerts_with_lists = []
    for alert in email_alerts:
        # Convierte roles a lista
        roles_list = []
        if alert.recipients_roles:
            roles_list = [r.strip() for r in alert.recipients_roles.split(",") if r.strip()]

        # Convierte CSV de external en lista
        external_list = []
        if alert.recipients_external:
            external_list = [e.strip() for e in alert.recipients_external.split(",") if e.strip()]

        # Inyectamos atributos extra al objeto
        alert.roles_list = roles_list
        alert.external_list = external_list

        alerts_with_lists.append(alert)

    # Filtrado por objeto

    alert_groups = [
        {
            "title": "Lead Notifications",
            "icon": "person_add",
            "alerts": [a for a in alerts_with_lists if a.native_object == "Lead"]
        },
        {
            "title": "Account Notifications",
            "icon": "account_circle",
            "alerts": [a for a in alerts_with_lists if a.native_object == "Account"]
        },
        {
            "title": "Opportunity Notifications",
            "icon": "trending_up",
            "alerts": [a for a in alerts_with_lists if a.native_object == "Opportunity"]
        },
        {
            "title": "Quote Notifications",
            "icon": "request_quote",
            "alerts": [a for a in alerts_with_lists if a.native_object == "Quote"]
        },
        {
            "title": "Subscription Notifications",
            "icon": "autorenew",
            "alerts": [a for a in alerts_with_lists if a.native_object == "Subscription"]
        }
    ]

    return render(request, 'manage_notifications.html', {
        'alert_groups': alert_groups
    })

def edit_notification(request, alert_name):
    notification = get_object_or_404(EmailAlert, name=alert_name)

    if request.method == "POST":
        post_data = request.POST.copy()

        # Convertimos los hidden inputs de chips a listas
        if 'recipients_users' in post_data and post_data['recipients_users']:
            post_data.setlist('recipients_users', post_data['recipients_users'].split(','))

        # recipients_roles lo dejamos como JSON enviado desde JS
        form = EmailAlertForm(post_data, instance=notification)

        if form.is_valid():
            notification = form.save(commit=False)

            # recipients_roles ya viene como string limpio desde clean_recipients_roles
            # recipients_external convertimos a string limpio
            notification.recipients_external = ",".join([
                e.strip() for e in form.cleaned_data.get("recipients_external", "").split(",") if e.strip()
            ])

            notification.offset_days = form.cleaned_data.get("offset_days")
            notification.scheduled_cron = form.cleaned_data.get("scheduled_cron")

            if not form.cleaned_data.get("custom_object"):
                notification.custom_object = None


            notification.updated_by = request.user

            notification.save()
            form.save_m2m()  # guarda recipients_users

            return redirect("cpq:manage_notifications")
        else:
            print("Form errors:", form.errors)

    else:
        form = EmailAlertForm(instance=notification)

    # Preparar roles para chips JS
    role_dict = dict(EmailAlert.ROLE_CHOICES)
    initial_roles = []

    if notification.recipients_roles:
        role_keys = [r.strip() for r in notification.recipients_roles.split(",") if r.strip()]
        initial_roles = [{"tag": role_dict.get(key, key), "value": key} for key in role_keys]

    context = {
        "notification": notification,
        "form": form,
        "roles_choices": EmailAlert.ROLE_CHOICES,
        "initial_roles": initial_roles,
        "users": User.objects.all(),
        "emails_external": notification.recipients_external.split(",") if notification.recipients_external else [],
    }

    return render(request, "edit_email_alert.html", context)


@require_POST
def create_notification(request):
    notification_type = request.POST.get('notification_type')  # 'account', 'lead', etc.
    when = request.POST.get('account_when')  # coincide con el name del select
    recipient = request.POST.get('account_recipient')  # coincide con el name del select

    print(f"Informacion: {notification_type}")
    print(f"When: {when}")
    print(f"Recipient: {recipient}")

    # Guardar en el modelo
    #Notification.objects.create(
    #    notification_type=notification_type,
    #    when=when,
    #    recipient=recipient,
    #    options={}  # opciones extra si las necesitas
    #)

    return JsonResponse({'status': 'ok'})

def create_business_rule(request):
    rule_type = request.GET.get("type", "validation")
    target_type = request.GET.get("target_type", "quote_line")

    if request.method == "POST":
        print(f"\n\nSi llega al POST\n\n")
        form = BusinessRuleForm(request.POST)
        target_type = request.POST.get("target_type", "quote_line")
        formset = get_rule_condition_formset(target_type, request.POST)

        if form.is_valid() and formset.is_valid():
            rule = form.save(commit=False)
            rule.rule_type = rule_type
            rule.save()

            for condition in formset.save(commit=False):
                condition.rule = rule
                condition.save()

            return redirect("cpq:business_rules")
        else:
            print("Form errors:", form.errors)
            print("Formset errors:")
            for f in formset.forms:
                print(f.errors)

    else:
        form = BusinessRuleForm(initial={"rule_type": rule_type})
        target_type = request.GET.get("target_type", "quote_line")
        formset = get_rule_condition_formset(target_type)


    return render(request, "create_business_rule.html", {
        "form": form,
        "formset": formset,
        "rule_type": rule_type,
        "QUOTE_FIELDS": mark_safe(json.dumps(QUOTE_FIELDS)),
        "QUOTE_LINE_FIELDS": mark_safe(json.dumps(QUOTE_LINE_FIELDS)),
        "PRODUCT_FIELDS": mark_safe(json.dumps(PRODUCT_FIELDS)),
    })


def create_custom_record(request, object_name, user_id):

    custom_object = get_object_or_404(CustomObject, name=object_name)
    DynamicForm = generate_dynamic_form(custom_object)
    
    if request.method == 'POST':
        form = DynamicForm(request.POST)
        if form.is_valid():
            user = User.objects.get(id=user_id)
            record = CustomRecord.objects.create(
                    object_type=custom_object,
                    created_by = user,
                    updated_by = user
                )

            content_type = ContentType.objects.get_for_model(record)

            for field_name, value in form.cleaned_data.items():
                try:
                    custom_field = CustomField.objects.get(name=field_name, custom_object=custom_object)
                    if not value:
                        value = "---"

                    CustomFieldValue.objects.create(
                        record=record,
                        field=custom_field,
                        value=value,
                        content_type=content_type,
                        object_id=record.id
                    )
                
                except CustomField.DoesNotExist:
                    print(f"Field not found: {field_name}")
            messages.success(request, f"{custom_object.label} record created successfully.")
            return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))
    else:
        form = DynamicForm()

    return render(request, 'custom_objects/record_form.html', {
        'form': form,
        'custom_object': custom_object
    })


def get_lookup_data_for_form(custom_object):
    lookup_data = {}
    for field in CustomField.objects.filter(custom_object=custom_object, data_type="lookup"):
        try:
            model = apps.get_model(field.lookup_model)
            # Only grab id and name or string version
            instances = model.objects.all()
            lookup_data[field.name] = [{"id": i.id, "label": str(i)} for i in instances]
        except Exception as e:
            lookup_data[field.name] = []
    return lookup_data

def search_accounts(request):
    q = request.GET.get("q", "")
    results = []

    if q:
        matches = Account.objects.filter(name__icontains=q)[:20]
        results = [{"id": acc.id, "name": acc.name} for acc in matches]

    return JsonResponse({"results": results})


def usage_dashboard(request):
    current_tenant = Tenant.objects.first()
    usage_logs = ActionUsage.objects.all()
 

    # ---- Total Actions by Month ----
    actions_by_month = (
        usage_logs
        .annotate(month=TruncMonth("timestamp"))
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )

    # ---- Top 5 Actions (Overall) ----
    top_actions = (
        usage_logs
        .values("action")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )

    # ---- Total Actions by User ----
    actions_by_user = (
        usage_logs
        .values("user__username")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    print(actions_by_user)
    # ---- Overflow Metric (Current Month Only) ----
    start_of_month = make_aware(datetime(now().year, now().month, 1))
    monthly_count = usage_logs.filter(timestamp__gte=start_of_month).count()
    action_limit = current_tenant.actions_limit or 1000
    overflow = monthly_count - action_limit


    actions_by_month_serialized = [
    {
        "month": entry["month"].strftime("%Y-%m"),  # or "%b %Y" for readable labels
        "total": entry["total"]
    }
    for entry in actions_by_month
    ]

    actions_by_user_serialized = [
        {
            "user": entry.get("user__username") or "Unknown",
            "total": entry["count"]
        }
        for entry in actions_by_user
    ]


    context = {
        "tenant": current_tenant,
        "actions_by_month_json": mark_safe(json.dumps(list(actions_by_month_serialized))),
        "actions_by_user_json": mark_safe(json.dumps(list(actions_by_user_serialized))),
        "top_actions": top_actions,
        "monthly_count": monthly_count,
        "limit": action_limit,
        "overflow": max(0, overflow),
    }

    return render(request, "usage.html", context)