import logging
from ..utils import run_async
from ..models import ActionTrigger, ScheduledTask
from ..renewals.renewals import make_opportunity_renewal, create_renewal_task_for_opportunity
from django.utils.timezone import now

logger = logging.getLogger(__name__)


def fire_triggers(trigger_name: str, context: dict):
    """
    Busca ActionTrigger activos para trigger_name y ejecuta su acción.
    context: dict con información del evento (ej: {'opportunity': opportunity})
    """
    triggers = ActionTrigger.objects.filter(trigger=trigger_name, active=True)
    for trig in triggers:
        try:
            if trig.object_name == "renewal_task" and trig.action == "create":
                opp = context.get("opportunity")

                if not opp or not opp.quotes.first():
                        logger.warning(f"⚠️ Trigger {trig.id} fired without valid opportunity/quote in context")
                        continue
                
                contract = opp.contracts.filter(contract_status="Active").first()

                if not contract:
                    logger.warning(f"⚠️ Trigger {trig.id} fired but opportunity has no contract")
                    continue
                
                execute_at = trig.action_params["months_before"]

                if execute_at == "immediately":
                    try:
                        result = make_opportunity_renewal(opp)
                        if result is True:
                            status = "done"
                            last_error = ""
                        else:
                            status = "failed"
                            last_error = result[1]  # mensaje de error

                        ScheduledTask.objects.create(
                            opportunity=opp,
                            execute_at=now(),
                            status=status,
                            attempts=1,
                            last_error=last_error,
                            created_at=now(),
                            updated_at=now()
                        )

                    except Exception as e:
                        logger.exception(f"❌ Error creating renewal task for opportunity {opp.id}: {e}")

                else:
                    months_before = int(trig.action_params.get("months_before", 6))
                    create_renewal_task_for_opportunity(opp, months_before=months_before)

            else:
                logger.warning(f"⚠️ Unknown action {trig.action} on {trig.object_name} for trigger {trig.id}")

        except Exception as e:
            logger.exception(f"❌ Error firing trigger {trig.id}: {e}")


def dispatch_trigger(trigger_name: str, context: dict):


    try:
        run_async(fire_triggers, trigger_name, context)
        logger.info(f"\n🚀 Trigger {trigger_name} dispatched.\n")
    except Exception as e:
        logger.exception(f"\n❌ Error dispatching trigger {trigger_name}: {e}.\n")