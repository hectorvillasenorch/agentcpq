from django.contrib import admin
from django import forms
from .models import (
    Quote,
    QuoteLine,
    Subscription,
    Asset,
    Product,
    Lead,
    Opportunity,
    Account,
    Activity,
    CustomObject,
    CustomField,
    Option,
    BusinessRule,
    CustomFieldValue,
    CustomRecord,
    ActionUsage,
    Contact,
    Tenant,
    QuoteDocument,
    SystemFieldMapping,
    Knowledge,
    Contract, 
    ScheduledTask,
    ActionTrigger
)
from .forms import  get_dynamic_form
from agents.models import ChatMessage, ChatSession, AgentPrompt
from django.contrib.contenttypes.models import ContentType
from django.utils.html import format_html, format_html_join
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.utils.timezone import localtime
from django.utils.text import slugify

# admin.site.register(Subscription)
# admin.site.register(Asset)


class DynamicCustomFieldAdmin(admin.ModelAdmin):
    def get_form(self, request, obj=None, **kwargs):
        form_class = self.form

        class RequestBoundForm(form_class):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs['user'] = request.user
                super().__init__(*args, **inner_kwargs)

        return RequestBoundForm

@admin.register(CustomObject)
class CustomObjectAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(CustomObject, crm="AgentCPQ", object_type="CustomObject")
    list_display = ('name', 'label', 'description')  # Adjust as needed

@admin.register(CustomField)
class CustomFieldAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(CustomField, crm="AgentCPQ", object_type="CustomField")
    list_display = ("label", "name", "data_type", "object_type", "custom_object", "created_by", "created_at")



class LeadAdmin(DynamicCustomFieldAdmin):
    readonly_fields = ['related_activities']

    def related_activities(self, obj):
        if not obj:
            return ""

        # Use the FK field name for prefill (lead)
        add_url = f"{reverse('admin:cpq_activity_add')}?lead={obj.pk}"

        # Use the declared related_name='activities'
        activities_qs = obj.activities.all()

        rows = format_html_join(
            '',
            '<tr>'
            '<td style="padding:6px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600;">'
            '<a href="{}" style="text-decoration:none;">{}</a>'
            '</td>'
            '<td style="padding:6px 8px;white-space:nowrap;">{}</td>'
            '<td style="padding:6px 8px;white-space:nowrap;">{}</td>'
            '<td style="width:100%;white-space:normal;word-wrap:break-word;">{}</td>'
            '<td style="padding:6px 8px;white-space:nowrap;">'
            '<a href="{}" style="margin-right:8px;padding:4px 6px;color:#2563eb;text-decoration:none;" title="Edit">&#9998;</a>'
            '<a href="{}" style="padding:4px 6px;color:#dc2626;text-decoration:none;" title="Delete">&#128465;</a>'
            '</td>'
            '</tr>',
            (
                (
                    reverse('admin:cpq_activity_change', args=[a.pk]),  # subject link target
                    a.subject,
                    a.get_status_display() if hasattr(a, 'get_status_display') else a.status,
                    a.due_date or '',
                    a.notes or '',
                    reverse('admin:cpq_activity_change', args=[a.pk]),   # edit icon link
                    reverse('admin:cpq_activity_delete', args=[a.pk])    # delete icon link
                )
                for a in activities_qs
            )
        )

        if not rows:
            rows = format_html('<tr><td colspan="5" style="padding:6px 8px;color:#777;">No activities yet.</td></tr>')

        return format_html(
            '''
            <a href="{}" class="button" style="margin-bottom:10px;display:inline-block;background:#2b8dbf;color:white;padding:5px 10px;border-radius:3px;">+ Add Activity</a>
            <table style="width:100%;border-collapse:collapse;table-layout:fixed;">
                <thead>
                    <tr style="background:#333;color:white;">
                        <th style="text-align:left;padding:6px 8px;width:22%;">Subject</th>
                        <th style="text-align:left;padding:6px 8px;">Status</th>
                        <th style="text-align:left;padding:6px 8px;">Due Date</th>
                        <th style="text-align:left;padding:6px 8px;">Notes</th>
                        <th style="text-align:left;padding:6px 8px;width:80px;">Actions</th>
                    </tr>
                </thead>
                <tbody>{}</tbody>
            </table>
            ''',
            add_url,
            rows
        )

    related_activities.short_description = "Activities" # type: ignore[attr-defined]
    form = get_dynamic_form(Lead, crm="AgentCPQ", object_type="Lead")
    def get_fieldsets(self, request, obj=None):
        fields = list(self.form().fields.keys()) + ['related_activities']
        return [(None, {'fields': fields})]
    search_fields = ['first_name', 'last_name', 'email']
    list_filter = ['status', 'created_at']

    list_display = ('first_name','last_name', 'phone', 'email', 'status', 'assigned_to', 'created_at', 'updated_at')
