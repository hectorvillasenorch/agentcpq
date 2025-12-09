import json
import os
import openai
import logging
from dotenv import load_dotenv
from datetime import date

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
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

    prompt_tuple = make_system_prompt("bundles_agent", "update", "extract_option_updates", None)
    if prompt_tuple:
        system_prompt, temperature = prompt_tuple
    else:
        # Fallback prompt if no AgentPrompt is configured
        system_prompt = """
        You extract bundle option updates from user requests.
        Return ONLY JSON: an array of bundles to update.
        Each bundle object must include:
        - parent_product_sku (string or null)
        - parent_product_name (string or null)
        - updates (array) where each update has:
            - product_option_sku (string or null)
            - product_option_name (string or null)
            - quantity (int or null)
            - is_required (bool or null)
            - min_quantity (int or null)
            - max_quantity (int or null)
            - default_selected (bool or null)
            - group_name (string or null)
        Use null when data is missing. No text outside JSON.
        """
        temperature = 0

    user_prompt = user_message

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

        normalized = _normalize_option_updates(extracted_updates)
        if normalized:
            return normalized

        logging.warning("⚠️ GPT response is not in expected format.")
        return None

    except Exception as e:
        logging.error(f"❌ Error extracting option updates: {str(e)}")
        return None


def _normalize_option_updates(raw):
    """
    Normalize various LLM shapes to the expected schema:
    [
      {
        "parent_product_sku": "...",
        "parent_product_name": "...",
        "updates": [
          {
            "product_option_sku": "...",
            "product_option_name": "...",
            "quantity": <int or null>,
            "is_required": <bool or null>,
            "min_quantity": <int or null>,
            "max_quantity": <int or null>,
            "default_selected": <bool or null>,
            "group_name": <string or null>
          }
        ]
      }
    ]
    """
    if not isinstance(raw, list):
        return None

    normalized_bundles = []

    for bundle in raw:
        if not isinstance(bundle, dict):
            return None

        parent_sku = bundle.get("parent_product_sku") or bundle.get("bundle_sku") or bundle.get("bundleSku") or bundle.get("bundle")
        parent_name = bundle.get("parent_product_name") or bundle.get("bundle_name") or bundle.get("bundleName")
        updates = bundle.get("updates") or bundle.get("options")

        bundle_level_qty = bundle.get("quantity")

        if not isinstance(updates, list):
            return None

        norm_updates = []
        for upd in updates:
            if not isinstance(upd, dict):
                return None
            qty = upd.get("quantity", bundle_level_qty)
            norm_updates.append({
                "product_option_sku": upd.get("product_option_sku") or upd.get("option_sku") or upd.get("component_sku"),
                "product_option_name": upd.get("product_option_name") or upd.get("option_name") or upd.get("component_name"),
                "quantity": qty if isinstance(qty, int) else (None if qty is None else qty),
                "is_required": upd.get("is_required"),
                "min_quantity": upd.get("min_quantity") if upd.get("min_quantity") is not None else upd.get("min"),
                "max_quantity": upd.get("max_quantity") if upd.get("max_quantity") is not None else upd.get("max"),
                "default_selected": upd.get("default_selected"),
                "group_name": upd.get("group_name"),
            })

        normalized_bundles.append({
            "parent_product_sku": parent_sku,
            "parent_product_name": parent_name,
            "updates": norm_updates,
        })

    if all(
        isinstance(b, dict)
        and "parent_product_sku" in b
        and "parent_product_name" in b
        and isinstance(b.get("updates"), list)
        for b in normalized_bundles
    ):
        return normalized_bundles

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
