import json
import os
import re
from django.http import JsonResponse
from .orchestrator import handle_user_request
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.template.context_processors import csrf
from dotenv import load_dotenv
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
    opportunity_id = request.GET.get('opportunity_id', 'No Opportunity ID provided')

    # ✅ Log the full incoming request URL
    print(f"🔹 DEBUG: Incoming request URL - {request.build_absolute_uri()}")  
    print(f"🔹 DEBUG: Extracted Opportunity ID - {opportunity_id}")  

    if request.method == "POST":
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
            

        try:
            # ✅ Step 1: Load Session Context
            session_data = request.session.get("session_data", {})
            # ✅ Step 1: Load Session Context
            session_data = request.session.get("session_data", {})
            print("🔹 DEBUG: Session Data:", session_data)  # ✅ Debugging step

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
            response = handle_user_request(user_message, session_data)
            

            # ✅ Step 4: Store Context in Session
            request.session["session_data"] = session_data
            logging.info(f"[Orchestrator] Agent Response: {response}")

            return JsonResponse({"response": response})

        except Exception as e:
            logging.error(f"❌ Error in `chat_with_gpt`: {e}")
            return JsonResponse({"response": f"⚠️ An error occurred: {str(e)}"}, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)

