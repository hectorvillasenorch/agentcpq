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

from cpq.actions.executor import CustomActionExecutor
from cpq.models import ActionLog, CustomObject, CustomField, CustomFieldValue, CustomRecord

# Import helpers and format
from cpq.action_trigger.helpers.helpers_and_format import (
    normalize_model_name,
    to_camel_case,
    debug_alias_map,
    normalize_number,
    make_json_safe,
    get_model_class,
)


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TriggerEngine:
    def __init__(self):
        self.action_handlers = {
            "SET": self._handle_set,
            "UPDATE": self._handle_set,
            "CREATE": self._handle_create,
            "DELETE": self._handle_delete,
            "EMAIL": self._handle_email,
            "WEBHOOK": self._handle_webhook,
        }

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

        models_to_watch = self._get_models_to_watch()

        for model in models_to_watch:
            # Pre signals
            pre_save.connect(self._make_signal_receiver("pre_save"), sender=model, weak=False)
            pre_delete.connect(self._make_signal_receiver("pre_delete"), sender=model, weak=False)

            # Post signals
            post_save.connect(self._make_signal_receiver("post_save"), sender=model, weak=False)
            post_delete.connect(self._make_signal_receiver("post_delete"), sender=model, weak=False)

        logger.info("⚙️ TriggerEngine: señales registradas (pre/post save/delete) para %d modelos", len(models_to_watch))
    
    def _make_signal_receiver(self, timing: str):
        """
        Receiver con ejecución deduplicada mediante execution_fingerprint.
        """
        def _receiver(sender, instance, **kwargs):
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
            # 2) Si este fingerprint ya se ejecutó → evitar duplicados
            # --------------------------------------------------------------
            if fingerprint in self._executed_fingerprints:
                logger.debug(
                    f"⚠️ Duplicate trigger prevented via fingerprint ({sender.__name__}, pk={instance.pk})"
                )
                return

            # --------------------------------------------------------------
            # 3) Determinar acción (create / update / delete)
            # --------------------------------------------------------------
            created = kwargs.get("created", None)
            if timing in ("pre_delete", "post_delete"):
                action = "delete"
            elif created is True:
                action = "create"
            else:
                action = "update"

            object_type = self._normalize_model_name(sender.__name__)
            event_type = f"{object_type}.{action}"

            ActionTrigger = apps.get_model("cpq", "ActionTrigger")
            active_triggers = [
                t for t in ActionTrigger.objects.filter(active=True, signal_timing=timing)
                if self._event_type_matches(t.event_type, event_type)
            ]

            if not active_triggers:
                logger.debug(f"\n🕐 SIGNAL [{timing.upper()} → {event_type}] — No trigger actions\n")
                return

            logger.debug(
                "\n" + "=" * 80 +
                f"\n⚡ Trigger fired [{timing.upper()} → {event_type}]\n"
                f"   📦 Model: {sender.__name__}\n"
                f"   🔑 PK: {getattr(instance, 'pk', None)}\n"
                f"   🕐 Instance: {instance}\n" +
                "=" * 80
            )

            # --------------------------------------------------------------
            # 4) Registrar fingerprint como “ya ejecutado” para evitar loops
            # --------------------------------------------------------------
            self._executed_fingerprints.add(fingerprint)

            # --------------------------------------------------------------
            # 5) Ejecutar evento
            # --------------------------------------------------------------
            try:
                self._execute_event(event_type, instance, timing)
            except Exception as exc:
                logger.exception(
                    "❌ Error handling event %s (%s): %s", event_type, timing, exc
                )

        return _receiver


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

    # -------------------------------------------------------------------------
    # Main entry point for an event
    # -------------------------------------------------------------------------
    def handle_event(self, object_type: str, action: str, instance: Model, signal_timing: str = "post_save"):
        """
        Procesa un evento usando el sistema anti-duplicados basado en fingerprint.
        """
        event_type = f"{object_type}.{action}"
        logger.debug(f"⚙️ Processing triggers for event {event_type} [{signal_timing}]")

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

        # ------------------------------------------------------------------
        # Ejecutar cada trigger
        # ------------------------------------------------------------------
        for trig in triggers:
            try:
                matched, context = self._evaluate_trigger(trig, instance)
                if not matched:
                    continue

                exec_results = self._execute_trigger_actions(trig, instance, context)
                results.append({"trigger_id": getattr(trig, "id", None), "results": exec_results})

                # Si acciones afectan quote o quote_line
                for action_data in (trig.actions or []):
                    target = (action_data.get("target") or {}).get("object", "")
                    if target in ("quote", "quote_line"):

                        if target == "quote":
                            quotes_to_recalc.add(instance.pk)

                        if target == "quote_line" and getattr(instance, "quote_id", None):
                            quotes_to_recalc.add(instance.quote_id)

            except Exception as exc:
                logger.exception("❌ Trigger %s execution error: %s", getattr(trig, "id", "?"), exc)

        # ------------------------------------------------------------------
        # Recalcular quotes afectadas
        # ------------------------------------------------------------------
        if quotes_to_recalc:
            Quote = apps.get_model("cpq", "Quote")
            for qid in quotes_to_recalc:
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

                    logger.debug(f"🔁 Recalculated Quote(pk={q.pk}) after trigger execution")

                except Exception as e:
                    logger.exception(f"❌ Error recalculating Quote(pk={qid}): {e}")
                finally:
                    if hasattr(q, "_skip_trigger"):
                        delattr(q, "_skip_trigger")

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

        return results


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
            obj = stored_event.get("object_type")
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
        """

        conditions = trigger.conditions or {"logic": "AND", "items": []}
        items: List[Dict[str, Any]] = conditions.get("items", [])
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
            if alias is None:
                alias_candidates[alias] = [instance]
                continue

            # Detectar modelo del lado derecho
            right_models = [
                c.get("right", {}).get("object")
                for c in conds
                if isinstance(c.get("right", {}), dict)
                and c["right"].get("type") == "field"
                and c["right"].get("object")
            ]
            model_name = right_models[0] if right_models else None

            if not model_name:
                logger.debug("⚠️ Alias '%s' sin modelo detectable en right.object", alias)
                return False, {}

            # Filtros: only == conditions
            filters: Dict[str, Any] = {}

            for c in conds:
                if c.get("operator") not in ("==", "="):
                    continue

                left = c.get("left", {})
                right = c.get("right", {})
                if right.get("type") == "field" and right.get("object") == model_name:
                    expected = self._resolve_value_from_reference(left, {None: instance}, instance)
                    filters[right.get("path")] = expected

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
            left = cond.get("left", {})
            right = cond.get("right", {})
            op = cond.get("operator")

            left_val = self._resolve_value_from_reference(left, alias_map, instance)
            right_val = self._resolve_value_from_reference(right, alias_map, instance)

            ok = self._compare(left_val, right_val, op)
            results.append(ok)

            # ✔ AND: si una falla, el trigger falla
            if logic == "AND" and not ok:
                logger.debug(
                    "❌ Condición NO cumple (AND): %s %s %s (resueltos: %s %s %s)",
                    left, op, right, left_val, op, right_val
                )
                return False, {}

            # ✔ OR: si una es verdadera, el trigger es válido
            if logic == "OR" and ok:
                logger.debug(
                    "✅ Condición cumple (OR): %s %s %s (resueltos: %s %s %s)",
                    left, op, right, left_val, op, right_val
                )
                return True, alias_map

            # si OR pero esta individual falla → continuar evaluando

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
            return ref.get("data")

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
            path = ref.get("path")
            alias = ref.get("alias")  # Recomendado para custom

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

                value = self._resolve_custom_field_value(rec, path)
                logger.debug("📌 Resolviendo CustomObject: %s.%s (alias=%s) => %s", obj_name, path, alias, value)
                return value

            # Modelo nativo desde alias_map
            if obj_name in alias_map and alias_map[obj_name] is not None:
                return self._resolve_path(alias_map[obj_name], path)

            # Modelo nativo = instancia principal
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj_name == inst_name:
                return self._resolve_path(instance, path)

            # Buscar en otros objetos del contexto
            for rec in alias_map.values():
                if rec is not None and self._normalize_model_name(rec.__class__.__name__) == obj_name:
                    return self._resolve_path(rec, path)

            return None

        # --------------------------------------------------
        # Sin type (left-like) → relativo al instance
        # --------------------------------------------------
        obj_name = ref.get("object")
        path = ref.get("path")
        if obj_name is None and path:
            return self._resolve_path(instance, path)

        inst_name = self._normalize_model_name(instance.__class__.__name__)
        if obj_name in (inst_name, instance.__class__.__name__.lower(), None):
            return self._resolve_path(instance, path)

        if obj_name in alias_map and alias_map[obj_name] is not None:
            return self._resolve_path(alias_map[obj_name], path)

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
        - UPDATE simple (SET / UPDATE de un campo)
        - UPDATE bulk (con target.filters)
        - DELETE simple
        - DELETE bulk (con target.filters)
        - EMAIL / WEBHOOK
        """
        results = []

        for action in (trigger.actions or []):
            op = (action.get("operation") or "").upper()
            target = action.get("target") or {}
            value_def = action.get("value") or {}
            action_filters = action.get("filters")  # usado solo en BULK CREATE
            target_filters = target.get("filters")  # usado en BULK UPDATE / DELETE

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
            # 🟩 CREATE SIMPLE (sin filtros, igual que AT-001)
            # ==================================================================
            if op == "CREATE":
                model_name = target.get("object")
                if not model_name:
                    continue

                ModelClass = apps.get_model("cpq", self._to_camel_case(model_name))

                # contexto para resolver fields
                context["_current_action"] = {
                    "target_object": model_name,
                    "target_model": ModelClass,
                }

                fields = self._resolve_value_for_action(value_def, instance, context)
                if not isinstance(fields, dict):
                    fields = {}

                final_fields = {
                    f: self._coerce_fk(ModelClass, f, v, context=context, instance=instance)
                    for f, v in fields.items()
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
            # 📝 UPDATE SIMPLE (SET) → TODO pasa por _handle_set
            # ==================================================================
            if op == "UPDATE":
                result = self._handle_set(action, instance, context)
                results.append({"action": action, "status": "ok", "result": result})
                continue

            # ==================================================================
            # 🗑️ DELETE SIMPLE (sin filtros) → borrar UNA instancia
            # ==================================================================
            if op == "DELETE":
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
        """
        filters = action.get("filters") or {}
        source_model_name = filters.get("source_object")
        items = filters.get("items", [])

        if not source_model_name:
            return {"created": False, "reason": "source_object missing in filters"}

        SourceModel = self._get_model_class(source_model_name)
        if SourceModel is None:
            return {"created": False, "reason": f"Source model '{source_model_name}' not found"}

        target_obj_name = action.get("target", {}).get("object")
        TargetModel = self._get_model_class(target_obj_name)
        if TargetModel is None:
            return {"created": False, "reason": f"Target model '{target_obj_name}' not found"}

        # ----------------------------------------------------------------------
        # 1. Build ORM filters for SourceModel
        # ----------------------------------------------------------------------
        orm_filters = {}

        for f in items:
            field = f.get("field")
            op = f.get("operator", "==")
            val_block = f.get("value", {})

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
            local_context[source_model_name] = source_record  # CORRECCIÓN CRÍTICA

            # Store action for FK coercion
            local_context["_current_action"] = {
                "target_object": target_obj_name,
                "target_model": TargetModel,
            }

            # Resolve CREATE fields
            fields = self._resolve_value_for_action(action.get("value", {}), instance, local_context)

            final_fields = {}
            for fname, raw in fields.items():
                final_fields[fname] = self._coerce_fk(TargetModel, fname, raw, context=local_context, instance=instance)

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
        """
        target = action.get("target", {})
        value_def = action.get("value", {})

        model_name = target.get("object")
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

        for f in (target.get("filters") or []):
            field = f.get("field")
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
        # 2. Resolver los fields a actualizar
        # ----------------------------------------------------------------------
        raw_fields = self._resolve_value_for_action(value_def, instance, context)
        # raw_fields → {'field1': value, 'field2': value2, ...}

        if not raw_fields:
            return {"updated": False, "reason": "no resolved fields"}

        updated_pks = []

        # ----------------------------------------------------------------------
        # 3. Recorrer cada registro y actualizar uno por uno
        # ----------------------------------------------------------------------
        for obj in rows:
            for field, new_value in raw_fields.items():
                # Soporte FK
                coerced = self._coerce_fk(ModelClass, field, new_value, context=context, instance=obj)
                setattr(obj, field, coerced)

            setattr(obj, "_skip_trigger", True)
            obj.save(update_fields=list(raw_fields.keys()))
            delattr(obj, "_skip_trigger")

            updated_pks.append(obj.pk)
            logger.debug(f"🔧 BULK UPDATE updated {model_name}(pk={obj.pk}) fields={raw_fields}")

        # ----------------------------------------------------------
        # 🔁 Recalcular quotes afectadas (igual que en DELETE)
        # ----------------------------------------------------------
        from django.apps import apps

        # Si el objeto que se está actualizando es quote_line
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


    def _handle_set(self, action, instance, context):
        """
        Ejecuta una acción SET/UPDATE sobre un campo, incluyendo soporte
        para campos CustomFields (__c) en cualquier modelo (Account, Quote, etc.)
        """
        from django.contrib.contenttypes.models import ContentType

        target = action.get("target", {})
        value_def = action.get("value", {})

        target_inst, target_field = self._resolve_target_instance_and_field(target, instance, context)
        if target_inst is None or not target_field:
            return {"updated": False, "reason": "no se pudo resolver instancia/field del target"}

        new_val = self._resolve_value_for_action(value_def, instance, context)
        if new_val is None:
            return {"updated": False, "reason": "valor no resuelto o nulo"}

        # 1) Campo __c → CustomFieldValue
        if target_field.endswith("__c"):
            try:
                ct = ContentType.objects.get_for_model(target_inst.__class__)
                model_name = target_inst.__class__.__name__

                cf = (
                    CustomField.objects.filter(
                        name=target_field,
                        object_type__iexact=model_name
                    ).first()
                    or CustomField.objects.filter(
                        name=target_field,
                        custom_object__name__iexact=model_name
                    ).first()
                )

                if not cf:
                    logger.warning(f"⚠️ No se encontró CustomField '{target_field}' para {model_name}")
                    return {"updated": False, "reason": f"CustomField '{target_field}' no encontrado"}

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
                    f"{model_name}.{target_field} = {new_val} (pk={cfv.pk})"
                )

                return {"updated": True, "pk": cfv.pk, "custom_field": target_field}

            except Exception as e:
                logger.exception(f"❌ Error actualizando CustomFieldValue {target_field}: {e}")
                return {"updated": False, "reason": str(e)}

        # 2) Campo nativo
        setattr(target_inst, target_field, new_val)

        # Evitar loops (para que no vuelva a disparar el trigger)
        setattr(target_inst, "_skip_trigger", True)
        try:
            target_inst.save(update_fields=[target_field])
        finally:
            if hasattr(target_inst, "_skip_trigger"):
                delattr(target_inst, "_skip_trigger")

        logger.debug(
            "📝 UPDATE %s.%s = %s (pk=%s)",
            self._normalize_model_name(target_inst.__class__.__name__),
            target_field,
            new_val,
            target_inst.pk,
        )

        return {"updated": True, "pk": target_inst.pk}

    def _handle_create(self, action, instance, context):
        return {"created": False}
    
    def _handle_create(self, action, instance, context):
        # legacy path - bulk create handled earlier
        return {"created": False}

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
        return {"emailed": True}

    def _handle_webhook(self, action, instance, context):
        return {"webhook": True}

    def _resolve_value_for_action(self, value_def: Dict[str, Any], instance: Model, context: Dict[str, Any]):
        """
        Resolución completa para CREATE / UPDATE:
        - Soporta path="" → usar instancia completa
        - Respeta source_object en bulk
        - Coerce FK correctamente
        """
        if not value_def:
            return None

        # ----------------------------------------------------------------------
        # CASE 1: CREATE → fields{}
        # ----------------------------------------------------------------------
        if "fields" in value_def:
            resolved = {}

            for fname, field_def in value_def["fields"].items():
                ftype = field_def.get("type")
                obj = field_def.get("object")
                path = field_def.get("path", "")
                alias = field_def.get("alias")

                # STATIC
                if ftype == "static":
                    resolved[fname] = field_def.get("data")
                    continue

                # FIELD
                if ftype == "field":
                    base = None

                    # PRIORIDAD ALTA → contexto directo
                    if obj in context:
                        base = context[obj]

                    # Instancia principal
                    inst_name = self._normalize_model_name(instance.__class__.__name__)
                    if base is None and obj == inst_name:
                        base = instance

                    # path vacío → usar instancia completa del obj
                    if path == "":
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
                    resolved[fname] = self._evaluate_expression(field_def.get("formula", ""), instance, context)
                    continue

                # DATE
                if ftype == "date":
                    resolved[fname] = self._evaluate_date_formula(field_def.get("formula", ""), instance, context)
                    continue

                # ✅ SEQUENCE (NEXT_SEQUENCE)
                if ftype == "sequence":
                    resolved[fname] = self._resolve_sequence(field_def)
                    continue

            return resolved

        # ----------------------------------------------------------------------
        # CASE 2: UPDATE / DELETE → simple value.type
        # ----------------------------------------------------------------------
        ftype = value_def.get("type")

        if ftype == "static":
            return value_def.get("data")

        if ftype == "field":
            obj = value_def.get("object")
            path = value_def.get("path", "")

            if obj in context:
                if path == "":
                    return context[obj]
                return self._resolve_path(context[obj], path)

            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj == inst_name:
                return self._resolve_path(instance, path)

            for cand in context.values():
                if isinstance(cand, Model) and self._normalize_model_name(cand.__class__.__name__) == obj:
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

        if isinstance(obj, CustomRecord):
            cobj = obj.object_type
            cf = CustomField.objects.filter(custom_object=cobj, name=field_name).first()
            if not cf:
                logger.debug(f"⚠️ No existe CustomField '{field_name}' en {cobj.name}")
                return None

            cfv = CustomFieldValue.objects.filter(field=cf, record=obj).first()
            if not cfv:
                logger.debug(f"⚠️ CustomRecord {obj.pk} no tiene valor para '{field_name}'")
                return None

            return self._return_custom_value(cf, cfv)

        ct = ContentType.objects.get_for_model(obj.__class__)
        cfs = CustomFieldValue.objects.filter(
            content_type=ct,
            object_id=obj.pk
        ).select_related("field", "record", "field__custom_object")

        for cfv in cfs:
            if cfv.field.name == field_name:
                return self._return_custom_value(cfv.field, cfv)

        logger.debug(f"⚠️ No se encontró valor para {obj} → {field_name}")
        return None

    def _return_custom_value(self, field, cfv):
        if field.data_type and field.data_type.lower().strip() == "lookup" and field.lookup_model:
            target_obj = cfv.content_object or cfv.record
            next_field = getattr(self, "_next_custom_field", None)
            if next_field and next_field.endswith("__c"):
                return self._resolve_custom_field_value(target_obj, next_field)
            return target_obj
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
        if t in ("decimal", "float", "double", "currency"):
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

    def _fallback_custom_record_from_alias_map(self, alias_map: Dict[Optional[str], Any], custom_object_name: str):
        matches = [
            rec for rec in alias_map.values()
            if isinstance(rec, CustomRecord) and getattr(rec.object_type, "name", None) == custom_object_name
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _resolve_target_instance_and_field(
        self,
        target_def: Dict[str, Any],
        instance: Model,
        context: Dict[Optional[str], Any],
    ) -> Tuple[Optional[Model], Optional[str]]:
        if not target_def:
            return None, None

        obj_name = (target_def.get("object") or "").strip()
        path = (target_def.get("path") or "").strip()

        if not obj_name or not path:
            return None, None

        # Punto de inicio
        inst = None

        if obj_name in context and isinstance(context[obj_name], Model):
            inst = context[obj_name]

        if inst is None:
            inst_name = self._normalize_model_name(instance.__class__.__name__)
            if obj_name in (inst_name, instance.__class__.__name__.lower()):
                inst = instance

        if inst is None:
            for rec in context.values():
                if isinstance(rec, Model) and self._normalize_model_name(rec.__class__.__name__) == obj_name:
                    inst = rec
                    break

        if inst is None:
            inst = instance

        parts = path.split(".")
        *leading, last = parts

        current = inst
        for seg in leading:
            if current is None:
                break
            current = self._resolve_path(current, seg)

        if current is None or not isinstance(current, Model):
            return None, None

        if last.endswith("__c") and len(parts) > 1:
            prev_seg = leading[-1] if leading else None
            if prev_seg and prev_seg.endswith("__c"):
                resolved_obj = self._resolve_path(inst, ".".join(leading))
                if resolved_obj is not None:
                    return resolved_obj, last

        return current, last
    
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
                return "0"

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

            # 2) Si es ID → convertir
            if isinstance(value, (int, str)):
                try:
                    return RelatedModel.objects.get(pk=value)
                except RelatedModel.DoesNotExist:
                    return None

            # 3) Si value es None pero tenemos contexto
            if value is None and instance is not None:
                inst_name = self._normalize_model_name(instance.__class__.__name__)
                if inst_name == self._normalize_model_name(RelatedModel.__name__):
                    return instance

            # 4) Si value es None y hay alias en context
            if value is None and context:
                for cand in context.values():
                    if isinstance(cand, RelatedModel):
                        return cand

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

            q.subtotal = q.get_subtotal_amount()
            q.update_discount_fields()
            q.update_net_amount()

            q.save(update_fields=[
                "subtotal", "discount_percentage", "discount_amount",
                "net_amount", "tax_amount", "tax_percentage", "updated_at"
            ])

            logger.debug(f"✅ Quote(pk={q.pk}) recalculada tras CREATE quote_line")
        except Exception as e:
            logger.exception(f"❌ Error recalculando Quote tras CREATE quote_line: {e}")
        finally:
            if hasattr(q, "_skip_trigger"):
                delattr(q, "_skip_trigger")

# Instancia global del engine
engine = TriggerEngine()
