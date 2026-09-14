from django.contrib import admin
from django import forms
import json
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.models import Group
from django.db import models
from django.db.models import JSONField
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
    ObjectRelationConfig,
    CustomObjectPermission,
    AccessPolicy,
    RecordAccessGrant,
    CustomField,
    Option,
    BusinessRule,
    CustomFieldValue,
    CustomRecord,
    ActionUsage,
    Contact,
    PartnerProfile,
    Tenant,
    QuoteDocument,
    SystemFieldMapping,
    Knowledge,
    Contract, 
    ScheduledTask,
    ScheduledEmail,
    ActionTrigger,
    EmailAlert,
    CustomAction,
    ActionLog,
    DomainEvent,
    ApprovalWorkflow,
    ApprovalRule,
    ApprovalStep,
    QuoteApproval,
)
from .models import PicklistValue
from .forms import  get_dynamic_form
from agents.models import ChatMessage, ChatSession, AgentPrompt
from django.contrib.contenttypes.models import ContentType
from django.utils.html import format_html, format_html_join
from django.forms.models import construct_instance
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.utils.timezone import localtime
from django.utils.text import slugify


class JSONPrettyTextarea(forms.Textarea):
    """
    Monospace textarea with sensible defaults for editing JSON.
    """
    def __init__(self, rows=10, **kwargs):
        attrs = {
            "rows": rows,
            "style": (
                "font-family:Menlo,Consolas,monospace;"
                "white-space:pre;tab-size:2;"
                "background:#0d1117;color:#c9d1d9;"
                "border:1px solid #30363d;border-radius:6px;"
                "padding:10px;"
            ),
        }
        attrs.update(kwargs.pop("attrs", {}))
        super().__init__(attrs=attrs, **kwargs)

# admin.site.register(Subscription)
# admin.site.register(Asset)

class UTCDisplayAdmin(admin.ModelAdmin):
    """Base admin que convierte fechas UTC a data-attributes para JS."""
    
    def _utc_field(self, obj, field_name):
        value = getattr(obj, field_name, None)
        if value:
            return format_html(
                '<span class="utc-date" data-utc="{}">{}</span>',
                value.isoformat(),
                value.strftime("%b %d, %Y, %I:%M %p")  # temporal
            )
        return "-"
    
    def created_at_js(self, obj):
        return self._utc_field(obj, "created_at")
    created_at_js.short_description = "Created At"

    def updated_at_js(self, obj):
        return self._utc_field(obj, "updated_at")
    updated_at_js.short_description = "Updated At"

    class Media:
        js = ("js/agents/admin_convert_timezone.js",)


class DynamicCustomFieldAdmin(admin.ModelAdmin):
    def get_form(self, request, obj=None, **kwargs):
        form_class = self.form

        class RequestBoundForm(form_class):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs['user'] = request.user
                super().__init__(*args, **inner_kwargs)

        return RequestBoundForm

@admin.register(CustomObject)
class CustomObjectAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(CustomObject, crm="AgentCPQ", object_type="CustomObject")
    list_display = ("label", "name", "fields_count", "record_count", "show_in_sidebar", "created_by", "created_at_js")
    list_filter = ("show_in_sidebar",)
    search_fields = ("name", "label", "description")
    ordering = ("label",)
    list_per_page = 50

    @admin.display(description="Fields")
    def fields_count(self, obj):
        return obj.custom_fields.count()

    @admin.display(description="Records")
    def record_count(self, obj):
        try:
            return obj.records.count()
        except Exception:
            return "—"


@admin.register(CustomObjectPermission)
class CustomObjectPermissionAdmin(admin.ModelAdmin):
    list_display = ("group", "custom_object", "can_view", "can_add", "can_change", "can_delete", "created_at", "updated_at")
    list_filter = ("custom_object", "group", "can_view", "can_add", "can_change", "can_delete")
    search_fields = ("group__name", "custom_object__name", "custom_object__label")
    autocomplete_fields = ("group", "custom_object")


@admin.register(AccessPolicy)
class AccessPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "label",
        "strategy",
        "is_active",
        "allow_superuser",
        "allow_staff",
        "include_partner_scope",
        "use_record_grants",
        "allow_unassigned_records",
        "updated_at",
    )
    list_filter = (
        "strategy",
        "is_active",
        "allow_superuser",
        "allow_staff",
        "include_partner_scope",
        "use_record_grants",
    )
    search_fields = ("key", "label")
    ordering = ("-updated_at",)


