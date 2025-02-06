from django.contrib import admin
from .models import Quote, QuoteLine, Subscription, Asset, Product

admin.site.register(Quote)
admin.site.register(QuoteLine)
admin.site.register(Subscription)
admin.site.register(Asset)
admin.site.register(Product)