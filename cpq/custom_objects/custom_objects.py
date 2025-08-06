from cpq.models import CustomField, CustomObject

def create_defaults_fields_for_custom_objects(custom_object):
    CustomField.objects.create(
        label = "created_at",
        name = "created_at__c",
        crm = "AgentCPQ",
        object_type = "",
        required = True,
        lookup_model = "admin.LogEntry",
        custom_object = custom_object,
        created_by = custom_object.created_by,
        updated_by = custom_object.updated_by
    )

    CustomField.objects.create(
        label = "created_by",
        name = "created_at__c",
        crm = "AgentCPQ",
        object_type = "",
        required = True,
        lookup_model = "admin.LogEntry",
        custom_object = custom_object,
        created_by = custom_object.created_by,
        updated_by = custom_object.updated_by
    )