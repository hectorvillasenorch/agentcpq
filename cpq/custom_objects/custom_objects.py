from cpq.models import CustomRecord, CustomFieldValue, CustomField
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

def create_defaults_fields_for_custom_objects(custom_object):
    CustomField.objects.create(
        label = "custom_identifier",
        name = "custom_identifier__c",
        crm = "AgentCPQ",
        object_type = custom_object.name,
        required = False,
        lookup_model = "admin.LogEntry",
        custom_object = custom_object,
        created_by = custom_object.created_by,
        updated_by = custom_object.updated_by
    )

def set_custom_indentifier(record):

    # Obtener el campo custom_identifier para el custom object del record
    custom_indentifier_field = CustomField.objects.get(
        name="custom_identifier__c", 
        custom_object=record.object_type
    )

    # Buscar si hay otros CustomRecord con el mismo object_type
    other_records = CustomRecord.objects.filter(object_type=record.object_type).exclude(id=record.id)
    
    # Obtener el prefijo según el label del objeto (3 letras o 1 si es menor)
    label = record.object_type.label if hasattr(record.object_type, 'label') else record.object_type.name
    prefix = label[:3].upper() if len(label) >= 3 else label[:1].upper()

    if not other_records.exists():
        # No hay otros registros: crear CustomFieldValue con valor 'PREFIX-00001'
        value = f"{prefix}-00001"
    else:
        # Hay otros registros: obtener el último por created_at
        last_record = other_records.order_by('-created_at').first()
        # Buscar el CustomFieldValue del último registro para el campo custom_identifier_field
        last_cfv = CustomFieldValue.objects.filter(
            field=custom_indentifier_field,
            record=last_record
        ).order_by('-created_at').first()

        if last_cfv and last_cfv.value:
            # Extraer el número del valor del último cfv (por ejemplo, de 'VEH-00076' sacar 76)
            try:
                last_number = int(last_cfv.value.split('-')[-1])
            except (ValueError, IndexError):
                last_number = 0
        else:
            last_number = 0

        # Incrementar en 1
        next_number = last_number + 1
        # Formatear con 5 dígitos rellenos con ceros
        number_part = str(next_number).zfill(5)
        value = f"{prefix}-{number_part}"

    # Create the associated CustomFieldValues.
    content_type = ContentType.objects.get_for_model(CustomRecord)

    # Crear nuevo CustomFieldValue para el record actual
    new_cfv = CustomFieldValue(
        field=custom_indentifier_field,
        record=record,
        value=value,
        content_type=content_type,
        object_id=record.object_type.id,
    )
    new_cfv.save()

    # Opcional: actualizar el campo custom_identifier en CustomRecord si existe
    record.custom_identifier = value
    record.save(update_fields=['custom_identifier'])

    return value
