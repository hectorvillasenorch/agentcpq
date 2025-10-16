from django.apps import AppConfig
import os
import threading

class CpqConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cpq"

    # Variable de clase para evitar lanzar múltiples schedulers
    scheduler_started = False

    def ready(self):
        import cpq.signals

        from .tasks.renewals_scheduler import start_renewal_scheduler
        # t = threading.Thread(target=start_renewal_scheduler, daemon=True)
        # t.start()
