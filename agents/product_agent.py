from cpq.models import Product
import openai
from dotenv import load_dotenv
import json, inspect
import os
import re
import logging,threading
from .utils.quote_agent.db_helpers import log_action_usage
from .utils.message_formatters import SUCCESS_ICON
from decimal import Decimal

from .utils.orchestrator.context_handle_helpers import estimate_cost

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
#OPENAI_MODEL = "gpt-3.5-turbo"
OPENAI_MODEL = "gpt-4o-mini"
logger = logging.getLogger(__name__)

# Import context handle function
from .utils.orchestrator.context_handle_helpers import save_or_update_conversation_context

from .utils.product_agent.llm_helpers import extract_product_data_with_llm, generate_final_product_message

from .utils.session_context_helpers.session_context_helpers import get_session_context


from .utils.product_agent.handle_helpers import handle_create_product

def product_agent(user, action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "CreateProductRecord": create_product,
        "UpdateProductRecord": update_product
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request. From Product Agent"}


def create_product(user, user_message, session_data):
    """
    Handles product creation requests for multiple products.
    Tracks products in session state, saves completed products,
    and generates dynamic messages using LLM including DB errors.
    """
    current_state, previous_summary = get_session_context("create_product", session_data)

    # --- Initial call to the LLM to extract products ---
    llm_result, tokens_used, cost_est = extract_product_data_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- Separate completed vs. incomplete products ---
    completed_products = []
    remaining_products = []

    for product in llm_result["create_product"]:
        if product.get("completed"):
            completed_products.append(product["data"])
        else:
            remaining_products.append(product)

    # Save only the incomplete ones in the session state
    session_data["state"]["create_product"] = remaining_products

    # Return if not any completed products
    if not completed_products:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    # --- Persist completed products and capture errors ---
    result = handle_create_product(user, completed_products)

    print(f"Result: {result}")

    # --- Generate final dynamic message using a separate function ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_product_message(
        completed_products=completed_products,
        db_results=result,
        remaining_products=remaining_products,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }



def extract_sku_from_message(user_message):
    """Extract SKU from user input using GPT."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""
        Extract the SKU from the following user message. If no SKU is found, return "MISSING_SKU".

        Example 1:
        User: "Update product ACPQ-003, change is_subscription to true."
        Output: ACPQ-003

        Example 2:
        User: "Can you modify the product with SKU AI-001 to have a price of 100?"
        Output: AI-001

        Example 3:
        User: "Change the product's name to 'Super AI Assistant'."
        Output: MISSING_SKU

        User message: {user_message}
        Output:
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )

        extracted_sku = response.choices[0].message.content.strip()
        print("🔹 DEBUG: Extracted SKU:", extracted_sku)  # ✅ Debugging step

        return extracted_sku

    except Exception as e:
        print(f"⚠️ Error extracting SKU: {str(e)}")
        return "MISSING_SKU"

def update_product(user, user_message, session_data):
    """Modify product details based on user input before confirmation."""
    try:
        print("🔹 DEBUG: USER MESSAGE:", user_message)  # Debugging step

        # ✅ Extract SKU from the user request
        sku = extract_sku_from_message(user_message)
        print("🔹 DEBUG: Extracted SKU:", sku)  # Debugging step

        # 🧠 Make the session context
        session_context = {
            "user": user,
            "intent": "UpdateProductRecord",
            "agent_name": "product_agent",
            "session_data": session_data,
            "user_message": user_message,
            "item_index": 1,
            "extracted": {
                "updated_product": sku
            }
        }

        if sku == "MISSING_SKU":
            return {"message": "⚠️ Error: No SKU found in update request. Please specify the product SKU.", "product_details": None}

        # ✅ Step 2: Check if product exists in the database
        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            return {"message": f"⚠️ Error: Product with SKU `{sku}` not found. Would you like to create it instead?", "product_details": None}

        # ✅ Extract existing product details
        product_details = {
            "sku": product.sku,
            "name": product.name,
            "price": float(product.price),
            "is_subscription": product.is_subscription,
            "term": product.term,
            "is_bundle": product.is_bundle,
            "description": product.description or "",
            "family": product.family,
        }

        print("🔹 DEBUG: Current Product Details in DB:", product_details)  # Debugging step

        # ✅ Modify product details using GPT
        updated_product = gpt_modify_product_details(user_message, product_details)

        if not updated_product:
            agent_response = "Error: No changes detected or invalida update request"
            save_or_update_conversation_context(session_context, agent_response)
            return {"message": "⚠️ No changes detected or invalid update request."}

        # ✅ Store JSON preview for reference
        json_preview = json.dumps(updated_product, indent=2)

        # ✅ Execute the update
        product_update_executed = update_product_record(user, updated_product)

        return {
            "message": product_update_executed,
            #"product_details": updated_product
        }

    except Exception as e:
        return {"message": f"⚠️ Error updating product details: {str(e)}", "product_details": None}



def update_product_record(user,updated_product_details):
    """Update the product in the database and return a success message."""
    try:
        sku = updated_product_details["sku"]
        print(f"🔹 DEBUG: Updating product with SKU: {sku}")  # ✅ Debugging step

        # ✅ Find the product in the database
        product = Product.objects.get(sku=sku)

        # ✅ Update fields if they exist in the updated details
        product.name = updated_product_details.get("name", product.name)
        product.price = updated_product_details.get("price", product.price)
        product.is_subscription = updated_product_details.get("is_subscription", product.is_subscription)
        product.term = updated_product_details.get("term", product.term)
        product.is_bundle = updated_product_details.get("is_bundle", product.is_bundle)
        if "description" in updated_product_details:
            product.description = updated_product_details.get("description") or ""
        if "family" in updated_product_details:
            product.family = updated_product_details.get("family") or product.family
        product.updated_by = user

        # ✅ Save the updated product
        product.save()
        log_action_usage("UpdateProductRecord", user, "Product", product.name)
        print(f"✅ DEBUG: Product {sku} successfully updated.")  # ✅ Debugging step

        return f"{SUCCESS_ICON} Product {sku} successfully updated."

    except Product.DoesNotExist:
        return f"⚠️ Error: Product with SKU `{sku}` not found."
    except Exception as e:
        return f"⚠️ Error updating product `{sku}`: {str(e)}"


def gpt_modify_product_details(user_message, product_details):
    """Use GPT to modify product details based on user request."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""
        Modify the following product details based on the user's request.
        If a field is not mentioned, keep its current value.

        Current product details:
        {json.dumps(product_details, indent=2)}

        User request: "{user_message}"

        Return the modified product details in JSON format, with the same structure as the input.
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )

        modified_product_details = json.loads(response.choices[0].message.content)
        print("🔹 DEBUG: Modified Product Details:", modified_product_details)  # ✅ Debugging step

        return modified_product_details

    except Exception as e:
        print(f"⚠️ Error modifying product details: {str(e)}")
        return None

def clean_llm_response(raw_response: str) -> str:
    # Clean triple backticks and text json if are present
    pattern = r"```(?:json)?\s*(.*?)\s*```"
    match = re.search(pattern, raw_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return raw_response.strip()
