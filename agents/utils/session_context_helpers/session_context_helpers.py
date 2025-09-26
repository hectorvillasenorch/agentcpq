

def get_session_context(action, session_data):

    # Get or create state on session_data
    session_data.setdefault("state", {})

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

        session_data["state"] = context_data

    current_state = session_data["state"][action]
    previous_summary = session_data["state"].get("summary")

    return current_state, previous_summary
