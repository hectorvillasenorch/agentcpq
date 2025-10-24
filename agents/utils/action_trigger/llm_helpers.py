import json, os, re
import openai
import logging
from dotenv import load_dotenv
from agents.models import AgentPrompt
from django.apps import apps

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
#OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def to_snake_case(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def extract_action_triggers_with_llm(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract structured data for creating action triggers.
    Returns JSON and agent message.
    """
    # 🔹 Obtener todos los modelos disponibles en CPQ (y normalizarlos)
    EXCLUDED_MODELS = ["SystemFieldMapping", "ApprovalRule", "AuditLog"]
    all_models = [m.__name__ for m in apps.get_app_config('cpq').get_models()]
    available_models = [to_snake_case(m) for m in all_models if m not in EXCLUDED_MODELS]

    print(f"\n\nAvailable models: {available_models}\n\n")

    system_prompt = """
    You are a helpful AI assistant that extracts structured data to define Action Triggers for a CPQ system.
    Your goal is to interpret the user message and build an Action Trigger definition in JSON format.

    Always return a JSON with this structure:
    {
        "create_action_trigger": [
            {
                "data": {
                    "description": null,
                    "event_type": null,
                    "conditions": {
                        "logic": "AND",
                        "items": []
                    },
                    "actions": [],
                    "active": true
                },
                "completed": false
            }
        ],
        "agent_message": "string",
        "summary": "string"
    }

    🔹 **Field definitions:**

    - description: A short natural language summary (1 sentence) explaining what the trigger does.  
      Example: "Update quote line price using Pricing Table when SKU and Tier match."

    - event_type: The system event that activates the trigger. Must follow the format:
      "<object>.<action>"  
      Examples:
        - "quote.created"
        - "quote.updated"
        - "quote_line.updated"
        - "quote_line.created"

    - conditions: Defines logical comparisons that determine when the trigger executes.
      Must have:
      {
        "logic": "AND" | "OR",
        "items": [
          {
            "alias": "optional_alias",
            "left": {"object": "<ObjectName>", "path": "<field>"},
            "operator": "== | != | > | < | >= | <= | contains | in | not in",
            "right": {
              "type": "field" | "static",
              "object": "<ObjectName>" (if type=field),
              "path": "<field>",
              "data": "<value if static>"
            }
          }
        ]
      }

    - actions: Defines what to do if the conditions are true.
      Example:
      [
        {
          "operation": "SET" | "CREATE" | "DELETE",
          "target": {"object": "<ObjectName>", "path": "<field>"},
          "value": {
            "type": "field" | "static",
            "object": "<ObjectName>" (if type=field),
            "path": "<field>",
            "data": "<value if static>"
          }
        }
      ]

    - active: boolean. If not specified, assume true.
    """

    system_prompt += f"""
    🔸 Model naming rules:
    The user might refer to models using variations like "Quote Line", "QuoteLine", or "quoteline".
    You must always normalize object names to lowercase snake_case.

    Here are the available object names in this system:
    {json.dumps(available_models, indent=2)}

    Only use these normalized names for "object" fields.
    """

    system_prompt += """
    - completed: true only if all required fields (description, event_type, conditions, actions) are fully defined and valid.

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
        temperature=0.8
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None

    # ✅ Normalize structure
    normalized_triggers = []
    for trig in result_json.get("create_action_trigger", []):
        data = trig.get("data", {})

        normalized_triggers.append({
            "data": {
                "description": data.get("description"),
                "event_type": data.get("event_type"),
                "conditions": data.get("conditions", {"logic": "AND", "items": []}),
                "actions": data.get("actions", []),
                "active": data.get("active", True)
            },
            "completed": trig.get("completed", False)
        })

    result_json["create_action_trigger"] = normalized_triggers
    return result_json