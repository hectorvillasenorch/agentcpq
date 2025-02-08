import openai , json, os
import re
from django.http import JsonResponse
from .orchestrator import orchestrate_request
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.template.context_processors import csrf
from dotenv import load_dotenv
from cpq.models import Product 
import logging
from .orchestrator import orchestrate_request

logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"



def agents_chat(request):
    """Render the chat page with CSRF token."""
    context = {}
    context.update(csrf(request))  # ✅ Add CSRF token to context
    return render(request, "agents.html", context)



@csrf_exempt
def chat_with_gpt(request):
    """Process user messages and route them based on AI-determined intent."""
    if request.method == "POST":
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()

        try:
            # ✅ Step 1: Load Session Context
            session_data = request.session.get("session_data", {})

            # ✅ Step 2: Handle Pending Actions
            pending_action = session_data.get("pending_action")

            if pending_action:
                logging.info(f"🔄 Resuming pending action: {pending_action}")

                if pending_action == "confirm_opportunity":
                    opportunity_name = user_message
                    session_data["opportunity_name"] = opportunity_name
                    session_data["pending_action"] = None
                    request.session["session_data"] = session_data
                    return JsonResponse({"response": f"✅ Opportunity `{opportunity_name}` added. Would you like to add products now?"})

                if pending_action == "confirm_product_addition":
                    product_sku = user_message
                    session_data["product_sku"] = product_sku
                    session_data["pending_action"] = None
                    request.session["session_data"] = session_data
                    return JsonResponse({"response": f"✅ Product `{product_sku}` added to the quote."})

            # ✅ Step 3: Route User Message via Orchestrator
            response = orchestrate_request(user_message, session_data)

            # ✅ Step 4: Store Context in Session
            request.session["session_data"] = session_data
            logging.info(f"[Orchestrator] Agent Response: {response}")

            return JsonResponse({"response": response})

        except Exception as e:
            logging.error(f"❌ Error in `chat_with_gpt`: {e}")
            return JsonResponse({"response": f"⚠️ An error occurred: {str(e)}"}, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)
# def chat_with_gpt(request):
#     """Processes user message, determines intent, and routes response."""
#     if request.method == "POST":
#         data = json.loads(request.body)
#         user_message = data.get("message", "").strip()

#         try:
#             session_data = request.session.get("session_memory", {})
#             response = orchestrate_request(user_message, session_data)

#             return JsonResponse({"response": response})  # ✅ Fixed: Wrapped in a dictionary

#         except Exception as e:
#             logging.error(f"❌ Error in chat_with_gpt: {e}")
#             return JsonResponse({"response": "⚠️ An error occurred while processing your request."})

#     return JsonResponse({"error": "Invalid request"}, status=400)
# def chat_with_gpt(request):
#     """Process user messages and route them based on intent (create/update product)."""
#     if request.method == "POST":
#         data = json.loads(request.body)
#         user_message = data.get("message", "").strip()

#         try:
#             client = openai.OpenAI(api_key=OPENAI_API_KEY)

#             # ✅ Step 1: Check if user is responding to a pending action
#             pending_action = request.session.get("pending_action")
            
#             if pending_action == "confirm_creation":
#                 product_details = request.session.get("pending_product")
#                 print("🔹 DEBUG: Pending product details before creation:", product_details)  # ✅ Debugging step

#                 if user_message in ["yes", "confirm"]:
#                     response_text = create_product_record(product_details)  # ✅ Now returns a string
#                     request.session.pop("pending_action", None)
#                     request.session.pop("pending_product", None)
#                     return JsonResponse({"response": response_text})  # ✅ Correct place to return JsonResponse

#                 else:
#                     request.session.pop("pending_action", None)
#                     request.session.pop("pending_product", None)
#                     return JsonResponse({"response": "❌ Product creation canceled."})

#             if pending_action == "confirm_update":
#                 updated_product = request.session.get("pending_update")
#                 print("🔹 DEBUG: Pending update details before confirmation:", updated_product)  # ✅ Debugging step

#                 if user_message in ["yes", "confirm"]:
#                     response_text = update_product_record(updated_product)  # ✅ Now returns a string
#                     request.session.pop("pending_action", None)
#                     request.session.pop("pending_update", None)
#                     return JsonResponse({"response": response_text})  # ✅ Correct place to return JsonResponse

#                 else:
#                     request.session.pop("pending_action", None)
#                     request.session.pop("pending_update", None)
#                     return JsonResponse({"response": "❌ Product update canceled."})

