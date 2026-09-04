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
        from cpq.action_trigger.trigger_engine import engine
        try:
            engine.register_signals()
        except Exception as exc:
            # Allow the app to boot even when DB schema isn't migrated yet (e.g., first Heroku deploy).
            try:
                from django.db import ProgrammingError, OperationalError
                if isinstance(exc, (ProgrammingError, OperationalError)):
                    return
            except Exception:
                pass
            raise
        # t = threading.Thread(target=start_renewal_scheduler, daemon=True)
        # t.start()

        # 📧 Deliver scheduled email reminders (runs every ~60s in-process).
        if os.environ.get("RUN_AUTO_RELOAD") != "true":
            try:
                from .tasks.email_scheduler import start_email_scheduler

                thread = threading.Thread(target=start_email_scheduler, daemon=True, name="email-scheduler")
                thread.start()
            except Exception:
                # Never block app boot because of the scheduler.
                pass
