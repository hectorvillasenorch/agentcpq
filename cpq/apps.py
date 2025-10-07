from django.apps import AppConfig
import threading

class CpqConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cpq"

    def ready(self):
        import cpq.signals

        from .tasks.renewals_scheduler import start_renewal_scheduler
        t = threading.Thread(target=start_renewal_scheduler, daemon=True)
        t.start()