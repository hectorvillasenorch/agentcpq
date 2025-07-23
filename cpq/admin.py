from django.contrib import admin
from .models import Quote, QuoteLine, Subscription, Asset, Product, Lead, Opportunity, Account, Activity, CustomObject, CustomField, Option, BusinessRule, CustomFieldValue, CustomRecord,ActionUsage,Contact,Tenant, ChatMessage, ChatSession
from .forms import  get_dynamic_form
from django.contrib.contenttypes.models import ContentType

# admin.site.register(Subscription)
# admin.site.register(Asset)

@admin.register(CustomObject)
class CustomObjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'label', 'description')  # Adjust as needed

@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "name", "data_type", "custom_object","object_type")

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
    list_display = ('tenant_id','name', 'industry', 'website', 'phone', 'created_at', 'updated_at')
    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]
admin.site.register(Account, AccountAdmin)


class QuoteAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Quote, crm="AgentCPQ", object_type="Quote")
    list_display = ('name','account', 'opportunity', 'net_amount', 'status', 'expiration_date', 'created_at', 'updated_at')

admin.site.register(Quote, QuoteAdmin)
# admin.site.register(Account)

class ActivityInline(admin.TabularInline):  # or admin.StackedInline
    model = Activity
    extra = 1  # show 1 empty form by default
    fields = ['notes','activity_type','status','due_date']  # fields you want editable inline

class OpportunityAdmin(DynamicCustomFieldAdmin):
    form = get_dynamic_form(Opportunity, crm="AgentCPQ", object_type="Opportunity")
    list_display = ('name','amount', 'account', 'stage', 'expected_close_date', 'primary_quote', 'created_at')
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
    form = get_dynamic_form(Product, crm="AgentCPQ", object_type="Product")

    def get_fieldsets(self, request, obj=None):
        return [(None, {'fields': list(self.form().fields.keys())})]

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

@admin.register(BusinessRule)
class BusinessRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'active')  # replace with actual fields
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

class ChatSessionAdmin(DynamicCustomFieldAdmin):
    list_display = ('title','user', 'session_id','created_at')
    
admin.site.register(ChatSession, ChatSessionAdmin)

class ChatMessageAdmin(DynamicCustomFieldAdmin):
    list_display = ('session','sender', 'timestamp')
    
admin.site.register(ChatMessage, ChatMessageAdmin)