@admin.register(RecordAccessGrant)
class RecordAccessGrantAdmin(admin.ModelAdmin):
    list_display = (
        "content_type",
        "object_id",
        "user",
        "group",
        "can_view",
        "can_change",
        "can_delete",
        "can_share",
        "created_by",
        "updated_at",
    )
    list_filter = (
        "content_type",
        "can_view",
        "can_change",
        "can_delete",
        "can_share",
    )
    search_fields = (
        "object_id",
        "user__username",
        "group__name",
        "content_type__model",
    )
    autocomplete_fields = ("user", "group", "created_by")
    raw_id_fields = ("content_type",)
    ordering = ("-updated_at",)


class CustomObjectPermissionInline(admin.TabularInline):
    model = CustomObjectPermission
    extra = 0
    fields = ("custom_object", "can_view", "can_add", "can_change", "can_delete")
    autocomplete_fields = ("custom_object",)


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(Group)
class GroupAdmin(DjangoGroupAdmin):
    inlines = (CustomObjectPermissionInline,)

@admin.register(CustomField)
class CustomFieldAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(CustomField, crm="AgentCPQ", object_type="CustomField")
    list_display = ("label", "name", "data_type", "object_type", "custom_object", "created_by", "created_at_js")
    list_filter = ("data_type", "object_type", "custom_object")
    search_fields = ("label", "name", "object_type", "crm", "custom_object__name", "custom_object__label")
    ordering = ("custom_object__label", "object_type", "label")


class CustomFieldValueInline(admin.TabularInline):
    model = CustomFieldValue
    fk_name = "record"
    extra = 0
    fields = ("field", "value", "updated_by_user", "created_at")
    readonly_fields = ("created_at",)
    raw_id_fields = ("field", "updated_by_user")


@admin.register(CustomRecord)
class CustomRecordAdmin(UTCDisplayAdmin, admin.ModelAdmin):
    list_display = (
        "custom_identifier",
        "object_label",
        "object_type",
        "created_by",
        "created_at_js",
        "updated_at_js",
    )
    list_filter = ("object_type", "created_by")
    search_fields = ("custom_identifier", "object_type__name", "object_type__label")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (CustomFieldValueInline,)

    def object_label(self, obj):
        return (obj.object_type.label or obj.object_type.name) if obj.object_type_id else "-"

    object_label.short_description = "Object"


@admin.register(CustomFieldValue)
class CustomFieldValueAdmin(UTCDisplayAdmin, admin.ModelAdmin):
    list_display = ("record", "field", "value", "updated_by_user", "created_at")
    list_filter = ("field__custom_object", "field__object_type", "updated_by_user")
    search_fields = (
        "value",
        "record__custom_identifier",
        "field__name",
        "field__label",
        "field__object_type",
        "field__crm",
    )
    raw_id_fields = ("field", "updated_by_user", "record")
    ordering = ("-created_at",)


@admin.register(PartnerProfile)
class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "partner_name", "is_partner", "created_at", "updated_at")
    list_filter = ("is_partner",)
    search_fields = ("user__username", "user__email", "partner_name")
    filter_horizontal = ("accounts", "contacts")



class LeadSourceFilter(admin.SimpleListFilter):
    """Filter leads by their free-text `source` field (Website, Referral, …).

    Django can't natively list-filter a plain CharField, so this lists the
    distinct non-empty source values actually present in the database.
    """

    title = "Source"
    parameter_name = "lead_source"

    def lookups(self, request, model_admin):
        values = (
            model_admin.model.objects.exclude(source="")
            .exclude(source__isnull=True)
            .order_by("source")
            .values_list("source", flat=True)
            .distinct()
        )
        return [(value, value) for value in values]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source__iexact=self.value())
        return queryset


class LeadAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
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
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']] + ['related_activities']
        return [(None, {'fields': fields})]
    
    search_fields = ['first_name', 'last_name', 'email', 'source', 'company']
    list_filter = ['status', LeadSourceFilter, 'created_at']

    list_display = ('first_name','last_name', 'phone', 'email', 'status', 'assigned_to', 'created_at_js', 'updated_at_js')
admin.site.register(Lead, LeadAdmin)