admin.site.register(Lead, LeadAdmin)






# class ActivityInline(admin.TabularInline):  # or admin.StackedInline
#     model = Activity
#     extra = 0  # don’t show extra empty rows
#     fields = ('activity_type', 'date', 'status')  # customize visible fields
#     show_change_link = True  # optional: show link to full edit form


class AccountAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Account, crm="AgentCPQ", object_type="Account")
    list_display = ('tenant_id','name', 'industry', 'website', 'phone', 'created_at', 'updated_at')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(Account, AccountAdmin)

class ContractAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Contract, crm="AgentCPQ", object_type="Contract")
    list_display = ('opportunity','start_date','end_date', 'contract_status')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(Contract, ContractAdmin)

class SubscriptionAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Subscription, crm="AgentCPQ", object_type="Subscription")
    list_display = ('start_date','end_date', 'billing_cycle', 'price_per_cycle', 'term', 'contract', 'quote', 'product', 'quote_line')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(Subscription, SubscriptionAdmin)


class ActionTriggerAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(ActionTrigger, crm="AgentCPQ", object_type="ActionTrigger")
    list_display = ('trigger','action','object_name', 'action_params', 'active')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(ActionTrigger, ActionTriggerAdmin)

class ScheduledTaskAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(ScheduledTask, crm="AgentCPQ", object_type="ScheduledTask")
    list_display = ('opportunity','status','execute_at', 'attempts', 'last_error', 'created_at', 'updated_at')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(ScheduledTask, ScheduledTaskAdmin)


class QuoteAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Quote, crm="AgentCPQ", object_type="Quote")
    list_display = ('name','account', 'opportunity', 'net_amount', 'status', 'expiration_date', 'created_at', 'updated_at')
    # Required because QuoteDocumentAdmin uses autocomplete_fields=("quote",)
    search_fields = ('name', 'qteid', 'account__name', 'opportunity__name')

admin.site.register(Quote, QuoteAdmin)

# Admin for QuoteDocument
@admin.register(QuoteDocument)
class QuoteDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "quote_id", "version", "generated_at", "generated_by", "name", "file")
    search_fields = ("quote__name", "quote__id", "id")
    list_filter = ("version", "generated_at")
    autocomplete_fields = ("quote",)
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)

# admin.site.register(Account)

# class ActivityInline(admin.TabularInline):  # or admin.StackedInline
#     model = Activity
#     extra = 1  # show 1 empty form by default
#     fields = ['notes','activity_type','status','due_date']  # fields you want editable inline

BaseOpportunityForm = get_dynamic_form(Opportunity, crm="AgentCPQ", object_type="Opportunity")

class OpportunityEditableForm(BaseOpportunityForm): # type: ignore
    hs_deal_id = forms.CharField(required=False, label="HubSpot Deal ID")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Prefill with instance value when editing
        if getattr(self, 'instance', None) is not None:
            self.fields['hs_deal_id'].initial = getattr(self.instance, 'hs_deal_id', None)

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.hs_deal_id = self.cleaned_data.get('hs_deal_id')
        if commit:
            obj.save()
        return obj

