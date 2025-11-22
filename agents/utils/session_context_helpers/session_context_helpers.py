

def get_session_context(action, session_data):

    # Get or create state on session_data
    session_data.setdefault("state", {})

    last_attempt = session_data["state"].get("last_attempt")

    if last_attempt and last_attempt != action:
        if last_attempt in session_data["state"]:
            del session_data["state"][last_attempt]
        session_data["state"]["last_attempt"] = action
    else:
        session_data["state"]["last_attempt"] = action

    # Initialize default state if not exists
    if action not in session_data.get("state", {}):
        if action == "create_quote":
            context_data = {
                "create_quote": {
                    "data": {
                        "account": None,
                        "opportunity": None,
                        "products": [
                            {
                                "sku": None,
                                "name": None,
                                "quantity": None,
                                "discount_type": None,
                                "discount_value": None,
                                "term": None
                            }
                        ],
                        "start_date": "",
                        "end_date": ""
                    },
                    "completed": False
                },
                "summary": None
            }

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

        if action == "update_quote_line":
            context_data = {
                "update_quote_line": [
                    {
                        "data": {
                            "sku": None,
                            "name": None,
                            "fields": {
                                "quantity": None,
                                "discount_type": None,
                                "discount_percentage": None,
                                "discount_amount": None,
                                "term": None
                            }
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "add_product_to_quote":
            context_data = {
                "add_product_to_quote": [
                    {
                        "data": {
                            "sku": None,
                            "name": None,
                            "quantity": None,
                            "discount_type": None,
                            "discount_value": None,
                            "term": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "delete_quote_line":
            context_data = {
                "delete_quote_line": [
                    {
                        "data": {
                            "sku": None,
                            "name": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "update_quote":
            context_data = {
                "update_quote": [
                    {
                        "data": {
                            "quote_name": None,
                            "field": None,
                            "value": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "show_metrics":
            context_data = {
                "show_metrics": [
                    {
                        "data": {
                            "object": None,
                            "method": "read",
                            "limit": None,
                            "conditions": [
                                {
                                    "field": None,
                                    "operator": None,
                                    "value": None
                                },
                                {
                                    "field": None,
                                    "operator": None,
                                    "value": None
                                }
                            ],
                            "sort": {
                                "field": None,
                                "order": None
                            }
                        },
                        "completed": False
                    }
                ],
                "summary": None
            }

        if action == "create_inclusion_rule":
            context_data = {
                "create_inclusion_rule": [
                    {
                        "data": {
                            "description": None,
                            "rule_type": "inclusion",
                            "target_type": None,
                            "priority": 10,
                            "message": None,
                            "active": True,
                            "conditions": {
                                "trigger_product": {
                                    "sku": None,
                                    "name": None
                                },
                                "included_products": [],
                                "options": [],
                                "applies_to": None
                            }

                        },
                        "completed": False
                    }
                ],
                "summary": None
            }

        if action == "create_action_trigger":
            context_data = {
                "create_action_trigger": [
                    {
                        "data": {
                            "description": None,
                            "event_type": None,
                            "active": None,
                            "conditions": {},
                            "actions": {}

                        },
                        "completed": False
                    }
                ],
                "summary": None
            }

        if action == "create_exclusion_rule":
            context_data = {
                "create_exclusion_rule": [
                    {
                        "data": {
                            "description": None,
                            "rule_type": "exclusion",
                            "target_type": None,
                            "priority": 10,
                            "error_message": None,
                            "active": True,
                            "conditions": {
                                "excluded_products": []
                            }

                        },
                        "completed": False
                    }
                ],
                "summary": None
            }

        if action == "update_custom_field":
            context_data = {
                "update_custom_field": [
                    {
                        "data": {
                            "target_field_label": None,
                            "target_custom_object": None,
                            "target_default_object": None,
                            "updates": {
                                "label": None,
                                "crm": None,
                                "object_type": None,
                                "data_type": None,
                                "required": True,
                                "custom_object": None,
                                "options": None
                            }

                        },
                        "completed": False
                    }
                ],
                "summary": None
            }
            
        if action == "show_quote_details":
            context_data = {
                "show_quote_details": [
                    {
                        "data": {
                            "quote": None,
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "show_rules":
            context_data = {
                "show_rules": [
                    {
                        "data": {
                            "request_description": None,
                            "name": None,
                            "rule_type": None,
                            "target_type": None,
                            "priority": None,
                            "active": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        if action == "update_rule":
            context_data = {
                "update_rule": [
                    {
                        "data": {
                            "name": None
                        },
                        "completed": False
                    },
                ],
                "summary": None
            }

        session_data["state"].update(context_data)

    current_state = session_data["state"][action]
    previous_summary = session_data["state"].get("summary")

    return current_state, previous_summary


def clear_session_state(state, session_data):
    if "state" in session_data and state in session_data["state"]:
        del session_data["state"][state]