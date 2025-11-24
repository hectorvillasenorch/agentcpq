from django.db.models import Q


def apply_filters(queryset, filters):
    """
    Aplica filters normalizados de tu LLM a un queryset.
    Cada filter viene con:
    {
        "field": "quote.account.tier__c",
        "operator": "==",
        "value": {
            "type": "static" / "field",
            "data": ...,
            "object": ...,
            "path": ...
        }
    }
    """
    q = Q()

    for f in filters:
        field_path = f["field"].replace(".", "__")
        op = f["operator"]
        v = f["value"]

        # Convert operator
        lookup = {
            "==": "",
            "!=": "",
            ">": "__gt",
            "<": "__lt",
            ">=": "__gte",
            "<=": "__lte",
            "contains": "__icontains",
            "in": "__in",
            "not in": "__in",  # se filtra al final
        }.get(op)

        # Compute value
        if v["type"] == "static":
            val = v.get("data")
        elif v["type"] == "field":
            # Para bulk CREATE / UPDATE, value.field solo se evalúa durante el loop
            # así que aquí ponemos placeholder
            val = None
        else:
            continue

        full_lookup = f"{field_path}{lookup}"

        if op == "!=":
            q &= ~Q(**{field_path: val})
        elif op == "not in":
            q &= ~Q(**{full_lookup: val})
        else:
            q &= Q(**{full_lookup: val})

    return queryset.filter(q)
