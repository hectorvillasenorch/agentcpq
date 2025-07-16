from cpq.models import Product 
import openai
from dotenv import load_dotenv
import json
import os
import logging
from .utils.quote_agent.db_helpers import log_action_usage

#LLM Helpers
from .utils.product_agent.llm_helpers import extract_bundle_components

# Record Helpers
from .utils.product_agent.record_helpers import handle_bundle_components


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"


def bundles_agent(user, action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "AddProductToBundle": create_bundle_components
        # "UpdateBundle": generate_quote_pdf,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request. From Bundles Agent"}

    

def create_bundle_components(user, user_message, session_data): #Using Option model
    """Handle bundle components."""
    logging.info("🔄 Creating bundle components...")

    extracted_components = extract_bundle_components(user_message)

    if not extracted_components or not isinstance(extracted_components, list):
        return {
            "message": "⚠️ Could not parse the bundle structure. Please include a bundle SKU, name, and a list of components with fields like product SKU, quantity, and required status."
        }
    
    components_created = []
    response_message = ""

    response_message, components_created = handle_bundle_components(extracted_components, response_message)

    if components_created:
        return {
            "message": response_message
        }
    else:
        return {
            "message": f"⚠️ Error: Something went wrong — no product(s) was added to the bundle. Please try again or verify your input.<br><br>{response_message}"
        }
    
