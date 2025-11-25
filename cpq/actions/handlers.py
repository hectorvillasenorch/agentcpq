import logging
from django.db import transaction

from .helpers_filters import apply_filters
from .helpers_values import resolve_value_fields

logger = logging.getLogger(__name__)


class BaseHandler:
    def execute(self, *, action, payload):
        raise NotImplementedError


# ==========================================================
#  CREATE HANDLER (single + bulk)
# ==========================================================

class CreateHandler(BaseHandler):
    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()

        value_fields = action.data.get("fields", {})
        filters = action.target_filters  # lista de dicts si bulk

        # BULK CREATE
        if filters:
            queryset = apply_filters(model.objects.all(), filters)
            created = []
            with transaction.atomic():
                for source in queryset:
                    final_values = resolve_value_fields(value_fields, source)
                    inst = model.objects.create(**final_values)
                    created.append(inst.pk)
            return {"created_count": len(created), "pks": created}

        # NORMAL CREATE
        with transaction.atomic():
            final_values = resolve_value_fields(value_fields)
            inst = model.objects.create(**final_values)

        return {"pk": inst.pk, "created": True}


# ==========================================================
#  UPDATE HANDLER (single + bulk)
# ==========================================================

class UpdateHandler(BaseHandler):

    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()
        filters = action.target_filters

        value = action.data  # {"type": "...", "...": ...}

        # BULK UPDATE
        if filters:
            queryset = apply_filters(model.objects.all(), filters)
            updated = 0

            with transaction.atomic():
                for obj in queryset:
                    setattr(obj, "_skip_trigger", True)
                    try:
                        # value for bulk update is ONE field update
                        final = resolve_value_fields({"value": value}, obj)
                        obj.value = final["value"]
                        obj.save()
                        updated += 1
                    finally:
                        delattr(obj, "_skip_trigger")

            return {"updated_count": updated}

        # SINGLE UPDATE
        lookup = action.target_lookup
        if not lookup:
            raise ValueError("Falta lookup para UPDATE single")

        try:
            inst = model.objects.get(**lookup)
        except model.DoesNotExist:
            return {"updated_count": 0}

        setattr(inst, "_skip_trigger", True)
        try:
            # resolve dynamic value
            resolved = resolve_value_fields({"value": value}, inst)
            inst.value = resolved["value"]
            inst.save()
        finally:
            delattr(inst, "_skip_trigger")

        return {"updated_count": 1, "pk": inst.pk}


# ==========================================================
#  DELETE (same as before)
# ==========================================================

class DeleteHandler(BaseHandler):
    def execute(self, *, action, payload):
        model = action.target_content_type.model_class()
        lookup = action.target_lookup
        with transaction.atomic():
            deleted, _ = model.objects.filter(**lookup).delete()
        return {"deleted_count": deleted}
