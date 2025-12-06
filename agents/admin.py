from django.contrib import admin

from .models import SingleRecordLayout


@admin.register(SingleRecordLayout)
class SingleRecordLayoutAdmin(admin.ModelAdmin):
    list_display = ("user", "object_name", "updated_at")
    list_filter = ("object_name", "user")
    search_fields = ("user__username", "object_name")
    ordering = ("-updated_at",)