# class ActivityInline(admin.TabularInline):  # or admin.StackedInline
#     model = Activity
#     extra = 0  # don’t show extra empty rows
#     fields = ('activity_type', 'date', 'status')  # customize visible fields
#     show_change_link = True  # optional: show link to full edit form


class AccountAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(Account, crm="AgentCPQ", object_type="Account")
    list_display = ('tenant_id','name', 'industry', 'website', 'phone', 'created_at_js', 'updated_at_js')
    search_fields = ("tenant_id", "name", "industry", "website", "phone")
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]
admin.site.register(Account, AccountAdmin)

class ContractAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
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


class ScheduledTaskAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(ScheduledTask, crm="AgentCPQ", object_type="ScheduledTask")
    list_display = ('opportunity','status','execute_at', 'attempts', 'last_error', 'created_at_js', 'updated_at_js')
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]
admin.site.register(ScheduledTask, ScheduledTaskAdmin)


@admin.register(ScheduledEmail)
class ScheduledEmailAdmin(admin.ModelAdmin):
    list_display = ("_subject", "_to", "instance_model", "instance_id", "send_at", "status", "attempts", "updated_at")
    list_filter = ("status",)
    date_hierarchy = "send_at"
    search_fields = ("instance_model", "instance_id", "last_error")
    actions = ("cancel_selected",)

    @admin.display(description="Subject")
    def _subject(self, obj):
        try:
            return (obj.action or {}).get("email", {}).get("subject", {}).get("value", "")
        except Exception:
            return ""

    @admin.display(description="To")
    def _to(self, obj):
        try:
            recipients = (obj.action or {}).get("email", {}).get("recipients", {})
            externals = recipients.get("external") or []
            return ", ".join(str(e) for e in externals)
        except Exception:
            return ""

    @admin.action(description="Cancel selected (mark sent — no delivery)")
    def cancel_selected(self, request, queryset):
        updated = queryset.filter(status="pending").update(status="sent", last_error="Cancelled manually in admin")
        self.message_user(request, f"Cancelled {updated} pending reminder(s); they will not be sent.")


class QuoteAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(Quote, crm="AgentCPQ", object_type="Quote")
    list_display = (
        'name',
        'account',
        'opportunity',
        'net_amount',
        'status',
        'expiration_date',
        'quickbooks_invoice_id',
        'created_at_js',
        'updated_at_js',
    )
    # Required because QuoteDocumentAdmin uses autocomplete_fields=("quote",)
    search_fields = ('name', 'qteid', 'account__name', 'opportunity__name')

admin.site.register(Quote, QuoteAdmin)


class ApprovalRuleInline(admin.TabularInline):
    model = ApprovalRule
    fk_name = "workflow"
    extra = 0
    fields = ("name", "priority")
    show_change_link = True


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    fk_name = "rule"
    extra = 0
    fields = ("sequence", "approver_role")
    ordering = ("sequence",)


@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "rule_count")
    search_fields = ("name", "description")
    inlines = (ApprovalRuleInline,)

    def rule_count(self, obj):
        return obj.rules.count()

    rule_count.short_description = "Rules"


@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "workflow", "priority", "step_count")
    list_filter = ("workflow",)
    search_fields = ("name", "workflow__name")
    ordering = ("workflow__name", "-priority", "name")
    inlines = (ApprovalStepInline,)

    def step_count(self, obj):
        return obj.steps.count()

    step_count.short_description = "Steps"


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("workflow_name", "rule", "sequence", "approver_role")
    list_filter = ("rule__workflow", "approver_role")
    search_fields = ("approver_role", "rule__name", "rule__workflow__name")
    ordering = ("rule__workflow__name", "rule__name", "sequence")

    def workflow_name(self, obj):
        return obj.rule.workflow.name if obj.rule_id and obj.rule.workflow_id else "-"

    workflow_name.short_description = "Workflow"


