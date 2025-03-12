from django.db.models import Sum, F, Max
import json
import os
import openai
import logging
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product, ApprovalWorkflow, ApprovalStep, QuoteApproval
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from datetime import datetime

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def approval_agent(action, user_message, session_data):
    """Handles approval-related actions dynamically using GPT message parsing."""
    
    # ✅ Extract structured intent and parameters from the user message
    parsed_data = parse_user_message(user_message)
    action = parsed_data.get("action", "Unknown")
    parameters = parsed_data.get("parameters", {})

    logging.info(f" 🟡 >>>>>>>>>>>>>>>>>> QUOTE ID: {parameters.get("quote_id")}")

    # ✅ Handle unknown actions
    if action == "Unknown":
        return {"message": "🤖 Sorry, I couldn’t understand your request. Try rephrasing it."}

    # ✅ Action-to-function mapping
    action_map = {
        "SubmitForApproval": submit_for_approval,
        "CheckApprovalStatus": get_approval_status,
        "ApproveQuote": approve_quote,
        "RejectQuote": reject_quote,
        "RecallQuote": recall_quote,
    }

    # ✅ Check if the extracted action is in the action_map
    if action in action_map:
        return action_map[action](user_message, session_data, **parameters)

    return {"message": "🤖 Sorry, I couldn’t process your request. Please try again."}


