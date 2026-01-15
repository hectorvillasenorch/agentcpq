from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agentcpq.intelligence"
    label = "intelligence"
    verbose_name = "Intelligence"

    def ready(self):
        from . import signals  # noqa: F401