class OpportunityAdmin(DynamicCustomFieldAdmin):
    form = OpportunityEditableForm
    list_display = ('name','amount', 'account', 'stage', 'expected_close_date', 'primary_quote', 'created_at')
    def get_fieldsets(self, request, obj=None):
        fields = list(self.form().fields.keys())
        if 'hs_deal_id' not in fields:
            fields.append('hs_deal_id')
        return [(None, {'fields': fields})]

admin.site.register(Opportunity, OpportunityAdmin)


@admin.register(Knowledge)
class KnowledgeAdmin(admin.ModelAdmin):
    list_display = ('title', 'language', 'has_video', 'is_active', 'created_at')
    list_filter = ('language', 'has_video', 'is_active', 'created_at')
    search_fields = ('title', 'content_text', 'tags')
    readonly_fields = ('created_at', 'updated_at', 'image_preview', 'embedding')
    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'language', 'tags', 'is_active')
        }),
        ('Content', {
            'fields': ('content_text',)
        }),
        ('Media', {
            'fields': ('image_file', 'image_url', 'image_preview', 'video_url', 'embedding')
        }),
        ('Ownership & Timestamps', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at')
        }),
    )

    def image_preview(self, obj):
        if obj and obj.image_url:
            return format_html(
                "<img src='{}' style='max-width:320px;height:auto;border-radius:6px;' alt='Knowledge image preview'>",
                obj.image_url,
            )
        return "No image uploaded"

    image_preview.short_description = "Image preview"

class OptionInline(admin.TabularInline):
    model = Option
    fk_name = 'parent_product'  # ✔ correct parent FK
    extra = 0
    can_delete = True
    show_change_link = True  # optional: shows ✏️ edit icon

    fields = ('product_option', 'quantity', 'is_required', 'min_quantity', 'max_quantity', 'default_selected', 'group_name')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'parent_product':
            kwargs['queryset'] = Product.objects.filter(is_bundle=True)

        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)

        if hasattr(formfield, 'widget') and hasattr(formfield.widget, 'can_add_related'):
            formfield.widget.can_add_related = False  # ❌ hide green plus
            formfield.widget.can_change_related = True  # ✅ keep pencil icon

        return formfield

class ProductAdmin(DynamicCustomFieldAdmin):
    change_list_template = "admin/product/change_list.html"

    # 🔹 quitar 'created_by' de readonly_fields
    readonly_fields = ('updated_by',)

    def get_fieldsets(self, request, obj=None):
        form = self.get_form(request, obj)()
        return [(None, {'fields': list(form.fields.keys())})]

    def save_model(self, request, obj, form, change):
        if hasattr(obj, 'created_by'):
            if not change:  # creación
                obj.created_by = request.user
            else:  # edición
                original = self.model.objects.get(pk=obj.pk)
                obj.created_by = original.created_by

        super().save_model(request, obj, form, change)

        # Keep custom fields (CustomFieldValue)
        for field in CustomField.objects.filter(crm="AgentCPQ", object_type="Product"):
            field_name = field.name
            print(f"\n\n Field Name: {field_name} \n\n")
            if field_name in form.cleaned_data:
                value = form.cleaned_data[field_name]
                print(f"\n\n Value for {field_name}: {value}\n\n")
                cf_value, _ = CustomFieldValue.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=obj.id,
                    field=field,
                )
                cf_value.value = value if value else ""
                cf_value.updated_by_user = request.user
                cf_value.save()

    def format_datetime(self, dt):
        if not dt:
            return ""
        local_dt = localtime(dt)
        return local_dt.strftime("%m/%d/%Y, %I:%M %p")

    def display_created_by(self, obj):
        if hasattr(obj, "created_by") and hasattr(obj, "created_at"):
            return format_html(
                '{} - <span class="utc-datetime" data-datetime="{}">...</span>',
                obj.created_by,
                obj.created_at.isoformat(),
            )
        return ""

    def display_updated_by(self, obj):
        if hasattr(obj, "updated_by") and hasattr(obj, "updated_at"):
            return format_html(
                '{} - <span class="utc-datetime" data-datetime="{}">...</span>',
                obj.updated_by,
                obj.updated_at.isoformat(),
            )
        return ""

    def display_name_sku(self, obj):
        return f"{obj.name} ({obj.sku})"

    display_created_by.short_description = "Created by" # type: ignore
    display_updated_by.short_description = "Updated by" # type: ignore
    display_name_sku.short_description = "Product"      # type: ignore

    def get_list_display(self, request):
        initial_fields = ['display_name_sku', 'price', 'family']
        trailing_fields = ['display_updated_by', 'display_created_by']

        custom_fields = CustomField.objects.filter(crm="AgentCPQ", object_type="Product")
        dynamic_fields = []

        for field in custom_fields:
            method_name = f"custom_field_{field.id}"
            dynamic_fields.append(method_name)

            if hasattr(self, method_name):
                delattr(self, method_name)

            setattr(self, method_name, self.build_custom_field_method(field))

        return initial_fields + dynamic_fields + trailing_fields

    def build_custom_field_method(self, field):
        def method(obj):
            content_type = ContentType.objects.get_for_model(obj)
            try:
                value_obj = CustomFieldValue.objects.get(
                    content_type=content_type,
                    object_id=obj.id,
                    field=field
                )
                return value_obj.value or "---"
            except CustomFieldValue.DoesNotExist:
                return "---"
        method.short_description = field.label or field.name  # type: ignore
        method.admin_order_field = None                       # type: ignore
        return method

    def get_form(self, request, obj=None, **kwargs):
        form_class = get_dynamic_form(Product, crm="AgentCPQ", object_type="Product")

        class FormWithUser(form_class):
            def __init__(self2, *args, **kw):
                kw['user'] = request.user
                super().__init__(*args, **kw)

        return FormWithUser

