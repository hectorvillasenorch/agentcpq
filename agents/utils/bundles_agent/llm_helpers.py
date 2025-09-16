import json
import os
import openai
import logging
from dotenv import load_dotenv
from datetime import date

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# FUNCTION TO EXTRACT BUNDLE COMPONENTS (CREATE_BUNDLE_COMPONENTS)
def extract_bundle_components(user_message):
    """Uses GPT to extract Bundle and Bundle Components."""

    prompt = f"""
    Extract structured bundle components from the following request.
    Return a JSON array where each object represents a bundle and contains:
    - "bundle_sku" (string): the SKU of the bundle product.
    - "bundle_name" (string): the name of the bundle product.
    - "components" (array): a list of products included in the bundle. Each item in this list should be an object with:
        - "product_sku" (string)
        - "product_name" (string)
        - "quantity" (int)
        - "is_required" (bool)
        - "min_quantity" (int)
        - "max_quantity" (int)
        - "default_selected" (bool)
        - "group_name" (string)

    **Example Input & Output:**
    User: "Add the following products to bundle OFFICE-KIT: 1 unit of Laptop, required and group Core, x2 of MSE-002, optional and group Accessories. After that add five boxes of nails to bundle Construction."
    Response:
    [
        {{
            "bundle_sku": "OFFICE-KIT",
            "bundle_name": null,
            "components": {{
                {{
                    "product_sku": null,
                    "product_name": "Laptop",
                    "quantity": 1,
                    "is_required": true,
                    "min_quantity": null,
                    "max_quantity": null,
                    "default_selected": null,
                    "group_name": "Core"
                }},
                {{
                    "product_sku": "MSE-002",
                    "product_name": null,
                    "quantity": 2,
                    "is_required": false,
                    "min_quantity": null,
                    "max_quantity": null,
                    "default_selected": null,
                    "group_name": "Accesories"
                }}
            }}
        }},
        {{
            "bundle_sku": null,
            "bundle_name": "Construction",
            "components": {{
                {{
                    "product_sku": null,
                    "product_name": "Nails",
                    "quantity": 5,
                    "is_required": false,
                    "min_quantity": null,
                    "max_quantity": null,
                    "default_selected": null,
                    "group_name": null
                }}
            }}
        }}
    ]

    **Example Input & Output 2:**
    User: "Add these components to the bundle SOFT-PACK-01 (Productivity Software Suite): x1 Word Processor, required, min 1, max 5, preselected, group: Core, x5 of SRT-003, required: optional, min: 1, max: 8, default selected: false, group: Services"
    Response:
    [
        {{
            "bundle_sku": "SOFT-PACK-01",
            "bundle_name": "Productivity Software Suite",
            "components": {{
                {{
                    "product_sku": null,
                    "product_name": "Word Processor",
                    "quantity": 1,
                    "is_required": true,
                    "min_quantity": 1,
                    "max_quantity": 5,
                    "default_selected": true,
                    "group_name": "Core"
                }},
                {{
                    "product_sku": "SRT-003",
                    "product_name": null,
                    "quantity": 5,
                    "is_required": false,
                    "min_quantity": 1,
                    "max_quantity": 8,
                    "default_selected": false,
                    "group_name": "Services"
                }}
            }}
        }}
    ]

    **Requirements:**
    - If no bundle_sku are found in the message, return null as bundle_sku
    - If no bundle_name are found in the message, return null as bundle_name
    - If no product_sku are found in the message, return null as product_sku
    - If no product_name are found in the message, return null as product_name'
    - If no quantity are found in the message, return 1 as quantity
    - If no is_required are found in the message, return null as is_required
    - If no min_quantity are found in the message, return null as min_quantity
    - If no max_quantity are found in the message, return null as max_quantity
    - If no default_selected are found in the message, return null as default_selected
    - If no group_name are found in the message, return null as group_name

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for quote line."},
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
                isinstance(bundle, dict) and
                "bundle_sku" in bundle and
                "bundle_name" in bundle and
                "components" in bundle and
                isinstance(bundle["components"], list) and all(
                    isinstance(component, dict) and
                    all(key in component for key in [
                        "product_sku", "product_name", "quantity",
                        "is_required", "min_quantity", "max_quantity",
                        "default_selected", "group_name"
                    ])
                    for component in bundle["components"]
                )
                for bundle in extracted_updates
            ):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting bundle components details: {str(e)}")
        return None
    
# FUNCTION TO UPDATE OPTION (UPDATE_BUNBLE_OPTION)
def extract_option_updates(user_message):
    """Uses GPT to extract the option updates."""

    prompt = f"""
    Extract structured option updates from the following request.
    Return a JSON array where each object represents an option update and contains:

    - "parent_product_sku" (string): The SKU of the bundle
    - "parent_product_name" (string):  The name of the bundle
    - "updates" (array): a list of product to update
        - "product_option_sku" (string): The sku of the product_option to update
        - "product_option_name" (string): The name of the product_option to update
        - "quantity" (int)
        - "is_required" (boolean)
        - "min_quantity" (int)
        - "max_quantity" (int)
        - "default_selected" (boolean)
        - "group_name" (string)

    **Example Input & Output:**
    User: "update option for component Product1 in bundle KIT-001 set quantity to 2, required and max quantity to 15."
    Response:
    [
        {{
            "parent_product_sku": "KIT-001",
            "parent_product_name": null,
            "updates": {{
                {{
                    "product_option_sku": null,
                    "product_option_name": "Product1",
                    "quantity": 2,
                    "is_required": true,
                    "min_quantity": 15,
                    "max_quantity": null,
                    "default_selected": null,
                    "group_name": null
                }}
            }}
        }}
    ]

    **Example Input & Output 2:**
    User: "udpate option for product YHGT-UJI-654 in bundle Example Kit Bundle set quantity to 15, not required, min quantity to 5, max quantity to 20, selected and Expensive Products as group name."
    Response:
    [
        {{
            "parent_product_sku": null,
            "parent_product_name": "Example Kit Bundle",
            "updates": {{
                {{
                    "product_option_sku": "YHGT-UJI-654",
                    "product_option_name": null,
                    "quantity": 15,
                    "is_required": false,
                    "min_quantity": 5,
                    "max_quantity": 20,
                    "default_selected": true,
                    "group_name": "Expensive Products"
                }}
            }}
        }}
    ]
    
    
    **Example Input & Output 2:**
    User: "udpate option for product SKU-987 in bundle JHU-098 and Easy Tool in bundle Construction Tool Kit set required and selected."
    Response:
    [
        {{
            "parent_product_sku": "JHU-098",
            "parent_product_name": null,
            "updates": {{
                {{
                    "product_option_sku": "SKU-987",
                    "product_option_name": null,
                    "quantity": null,
                    "is_required": true,
                    "min_quantity": null,
                    "max_quantity": null,
                    "default_selected": true,
                    "group_name": null
                }}
            }}
        }},
        {{
            "parent_product_sku": null,
            "parent_product_name": "Construction Tool Kit",
            "updates": {{
                {{
                    "product_option_sku": null",
                    "product_option_name": "Easy Tool",
                    "quantity": null,
                    "is_required": true,
                    "min_quantity": null,
                    "max_quantity": null,
                    "default_selected": true,
                    "group_name": null
                }}
            }}
        }}
    ]

    **Requirements:**
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

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for quote line."},
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
                isinstance(bundle, dict) and
                "parent_product_sku" in bundle and
                "parent_product_name" in bundle and
                "updates" in bundle and
                isinstance(bundle["updates"], list) and all(
                    isinstance(component, dict) and
                    all(key in component for key in [
                        "product_option_sku", "product_option_name", "quantity", "is_required", "min_quantity", "max_quantity", "default_selected", "group_name"
                    ])
                    for component in bundle["updates"]
                )
                for bundle in extracted_updates
            ):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting option updates: {str(e)}")
        return None
    
