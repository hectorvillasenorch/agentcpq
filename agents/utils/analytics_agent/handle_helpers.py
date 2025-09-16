from cpq.models import Product, Lead, Account, Contact, Opportunity, Quote
from datetime import datetime, date, timedelta
from django.utils.timezone import now
from django.db.models import ForeignKey

def handle_show_metrics(user, completed_metrics):
    MODEL_MAP = {
        "Product": Product,
        "Lead": Lead,
        "Account": Account,
        "Contact": Contact,
        "Opportunity": Opportunity,
        "Quote": Quote,
    }

    response_message = ""
    results = {}

    for metric in completed_metrics:
        object_name = metric.get("object")
        method = metric.get("method", "read")
        limit = metric.get("limit", 10)
        conditions = metric.get("conditions", [])
        sort = metric.get("sort", None)

        # --- Validate that the object exists ---
        model = MODEL_MAP.get(object_name)
        if not model:
            response_message += f"⚠️ Unknown object '{object_name}'.<br>"
            continue

        filters = {}
        exclude_filters = {}

        # --- Apply conditions ---
        all_conditions_valid = True
        for cond in conditions:
            field = cond.get("field")
            operator = cond.get("operator")
            value = cond.get("value")

            if not field or not operator:
                continue

            supported, error_msg = apply_operator(field, operator, value, filters, exclude_filters, model=model)
            if not supported:
                response_message += (
                    f"⚠️ Condition failed for {object_name}: "
                    f"field='{field}', operator='{operator}', value='{value}'. "
                    f"Error: {error_msg}. Skipping this object.<br>"
                )
                all_conditions_valid = False
                break  # ⚡ salir del loop de condiciones si alguna falla

        # --- Si alguna condición falló, saltar al siguiente objeto ---
        if not all_conditions_valid:
            continue

        # --- Aplicar filtros y exclude ---
        qs = model.objects.all()
        if filters:
            qs = qs.filter(**filters)
        if exclude_filters:
            qs = qs.exclude(**exclude_filters)

        # --- Ordenamiento ---
        if sort and sort.get("field"):
            order_field = sort["field"]
            if sort.get("order") == "desc":
                order_field = f"-{order_field}"
            qs = qs.order_by(order_field)

        # --- Límite ---
        if limit:
            qs = qs[:limit]

        # Guardar resultados serializados
        results[object_name] = safe_serialize_queryset(qs, object_name)
        response_message += f"📊 Retrieved {qs.count()} {object_name}(s).<br>"

    return response_message, results


def apply_operator(field, operator, value, filters, exclude_filters, model=None):
    """
    Aplica un operador específico y actualiza filters/exclude_filters.
    Resuelve automáticamente ForeignKeys si se pasa un string.
    Retorna (True, "") si el operador es soportado,
    o (False, mensaje_error) si falla.
    """
    # --- Automatically resolve ForeignKeys ---
    if model:
        try:
            field_obj = model._meta.get_field(field)
            if isinstance(field_obj, ForeignKey) and isinstance(value, str):
                rel_model = field_obj.related_model
                lookup_field = 'username' if hasattr(rel_model, 'username') else 'name'
                try:
                    related_obj = rel_model.objects.get(**{lookup_field: value})
                    value = related_obj.pk
                except rel_model.DoesNotExist:
                    return False, f"related object with {lookup_field}='{value}' does not exist"
        except Exception as e:
            return False, f"field '{field}' does not exist or is invalid"

    # Operators dictionary
    operator_funcs = {
        "equals": lambda f, v: filters.update({f"{f}__exact": v}),
        "not_equals": lambda f, v: exclude_filters.update({f"{f}__exact": v}),
        "contains": lambda f, v: filters.update({f"{f}__icontains": v}),
        "starts_with": lambda f, v: filters.update({f"{f}__istartswith": v}),
        "ends_with": lambda f, v: filters.update({f"{f}__iendswith": v}),
        "greater_than": lambda f, v: filters.update({f"{f}__gt": v}),
        "greater_or_equal": lambda f, v: filters.update({f"{f}__gte": v}),
        "less_than": lambda f, v: filters.update({f"{f}__lt": v}),
        "less_or_equal": lambda f, v: filters.update({f"{f}__lte": v}),
        "before_date": lambda f, v: filters.update({f"{f}__lt": v}),
        "after_date": lambda f, v: filters.update({f"{f}__gt": v}),
        "in": lambda f, v: filters.update({f"{f}__in": v if isinstance(v, list) else [v]}),
        "not_in": lambda f, v: exclude_filters.update({f"{f}__in": v if isinstance(v, list) else [v]}),
        "is_true": lambda f, v: filters.update({f: True}),
        "is_false": lambda f, v: filters.update({f: False}),
        "within_last": lambda f, v: filters.update({
            f"{f}__gte": now() - timedelta(**(v if isinstance(v, dict) else {"days": int(v)}))
        }),
        "within_range": lambda f, v: filters.update({
            f"{f}__gte": v[0], f"{f}__lte": v[1]
        }) if isinstance(v, (list, tuple)) and len(v) == 2 else None,
    }

    func = operator_funcs.get(operator)
    if not func:
        return False, f"unsupported operator '{operator}'"

    func(field, value)
    return True, ""



