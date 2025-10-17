import json
import re
import logging

def clean_llm_json(raw_response):
    """
    Cleans the LLM response and returns a JSON dict.
    Handles Markdown blocks (```json ... ```), trims, and JSON errors.
    Returns None if parsing fails.
    """
    if not raw_response:
        return None

    # Clear Markdown ```json ... ```
    if raw_response.startswith("```"):
        raw_response = re.sub(r"^```(json)?", "", raw_response.strip())
        raw_response = re.sub(r"```$", "", raw_response.strip())
        raw_response = raw_response.strip()

    try:
        result_json = json.loads(raw_response)
        logging.info("\n\n✅ LLM response cleaned and parsed successfully.\n\n")
        return result_json
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        logging.error(f"🪶 Raw response that failed to decode:\n{raw_response}")
        return None