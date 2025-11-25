from django.utils.deprecation import MiddlewareMixin

from django.utils.deprecation import MiddlewareMixin
from cpq.action_trigger.trigger_engine import engine
#from cpq.action_trigger.queue import TriggerQueue
import logging

class SaveLastDashboardSessionMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            path = request.path

            # Solo guardar si la URL empieza con /dashboard/
            if path.startswith("/dashboard/") or path == "/dashboard":
                request.session["last_dashboard_session"] = request.get_full_path()

        return None


logger = logging.getLogger(__name__)

#class CPQTriggerMiddleware(MiddlewareMixin):
#    """
#    Middleware global:
#    - Deja la cola activa durante el request
#    - Al finalizar (response o exception), hace flush de todos los eventos encolados
#    """
#
#    def process_request(self, request):
#        # Asegura que la cola esté activa por request (por si algún código la desactiva temporalmente)
#        TriggerQueue.enable()
#        return None
#
#    def process_exception(self, request, exception):
#        try:
#            TriggerQueue.flush(engine)
#        except Exception:
#            logger.exception("❌ Error flushing TriggerQueue on exception")
#        # No corta la propagación de la excepción
#        return None
#
#    def process_response(self, request, response):
#        try:
#            TriggerQueue.flush(engine)
#        except Exception:
#            logger.exception("❌ Error flushing TriggerQueue on response")
#        return response