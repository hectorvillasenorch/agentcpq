import json
import os
import openai
import logging
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
#OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# FUNCTION TO EXTRACT CUSTOM OBJECTS DETAILS (CREATE_CUSTOM_OBJECT)
def extract_custom_objects(user_message):
    """Uses GPT to extract custom object name, label, and new values to create custom objects."""

    prompt = f"""
    Extract structured custom objects details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Return a JSON array of objects, where each object must include:

    - "label" (string): The label of the Custom Object
    - "description" (string): If user wants to update the description

    **Example Input & Output:**

    User: "create a custom object named payment"
    Response:
    [
        {{
            "label": "Payment"
            "description": "Stores the invoice number or billing reference associated with this record for accounting and tracking purposes."
        }}
    ]

    User: "Please create a custom field named invoice. The description should be: 'Stores the invoice number or reference related to this record for billing and tracking purposes."
    Response:
    [
        {{
            "label": "Invoice"
            "description": "Stores the invoice number or reference related to this record for billing and tracking purposes."
        }}
    ]

    User: "Hey, I’d like to add a few custom fields to my object. One should be called Invoice, which will store the invoice number or reference for billing purposes. Another one named Customer Type to track whether the customer is new, returning, or a partner. And also a field called Delivery Date to specify when the product or service is expected to be delivered."
    Response:
    [
        {{
            "label": "Invoice"
            "description": "Stores the invoice number or billing reference associated with this record for accounting and tracking purposes."
        }},
        {{
            "label": "Customer Type"
            "description": "Indicates the classification of the customer, such as New, Returning, or Partner, to help segment and tailor sales strategies."
        }},
        {{
            "label": "Delivery Date"
            "description": "Specifies the expected date of delivery for the product or service, useful for planning and customer communication."
        }}
    ]

    **Requirements:**
    - If no "label" is found in the message, return null as "label".
    - The "label" must always start with a capital letter.
    - If no "description" is found in the message, return a short inferred description based on the context of the custom field.
    - If the message explicitly states that no description should be included, set "description" to null.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("label" in p and "description" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
    
# FUNCTION TO EXTRACT CUSTOM OBJECTS UPDATES (UPDATE_CUSTOM_OBJECT)
def extract_custom_objects_updates(user_message, custom_objects):
    """Uses GPT to extract custom object name, label, and new values to update custom objects."""

    prompt = f"""
    Extract structured custom objects details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Return a JSON array of objects, where each object must include:

    - "label" (string): The label of the Custom Object that user wants to update. Here are the current custom objects: {custom_objects}
    - "udpates":
        - "label" (string): The new label value for the Custom Object
        - "description" (string): The new description value for the Custom Object

    **Example Input & Output:**

    User: "change the label of the object Invoice to Client Invoice"
    Response:
    [
        {{
            "label": "Payment",
            "updates: {{
                "label: "Client Invoice",
                "description": null
            }}
        }}
    ]

    User: "Update the Subscription object: change the label to Membership and set the description to Handles recurring user payments."
    Response:
    [
        {{
            "label": "Subscription",
            "updates: {{
                "label: "Membership",
                "description": "Handles recurring user payments."
            }}
        }}
    ]

    **Requirements:**
    - The first "label" key represents the label of the custom object that will be edited.
    - The second "label" key represents the value to be updated for the custom object.
    - If no "label" is found in the message, return null as "label".
    - The "label" must always start with a capital letter.
    - If no "description" is found in the message, return null as "description"

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("label" in p and "updates" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting custom objects details: {str(e)}")
        return None
    

def extract_custom_objects_deletes(user_message, custom_objects):
    """Uses GPT to extract custom object to delete."""

    prompt = f"""
    Extract structured custom objects details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Return a JSON array of objects, where each object must include:

    - "label" (string): The label of the Custom Object that user wants to delete. Here are the current custom objects: {custom_objects}

    **Example Input & Output:**

    User: "I want to delete invoice object"
    Response:
    [
        {{
            "label": "Invoice"
        }}
    ]

    User: "Please delete the custom objects Invoice, Shipment and ReturnOrder from the system."
    Response:
    [
        {{
            "label": "Invoice"
        }},
        {{
            "label": "Shipment"
        }},
        {{
            "label": "ReturnOrden"
        }}
    ]

    **Requirements:**
    - If no "label" is found in the message, return null as "label".
    - The "label" must always start with a capital letter.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("label" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting custom objects details: {str(e)}")
        return None
    
    
# FUNCTION TO EXTRACT CUSTOM FIELDS DETAILS (CREATE_CUSTOM_FIELDS)
def extract_custom_fields(user_message, custom_objects):
    """Uses GPT to extract custom field name, label, and new values to create custom fields."""

    prompt = f"""
    Extract structured custom fields details from the following request.


    Return a JSON array of fields, where each object must include:

    - "label" (string): The label of the Custom Field
    - "crm" (string): The CRM associated with the custom field.
    - "object_type": The default object in AgentCPQ that the field belongs to. Must be one of: Activity, Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.
    - "data_type" (string): The data type of the custom field. Must be one of: text, number, date, boolean, dropdown, text_area, or lookup.
    - "required" (boolean): Indicates whether the field is required in the custom object.
    - "custom_object" (String): The label or name of the custom object this field belongs to. Must be one of: {custom_objects}
    - "options" (Array of strings): For dropdown data type if requires options.

    **Example Input & Output:**

    User: "create a custom field named Name for Invoice"
    Response:
    [
        {{
            "label": "Name",
            "crm": null,
            "object_type": null,
            "data_type": "text",
            "required": null,
            "custom_object": "invoice__c",
            "options": null
        }}
    ]

    User: "Add a required text field called 'Serial Number' and a dropdown field called 'Status' with the options: Active, Inactive, Pending — to the Quote Line object."
    Response:
    [
        {{
            "label": "Serial Number",
            "crm": null,
            "object_type": "QuoteLine",
            "data_type": "text",
            "required": true,
            "custom_object": null,
            "options": null
        }},
        {{
            "label": "Status",
            "crm": null,
            "object_type": "QuoteLine",
            "data_type": "dropdown",
            "required": null,
            "custom_object": null,
            "options": ["Active", "Inactive", "Pending"]
        }}
    ]

    User: "Add a dropdown field called Priority to the Maintenance Log object"
    Response:
    [
        {{
            "label": "Priority",
            "crm": null,
            "object_type": null,
            "data_type": "dropdown",
            "required": null,
            "custom_object": "maintenance_log__c",
            "options": null
        }}
    ]

    **Requirements:**
    - If no "label" is found in the message, return null as "label".
    - If no "crm" is found in the message, return "AgentCPQ" as "crm".
    - If no "object_type" is found in the message, return null as "object_type".
    - If no "data_type" is found in the message, return null as "data_type".
    - If no "required" is found in the message, return null as "required".
    - If no "custom_object" is found in the message, return null as "custom_object".
    - "object_type" should only be set when the user specifies a default object in AgentCPQ (Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine). In this case, "custom_object" must be null.
    - "custom_object" should only be set when the user specifies a custom object from the provided list. In this case, "object_type" must be null.
    - "object_type" and "custom_object" must never both contain values. Always set one to null when the other is present.
    - If the "data_type" is "dropdown", include the dropdown choices in a key called "options" as an array of strings. If "data_type" is not "Dropdown", set "options" to null.
    - If the "data_type" is "dropdown" but no "options" are found in the message, return null as "options".

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all(
                all(k in p for k in ["label", "crm", "object_type", "data_type", "required", "custom_object"])
                for p in extracted_updates
            ):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
    

# FUNCTION TO EXTRACT CUSTOM FIELDS UPDATES (UPDATE_CUSTOM_FIELDS)
def extract_custom_fields_updates(user_message, custom_objects, custom_fields):
    """Uses GPT to extract custom field name, label, and new values to update custom fields."""

    prompt = f"""
    Extract structured custom fields details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**


    Return a JSON array of fields, where each object must include:

    - "target_field_label" (string): The label of the custom field that will be updated. Here are the current custom fields: {custom_fields}
    - "target_custom_object" (string): The custom object that the custom field to be updated belongs to. One of {custom_objects}
    - "target_default_object" (string): The default object that the custom field to be updated belongs to.
    - "updates":
        - "label" (string): This will be the new label for the Custom Field.
        - "crm" (string): This will be the new CRM for the Custom Field.
        - "object_type": This will be the new default object in AgentCPQ that the field belongs to. Must be one of: Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.
        - "data_type" (string): This will be the data type for the Custom Field. Must be one of: text, number, date, boolean, dropdown, text_area, or lookup.
        - "required" (boolean): This will indicate whether the field is required in the custom object.
        - "custom_object" (String): This will be the label or name of the custom object this field belongs to. It must be one of: {custom_objects}
        - "options" (Array of strings): For dropdown data type if requires options.

    **Example Input & Output:**

    User: "Please update the "Product Category" field from the "Inventory" custom object. I'd like to change the label to "Category", set the CRM to "HubSpot", make it not required, and set the data type to "dropdown" with the following options: Electronics, Clothing, Home, and Toys."
    Response:
    [
        {{
            "target_field_label": "Product Category",
            "target_custom_object": "Inventory",
            "target_default_object": null,
            "updates": {{
                "label": "Category",
                "crm": "HubSpot",
                "object_type": null,
                "required": false,
                "custom_object": null,
                "data_type": "dropdown",
                "options": ["Electronics", "Clothing", "Home", "Toys"]
            }}
        }}
    ]

    User: "I’d like to update the following fields: the first one is the "UOM" field from the "Product" object — I’d like to change its label to "Unit Of Measure", change the object to the custom object Inventory and set the data type to text; the second one is the "Event Type" field from the "Event" object — I’d like to change its data type to dropdown with the following options: Wedding, Birthday, and Graduation."
    Response:
    [
        {{
            "target_field_label": "UOM",
            "target_custom_object": null,
            "target_default_object": "Product",
            "updates": {{
                "label": "Unit Of Measure",
                "crm": null,
                "object_type": null,
                "required": null,
                "custom_object": "Inventory",
                "data_type": "text",
                "options": ["Electronics", "Clothing", "Home", "Toys"]
            }}
        }},
        {{
            "target_field_label": "Event Type",
            ""target_custom_object": "Event",
            "target_default_object": null,
            "updates": {{
                "label": "Unit Of Measure",
                "crm": null,
                "object_type": null,
                "required": null,
                "custom_object": null,
                "data_type": "dropdown",
                "options": ["Wedding", "Birthday", "Graduation"]
            }}
        }}
    ]

    User: "Change the field named UOM from the vehicle object to the default product object."
    Response:
    [
        {{
            "target_field_label": "UOM",
            "target_custom_object": "Vehicle",
            "target_default_object": null,
            "updates": {{
                "label": null,
                "crm": null,
                "object_type": "Product",
                "required": null,
                "custom_object": null,
                "data_type": null,
                "options": null
            }}
        }}
    ]

    **Requirements:**
    - If "target_field_label" is not found in the message, set it as null.
    - If "target_custom_object" is not found in the message, set it as null.
    - If "target_default_object" is not found in the message, set it as null.
    - Exactly one of "target_custom_object" or "target_default_object" must be set to indicate the current location of the field. The other must be null.
    - The value of "target_custom_object" must be one of the following custom objects: {custom_objects}.
    - The value of "target_default_object" must be one of the following default objects: Activity, Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.
    - The destination where the field should be moved or updated must be indicated inside "updates" as either:
        - "object_type" (for default system objects: Activity, Lead, Contact, Account, Opportunity, Product, Quote, QuoteLine), or
        - "custom_object" (for custom objects: {custom_objects}).
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



    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all(
                all(k in p for k in ["target_field_label", "target_custom_object", "target_default_object", "updates"])
                for p in extracted_updates
            ):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None

# FUNCTION TO EXTRACT CUSTOM FIELDS DELETES (DELETE_CUSTOM_FIELD) 
def extract_custom_fields_deletes(user_message, custom_objects, custom_fields):
    """Uses GPT to extract custom fields to delete."""

    prompt = f"""
    Extract structured custom objects details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Return a JSON array of objects, where each object must include:

    - "field_label" (string): The label of the Custom Field that user wants to delete. Here are the current custom fields: {custom_fields}
    - "custom_object_label" (string): The label of the custom object that the custom field to be deleted belongs to. Here are the current custom objects: {custom_objects}
    - "default_object_label" (string): The label of the default object that the custom field to be deleted belongs to.

    **Example Input & Output:**

    User: "Please delete the custom field "Delivery Date" from the "Order" object."
    Response:
    [
        {{
            "field_label": "Delivery Date",
            "custom_object_label": "Order",
            "default_object_label": null
        }}
    ]

    User: "Please delete the fields "Industry" and "Annual Revenue" from the "Account" default object"
    Response:
    [
        {{
            "field_label": "Industry",
            "custom_object_label": null,
            "default_object_label": "Account"
        }},
        {{
            "field_label": "Annual Revenu",
            "custom_object_label": null,
            "default_object_label": "Account"
        }}
    ]

    **Requirements:**
    - If no "field_label" is found in the message, return null as "field_label".
    - If no "custom_object_label" is found in the message, return null as "custom_object_label".
    - If no "default_object_label" is found in the message, return null as "default_object_label".
    - The default_object_label must be one of the following default objects: Activity, Lead, Contact, Account, Opportunity, Product, Quote, or QuoteLine.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("field_label" in p and "custom_object_label" in p and "default_object_label" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting custom objects details: {str(e)}")
        return None


# FUNCTIOn TO EXTRACT CUSTOM OBJECT RECORDS DETAILS (CREATE_CUSTOM_OBJECT_RECORD)
def extract_custom_object_data(user_message, custom_objects_data, custom_objects_names):
    """Uses GPT to extract custom object records details"""

    prompt = f"""
    Extarct structured custom objects records details from the following request.

    You are an AI assistant that extracts structured data to create a custom object record from the message.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    The list of available custom objects and their fields is the following:
    {json.dumps(custom_objects_data, indent=2)}

    List of object names you can use:
    {custom_objects_names}

    ---

    Given a user instruction, extract:
    - The correct `custom_object_name` (must match exactly one of the names from the list)
    - The `values`: a list of {{"field", "value"}} pairs based only on the available fields of that object.

    Each `field` must match exactly one of the `label` values in the selected object’s fields.

    ---

    ✅ Format your response in this exact JSON structure:

    ```json
    [
    "custom_object_name": "object_name_here",
    "values": 
        {{
            "field": "field_label_here",
            "value": "value_from_user_message"
        }},
        {{
            "field": "field_label_here",
            "value": "value_from_user_message"
        }}
        // Add as many as you find in the user message
    ]

    **Example Input & Output:**

    User: "Please create a new invoice for customer John Doe with an amount of $1500 and set the status to Pending."
    Response:
    [
        {{
            "custom_object_name": "invoice__c",
            "values":
                {{
                    "field": "customer__c",
                    "value": "John Doe"
                }},
                {{
                    "field": "amount",
                    "value": 1,500
                }}
        }}
    ]

    User: "I need to register a new work order assigned to technician Sarah Smith for the broken AC unit. Priority: High, Due date: August 10th and log a shipment going to Mexico City, shipped by DHL, with a tracking number of 123456789."
    Response:
    [
        {{
            "custom_object_name": "work_order__c",
            "values": [
                {{
                    "field": "assigned_to",
                    "value": "Sarah Smith"
                }},
                {{
                    "field": "description",
                    "value": "broken AC unit"
                }},
                {{
                    "field": "priority",
                    "value": "High"
                }},
                {{
                    "field": "due_date",
                    "value": "2025-08-10"
                }}
            ]
        }},
        {{
            "custom_object_name": "shipment__c",
            "values": [
                {{
                    "field": "destination",
                    "value": "Mexico City"
                }},
                {{
                    "field": "carrier",
                    "value": "DHL"
                }},
                {{
                    "field": "tracking_number",
                    "value": "123456789"
                }}
            ]
        }}
    ]

    **Requirements:**
    - If no "label" is found in the message, return null as "label".
    - The "custom_object_label" must always be returned in lowercase letters.
    - If no "description" is found in the message, return a short inferred description based on the context of the custom field.
    - If the message explicitly states that no description should be included, set "description" to null.
    - If any custom object label, field name, or value cannot be found or inferred from the message, set it as null.
    - Values must follow these type rules:
    - For fields of type text, date, dropdown, text area, and look up, the value must be a string.
    - For fields of type number, the value must be a decimal number without quotes.
    - For fields of type boolean, the value must be either true or false without quotes.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("custom_object_name" in p and "values" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
    
# FUNCTIOn TO EXTRACT CUSTOM OBJECT RECORDS UPDATES (UPDATE_CUSTOM_RECORD)
def extract_custom_records_updates(user_message, record_identifiers, custom_objects_data, custom_objects_names):
    """Uses GPT to extract custom object records details"""

    prompt = f"""
    Extract structured custom objects records details from the following request.

    You are an AI assistant that extracts structured data to update multiple custom object record from the message.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    The list of available custom objects and their fields is the following:
    {json.dumps(custom_objects_data, indent=2)}

    List of object names you can use:
    {custom_objects_names}

    List of the current record identifiers:
    {record_identifiers}

    ---

    Given a user instruction, extract:
    - The correct `record_identifier` (must match exactly one of the identifiers from the list)
    - The `values`: a list of {{"field", "value"}} pairs based only on the available fields of that object.

    Each `field` must match exactly one of the `label` values in the selected object’s fields.

    ---

    ✅ Format your response in this exact JSON structure:

    ```json
    [
    "record_identifier": "record_identifier_here"
    "values": [
        {{
            "field": "field_label_here",
            "value": "value_from_user_message"
        }},
        {{
            "field": "field_label_here",
            "value": "value_from_user_message"
        }}
        // Add as many as you find in the user message
        ]
    ]

    **Example Input & Output:**

    User: "Please update record INV-00045: change the amount to $1750 and set the status to Paid."
    Response:
    [
        {{
            "record_identifier": "INV-00045",
            "values": [
                {{
                    "field": "amount",
                    "value": 1750
                }},
                {{
                    "field": "status",
                    "value": "Paid"
                }}
            ]
        }}
    ]


    User: "For work orders WO-00012 and WO-00013, set the priority to High. Also, mark WO-00012 as In Progress and WO-00013 as Completed."
    Response:
    [
        {{
            "record_identifier": "WO-00012",
            "values": [
                {{
                    "field": "priority",
                    "value": "High"
                }},
                {{
                    "field": "status",
                    "value": "In Progress"
                }}
            ]
        }},
        {{
            "record_identifier": "WO-00013",
            "values": [
                {{
                    "field": "priority",
                    "value": "High"
                }},
                {{
                    "field": "status",
                    "value": "Completed"
                }}
            ]
        }}
    ]


    **Requirements:**
    - If no "record_identifier" is found in the message, return null as "record_identifier".
    - The "record_identifier" must always be returned in uppercase letters.
    - The fields to fill must be taken from the provided list of fields.
    - If no value is found for a field in the user message, set "value" as null.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("record_identifier" in p and "values" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting custom records details: {str(e)}")
        return None

# FUNCTION TO EXTRACT CUSTOM RECORDS DELETES (DELETE_CUSTOM_RECORD)
def extract_custom_records_deletes(user_message, record_identifiers):
    """Uses GPT to extract custom records to delete."""

    prompt = f"""
    Extract structured custom objects details from the following request.

    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Return a JSON array of objects, where each object must include:

    - "record_identifier" (string): The record identifier to delete. Here are the current records identifiers: {record_identifiers}

    **Example Input & Output:**

    User: "I want to delete the record VEH-00001"
    Response:
    [
        {{
            "record_identifier": "VEH-00001"
        }}
    ]

    User: "Hi, please delete the records with identifiers VEH-00012, VEH-00015, and VEH-00020"
    Response:
    [
        {{
            "record_identifier": "VEH-00012",
            "record_identifier": "VEH-00015",
            "record_identifier": "VEH-00020"
        }}
    ]

    **Requirements:**
    - If no "record_identifier" is found in the message, return null as "record_identifier".

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract custom objects details to create."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("record_identifier" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting custom records details: {str(e)}")
        return None