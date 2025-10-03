import threading
import time
from datetime import datetime, timedelta
from django.utils import timezone
from cpq.models import RenewalTask, Opportunity
from cpq.renewals.renewals import make_opportunity_renewal
import logging

logger = logging.getLogger(__name__)

def should_create_renewal(opportunity):
    """
    Verifica si ya existe un Opportunity renewal para esta oportunidad.
    """
    account_name = opportunity.account.name
    renewal_name = f"Opportunity renewal for {account_name}"
    exists = Opportunity.objects.filter(name=renewal_name).exists()
    return not exists

def run_renewal_tasks():
    """
    Revisa todos los RenewalTask pendientes para el día actual y ejecuta
    make_opportunity_renewal si no existe todavía la renovación.
    """
    today = timezone.localtime().date()  # zona horaria de settings
    tasks = RenewalTask.objects.filter(status="pending", execute_at__date__lte=timezone.localtime().date())
    
    for task in tasks:
        opp = task.opportunity
        if should_create_renewal(opp):
            result = make_opportunity_renewal(opp)
            if result is True:
                task.status = "done"
                task.last_error = ""
                logger.info(f"✅ Renewal executed for Opportunity {opp.id} via scheduler")
            else:
                task.status = "failed"
                task.last_error = result[1] if isinstance(result, tuple) else "Unknown error"
                logger.error(f"❌ Renewal failed for Opportunity {opp.id}: {task.last_error}")
            task.attempts += 1
            task.updated_at = timezone.now()
            task.save()
        else:
            logger.info(f"⚠️ RenewalTask for Opportunity {opp.id} already exists, skipping task.")
            task.status = "done"
            task.updated_at = timezone.now()
            task.save()

def seconds_until_next_12pm():
    """
    Calcula los segundos hasta las 12 PM según la zona horaria de settings.
    """
    now_tz = timezone.localtime()
    next_run = now_tz.replace(hour=12, minute=0, second=0, microsecond=0)
    if now_tz >= next_run:
        next_run += timedelta(days=1)
    return (next_run - now_tz).total_seconds()

def start_renewal_scheduler():
    """
    Scheduler que corre una primera vez al iniciar y luego cada 24h a las 12 PM.
    """
    logger.info("🚀 Renewal scheduler started")
    # --- primera ejecución inmediata ---
    run_renewal_tasks()

    while True:
        sleep_seconds = seconds_until_next_12pm()
        logger.info(f"⏱ Sleeping {sleep_seconds/3600:.2f} hours until next run at 12 PM")
        time.sleep(sleep_seconds)
        run_renewal_tasks()