@admin.register(QuoteApproval)
class QuoteApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "quote",
        "workflow",
        "step",
        "status",
        "approved_by",
        "approved_at",
    )
    list_filter = ("status", "workflow")
    search_fields = (
        "quote__name",
        "quote__id",
        "workflow__name",
        "step__approver_role",
        "approved_by",
    )
    raw_id_fields = ("quote",)
    ordering = ("quote__id", "workflow__name", "step__sequence")

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
        # Use picklist choices for stage
        try:
            from .models import picklist_choices
            self.fields["stage"] = forms.ChoiceField(
                choices=picklist_choices("Opportunity", "stage"),
                required=False,
                initial=getattr(self.instance, "stage", None) if getattr(self, "instance", None) else None,
                label="Stage",
            )
        except Exception:
            pass
        # Prefill with instance value when editing
        if getattr(self, 'instance', None) is not None:
            self.fields['hs_deal_id'].initial = getattr(self.instance, 'hs_deal_id', None)

    def clean_hs_deal_id(self):
        value = self.cleaned_data.get('hs_deal_id')
        if not value:
            return None
        return value

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.hs_deal_id = self.cleaned_data.get('hs_deal_id') or None
        if commit:
            obj.save()
        return obj

class OpportunityAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = OpportunityEditableForm
    list_display = ()

    def stage_label(self, obj):
        try:
            from .models import picklist_choices
            for value, label in picklist_choices("Opportunity", "stage"):
                if value == obj.stage:
                    return label
        except Exception:
            pass
        return obj.stage
    stage_label.short_description = "Stage"

    def get_list_display(self, request):
        return [
            ("stage_label" if field.name == "stage" else field.name)
            for field in self.model._meta.fields
        ]
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]

        # Agregamos hs_deal_id si no está
        if 'hs_deal_id' not in fields:
            fields.append('hs_deal_id')

        return [(None, {'fields': fields})]

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "stage":
            try:
                from .models import picklist_choices
                kwargs["choices"] = picklist_choices("Opportunity", "stage")
            except Exception:
                pass
        return super().formfield_for_choice_field(db_field, request, **kwargs)

admin.site.register(Opportunity, OpportunityAdmin)


@admin.register(Knowledge)
class KnowledgeAdmin(UTCDisplayAdmin, admin.ModelAdmin):
    list_display = ('image_preview_list', 'title', 'language', 'has_video', 'is_active', 'created_by', 'created_at_js', 'updated_at_js')
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
    )

    def _resolve_image_url(self, obj):
        if not obj:
            return ""

        try:
            if obj.image_file:
                return obj.image_file.url
        except (ValueError, AttributeError):
            # File exists but storage cannot resolve, fall back to URL field
            pass

        return getattr(obj, 'image_url', '') or ""

    def image_preview(self, obj):
        image_url = self._resolve_image_url(obj)
        if image_url:
            return format_html(
                "<img src='{}' style='max-width:320px;height:auto;border-radius:6px;' alt='Knowledge image preview'>",
                image_url,
            )
        return "No image uploaded"

    image_preview.short_description = "Image preview"

    def image_preview_list(self, obj):
        image_url = self._resolve_image_url(obj)
        if image_url:
            return format_html(
                "<img src='{}' style='width:75px;height:75px;object-fit:cover;border-radius:4px;' alt='Knowledge thumbnail'>",
                image_url,
            )
        return "—"
    
    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, 'created_by'):
            obj.created_by = request.user
        elif hasattr(obj, 'updated_by'):
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    image_preview_list.short_description = "Preview"

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

class ProductAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    change_list_template = "admin/product/change_list.html"

    # 🔹 quitar 'created_by' de readonly_fields
    readonly_fields = ('updated_by',)
    list_display = ('name', 'sku', 'price', 'fixed_price', 'price_mode', 'is_subscription', 'is_bundle', 'is_active', 'created_at_js', 'updated_at_js')
    list_filter = ('is_active', 'is_bundle', 'is_subscription', 'price_mode')

    def get_fieldsets(self, request, obj=None):
        form = self.get_form(request, obj)()
        fields = [f for f in form.fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]

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
            #print(f"\n\n Field Name: {field_name} \n\n")
            if field_name in form.cleaned_data:
                value = form.cleaned_data[field_name]
                #print(f"\n\n Value for {field_name}: {value}\n\n")
                cf_value, _ = CustomFieldValue.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=obj.id,
                    field=field,
                )
                cf_value.value = value if value else ""
                if hasattr(cf_value, 'updated_by_user'):
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
        initial_fields = ['display_name_sku', 'price', 'family', 'is_active']
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
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]

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
class BusinessRuleAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    class BusinessRuleAdminForm(forms.ModelForm):
        conditions = forms.CharField(
            required=False,
            widget=JSONPrettyTextarea(rows=12),
            help_text="JSON list of conditions",
        )

        class Meta:
            model = BusinessRule
            fields = "__all__"

        def __init__(self, *args, **kwargs):
            kwargs.pop("user", None)
            super().__init__(*args, **kwargs)

            # Extend target_type choices to support any standard/custom object for validation rules.
            base_choices = [
                ("quote", "Quote"),
                ("quote_line", "Quote Line"),
                ("product", "Product"),
                ("multiple", "Multiple"),
            ]
            standard_choices = [
                ("lead", "Lead"),
                ("account", "Account"),
                ("contact", "Contact"),
                ("opportunity", "Opportunity"),
                ("activity", "Activity"),
                ("contract", "Contract"),
                ("subscription", "Subscription"),
                ("option", "Option"),
                ("tenant", "Tenant"),
                ("knowledge", "Knowledge"),
            ]

            custom_choices = []
            try:
                for co in CustomObject.objects.all().order_by("label", "name"):
                    value = (co.name or "").strip().lower()
                    if not value:
                        continue
                    label = (co.label or co.name).strip()
                    custom_choices.append((value, f"{label} ({co.name})"))
            except Exception:
                # If DB isn't ready (migrations/connection), still allow standard targets.
                custom_choices = []

            # Preserve any existing value even if it isn't in the choice list (backwards compatibility).
            current_value = (
                (getattr(self.instance, "target_type", None) or self.initial.get("target_type") or "")
                .strip()
                .lower()
            )
            known_values = {v for v, _ in (base_choices + standard_choices + custom_choices)}
            if current_value and current_value not in known_values:
                custom_choices.insert(0, (current_value, f"{current_value} (custom)"))

            merged = []
            seen = set()
            for value, label in base_choices + standard_choices + custom_choices:
                if value in seen:
                    continue
                seen.add(value)
                merged.append((value, label))

            if "target_type" in self.fields and hasattr(self.fields["target_type"], "choices"):
                self.fields["target_type"].choices = merged

            value = self.initial.get("conditions") or getattr(self.instance, "conditions", None)
            if isinstance(value, (dict, list)):
                self.initial["conditions"] = json.dumps(value, indent=2)
            elif isinstance(value, str) and value.strip():
                try:
                    self.initial["conditions"] = json.dumps(json.loads(value), indent=2)
                except Exception:
                    self.initial["conditions"] = value

        def clean_conditions(self):
            raw = self.cleaned_data.get("conditions")
            if raw in (None, "", "null"):
                return []
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError(f"Invalid JSON for conditions: {exc}")

        def _post_clean(self):
            """
            Extend functionality: allow BusinessRule.target_type to be any standard/custom object key,
            even though the model field has legacy `choices` that would otherwise reject it.
            """
            opts = self._meta
            exclude = set(self._get_validation_exclusions())
            exclude.add("target_type")

            try:
                self.instance = construct_instance(self, self.instance, opts.fields, opts.exclude)
            except ValidationError as e:
                self._update_errors(e)

            try:
                self.instance.full_clean(exclude=exclude, validate_unique=False)
            except ValidationError as e:
                self._update_errors(e)

            if self._validate_unique:
                self.validate_unique()

    form = BusinessRuleAdminForm
    list_display = ('name', 'rule_type', 'active', 'get_created_by', 'created_at_js')
    search_fields = ('name',)
    list_filter = ('rule_type', 'active')

    def get_created_by(self, obj):
        return obj.created_by or "-"
    get_created_by.short_description = "Created by"


class QuoteLineAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(QuoteLine, crm="AgentCPQ", object_type="QuoteLine")

    list_display = ('product_name', 'unit_price', 'quantity', 'quote', 'discount_type', 'discount_percentage', 'discount_amount', 'subtotal', 'total_price', 'created_at_js', 'updated_at_js')

    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]
    
admin.site.register(QuoteLine, QuoteLineAdmin)

@admin.register(ActionUsage)
class ActionUsageAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "user", "related_object_type", "related_object_id")
    list_filter = ("action", "related_object_type")
    search_fields = ("action", "related_object_id", "user__username")

class ContactAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    # build a dynamic ModelForm for AgentCPQ → Contact
    form = get_dynamic_form(Contact, crm="AgentCPQ", object_type="Contact")

    # expose every form field in a single fieldset
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]

    # tweak these to match your actual model columns
    list_display = (
        'first_name',
        'last_name',
        'email',
        'phone',
        'account',        # drop if not on the model
        'created_at_js',     # idem
    )

    # optional niceties
    search_fields = ('first_name', 'last_name', 'email')
    list_filter   = ('created_at',)

