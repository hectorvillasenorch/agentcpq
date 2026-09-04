from django import template

register = template.Library()


@register.filter(name="move_apps_to_end")
def move_apps_to_end(app_list, labels):
    """Move apps whose app_label is in the comma-separated ``labels`` list to the end.

    Used by the admin dashboard override so the CPQ section renders last
    (after Intelligence), even though it sorts alphabetically in the middle.
    """
    to_move = [label.strip() for label in (labels or "").split(",") if label.strip()]
    if not to_move:
        return app_list
    items = list(app_list)
    moved = [app for app in items if app.get("app_label") in to_move]
    rest = [app for app in items if app.get("app_label") not in to_move]
    return rest + moved
