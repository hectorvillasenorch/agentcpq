from django.contrib import admin
from .models import Quote, QuoteLine, Subscription, Asset, Product, Lead, Opportunity, Account, Activity, CustomObject, CustomField, Option, BusinessRule

admin.site.register(Quote)
admin.site.register(Account)
admin.site.register(QuoteLine)
admin.site.register(Subscription)
admin.site.register(Asset)

class ActivityInline(admin.TabularInline):  # or admin.StackedInline
    model = Activity
    extra = 1  # show 1 empty form by default
    fields = ['notes','activity_type','status','due_date']  # fields you want editable inline

class LeadAdmin(admin.ModelAdmin):
    list_display = ('leadId','first_name','last_name', 'phone', 'email', 'source', 'status', 'created_at')
    inlines = [ActivityInline]

admin.site.register(Lead, LeadAdmin)


# class AccountAdmin(admin.ModelAdmin):
#     list_display = ('name', 'industry', 'website', 'owner', 'created_at')
# admin.site.register(Account, AccountAdmin)

class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('name', 'account', 'stage', 'amount', 'owner', 'expected_close_date')

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
  

class ProductAdmin(admin.ModelAdmin):
    list_display = ('prdid','name', 'sku', 'price', 'is_subscription', 'term', 'is_bundle')
    inlines = [OptionInline]

admin.site.register(Product, ProductAdmin)


class ActivityAdmin(admin.ModelAdmin):
    list_display = ('activity_type','lead','status','due_date', 'notes')

admin.site.register(Activity,ActivityAdmin)


class OptionAdmin(admin.ModelAdmin):
    list_display = ('product_option','parent_product','is_required','min_quantity','max_quantity','default_selected')

admin.site.register(Option,OptionAdmin)




@admin.register(CustomObject)
class CustomObjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'label', 'description')  # Adjust as needed

@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "name", "data_type", "custom_object","object_type")

@admin.register(BusinessRule)
class BusinessRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'active')  # replace with actual fields
    search_fields = ('name',)
    list_filter = ('rule_type', 'active')