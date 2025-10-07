from cpq.models import Product
import openai
from dotenv import load_dotenv
import json
import os
import logging
from .utils.quote_agent.db_helpers import log_action_usage

# FROM QUOTE ANGENT

from .utils.quote_agent.general_helpers import get_active_quote

#LLM Helpers
from .utils.bundles_agent.llm_helpers import extract_bundle_components, extract_delete_options_from_quote, extract_option_updates

# Record Helpers
from .utils.bundles_agent.record_helpers import handle_bundle_components, handle_delete_options_from_quote, handle_option_updates


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"


def bundles_agent(user, action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "AddProductToBundle": create_bundle_components, # For the future, modify this function name to create_bundle_option
        "UpdateBundleOption": update_bundle_option,
        #"DeleteBundleOption": delete_bundle_option,
        #"UpdateBundleComponentInQuote": update_bundle_component_in_quote,
        "DeleteBundleComponentFromQuote": delete_bundle_option_from_quote,
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

def delete_bundle_option_from_quote(user, user_message, session_data):
    """Delete Bundle Option From Quote."""
    logging.info("🔄 Deleting bundle components...")

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote

    extracted_delete_options =  extract_delete_options_from_quote(user_message)

    if not extracted_delete_options or not isinstance(extracted_delete_options, list):
        return {
            "message": "⚠️ Failed to extract bundle options correctly. Please try again."
        }

    options_deleted = []
    response_message = ""

    response_message, options_deleted = handle_delete_options_from_quote(extracted_delete_options, response_message, quote)

    if options_deleted:
        return {
            "message": response_message
        }
    else:
        return {
            "message": f"⚠️ Error: Something went wrong — no bundle component(s) quote line was deleted from the quote. Please try again or verify your input.<br><br>{response_message}"
        }

def update_bundle_option(user, user_message, session_data):
    """Updatins Bundle Option"""
    logging.info("🔄 Updating bundle option...")

    extracted_option_updates = extract_option_updates(user_message)

    if not extracted_option_updates:

        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }

    response_message = ""

    # ✅ Handle updates option
    response_message, updated_options = handle_option_updates(extracted_option_updates, response_message)

    # ✅ Return
    if not updated_options:
        return {
            "message": f"No options were updated. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True

        }
