# cpq/action_trigger/trigger_engine.py
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Tuple, Optional

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from datetime import datetime, date
from decimal import Decimal
import re

from cpq.actions.executor import CustomActionExecutor
from cpq.models import ActionLog, CustomObject, CustomField, CustomFieldValue, CustomRecord

# Get email handler
from cpq.action_trigger.email.email_action import execute_email_action

# Import helpers and format
from cpq.action_trigger.helpers.helpers_and_format import (
    normalize_model_name,
    to_camel_case,
    debug_alias_map,
    normalize_number,
    make_json_safe,
    get_model_class,
    get_next_custom_identifier
)


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TriggerEngine:
    def __init__(self):
        self.action_handlers = {
            "SET": self._handle_set,
            "UPDATE": self._handle_set,
            "CREATE": self._handle_create,
            "CLONE": self._handle_clone,
            "DELETE": self._handle_delete,
            "EMAIL": self._handle_email,
            "WEBHOOK": self._handle_webhook,
        }
        self._connected_models = set()
        self._trigger_listener_registered = False

        # ✅ Anti-Loop global (industrial grade)
        self._processing_events = set()

    # ----------------------------------------------------------------------
    # Wrappers: keep backward compatibility with old method names
    # ----------------------------------------------------------------------
    def _normalize_model_name(self, name: str) -> str:
        return normalize_model_name(name)

    def _to_camel_case(self, snake: str) -> str:
        return to_camel_case(snake)

    def _debug_alias_map(self, alias_map):
        return debug_alias_map(alias_map)

    def _normalize_number(self, value):
        return normalize_number(value)

    def _make_json_safe(self, obj):
        return make_json_safe(obj)

    def _get_model_class(self, model_name_snake: str):
        return get_model_class(model_name_snake)

    def register_signals(self):
        """Registers listeners for CPQ app models (pre/post save/delete)."""

        from django.db.models.signals import pre_save, post_save, pre_delete, post_delete

        self._register_trigger_change_listener()

        models_to_watch = self._get_models_with_active_triggers()

        for model in models_to_watch:
            if model in self._connected_models:
                continue
            pre_save.connect(self._make_signal_receiver("pre_save"), sender=model, weak=False)
            pre_delete.connect(self._make_signal_receiver("pre_delete"), sender=model, weak=False)
            post_save.connect(self._make_signal_receiver("post_save"), sender=model, weak=False)
            post_delete.connect(self._make_signal_receiver("post_delete"), sender=model, weak=False)
            self._connected_models.add(model)

        logger.info(
            "⚙️ TriggerEngine: señales registradas para %d modelos con triggers activos",
            len(self._connected_models),
        )
    
    def _make_signal_receiver(self, timing: str):
        """
        Receiver con ejecución deduplicada mediante execution_fingerprint.
        """
        def _receiver(sender, instance, **kwargs):
            # Snapshot original instance for update comparisons
            self._attach_original_snapshot(sender, instance, timing, kwargs)
            # --------------------------------------------------------------
            # 1) Obtener o generar execution_fingerprint para este evento
            # --------------------------------------------------------------
            fingerprint = getattr(instance, "_trigger_fingerprint", None)

            if not fingerprint:
                fingerprint = uuid.uuid4().hex
                setattr(instance, "_trigger_fingerprint", fingerprint)

            # Estructura global donde guardamos eventos ya ejecutados
            if not hasattr(self, "_executed_fingerprints"):
                self._executed_fingerprints = set()

            # --------------------------------------------------------------
            # 3) Determinar acción (create / update / delete)
            # --------------------------------------------------------------
            created = kwargs.get("created", None)
            if timing in ("pre_delete", "post_delete"):
                action = "DELETE"
            elif created is True:
                action = "CREATE"
            else:
                action = "UPDATE"

            # --------------------------------------------------------------
            # 4) EVENTO TÉCNICO (modelo real)
            # --------------------------------------------------------------
            real_object_type = self._normalize_model_name(sender.__name__)
            real_event_type = f"{real_object_type}.{action.lower()}"

            # --------------------------------------------------------------
            # 5) EVENTOS VIRTUALES (Custom Objects)
            # --------------------------------------------------------------
            virtual_events = self._resolve_virtual_events(sender, instance, action)

            events_to_process = []

            # Evento técnico (opcional, pero lo dejamos)
            events_to_process.append({
                "object_type": real_object_type,
                "action": action.lower(),
                "instance": instance,
            })

            # Eventos virtuales (negocio)
            for ve in virtual_events:
                events_to_process.append({
                    "object_type": ve["object_type"],
                    "action": ve["action"].lower(),
                    "instance": ve["instance"],
                })

            # --------------------------------------------------------------
            # 6) Ejecutar TODOS los eventos resueltos
            # --------------------------------------------------------------
            for evt in events_to_process:
                evt_type = f"{evt['object_type']}.{evt['action']}"

                ActionTrigger = apps.get_model("cpq", "ActionTrigger")
                active_triggers = [
                    t for t in ActionTrigger.objects.filter(active=True, signal_timing=timing)
                    if self._event_type_matches(t.event_type, evt_type)
                ]

                if not active_triggers:
                    logger.debug(f"\n🕐 SIGNAL [{timing.upper()} → {evt_type}] — No trigger actions\n")
                    continue

                logger.debug(
                    "\n" + "=" * 80 +
                    f"\n⚡ Trigger fired [{timing.upper()} → {evt_type}]\n"
                    f"   📦 Model: {sender.__name__}\n"
                    f"   🧩 Virtual Object: {evt['object_type']}\n"
                    f"   🔑 PK: {getattr(evt['instance'], 'pk', None)}\n"
                    f"   🕐 Instance: {evt['instance']}\n" +
                    "=" * 80
                )

                # ----------------------------------------------------------
                # Anti-loop: registrar fingerprint
                # ----------------------------------------------------------
                self._executed_fingerprints.add(fingerprint)

                try:
                    self._execute_event(
                        evt_type,
                        evt["instance"],     # 👈 IMPORTANTE: CustomRecord
                        timing
                    )
                except Exception as exc:
                    logger.exception(
                        "❌ Error handling event %s (%s): %s", evt_type, timing, exc
                    )

        return _receiver
    
    # ----------------------------------------------------------------------
    # 🧠 EVENT VIRTUALIZATION (Custom Objects)
    # ----------------------------------------------------------------------
    def _resolve_virtual_events(self, sender, instance, action: str):
        """
        Traduce signals técnicos (CustomRecord / CustomFieldValue)
        a eventos de negocio (<custom_object>__c.ACTION)

        Retorna lista de:
            {
                "object_type": str,
                "action": str,
                "instance": Model
            }
        """
        virtual_events = []

        # --------------------------------------------------
        # 🧩 CustomRecord → <custom_object>__c.(CREATE|UPDATE|DELETE)
        # --------------------------------------------------
        if isinstance(instance, CustomRecord):
            try:
                custom_object_name = instance.object_type.name
                virtual_events.append({
                    "object_type": custom_object_name,
                    "action": action.upper(),
                    "instance": instance,
                })
            except Exception:
                pass

        return virtual_events

    def _attach_original_snapshot(self, sender, instance, timing: str, kwargs):
        """
        Cache a copy of the DB row before changes to allow previous-value comparisons.
        Only applies on updates (existing pk) to avoid extra work on creates.
        """
        if getattr(instance, "_trigger_original", None) is not None:
            return

        is_delete = timing in ("pre_delete", "post_delete")
        created_flag = kwargs.get("created", None)

        # Skip if no PK (new instance) or we already know it's a create
        if not getattr(instance, "pk", None):
            return
        if created_flag is True and not is_delete:
            return

        try:
            original = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            return
        setattr(instance, "_trigger_original", original)

    def _execute_event(self, event_type: str, instance: Model, signal_timing: str):
        self.handle_event(
            object_type=event_type.split(".")[0],
            action=event_type.split(".")[1],
            instance=instance,
            signal_timing=signal_timing,
        )

    def _get_models_to_watch(self) -> List[Model]:
        """
        Returns only the CPQ app models that should be observed for signals.
        Automatically excludes models listed in the blacklist.
        """
        app_label = getattr(settings, "CPQ_APP_LABEL", "cpq")
        app_config = apps.get_app_config(app_label)

        # 🧱 blacklist (hardcoded)
        blacklist = {
            "action_log",
            "actiontrigger",
            "action_usage",
            "customfield",
            "customobject",
            "emailalertlog",
            "quote_ui_render",
            "quote_document_settings",
            "tenant",
            "tenantusagelog",
            "tenantusagereport",
        }

        all_models = list(app_config.get_models())

        models_to_watch = [
            m for m in all_models
            if self._normalize_model_name(m.__name__) not in blacklist
        ]

        logger.debug(
            "📊 Modelos CPQ detectados: %d | Incluidos: %d | Excluidos: %s",
            len(all_models),
            len(models_to_watch),
            ", ".join(sorted(blacklist))
        )

        return models_to_watch

    def _get_models_with_active_triggers(self) -> List[Model]:
        """
        Returns models that have at least one active ActionTrigger for their object_type.
        Falls back to the full list (minus blacklist) if none found to preserve behavior.
        """
        ActionTrigger = apps.get_model("cpq", "ActionTrigger")
        object_types = set()
        try:
            for t in ActionTrigger.objects.filter(active=True).only("event_type"):
                obj = self._extract_object_type(t.event_type)
                if obj:
                    object_types.add(obj)
        except Exception as exc:
            # Production safety: during first deploy/migrations the table may not exist yet.
            # Do not crash the whole app on startup; simply skip dynamic trigger wiring.
            try:
                from django.db import ProgrammingError, OperationalError
                if isinstance(exc, (ProgrammingError, OperationalError)):
                    logger.warning(
                        "⚠️ TriggerEngine: could not query ActionTrigger table yet (%s). "
                        "Skipping dynamic trigger wiring until migrations run.",
                        exc,
                    )
                    return self._get_models_to_watch()
            except Exception:
                pass
            raise

        models: List[Model] = []
        for obj in object_types:
            model = self._get_model_class(obj)
            if model:
                models.append(model)

        if models:
            return models

        # Fallback to previous behavior if no active triggers found
        return self._get_models_to_watch()

    def _extract_object_type(self, event) -> Optional[str]:
        if isinstance(event, dict):
            return self._normalize_model_name(event.get("object_type") or "")
        if isinstance(event, str) and "." in event:
            return self._normalize_model_name(event.split(".")[0])
        return None

    def _register_trigger_change_listener(self):
        """Auto-refresh signal registrations when ActionTriggers are created/updated/deleted."""
        if self._trigger_listener_registered:
            return

        from django.db.models.signals import post_save, post_delete

        ActionTrigger = apps.get_model("cpq", "ActionTrigger")

        def _refresh_signals(sender, **kwargs):
            # Recompute models with active triggers and connect any new ones
            models = self._get_models_with_active_triggers()
            for m in models:
                if m in self._connected_models:
                    continue
                from django.db.models.signals import pre_save, post_save as ps, pre_delete, post_delete as pd
                pre_save.connect(self._make_signal_receiver("pre_save"), sender=m, weak=False)
                pre_delete.connect(self._make_signal_receiver("pre_delete"), sender=m, weak=False)
                ps.connect(self._make_signal_receiver("post_save"), sender=m, weak=False)
                pd.connect(self._make_signal_receiver("post_delete"), sender=m, weak=False)
                self._connected_models.add(m)

        post_save.connect(_refresh_signals, sender=ActionTrigger, weak=False)
        post_delete.connect(_refresh_signals, sender=ActionTrigger, weak=False)
        self._trigger_listener_registered = True

    # -------------------------------------------------------------------------
    # Main entry point for an event
    # -------------------------------------------------------------------------
    def handle_event(self, object_type: str, action: str, instance: Model, signal_timing: str = "post_save"):
        """
        Procesa un evento usando el sistema anti-duplicados basado en fingerprint.
        """
        event_type = f"{object_type}.{action}"
        logger.debug(f"⚙️ Processing triggers for event {event_type} [{signal_timing}]")

        # ------------------------------------------------------------------
        # 🔒 GUARD: Custom Objects solo se ejecutan vía eventos virtuales
        # ------------------------------------------------------------------
        if object_type.endswith("__c") and signal_timing != "virtual":
            logger.debug(
                "⛔ Skipping NON-virtual trigger for CustomObject %s (%s)",
                object_type,
                signal_timing,
            )
            return []

        from django.db import transaction

        is_custom_object_create = (
            object_type.endswith("__c")
            and action == "create"
        )

        # ----------------------------------------------------------------------
        # ✅ Anti-Loop: bloquear reentradas mientras este evento está en proceso
        # ----------------------------------------------------------------------
        event_key = f"{object_type}.{action}:{instance.pk}"

        if event_key in self._processing_events:
            logger.debug(f"⛔ Prevented recursive trigger for {event_key}")
            return []

        self._processing_events.add(event_key)

        triggers = self._load_active_triggers_for_event(event_type, signal_timing)
        results = []

        if not triggers:
            logger.debug(f"🚫 No triggers activos para {event_type} ({signal_timing})\n\n")
            return results

        logger.debug(f"📦 Ejecutando {len(triggers)} trigger(s) activos para {event_type} ({signal_timing})")

        # ------------------------------------------------------------------
        # ⭐ Recuperar el fingerprint (ya viene desde el receiver)
        # ------------------------------------------------------------------
        fingerprint = getattr(instance, "_trigger_fingerprint", None)
        if not fingerprint:
            fingerprint = uuid.uuid4().hex
            setattr(instance, "_trigger_fingerprint", fingerprint)

        # Evitar loops internos por guardados derivados
        original_skip = getattr(instance, "_skip_trigger", False)
        setattr(instance, "_skip_trigger", True)

        quotes_to_recalc = set()

        # Si el evento es sobre quote o quote_line, registrar quote afectada
        if instance.__class__.__name__ == "QuoteLine" and getattr(instance, "quote_id", None):
            quotes_to_recalc.add(instance.quote_id)
        elif instance.__class__.__name__ == "Quote":
            quotes_to_recalc.add(instance.pk)

        # ==============================================================
        # ✅ EJECUCIÓN ATÓMICA REAL
        # ==============================================================
        from django.db import transaction

        failed_context = None   # ✅ guardamos info del error aquí


        def _execute_triggers():
            failed_context = None

            try:
                with transaction.atomic():

                    for trig in triggers:
                        try:
                            matched, context = self._evaluate_trigger(trig, instance)
                            if not matched:
                                continue

                            # --------------------------------------------------
                            # 🧩 Inyectar metadata del evento
                            # --------------------------------------------------
                            context["_event"] = self._build_event_context(
                                object_type=object_type,
                                action=action,
                                instance=instance,
                                signal_timing=signal_timing,
                            )

                            context["_trigger"] = trig
                            try:
                                exec_results = self._execute_trigger_actions(trig, instance, context)
                            finally:
                                # Limpieza garantizada, pase lo que pase
                                context.pop("_trigger", None)

                            results.append({
                                "trigger_id": getattr(trig, "id", None),
                                "results": exec_results
                            })

                            def log_success():
                                try:
                                    operation, target_model = self._resolve_operation_and_target_from_trigger(trig)

                                    exists = ActionLog.objects.filter(
                                        trigger_name=trig.name,   # ✅ ahora cada trigger es único
                                        target_pk=str(instance.pk),
                                        operation=operation,     # ✅ mismo tipo de acción
                                        event_type=event_type,
                                        signal_timing=signal_timing,
                                    ).exists()

                                    if exists:
                                        return  # ✅ Evita duplicado real definitivo

                                    result_payload = {"ok": True}

                                    # ✅ Extraer warnings de cualquier acción (CLONE, BULK, etc.)
                                    warnings = []

                                    for r in exec_results:
                                        action_result = r.get("result") or {}
                                        if isinstance(action_result, dict):
                                            w = action_result.get("warnings")
                                            if isinstance(w, list):
                                                warnings.extend(w)

                                    if warnings:
                                        result_payload["warnings"] = warnings

                                    ActionLog.objects.create(
                                        trigger_name=trig.name,
                                        operation=operation,
                                        target_model=target_model,
                                        target_pk=str(instance.pk),
                                        event_type=event_type,
                                        signal_timing=signal_timing,
                                        status="success",
                                        payload=exec_results,
                                        result=result_payload
                                    )

                                except Exception as log_exc:
                                    logger.exception("⚠️ Error creando ActionLog (success): %s", log_exc)

                            transaction.on_commit(log_success)

                            for action_data in (trig.actions or []):
                                raw_target = action_data.get("target")

                                # Normalizar target en string
                                if isinstance(raw_target, str):
                                    # target root model: "opportunity", "quote", "quote_line"
                                    parts = raw_target.split(".")
                                    target_root = parts[0]
                                    target_last = parts[-1]
                                elif isinstance(raw_target, dict):
                                    target_root = raw_target.get("object", "")
                                    target_last = raw_target.get("path", "").split(".")[-1] if raw_target.get("path") else target_root
                                else:
                                    target_root = ""
                                    target_last = ""

                                # ------------------------------------------------------
                                # 🟢 Detectar cuándo recalcular QUOTE
                                # ------------------------------------------------------
                                # Caso 1: target = "quote"
                                if target_root == "quote":
                                    quotes_to_recalc.add(instance.pk)

                                # Caso 2: target es quote_line
                                if target_root == "quote_line" and getattr(instance, "quote_id", None):
                                    quotes_to_recalc.add(instance.quote_id)

                                # Caso 3: target es un path que termina en "quote"
                                if target_last == "quote":
                                    quotes_to_recalc.add(instance.pk)

                                # Caso 4: target es un path que termina en "quote_line"
                                if target_last == "quote_line" and getattr(instance, "quote_id", None):
                                    quotes_to_recalc.add(instance.quote_id)

                        except Exception as exc:
                            # ✅ SOLO guardamos el error, NO escribimos BD aquí
                            failed_context = {
                                "trig": trig,
                                "exception": exc
                            }

                            logger.exception(
                                "❌ Trigger %s execution error (ROLLBACK): %s",
                                getattr(trig, "id", "?"),
                                exc
                            )

                            raise   # 🔥 fuerza rollback total del atomic

            except Exception:
                logger.exception("❌ TRANSACTION ROLLED BACK for event %s", event_type)

                # ✅ ✅ ✅ AQUÍ SÍ SE GUARDA EL ACTION LOG FAILED (FUERA DEL ATOMIC)
                if failed_context:
                    trig = failed_context["trig"]
                    exc = failed_context["exception"]

                    try:
                        operation, target_model = self._resolve_operation_and_target_from_trigger(trig)

                        ActionLog.objects.create(
                            trigger_name=trig.name,
                            operation=operation,
                            target_model=target_model,
                            target_pk=str(instance.pk),
                            event_type=f"{object_type}.{action}",
                            signal_timing=signal_timing,
                            status="failed",
                            payload={},
                            result={"error": str(exc)}
                        )
                    except Exception as log_exc:
                        logger.exception("⚠️ Error escribiendo ActionLog (failed): %s", log_exc)

                return []
            
        if is_custom_object_create:
            # 🔥 Ejecutar DESPUÉS del commit
            print(f"\n\nSe ejecuta despues de que se crean los custom fields")
            transaction.on_commit(_execute_triggers)
        else:
            # 🟢 Ejecutar como siempre
            _execute_triggers()

        # ------------------------------------------------------------------
        # Recalcular quotes afectadas
        # ------------------------------------------------------------------
        if quotes_to_recalc:
            logger.debug("🧮 quotes_to_recalc → %s", quotes_to_recalc)
            Quote = apps.get_model("cpq", "Quote")
            for qid in quotes_to_recalc:
                q = Quote.objects.filter(pk=qid).first()
                if not q:
                    logger.debug("⚠️ Quote(pk=%s) not found while recalc; skipping", qid)
                    continue

                try:
                    setattr(q, "_skip_trigger", True)
                    logger.debug(
                        "🔍 Pre-recalc (bulk) Quote(pk=%s) discounts → type=%s, perc=%s, amount=%s",
                        q.pk,
                        q.discount_type,
                        q.discount_percentage,
                        q.discount_amount,
                    )
                    q.subtotal = q.get_subtotal_amount()
                    q.update_discount_fields()
                    q.update_net_amount()

                    q.save(update_fields=[
                        "subtotal", "discount_percentage", "discount_amount",
                        "net_amount", "tax_amount", "tax_percentage", "updated_at"
                    ])

                    logger.debug(
                        "🔁 Recalculated Quote(pk=%s) after trigger execution | type=%s, perc=%s, amount=%s",
                        q.pk,
                        q.discount_type,
                        q.discount_percentage,
                        q.discount_amount,
                    )

                except Exception as e:
                    logger.exception(f"❌ Error recalculating Quote(pk={qid}): {e}")
                finally:
                    if hasattr(q, "_skip_trigger"):
                        delattr(q, "_skip_trigger")
        else:
            logger.debug("ℹ️ quotes_to_recalc is empty; no bulk quote recalc executed.")

        # ------------------------------------------------------------------
        # LIMPIEZA FINAL
        # ------------------------------------------------------------------
        if original_skip:
            setattr(instance, "_skip_trigger", original_skip)
        else:
            if hasattr(instance, "_skip_trigger"):
                delattr(instance, "_skip_trigger")

        # Eliminamos el fingerprint al final del ciclo del evento
        # para que futuros eventos NO queden bloqueados
        if hasattr(self, "_executed_fingerprints"):
            if fingerprint in self._executed_fingerprints:
                self._executed_fingerprints.remove(fingerprint)

        if hasattr(instance, "_trigger_fingerprint"):
            delattr(instance, "_trigger_fingerprint")

        # ----------------------------------------------------------------------
        # 🔄 Anti-Loop cleanup
        # ----------------------------------------------------------------------
        if event_key in self._processing_events:
            self._processing_events.remove(event_key)

        return results
    
    def handle_virtual_event(self, *, event_name: str, instance, source: str = None):
        """
        Entry point para eventos virtuales (__c).

        Traduce el evento virtual al pipeline REAL del engine.
        """

        if not event_name or not instance:
            return

        try:
            object_name, action = event_name.split(".", 1)
        except ValueError:
            logger.warning(f"⚠️ Invalid virtual event_name '{event_name}'")
            return

        logger.debug(
            "\n"
            "================================================================================\n"
            "⚡ Trigger fired [VIRTUAL → %s]\n"
            "📦 Model: CustomRecord\n"
            "🧩 Virtual Object: %s\n"
            "🔑 PK: %s\n"
            "🕐 Source: %s\n"
            "================================================================================",
            event_name,
            object_name,
            instance.pk,
            source,
        )

        # 🔥 USAR EL PIPELINE REAL QUE YA EXISTE
        self.handle_event(
            object_type=object_name,
            action=action,
            instance=instance,
            signal_timing="virtual",   # ← CLAVE
        )


    # -------------------------------------------------------------------------
    # Carga de triggers por event_type
    # -------------------------------------------------------------------------
    def _load_active_triggers_for_event(self, event_type: str, signal_timing: str):
        ActionTrigger = apps.get_model("cpq", "ActionTrigger")

        all_active = (
            ActionTrigger.objects
            .filter(active=True, signal_timing=signal_timing)
            .order_by("priority", "created_at")  # ← ORDEN CORRECTO
        )

        matches = [
            t for t in all_active
            if self._event_type_matches(t.event_type, event_type)
        ]

        if matches:
            logger.debug(
                f"📦 Found {len(matches)} active trigger(s) for {event_type} "
                f"[{signal_timing}] in priority order: {[t.priority for t in matches]}"
            )

        return matches

    def _event_type_matches(self, stored_event, incoming_event: str) -> bool:
        if isinstance(stored_event, dict):
            obj = stored_event.get("object_name")
            act = stored_event.get("action")
            return incoming_event == f"{obj}.{act}"
        if isinstance(stored_event, str):
            return stored_event == incoming_event
        return False

    # -------------------------------------------------------------------------
    # Evaluación de condiciones (incluye alias y Custom Objects)
    # -------------------------------------------------------------------------
    def _evaluate_trigger(self, trigger, instance: Model) -> Tuple[bool, Dict[str, Any]]:  # noqa: C901
        """
        Evalúa condiciones del trigger respetando lógica AND/OR.
        Soporta:
            - alias
            - custom objects
            - condiciones múltiples
            - logic: AND / OR

        Nuevo formato de condiciones:
            - Usa source / target en lugar de left / right
            - Usa field_name en lugar de path
        Mantiene compatibilidad con el formato viejo (left/right, path).
        """

        conditions = trigger.conditions or {"logic": "AND", "items": []}
        items: List[Dict[str, Any]] = conditions.get("items", []) or []
        logic = (conditions.get("logic") or "AND").upper()

        # ----------------------------------------------------------------------
        # 1) Agrupar por alias
        # ----------------------------------------------------------------------
        alias_groups = self._group_conditions_by_alias(items)

        # ----------------------------------------------------------------------
        # 2) Construir candidatos para alias (consulta de objetos)
        # ----------------------------------------------------------------------
        alias_candidates: Dict[Optional[str], List[Any]] = {}

        for alias, conds in alias_groups.items():
            # alias None → instancia principal
            if alias is None:
                alias_candidates[alias] = [instance]
                continue

            # Detectar modelo del lado "target" (nuevo) o "right" (legacy)
            target_models = []

            for c in conds:
                tgt = c.get("target") or c.get("right") or {}
                if (
                    isinstance(tgt, dict)
                    and tgt.get("type") == "field"
                    and tgt.get("object")
                ):
                    target_models.append(tgt.get("object"))

            model_name = target_models[0] if target_models else None

            if not model_name:
                logger.debug("⚠️ Alias '%s' sin modelo detectable en target.object", alias)
                return False, {}

            # Filtros: sólo condiciones == para resolver el alias
            filters: Dict[str, Any] = {}

            for c in conds:
                if c.get("operator") not in ("==", "="):
                    continue

                source_ref = c.get("source") or c.get("left") or {}
                target_ref = c.get("target") or c.get("right") or {}

                if (
                    isinstance(target_ref, dict)
                    and target_ref.get("type") == "field"
                    and target_ref.get("object") == model_name
                ):
                    expected = self._resolve_value_from_reference(
                        source_ref,
                        {None: instance},
                        instance,
                    )
                    field_key = target_ref.get("field_name") or target_ref.get("path")
                    if field_key:
                        filters[field_key] = expected

            # Buscar candidatos
            if self._is_custom_object(model_name):
                logger.debug("🔍 CustomObject lookup: %s with filters %s", model_name, filters)
                candidates = self._find_custom_object_records(model_name, filters)
            else:
                ModelClass = self._get_model_class(model_name)
                orm_filters = self._translate_filters_for_orm(filters)
                candidates = list(ModelClass.objects.filter(**orm_filters))

            if len(candidates) == 0:
                logger.debug("⛔ Alias '%s' sin candidatos (0 encontrados)", alias)
                return False, {}

            if len(candidates) > 1:
                logger.debug("⛔ Alias '%s' ambiguo (%d candidatos)", alias, len(candidates))
                return False, {}

            alias_candidates[alias] = candidates

        # ----------------------------------------------------------------------
        # 3) Resolver alias → objeto único
        # ----------------------------------------------------------------------
        alias_map = {a: objs[0] for a, objs in alias_candidates.items()}

        # ----------------------------------------------------------------------
        # 4) Evaluar condiciones individuales
        # ----------------------------------------------------------------------
        results = []

        for cond in items:
            left_ref = cond.get("source") or cond.get("left") or {}
            right_ref = cond.get("target") or cond.get("right") or {}
            op = cond.get("operator")

            left_val = self._resolve_value_from_reference(left_ref, alias_map, instance)
            right_val = self._resolve_value_from_reference(right_ref, alias_map, instance)

            ok = self._compare(left_val, right_val, op)
            results.append(ok)

            # ✔ AND: si una falla, el trigger falla
            if logic == "AND" and not ok:
                logger.debug(
                    "❌ Condición NO cumple (AND): %s %s %s (resueltos: %s %s %s)",
                    left_ref, op, right_ref, left_val, op, right_val
                )
                return False, {}

            # ✔ OR: si una es verdadera, el trigger es válido
            if logic == "OR" and ok:
                logger.debug(
                    "✅ Condición cumple (OR): %s %s %s (resueltos: %s %s %s)",
                    left_ref, op, right_ref, left_val, op, right_val
                )
                return True, alias_map

        # ----------------------------------------------------------------------
        # 5) Resultado final
        # ----------------------------------------------------------------------
        if logic == "AND":
            logger.debug("✅ Condiciones cumplidas (AND). Alias context: %s", self._debug_alias_map(alias_map))
            return True, alias_map

        if logic == "OR":
            logger.debug("❌ Ninguna condición OR cumplió")
            return False, {}

        # fallback
        return False, {}


    def _group_conditions_by_alias(self, items: List[Dict[str, Any]]) -> Dict[Optional[str], List[Dict[str, Any]]]:
        groups: Dict[Optional[str], List[Dict[str, Any]]] = {}
        for it in items:
            groups.setdefault(it.get("alias"), []).append(it)
        return groups

    # -------------------------------------------------------------------------
    # Resolución de referencias y paths
    # -------------------------------------------------------------------------
    def _resolve_value_from_reference(self, ref: Dict[str, Any], alias_map: Dict[Optional[str], Any], instance: Model):
        if not isinstance(ref, dict):
            return ref

        rtype = ref.get("type")

        # --------------------------------------------------
        # STATIC
        # --------------------------------------------------
        if rtype == "static":
            return ref.get("value")

        # --------------------------------------------------
        # DATE → usar _evaluate_date_formula (para condiciones)
        # --------------------------------------------------
        if rtype == "date":
            formula = ref.get("formula", "")
            value = self._evaluate_date_formula(formula, instance, alias_map)
            logger.debug("📅 Resolviendo DATE formula '%s' => %s", formula, value)
            return value

        # --------------------------------------------------
        # EXPRESSION → opcional, por si algún día usas expresiones en condiciones
        # --------------------------------------------------
        if rtype == "expression":
            formula = ref.get("formula", "")
            value = self._evaluate_expression(formula, instance, alias_map)
            logger.debug("🧮 Resolviendo EXPRESSION '%s' => %s", formula, value)
            return value

        # --------------------------------------------------
        # FIELD (Custom o nativo)
        # --------------------------------------------------
        if rtype == "field":
            obj_name = ref.get("object")
            field_name = ref.get("field_name")
            #path = ref.get("path")
            alias = ref.get("alias")  # Recomendado para custom

            # Allow referencing previous snapshot explicitly
            if obj_name == "previous":
                original = getattr(instance, "_trigger_original", None)
                return self._resolve_path(original, path) if original else None

            # CustomObject
            if self._is_custom_object(obj_name):
                rec = None
                if alias and alias in alias_map:
                    rec = alias_map[alias]
                else:
                    rec = self._fallback_custom_record_from_alias_map(alias_map, obj_name)

                if rec is None:
                    logger.debug("⚠️ No hay record de CustomObject '%s' en alias_map (alias='%s')", obj_name, alias)
                    return None

                value = self._resolve_custom_field_value(rec, field_name)
                logger.debug("📌 Resolviendo CustomObject: %s.%s (alias=%s) => %s", obj_name, field_name, alias, value)
                return value

            # Modelo nativo desde alias_map
            if obj_name in alias_map and alias_map[obj_name] is not None:
                return self._resolve_path(alias_map[obj_name], field_name)

            # Modelo nativo = instancia principal
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj_name == inst_name:
                return self._resolve_path(instance, field_name)

            # Buscar en otros objetos del contexto
            for rec in alias_map.values():
                if rec is not None and self._normalize_model_name(rec.__class__.__name__) == obj_name:
                    return self._resolve_path(rec, field_name)

            return None

        # --------------------------------------------------
        # PREVIOUS (explicit old value)
        # --------------------------------------------------
        if rtype == "previous":
            original = getattr(instance, "_trigger_original", None)
            path = ref.get("path")
            return self._resolve_path(original, path) if original else None

        # --------------------------------------------------
        # Sin type (left-like) → relativo al instance
        # --------------------------------------------------
        obj_name = ref.get("object")
        field_name = ref.get("field_name")
        if obj_name is None and field_name:
            return self._resolve_path(instance, field_name)

        inst_name = self._normalize_model_name(instance.__class__.__name__)
        if obj_name in (inst_name, instance.__class__.__name__.lower(), None):
            return self._resolve_path(instance, field_name)

        if obj_name in alias_map and alias_map[obj_name] is not None:
            return self._resolve_path(alias_map[obj_name], field_name)

        return None

    def _resolve_path(self, base_obj: Any, path: str):
        if base_obj is None or not path:
            return None

        parts = path.split(".")
        current = base_obj

        for idx, part in enumerate(parts):
            if current is None:
                return None

            next_part = parts[idx + 1] if idx + 1 < len(parts) else None
            self._next_custom_field = next_part  # para lookups encadenados

            if part == "id":
                # Devolver siempre la instancia completa, no el valor del ID
                self._next_custom_field = None
                return current

            if part.endswith("__c"):
                current = self._resolve_custom_field_value(current, part)
            else:
                try:
                    current = getattr(current, part)
                except Exception:
                    current = None

            if hasattr(current, "content_object"):
                current = current.content_object

            self._next_custom_field = None

        return current
    
    # -------------------------------------------------------------------------
    # ✅ NORMALIZACIÓN GLOBAL DE VALORES (ARQUITECTURA BASE)
    # -------------------------------------------------------------------------
    def _normalize_value(self, value):
        """
        Convierte automáticamente strings a su tipo real cuando sea posible:
        - "2025-12-30" → date
        - "10" → int
        - "10.5" → Decimal
        - "true" → True
        """
        if value is None:
            return None

        # Ya es tipo correcto → devolver directo
        if isinstance(value, (int, float, bool, Decimal, date, datetime)):
            return value

        if isinstance(value, str):
            v = value.strip()

            # -----------------------
            # Fecha ISO (YYYY-MM-DD)
            # -----------------------
            try:
                if "T" in v:
                    return datetime.fromisoformat(v)
                return datetime.fromisoformat(v).date()
            except Exception:
                pass

            # -----------------------
            # Booleanos
            # -----------------------
            if v.lower() in ("true", "1", "yes", "y", "t"):
                return True
            if v.lower() in ("false", "0", "no", "n", "f"):
                return False

            # -----------------------
            # Entero
            # -----------------------
            try:
                return int(v)
            except Exception:
                pass

            # -----------------------
            # Decimal
            # -----------------------
            try:
                return Decimal(v)
            except Exception:
                pass

        return value

    def _normalize_pair(self, left, right):
        """
        Normaliza ambos lados de una comparación SIEMPRE.
        Esta función es la que te blinda todo el engine.
        """
        left = self._normalize_value(left)
        right = self._normalize_value(right)
        return left, right

    # -------------------------------------------------------------------------
    # ✅ COMPARADOR NORMALIZADO (BLINDA TODO EL ENGINE)
    # -------------------------------------------------------------------------
    def _compare(self, left, right, operator: str) -> bool:
        # ✅ Normalización GLOBAL (fechas, números, strings, bool)
        left, right = self._normalize_pair(left, right)

        if operator in ("==", "="):
            return left == right

        if operator == "!=":
            return left != right

        if operator == ">":
            try:
                return left > right
            except Exception as e:
                logger.debug(f"⚠️ Error '>' comparando {left} ({type(left)}) y {right} ({type(right)}): {e}")
                return False

        if operator == "<":
            try:
                return left < right
            except Exception as e:
                logger.debug(f"⚠️ Error '<' comparando {left} ({type(left)}) y {right} ({type(right)}): {e}")
                return False

        if operator == ">=":
            try:
                return left >= right
            except Exception as e:
                logger.debug(f"⚠️ Error '>=' comparando {left} ({type(left)}) y {right} ({type(right)}): {e}")
                return False

        if operator == "<=":
            try:
                return left <= right
            except Exception as e:
                logger.debug(f"⚠️ Error '<=' comparando {left} ({type(left)}) y {right} ({type(right)}): {e}")
                return False

        if operator == "contains":
            try:
                return right in left
            except Exception as e:
                logger.debug(f"⚠️ Error 'contains' comparando {left} y {right}: {e}")
                return False

        return False

    # -------------------------------------------------------------------------
    # Ejecución de acciones
    # -------------------------------------------------------------------------
    def _execute_trigger_actions(self, trigger, instance, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Ejecuta acciones del trigger.
        TODO pasa por aquí:
        - CREATE simple
        - CREATE bulk (con action.filters)
        - UPDATE simple (SET / UPDATE de uno o varios campos con value.fields)
        - UPDATE bulk (con target.filters)
        - DELETE simple
        - DELETE bulk (con target.filters)
        - EMAIL / WEBHOOK aun no agregado al trigger

        Cambios:
        - target puede ser string path o dict (compatibilidad)
        - UPDATE simple ahora usa siempre value.fields
        """
        # ✅ Asegurar contexto raíz de CustomObject (income__c, project__c, etc.)
        self._ensure_event_root_in_context(context, instance)

        results = []

        for action in (trigger.actions or []):
            op = (action.get("operation") or "").upper()
            target = action.get("target")
            value_def = action.get("value") or {}

            # BULK filters
            action_filters = action.get("filters")  # usado en BULK CREATE / BULK CLONE
            target_filters = None
            if isinstance(target, dict):
                target_filters = target.get("filters")

            # ==================================================================
            # 🔁 BULK CLONE (usa action.filters → source_object + items[])
            # ==================================================================
            if op == "CLONE" and action_filters:
                result = self._handle_bulk_clone(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 🔁 BULK CREATE (usa action.filters → source_object + items[])
            # ==================================================================
            if op == "CREATE" and action_filters:
                result = self._handle_bulk_create(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 🔁 BULK UPDATE (usa target.filters)
            # ==================================================================
            if op == "UPDATE" and target_filters:
                result = self._handle_bulk_update(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 🔁 BULK DELETE (usa target.filters)
            # ==================================================================
            if op == "DELETE" and target_filters:
                result = self._handle_delete(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # ✅ Custom Object CREATE (target endswith __c) → usar _handle_create
            # ==================================================================
            if op == "CREATE" and isinstance(target, str) and target.endswith("__c"):
                result = self._handle_create(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # ✅ CREATE SIMPLE (sin filtros)
            # ==================================================================
            if op == "CREATE":
                model_name = None

                if isinstance(target, (str, dict)):
                    model_name = self._resolve_target_model_name(target)

                if not model_name:
                    logger.warning(f"⚠️ CREATE: no se pudo resolver modelo para target={target}")
                    continue

                ModelClass = self._get_model_class(model_name)
                if ModelClass is None:
                    logger.warning(f"⚠️ CREATE: modelo '{model_name}' no encontrado para target={target}")
                    continue

                # contexto para resolver fields
                context["_current_action"] = {
                    "target_object": model_name,
                    "target_model": ModelClass,
                }

                fields = self._resolve_value_for_action(value_def, instance, context)
                if not isinstance(fields, dict):
                    fields = {}

                # ✅ 1) Limpiar campos inválidos
                clean_fields = self._filter_model_fields(ModelClass, fields)

                # ✅ 2) Coercer ForeignKeys solo en campos reales
                final_fields = {
                    f: self._coerce_fk(ModelClass, f, v, context=context, instance=instance)
                    for f, v in clean_fields.items()
                }

                created_instance = ModelClass.objects.create(**final_fields)

                # Recalcular quote si aplica
                if model_name == "quote_line":
                    self._recalc_quote_after_create_quoteline(created_instance)

                results.append({
                    "action": action,
                    "status": "ok",
                    "result": {"pk": created_instance.pk, "created": True},
                })
                continue

            # ==================================================================
            # 🟩 CLONE SIMPLE (sin filtros)
            # ==================================================================
            if op == "CLONE":
                result = self._handle_clone(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 📝 UPDATE SIMPLE (SET) → ahora siempre con value.fields
            # ==================================================================
            if op == "UPDATE":
                # All UPDATEs (standard + custom) flow through _handle_set.
                # - New format: value.fields (multi-field) ✅
                # - Legacy format: value.type + target.path ✅
                result = self._handle_set(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 🗑️ DELETE SIMPLE (sin filtros) → borrar UNA instancia
            # ==================================================================
            if op == "DELETE":
                delete_stub = type("TempAction", (), {
                    "pk": f"temp-{uuid.uuid4().hex[:6]}",
                    "method": "DELETE",
                    "target_content_type": target_ct,
                    "target_lookup": {"pk": target_inst.pk},
                    "target_filters": None,
                    "data": {},
                    "is_active": True,
                })()
                target_inst, _ = self._resolve_target_instance_and_field(target, instance, context)
                if not target_inst:
                    continue

                result = self._handle_single_delete(target_inst)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 📧 / 🌐 EMAIL / WEBHOOK
            # ==================================================================
            if op == "EMAIL":
                result = self._handle_email(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            if op == "WEBHOOK":
                result = self._handle_webhook(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

        return results
    
    def _handle_bulk_create(self, action, instance, context):
        """
        BULK CREATE (CORREGIDO)
        - Filtra sobre source_object (NO sobre target)
        - Resuelve filtros desde action["filters"]
        - Crea un registro del target por cada source record

        Cambios:
        - Soporta field_name además de field en los filtros.
        """
        filters = action.get("filters") or {}
        source_model_name = filters.get("source_object")
        items = filters.get("items", [])

        if not source_model_name:
            return {"created": False, "reason": "source_object missing in filters"}

        SourceModel = self._get_model_class(source_model_name)
        if SourceModel is None:
            return {"created": False, "reason": f"Source model '{source_model_name}' not found"}

        target_raw = action.get("target")
        if isinstance(target_raw, str):
            target_obj_name = self._resolve_target_model_name(target_raw)
        else:
            target_obj_name = (target_raw or {}).get("object")

        TargetModel = self._get_model_class(target_obj_name)
        if TargetModel is None:
            return {"created": False, "reason": f"Target model '{target_obj_name}' not found"}

        # ----------------------------------------------------------------------
        # 1. Build ORM filters for SourceModel
        # ----------------------------------------------------------------------
        orm_filters = {}

        for f in items:
            field = f.get("field_name") or f.get("field")
            op = f.get("operator", "==")
            val_block = f.get("value", {})

            if not field:
                continue

            resolved = self._resolve_value_for_action(val_block, instance, context)
            orm_key = field.replace(".", "__")

            if op == "!=":
                orm_key = f"{orm_key}__ne"
            elif op == ">":
                orm_key = f"{orm_key}__gt"
            elif op == "<":
                orm_key = f"{orm_key}__lt"
            elif op == ">=":
                orm_key = f"{orm_key}__gte"
            elif op == "<=":
                orm_key = f"{orm_key}__lte"
            elif op == "contains":
                orm_key = f"{orm_key}__icontains"
            elif op == "in":
                orm_key = f"{orm_key}__in"

            orm_filters[orm_key] = resolved

        qs = SourceModel.objects.filter(**orm_filters)

        created_pks = []

        # ----------------------------------------------------------------------
        # 2. For each matched source record → create a target
        # ----------------------------------------------------------------------
        for source_record in qs:
            # EXTENDED CONTEXT: use exact object name for LLM paths
            local_context = dict(context)
            local_context[source_model_name] = source_record

            # Store action for FK coercion
            local_context["_current_action"] = {
                "target_object": target_obj_name,
                "target_model": TargetModel,
            }

            # Resolve CREATE fields
            fields = self._resolve_value_for_action(action.get("value", {}), instance, local_context)

            # ✅ LIMPIEZA GLOBAL
            clean_fields = self._filter_model_fields(TargetModel, fields or {})

            final_fields = {}
            for fname, raw in clean_fields.items():
                final_fields[fname] = self._coerce_fk(
                    TargetModel, fname, raw,
                    context=local_context,
                    instance=instance
                )

            obj = TargetModel.objects.create(**final_fields)
            created_pks.append(obj.pk)

            # Recalc if needed
            if target_obj_name == "quote_line":
                self._recalc_quote_after_create_quoteline(obj)

        return {
            "bulk_created": True,
            "count": len(created_pks),
            "object": target_obj_name,
            "pks": created_pks,
        }

    
    def _handle_bulk_update(self, action, instance, context):
        """
        UPDATE with filters → Bulk Update.
        Aplica los fields especificados a TODOS los registros que coincidan en el queryset.

        Cambios:
        - target puede ser string o dict
        - filtros soportan field_name además de field
        - value usa siempre value.fields
        """
        target = action.get("target") or {}
        value_def = action.get("value") or {}

        # target puede ser string o dict
        if isinstance(target, str):
            model_name = self._resolve_target_model_name(target)
            filters_list = []
        else:
            model_name = target.get("object")
            filters_list = target.get("filters") or []

        if not model_name:
            return {"updated": False, "reason": "object missing in target"}

        # Obtener ModelClass
        ModelClass = self._get_model_class(model_name)
        if ModelClass is None:
            return {"updated": False, "reason": f"Model '{model_name}' not found"}

        # ----------------------------------------------------------------------
        # 1. Construir ORM filters
        # ----------------------------------------------------------------------
        orm_filters = {}

        for f in filters_list:
            field = f.get("field_name") or f.get("field")
            operator = f.get("operator", "==")
            val_block = f.get("value", {})

            if not field:
                continue

            resolved_value = self._resolve_value_for_action(val_block, instance, context)
            orm_key = field.replace(".", "__")

            if operator == "!=":
                orm_key = f"{orm_key}__ne"
            elif operator == ">":
                orm_key = f"{orm_key}__gt"
            elif operator == "<":
                orm_key = f"{orm_key}__lt"
            elif operator == ">=":
                orm_key = f"{orm_key}__gte"
            elif operator == "<=":
                orm_key = f"{orm_key}__lte"
            elif operator == "contains":
                orm_key = f"{orm_key}__icontains"
            elif operator == "in":
                orm_key = f"{orm_key}__in"

            orm_filters[orm_key] = resolved_value

        logger.debug(f"🧩 BULK UPDATE filters ORM: {orm_filters}")

        queryset = ModelClass.objects.filter(**orm_filters)
        rows = list(queryset)
        count = len(rows)

        logger.debug(f"📌 BULK UPDATE matched {count} records in {model_name}")

        if count == 0:
            return {"updated": False, "reason": "no records matched"}

        # ----------------------------------------------------------------------
        # 2. Resolver los fields a actualizar (value.fields)
        # ----------------------------------------------------------------------
        raw_fields = self._resolve_value_for_action(value_def, instance, context)
        clean_fields = self._filter_model_fields(ModelClass, raw_fields or {})

        if not clean_fields:
            return {"updated": False, "reason": "no resolved fields"}

        updated_pks = []

        # ----------------------------------------------------------------------
        # 3. Recorrer cada registro y actualizar uno por uno
        # ----------------------------------------------------------------------
        for obj in rows:
            for field, new_value in clean_fields.items():
                coerced = self._coerce_fk(ModelClass, field, new_value, context=context, instance=obj)
                setattr(obj, field, coerced)

            setattr(obj, "_skip_trigger", True)
            obj.save(update_fields=list(clean_fields.keys()))
            delattr(obj, "_skip_trigger")

            updated_pks.append(obj.pk)
            logger.debug(f"🔧 BULK UPDATE updated {model_name}(pk={obj.pk}) fields={clean_fields}")

        # ----------------------------------------------------------
        # 🔁 Recalcular quotes afectadas (igual que en DELETE)
        # ----------------------------------------------------------
        from django.apps import apps

        if model_name == "quote_line" and hasattr(ModelClass, "quote_id"):
            unique_quote_ids = set(
                ModelClass.objects.filter(pk__in=updated_pks).values_list("quote_id", flat=True)
            )

            logger.debug(f"🔁 Recalculando {len(unique_quote_ids)} quote(s) afectadas por BULK UPDATE...")

            Quote = apps.get_model("cpq", "Quote")

            for qid in unique_quote_ids:
                q = Quote.objects.filter(pk=qid).first()
                if not q:
                    continue
                try:
                    setattr(q, "_skip_trigger", True)
                    q.subtotal = q.get_subtotal_amount()
                    q.update_discount_fields()
                    q.update_net_amount()
                    q.save(update_fields=[
                        "subtotal", "discount_percentage", "discount_amount",
                        "net_amount", "tax_amount", "tax_percentage", "updated_at"
                    ])
                    logger.debug(f"✅ Quote(pk={q.pk}) recalculada tras BULK UPDATE")
                except Exception as e:
                    logger.exception(f"❌ Error recalculando Quote(pk={qid}) tras BULK UPDATE: {e}")
                finally:
                    if hasattr(q, "_skip_trigger"):
                        delattr(q, "_skip_trigger")

        return {
            "bulk_updated": True,
            "count": len(updated_pks),
            "object": model_name,
            "pks": updated_pks
        }
    
    def _handle_bulk_clone(self, action, instance, context):
        """
        BULK CLONE:
        ✅ Usa action.filters para buscar source_object
        ✅ Soporta rutas profundas en target (string path o dict legacy)
        ✅ Clona cada registro encontrado
        ✅ Aplica SOLO los overrides definidos en action.value
        ✅ Omite campos UNIQUE automáticamente
        ✅ Aplica coerción correcta de ForeignKeys
        ✅ Recalcula Quote si se clonan QuoteLine

        Cambios:
        - Soporta field_name además de field en filtros
        - target puede ser string path o dict
        """

        filters = action.get("filters") or {}
        source_model_name = filters.get("source_object")
        items = filters.get("items", [])

        if not source_model_name:
            return {"bulk_cloned": False, "reason": "source_object missing in filters"}

        SourceModel = self._get_model_class(source_model_name)
        if SourceModel is None:
            return {"bulk_cloned": False, "reason": f"Source model '{source_model_name}' not found"}

        target_raw = action.get("target")
        if isinstance(target_raw, str):
            raw_target = target_raw.strip()
        else:
            raw_target = (target_raw or {}).get("object")

        if not raw_target:
            return {"bulk_cloned": False, "reason": "target.object missing"}

        # ----------------------------------------------------------------------
        # ✅ 1) CONSTRUIR FILTROS ORM PARA EL SOURCE
        # ----------------------------------------------------------------------
        orm_filters = {}

        for f in items:
            field = f.get("field_name") or f.get("field")
            op = f.get("operator", "==")
            val_block = f.get("value", {})

            if not field:
                continue

            resolved = self._resolve_value_for_action(val_block, instance, context)
            orm_key = field.replace(".", "__")

            if op == "!=":
                orm_filters[f"{orm_key}__ne"] = resolved
                continue
            elif op == ">":
                orm_key = f"{orm_key}__gt"
            elif op == "<":
                orm_key = f"{orm_key}__lt"
            elif op == ">=":
                orm_key = f"{orm_key}__gte"
            elif op == "<=":
                orm_key = f"{orm_key}__lte"
            elif op == "contains":
                orm_key = f"{orm_key}__icontains"
            elif op == "in":
                orm_key = f"{orm_key}__in"

            orm_filters[orm_key] = resolved

        queryset = SourceModel.objects.filter(**orm_filters)

        cloned_pks = []
        warnings = []

        # ----------------------------------------------------------------------
        # ✅ 2) CLONAR CADA REGISTRO
        # ----------------------------------------------------------------------
        for source_record in queryset:

            # ---- Contexto extendido para overrides ----
            local_context = dict(context)
            local_context[source_model_name] = source_record

            # ------------------------------------------------------------------
            # ✅ 3) RESOLVER RUTA PROFUNDA DEL TARGET
            # ------------------------------------------------------------------
            path_parts = raw_target.split(".")
            current = None

            if path_parts[0] == source_model_name:
                current = source_record
            elif path_parts[0] in local_context:
                current = local_context[path_parts[0]]

            from django.db.models import ForeignKey, OneToOneField

            last_model_inst = current

            for part in path_parts[1:]:
                if current is None:
                    break

                try:
                    next_val = getattr(current, part)
                except Exception:
                    current = None
                    break

                is_fk = False
                try:
                    field = current.__class__._meta.get_field(part)
                    if isinstance(field, (ForeignKey, OneToOneField)):
                        is_fk = True
                except Exception:
                    pass

                if is_fk and isinstance(next_val, Model):
                    last_model_inst = next_val

                current = next_val

            if isinstance(current, Model):
                source_instance = current
            elif isinstance(last_model_inst, Model):
                # ej: opportunity.primary_quote.account.name → usamos Account
                source_instance = last_model_inst
            else:
                warnings.append(
                    f"⚠️ Skipped BULK CLONE invalid path '{raw_target}' (not a model)"
                )
                continue

            TargetModel = source_instance.__class__

            target_obj_name = self._normalize_model_name(TargetModel.__name__)

            local_context["_current_action"] = {
                "target_object": target_obj_name,
                "target_model": TargetModel,
            }

            # ------------------------------------------------------------------
            # ✅ 4) DETECTAR Y OMITIR CAMPOS UNIQUE
            # ------------------------------------------------------------------
            unique_fields = self._detect_unique_clone_fields(TargetModel)
            if unique_fields:
                warnings.append(
                    f"⚠️ Unique fields skipped while cloning {target_obj_name}: "
                    + ", ".join(unique_fields)
                )

            # ------------------------------------------------------------------
            # ✅ 5) COPIAR BASE DE DATOS (SIN PK, M2M NI UNIQUE)
            # ------------------------------------------------------------------
            base_data = {
                f.name: getattr(source_instance, f.name)
                for f in TargetModel._meta.get_fields()
                if (
                    f.concrete
                    and not f.many_to_many
                    and not f.primary_key
                    and not getattr(f, "unique", False)
                )
            }

            # ------------------------------------------------------------------
            # ✅ 6) RESOLVER OVERRIDES
            # ------------------------------------------------------------------
            overrides = self._resolve_value_for_action(
                action.get("value") or {},
                instance,
                local_context,
            ) or {}

            overrides = self._filter_model_fields(TargetModel, overrides)

            final_data = {**base_data, **overrides}

            # ------------------------------------------------------------------
            # ✅ 7) COERCIÓN DE FOREIGN KEYS
            # ------------------------------------------------------------------
            for fname, val in final_data.items():
                final_data[fname] = self._coerce_fk(
                    TargetModel,
                    fname,
                    val,
                    context=local_context,
                    instance=source_instance
                )

            # ------------------------------------------------------------------
            # ✅ 8) CREAR REGISTRO CLONADO
            # ------------------------------------------------------------------
            new_obj = TargetModel.objects.create(**final_data)
            cloned_pks.append(new_obj.pk)

            # ------------------------------------------------------------------
            # ✅ 9) RECALCULAR QUOTE SI SE CLONÓ UNA QUOTELINE
            # ------------------------------------------------------------------
            if target_obj_name == "quote_line":
                self._recalc_quote_after_create_quoteline(new_obj)

        return {
            "bulk_cloned": True,
            "count": len(cloned_pks),
            "object": raw_target,
            "pks": cloned_pks,
            "warnings": warnings,
        }

    
    def _handle_clone(self, action, instance, context):
        """
        CLONE normal con soporte de:
        ✅ Rutas profundas en target (string path o dict legacy)
        ✅ Validación de modelo real
        ✅ Omisión de UNIQUE fields
        ✅ Warnings controlados
        """

        target_raw = action.get("target")

        # Nuevo formato: target es string path ("opportunity.primary_quote.account")
        if isinstance(target_raw, str):
            full_path = target_raw.strip()
            if not full_path:
                return {"cloned": False, "reason": "target path empty"}
        else:
            # Legacy dict: { "object": "...", "path": "..." }
            target_def = target_raw or {}
            raw_object = target_def.get("object")
            raw_path = target_def.get("path")
            if not raw_object:
                return {"cloned": False, "reason": "target.object missing"}
            full_path = raw_object if not raw_path else f"{raw_object}.{raw_path}"

        path_parts = full_path.split(".")
        root_name = path_parts[0]
        current = None

        # 1️⃣ Context directo
        if root_name in context and isinstance(context[root_name], Model):
            current = context[root_name]
        else:
            # 2️⃣ Instancia principal
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if root_name == inst_name:
                current = instance

        # ❌ No se pudo resolver raíz
        if current is None:
            return {
                "cloned": False,
                "warnings": [
                    f"⚠️ CLONE root '{root_name}' not found in context or instance"
                ]
            }

        from django.db.models import ForeignKey, OneToOneField

        # 🧭 Navegar la ruta restante, recordando el ÚLTIMO modelo de FK
        last_model_inst = current

        for part in path_parts[1:]:
            if current is None:
                break

            try:
                next_val = getattr(current, part)
            except Exception:
                current = None
                break

            # ¿Es FK / O2O este segmento?
            is_fk = False
            try:
                field = current.__class__._meta.get_field(part)
                if isinstance(field, (ForeignKey, OneToOneField)):
                    is_fk = True
            except Exception:
                pass

            if is_fk and isinstance(next_val, Model):
                last_model_inst = next_val

            current = next_val

        # Determinar instancia fuente REAL
        if isinstance(current, Model):
            source_instance = current
        elif isinstance(last_model_inst, Model):
            # ej: opportunity.primary_quote.account.name → usamos Account
            source_instance = last_model_inst
        else:
            return {
                "cloned": False,
                "warnings": [
                    f"⚠️ Invalid CLONE target path '{full_path}'. "
                    f"Final resolved value is NOT a model ({type(current).__name__})."
                ]
            }

        # ✅ ESTA ES LA INSTANCIA FUENTE REAL
        ModelClass = source_instance.__class__
        target_obj_name = self._normalize_model_name(ModelClass.__name__)

        # --------------------------------------------------
        # ✅ 2) DETECTAR CAMPOS UNIQUE OMITIDOS
        # --------------------------------------------------
        unique_fields = self._detect_unique_clone_fields(ModelClass)

        warnings = []
        if unique_fields:
            warnings.append(
                f"⚠️ Heads up! Some unique fields were skipped while cloning {target_obj_name}: "
                + ", ".join(unique_fields)
            )

        # --------------------------------------------------
        # ✅ 3) COPIAR TODOS LOS CAMPOS BASE
        # --------------------------------------------------
        original_data = {
            f.name: getattr(source_instance, f.name)
            for f in ModelClass._meta.get_fields()
            if (
                f.concrete
                and not f.many_to_many
                and not f.primary_key
                and not getattr(f, "unique", False)
            )
        }

        # --------------------------------------------------
        # ✅ 4) RESOLVER OVERRIDES
        # --------------------------------------------------
        context["_current_action"] = {
            "target_object": target_obj_name,
            "target_model": ModelClass,
        }

        override_fields = self._resolve_value_for_action(
            action.get("value") or {},
            instance,
            context,
        ) or {}

        override_fields = self._filter_model_fields(ModelClass, override_fields)

        final_data = {**original_data, **override_fields}

        # --------------------------------------------------
        # ✅ 5) COERCE DE FOREIGN KEYS
        # --------------------------------------------------
        for fname, val in final_data.items():
            final_data[fname] = self._coerce_fk(
                ModelClass,
                fname,
                val,
                context=context,
                instance=instance
            )

        # --------------------------------------------------
        # ✅ 6) CREAR REGISTRO CLONADO
        # --------------------------------------------------
        new_obj = ModelClass.objects.create(**final_data)

        # --------------------------------------------------
        # ✅ 7) RECALCULAR QUOTE SI APLICA
        # --------------------------------------------------
        if target_obj_name == "quote_line":
            self._recalc_quote_after_create_quoteline(new_obj)

        return {
            "cloned": True,
            "object": target_obj_name,
            "source_pk": source_instance.pk,
            "new_pk": new_obj.pk,
            "warnings": warnings,
        }


    def _handle_set(self, action, instance, context):
        """
        Ejecuta una acción SET/UPDATE sobre uno o varios campos.

        Nuevo comportamiento:
        - UPDATE simple usa siempre value.fields (uno o varios campos)
        - Soporta campos nativos y CustomFields (__c)
        - Mantiene compatibilidad con el formato legacy (value.type + target.path)
        """
        from django.contrib.contenttypes.models import ContentType

        target_def = action.get("target")
        value_def = action.get("value") or {}

        target_inst, legacy_target_field = self._resolve_target_instance_and_field(
            target_def,
            instance,
            context,
        )
        if target_inst is None:
            return {"updated": False, "reason": "no se pudo resolver instancia del target"}

        # ============================================================
        # 🔥 DETECCIÓN CLAVE: UPDATE SOBRE CUSTOM OBJECT (__c)
        # ============================================================
        is_custom_object_update = (
            isinstance(target_def, str)
            and target_def.endswith("__c")
            and target_inst.__class__.__name__ == "CustomRecord"
        )

        # ============================================================
        # ✅ NUEVO FORMATO: value.fields { "<field_name>": { ... } }
        # ============================================================
        if isinstance(value_def.get("fields"), dict) and value_def["fields"]:
            resolved_fields = self._resolve_value_for_action(value_def, instance, context) or {}
            if not isinstance(resolved_fields, dict) or not resolved_fields:
                return {"updated": False, "reason": "no resolved fields"}

            updated_native = []
            updated_custom = []

            for fname, new_val in resolved_fields.items():
                field_def = (value_def.get("fields") or {}).get(fname, {}) or {}
                field_type = field_def.get("type")

                # Bloquear sólo cuando:
                # - NO es static
                # - y el valor no se pudo resolver (None)
                if field_type != "static" and new_val is None:
                    logger.debug(
                        f"⚠️ UPDATE skipped field '{fname}' because value is None and type != static"
                    )
                    continue

                # ----------------------------------------------------
                # 1) Campo __c → CustomFieldValue
                # ----------------------------------------------------
                if fname.endswith("__c"):
                    try:
                        ct = ContentType.objects.get_for_model(target_inst.__class__)

                        if isinstance(target_inst, CustomRecord):
                            model_name = target_inst.object_type.name
                        else:
                            model_name = target_inst.__class__.__name__

                        cf = (
                            CustomField.objects.filter(
                                name=fname,
                                object_type__iexact=model_name
                            ).first()
                            or CustomField.objects.filter(
                                name=fname,
                                custom_object__name__iexact=model_name
                            ).first()
                        )

                        if not cf:
                            logger.warning(f"⚠️ No se encontró CustomField '{fname}' para {model_name}")
                            continue

                        if isinstance(target_inst, CustomRecord):
                            content_type = ContentType.objects.get_for_model(target_inst)

                            cfv, created = CustomFieldValue.objects.update_or_create(
                                field=cf,
                                record=target_inst,  # 🔑 CLAVE LÓGICA REAL
                                defaults={
                                    "content_type": content_type,
                                    "object_id": target_inst.pk,
                                    "value": str(new_val),
                                },
                            )
                        else:
                            cfv, created = CustomFieldValue.objects.update_or_create(
                                field=cf,
                                content_type=ct,
                                object_id=target_inst.pk,
                                defaults={"value": str(new_val)},
                            )

                        logger.debug(
                            f"🧩 {'CREATED' if created else 'UPDATED'} CustomFieldValue "
                            f"{model_name}.{fname} = {new_val} (pk={cfv.pk})"
                        )
                        updated_custom.append(fname)

                    except Exception as e:
                        logger.exception(f"❌ Error actualizando CustomFieldValue {fname}: {e}")
                        continue

                # ----------------------------------------------------
                # 2) Campo nativo
                # ----------------------------------------------------
                else:
                    setattr(target_inst, fname, new_val)
                    updated_native.append(fname)

            # Guardar nativos en un solo save
            if updated_native:
                setattr(target_inst, "_skip_trigger", True)
                try:
                    target_inst.save(update_fields=updated_native)
                finally:
                    if hasattr(target_inst, "_skip_trigger"):
                        delattr(target_inst, "_skip_trigger")

                logger.debug(
                    "📝 UPDATE %s fields %s (pk=%s)",
                    self._normalize_model_name(target_inst.__class__.__name__),
                    updated_native,
                    target_inst.pk,
                )

            if not updated_native and not updated_custom:
                return {"updated": False, "reason": "no fields updated"}

            return {
                "updated": True,
                "pk": target_inst.pk,
                "fields": updated_native,
                "custom_fields": updated_custom,
            }

        # ============================================================
        # 🚫 BLOQUEO LEGACY PARA CUSTOM OBJECTS
        # ============================================================
        if is_custom_object_update:
            return {
                "updated": False,
                "reason": "custom object update requires value.fields"
            }

        # ============================================================
        # 🧩 FORMATO LEGACY: value.type + target.path (un solo campo)
        # ============================================================
        value_type = (value_def or {}).get("type")
        new_val = self._resolve_value_for_action(value_def, instance, context)

        if not legacy_target_field:
            return {"updated": False, "reason": "no target field resolved (legacy update)"}

        if value_type != "static" and new_val is None:
            return {"updated": False, "reason": "valor no resuelto"}

        # 1) Campo __c → CustomFieldValue
        if legacy_target_field.endswith("__c"):
            try:
                ct = ContentType.objects.get_for_model(target_inst.__class__)
                model_name = target_inst.__class__.__name__

                cf = (
                    CustomField.objects.filter(
                        name=legacy_target_field,
                        object_type__iexact=model_name
                    ).first()
                    or CustomField.objects.filter(
                        name=legacy_target_field,
                        custom_object__name__iexact=model_name
                    ).first()
                )

                if not cf:
                    logger.warning(f"⚠️ No se encontró CustomField '{legacy_target_field}' para {model_name}")
                    return {"updated": False, "reason": f"CustomField '{legacy_target_field}' no encontrado"}

                if target_inst.__class__.__name__ == "CustomRecord":
                    cfv, created = CustomFieldValue.objects.update_or_create(
                        field=cf,
                        record=target_inst,
                        defaults={"value": str(new_val)},
                    )
                else:
                    cfv, created = CustomFieldValue.objects.update_or_create(
                        field=cf,
                        content_type=ct,
                        object_id=target_inst.pk,
                        defaults={"value": str(new_val)},
                    )

                logger.debug(
                    f"🧩 {'CREATED' if created else 'UPDATED'} CustomFieldValue "
                    f"{model_name}.{legacy_target_field} = {new_val} (pk={cfv.pk})"
                )

                return {"updated": True, "pk": cfv.pk, "custom_field": legacy_target_field}

            except Exception as e:
                logger.exception(f"❌ Error actualizando CustomFieldValue {legacy_target_field}: {e}")
                return {"updated": False, "reason": str(e)}

        # 2) Campo nativo
        setattr(target_inst, legacy_target_field, new_val)

        setattr(target_inst, "_skip_trigger", True)
        try:
            target_inst.save(update_fields=[legacy_target_field])
        finally:
            if hasattr(target_inst, "_skip_trigger"):
                delattr(target_inst, "_skip_trigger")

        logger.debug(
            "📝 UPDATE %s.%s = %s (pk=%s) [LEGACY]",
            self._normalize_model_name(target_inst.__class__.__name__),
            legacy_target_field,
            new_val,
            target_inst.pk,
        )

        return {"updated": True, "pk": target_inst.pk}

    def _handle_create(self, action, instance, context):
        """
        CREATE handler con soporte para Custom Objects (__c).

        - Crea CustomRecord
        - Genera custom_identifier automáticamente
        - Crea CustomFieldValue usando helper centralizado
        - Retorna el CustomRecord
        """

        from uuid import uuid4
        from django.db import transaction

        target = action.get("target")
        value_def = action.get("value") or {}

        # --------------------------------------------------
        # 1️⃣ Detectar CREATE de Custom Object
        # --------------------------------------------------
        if not isinstance(target, str) or not target.endswith("__c"):
            return {"created": False, "reason": "not a custom object create"}

        custom_object_name = target

        # --------------------------------------------------
        # 2️⃣ Obtener CustomObject
        # --------------------------------------------------
        try:
            custom_object = CustomObject.objects.get(name=custom_object_name)
        except CustomObject.DoesNotExist:
            return {
                "created": False,
                "reason": f"CustomObject '{custom_object_name}' not found"
            }

        # --------------------------------------------------
        # 3️⃣ Generar custom_identifier
        # --------------------------------------------------
        last_record = custom_object.records.order_by("-created_at").first()

        if last_record and last_record.custom_identifier:
            next_identifier = get_next_custom_identifier(
                last_record.custom_identifier
            )
        else:
            label = custom_object.label or custom_object.name
            prefix = label[:3].upper() if len(label) >= 3 else label[:1].upper()
            next_identifier = f"{prefix}-00001"

        # --------------------------------------------------
        # 4️⃣ Crear CustomRecord + Fields
        # --------------------------------------------------
        with transaction.atomic():
            custom_record = CustomRecord.objects.create(
                object_type=custom_object,
                custom_identifier=next_identifier,
                record_id=uuid4(),
                created_by=context.get("_user"),
                updated_by=context.get("_user"),
            )

            # --------------------------------------------------
            # 5️⃣ Resolver value.fields
            # --------------------------------------------------
            resolved_fields = self._resolve_value_for_action(
                value_def,
                instance,
                context,
            ) or {}

            # --------------------------------------------------
            # 6️⃣ Crear CustomFieldValue (USANDO HELPER)
            # --------------------------------------------------
            for field_name, field_value in resolved_fields.items():
                if not field_name.endswith("__c"):
                    continue

                cf = CustomField.objects.filter(
                    name=field_name,
                    custom_object=custom_object
                ).first()

                if not cf:
                    continue

                self._create_custom_field_value(
                    record=custom_record,
                    custom_field=cf,
                    value=field_value,
                    user=context.get("_user"),
                )

        # --------------------------------------------------
        # 7️⃣ Resultado
        # --------------------------------------------------
        return {
            "created": True,
            "pk": custom_record.pk,
            "custom_identifier": custom_record.custom_identifier,
            "instance": custom_record,  # 🔥 CLAVE
        }

    def _handle_delete(self, action, instance, context):
        """
        ✅ DELETE con soporte de filtros dinámicos y recalculo automático de Quote si se afectan QuoteLine.
        """
        from django.contrib.contenttypes.models import ContentType

        target = action.get("target", {})
        filters = target.get("filters", [])

        if not target.get("object"):
            return {"deleted": False, "reason": "object ausente en target"}

        model_name = self._normalize_model_name(target["object"])
        ModelClass = self._get_model_class(model_name)
        if ModelClass is None:
            return {"deleted": False, "reason": f"Modelo '{model_name}' no encontrado"}

        # 🔍 Construir filtros ORM desde la definición
        orm_filters = {}
        for f in filters:
            field = f.get("field")
            op = f.get("operator", "==")
            val_block = f.get("value", {})

            if not field:
                continue

            resolved_value = self._resolve_value_for_action(val_block, instance, context)
            orm_key = field.replace(".", "__")

            if op == "!=":
                orm_key = f"{orm_key}__ne"
            elif op == ">":
                orm_key = f"{orm_key}__gt"
            elif op == "<":
                orm_key = f"{orm_key}__lt"
            elif op == ">=":
                orm_key = f"{orm_key}__gte"
            elif op == "<=":
                orm_key = f"{orm_key}__lte"
            elif op == "contains":
                orm_key = f"{orm_key}__icontains"
            elif op == "in":
                orm_key = f"{orm_key}__in"

            orm_filters[orm_key] = resolved_value

        logger.debug(f"🧩 DELETE filters ORM: {orm_filters}")

        # 🧠 Detectar quotes afectadas ANTES del delete
        quote_ids = []
        if model_name == "quote_line" and hasattr(ModelClass, "quote_id"):
            quote_ids = list(ModelClass.objects.filter(**orm_filters).values_list("quote_id", flat=True))

        # ✅ Ejecutar borrado masivo
        with transaction.atomic():
            qs = ModelClass.objects.filter(**orm_filters)
            count_before = qs.count()
            deleted, _ = qs.delete()

        logger.debug(f"🗑️ DELETE {model_name}: {deleted} registros eliminados ({count_before} encontrados)")

        # 🔁 Recalcular quotes afectadas
        if model_name == "quote_line" and quote_ids:
            Quote = apps.get_model("cpq", "Quote")
            unique_qids = set(quote_ids)
            logger.debug(f"🔁 Recalculando {len(unique_qids)} quote(s) afectadas por DELETE...")
            for qid in unique_qids:
                q = Quote.objects.filter(pk=qid).first()
                if not q:
                    continue
                try:
                    setattr(q, "_skip_trigger", True)
                    q.subtotal = q.get_subtotal_amount()
                    q.update_discount_fields()
                    q.update_net_amount()
                    q.save(update_fields=[
                        "subtotal", "discount_percentage", "discount_amount",
                        "net_amount", "tax_amount", "tax_percentage", "updated_at"
                    ])
                    logger.debug(f"✅ Quote(pk={q.pk}) recalculada tras borrar QuoteLine(s)")
                except Exception as e:
                    logger.exception(f"❌ Error recalculando Quote(pk={qid}): {e}")
                finally:
                    if hasattr(q, "_skip_trigger"):
                        delattr(q, "_skip_trigger")

        return {
            "deleted": True,
            "deleted_count": deleted,
            "model": model_name,
            "affected_quotes": list(set(quote_ids)),
        }
    
    def _handle_single_delete(self, obj):
        """
        DELETE de un solo registro (sin filters).
        Soporta recalcular Quote si borras una QuoteLine.
        """
        from django.apps import apps

        model_name = self._normalize_model_name(obj.__class__.__name__)
        pk = obj.pk

        affected_quotes = []

        # Si estamos borrando una quote_line → marcar quote para recalcular
        if model_name == "quote_line" and getattr(obj, "quote_id", None):
            affected_quotes.append(obj.quote_id)

        obj.delete()
        logger.debug(f"🗑️ DELETE single {model_name}(pk={pk})")

        # 🔁 Recalcular quotes afectadas (igual idea que en _handle_delete)
        if affected_quotes:
            Quote = apps.get_model("cpq", "Quote")
            unique_qids = set(affected_quotes)
            logger.debug(f"🔁 Recalculando {len(unique_qids)} quote(s) afectadas por DELETE single...")

            for qid in unique_qids:
                q = Quote.objects.filter(pk=qid).first()
                if not q:
                    continue
                try:
                    setattr(q, "_skip_trigger", True)
                    q.subtotal = q.get_subtotal_amount()
                    q.update_discount_fields()
                    q.update_net_amount()
                    q.save(update_fields=[
                        "subtotal", "discount_percentage", "discount_amount",
                        "net_amount", "tax_amount", "tax_percentage", "updated_at"
                    ])
                    logger.debug(f"✅ Quote(pk={q.pk}) recalculada tras DELETE single")
                except Exception as e:
                    logger.exception(f"❌ Error recalculando Quote(pk={qid}) tras DELETE single: {e}")
                finally:
                    if hasattr(q, "_skip_trigger"):
                        delattr(q, "_skip_trigger")

        return {
            "deleted": True,
            "deleted_count": 1,
            "model": model_name,
            "pk": pk,
            "affected_quotes": list(set(affected_quotes)),
        }

    def _handle_email(self, action, instance, context):
        return execute_email_action(
            action=action,
            instance=instance,
            context=context,
        )

    def _handle_webhook(self, action, instance, context):
        return {"webhook": True}

    def _resolve_value_for_action(self, value_def: Dict[str, Any], instance: Model, context: Dict[str, Any]):
        """
        Resolución completa para CREATE / UPDATE:
        - Soporta path="" → usar instancia completa
        - Respeta source_object en bulk
        - Coerce FK correctamente
        - Nuevo formato:
            - static.value (en vez de static.data)
            - field.field_name (acepta path legacy también)
            - UPDATE simple usa siempre value.fields

        🔥 Mejora:
        - En value.fields:
            1) Primero resuelve TODOS los campos cuyo nombre empieza con 'LOOKUP_' y type == 'lookup'
               y los guarda en un contexto local (local_context).
            2) Luego, con ese contexto enriquecido, resuelve el resto de los campos (static, field, expression, date, sequence, lookup normal).
        - Esto hace que expresiones como `DATEADD(LOOKUP_Contract.end_date, 1, 'months')`
          o fields con object="LOOKUP_Opportunity" siempre tengan el lookup resuelto ANTES.
        """
        if not value_def:
            return None

        # ----------------------------------------------------------------------
        # CASE 1: CREATE / UPDATE (nuevo) → fields{}
        # ----------------------------------------------------------------------
        if "fields" in value_def:
            fields_def = value_def.get("fields") or {}
            resolved: Dict[str, Any] = {}

            # ⚠️ Muy importante: NO mutamos el contexto original, usamos una copia local
            local_context = dict(context)

            # ==============================================================
            # PASO 1: Resolver primero TODOS los LOOKUP_* (por nombre de key)
            # ==============================================================
            for fname, field_def in fields_def.items():
                if not isinstance(field_def, dict):
                    continue

                ftype = field_def.get("type")

                # Solo los que:
                # - key empieza con LOOKUP_
                # - y type == 'lookup'
                if fname.startswith("LOOKUP_") and ftype == "lookup":
                    lookup_val = self._resolve_lookup(field_def, instance, local_context)
                    resolved[fname] = lookup_val
                    # Hacemos disponible el resultado para expresiones y fields posteriores
                    local_context[fname] = lookup_val

            # ==============================================================
            # PASO 2: Resolver el resto de campos con el contexto enriquecido
            # ==============================================================

            for fname, field_def in fields_def.items():
                # Si ya lo resolvimos en el paso 1 (LOOKUP_*), lo saltamos
                if fname in resolved or not isinstance(field_def, dict):
                    continue

                ftype = field_def.get("type")
                obj = field_def.get("object")
                path = field_def.get("path")
                if path is None:
                    path = field_def.get("field_name", "")
                alias = field_def.get("alias")

                # STATIC
                if ftype == "static":
                    resolved[fname] = field_def.get("value", field_def.get("data"))
                    continue

                # FIELD
                if ftype == "field":
                    base = None

                    # PRIORIDAD 1: contexto local (incluye LOOKUP_* resueltos)
                    if obj in local_context:
                        base = local_context[obj]

                    # PRIORIDAD 2: instancia principal del evento
                    if base is None:
                        inst_name = self._normalize_model_name(instance.__class__.__name__)
                        if obj == inst_name:
                            base = instance

                    # path vacío o id → devolver instancia completa
                    if path in ("", "id"):
                        resolved[fname] = base
                        continue

                    if base is None:
                        resolved[fname] = None
                        continue

                    raw_value = self._resolve_path(base, path)
                    resolved[fname] = raw_value
                    continue

                # EXPRESSION
                if ftype == "expression":
                    # 👈 Aquí ya puede usar LOOKUP_* dentro del formula, porque local_context
                    # ya tiene LOOKUP_Contract, LOOKUP_Opportunity, etc.
                    resolved[fname] = self._evaluate_expression(
                        field_def.get("formula", ""),
                        instance,
                        local_context,
                    )
                    continue

                # DATE
                if ftype == "date":
                    resolved[fname] = self._evaluate_date_formula(
                        field_def.get("formula", ""),
                        instance,
                        local_context,
                    )
                    continue

                # SEQUENCE (NEXT_SEQUENCE)
                if ftype == "sequence":
                    resolved[fname] = self._resolve_sequence(field_def)
                    continue

                # LOOKUP normal (para campos "product", "account", etc. que usan lookup pero
                # no son aliases tipo LOOKUP_*)
                if ftype == "lookup":
                    resolved[fname] = self._resolve_lookup(field_def, instance, local_context)
                    continue

            return resolved

        # ----------------------------------------------------------------------
        # CASE 2: LEGACY simple value.type (UPDATE/DELETE antiguos)
        # ----------------------------------------------------------------------
        ftype = value_def.get("type")

        if ftype == "static":
            return value_def.get("value", value_def.get("data"))

        if ftype == "field":
            obj = value_def.get("object")
            path = value_def.get("path")
            if path is None:
                path = value_def.get("field_name", "")

            # ✅ 1) PRIORIDAD: CONTEXT DIRECTO
            if obj in context:
                if path == "":
                    return context[obj]   # ✅ DEVUELVE INSTANCIA COMPLETA
                return self._resolve_path(context[obj], path)

            # ✅ 2) COMPARAR CONTRA INSTANCIA PRINCIPAL
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj == inst_name:
                if path == "":
                    return instance      # ✅ DEVUELVE INSTANCIA COMPLETA
                return self._resolve_path(instance, path)

            # ✅ 3) BUSCAR EN CONTEXT POR TIPO
            for cand in context.values():
                if isinstance(cand, Model) and self._normalize_model_name(cand.__class__.__name__) == obj:
                    if path == "":
                        return cand      # ✅ DEVUELVE INSTANCIA COMPLETA
                    return self._resolve_path(cand, path)

            return None

        if ftype == "expression":
            return self._evaluate_expression(value_def.get("formula", ""), instance, context)

        if ftype == "date":
            return self._evaluate_date_formula(value_def.get("formula", ""), instance, context)

        if ftype == "sequence":
            return self._resolve_sequence(value_def)

        return None

    # -------------------------------------------------------------------------
    # Utilidades de modelos / custom objects
    # -------------------------------------------------------------------------
    def _is_custom_object(self, name: str) -> bool:
        return isinstance(name, str) and name.endswith("__c")

    def _translate_filters_for_orm(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in filters.items() if v is not None}

    def _find_custom_object_records(self, custom_object_name: str, filters: Dict[str, Any]) -> List[Any]:
        try:
            obj = CustomObject.objects.get(name=custom_object_name)
        except CustomObject.DoesNotExist:
            logger.debug("⚠️ CustomObject '%s' no existe", custom_object_name)
            return []

        records = CustomRecord.objects.filter(object_type=obj)
        if not filters:
            return list(records)

        fields_by_name = {f.name: f for f in CustomField.objects.filter(custom_object=obj)}

        matched: List[Any] = []
        for rec in records:
            ok = True
            for field_name, expected in filters.items():
                cf = fields_by_name.get(field_name)
                if not cf:
                    ok = False
                    break
                cfv = CustomFieldValue.objects.filter(field=cf, record=rec).first()
                if cfv is None:
                    ok = False
                    break
                actual_val = self._cast_custom_value(cfv.value, cf.data_type)
                expected_val = self._cast_custom_value(expected, cf.data_type)
                if actual_val != expected_val:
                    ok = False
                    break
            if ok:
                matched.append(rec)

        return matched

    def _resolve_custom_field_value(self, obj: Any, field_name: str):
        from django.contrib.contenttypes.models import ContentType

        # -------------------------------------------------
        # CASE 1: CustomRecord (virtual object)
        # -------------------------------------------------
        if isinstance(obj, CustomRecord):
            cobj = obj.object_type

            cf = CustomField.objects.filter(
                custom_object=cobj,
                name=field_name
            ).first()

            if not cf:
                logger.debug(f"⚠️ No existe CustomField '{field_name}' en {cobj.name}")
                return None

            cfv = CustomFieldValue.objects.filter(
                field=cf,
                record=obj
            ).first()

            if not cfv:
                logger.debug(f"⚠️ CustomRecord {obj.pk} no tiene valor para '{field_name}'")
                return None

            # 🔥 LOOKUP HANDLING (delegado)
            if cf.data_type == "lookup":
                raw_value = cfv.value
                if not raw_value:
                    return None

                if not cf.lookup_model:
                    logger.debug(f"⚠️ Lookup field '{field_name}' sin lookup_model definido")
                    return None

                return self._resolve_lookup_flexible(
                    lookup_model=cf.lookup_model,
                    raw_value=raw_value
                )

            # -----------------------------
            # NORMAL CUSTOM FIELD
            # -----------------------------
            return self._return_custom_value(cf, cfv)

        # -------------------------------------------------
        # CASE 2: Standard Django model
        # -------------------------------------------------
        ct = ContentType.objects.get_for_model(obj.__class__)
        cfs = CustomFieldValue.objects.filter(
            content_type=ct,
            object_id=obj.pk
        ).select_related("field", "record", "field__custom_object")

        for cfv in cfs:
            if cfv.field.name == field_name:
                cf = cfv.field

                # 🔥 LOOKUP HANDLING (delegado)
                if cf.data_type == "lookup":
                    raw_value = cfv.value
                    if not raw_value:
                        return None

                    if not cf.lookup_model:
                        logger.debug(f"⚠️ Lookup field '{field_name}' sin lookup_model definido")
                        return None

                    return self._resolve_lookup_flexible(
                        lookup_model=cf.lookup_model,
                        raw_value=raw_value
                    )

                return self._return_custom_value(cf, cfv)

        logger.debug(f"⚠️ No se encontró valor para {obj} → {field_name}")
        return None

    def _return_custom_value(self, field, cfv):
        """
        🔥 FIX REAL:
        - Si el CustomField es lookup, NO debe devolver cfv.record/cfv.content_object (eso es el mismo record).
        - Debe resolver el target a partir de cfv.value + field.lookup_model.
        - Mantiene fallback al comportamiento anterior para no romper casos viejos.
        """
        try:
            if field.data_type and field.data_type.lower().strip() == "lookup" and field.lookup_model:
                # 1) Resolver el objeto referenciado por el valor guardado
                raw_value = getattr(cfv, "value", None)

                target_obj = self._resolve_lookup_target_instance(field=field, raw_value=raw_value)

                # 2) Fallback legacy (por compatibilidad)
                if target_obj is None:
                    target_obj = cfv.content_object or cfv.record

                # 3) Soportar lookups encadenados (__c.__c.__c)
                next_field = getattr(self, "_next_custom_field", None)
                if next_field and next_field.endswith("__c"):
                    return self._resolve_custom_field_value(target_obj, next_field)

                return target_obj

        except Exception:
            # fallback duro por compatibilidad
            pass

        return self._cast_custom_value(cfv.value, field.data_type)


    def _cast_custom_value(self, raw: Any, data_type: Optional[str]):
        if raw is None:
            return None
        if not data_type:
            return str(raw)

        t = data_type.lower().strip()
        s = str(raw)

        if t in ("number", "integer", "int"):
            try:
                return int(float(s))
            except Exception:
                return None
        if t in ("decimal", "float", "double", "currency", "percent", "percentage"):
            try:
                return float(s)
            except Exception:
                return None
        if t in ("boolean", "bool", "checkbox"):
            return s.lower() in ("1", "true", "yes", "y", "t")
        if t in ("text", "string", "textarea", "picklist"):
            return s
        if t in ("date", "datetime"):
            return s
        return s

    def _resolve_target_instance_and_field(
        self,
        target_def: Any,
        instance: Model,
        context: Dict[Optional[str], Any],
    ) -> Tuple[Optional[Model], Optional[str]]:
        """
        Resuelve la instancia objetivo y, opcionalmente, el nombre del campo.

        Reglas clave:
        - Custom Objects (__c) NO navegan paths
        - __c siempre resuelve a CustomRecord
        - No hay fallbacks para __c
        """

        if not target_def:
            return None, None

        # --------------------------------------------------
        # Normalizar target a (obj_name, path)
        # --------------------------------------------------
        if isinstance(target_def, str):
            raw = target_def.strip()
            if not raw:
                return None, None
            parts = raw.split(".")
            obj_name = parts[0]
            path = ".".join(parts[1:]) if len(parts) > 1 else ""
        else:
            obj_name = (target_def.get("object") or "").strip()
            path = (target_def.get("path") or "").strip()

        if not obj_name:
            return None, None

        # ==================================================
        # 🔴 CASO ESPECIAL: CUSTOM OBJECT (__c)
        # ==================================================
        if isinstance(obj_name, str) and obj_name.endswith("__c"):

            # 1) Resolver raíz (root CustomRecord)
            root = None

            # El instance del evento YA debe ser CustomRecord del mismo object
            if isinstance(instance, CustomRecord) and instance.object_type.name == obj_name:
                root = instance

            # Buscar CustomRecord en el contexto (LOOKUP_* u otros)
            if root is None:
                for v in context.values():
                    if isinstance(v, CustomRecord) and v.object_type.name == obj_name:
                        root = v
                        break

            # ❌ No inventamos instancias para __c
            if root is None:
                return None, None

            # Sin path => target es el propio CustomRecord
            if not path:
                return root, None

            # 2) Navegar path MIXTO:
            #    - segmentos __c => custom lookup (CustomRecord)
            #    - segmentos normales => getattr (Django model / attrs)
            parts = path.split(".")
            current = root
            last_model_inst = root  # puede ser CustomRecord o Django Model

            from django.db.models import ForeignKey, OneToOneField

            for seg in parts:
                if current is None:
                    break

                # resolver un segmento a la vez (reutiliza tu _resolve_path y el nuevo lookup)
                next_val = self._resolve_path(current, seg)

                # Track del "último modelo/instancia válida"
                if isinstance(next_val, (CustomRecord, Model)):
                    last_model_inst = next_val
                else:
                    # Si current es Django model, intentamos detectar FK/O2O para mantener last_model_inst
                    try:
                        if isinstance(current, Model):
                            field = current.__class__._meta.get_field(seg)
                            if isinstance(field, (ForeignKey, OneToOneField)) and isinstance(next_val, Model):
                                last_model_inst = next_val
                    except Exception:
                        pass

                current = next_val

            # 3) Determinar instancia final para UPDATE/CREATE/DELETE
            if isinstance(current, (CustomRecord, Model)):
                return current, None

            if isinstance(last_model_inst, (CustomRecord, Model)) and last_model_inst is not root:
                # ej: income__c.project__c.quote.account.name  -> last_model_inst = Account
                return last_model_inst, None

            # fallback legacy: target era algo tipo "income__c.some_scalar"
            last_seg = parts[-1] if parts else None
            return root, last_seg

        # ==================================================
        # 🟢 LÓGICA NORMAL (MODELOS DJANGO)
        # ==================================================

        inst = None

        # 1) Contexto directo
        if obj_name in context and isinstance(context[obj_name], Model):
            inst = context[obj_name]

        # 2) Instancia principal
        if inst is None:
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj_name in (inst_name, instance.__class__.__name__.lower()):
                inst = instance

        # 3) Buscar en otros objetos del contexto por tipo
        if inst is None:
            for rec in context.values():
                if isinstance(rec, Model) and self._normalize_model_name(rec.__class__.__name__) == obj_name:
                    inst = rec
                    break

        # ❌ Si no se resolvió, no forzamos fallback
        if inst is None:
            return None, None

        # Sin path → target es el propio objeto
        if not path:
            return inst, None

        parts = path.split(".")
        current = inst
        last_model_inst: Optional[Model] = inst

        from django.db.models import ForeignKey, OneToOneField

        for seg in parts:
            if current is None:
                break

            next_val = self._resolve_path(current, seg)

            is_fk = False
            try:
                field = current.__class__._meta.get_field(seg)
                if isinstance(field, (ForeignKey, OneToOneField)):
                    is_fk = True
            except Exception:
                pass

            if is_fk and isinstance(next_val, Model):
                last_model_inst = next_val

            current = next_val

        # Caso 1: terminamos en un modelo
        if isinstance(current, Model):
            return current, None

        # Caso 2: terminamos en un campo, pero hubo FK antes
        if isinstance(last_model_inst, Model) and last_model_inst is not inst:
            return last_model_inst, None

        # Caso 3: legacy simple (quote.name)
        last_seg = parts[-1]
        return inst, last_seg
    
    def _evaluate_expression(self, formula: str, instance: Model, context: Dict[str, Any]):
        """
        Evaluador completo de expresiones CPQ con BLINDAJE TOTAL DE FECHAS:
        - Aritmética
        - IF(cond, a, b)
        - Strings
        - Fechas coherentes (date vs date)
        - Colecciones
        """

        import re
        from datetime import date, datetime, timedelta
        from dateutil.relativedelta import relativedelta
        from decimal import Decimal

        if not formula:
            return None

        expr = formula.strip()

        # -----------------------------------------------------
        # ✅ 1) Reemplazar referencias NORMALIZADAS
        # -----------------------------------------------------
        def replace_refs(match):
            ref = match.group(0)
            raw_val = self._resolve_expression_reference(ref, instance, context)

            # ✅ NORMALIZACIÓN GLOBAL
            val = self._normalize_value(raw_val)

            if val is None:
                return "None"

            if isinstance(val, Decimal):
                return str(float(val))

            if isinstance(val, bool):
                return "True" if val else "False"

            if isinstance(val, (int, float)):
                return str(val)

            # ✅ ✅ AQUÍ ESTÁ LA CLAVE DEL BUG
            # Forzamos datetime → date dentro del eval
            if isinstance(val, datetime):
                return f"datetime.fromisoformat('{val.isoformat()}').date()"

            if isinstance(val, date):
                return f"date.fromisoformat('{val.isoformat()}')"

            return f"'{str(val)}'"

        expr = re.sub(
            r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+",
            replace_refs,
            expr
        )

        # -----------------------------------------------------
        # ✅ 2) Entorno seguro con FECHAS COHERENTES
        # -----------------------------------------------------
        safe_env = {
            # Aritmética
            "ROUND": round,
            "FLOOR": lambda x: int(x // 1),
            "CEIL": lambda x: int(-(-x // 1)),
            "ABS": abs,
            "MAX": max,
            "MIN": min,

            # Condicional
            "IF": lambda cond, a, b: a if cond else b,

            # Strings
            "CONCAT": lambda *args: "".join(str(a) for a in args),
            "UPPER": lambda s: str(s).upper(),
            "LOWER": lambda s: str(s).lower(),
            "LEFT": lambda s, n: str(s)[:int(n)],
            "RIGHT": lambda s, n: str(s)[-int(n):],
            "TRIM": lambda s: str(s).strip(),
            "REPLACE": lambda s, a, b: str(s).replace(a, b),

            # Fechas BASE
            "TODAY": lambda: date.today(),
            "TOMORROW": lambda: date.today() + timedelta(days=1),
            "NOW": lambda: datetime.now().date(),

            # ✅ ✅ DATEADD COHERENTE (date entra → date sale)
            "DATEADD": lambda base, n, unit: (
                (
                    base + timedelta(days=int(n))
                    if "day" in unit.lower()
                    else base + relativedelta(months=int(n))
                    if "month" in unit.lower()
                    else base + relativedelta(years=int(n))
                ).date()
                if isinstance(base, datetime)
                else (
                    base + timedelta(days=int(n))
                    if "day" in unit.lower()
                    else base + relativedelta(months=int(n))
                    if "month" in unit.lower()
                    else base + relativedelta(years=int(n))
                )
            ),

            # Necesario para fechas ISO
            "datetime": datetime,
            "date": date,
        }

        # -----------------------------------------------------
        # ✅ 3) Colecciones NORMALIZADAS
        # -----------------------------------------------------
        def resolve_collection(expr_path):
            parts = expr_path.split(".")
            if len(parts) < 2:
                return []

            obj_name = parts[-2]
            field = parts[-1]

            for v in context.values():
                if hasattr(v, "all") and obj_name in str(v.model).lower():
                    return [self._normalize_value(getattr(item, field, 0)) for item in v.all()]

            return []

        safe_env["SUM"] = lambda lst: sum(resolve_collection(lst)) if isinstance(lst, str) else sum(lst)
        safe_env["AVG"] = lambda lst: (
            (sum(resolve_collection(lst)) / len(resolve_collection(lst)))
            if isinstance(lst, str) and resolve_collection(lst)
            else (sum(lst) / len(lst) if lst else 0)
        )
        safe_env["COUNT"] = lambda lst: (
            len(resolve_collection(lst)) if isinstance(lst, str) else len(lst)
        )

        # -----------------------------------------------------
        # ✅ 4) Ejecutar eval seguro
        # -----------------------------------------------------
        try:
            result = eval(expr, {"__builtins__": {}}, safe_env)
        except Exception as e:
            logger.warning(f"⚠️ Error evaluando expresión '{formula}': {e}")
            return None

        # -----------------------------------------------------
        # ✅ 5) NORMALIZACIÓN FINAL
        # -----------------------------------------------------
        return self._normalize_value(result)
    
    # -------------------------------------------------------------------------
    # ✅ GENERIC SEQUENCE RESOLVER (NEXT_SEQUENCE)
    # -------------------------------------------------------------------------
    def _resolve_sequence(self, seq_def: Dict[str, Any]):
        """
        Generic NEXT_SEQUENCE resolver.

        Strategies:
        - auto → intenta detectar si usar ID o MAX+1
        - id_based → usa el siguiente ID de Django
        - max_plus_one → usa MAX(field) + 1
        - scoped_max_plus_one → MAX(field) + 1 con filtros

        Ejemplo:
        {
            "type": "sequence",
            "strategy": "auto",
            "model": "quote",
            "field": "name",
            "prefix": "Q-",
            "padding": 5,
            "scope": { "account": 10 }
        }
        """

        strategy = seq_def.get("strategy", "auto")
        model_name = seq_def.get("model")
        field_name = seq_def.get("field")
        prefix = seq_def.get("prefix") or ""
        padding = int(seq_def.get("padding") or 0)
        scope = seq_def.get("scope")

        if not model_name or not field_name:
            logger.warning("⚠️ Invalid sequence definition (missing model/field)")
            return None

        ModelClass = self._get_model_class(model_name)
        if ModelClass is None:
            logger.warning(f"⚠️ Sequence model '{model_name}' not found")
            return None

        # ----------------------------------------------------------
        # ✅ AUTO STRATEGY
        # ----------------------------------------------------------
        if strategy == "auto":
            # Si el campo es 'name' o tiene prefijo → usar MAX+1
            field_obj = ModelClass._meta.get_field(field_name)
            if field_obj.get_internal_type() in ("CharField", "TextField"):
                strategy = "max_plus_one"
            else:
                strategy = "id_based"

        # ----------------------------------------------------------
        # ✅ ID BASED
        # ----------------------------------------------------------
        if strategy == "id_based":
            next_id = (ModelClass.objects.order_by("-id").first().id + 1) if ModelClass.objects.exists() else 1
            num = next_id

        # ----------------------------------------------------------
        # ✅ MAX + 1 GLOBAL
        # ----------------------------------------------------------
        elif strategy == "max_plus_one":
            existing = (
                ModelClass.objects
                .filter(**{f"{field_name}__startswith": prefix})
                .values_list(field_name, flat=True)
            )

            nums = []
            for v in existing:
                try:
                    clean = str(v).replace(prefix, "")
                    nums.append(int(clean))
                except Exception:
                    continue

            num = max(nums) + 1 if nums else 1

        # ----------------------------------------------------------
        # ✅ MAX + 1 CON SCOPE
        # ----------------------------------------------------------
        elif strategy == "scoped_max_plus_one":
            qs = ModelClass.objects.all()

            if isinstance(scope, dict):
                qs = qs.filter(**scope)

            existing = qs.values_list(field_name, flat=True)

            nums = []
            for v in existing:
                try:
                    clean = str(v).replace(prefix, "")
                    nums.append(int(clean))
                except Exception:
                    continue

            num = max(nums) + 1 if nums else 1

        else:
            logger.warning(f"⚠️ Unknown sequence strategy '{strategy}'")
            return None

        # ----------------------------------------------------------
        # ✅ FORMATEO FINAL
        # ----------------------------------------------------------
        num_str = str(num).zfill(padding) if padding else str(num)
        return f"{prefix}{num_str}"

    
    def _resolve_expression_reference(self, ref: str, instance: Model, context: Dict[str, Any]):
        """
        Resuelve referencias dentro de expresiones, como opportunity.name o quote.account.tier__c
        """
        if not ref or "." not in ref:
            return None

        parts = ref.split(".", 1)
        obj = parts[0].strip()
        path = parts[1].strip()

        # 🔥 Si es ".id" → no usar resolve_path, devolver instancia completa
        if path == "id":
            # contexto
            if obj in context and isinstance(context[obj], Model):
                return context[obj]

            # instancia principal
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj == inst_name:
                return instance

            # otros objetos en el contexto
            for cand in context.values():
                if isinstance(cand, Model) and self._normalize_model_name(cand.__class__.__name__) == obj:
                    return cand

            return None

        # Buscar en el contexto (alias)
        if obj in context and isinstance(context[obj], Model):
            return self._resolve_path(context[obj], path)

        # Buscar en la instancia principal
        inst_name = self._normalize_model_name(instance.__class__.__name__)
        if obj == inst_name:
            return self._resolve_path(instance, path)

        # Buscar en otros objetos del contexto
        for cand in context.values():
            if isinstance(cand, Model) and self._normalize_model_name(cand.__class__.__name__) == obj:
                return self._resolve_path(cand, path)

        return None
    
    def _coerce_fk(self, model_class, field_name, value, context=None, instance=None):
        """
        Convierte valores a instancias de ForeignKey.
        Casos soportados:
        - value = instancia correcta → devolver tal cual
        - value = ID → convertir a instancia
        - value = None y el field_def no especifica path → usar la instancia del evento
        """
        try:
            field = model_class._meta.get_field(field_name)
            from django.db.models import ForeignKey

            if not isinstance(field, ForeignKey):
                return value  # No es FK → devolver tal cual

            RelatedModel = field.related_model

            # 1) Ya es instancia correcta
            if isinstance(value, RelatedModel):
                return value

            # 2) Si es instancia de otro modelo → inválido
            if isinstance(value, Model):
                return None  # evitar error silencioso

            # 3) Si es ID → convertir
            if isinstance(value, (int, str)):
                try:
                    return RelatedModel.objects.get(pk=value)
                except RelatedModel.DoesNotExist:
                    return None

            # ✅ 4) Si value es None → NO intentar inferir nada
            if value is None:
                return None

        except Exception:
            pass

        return value

    
    def _evaluate_date_formula(self, formula: str, instance, context):
        """
        Evaluación avanzada y dinámica de expresiones de fecha.
        Capacidades:
            - today(), tomorrow(), now()
            - Fechas literales: "2025-12-01"
            - Aritmética: + / - N days/months/years/business_days
            - Funciones avanzadas:
                start_of_month(), end_of_month()
                start_of_year(),  end_of_year()
                next_month(), next_year()
            - Agregaciones:
                max(model.field)
                min(model.field)
            - Operaciones encadenadas
            - 🔒 NORMALIZACIÓN GLOBAL incluida
        """
        import re
        from datetime import date, datetime, timedelta
        from dateutil.relativedelta import relativedelta

        if not formula:
            return None

        f = formula.strip().lower()

        # =============================================================
        # 1) FECHAS LITERALES ("2025-12-05")
        # =============================================================
        literal_match = re.match(r'^["\'](\d{4}-\d{2}-\d{2})["\']$', f)
        if literal_match:
            try:
                return self._normalize_value(
                    datetime.strptime(literal_match.group(1), "%Y-%m-%d").date()
                )
            except Exception:
                return None

        # =============================================================
        # 2) FUNCIONES BASE
        # =============================================================
        today = date.today()
        now = datetime.now()

        base_function_map = {
            r"^today(\(\))?$"          : lambda: today,
            r"^tomorrow(\(\))?$"       : lambda: today + timedelta(days=1),
            r"^now(\(\))?$"            : lambda: now,

            r"^start_of_month(\(\))?$" : lambda: today.replace(day=1),
            r"^end_of_month(\(\))?$"   : lambda: (today.replace(day=1) + relativedelta(months=1) - timedelta(days=1)),
            r"^start_of_year(\(\))?$"  : lambda: date(today.year, 1, 1),
            r"^end_of_year(\(\))?$"    : lambda: date(today.year, 12, 31),

            r"^next_month(\(\))?$"     : lambda: today + relativedelta(months=1),
            r"^next_year(\(\))?$"      : lambda: today + relativedelta(years=1),
        }

        base_date = None

        # Match directo
        for pattern, func in base_function_map.items():
            if re.match(pattern, f):
                base_date = func()
                break

        # Match al inicio de una cadena
        if base_date is None:
            for pattern, func in base_function_map.items():
                if re.match(pattern, f.split()[0]):
                    base_date = func()
                    break

        if base_date is None:
            return None

        current = base_date

        # =============================================================
        # 3) AGREGACIONES: max(...) / min(...)
        # =============================================================
        agg_pattern = r"(max|min)\(([a-zA-Z0-9_\.]+)\)"
        aggs = re.findall(agg_pattern, f)

        for agg_func, full_path in aggs:
            parts = full_path.split(".")
            field = parts[-1]
            model_chain = parts[:-1]

            base_model_name = model_chain[0]
            base_model_snake = self._normalize_model_name(base_model_name)

            # -------------------------
            # Resolver instancia raíz
            # -------------------------
            root_obj = None

            if base_model_name in context:
                root_obj = context[base_model_name]
            elif base_model_snake == self._normalize_model_name(instance.__class__.__name__):
                root_obj = instance
            else:
                for cand in context.values():
                    if isinstance(cand, Model) and self._normalize_model_name(cand.__class__.__name__) == base_model_snake:
                        root_obj = cand
                        break

            if not root_obj:
                logger.debug(f"⚠ No se pudo resolver instancia para {full_path}")
                continue

            # -------------------------
            # Navegar la ruta anidada
            # -------------------------
            current_obj = root_obj
            for attr in model_chain[1:]:
                try:
                    current_obj = getattr(current_obj, attr)
                except Exception:
                    current_obj = None
                    break

            if hasattr(current_obj, "all"):
                items = list(current_obj.all())
            else:
                items = [current_obj]

            # -------------------------
            # Extraer y NORMALIZAR valores
            # -------------------------
            values = []
            for item in items:
                if item is None:
                    continue
                try:
                    raw_val = getattr(item, field)
                    norm_val = self._normalize_value(raw_val)   # ✅ NORMALIZACIÓN AQUÍ
                    values.append(norm_val)
                except Exception:
                    pass

            if not values:
                continue

            agg_value = max(values) if agg_func == "max" else min(values)

            f = f.replace(f"{agg_func}({full_path})", str(agg_value))

        # =============================================================
        # 4) OPERACIONES ARITMÉTICAS ENCANDENADAS
        # =============================================================
        op_pattern = r"([+-])\s*(\d+)\s*(days|day|months|month|years|year|business_days)"
        ops = re.findall(op_pattern, f)

        for sign, num, unit in ops:
            n = int(num)
            if sign == "-":
                n = -n

            if unit == "business_days":
                step = 1 if n > 0 else -1
                count = abs(n)
                while count > 0:
                    current = current + timedelta(days=step)
                    if current.weekday() < 5:
                        count -= 1
                continue

            if "day" in unit:
                current = current + timedelta(days=n)
                continue

            if "month" in unit:
                current = current + relativedelta(months=n)
                continue

            if "year" in unit:
                current = current + relativedelta(years=n)
                continue

        # ✅ NORMALIZACIÓN FINAL DEL RESULTADO
        return self._normalize_value(current)
    
    def _resolve_lookup(self, lookup_def: Dict[str, Any], instance: Model, context: Dict[str, Any]):
        """
        Generic lookup resolver.

        🔹 Soporta:
        - Django models (ORM)
        - Custom Objects (__c) → CustomRecord + CustomFieldValue

        lookup = {
            "type": "lookup",
            "model": "opportunity" | "proyecto__c",
            "where": {
                "logic": "AND",
                "items": [
                    { "field_name": "name", "operator": "==", "value": {...} }
                ]
            }
        }
        """

        model_name = lookup_def.get("model")
        where = lookup_def.get("where") or {}

        if not model_name or not where:
            logger.debug("⚠️ LOOKUP inválido: falta model o where")
            return None

        logic = (where.get("logic") or "AND").upper()
        items = where.get("items") or []

        # ==========================================================
        # 🟢 CASO 1: CUSTOM OBJECT (__c)
        # ==========================================================
        if self._is_custom_object(model_name):
            try:
                custom_object = CustomObject.objects.get(name=model_name)
            except CustomObject.DoesNotExist:
                logger.debug(f"⚠️ LOOKUP CustomObject '{model_name}' no existe")
                return None

            records = CustomRecord.objects.filter(object_type=custom_object)

            matched_records = []

            for rec in records:
                checks = []

                for cond in items:
                    field_name = cond.get("field_name") or cond.get("field")
                    operator = cond.get("operator", "==")
                    val_block = cond.get("value", {})

                    if not field_name:
                        continue

                    expected = self._resolve_value_for_action(val_block, instance, context)
                    actual = self._resolve_custom_field_value(rec, field_name)

                    # Normalización global (números, fechas, etc.)
                    actual, expected = self._normalize_pair(actual, expected)

                    ok = self._compare(actual, expected, operator)
                    checks.append(ok)

                    if logic == "AND" and not ok:
                        break

                    if logic == "OR" and ok:
                        break

                if (logic == "AND" and all(checks)) or (logic == "OR" and any(checks)):
                    matched_records.append(rec)

            if not matched_records:
                logger.debug(f"⚠️ LOOKUP {model_name}: 0 CustomRecord encontrados")
                return None

            if len(matched_records) > 1:
                logger.debug(f"⚠️ LOOKUP {model_name}: {len(matched_records)} resultados ambiguos")
                return None

            return matched_records[0]

        # ==========================================================
        # 🟢 CASO 2: DJANGO MODEL (COMPORTAMIENTO ORIGINAL)
        # ==========================================================
        ModelClass = self._get_model_class(model_name)
        if ModelClass is None:
            logger.debug(f"⚠️ LOOKUP model '{model_name}' no encontrado")
            return None

        orm_filters = {}

        for cond in items:
            field = cond.get("field_name") or cond.get("field")
            operator = cond.get("operator", "==")
            val_block = cond.get("value", {})

            if not field:
                continue

            resolved_value = self._resolve_value_for_action(val_block, instance, context)
            orm_key = field.replace(".", "__")

            if operator == "!=":
                orm_key = f"{orm_key}__ne"
            elif operator == ">":
                orm_key = f"{orm_key}__gt"
            elif operator == "<":
                orm_key = f"{orm_key}__lt"
            elif operator == ">=":
                orm_key = f"{orm_key}__gte"
            elif operator == "<=":
                orm_key = f"{orm_key}__lte"
            elif operator == "contains":
                orm_key = f"{orm_key}__icontains"
            elif operator == "in":
                orm_key = f"{orm_key}__in"

            orm_filters[orm_key] = resolved_value

        try:
            if logic == "OR":
                from django.db.models import Q
                q = Q()
                for k, v in orm_filters.items():
                    q |= Q(**{k: v})
                qs = ModelClass.objects.filter(q)
            else:
                qs = ModelClass.objects.filter(**orm_filters)

            count = qs.count()

            if count == 0:
                logger.debug(f"⚠️ LOOKUP {model_name}: 0 resultados con filtros {orm_filters}")
                return None

            if count > 1:
                logger.debug(f"⚠️ LOOKUP {model_name}: {count} resultados ambiguos con filtros {orm_filters}")
                return None

            return qs.first()

        except Exception as e:
            logger.exception(f"❌ Error ejecutando LOOKUP sobre {model_name}: {e}")
            return None
    
    def _recalc_quote_after_create_quoteline(self, quote_line_instance):
        """
        Recalcula un Quote cuando se crea una quote_line.
        Usado tanto en CREATE simple como en BULK CREATE.
        """
        from django.apps import apps

        Quote = apps.get_model("cpq", "Quote")
        q = Quote.objects.filter(pk=quote_line_instance.quote_id).first()
        if not q:
            return

        try:
            setattr(q, "_skip_trigger", True)

            logger.debug(
                "🔍 Pre-recalc Quote(pk=%s) discounts → type=%s, perc=%s, amount=%s",
                q.pk,
                q.discount_type,
                q.discount_percentage,
                q.discount_amount,
            )

            q.subtotal = q.get_subtotal_amount()
            q.update_discount_fields()
            q.update_net_amount()

            q.save(update_fields=[
                "subtotal", "discount_percentage", "discount_amount",
                "net_amount", "tax_amount", "tax_percentage", "updated_at"
            ])

            logger.debug(
                "✅ Post-recalc Quote(pk=%s) discounts → type=%s, perc=%s, amount=%s",
                q.pk,
                q.discount_type,
                q.discount_percentage,
                q.discount_amount,
            )
        except Exception as e:
            logger.exception(f"❌ Error recalculando Quote tras CREATE quote_line: {e}")
        finally:
            if hasattr(q, "_skip_trigger"):
                delattr(q, "_skip_trigger")

    def _resolve_operation_and_target_from_trigger(self, trig):
        actions = trig.actions or []

        if not isinstance(actions, list) or not actions:
            return "UNKNOWN", "UNKNOWN"

        first_action = actions[0]

        operation = (first_action.get("operation") or "UNKNOWN").upper()

        raw_target = first_action.get("target")
        if raw_target is None:
            target_model = "UNKNOWN"
        elif isinstance(raw_target, dict):
            target_model = (raw_target.get("object") or "UNKNOWN")
        else:
            target_model = self._resolve_target_model_name(raw_target) or "UNKNOWN"

        return operation, target_model

    
    def _filter_model_fields(self, ModelClass, data: dict):
        """
        Remove all keys that are NOT real Django model fields.
        This automatically removes all LOOKUP_* and any hallucinated keys.
        """
        if not isinstance(data, dict):
            return {}

        real_fields = {
            f.name for f in ModelClass._meta.get_fields()
            if f.concrete and not f.many_to_many
        }

        clean = {}
        for k, v in data.items():
            if k in real_fields:
                clean[k] = v

        return clean
    
    def _resolve_target_model_name(self, raw_target: Any) -> Optional[str]:
        """
        Dado un target (string path o dict), devuelve el nombre normalizado
        del modelo FINAL al que apunta el path.

        Reglas:
        - Si es dict → usa target["object"]
        - Si es string:
            - Empieza desde el primer segmento como modelo raíz
            - Recorre sólo campos ForeignKey / OneToOne
            - Si un segmento NO es FK, se detiene y devuelve el último modelo válido
              (ej: opportunity.primary_quote.account.name → Account)
        """
        if isinstance(raw_target, str) and raw_target.strip().endswith("__c"):
            return raw_target.strip()  # es custom object, no intentar apps.get_model
        
        # Dict legacy: {"object": "opportunity", "path": "..." }
        if isinstance(raw_target, dict):
            obj = (raw_target.get("object") or "").strip()
            return self._normalize_model_name(obj) if obj else None

        # Nada o no string
        if not isinstance(raw_target, str):
            return None

        raw = raw_target.strip()
        if not raw:
            return None

        parts = raw.split(".")
        root_name = parts[0]

        # Modelo raíz (event_root)
        ModelClass = self._get_model_class(root_name)
        if ModelClass is None:
            # Fallback: nos quedamos con el último segmento
            return self._normalize_model_name(parts[-1])

        # Recorremos sólo FKs / O2O
        from django.db.models import ForeignKey, OneToOneField

        for seg in parts[1:]:
            try:
                field = ModelClass._meta.get_field(seg)
            except Exception:
                # Segmento desconocido → nos quedamos en el último modelo válido
                break

            if isinstance(field, (ForeignKey, OneToOneField)):
                ModelClass = field.related_model
            else:
                # Campo normal → dejamos de bajar, usamos el último modelo FK
                break

        return self._normalize_model_name(ModelClass.__name__)
    
    def _detect_unique_clone_fields(self, ModelClass):
        """
        Retorna una lista de nombres de campos que son UNIQUE
        y que por diseño NO deben copiarse en CLONE.
        """
        uniques = []

        for f in ModelClass._meta.get_fields():
            if (
                f.concrete
                and not f.many_to_many
                and not f.primary_key
                and getattr(f, "unique", False)
            ):
                uniques.append(f.name)

        return uniques
    
    def _create_custom_field_value(
        self,
        *,
        record: CustomRecord,
        custom_field: CustomField,
        value: Any,
        user=None,
    ):
        """
        Crea un CustomFieldValue de forma consistente con UI y DB.

        🔒 Reglas:
        - SIEMPRE setea content_type + object_id
        - SIEMPRE apunta a CustomRecord
        - record NO sustituye el GenericForeignKey
        """

        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(record)

        return CustomFieldValue.objects.create(
            field=custom_field,

            # 🔑 Generic FK (OBLIGATORIO)
            content_type=content_type,
            object_id=record.pk,

            # 🔗 Relación directa
            record=record,

            value=str(value) if value is not None else "",
            updated_by_user=user,
        )
    
    def _ensure_event_root_in_context(self, context: Dict[str, Any], instance: Model):
        """
        Asegura que el objeto raíz del evento esté disponible en context
        bajo su nombre "de negocio".

        Ej:
        instance = CustomRecord(object_type.name="income__c")
        => context["income__c"] = instance
        """
        try:
            if isinstance(instance, CustomRecord):
                key = instance.object_type.name
                if key and key not in context:
                    context[key] = instance
        except Exception:
            pass


    def _extract_customrecord_id_from_any(self, raw: Any) -> Optional[int]:
        """
        Acepta:
        - int/str "66"  -> 66
        - custom_identifier "PRO-A-00066" -> 66 (último bloque numérico)
        """
        if raw is None:
            return None

        if isinstance(raw, int):
            return raw

        s = str(raw).strip()
        if not s:
            return None

        # Direct numeric
        if s.isdigit():
            try:
                return int(s)
            except Exception:
                return None

        # Find last numeric group (e.g. PRO-A-00066 -> 00066)
        nums = re.findall(r"(\d+)", s)
        if not nums:
            return None

        try:
            return int(nums[-1])
        except Exception:
            return None


    def _parse_lookup_model(self, lookup_model: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        lookup_model puede venir como:
        - "project__c" (CustomObject)
        - "cpq.account" (app_label.model)
        - "admin.LogEntry" (app_label.ModelName)
        Retorna (kind, app_label, model_name)
        kind:
            - "custom_object" (si termina en __c)
            - "django_model"  (si tiene app + model)
        """
        if not lookup_model:
            return None, None, None

        lm = str(lookup_model).strip()
        if not lm:
            return None, None, None

        if lm.endswith("__c"):
            return "custom_object", None, lm

        if "." in lm:
            app_label, model_name = lm.split(".", 1)
            app_label = app_label.strip()
            model_name = model_name.strip()
            if not app_label or not model_name:
                return None, None, None
            return "django_model", app_label, model_name

        # fallback (no sabemos)
        return None, None, None


    def _resolve_lookup_target_instance(self, *, field: CustomField, raw_value: Any) -> Any:
        """
        Resuelve a qué instancia apunta un CustomField lookup.

        - Si lookup_model es "__c" => CustomRecord del CustomObject correspondiente
        usando raw_value como (id o custom_identifier).
        - Si lookup_model es "app.Model" o "app.model" => Django model por pk.
        """
        if not field or not getattr(field, "lookup_model", None):
            return None

        kind, app_label, model_name = self._parse_lookup_model(field.lookup_model)

        # -------------------------------
        # LOOKUP a CustomObject (__c)
        # -------------------------------
        if kind == "custom_object":
            try:
                obj = CustomObject.objects.filter(name=model_name).first()
                if not obj:
                    return None

                # Soporta id o custom_identifier
                # 1) si es id directo -> filtra por pk
                cr_id = self._extract_customrecord_id_from_any(raw_value)

                if cr_id is not None:
                    rec = CustomRecord.objects.filter(object_type=obj, pk=cr_id).first()
                    if rec:
                        return rec

                # 2) intenta por custom_identifier exacto
                s = str(raw_value).strip() if raw_value is not None else ""
                if s:
                    rec = CustomRecord.objects.filter(object_type=obj, custom_identifier=s).first()
                    if rec:
                        return rec

                return None
            except Exception:
                return None

        # -------------------------------
        # LOOKUP a Django Model (app.Model)
        # -------------------------------
        if kind == "django_model":
            try:
                ModelClass = apps.get_model(app_label, model_name)
            except Exception:
                # fallback: a veces viene "cpq.account" (lower), Django lo acepta pero por si acaso:
                try:
                    ModelClass = apps.get_model(app_label, model_name.title())
                except Exception:
                    return None

            if ModelClass is None:
                return None

            # pk debe existir
            pk = raw_value
            if pk is None:
                return None

            # extraer int si viene tipo "ACC-00010" (no ideal, pero evita explotar)
            if isinstance(pk, str) and not pk.isdigit():
                maybe = self._extract_customrecord_id_from_any(pk)
                if maybe is not None:
                    pk = maybe

            try:
                return ModelClass.objects.filter(pk=pk).first()
            except Exception:
                return None

        return None
    
    def _build_event_context(self, *, object_type, action, instance, signal_timing, source=None):
        return {
            "object": object_type,
            "action": action,
            "pk": getattr(instance, "pk", None),
            "source": source,
            "signal_timing": signal_timing,
            "is_virtual": signal_timing == "virtual",
        }
    
    def _resolve_lookup_flexible(self, *, lookup_model, raw_value):
        from django.apps import apps

        if raw_value in (None, "", "---"):
            return None

        raw_str = str(raw_value).strip()

        # -------------------------------------------------
        # 1️⃣ PK directo (int o string numérico)
        # -------------------------------------------------
        if raw_str.isdigit():
            pk = int(raw_str)
            return self._resolve_lookup_by_pk(lookup_model, pk)

        # -------------------------------------------------
        # 2️⃣ Custom Identifier completo
        # -------------------------------------------------
        inst = self._resolve_lookup_by_identifier(
            lookup_model=lookup_model,
            identifier_value=raw_str
        )
        if inst:
            return inst

        # -------------------------------------------------
        # 3️⃣ Sufijo numérico (últimos dígitos)
        # -------------------------------------------------
        match = re.search(r"(\d+)$", raw_str)
        if match:
            pk = int(match.group(1))
            return self._resolve_lookup_by_pk(lookup_model, pk)

        return None
    
    def _resolve_lookup_by_pk(self, lookup_model, pk):
        from django.apps import apps

        try:
            if lookup_model.endswith("__c"):
                return CustomRecord.objects.filter(
                    object_type__name=lookup_model,
                    pk=pk
                ).first()

            app_label, model_name = lookup_model.split(".")
            Model = apps.get_model(app_label, model_name)
            return Model.objects.filter(pk=pk).first()

        except Exception:
            logger.exception(f"❌ Error resolving lookup by pk → {lookup_model}:{pk}")
            return None
        
    def _resolve_lookup_by_identifier(self, lookup_model: str, identifier_value: str):
        """
        Resolve a lookup value that may be:
        - pk (int / numeric string)
        - custom_identifier (e.g. PRO-A-00066)
        - numeric suffix of custom_identifier (e.g. 00066)

        Supports:
        - Custom Objects (__c → CustomRecord)
        - Django models (app.Model)

        Returns:
        - Model instance or None
        """
        from django.apps import apps

        if not identifier_value or not lookup_model:
            return None

        raw = str(identifier_value).strip()

        # -------------------------------------------------
        # 1️⃣ Direct PK resolution (fast path)
        # -------------------------------------------------
        if raw.isdigit():
            pk = int(raw)

            # Custom Object
            if lookup_model.endswith("__c"):
                obj = CustomRecord.objects.filter(
                    object_type__name=lookup_model,
                    pk=pk
                ).first()
                if obj:
                    return obj

            # Django model
            else:
                try:
                    app_label, model_name = lookup_model.split(".")
                    Model = apps.get_model(app_label, model_name)
                    obj = Model.objects.filter(pk=pk).first()
                    if obj:
                        return obj
                except Exception:
                    pass

        # -------------------------------------------------
        # 2️⃣ Custom Object resolution by identifier
        # -------------------------------------------------
        if lookup_model.endswith("__c"):
            qs = CustomRecord.objects.filter(
                object_type__name=lookup_model
            )

            # 2.a Exact custom_identifier match
            obj = qs.filter(custom_identifier=raw).first()
            if obj:
                return obj

            # 2.b Numeric suffix (e.g. PRO-A-00066 → 66)
            digits = "".join(c for c in raw if c.isdigit())
            if digits:
                try:
                    pk = int(digits.lstrip("0") or "0")
                    obj = qs.filter(pk=pk).first()
                    if obj:
                        return obj
                except Exception:
                    pass

            return None

        # -------------------------------------------------
        # 3️⃣ Django model resolution by identifier (best effort)
        # -------------------------------------------------
        try:
            app_label, model_name = lookup_model.split(".")
            Model = apps.get_model(app_label, model_name)
        except Exception:
            return None

        qs = Model.objects.all()

        # 3.a Try common identifier fields if they exist
        for field in ["custom_identifier", "identifier", "code", "external_id"]:
            if hasattr(Model, field):
                obj = qs.filter(**{field: raw}).first()
                if obj:
                    return obj

        # 3.b Numeric suffix fallback
        digits = "".join(c for c in raw if c.isdigit())
        if digits:
            try:
                pk = int(digits.lstrip("0") or "0")
                obj = qs.filter(pk=pk).first()
                if obj:
                    return obj
            except Exception:
                pass

        return None

# Instancia global del engine
engine = TriggerEngine()