# register with the admin site
admin.site.register(Contact, ContactAdmin)

class TenantAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(Tenant, crm="AgentCPQ", object_type="Tenant")

    readonly_fields = ("api_key_display", "api_secret_display")

    def _masked_value_widget(self, value: str, field_key: str, obj_id):
        if not value:
            return "-"
        input_id = f"tenant-secret-{field_key}-{obj_id or 'new'}"
        btn_id = f"tenant-secret-btn-{field_key}-{obj_id or 'new'}"
        return format_html(
            """
            <div style="display:flex;gap:8px;align-items:center;max-width:680px;">
              <input id="{input_id}" type="password" value="{value}" readonly
                     style="flex:1;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono','Courier New',monospace;
                            padding:6px 10px;border:1px solid #d1d5db;border-radius:10px;background:#fafafa;color:#111827;" />
              <button id="{btn_id}" type="button" class="button"
                      onclick="(function(){{var i=document.getElementById('{input_id}');var b=document.getElementById('{btn_id}');if(!i||!b) return;var show=(i.type==='password');i.type=show?'text':'password';b.textContent=show?'Hide':'Show';}})();">
                Show
              </button>
            </div>
            """,
            input_id=input_id,
            btn_id=btn_id,
            value=value,
        )

    def api_key_display(self, obj):
        return self._masked_value_widget(getattr(obj, "api_key", "") or "", "api_key", getattr(obj, "pk", None))

    api_key_display.short_description = "API Key (read-only)"

    def api_secret_display(self, obj):
        return self._masked_value_widget(getattr(obj, "api_secret", "") or "", "api_secret", getattr(obj, "pk", None))

    api_secret_display.short_description = "API Secret (read-only)"

    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        fieldsets = [(None, {'fields': fields})]
        if request.user.is_superuser:
            fieldsets.append(
                ("API Credentials", {"fields": ("api_key_display", "api_secret_display")})
            )
        return fieldsets

    list_display = ('tenant_id','name', 'plan', 'actions_limit', 'created_at_js', 'version')

admin.site.register(Tenant, TenantAdmin)
admin.site.register(EmailAlert)

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


@admin.register(PicklistValue)
class PicklistValueAdmin(admin.ModelAdmin):
    list_display = ("object_name", "field_name", "key", "label", "active", "is_default", "sort_order")
    list_filter = ("object_name", "field_name", "active", "is_default")
    search_fields = ("object_name", "field_name", "key", "label")


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


class ActionTriggerAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    class ActionTriggerAdminForm(forms.ModelForm):
        event_type = forms.CharField(
            required=False,
            widget=JSONPrettyTextarea(rows=10),
            help_text="JSON: e.g. {\"object_type\": \"quote\", \"action\": \"updated\"}",
        )
        conditions = forms.CharField(
            required=False,
            widget=JSONPrettyTextarea(rows=12),
            help_text="JSON structure for conditions",
        )
        actions = forms.CharField(
            required=False,
            widget=JSONPrettyTextarea(rows=14),
            help_text=(
                "JSON list of actions. EMAIL actions support optional `email.title` and `email.message` "
                "(inline Django template strings, e.g. \"Ingreso {{ instance.custom_identifier }} creado\"). "
                "EMAIL actions also support `email.fields` to control the 'Record Details' table (list of paths, "
                "or [{label,value}] entries), plus optional `email.fields_mode` = 'replace' (default) or 'append'."
            ),
        )

        class Meta:
            model = ActionTrigger
            fields = "__all__"

        def __init__(self, *args, **kwargs):
            # DynamicCustomFieldAdmin injects `user`; ignore it to avoid ModelForm errors.
            kwargs.pop("user", None)
            # Prefill JSON as pretty-printed text for easier editing
            super().__init__(*args, **kwargs)
            for field_name in ("event_type", "conditions", "actions"):
                value = self.initial.get(field_name) or getattr(self.instance, field_name, None)
                if isinstance(value, (dict, list)):
                    self.initial[field_name] = json.dumps(value, indent=2)
                elif isinstance(value, str) and value.strip():
                    # keep existing string but pretty print if valid JSON
                    try:
                        self.initial[field_name] = json.dumps(json.loads(value), indent=2)
                    except Exception:
                        self.initial[field_name] = value

        def _clean_json_field(self, field_name):
            raw = self.cleaned_data.get(field_name)
            if raw in (None, "", "null"):
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError(f"Invalid JSON for {field_name}: {exc}")

        def clean_event_type(self):
            return self._clean_json_field("event_type")

        def clean_conditions(self):
            return self._clean_json_field("conditions")

        def clean_actions(self):
            return self._clean_json_field("actions")

    class Media:
        css = {
            "all": [
                "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.17/codemirror.min.css",
                "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.17/theme/idea.min.css",
                "css/admin_actiontrigger_codemirror_override.css",
            ]
        }
        js = [
            "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.17/codemirror.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.17/mode/javascript/javascript.min.js",
            "js/admin_actiontrigger_codemirror.js",
        ]

    form = ActionTriggerAdminForm
    list_display = (
        "name",
        "short_event_type",
        "signal_timing",
        "priority",
        "active",
        "description",
        "created_by",
        "updated_at_js",
    )
    list_filter = ("active", "signal_timing", "created_by")
    search_fields = ("name", "description", "event_type", "actions")
    ordering = ("priority", "-updated_at")
    list_editable = ("priority", "active")

    def _format_json_snippet(self, value, max_len=80):
        if value is None or value == "":
            return "-"
        if isinstance(value, (dict, list)):
            try:
                text = json.dumps(value)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        if len(text) > max_len:
            return f"{text[:max_len]}…"
        return text

    def short_event_type(self, obj):
        return self._format_json_snippet(obj.event_type)

    short_event_type.short_description = "Event Type"

    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]
admin.site.register(ActionTrigger, ActionTriggerAdmin)

class ActionLogAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(ActionLog, crm="AgentCPQ", object_type="ActionLog")
    list_display = ('trigger_name', 'operation', 'target_model', 'event_type', 'result', 'status', 'signal_timing', 'executed_at')
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['executed_at', 'updated_at']]
        return [(None, {'fields': fields})]
admin.site.register(ActionLog, ActionLogAdmin)

class DomainEventAdmin(UTCDisplayAdmin):
    list_display = ("event_type", "object_type", "object_id", "source", "created_at_js")
    list_filter = ("event_type", "object_type", "source", "created_at")
    search_fields = ("event_type", "object_type", "object_id", "idempotency_key")
    date_hierarchy = "created_at"
    readonly_fields = (
        "event_type",
        "object_type",
        "object_id",
        "payload",
        "idempotency_key",
        "source",
        "created_at",
    )
    formfield_overrides = {
        JSONField: {"widget": JSONPrettyTextarea(rows=12)},
    }

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_fieldsets(self, request, obj=None):
        return [(None, {"fields": self.readonly_fields})]

admin.site.register(DomainEvent, DomainEventAdmin)

class CustomActionAdmin(UTCDisplayAdmin, DynamicCustomFieldAdmin):
    form = get_dynamic_form(CustomAction, crm="AgentCPQ", object_type="CustomAction")
    list_display = ('name', 'method', 'target_lookup', 'data', 'is_active', 'target_content_type_id')
    def get_fieldsets(self, request, obj=None):
        fields = [f for f in self.form().fields.keys() if f not in ['created_at', 'updated_at']]
        return [(None, {'fields': fields})]
admin.site.register(CustomAction, CustomActionAdmin)


def _infer_search_fields(model):
    """
    Build a safe default search_fields tuple for CPQ models that do not define one.
    Preference: common identifier text fields, then other text-like fields, then exact PK.
    """
    text_field_types = (
        models.CharField,
        models.TextField,
        models.EmailField,
        models.SlugField,
        models.UUIDField,
    )
    preferred_names = ("name", "label", "title", "key", "email", "username", "code")
    inferred = []

    for field_name in preferred_names:
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue
        if isinstance(field, text_field_types):
            inferred.append(field_name)

    for field in model._meta.fields:
        if isinstance(field, text_field_types) and field.name not in inferred:
            inferred.append(field.name)
        if len(inferred) >= 5:
            break

    if inferred:
        return tuple(inferred)

    # Fallback keeps the search UI available for models without text fields.
    return (f"={model._meta.pk.name}",)


