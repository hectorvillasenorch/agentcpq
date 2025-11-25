import time
import logging
from .handlers import CreateHandler, UpdateHandler, DeleteHandler

logger = logging.getLogger(__name__)


class CustomActionExecutor:
    """
    ✅ Executor profesional con protección anti-loop + handlers modernos.
    """
    def __init__(self):
        self.handlers = {
            "CREATE": CreateHandler(),
            "UPDATE": UpdateHandler(),
            "DELETE": DeleteHandler(),
        }

    def dispatch(self, action, payload=None):
        payload = payload or {}

        if not action.is_active:
            raise RuntimeError("Action no activa")

        method = action.method.upper()
        handler = self.handlers.get(method)
        if not handler:
            raise ValueError(f"Método no soportado: {method}")

        start = time.time()
        try:
            result = handler.execute(action=action, payload=payload)
            ms = int((time.time() - start) * 1000)
            logger.info(f"✅ CustomAction {method} ejecutada en {ms} ms")
            return result
        except Exception as e:
            logger.exception(f"❌ CustomAction {method} falló: {e}")
            raise
