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

        # Solo lanzar el scheduler si no se ha iniciado y si estamos en el proceso principal
        if not CpqConfig.scheduler_started and os.environ.get("RUN_MAIN") == "true":
            from .tasks.renewals_scheduler import start_renewal_scheduler

            # Crear hilo daemon para que corra en segundo plano
            t = threading.Thread(target=start_renewal_scheduler, daemon=True)
            t.start()

            # Marcar como iniciado
            CpqConfig.scheduler_started = True