from datetime import datetime, date
from django.db.models import ForeignKey

# Allowed fields per model
ALLOWED_FIELDS = {
    "Lead": ["first_name", "last_name", "phone", "email", "source", "contact", "status", "notes", "assigned_to", "created_at", "activities"],
    "Product": ["name", "sku", "price", "is_subscription", "term", "is_bundle", "family", "created_at", "description"],
    "Account": ["name", "industry", "website", "phone", "street", "city", "state", "zip_code"],
    "Contact": ["first_name", "last_name", "email", "phone", "company", "job_title", "notes", "account", "is_primary"],
    "Opportunity": ["name", "account", "amount", "stage", "expected_close_date", "primary_quote"],
    "Quote": ["name", "account", "opportunity", "subtotal", "net_amount", "tax_percentage", "tax_amount", "status",
              "discount_percentage", "discount_amount", "expiration_date", "notes", "created_at"],
    "Activity": ["subject", "activity_type", "status", "due_date"]
}

def safe_serialize_queryset(qs, model_name):
    allowed = ALLOWED_FIELDS.get(model_name, [])
    serialized = []

    for obj in qs:
        record = {}
        for field_name in allowed:
            value = getattr(obj, field_name, None)

            # Serialize ForeignKey as readable name
            field_obj = getattr(obj.__class__, field_name, None)
            if isinstance(field_obj, ForeignKey):
                if value is None:
                    value = None
                elif hasattr(value, "name"):
                    value = value.name
                elif hasattr(value, "first_name") and hasattr(value, "last_name"):
                    value = f"{value.first_name} {value.last_name}".strip()
                elif hasattr(value, "email"):
                    value = value.email
                else:
                    value = str(value.pk)

            # Serialize RelatedManager (reverse FK or M2M)
            elif hasattr(value, "all"):
                related_list = []
                for rel_obj in value.all():
                    rel_model = rel_obj.__class__.__name__
                    rel_allowed = ALLOWED_FIELDS.get(rel_model, [])
                    rel_data = {}
                    for f in rel_allowed:
                        v = getattr(rel_obj, f, None)
                        # Convert related object FKs to string
                        f_obj = getattr(rel_obj.__class__, f, None)
                        if isinstance(f_obj, ForeignKey):
                            if v is None:
                                v = None
                            elif hasattr(v, "name"):
                                v = v.name
                            elif hasattr(v, "first_name") and hasattr(v, "last_name"):
                                v = f"{v.first_name} {v.last_name}".strip()
                            elif hasattr(v, "email"):
                                v = v.email
                            else:
                                v = str(v.pk)
                        elif isinstance(v, (datetime, date)):
                            v = v.isoformat()
                        rel_data[f] = v
                    related_list.append(rel_data)
                value = related_list

            # Serialize dates
            elif isinstance(value, (datetime, date)):
                value = value.isoformat()

            # Convert any non-serializable object to string
            elif isinstance(value, (int, float, bool, str)) or value is None:
                pass
            else:
                value = str(value)

            record[field_name] = value
        serialized.append(record)
    return serialized
