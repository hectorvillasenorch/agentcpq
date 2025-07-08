from cpq.models import Product 
import openai
from dotenv import load_dotenv
import json
import os
import logging
from .utils.quote_agent.db_helpers import log_action_usage


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"


def product_agent(user, action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "CreateProductRecord": create_product,
        "UpdateProductRecord": update_product,
        # "UpdateBundle": generate_quote_pdf,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request. From Product Agent"}



def create_product(user, user_message, session_data):
    """Extracts product details, validates fields, and creates the product record."""
    try:
        product_details = extract_product_details(user_message, session_data)

        if "error" in product_details:
            return {"message": product_details["error"]}

        # ✅ Validate required fields
        required_fields = ["sku", "name", "price"]
        missing_fields = [field for field in required_fields if not product_details.get(field)]

        if missing_fields:
            return {"message": f"⚠️ Missing required fields: {', '.join(missing_fields)}. Please provide them."}

        # ✅ Check if SKU exists
        if Product.objects.filter(sku=product_details["sku"]).exists():
            return {"message": f"⚠️ Product `{product_details['sku']}` already exists in the database."}

        # ✅ Create product record
        success_message = create_product_record(user, product_details)

        return {"message": success_message}  # ✅ Ensure correct response format

    except Exception as e:
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
            return {"message": "⚠️ No changes detected or invalid update request."}

        # ✅ Store JSON preview for reference
        json_preview = json.dumps(updated_product, indent=2)

        # ✅ Execute the update
        product_update_executed = update_product_record(user,updated_product)

        return {
            "message": f"🔹 Updated product details:\n```json\n{json_preview}\n```\n\n {product_update_executed}",
            "product_details": updated_product
        }

    except Exception as e:
        return {"message": f"⚠️ Error updating product details: {str(e)}", "product_details": None}

def extract_product_details(user_request, session_data):
    """Use GPT to extract product details based on our schema, considering session data."""
    
    # ✅ Retrieve pending product if available
    pending_product = session_data.get("pending_product")

    schema = f"""
    Extract product details from the following request and return them as JSON.
    Fields:
    - sku (string, unique)
    - name (string)
    - price (decimal, can be 0)
    - is_subscription (boolean, default: false)
    - term (integer, default: 12 if is_subscription is True, otherwise null)
    - is_bundle (boolean, default: false)

    Example request: "Create a product called AI Sales Assistant with SKU CRM-001 and price 59.99. It is a subscription."
    Example response:
    {{
        "sku": "CRM-001",
        "name": "AI Sales Assistant",
        "price": 59.99,
        "is_subscription": true,
        "term": 12,
        "is_bundle": false
    }}

    If the user is confirming a previous product creation (e.g., "Yes, confirm"), use the following pending product details:
    {json.dumps(pending_product, indent=2) if pending_product else "None"}

    Request: {user_request}
    """

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4",
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
            extracted_data = json.loads(raw_response)
        except json.JSONDecodeError:
            return {"error": f"⚠️ LLM returned invalid JSON: {raw_response}"}

        return extracted_data

    except Exception as e:
        return {"error": f"⚠️ Error extracting product details: {str(e)}"}
  
def create_product_record(user,product_details):
    """Create a new product record in the database and return a success message."""
    try:
        # ✅ Create the product
        product = Product.objects.create(
            sku=product_details["sku"],
            name=product_details["name"],
            price=product_details["price"],
            is_subscription=product_details["is_subscription"],
            term=product_details.get("term", 12),  # Default term is 12
            is_bundle=product_details["is_bundle"],
        )

        print("✅ DEBUG: Created Product:", product)  # Debugging step

        # ✅ Instead of returning JsonResponse, return a success message string
        log_action_usage("CreateProductRecord", user, "Product", product.sku)

        return f"✅ Product `{product.sku}` successfully created."
       

    except Exception as e:
        return f"⚠️ Error creating product: {str(e)}"

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