def submit_for_approval(user_message, session_data, quote_name=None, quote_id=None):
    """Handles submitting a quote for approval or retrieving approval status.
       If the quote (by name) is not found, it will be auto-approved.
    """
    logging.info("🔄 Processing quote submission or status check...")

    # ✅ Extract quote name if not provided
    if not quote_name and "quote " in user_message.lower():
        try:
            quote_name = user_message.lower().split("quote ")[1].strip()
        except IndexError:
            return {"message": "⚠️ Invalid request format. Please provide a quote name, e.g., 'Submit for approval quote Q-XXXXX'."}

    # ✅ Ensure we have a valid quote name
    if not quote_name:
        return {"message": "⚠️ Missing quote name. Use 'Submit for approval quote Q-XXXXX'."}

    # ✅ Check if the user is requesting approval status
    if "status" in user_message.lower():
        return get_approval_status(quote_id=quote_name)  # Here we assume quote_name acts as an identifier

    # ✅ Retrieve the quote by name; if not found, auto-approve it
    try:
        quote = Quote.objects.get(name=quote_name)
    except Quote.DoesNotExist:
        logging.warning(f"⚠️ Quote `{quote_name}` not found. Auto-approving it.")
        # Simulate auto-approval for a missing quote:
        return {
            "message": f"✅ Quote `{quote_name}` not found. It has been auto-approved.",
            "quote_name": quote_name,
            "history": [{
                "workflow": "Auto-Approval",
                "step": "System Approved",
                "status": "Approved",
                "approved_by": "System",
                "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }]
        }

    # ✅ Store the active quote in session data
    session_data["active_quote"] = {"quote_id": quote.id, "quote_name": quote_name}

    # ✅ Proceed to process quote approval
    return process_quote_approval(session_data)


def process_quote_approval(session_data):
    """Processes the approval of a quote after validation."""
    try:
        # ✅ Retrieve the active quote from session data
        active_quote = session_data.get("active_quote")
        if not active_quote or "quote_id" not in active_quote:
            return {"message": "⚠️ No active quote found. Please specify a quote to submit for approval."}

        quote = Quote.objects.get(id=active_quote["quote_id"])

        # ✅ Check if the quote is already Approved or Rejected
        existing_approval = QuoteApproval.objects.filter(quote=quote).order_by('-approved_at').first()
        if existing_approval and existing_approval.status in ["Approved", "Rejected"]:
            return {"message": f"⚠️ This quote has already been {existing_approval.status.lower()} and cannot be resubmitted."}

        # ✅ Get total discount percentage
        total_discount = quote.get_total_discount_percentage()

        # ✅ Find the applicable approval workflow
        workflow = ApprovalWorkflow.objects.first()  # TODO: Implement dynamic selection logic
        if not workflow:
            return {"message": "⚠️ No approval workflow found. Please configure an approval process first."}

        # ✅ Find the first approval rule that matches the quote
        applicable_rule = None
        for rule in workflow.rules.order_by('-priority'):
            if rule.matches_quote(quote):
                applicable_rule = rule
                break  # Stop at the highest-priority matching rule

        if not applicable_rule:
            return {"message": f"⚠️ No approval rule found for quote `{quote.name}` in workflow `{workflow.name}`."}

        # ✅ Find the first approval step for the selected rule
        approval_step = applicable_rule.steps.order_by("sequence").first()
        if not approval_step:
            return {"message": f"⚠️ No approval step found for rule `{applicable_rule.name}` in workflow `{workflow.name}`."}

        # ✅ Auto-Approval Logic
        if approval_step.approver_role == "Auto-Approved":
            logging.info(f"🟢 Auto-approving quote `{quote.name}` as per rule `{applicable_rule.name}`.")
            return auto_approve_quote(quote, workflow, approval_step)

        # ✅ Create or update approval record
        approval, created = QuoteApproval.objects.update_or_create(
            quote=quote,
            workflow=workflow,
            step=approval_step,
            defaults={"status": "Pending"}
        )

        # ✅ Update quote status
        quote.status = "Pending Approval"
        quote.save()

        # ✅ Ensure session updates
        session_data["approval_status"] = "Pending"
        session_data["active_approval"] = {
            "quote_id": quote.id,
            "approval_step": approval_step.approver_role
        }

        logging.info(f"🟢 Quote `{quote.name}` submitted for approval (Step: {approval_step.approver_role})")
        return {"message": f"✅ Quote `{quote.name}` submitted for approval. Awaiting `{approval_step.approver_role}` approval."}

    except Quote.DoesNotExist:
        return {"message": "⚠️ Quote not found. Please provide a valid quote ID."}
    except Exception as e:
        logging.error(f"❌ Error submitting for approval: {str(e)}")
        return {"message": f"⚠️ Error submitting for approval: {str(e)}"}


def get_approval_status(user_message=None, session_data=None, quote_id=None, status=None):
    """Retrieves the approval status and history of a given quote, with optional filtering by status.
       If the quote is not found, it will be auto-approved.
    """
    logging.warning(f"⚠️ Quote ID:==========================> `{quote_id}` ")
    try:
        
        # ✅ 1. If no quote_id provided, check session_data for active quote
        if not quote_id and session_data and isinstance(session_data.get("active_quote"), dict):
            quote_id = session_data["active_quote"].get("quote_id")

        # ✅ 2. If still no quote_id, return an error
        if not quote_id:
            return {
                "success": False,
                "message": "⚠️ No active quote found. Please specify a quote ID or ensure a quote is selected in the session."
            }

        # ✅ 3. Retrieve the quote
        try:
            quote = Quote.objects.get(name=quote_id)
        except Quote.DoesNotExist:
            logging.warning(f"⚠️ Quote with ID `{quote_id}` not found. Auto-approving it.")
            # Simulate auto-approval for a missing quote:
            return {
                "success": True,
                "message": f"✅ Quote with ID `{quote_id}` not found in records but has been auto-approved.",
                "quote_name": quote_id,
                "history": [{
                    "workflow": "Auto-Approval",
                    "step": "System Approved",
                    "status": "Approved",
                    "approved_by": "System",
                    "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }]
            }

        # ✅ 4. Fetch approval records for this quote
        approvals = QuoteApproval.objects.filter(quote_id=quote.id).order_by('-approved_at')

        if not approvals.exists():
            return {
                "success": True,
                "message": f"ℹ️ No approvals found for Quote `{quote.name}`.",
                "quote_name": quote.name,
                "history": []
            }

        # ✅ 5. Format approval history as JSON
        approval_data = [
            {
                "workflow": approval.workflow.name,
                "step": approval.step.approver_role,
                "status": approval.status,
                "approved_by": approval.approved_by or "N/A",
                "approved_at": approval.approved_at.strftime("%Y-%m-%d %H:%M:%S") if approval.approved_at else "N/A"
            }
            for approval in approvals
        ]

        return {
            "success": True,
            "message": f"📋 Approval history for Quote `{quote.name}`:",
            "quote_name": quote.name,
            "history": approval_data
        }

    except Exception as e:
        logging.error(f"❌ Error retrieving approval status: {str(e)}")
        return {
            "success": False,
            "message": f"⚠️ Error retrieving approval status: {str(e)}"
        }


def approve_quote(user_message, session_data):
    """Handles approval of a submitted quote, with auto-approval based on discount thresholds."""
    logging.info("🔄 Checking quote approval...")

    active_quote = session_data.get("active_quote")
    if not active_quote or "quote_id" not in active_quote:
        return {"message": "⚠️ No active quote found. Please specify a quote to approve."}

    try:
        # ✅ Retrieve Quote
        quote = Quote.objects.get(id=active_quote['quote_id'])
        approval = QuoteApproval.objects.filter(quote=quote, status="Pending Approval").first()

        if not approval:
            return {"message": f"⚠️ No pending approval found for quote {quote.name}."}
        
        if approval.status == "Approved":
            return {"message": f"✅ Quote {quote.name} has already been approved."}

        # ✅ Retrieve Approval Workflow
        workflow = approval.workflow
        steps = ApprovalStep.objects.filter(workflow=workflow).order_by('sequence')

        # ✅ Get the highest discount in the quote
        max_discount = Decimal(quote.quoteline_set.aggregate(max_discount=Max("additional_discount"))["max_discount"] or 0)
        logging.info(f"🔍 Max Discount in Quote: {max_discount}%")

        # ✅ Determine the required approval step
        required_step = steps.filter(approval_threshold__gte=max_discount).order_by("approval_threshold").first()

        if required_step:
            if required_step.approver_role == "Auto-Approved":
                approval.status = "Approved"
                approval.approved_by = "System"
                approval.approved_at = timezone.now()
                approval.save()

                quote.status = "Approved"
                quote.save()
                logging.info(f"🟢 Quote {quote.name} auto-approved (Discount: {max_discount}%).")
                return {"message": f"✅ Quote {quote.name} auto-approved. No manual approval required."}

            else:
                return {"message": f"⚠️ Quote {quote.name} requires `{required_step.approver_role}` approval due to a {max_discount}% discount."}

        return {"message": f"⚠️ No approval step found for {max_discount}% discount in workflow `{workflow.name}`."}

    except Quote.DoesNotExist:
        return {"message": "⚠️ Quote not found. Please provide a valid quote ID."}
    except Exception as e:
        logging.error(f"❌ Error approving quote: {str(e)}")
        return {"message": f"⚠️ Error approving quote: {str(e)}"}


def reject_quote(user_message, session_data):
    """Handles rejection of a submitted quote."""
    logging.info("🔄 Rejecting quote...")

    active_quote = session_data.get("active_quote")
    if not active_quote or "quote_id" not in active_quote:
        return {"message": "⚠️ No active quote found. Please specify a quote to reject."}

    try:
        quote = Quote.objects.get(id=active_quote['quote_id'])
        approval = QuoteApproval.objects.filter(quote=quote, status="Pending Approval").first()

        if not approval:
            return {"message": f"⚠️ No pending approval found for quote `{quote.name}`."}

        # ✅ Mark as rejected
        approval.status = "Rejected"
        approval.approved_by = "System"  # TODO: Replace with actual approver info
        approval.approved_at = timezone.now()
        approval.save()
        quote.status = "Rejected"
        quote.save()

        logging.info(f"🛑 Quote {quote.name} rejected.")
        return {"message": f"❌ Quote `{quote.name}` has been rejected."}

    except Quote.DoesNotExist:
        return {"message": "⚠️ Quote not found. Please provide a valid quote ID."}
    except Exception as e:
        logging.error(f"❌ Error rejecting quote: {str(e)}")
        return {"message": f"⚠️ Error rejecting quote: {str(e)}"}


def recall_quote(user_message, session_data):
    """Allows a user to recall a submitted quote before it's approved/rejected."""
    logging.info("🔄 Recalling quote...")

    active_quote = session_data.get("active_quote")
    if not active_quote or "quote_id" not in active_quote:
        return {"message": "⚠️ No active quote found. Please specify a quote to recall."}

    try:
        quote = Quote.objects.get(id=active_quote['quote_id'])
        approval = QuoteApproval.objects.filter(quote=quote, status="Pending Approval").first()

        if not approval:
            return {"message": f"⚠️ No pending approval found for quote `{quote.name}`."}

        # ✅ Recall approval
        approval.status = "Recalled"
        approval.save()
        quote.status = "Recalled"
        quote.save()

        logging.info(f"🟡 Quote {quote.name} has been recalled.")
        return {"message": f"🔄 Quote `{quote.name}` has been recalled and can be modified again."}

    except Quote.DoesNotExist:
        return {"message": "⚠️ Quote not found. Please provide a valid quote ID."}
    except Exception as e:
        logging.error(f"❌ Error recalling quote: {str(e)}")
        return {"message": f"⚠️ Error recalling quote: {str(e)}"}


def auto_approve_quote(quote, workflow, step):
    """Marks the quote as Auto-Approved instantly."""
    approval, created = QuoteApproval.objects.update_or_create(
        quote=quote,
        workflow=workflow,
        step=step,
        defaults={
            "status": "Approved",
            "approved_by": "System",
            "approved_at": datetime.now()
        }
    )
    quote.status = "Approved"
    quote.save()
    logging.info(f"✅ Quote `{quote.name}` Auto-Approved.")
    return {"message": f"✅ Quote `{quote.name}` Auto-Approved."}


def parse_user_message(user_message):
    """Uses OpenAI API to extract structured intent and parameters from user messages."""
    system_prompt = """
    You are an AI assistant that extracts structured data from natural language user messages.
    Your task is to analyze a given message and return a JSON object with:
    
    - "action": The type of action (e.g., "CheckApprovalStatus", "SubmitForApproval", "ApproveQuote", "RejectQuote", "RecallQuote").
    - "parameters": A dictionary of key parameters such as:
        - "quote_id" (if mentioned)
        - "status" (if a specific approval status is requested, e.g., "Pending", "Approved", "Rejected")
    
    If the action or parameters are unclear, return "action": "Unknown" and "parameters": {}.
    
    Example Input: "Check the approval status for quote Q-00032."
    Example Output:
    {
        "action": "CheckApprovalStatus",
        "parameters": {
            "quote_id": "Q-00032"
        }
    }
    
    Example Input: "What are the pending approvals for quote Q-00045?"
    Example Output:
    {
        "action": "CheckApprovalStatus",
        "parameters": {
            "quote_id": "Q-00045",
            "status": "Pending"
        }
    }
    
    Example Input: "Reject quote Q-00050 because it's missing pricing details."
    Example Output:
    {
        "action": "RejectQuote",
        "parameters": {
            "quote_id": "Q-00050",
            "reason": "Missing pricing details"
        }
    }
    """

    try:
        client = openai.OpenAI()  # ✅ Create a client instance
        response = client.chat.completions.create(  # ✅ Use the correct API format
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2
        )

        # ✅ Access the message content correctly
        parsed_response = json.loads(response.choices[0].message.content)
        return parsed_response

    except Exception as e:
        logging.error(f"❌ Error parsing user message: {str(e)}")
        return {
            "action": "Unknown",
            "parameters": {},
            "error": str(e)
        }