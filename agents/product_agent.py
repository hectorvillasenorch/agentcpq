from cpq.models import Product 
import openai
from dotenv import load_dotenv
import json, inspect
import os
import re
import logging,threading
from .utils.quote_agent.db_helpers import log_action_usage
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
        # "UpdateBundle": generate_quote_pdf,
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

    # --- 1️⃣ Llamada inicial al LLM para extraer productos ---
    llm_result, tokens_used, cost_est = extract_product_data_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_products = []
    remaining_products = []

    for product in llm_result["create_product"]:
        if product.get("completed"):
            completed_products.append(product["data"])
        else:
            remaining_products.append(product)

    # Guardar solo los incompletos en session state
    session_data["state"]["create_product"] = remaining_products

    # Return if not any completed products
    if not completed_products:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    # --- 4️⃣ Persistir productos completados y capturar errores ---
    result = handle_create_product(user, completed_products)

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_product_message(
        completed_products=completed_products,
        db_results=result,
        remaining_products=remaining_products,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "tokens": tokens_used + tokens_used_final,
        "cost": cost_est + cost_final,
        "session_summary": updated_summary
    }



def create_product2(user, user_message, session_data):
    """Extracts product details, validates fields, and creates the product record."""
    try:
        product_details = extract_product_details(user_message, session_data)

        if "error" in product_details:
            return {"message": product_details["error"]}
        
        response_message = ""
        
        for product_detail in product_details:
        
            # ✅ Validate fields format
            sku = product_detail.get("sku", None)
            name = product_detail.get("name", None)
            price = product_detail.get("price", None)

            # 🧠 Make the session context
            session_context = {
                "user": user,
                "intent": "CreateProductRecord",
                "agent_name": "product_agent",
                "session_data": session_data,
                "user_message": user_message,
                "item_index": 1,
                "extracted": {
                    "sku": sku,
                    "name": name,
                    "price": price
                }
            }

            # ✅ Validate required fields if product is not a bundle
            if product_detail.get("is_bundle") == True:
                required_fields = ["sku", "name"]
                missing_fields = [field for field in required_fields if not product_detail.get(field)]
            else:
                required_fields = ["sku", "name", "price"]
                missing_fields = [field for field in required_fields if not product_detail.get(field)]

            if missing_fields:
                agent_response = f"⚠️ Missing required fields: {', '.join(missing_fields)}. Please enter a value to proceed."
                logging.warning(f"⚠️ Missing required fields: {', '.join(missing_fields)}. Please enter a value to proceed.")
                save_or_update_conversation_context(session_context, agent_response) # Save conversation context before to return
                return {"message": agent_response}
            
            if not isinstance(sku, str):
                logging.warning(f"⚠️ SKU must be a string.")
                agent_response = "Error: SKU must be a string."
                save_or_update_conversation_context(session_context, agent_response)
                return {
                    "message": f"⚠️ SKU must be a string."
                }

            if not isinstance(name, str):
                logging.warning(f"⚠️ Name must be a string.")
                agent_response = "Error: Name must be a string"
                save_or_update_conversation_context(session_context, agent_response)
                return {
                    "message": f"⚠️ Name must be a string."
                }

            if not isinstance(price, (Decimal, float, int, str)):
                try:
                    price = Decimal(str(price))
                except:
                    logging.warning(f"⚠️ Price must be a number or numeric string")
                    agent_response = "Error: Name must be a string"
                    save_or_update_conversation_context(session_context, agent_response)
                    return {
                        "message": f"⚠️ Name must be a string."
                    }

            # ✅ Check if SKU exists
            if Product.objects.filter(sku=product_detail["sku"]).exists():
                agent_response = f"Error: Product {product_detail['sku']} already exists in the database"
                save_or_update_conversation_context(session_context, agent_response)
                return {"message": f"⚠️ Product `{product_detail['sku']}` already exists in the database."}

            # ✅ Create product record
            success_message = create_product_record(user, product_detail)

            response_message += success_message

        return {"message": response_message}  # ✅ Ensure correct response format

    except Exception as e:
        agent_response = f"Error: {e}"
        save_or_update_conversation_context(session_context, agent_response)
        return {"message": f"⚠️ Error processing product creation: {str(e)}"}

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

def extract_product_details(user_request, session_data):
    """Use GPT to extract product details based on our schema, considering session data."""
    
    # ✅ Retrieve pending product if available
    pending_product = session_data.get("pending_product")

    schema = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Extract product details from the following request and return them as JSON. The user may specify multiple products in a single message.
    Fields:
    - sku (string, unique)
    - name (string)
    - price (decimal, can be 0)
    - is_subscription (boolean)
    - term (integer, default: 12 if is_subscription is True, otherwise null)
    - is_bundle (boolean)
    - description (string, default: null if not specified by the user)

    Example request: "Create a product called AI Sales Assistant with SKU CRM-001 and price 59.99. It is a subscription. With a description: Description: "AI-powered tool to streamline sales processes."
    Example response:
    [
    {{
        "sku": "CRM-001",
        "name": "AI Sales Assistant",
        "price": 59.99,
        "is_subscription": true,
        "term": 12,
        "is_bundle": false,
        "description": "AI-powered tool to streamline sales processes."
    }}
    ]

    Requirements:
    - If no SKU is found in the user message, set SKU as null
    - If no name is found in the user message, set name as null
    - If no price is found in the user message, set price as null
    - If no is_subscription is found in the user message, set is_subscription as null
    - If no term is found in the user message, set term as null
    - If no is_bundle is found in the user message, set is_bundle as null
    - If no description is found in the user message, set description as null

    If the user is confirming a previous product creation (e.g., "Yes, confirm"), use the following pending product details:
    {json.dumps(pending_product, indent=2) if pending_product else "None"}

    Request: {user_request}

    **Return a valid JSON only of product object. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json) — just return the JSON.**
    """

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a CPQ AI assistant that extracts product details based on a defined schema."},
                {"role": "user", "content": schema}
            ]
        )

        # ✅ Print the raw response to debug issues
        raw_response = response.choices[0].message.content.strip()
        print("🔹 RAW LLM RESPONSE:", raw_response)  # Debugging

        # ✅ Ensure it's a valid JSON response
        try:
            raw_response = clean_llm_response(raw_response)
            extracted_data = json.loads(raw_response)
        except json.JSONDecodeError:
            logging.warning(f"⚠️ LLM returned an invalid response: {raw_response}")
            return {"error": f"⚠️ Error extracting product details: {raw_response}"}

        return extracted_data

    except Exception as e:
        logging.warning(f"⚠️ Something went wrong when LLM trying to extract product details: {raw_response}")
        return {"error": f"⚠️ Error extracting product details: {str(e)}"}
  

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
        product.updated_by = user

        # ✅ Save the updated product
        product.save()
        log_action_usage("UpdateProductRecord", user, "Product", product.name)
        print(f"✅ DEBUG: Product `{sku}` successfully updated.")  # ✅ Debugging step

        return f"✅ Product `{sku}` successfully updated."

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