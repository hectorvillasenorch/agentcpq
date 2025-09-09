import threading, logging

def run_agent_async(agent_func, *args, **kwargs):
    """
    Runs an agent function in a separate thread.
    Catches any exception and returns a generic error message.
    Returns a dict in the expected format.
    """
    result_container = {}

    def wrapper():
        try:
            result = agent_func(*args, **kwargs)
            if result is None:
                result_container["result"] = {
                    "message": "⚠️ Something went wrong inside AgentCPQ, please try again. "
                               "If the issue persists, contact AgentCPQ support."
                }
            else:
                result_container["result"] = result
        except Exception as e:
            logging.error(f"❌ Error in agent function {agent_func.__name__}: {str(e)}", exc_info=True)
            result_container["result"] = {
                "message": "⚠️ Something went wrong inside AgentCPQ, please try again. "
                           "If the issue persists, contact AgentCPQ support."
            }

    thread = threading.Thread(target=wrapper)
    thread.start()
    thread.join()  # Wait for completion (optional, can remove if realmente quieres async)
    return result_container["result"]
