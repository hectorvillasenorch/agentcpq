

def get_session_context(action, session_data):

    # Get or create state on session_data
    session_data.setdefault("state", {})

    # Initialize default state if not exists
    if action not in session_data.get("state", {}):
        if action == "create_product":
            context_data = {
                "create_product": [
                    {
                        "data": {
                            "name": None,
                            "sku": None,
                            "price": None,
                            "description": None,
                            "is_bundle": None,
                            "is_subscription": None,
                            "term": None,
                            "family": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        session_data["state"] = context_data

    current_state = session_data["state"][action]
    previous_summary = session_data["state"].get("summary")

    return current_state, previous_summary