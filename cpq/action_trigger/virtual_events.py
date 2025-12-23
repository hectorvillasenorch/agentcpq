# cpq/action_trigger/virtual_events.py
from django.db import transaction
import threading
import logging

logger = logging.getLogger(__name__)

_local = threading.local()


class VirtualEventCollector:
    """
    Acumula eventos virtuales de negocio (__c) durante una transacción.
    NO ejecuta triggers.
    NO conoce el TriggerEngine.
    SOLO almacena intención de evento.
    """

    def __init__(self):
        # key = (object_name, instance_pk)
        self._events = {}

    def add(self, *, object_name: str, instance, action: str, source: str = None):
        if not object_name or not instance or not action:
            return

        key = (object_name, instance.pk)

        existing = self._events.get(key)

        # --------------------------------------------------
        # 🔑 PRIORIDAD DE ACCIONES:
        # CREATE > UPDATE > DELETE
        # --------------------------------------------------
        if existing:
            prev_action = existing.get("action")

            # Si ya tenemos CREATE, no lo pisamos
            if prev_action == "create":
                return

            # Si llega CREATE, siempre gana
            if action == "create":
                pass  # sobreescribe

            # Si llega UPDATE pero ya hay UPDATE, sobreescribe (última gana)
            elif action == "update" and prev_action == "update":
                pass

            # DELETE siempre gana (opcional, pero correcto)
            elif action == "delete":
                pass

            else:
                return

        self._events[key] = {
            "object_name": object_name,
            "instance": instance,
            "action": action,
            "source": source,
        }

        logger.debug(
            "🧩 [VirtualEventCollector] queued %s.%s (pk=%s, source=%s)",
            object_name,
            action,
            instance.pk,
            source,
        )

    def flush(self):
        """
        Devuelve y limpia los eventos acumulados.
        """
        events = list(self._events.values())
        self._events.clear()

        if events:
            logger.debug(
                "🚚 [VirtualEventCollector] flushing %s event(s)",
                len(events),
            )

        return events


def get_collector() -> VirtualEventCollector:
    """
    Devuelve el collector de este thread/request.
    """
    if not hasattr(_local, "collector"):
        _local.collector = VirtualEventCollector()
    return _local.collector

def schedule_flush_on_commit():
    """
    Programa el flush del collector al finalizar la transacción.
    Se puede llamar múltiples veces sin problema.
    """
    try:
        transaction.on_commit(_flush_collector_safe)
    except Exception:
        # Si no hay transacción activa, no hacemos nada
        pass


def _flush_collector_safe():
    """
    Flush post-commit.
    A PARTIR DE AQUÍ se ejecutan eventos virtuales en el TriggerEngine.
    """
    collector = get_collector()
    events = collector.flush()

    if not events:
        return

    from cpq.action_trigger.trigger_engine import engine

    for e in events:
        event_name = f"{e['object_name']}.{e['action']}"

        logger.debug(
            "🚀 [VirtualEvent] DISPATCH → %s (pk=%s, source=%s)",
            event_name,
            e["instance"].pk,
            e.get("source"),
        )

        try:
            engine.handle_virtual_event(
                event_name=event_name,
                instance=e["instance"],
                source=e.get("source"),
            )
        except Exception:
            logger.exception(
                "❌ Error executing virtual event %s (pk=%s)",
                event_name,
                e["instance"].pk,
            )