admin.site.register(Product, ProductAdmin)

class ActivityAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Activity, crm="AgentCPQ", object_type="Activity")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

    def _redirect_to_related(self, request, obj):
        """Return an HttpResponseRedirect to the related object's admin change page, if any."""
        if getattr(obj, 'lead_id', None):
            return HttpResponseRedirect(reverse('admin:cpq_lead_change', args=[obj.lead_id]))
        if getattr(obj, 'contact_id', None):
            return HttpResponseRedirect(reverse('admin:cpq_contact_change', args=[obj.contact_id]))
        if getattr(obj, 'opportunity_id', None):
            return HttpResponseRedirect(reverse('admin:cpq_opportunity_change', args=[obj.opportunity_id]))
        return None

    def response_add(self, request, obj, post_url_continue=None):
        """After creating an Activity, go back to the related Lead/Contact/Opportunity unless the user chose continue/add another/save as new."""
        # Respect standard admin buttons
        if ('_continue' in request.POST) or ('_addanother' in request.POST) or ('_saveasnew' in request.POST):
            return super().response_add(request, obj, post_url_continue)
        # Default "Save" → redirect to related record if present
        redirect = self._redirect_to_related(request, obj)
        return redirect or super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        """After editing an Activity and pressing plain Save, go back to the related object."""
        if ('_continue' in request.POST) or ('_addanother' in request.POST) or ('_saveasnew' in request.POST):
            return super().response_change(request, obj)
        redirect = self._redirect_to_related(request, obj)
        return redirect or super().response_change(request, obj)

    def delete_view(self, request, object_id, extra_context=None):
        """On delete, send the user back to the related Lead/Contact/Opportunity if present."""
        obj = self.get_object(request, object_id)
        redirect_url = None
        if obj is not None:
            # Compute where to go back to, same priority as other redirects
            if getattr(obj, 'lead_id', None):
                redirect_url = reverse('admin:cpq_lead_change', args=[obj.lead_id])
            elif getattr(obj, 'contact_id', None):
                redirect_url = reverse('admin:cpq_contact_change', args=[obj.contact_id])
            elif getattr(obj, 'opportunity_id', None):
                redirect_url = reverse('admin:cpq_opportunity_change', args=[obj.opportunity_id])
        # If it's a POST (confirmed), let the parent delete first, then override redirect
        if request.method == 'POST':
            # Let django handle the actual delete + messaging
            response = super().delete_view(request, object_id, extra_context)
            if redirect_url:
                return HttpResponseRedirect(redirect_url)
            return response
        # GET confirms as usual
        return super().delete_view(request, object_id, extra_context)

