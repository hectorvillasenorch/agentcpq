def resolve_value_fields(values_block, source_instance=None):
    """
    Para CREATE.value.fields o UPDATE.value:
    Convierte:
    - static → literal
    - field → toma valor de source_instance.<path>
    - expression → (aún no soportamos evaluation aquí)
    - date → (lo evaluas en tu engine si quieres)
    """
    result = {}

    for field_name, spec in values_block.items():

        if spec["type"] == "static":
            result[field_name] = spec["data"]

        elif spec["type"] == "field":
            obj = source_instance
            path = spec["path"].split(".")
            for part in path:
                if obj is None:
                    break
                obj = getattr(obj, part, None)
            result[field_name] = obj

        elif spec["type"] in ["expression", "date"]:
            # El TriggerEngine debe resolver expressions y date formulas antes.
            # Aquí asumimos que action.data ya trae los valores evaluados.
            return values_block

    return result
