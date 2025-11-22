# cpq/action_trigger/queue.py
from threading import local
from typing import List, Dict, Any
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

class _TriggerQueue(local):
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.active: bool = False

    def enable(self):
        self.active = True
        self.events = []

    def disable(self):
        self.active = False

    def push(self, *, event_type: str, instance, signal_timing: str):
        """
        Encola el evento si la cola está activa y el instance ya tiene PK.
        Guardamos (app_label.model, pk) para rehidratar desde DB en flush().
        """
        if not self.active:
            return False
        pk = getattr(instance, "pk", None)
        if pk is None:
            # No encolamos pre_save de create sin PK; esos casos se ejecutan inmediato
            return False

        model_label = instance._meta.label_lower  # p.ej. "cpq.quoteline"
        self.events.append({
            "event_type": event_type,          # "quote_line.create"
            "model_label": model_label,        # "cpq.quoteline"
            "pk": pk,                          # 123
            "timing": signal_timing,           # "post_save" | ...
        })
        return True

    def flush(self, engine):
        """
        1) Rehidrata cada instancia y ejecuta engine.handle_event(...)
        2) Junta las Quotes afectadas (por Quote y por QuoteLine)
        3) Recalcula las Quotes al final (una sola vez por PK)
        """
        if not self.events:
            self.disable()
            return

        # 1) Ejecutar eventos ya persistidos
        quotes_to_recalc = set()

        for ev in self.events:
            Model = apps.get_model(*ev["model_label"].split("."))
            instance = Model.objects.filter(pk=ev["pk"]).first()
            if not instance:
                continue

            obj, act = ev["event_type"].split(".", 1)
            engine.handle_event(
                object_type=obj,
                action=act,
                instance=instance,
                signal_timing=ev["timing"],
            )

            # 2) Detectar quotes a recalcular
            cls_name = instance.__class__.__name__
            if cls_name == "QuoteLine":
                # por línea: recalcular su quote padre
                if getattr(instance, "quote_id", None):
                    quotes_to_recalc.add(instance.quote_id)
            elif cls_name == "Quote":
                quotes_to_recalc.add(instance.pk)

        # 3) Recalcular quotes afectadas (una sola pasada, al final)
        Quote = apps.get_model("cpq", "Quote")
        for qid in quotes_to_recalc:
            q = Quote.objects.filter(pk=qid).first()
            if not q:
                continue
            try:
                # Evita loops de señales durante este guardado
                setattr(q, "_skip_trigger", True)

                q.subtotal = q.get_subtotal_amount()
                q.update_discount_fields()
                q.update_net_amount()
                q.save(update_fields=[
                    "subtotal", "discount_percentage", "discount_amount",
                    "net_amount", "tax_amount", "tax_percentage", "updated_at"
                ])
                logger.debug("🔁 Recalculated Quote(pk=%s) in TriggerQueue.flush()", qid)
            finally:
                if hasattr(q, "_skip_trigger"):
                    delattr(q, "_skip_trigger")

        # Limpiar y desactivar
        self.events = []
        self.disable()

TriggerQueue = _TriggerQueue()
