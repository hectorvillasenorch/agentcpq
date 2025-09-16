from cpq.models import CustomRecord, CustomFieldValue, CustomField
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


def set_custom_indentifier(record):

    # Search if exists others custom records with the same object_type
    other_records = CustomRecord.objects.filter(object_type=record.object_type).exclude(id=record.id)

    # Create prefix from label object (3 letters or 1 if is minor)
    label = record.object_type.label if hasattr(record.object_type, 'label') else record.object_type.name
    prefix = label[:3].upper() if len(label) >= 3 else label[:1].upper()

    if not other_records.exists():
        # No hay otros registros: crear CustomFieldValue con valor 'PREFIX-00001'
        value = f"{prefix}-00001"
    else:
        # Hay otros registros: obtener el último por created_at
        last_record = other_records.order_by('-created_at').first()

        if last_record:
            # Extraer el número del valor del último cfv (por ejemplo, de 'VEH-00076' sacar 76)
            try:
                last_number = int(last_record.custom_identifier.split('-')[-1])
            except (ValueError, IndexError):
                last_number = 0
        else:
            last_number = 0

        # Incrementar en 1
        next_number = last_number + 1
        # Formatear con 5 dígitos rellenos con ceros
        number_part = str(next_number).zfill(5)
        value = f"{prefix}-{number_part}"

    record.custom_identifier = value
    record.save(update_fields=['custom_identifier'])

    return value
