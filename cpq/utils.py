from django.shortcuts import render, get_object_or_404
from .models import CustomObject, CustomField, CustomRecord, CustomFieldValue, Contract
from django.contrib.contenttypes.models import ContentType
import threading
import logging

def run_async(func, *args, **kwargs):
    def wrapper():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logging.error(f"❌ Error in async signal: {e}", exc_info=True)

    threading.Thread(target=wrapper, daemon=True).start()

# def save_custom_object_values(object_name, post_data):
#     """
#     Save a custom record and its field values for a given object_name (e.g., 'payment__c').
#     """
#     try:
#         custom_object = CustomObject.objects.get(name=object_name)
#     except CustomObject.DoesNotExist:
#         raise ValueError(f"CustomObject {object_name} not found")

#     record = CustomRecord.objects.create()  # creates a new custom record instance
#     content_type = ContentType.objects.get_for_model(CustomRecord)
#     fields = CustomField.objects.filter(custom_object=custom_object)

#     for field in fields:
#         value = post_data.get(field.name)
#         if value:
#             CustomFieldValue.objects.create(
#                 field=field,
#                 content_type=content_type,
#                 object_id=record.id,
#                 value=value
#             )

#     return record  # Optional: return the created record


def create_custom_record(request, object_slug):
    custom_object = get_object_or_404(CustomObject, name__iexact=object_slug)
    custom_fields = CustomField.objects.filter(object_type=custom_object)

    if request.method == "POST":
        record = CustomRecord.objects.create(object_type=custom_object)

        for field in custom_fields:
            value = request.POST.get(field.name, '')
            CustomFieldValue.objects.create(
                record=record,
                custom_field=field,
                value=value
            )
        return redirect("success_page")

    return render(request, "create_record_form.html", {
        "custom_object": custom_object,
        "custom_fields": custom_fields,
    })



def custom_object_list_view(request, object_name):
    custom_object = get_object_or_404(CustomObject, name=object_name)
    fields = CustomField.objects.filter(custom_object=custom_object)
    content_type = ContentType.objects.get_for_model(CustomRecord)
    records = CustomRecord.objects.filter(
        customfieldvalue__field__in=fields
    ).distinct()

    rows = []
    for record in records:
        field_values = CustomFieldValue.objects.filter(
            content_type=content_type, object_id=record.id, field__in=fields
        )
        row_data = {value.field.label or value.field.name: value.value for value in field_values}
        rows.append(row_data)

    return render(request, 'custom_objects/dynamic_list.html', {
        'object_label': custom_object.label,
        'fields': fields,
        'records': rows
    })