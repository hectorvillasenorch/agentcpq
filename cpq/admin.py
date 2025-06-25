from django.contrib import admin
from .models import Quote, QuoteLine, Subscription, Asset, Product, Lead, Opportunity, Account, Activity, Tenant

admin.site.register(Quote)
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


class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'industry', 'website', 'owner', 'created_at')
admin.site.register(Account, AccountAdmin)

class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('name', 'account', 'stage', 'amount', 'owner', 'expected_close_date')

admin.site.register(Opportunity, OpportunityAdmin)

class ProductAdmin(admin.ModelAdmin):
    list_display = ('prdid','name', 'sku', 'price', 'is_subscription', 'term', 'is_bundle')

admin.site.register(Product, ProductAdmin)

class ActivityAdmin(admin.ModelAdmin):
    list_display = ('activity_type','lead','status','due_date', 'notes')

admin.site.register(Activity,ActivityAdmin)
