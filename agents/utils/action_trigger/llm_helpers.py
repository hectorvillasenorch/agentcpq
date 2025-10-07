import json, os, re
import openai
import logging
from dotenv import load_dotenv
from agents.models import AgentPrompt

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
#OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)


def extract_action_triggers_with_llm(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract structured data for creating action triggers.
    Returns JSON and agent message.
    """
    system_prompt = """
    You are a helpful AI assistant that create action triggers from user message.
    Always return JSON with structure:
    {
        "create_action_trigger": [
            {
                "data": {
                    "trigger": None,
                    "action": None,
                    "object_name": None,
                    "action_params": {},
                    "active": true,

                },
                "completed": False
            }
        ],
        "agent_message": "string",
        "summary": "string"
    }

    **Rules:**  
    1. The trigger must be one of the following: `opportunity_closed_won`  
    2. Action must be: `create`, `update`, or `delete`  
    3. Object Name must be one of the following: `renewal_task`  
    4. If the user does not specify the **Active** field, set it to `true` by default
    5. Mark completed as true when user provided trigger, action, object_name and action_params

    **Rules for action_params:**  
    1. If the `object_name` is `renewal_task`, then `action_params` must have the following JSON format:  
    ```json
    {
    "months_before": <VALUE>
    }
    The value of the months_before key must be:
    - "immediately", if the user specifies that they want the action trigger to be activated immediately.
    - 6, if the user specifies "after 6 months".
    - 3, if the user specifies "3 months before expiration date".

    **Agent message:**  
    - Interpret this as an attempt, therefore do not say things like "created successfully".  
    - If any of the following fields are not mentioned by the user, set **completed** to false and respond naturally to the user indicating what information is missing, without being technical: `trigger`, `action`, `object_name`, `action_params`.  
    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, data requests, etc.  
    - Be brief, professional, and natural.  
    - Do not be technical.  
    - Continue naturally (DO NOT start with "Hello").  
    - Use `<br>` for line breaks.  
    - Include information if the user attempted to create an inclusion rule.

    **Summary:**
    - Create a short summary combining previous summary + this iteration.
    """

    user_prompt = f"""
    User message: "{user_message}"

    Current state:
    {json.dumps(current_state, indent=2)}

    Previous summary:
    {previous_summary if previous_summary else "None"}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None

    # ✅ Normalize structure for action triggers
    normalized_triggers = []
    for trig in result_json.get("create_action_trigger", []):
        data = trig.get("data", {})
        normalized_triggers.append({
            "data": {
                "trigger": data.get("trigger"),
                "action": data.get("action"),
                "object_name": data.get("object_name"),
                "action_params": data.get("action_params", {}),
                "active": data.get("active", True)
            },
            "completed": trig.get("completed", False)
        })
    result_json["create_action_trigger"] = normalized_triggers

    return result_json