# FUNCTION TO EXTRACT DELETING OPTIONS (DELETE_BUNDLE_OPTION_FROM_QUOTE)
def extract_delete_options_from_quote(user_message):
    """Uses GPT to extract the bundle options that will be deleted."""

    prompt = f"""
    Extract structured bundle options and their corresponding parent bundles from the following request.
    The user may request to delete one or more options from one or multiple bundles.

    Return a JSON array where each object represents a bundle parent and options to will be deleted:
    - "bundle_sku" (string): the SKU of the bundle product.
    - "bundle_name" (string): the name of the bundle product.
    - "options" (array): a list of products included in the bundle. Each item in this list should be an object with:
        - "product_sku" (string)
        - "product_name" (string)

    **Example Input & Output:**
    User: "delete Product1, Product2 and PD-874 from Bundle1."
    Response:
    [
        {{
            "bundle_sku": null,
            "bundle_name": "Bundle1",
            "options": {{
                {{
                    "product_sku": null,
                    "product_name": "Product1"
                }},
                {{
                    "product_sku": null,
                    "product_name": "Product2"
                }},
                {{
                    "product_sku": "PD-874",
                    "product_name": null
                }}
            }}
        }}
    ]

    **Example Input & Output 2:**
    User: "delete BT-JUL-NH-0864 from First Bundle and Product2 from BD-AHI-987."
    Response:
    [
        {{
            "bundle_sku": null,
            "bundle_name": "First Bundle",
            "options": {{
                {{
                    "product_sku": "BT-JUL-NH-0864",
                    "product_name": null
                }}
            }}
        }},
        {{
            "bundle_sku": "BD-AHI-987",
            "bundle_name": null,
            "options": {{
                {{
                    "product_sku": null,
                    "product_name": "Product2"
                }}
            }}
        }}
    ]

    **Requirements:**
    - If no bundle_sku are found in the message, return null as bundle_sku
    - If no bundle_name are found in the message, return null as bundle_name
    - If no product_sku are found in the message, return null as product_sku
    - If no product_name are found in the message, return null as product_name

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for quote line."},
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
                isinstance(bundle, dict) and
                "bundle_sku" in bundle and
                "bundle_name" in bundle and
                "options" in bundle and
                isinstance(bundle["options"], list) and all(
                    isinstance(component, dict) and
                    all(key in component for key in [
                        "product_sku", "product_name"
                    ])
                    for component in bundle["options"]
                )
                for bundle in extracted_updates
            ):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting bundle options details: {str(e)}")
        return None