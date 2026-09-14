from django import template
from django.apps import apps
from django.urls import reverse, NoReverseMatch

register = template.Library()

KPI_MODELS = [
    ("Accounts", "cpq", "Account"),
    ("Opportunities", "cpq", "Opportunity"),
    ("Leads", "cpq", "Lead"),
    ("Contacts", "cpq", "Contact"),
    ("Products", "cpq", "Product"),
    ("Quotes", "cpq", "Quote"),
]


@register.simple_tag
def admin_kpis():
    """Return a list of {label, count} for the key objects shown on the admin
    dashboard. Counts are read defensively so a missing model never breaks the
    page."""
    kpis = []
    for label, app_label, model_name in KPI_MODELS:
        count = 0
        try:
            model = apps.get_model(app_label, model_name)
            count = model.objects.count()
        except Exception:
            count = 0
        url = None
        try:
            url = reverse(f"admin:{app_label}_{model_name.lower()}_changelist")
        except NoReverseMatch:
            url = reverse("admin:index")
        kpis.append({"label": label, "count": count, "url": url})
    return kpis