def _apply_default_cpq_search_fields():
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label != "cpq":
            continue
        if getattr(model_admin, "search_fields", None):
            continue
        model_admin.search_fields = _infer_search_fields(model)


def _is_filterable_field(field):
    if getattr(field, "auto_created", False):
        return False
    if getattr(field, "choices", None):
        return True
    return isinstance(
        field,
        (
            models.BooleanField,
            models.DateField,
            models.DateTimeField,
            models.ForeignKey,
            models.OneToOneField,
        ),
    )


def _infer_list_filter_fields(model):
    """
    Build safe default list_filter fields for CPQ models without explicit filters.
    Prefer status/active/date fields, then any filterable field.
    """
    preferred_names = (
        "status",
        "is_active",
        "active",
        "created_at",
        "updated_at",
        "owner",
        "assigned_to",
        "type",
    )
    inferred = []

    for field_name in preferred_names:
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue
        if _is_filterable_field(field):
            inferred.append(field_name)

    for field in model._meta.fields:
        if field.name in inferred:
            continue
        if _is_filterable_field(field):
            inferred.append(field.name)
        if len(inferred) >= 6:
            break

    if inferred:
        return tuple(inferred)

    # Keep a filter UI available even on models without typical filterable fields.
    return (model._meta.pk.name,)


def _apply_default_cpq_list_filters():
    for model, model_admin in admin.site._registry.items():
        if model._meta.app_label != "cpq":
            continue
        if getattr(model_admin, "list_filter", None):
            continue
        model_admin.list_filter = _infer_list_filter_fields(model)


_apply_default_cpq_search_fields()
_apply_default_cpq_list_filters()

# ---------------------------------------------------------------------------
# Object Related Sections — choose which related records show on an object's form
# ---------------------------------------------------------------------------
STANDARD_OBJECT_CHOICES = [
    "Lead", "Account", "Contact", "Opportunity", "Quote", "QuoteLine",
    "Product", "Activity", "Contract", "Subscription", "Option", "Tenant", "Knowledge",
]


class ObjectRelationConfigForm(forms.ModelForm):
    """Friendly dropdowns: standard objects + custom objects (by API name)."""

    class Meta:
        model = ObjectRelationConfig
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            custom_names = list(
                CustomObject.objects.order_by("label").values_list("name", "label")
            )
        except Exception:
            custom_names = []

        choices = [(name, name) for name in STANDARD_OBJECT_CHOICES]
        choices += [(name, f"{label} ({name})" if label and label != name else name) for name, label in custom_names]

        self.fields["parent_object"] = forms.ChoiceField(
            choices=choices, help_text=ObjectRelationConfig._meta.get_field("parent_object").help_text
        )
        self.fields["related_object"] = forms.ChoiceField(
            choices=choices, help_text=ObjectRelationConfig._meta.get_field("related_object").help_text
        )
        # Suggest the lookup fields that point at the parent (custom objects only).
        link_help = ObjectRelationConfig._meta.get_field("link_field").help_text
        candidate_fields = [
            f"{name} — {label}"
            for name, label in CustomField.objects.filter(lookup_model__startswith="cpq.")
            .values_list("name", "label")[:50]
        ]
        self.fields["link_field"] = forms.CharField(
            required=False,
            help_text=link_help + (
                ("  Known lookups: " + ", ".join(candidate_fields[:12])) if candidate_fields else ""
            ),
        )
        if self.instance and self.instance.pk:
            self.fields["parent_object"].initial = self.instance.parent_object
            self.fields["related_object"].initial = self.instance.related_object


@admin.register(ObjectRelationConfig)
class ObjectRelationConfigAdmin(admin.ModelAdmin):
    form = ObjectRelationConfigForm
    list_display = ("parent_object", "related_object", "link_field", "label", "position", "is_active")
    list_editable = ("label", "position", "is_active")
    list_filter = ("parent_object", "related_object", "is_active")
    search_fields = ("parent_object", "related_object", "label", "link_field")
    ordering = ("parent_object", "position")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

# ---------------------------------------------------------------------------
# Dynamic admin entries: one per custom object (POV, G-Drive Documentation, …)
# so each behaves like a real model in the admin (browse / add / change / delete).
# ---------------------------------------------------------------------------
from cpq.dynamic_admin import patch_admin_site  # noqa: E402

patch_admin_site(admin.site)
