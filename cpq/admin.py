from django.contrib import admin
from .models import Quote, QuoteLine, Subscription, Asset, Product, Lead, Opportunity, Account, Activity, CustomObject, CustomField, Option, BusinessRule, CustomFieldValue, CustomRecord,ActionUsage,Contact
from .forms import  get_dynamic_form
from django.contrib.contenttypes.models import ContentType
from django.utils.timezone import localtime
from django.utils.html import format_html
from django.utils.text import slugify


# admin.site.register(Subscription)

# admin.site.register(Asset)

# @admin.register(CustomObject)
# class CustomObjectAdmin(admin.ModelAdmin):
#     list_display = ('name', 'label', 'description')  # Adjust as needed

# @admin.register(CustomField)
# class CustomFieldAdmin(admin.ModelAdmin):
#     list_display = ("label", "name", "data_type", "custom_object","object_type")

class DynamicCustomFieldAdmin(admin.ModelAdmin):
    def get_form(self, request, obj=None, **kwargs):
        return self.form  # Already set per model

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

class LeadAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Lead, crm="AgentCPQ", object_type="Lead")
    list_display = ('first_name','last_name', 'phone', 'email', 'status', 'assigned_to', 'created_at', 'updated_at')
admin.site.register(Lead, LeadAdmin)

class AccountAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Account, crm="AgentCPQ", object_type="Account")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(Account, AccountAdmin)


class QuoteAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Quote, crm="AgentCPQ", object_type="Quote")

admin.site.register(Quote, QuoteAdmin)
# admin.site.register(Account)

class ActivityInline(admin.TabularInline):  # or admin.StackedInline
    model = Activity
    extra = 1  # show 1 empty form by default
    fields = ['notes','activity_type','status','due_date']  # fields you want editable inline

class OpportunityAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Opportunity, crm="AgentCPQ", object_type="Opportunity")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

admin.site.register(Opportunity, OpportunityAdmin)


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

    readonly_fields = ('created_by', 'updated_by')

    def get_fieldsets(self, request, obj=None):
        form = self.get_form(request, obj)()
        return [(None, {'fields': list(form.fields.keys())})]
    
    def save_model(self, request, obj, form, change):
        if hasattr(obj, 'created_by'):
            if not change:
                obj.created_by = request.user
            else:
                original = self.model.objects.get(pk=obj.pk)
                obj.created_by = original.created_by

        super().save_model(request, obj, form, change)

        # Keep custom fields (CustomFieldValue)
        for field in CustomField.objects.filter(crm="AgentCPQ", object_type="Product"):
            field_name = field.name
            if field_name in form.cleaned_data:
                value = form.cleaned_data[field_name]
                cf_value, _ = CustomFieldValue.objects.get_or_create(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=obj.id,
                    field=field,
                )
                cf_value.value = value
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

    display_created_by.short_description = "Created by"
    display_updated_by.short_description = "Updated by"
    display_name_sku.short_description = "Product"

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
        method.short_description = field.label or field.name
        method.admin_order_field = None
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

admin.site.register(Activity, ActivityAdmin)


class OptionAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Option, crm="AgentCPQ", object_type="Option")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
    list_display = ('product_option','parent_product','is_required','min_quantity','max_quantity','default_selected')

admin.site.register(Option, OptionAdmin)
    

### Uncomment to Enable This Feature ####

# @admin.register(BusinessRule)
# class BusinessRuleAdmin(admin.ModelAdmin):
#     list_display = ('name', 'rule_type', 'active')  # replace with actual fields
#     search_fields = ('name',)
#     list_filter = ('rule_type', 'active')


class QuoteLineAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(QuoteLine, crm="AgentCPQ", object_type="QuoteLine")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(QuoteLine, QuoteLineAdmin)

# @admin.register(ActionUsage)
# class ActionUsageAdmin(admin.ModelAdmin):
#     list_display = ("timestamp", "action", "user", "related_object_type", "related_object_id")
#     list_filter = ("action", "related_object_type")
#     search_fields = ("action", "related_object_id", "user__username")

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