admin.site.register(Activity, ActivityAdmin)


class OptionAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Option, crm="AgentCPQ", object_type="Option")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
    list_display = ('product_option','parent_product','is_required','min_quantity','max_quantity','default_selected')

admin.site.register(Option, OptionAdmin)


### Uncomment to Enable This Feature ####

@admin.register(BusinessRule)
class BusinessRuleAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(BusinessRule, crm="AgentCPQ", object_type="BusinessRule")
    list_display = ('name', 'rule_type', 'active', 'created_by', 'created_at')
    search_fields = ('name',)
    list_filter = ('rule_type', 'active')


class QuoteLineAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(QuoteLine, crm="AgentCPQ", object_type="QuoteLine")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(QuoteLine, QuoteLineAdmin)

@admin.register(ActionUsage)
class ActionUsageAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "user", "related_object_type", "related_object_id")
    list_filter = ("action", "related_object_type")
    search_fields = ("action", "related_object_id", "user__username")

class ContactAdmin(DynamicCustomFieldAdmin):
    # build a dynamic ModelForm for AgentCPQ → Contact
    form = get_dynamic_form(Contact, crm="AgentCPQ", object_type="Contact")

    # expose every form field in a single fieldset
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

    # tweak these to match your actual model columns
    list_display = (
        'first_name',
        'last_name',
        'email',
        'phone',
        'account',        # drop if not on the model
        'created_at',     # idem
    )

    # optional niceties
    search_fields = ('first_name', 'last_name', 'email')
    list_filter   = ('created_at',)

# register with the admin site
admin.site.register(Contact, ContactAdmin)

class TenantAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Tenant, crm="AgentCPQ", object_type="Tenant")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

    list_display = ('tenant_id','name', 'plan', 'actions_limit', 'created_at', 'version')

admin.site.register(Tenant, TenantAdmin)

class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ('sender', 'content', 'timestamp')
    readonly_fields = ('timestamp',)

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'user', 'title', 'created_at')
    readonly_fields = ('created_at',)
    inlines = [ChatMessageInline]


@admin.register(SystemFieldMapping)
class SystemFieldMappingAdmin(admin.ModelAdmin):
    list_display = ('crm', 'field_type', 'local_field', 'crm_field')
    list_filter   = ('crm', 'field_type')
    search_fields = ('local_field', 'crm_field')


@admin.register(AgentPrompt)
class AgentPromptAdmin(admin.ModelAdmin):
    list_display = (
        "agent_name",
        "method",
        "function",
        "short_instructions",
        "short_system_rules",
        "short_agent_message",
        "temperature",
    )
    list_filter = ("agent_name", "method")
    search_fields = ("system_instructions", "system_rules", "agent_message", "agent_summary")

    fieldsets = (
        (None, {
            "fields": ["agent_name", "method", "function", "system_instructions", "system_rules"]
        }),
        ("LLM Settings", {
            "fields": ["temperature", "agent_message", "agent_summary"]
        }),
    )

    def short_instructions(self, obj):
        """Muestra solo las primeras 80 letras del prompt para no saturar la tabla."""
        return (obj.system_instructions[:80] + "...") if obj.system_instructions else ""
    short_instructions.short_description = "Instructions"

    def short_system_rules(self, obj):
        """Muestra solo las primeras 80 letras de system_rules para la tabla."""
        return (obj.system_rules[:80] + "...") if obj.system_rules else ""
    short_system_rules.short_description = "System Rules"

    def short_agent_message(self, obj):
        """Muestra solo las primeras 80 letras de agent_message para la tabla."""
        return (obj.agent_message[:80] + "...") if obj.agent_message else ""
    short_agent_message.short_description = "Agent Message"
