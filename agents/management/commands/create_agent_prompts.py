from django.core.management.base import BaseCommand
from agents.models import AgentPrompt

class Command(BaseCommand):
    help = "Create default AgentPrompts in the database"

    def handle(self, *args, **options):
        # Lista de prompts por defecto
        default_prompts = [
            {
                "agent_name": "custom_object_agent",
                "method": "update",
                "function": "extract_custom_records_updates",
                "system_instructions": """"
                    Extract structured custom objects records details from the following request.

                    You are an AI assistant that extracts structured data to update multiple custom object record from the message.

                    ---

                    Given a user instruction, extract:
                    - The correct record_identifier (must match exactly one of the identifiers from the list)
                    - The values: a list of {"field", "value"} pairs based only on the available fields of that object.

                    Each field must match exactly one of the label values in the selected object’s fields.

                    ---

                    Format your response in this exact JSON structure:

                    ```json
                    [
                    "record_identifier": "record_identifier_here"
                    "values": [
                        {
                            "field": "field_label_here",
                            "value": "value_from_user_message"
                        },
                        {
                            "field": "field_label_here",
                            "value": "value_from_user_message"
                        }
                        // Add as many as you find in the user message
                        ]
                    ]

                    *Example Input & Output:*

                    User: "Please update record INV-00045: change the amount to $1750 and set the status to Paid."
                    Response:
                    [
                        {
                            "record_identifier": "INV-00045",
                            "values": [
                                {
                                    "field": "amount",
                                    "value": 1750
                                },
                                {
                                    "field": "status",
                                    "value": "Paid"
                                }
                            ]
                        }
                    ]


                    User: "For work orders WO-00012 and WO-00013, set the priority to High. Also, mark WO-00012 as In Progress and WO-00013 as Completed."
                    Response:
                    [
                        {
                            "record_identifier": "WO-00012",
                            "values": [
                                {
                                    "field": "priority",
                                    "value": "High"
                                },
                                {
                                    "field": "status",
                                    "value": "In Progress"
                                }
                            ]
                        },
                        {
                            "record_identifier": "WO-00013",
                            "values": [
                                {
                                    "field": "priority",
                                    "value": "High"
                                },
                                {
                                    "field": "status",
                                    "value": "Completed"
                                }
                            ]
                        }
                    ]
                """,
                "system_rules": """
                **Requirements:**
                    - If no "record_identifier" is found in the message, return null as "record_identifier".
                    - The "record_identifier" must always be returned in uppercase letters.
                    - The fields to fill must be taken from the provided list of fields.
                    - If no value is found for a field in the user message, set "value" as null.

                    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "custom_object_agent",
                "method": "update",
                "function": "extract_custom_fields_updates",
                "system_instructions": """
                    Extract structured custom fields details from the following request.

                    Return a JSON array of fields, where each object must include:

                    - "target_field_label" (string): The label of the custom field that will be updated.
                    - "target_custom_object" (string): The custom object that the custom field to be updated belongs to.
                    - "target_default_object" (string): The default object that the custom field to be updated belongs to.
                    - "updates":
                        - "label" (string): This will be the new label for the Custom Field.
                        - "crm" (string): This will be the new CRM for the Custom Field.
                        - "object_type": This will be the new default object in AgentCPQ that the field belongs to. Must be one of: Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.
                        - "data_type" (string): This will be the data type for the Custom Field. Must be one of: text, number, date, boolean, dropdown, text_area, or lookup.
                        - "required" (boolean): This will indicate whether the field is required in the custom object.
                        - "custom_object" (String): This will be the label or name of the custom object this field belongs to. It must be one of the current custom objects.
                        - "options" (Array of strings): For dropdown data type if requires options.

                    *Example Input & Output:*

                    User: "Please update the "Product Category" field from the "Inventory" custom object. I'd like to change the label to "Category", set the CRM to "HubSpot", make it not required, and set the data type to "dropdown" with the following options: Electronics, Clothing, Home, and Toys."
                    Response:
                    [
                        {
                            "target_field_label": "Product Category",
                            "target_custom_object": "Inventory",
                            "target_default_object": null,
                            "updates": {
                                "label": "Category",
                                "crm": "HubSpot",
                                "object_type": null,
                                "required": false,
                                "custom_object": null,
                                "data_type": "dropdown",
                                "options": ["Electronics", "Clothing", "Home", "Toys"]
                            }
                        }
                    ]

                    User: "I’d like to update the following fields: the first one is the "UOM" field from the "Product" object — I’d like to change its label to "Unit Of Measure", change the object to the custom object Inventory and set the data type to text; the second one is the "Event Type" field from the "Event" object — I’d like to change its data type to dropdown with the following options: Wedding, Birthday, and Graduation."
                    Response:
                    [
                        {
                            "target_field_label": "UOM",
                            "target_custom_object": null,
                            "target_default_object": "Product",
                            "updates": {
                                "label": "Unit Of Measure",
                                "crm": null,
                                "object_type": null,
                                "required": null,
                                "custom_object": "Inventory",
                                "data_type": "text",
                                "options": ["Electronics", "Clothing", "Home", "Toys"]
                            }
                        },
                        {
                            "target_field_label": "Event Type",
                            ""target_custom_object": "Event",
                            "target_default_object": null,
                            "updates": {
                                "label": "Unit Of Measure",
                                "crm": null,
                                "object_type": null,
                                "required": null,
                                "custom_object": null,
                                "data_type": "dropdown",
                                "options": ["Wedding", "Birthday", "Graduation"]
                            }
                        }
                    ]

                    User: "Change the field named UOM from the vehicle object to the default product object."
                    Response:
                    [
                        {
                            "target_field_label": "UOM",
                            "target_custom_object": "Vehicle",
                            "target_default_object": null,
                            "updates": {
                                "label": null,
                                "crm": null,
                                "object_type": "Product",
                                "required": null,
                                "custom_object": null,
                                "data_type": null,
                                "options": null
                            }
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - If "target_field_label" is not found in the message, set it as null.
                    - If "target_custom_object" is not found in the message, set it as null.
                    - If "target_default_object" is not found in the message, set it as null.
                    - Exactly one of "target_custom_object" or "target_default_object" must be set to indicate the current location of the field. The other must be null.
                    - The value of "target_custom_object" must be one of the current custom objects..
                    - The value of "target_default_object" must be one of the following default objects: Activity, Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.
                    - The destination where the field should be moved or updated must be indicated inside "updates" as either:
                        - "object_type" (for default system objects: Activity, Lead, Contact, Account, Opportunity, Product, Quote, QuoteLine), or
                        - "custom_object" (for custom objects).
                    - If "object_type" inside "updates" has a value, then "custom_object" inside "updates" must be set to null, and vice versa. They must never both have values at the same time.
                    - If the field is being moved from a custom object to a default object, then:
                        - Set "target_custom_object" to the current custom object name,
                        - Set "target_default_object" to null,
                        - Set the destination default object name inside "updates.object_type".
                    - Conversely, if moving from a default object to a custom object, then:
                        - Set "target_default_object" to the current default object name,
                        - Set "target_custom_object" to null,
                        - Set the destination custom object name inside "updates.custom_object".
                    - If "updates" is not found in the message, set it as null.
                    - Inside "updates", if any of the fields "label", "crm", "object_type", "required", "custom_object", "data_type", or "options" are not found, set them as null.
                    - The field "crm" inside "updates" can only be one of: "AgentCPQ", "HubSpot", or "Salesforce".
                    - If the "data_type" is "dropdown", include the dropdown choices in a key called "options" as an array of strings.
                    - If "data_type" is not "dropdown", set "options" to null.
                    - If the "data_type" is "dropdown" but no "options" are found in the message, set "options" as null.



                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "custom_object_agent",
                "method": "update",
                "function": "extract_custom_objects_updates",
                "system_instructions": """
                    Extract structured custom objects details from the following request.

                    Return a JSON array of objects, where each object must include:

                    - "label" (string): The label of the Custom Object that user wants to update.
                    - "udpates":
                        - "label" (string): The new label value for the Custom Object
                        - "description" (string): The new description value for the Custom Object

                    *Example Input & Output:*

                    User: "change the label of the object Invoice to Client Invoice"
                    Response:
                    [
                        {
                            "label": "Payment",
                            "updates: {
                                "label: "Client Invoice",
                                "description": null
                            }
                        }
                    ]

                    User: "Update the Subscription object: change the label to Membership and set the description to Handles recurring user payments."
                    Response:
                    [
                        {
                            "label": "Subscription",
                            "updates: {
                                "label: "Membership",
                                "description": "Handles recurring user payments."
                            }
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - The first "label" key represents the label of the custom object that will be edited.
                    - The second "label" key represents the value to be updated for the custom object.
                    - If no "label" is found in the message, return null as "label".
                    - The "label" must always start with a capital letter.
                    - If no "description" is found in the message, return null as "description"

                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "custom_object_agent",
                "method": "create",
                "function": "extract_custom_objects",
                "system_instructions": """
                    Extract structured custom objects details from the following request.

                    Return a JSON array of objects, where each object must include:

                    - "label" (string): The label of the Custom Object
                    - "description" (string): If user wants to update the description

                    *Example Input & Output:*

                    User: "create a custom object named payment"
                    Response:
                    [
                        {
                            "label": "Payment"
                            "description": "Stores the invoice number or billing reference associated with this record for accounting and tracking purposes."
                        }
                    ]

                    User: "Please create a custom field named invoice. The description should be: 'Stores the invoice number or reference related to this record for billing and tracking purposes."
                    Response:
                    [
                        {
                            "label": "Invoice"
                            "description": "Stores the invoice number or reference related to this record for billing and tracking purposes."
                        }
                    ]

                    User: "Hey, I’d like to add a few custom fields to my object. One should be called Invoice, which will store the invoice number or reference for billing purposes. Another one named Customer Type to track whether the customer is new, returning, or a partner. And also a field called Delivery Date to specify when the product or service is expected to be delivered."
                    Response:
                    [
                        {
                            "label": "Invoice"
                            "description": "Stores the invoice number or billing reference associated with this record for accounting and tracking purposes."
                        },
                        {
                            "label": "Customer Type"
                            "description": "Indicates the classification of the customer, such as New, Returning, or Partner, to help segment and tailor sales strategies."
                        },
                        {
                            "label": "Delivery Date"
                            "description": "Specifies the expected date of delivery for the product or service, useful for planning and customer communication."
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - If no "label" is found in the message, return null as "label".
                    - The "label" must always start with a capital letter.
                    - If no "description" is found in the message, return a short inferred description based on the context of the custom field.
                    - If the message explicitly states that no description should be included, set "description" to null.

                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0.8,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "update",
                "function": "extract_email_alert_updates",
                "system_instructions": """
                    Extract structured data from the user’s message to update one or multiple email alerts.
                    Return a JSON array of objects, where each object must include:

                    If the user wants to update the description, native_object, custom_object, offset_days, scheduled_cron or active then use the following JSON structure to extract the data:
                    - "alert_name" (string): The name of the email alert to be updated
                    - "description" (string): A short description of the email alert. If the user does not specify a description, infer one.
                    - "trigger" (string): The trigger that fires the alert. It can be any of the following: lead_created, account_created, opportunity_created, opportunity_closed_won, opportunity_closed_lost, quote_sent_for_approval, quote_approved, quote_rejected, quote_expiring, subscription_renewal.
                    - "native_object" (string): If the email alert is directed to a native object from the following list: Lead, Account, Opportunity, Quote, Subscription.
                    - "custom_object": If the email alert is directed to a custom object. 
                    - "offset_days" (int): Integer that indicates the days before or after the trigger when the alert should be sent. If the number is positive, it indicates days before; if the number is negative, it indicates days after.
                    - "scheduled_cron" (string): Cron format for sending the alert.

                    If the user wants to add, remove, or replace any recipient in their request, then extend the base JSON structure with the following:

                    - "recipients":
                        Inside recipients we will have a list of actions
                        - "action" (string): The action to perform on the recipients, it can be add, remove or replace.
                        - "remove" (List):
                            - "users" (List): List of user recipients for the email alert. If the user explicitly specifies that the alert should be sent to themselves (for example by saying "send me", "notify me", "alert me", "me"), then automatically include the username of the requesting user: {user.username}. In this field, only usernames are allowed—no emails, no roles.
                            - "roles" (List): List of role recipients for the email alert. The possible roles are: all_superusers, all_admins, all_staff, creator.
                                The field "recipients_roles" expects one or more of the following values:
                                - all_superusers
                                - all_admins
                                - all_staff
                                - creator

                                When the user mentions:
                                - "superusers", it should be interpreted as "all_superusers"
                                - "admins", it should be interpreted as "all_admins"
                                - "staff", it should be interpreted as "all_staff"

                                Always convert these user terms to the corresponding role keys before saving to the database.

                            - "externals" (List): List of external email recipients. The user must specify these in the message.
                        - "add" (List):
                            - "users" (List): List of user recipients for the email alert. If the user explicitly specifies that the alert should be sent to themselves (for example by saying "send me", "notify me", "alert me", "me"), then automatically include the username mentionated at the end of this prompt. In this field, only usernames are allowed—no emails, no roles.
                            - "roles" (List): List of role recipients for the email alert. The possible roles are: all_superusers, all_admins, all_staff, creator.
                                The field "recipients_roles" expects one or more of the following values:
                                - all_superusers
                                - all_admins
                                - all_staff
                                - creator

                                When the user mentions:
                                - "superusers", it should be interpreted as "all_superusers"
                                - "admins", it should be interpreted as "all_admins"
                                - "staff", it should be interpreted as "all_staff"

                                Always convert these user terms to the corresponding role keys before saving to the database.

                            - "externals" (List): List of external email recipients. The user must specify these in the message.


                    *Example Input & Output:*

                    User: "I would like to update the email alert account_created__045. I want to replace the recipient users user_alpha, user_beta, user_gamma with user_delta, user_epsilon."
                    Response:
                    [
                        {
                            "alert_name": "account_created__045",
                            "description": null,
                            "trigger": null,
                            "native_object": null,
                            "custom_object": null,
                            "offset_days": null,
                            "scheduled_cron": null,
                            "active": null
                            "recipients": {
                                "action": "replace",
                                "remove": {
                                    "users": ["user_alpha", "user_beta", "user_gamma"],
                                    "roles": [],
                                    "externals": []
                                },
                                "add": {
                                    "users": ["user_delta", "user_epsilon"],
                                    "roles": [],
                                    "externals": []
                                }
                            }
                        }
                    ]

                    User: "I want to update the alert account_created__023. Set the description to “Account creation alert”, set the trigger to account_created, set the native object to Accoun, make it inactive. Replace recipients: remove users (user1, user2, user3) and roles (admins); add users (user4, user5), roles (staff), and externals (partner@domain.com)."
                    Response:
                    [
                        {
                            "alert_name": "account_created__023",
                            "description": "Account creation alert",
                            "trigger": "account_created",
                            "native_object": "Account",
                            "custom_object": null,
                            "offset_days": null,
                            "scheduled_cron": null,
                            "active": false,
                            "recipients": {
                                "action": "replace",
                                "remove": {
                                    "users": ["user1", "user2", "user3"],
                                    "roles": ["admins"],
                                    "externals": []
                                },
                                "add": {
                                    "users": ["user4", "user5"],
                                    "roles": ["staff"],
                                    "externals": ["partner@domain.com"]
                                }
                            }
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - If "alert_name" is not specified, set it as null.
                    - If "description" is not specified, set it as null.
                    - If "trigger" is not specified, set it as null.
                    - If "native_object" is not specified, set it as null.
                    - If "custom_object" is not specified, set it as null.
                    - If "action" is not specified, set it as null.
                    - If "recipients" is not specified, set it as null.
                    - If "users", "roles", or "externals" are not specified, set them as empty lists [].
                    - If the user does not specify the usernames exactly as in the users list, then leave users empty.
                    - If the user specifies words like 'superadmins', 'superusers', 'admins', 'staff', or 'creator', then those should go into roles, whether for remove or for add.
                    - If the user specifies an external email that is not a user or a role, then it must go inside the externals list, whether the user wants to remove it or add it.
                    - "native_object" and "custom_object" cannot both exist at the same time.
                    - "offset_days" and "scheduled_cron" cannot both exist at the same time.
                    - If "scheduled_cron" is provided, it must follow a valid cron format.
                    - Ensure the JSON array contains valid objects with all fields normalized as described.

                    *IMPORTANT:* *Return a valid JSON array only of objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "update",
                "function": "extract_custom_object_updates",
                "system_instructions": """
                Extract structured update details from the following request.
                Return a JSON array of objects, where each object must include:

                - "label" (string): The label of the Custom Object
                - "name" (string): The name of the Custom Object
                - "updates" (list): A list of fields to update
                    - "label" (string): If user wants to update the label
                    - "name" (string): If user wants to update the name
                    - "description" (string): If user wants to update the description

                *Example Input & Output:*

                User: "Update rule IR-08763 type to inclusion and priority to 7."
                User: "update payment custom object"
                Response:
                [
                    {
                        "label": null
                        "name": "payment",
                        "updates": {
                            "label": null,
                            "name": null,
                            "description": null
                        }

                    }
                ]

                User: "Update rule target to quote"
                Response:
                [
                    {
                        "name": null,
                        "field": "target_type",
                        "value": "quote"
                    }
                ]

                User: "Update rule ER-00065 error message to 'You can't add the product UHTY-876 and ACPQ-001 at the same time' and set disabled"
                Response:
                [
                    {
                        "name": "ER-00065",
                        "field": "error_message",
                        "value": "You can't add the product UHTY-876 and ACPQ-001 at the same time."
                    },
                    {
                        "name": "ER-00065",
                        "field": "active",
                        "value": false
                    }
                ]

                User: "Update VR-00032 rule description to 'No discounts > 45%'"
                Response:
                [
                    {
                        "name": "VR-00032",
                        "field": "description",
                        "value": "No discounts > 45%"
                    }
                ]

                User: "Update the conditions of rule VR-00012. The new rule should prevent adding a discount greater than or equal to 15% to products with SKU QTGY-HY-009."
                Response:
                [
                    {
                        "name": "VR-00012",
                        "field": "conditions",
                        "value": {
                            "logic": "AND",
                            "items": [
                                {
                                    "fieldName": "quote_line.discount_percentage",
                                    "operator": ">=",
                                    "value": 15
                                },
                                {
                                    "fieldName": "quote_line.sku",
                                    "operator": "==",
                                    "value": "QTGY-HY-009"
                                }
                            ]
                        }
                    },
                    {
                        "name": "VR-00012",
                        "field": "error_message",
                        "value": "Discount cannot exceed 15% for product with SKU QTGY-HY-009"
                    },
                    {
                        "name": "VR-00012",
                        "field": "description",
                        "value": "Prevent discounts ≥ 15% for product QTGY-HY-009"
                    }
                ]

                If the user asks to update only the conditions of a rule but does not mention updating the error_message or description, then automatically infer and include appropriate values for those fields based on the intent or logic of the new rule. Add them as separate update objects using the same rule name.
                """,
                "system_rules": """
                    *Requirements:*
                    - If no name are found in the message, return null as name
                    - The "name" must always follow the format: one of VR, IR, or ER followed by a hyphen (-) and exactly 5 digits (e.g., "VR-00012").
                    - If no field are found in the message, return null as field
                    - If no value are found in the message, return null as value
                    - Only return a structured JSON object in "value" when the "field" is equal to "conditions".

                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "update",
                "function": "extract_rule_updates",
                "system_instructions": """
                    Extract structured update details from the following request.
                    Return a JSON array of objects, where each object must include:

                    - "name" (string, required): The name of the rule being updated.
                    - "field" (string, required): The field to be updated. Valid fields are: rule_type, target_type, priority, error_message, active, description, conditions.
                    - "value" (number, string, or object, required): The new value to assign to the specified field.

                    Value expectations by field:
                    - rule_type: "validation", "inclusion", or "exclusion"
                    - target_type: "quote_line", "quote", or "multiple"
                    - priority: any number
                    - error_message: any string
                    - active: true or false
                    - description: any string
                    - conditions: a structured JSON object representing the logical conditions used to evaluate the rule

                    *Example Input & Output:*

                    User: "Update rule IR-08763 type to inclusion and priority to 7."
                    Response:
                    [
                        {
                            "name": "IR-08763",
                            "field": "rule_type",
                            "value": "inclusion"
                        },
                        {
                            "name": "IR-08763",
                            "field": "priority",
                            "value": 7
                        }
                    ]

                    User: "Update rule target to quote"
                    Response:
                    [
                        {
                            "name": null,
                            "field": "target_type",
                            "value": "quote"
                        }
                    ]

                    User: "Update rule ER-00065 error message to 'You can't add the product UHTY-876 and ACPQ-001 at the same time' and set disabled"
                    Response:
                    [
                        {
                            "name": "ER-00065",
                            "field": "error_message",
                            "value": "You can't add the product UHTY-876 and ACPQ-001 at the same time."
                        },
                        {
                            "name": "ER-00065",
                            "field": "active",
                            "value": false
                        }
                    ]

                    User: "Update VR-00032 rule description to 'No discounts > 45%'"
                    Response:
                    [
                        {
                            "name": "VR-00032",
                            "field": "description",
                            "value": "No discounts > 45%"
                        }
                    ]

                    User: "Update the conditions of rule VR-00012. The new rule should prevent adding a discount greater than or equal to 15% to products with SKU QTGY-HY-009."
                    Response:
                    [
                        {
                            "name": "VR-00012",
                            "field": "conditions",
                            "value": {
                                "logic": "AND",
                                "items": [
                                    {
                                        "fieldName": "quote_line.discount_percentage",
                                        "operator": ">=",
                                        "value": 15
                                    },
                                    {
                                        "fieldName": "quote_line.sku",
                                        "operator": "==",
                                        "value": "QTGY-HY-009"
                                    }
                                ]
                            }
                        },
                        {
                            "name": "VR-00012",
                            "field": "error_message",
                            "value": "Discount cannot exceed 15% for product with SKU QTGY-HY-009"
                        },
                        {
                            "name": "VR-00012",
                            "field": "description",
                            "value": "Prevent discounts ≥ 15% for product QTGY-HY-009"
                        }
                    ]
                """,
                "system_rules": """""",
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "delete",
                "function": "extract_rule_deletes",
                "system_instructions": """
                    Extract structured name of rules from the following request.
                    Return a JSON array of objects, where each object must include:

                    - "name" (string, required): The name of the rule being deleted.

                    *Example Input & Output:*

                    User: "delete rules VR-00065, IR-06528 and ER-76549"
                    Response:
                    [
                        {
                            "name": "VR-00065"
                        },
                        {
                            "name": "IR-06528"
                        },
                        {
                            "name": "ER-76549"
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - If no name are found in the message, return null as name
                    - The "name" must always follow the format: one of VR, IR, or ER followed by a hyphen (-) and exactly 5 digits (e.g., "VR-00012").

                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "create",
                "function": "extract_rules_details_to_render",
                "system_instructions": """
                    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

                    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

                    - request_description (string): A short, human-readable description that summarizes what the user is asking. This must not be a copy of the user message. Instead, infer the intent and rephrase it as a concise summary.
                    - name (string): The name of the rule. If the user specifies a name, use it. The naming format starts with 'VR' for validation rules, 'IR' for inclusion rules, and 'ER' for exclusion rules, followed by 5 digits.
                    - rule_type (list): Type of rule. Must be one of:
                        - "validation"
                        - "inclusion"
                        - "exclusion"
                        If the user does not explicitly mention it, set rule_type as null.
                    - target_type (list): The level where the rule applies. Must be one of:
                        - "quote"
                        - "quote_line"
                        - "multiple"
                        If the user does not explicitly mention it, set target_type as null.
                    - priority (integer): The rule's priority. If the user does not explicitly mention it, set priority as null.
                    - active (boolean): If the user does not explicitly mention it, set active as null.

                    User:
                    "show rules"

                    Expected Output:
                    [
                    {
                        "request_description": null,
                        "name": null,
                        "rule_type": null,
                        "target_type": null,
                        "priority": null,
                        "active": null
                    }
                    ]

                    Example #2:

                    User:
                    "show me the validation and inclusion rules"

                    Expected Output:
                    [
                    {
                        "request_description": "Showing validation rules...",
                        "name": null,
                        "rule_type": ["validation"],
                        "target_type": null,
                        "priority": null,
                        "active": null
                    },
                    {
                        "request_description": "Showing inclusion rules...",
                        "name": null,
                        "rule_type": ["inclusion"],
                        "target_type": null,
                        "priority": null,
                        "active": null
                    }
                    ]

                    Example #3:

                    User:
                    "Display only the rules that apply to quotes and have priority 7"

                    Expected Output:
                    [
                    {
                        "request_description": "Showing rules with target type: quote and priority: 7...",
                        "name": null,
                        "rule_type": null,
                        "target_type": ["quote"],
                        "priority": 7,
                        "active": True
                    }
                    ]

                    Example #4:

                    User:
                    "show IR-00675 rule"

                    Expected Output:
                    [
                    {
                        "request_description": "Showing specific rule: IR-00675...",
                        "name": "IR-00675",
                        "rule_type": null,
                        "target_type": null,
                        "priority": null,
                        "active": null
                    }
                    ]

                    Example #5:

                    User:
                    "show rules VR-05463 and ER-00053"

                    Expected Output:
                    [
                    {
                        "request_description": "Showing specific rule: VR-05463...",
                        "name": "VR-05463",
                        "rule_type": null,
                        "target_type": null,
                        "priority": null,
                        "active": null
                    },
                    {
                        "request_description": "Showing specific rule: ER-00053...",
                        "name": "ER-00053",
                        "rule_type": null,
                        "target_type": null,
                        "priority": null,
                        "active": null
                    }
                    ]

                    Example #6:

                    User:
                    "show all rules"

                    If the user message is exactly "show all rules", respond only with the following JSON format (no additional text):

                    [
                        {
                            "request_description": "Showing all available rules...",
                            "name": null,
                            "rule_type": ["validation", "inclusion", "exclusion"],
                            "target_type": ["quote", "quote_line", "multiple"],
                            "priority": null,
                            "active": null
                        }
                    ]

                    For any other user input, respond normally.
                """,
                "system_rules": """
                    Requirements:
                    - Do not return explanations or extra text — only the JSON array of rules.
                    - If multiple rules are described in the message, return multiple objects in the array.
                    - If you cannot determine the correct value for any field (e.g., name, rule_type, target_type, priority, active), set its value to null.
                    - If the user refers to a specific rule by name (e.g., starting with VR, IR, or ER for validation, inclusion, or exclusion rules respectively), set rule_type, target_type, priority, and active to null, as they are not needed for identifying a specific rule.

                    *IMPORTANT:*
                    - Unless the user input is exactly "show all rules", do not include more than one value in the rule_type or target_type lists.
                    - If the user asks for multiple rule types or target types (e.g., "show validation and inclusion rules"), return one dictionary per rule type or target type, each with a single item in the corresponding list.
                    - Exception: If the user input is exactly "show all rules", then you may include multiple values in both rule_type and target_type lists inside a single dictionary.
                    *IMPORTANT:*
                    Rules for output:
                    - DO return only a raw JSON array of rule objects.
                    - DO NOT include triple backticks (```), json, or any Markdown formatting.
                    - DO NOT explain anything.
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "create",
                "function": "extract_validation_rules",
                "system_instructions": """
                    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

                    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

                    - description (string): The description of the rule. If the user specifies a description, use it. If not, generate a concise description that summarizes the rule purpose.
                    - rule_type (string): Type of rule. Must be one of:
                        - "validation"
                        If the user does not explicitly mention it, infer it based on the intent.
                    - target_type (string): The level where the rule applies. Must be one of:
                        - "quote"
                        - "quote_line"
                        - "multiple"
                        If the user specifies a target but the rule clearly involves fields from more than one level, set this to "multiple", even if the user suggested otherwise.
                    - priority (integer): The rule's priority. If specified, use it. If not, default to 10.
                    - error_message (string): The message to display when the rule is triggered. Use the user-provided message if available; otherwise, create a clear, professional message based on the intent of the rule.
                    - active (boolean): If user doesn't explicitly specify active (true or false), set active as true. If the user uses indirect language like "do not activate", "leave inactive", "but not active", "shouldn't be active", etc., set active as false. Use only lowercase true or false.
                    - conditions (object): The condition logic that triggers the rule. Must follow this strict JSON structure:

                    Response:
                    [
                    {
                        "conditions": {
                        "logic": "AND" | "OR",
                        "items": [
                            {
                            "fieldName": "quote.subtotal",
                            "operator": "==",
                            "value": 1000
                            },
                            {
                            "logic": "AND",
                            "items": [ ... ]
                            }
                        ]
                        }
                    }
                    ]

                    If only one condition is present, use "logic": "AND" by default.

                    Allowed field names per level:

                    Quote: net_amount, tax_amount, status, discount_percentage, discount_amount, discount_type, subtotal

                    Quote Line: quantity, unit_price, special_price, total_price, discount_percentage, discount_type, discount_amount, billing_frequency, billing_end_date, billing_start_date, is_subscription, product_name, sku, term, subtotal

                    Example #1:

                    User:
                    "Create a rule to prevent quote line items from having discounts greater than $100."

                    Expected Output:
                    [
                    {
                        "description": "Max Quote Line Discount Greater Than $100",
                        "rule_type": "validation",
                        "target_type": "quote_line",
                        "priority": 10,
                        "error_message": "Discount amount cannot exceed $100 for any quote line item.",
                        "active": true,
                        "conditions": {
                            "logic": "AND",
                            "items": [
                                {
                                    "fieldName": "quote_line.discount_amount",
                                    "operator": ">",
                                    "value": 100
                                }
                            ]
                        }
                    }
                    ]

                    Example #2:

                    User:
                    "create a validation rule to prevent discount > 60% for ACPQ-002 line item."

                    Expected Output:
                    [
                    {
                        "description": "Prevent discount greater than 60% for OK-TG-SHY-034 product.",
                        "rule_type": "validation",
                        "target_type": "quote_line",
                        "priority": 10,
                        "error_message": "Discount percentage cannot exceed 60% for line item OK-TG-SHY-034.",
                        "active": true,
                        "conditions": {
                            "logic": "AND",
                            "items": [
                                {
                                    "fieldName": "quote_line.discount_percentage",
                                    "operator": ">",
                                    "value": 60
                                },
                                {
                                    "fieldName": "quote_line.sku",
                                    "operator": "==",
                                    "value": "OK-TG-SHY-034"
                                }
                            ]
                        }
                    }
                    ]
                """,
                "system_rules": """
                Requirements:
                - Always include fieldName in full format: quote. or quote_line.
                - Always enclose string values in double quotes, and leave numeric values as raw numbers.
                - Do not return explanations or extra text — only the JSON array of rules.
                - If multiple rules are described in the message, return multiple objects in the array.
                + If ambiguous fields are used (e.g., discount_percentage without level), check for context clues:
                +   - If the user mentions "line item" or "quote line", infer quote_line.
                +   - If the user mentions "quote", infer quote.
                - If you cannot determine the correct value for any field (e.g., description, rule_type, target_type, priority, error_message, or conditions), set its value to null.
                - If no conditions are provided, set conditions to null (e.g. "conditions": null)

                *IMPORTANT:*
                Rules for output:
                - DO return only a raw JSON array of rule objects.
                - DO NOT include triple backticks (```), json, or any Markdown formatting.
                - DO NOT explain anything.
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "bundles_agent",
                "method": "update",
                "function": "extract_option_updates",
                "system_instructions": """
                    Extract structured option updates from the following request.
                    Return ONLY a JSON array. Each item must be an object with:

                    - "parent_product_sku" (string or null): bundle SKU
                    - "parent_product_name" (string or null): bundle name
                    - "updates": array of updates. Each update MUST include:
                        - "product_option_sku" (string or null)
                        - "product_option_name" (string or null)
                        - "quantity" (int or null)
                        - "is_required" (boolean or null)
                        - "min_quantity" (int or null)
                        - "max_quantity" (int or null)
                        - "default_selected" (boolean or null)
                        - "group_name" (string or null)
                    
                    Rules:
                    - Use null for any missing value.
                    - Do NOT invent keys or structure; no top-level keys other than the array.
                    - No text, explanations, or markdown—raw JSON only.

                    *Example Input & Output:*
                    User: "update option for component Product1 in bundle KIT-001 set quantity to 2, required and max quantity to 15."
                    Response:
                    [
                        {
                            "parent_product_sku": "KIT-001",
                            "parent_product_name": null,
                            "updates": {
                                {
                                    "product_option_sku": null,
                                    "product_option_name": "Product1",
                                    "quantity": 2,
                                    "is_required": true,
                                    "min_quantity": 15,
                                    "max_quantity": null,
                                    "default_selected": null,
                                    "group_name": null
                                }
                            }
                        }
                    ]

                    *Example Input & Output 2:*
                    User: "udpate option for product YHGT-UJI-654 in bundle Example Kit Bundle set quantity to 15, not required, min quantity to 5, max quantity to 20, selected and Expensive Products as group name."
                    Response:
                    [
                        {
                            "parent_product_sku": null,
                            "parent_product_name": "Example Kit Bundle",
                            "updates": {
                                {
                                    "product_option_sku": "YHGT-UJI-654",
                                    "product_option_name": null,
                                    "quantity": 15,
                                    "is_required": false,
                                    "min_quantity": 5,
                                    "max_quantity": 20,
                                    "default_selected": true,
                                    "group_name": "Expensive Products"
                                }
                            }
                        }
                    ]


                    *Example Input & Output 2:*
                    User: "udpate option for product SKU-987 in bundle JHU-098 and Easy Tool in bundle Construction Tool Kit set required and selected."
                    Response:
                    [
                        {
                            "parent_product_sku": "JHU-098",
                            "parent_product_name": null,
                            "updates": {
                                {
                                    "product_option_sku": "SKU-987",
                                    "product_option_name": null,
                                    "quantity": null,
                                    "is_required": true,
                                    "min_quantity": null,
                                    "max_quantity": null,
                                    "default_selected": true,
                                    "group_name": null
                                }
                            }
                        },
                        {
                            "parent_product_sku": null,
                            "parent_product_name": "Construction Tool Kit",
                            "updates": {
                                {
                                    "product_option_sku": null",
                                    "product_option_name": "Easy Tool",
                                    "quantity": null,
                                    "is_required": true,
                                    "min_quantity": null,
                                    "max_quantity": null,
                                    "default_selected": true,
                                    "group_name": null
                                }
                            }
                        }
                    ]
                """,
                "system_rules": """
                    *Requirements:*
                    - If no parent_product_sku are found in the message, return null as parent_product_sku
                    - If no parent_product_name are found in the message, return null as parent_product_name
                    - If no updates are found in the message, return null as updates
                        - If no product_option_sku are found in the message, return null as product_option_sku
                        - If no product_option_name are found in the message, return null as product_option_name
                        - If no quantity are found in the message, return null as quantity
                        - If no is_required are found in the message, return null as is_required
                        - If no min_quantity are found in the message, return null as min_quantity
                        - If no max_quantity are found in the message, return null as max_quantity
                        - If no default_selected are found in the message, return null as default_selected
                        - If no group_name are found in the message, return null as group_name

                    *IMPORTANT:* *Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).*
                """,
                "temperature": 0,
                "agent_message": "",
                "agent_summary": "",
            },
            {
                "agent_name": "admin_agent",
                "method": "create",
                "function": "extract_inclusion_rules",
                "system_instructions": """
                    You are a helpful AI assistant that create inclusion rules from user message.
                    Always return JSON with structure:
                    {
                    "create_inclusion_rule": [
                        {
                            "data": {
                                "description": null,
                                "rule_type": "inclusion",
                                "target_type": null,
                                "priority": 10,
                                "message": null,
                                "active": true,
                                "conditions": {
                                    "trigger_product": {
                                        "sku": null,
                                        "name": null
                                    },
                                    "included_products": [],
                                    "options": [],
                                    "applies_to": null
                                }
                                
                            },
                            "completed": false
                        }
                    ],
                    "agent_message": "string",
                    "summary": null
                    }

                    The included products must have this structure inside the "included_products" key:
                    {
                        "sku": <PRODUCT_SKU>, 
                        "name": <PRODUCT_NAME>, 
                        "quantity": 1
                    }
                """,
                "system_rules": """
                    Rules:

                    1. If the user does not specify a description, then create a short description for the rule.
                    The rule_type must ALWAYS be "inclusion".
                    2. The target_type must ALWAYS be "quote_line".

                    3. If the user does not specify a priority value, set it to 10.

                    4. If the user does not specify a message, then create a short message to indicate to the user what is happening with the inclusion rule.

                    5. If the user does not specify "active", then set it to true.

                    Rules for conditions:

                    1. There must be at least one trigger_product. If the user does not specify a trigger_product, then mark "completed" as false.
                    2. There must be at least one product in the included_products list. If the user does not specify any included product, then mark "completed" as false.
                    3. The "trigger_product" must have either sku or name. If the user specifies a SKU, set name as null; if the user specifies a name, then set sku as null.
                    4. If the user does not specify the quantity of any product to include, set "quantity" to 1.
                """,
                "temperature": 0.0,
                "agent_message": """
                    Agent message:
                    - Interpret this as an attempt, therefore do not say things like "created successfully".
                    - If a trigger_product is not mentioned, respond naturally by asking the user which product should be the trigger. Use language that a regular user can understand, without emphasizing technical or internal terms. You may mention "trigger product" if it helps with clarity, but keep the message intuitive.
                    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, data requests, etc.
                    - Be brief, professional, and natural.
                    - Do not be technical.
                    - Continue naturally (DO NOT start with "Hello").
                    - Use <br> for line breaks.
                    - Include information if the user attempted to create an inclusion rule.
                """,
                "agent_summary": """
                    Summary:
                    - Create a short summary combining previous summary + this iteration.
                """,
            },
            {
                "agent_name": "action_trigger_agent",
                "method": "create",
                "function": "extract_action_triggers_with_llm",
                "system_instructions": """
                You are a helpful AI assistant that create action triggers from user message.
                    Always return JSON with structure:
                    {context_data = {
                                "create_action_trigger": [
                                    {
                                        "data": {
                                            "trigger": None,
                                            "action": None,
                                            "object_name": None,
                                            "action_params": {},
                                            "active": true,

                                        },
                                        "completed": False
                                    }
                                ],
                                "agent_message": "string",
                                "summary": "string"
                            }
                """,
                "system_rules": """
                    **Rules:**  
                    1. The trigger must be one of the following: `opportunity_closed_won`  
                    2. Action must be: `create`, `update`, or `delete`  
                    3. Object Name must be one of the following: `renewal_task`  
                    4. If the user does not specify the **Active** field, set it to `true` by default
                    5. Mark completed as true when user provided trigger, action, object_name and action_params

                    **Rules for action_params:**  
                    1. If the `object_name` is `renewal_task`, then `action_params` must have the following JSON format:  
                    ```json
                    {
                    "months_before": <VALUE>
                    }
                    The value of the months_before key must be:

                    "immediately", if the user specifies that they want the action trigger to be activated immediately.

                    6, if the user specifies "after 6 months".

                    3, if the user specifies "3 months before expiration date".
                """,
                "temperature": 0.8,
                "agent_message": """
                    **Agent message:**  
                    - Interpret this as an attempt, therefore do not say things like "created successfully".  
                    - If any of the following fields are not mentioned by the user, set **completed** to false and respond naturally to the user indicating what information is missing, without being technical: `trigger`, `action`, `object_name`, `action_params`.  
                    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, data requests, etc.  
                    - Be brief, professional, and natural.  
                    - Do not be technical.  
                    - Continue naturally (DO NOT start with "Hello").  
                    - Use `<br>` for line breaks.  
                    - Include information if the user attempted to create an inclusion rule.
                """,
                "agent_summary": """
                    Summary:
                    - Create a short summary combining previous summary + this iteration.
                """,
            },
            #{
            #    "agent_name": "",
            #    "method": "",
            #    "function": "",
            #    "system_instructions": """""",
            #    "system_rules": """""",
            #    "temperature": 0,
            #    "agent_message": "",
            #    "agent_summary": "",
            #},
        ]

        for prompt_data in default_prompts:
            obj, created = AgentPrompt.objects.get_or_create(
                agent_name=prompt_data["agent_name"],
                method=prompt_data["method"],
                function=prompt_data["function"],
                defaults={
                    "system_instructions": prompt_data["system_instructions"],
                    "system_rules": prompt_data["system_rules"],
                    "agent_message": prompt_data["agent_message"],
                    "agent_summary": prompt_data.get("agent_summary", ""),
                    "temperature": prompt_data.get("temperature", 0.8)
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✅ Created AgentPrompt: {prompt_data["function"]}"))
            else:
                self.stdout.write(self.style.WARNING(f"⚠️ AgentPrompt already exists: {prompt_data["function"]}"))
