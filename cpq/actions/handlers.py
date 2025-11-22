import time
import logging
from django.db import transaction

logger = logging.getLogger(__name__)


class BaseHandler:
    def execute(self, *, action, payload):
        raise NotImplementedError


class CreateHandler(BaseHandler):
    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()
        values = action.data or payload.get("data", {})
        with transaction.atomic():
            instance = model.objects.create(**values)
        return {"pk": instance.pk, "created": True}


def _enforce_discount_type(values: dict) -> dict:
    """
    Si en un UPDATE vienen campos de descuento, forzar discount_type coherente.
    """
    if "discount_percentage" in values:
        values["discount_type"] = "percentage"
    elif "discount_amount" in values:
        values["discount_type"] = "amount"
    return values


class UpdateHandler(BaseHandler):
    """
    ✅ Update seguro: respeta la lógica de save() y evita loops.
    """
    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()
        lookup = action.target_lookup or payload.get("lookup")
        values = action.data or payload.get("data", {})

        if not lookup:
            raise ValueError("Falta lookup para UPDATE")

        # ✅ Enforce discount_type si corresponde
        values = _enforce_discount_type(values)

        try:
            instance = model.objects.get(**lookup)
        except model.DoesNotExist:
            return {"updated_count": 0}

        # ✅ Evitar loops
        setattr(instance, "_skip_trigger", True)

        try:
            for field, value in values.items():
                setattr(instance, field, value)

            instance.save()
        finally:
            if hasattr(instance, "_skip_trigger"):
                delattr(instance, "_skip_trigger")

        return {"updated_count": 1, "pk": instance.pk, "updated": True}


class DeleteHandler(BaseHandler):
    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()
        lookup = action.target_lookup or payload.get("lookup")
        if not lookup:
            raise ValueError("Falta lookup para DELETE")
        with transaction.atomic():
            deleted, _ = model.objects.filter(**lookup).delete()
        return {"deleted_count": deleted, "deleted": True}