#             # ✅ Step 2: Detect user intent
#             intent_detection_prompt = f"""
#             You are an AI assistant that classifies user messages into intents.
#             Here are the possible intents:
#             - "create_product": When the user wants to create a new product.
#             - "update_product": When the user wants to update an existing product.
#             - "general_query": When the user asks something else.

#             User message: "{user_message}"
#             Return only the intent as a single word.
#             """

#             response = client.chat.completions.create(
#                 model="gpt-4",
#                 messages=[{"role": "user", "content": intent_detection_prompt}]
#             )
#             intent = response.choices[0].message.content.strip().lower()

#             print("🔹 DEBUG: DETECTED INTENT:", intent)  # ✅ Debugging step

#             # ✅ Step 3: Route request based on detected intent
#             if intent == "create_product":
#                 product_response = create_product_from_message(user_message)

#                 if product_response["product_details"]:
#                     print("🔹 DEBUG: Extracted product details before storing in session:", product_response["product_details"])  # ✅ Debugging step
#                     request.session["pending_action"] = "confirm_creation"
#                     request.session["pending_product"] = product_response["product_details"]

#                 return JsonResponse({"response": product_response["message"]})

#             elif intent == "update_product":
#                 update_response = update_product_details(user_message)

#                 if update_response["product_details"]:
#                     print("🔹 DEBUG: Extracted update details before storing in session:", update_response["product_details"])  # ✅ Debugging step
#                     request.session["pending_action"] = "confirm_update"
#                     request.session["pending_update"] = update_response["product_details"]

#                 return JsonResponse({"response": update_response["message"]})

#             else:
#                 # ✅ Step 4: Process general AI queries
#                 response = client.chat.completions.create(
#                     model="gpt-4",
#                     messages=[
#                         {"role": "system", "content": "You are an AI assistant that helps users with CPQ automation."},
#                         {"role": "user", "content": user_message}
#                     ]
#                 )
#                 ai_response = response.choices[0].message.content

#         except Exception as e:
#             ai_response = f"⚠️ Error: {str(e)}"

#         return JsonResponse({"response": ai_response})

#     return JsonResponse({"error": "Invalid request"}, status=400)

def create_product_from_message(user_message):
    """Extract product details, validate, and ask for confirmation before creating."""
    try:
        # ✅ Extract product details using GPT
        product_details = extract_product_details(user_message)

        if "error" in product_details:
            return {"message": product_details["error"], "product_details": None}

        # ✅ Check if SKU exists in the database (preserving case)
        if Product.objects.filter(sku=product_details["sku"]).exists():
            return {"message": f"⚠️ Product `{product_details['sku']}` already exists in the database.", "product_details": None}

        # ✅ Debugging step: Print the extracted SKU before storing it in session
        print("🔹 DEBUG: Extracted SKU before confirming:", product_details["sku"])  

        # ✅ Show JSON Preview Before Creating
        json_preview = json.dumps(product_details, indent=2)
        return {
            "message": f"🔹 Here is the product that will be created:\n```json\n{json_preview}\n```\nDo you confirm?",
            "product_details": product_details
        }

    except Exception as e:
        return {"message": f"⚠️ Error processing product creation: {str(e)}", "product_details": None}
    

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

def update_product_details(user_message):
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

        # ✅ Show updated JSON to user before saving
        json_preview = json.dumps(updated_product, indent=2)
        return {
            "message": f"🔹 Updated product details:\n```json\n{json_preview}\n```\nDo you confirm?",
            "product_details": updated_product
        }

    except Exception as e:
        return {"message": f"⚠️ Error updating product details: {str(e)}", "product_details": None}

def extract_product_details(user_request):
    """Use GPT to extract product details based on our schema."""
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
        print("🔹 RAW GPT RESPONSE:", raw_response)  # Debugging

        # ✅ Ensure it's a valid JSON response
        try:
            extracted_data = json.loads(raw_response)
        except json.JSONDecodeError:
            return {"error": f"⚠️ GPT returned invalid JSON: {raw_response}"}

        return extracted_data

    except Exception as e:
        return {"error": f"⚠️ Error extracting product details: {str(e)}"}    
  
def create_product_record(product_details):
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
        return f"✅ Product `{product.sku}` successfully created."

    except Exception as e:
        return f"⚠️ Error creating product: {str(e)}"

def update_product_record(updated_product_details):
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