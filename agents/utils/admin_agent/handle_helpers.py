import re, json, logging
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from cpq.models import CustomObject, EmailAlert

# Session Context Helpers
from agents.utils.orchestrator.context_handle_helpers import save_or_update_conversation_context, make_session_context

# Record Helpers
from agents.utils.admin_agent.record_helpers import save_email_alert



def handle_email_alerts_creation(user, extracted_email_alerts, response_message, session_context):

    alerts_created = []

    TRIGGER_CHOICES = [
        "lead_created",
        "account_created",
        "opportunity_created",
        "opportunity_closed_won",
        "opportunity_closed_lost",
        "quote_sent_for_approval",
        "quote_approved",
        "quote_rejected",
        "quote_expiring",
        "subscription_renewal",
    ]

    NATIVE_OBJECT_CHOICES = [
        "Lead",
        "Account",
        "Opportunity",
        "Quote",
        "Subscription",
    ]

    ROLE_CHOICES = [
        "all_superusers",
        "all_admins",
        "all_staff",
        "creator",
    ]

    for index, alert in enumerate(extracted_email_alerts, start=1):
        description = alert.get("description", None)
        trigger = alert.get("trigger", None)
        native_object = alert.get("native_object", None)
        custom_object_name = alert.get("custom_object", None)

        recipients_users = alert.get("recipients_users", []) or []
        recipients_roles = alert.get("recipients_roles", []) or []
        recipients_external = alert.get("recipients_external", []) or []

        offset_days = alert.get("offset_days", None)
        scheduled_cron = alert.get("scheduled_cron", None)


        # ---- DESCRIPTION ----
        if not description:
            session_context["item_index"] = index
            session_context["extracted"] = alert
            agent_response = f"⚠️ No description specified for email alert #{index}. AgentCPQ could not infer a description."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{agent_response}<br>"
            continue

        # ---- TRIGGER ----
        if not trigger or trigger not in TRIGGER_CHOICES:
            session_context["item_index"] = index
            session_context["extracted"] = alert
            agent_response = (
                f"⚠️ The trigger '{trigger}' is not valid for email alert #{index}. "
                f"Please select one from the following list: {', '.join(TRIGGER_CHOICES)}."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{agent_response}<br>"
            continue

        # ---- OBJECT VALIDATION ----
        if not native_object and not custom_object_name:
            session_context["item_index"] = index
            session_context["extracted"] = alert
            agent_response = (
                f"⚠️ No object specified for email alert '{description}'. "
                "Please specify either a native object (Lead, Account, Opportunity, Quote, Subscription) "
                "or a custom object for this alert."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{agent_response}<br>"
            continue

        if native_object and custom_object_name:
            native_object = None

        # ---- NATIVE OBJECT ----
        if native_object and native_object not in NATIVE_OBJECT_CHOICES:
            session_context["item_index"] = index
            session_context["extracted"] = alert
            agent_response = (
                f"⚠️ The native object '{native_object}' is not valid. "
                f"Valid options are: {', '.join(NATIVE_OBJECT_CHOICES)}."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{agent_response}<br>"
            continue

        # ---- CUSTOM OBJECT ----
        if custom_object_name:
            try:
                co_obj = CustomObject.objects.get(name=custom_object_name)
            except CustomObject.DoesNotExist:
                session_context["item_index"] = index
                session_context["extracted"] = alert
                agent_response = (
                    f"⚠️ The custom object '{custom_object_name}' does not exist. "
                    f"Please select one from the existing custom objects: "
                    f"{', '.join(CustomObject.objects.values_list('name', flat=True))}."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += f"{agent_response}<br>"
                continue

        # ---- RECIPIENTS USERS ----
        if not isinstance(recipients_users, list):
            recipients_users = []

        valid_users = []
        invalid_users = []

        for username in recipients_users:
            if User.objects.filter(username=username).exists():
                valid_users.append(username)
            else:
                invalid_users.append(username)

        recipients_users = valid_users

        if invalid_users:
            response_message += (
                f"⚠️ The following users were not found in the system and will not be notified: "
                f"{', '.join(invalid_users)}.<br>"
            )

        # ---- RECIPIENTS ROLES ----
        if not isinstance(recipients_roles, list):
            recipients_roles = []

        valid_roles = [r for r in recipients_roles if r in ROLE_CHOICES]
        invalid_roles = [r for r in recipients_roles if r not in ROLE_CHOICES]

        recipients_roles = valid_roles

        if invalid_roles:
            response_message += (
                f"⚠️ The following roles are invalid and will not be notified: "
                f"{', '.join(invalid_roles)}.<br>"
            )

        # ---- RECIPIENTS EXTERNAL ----
        if not isinstance(recipients_external, list):
            recipients_external = []

        valid_external = []
        invalid_external = []

        for email in recipients_external:
            try:
                validate_email(email)
                valid_external.append(email)
            except ValidationError:
                invalid_external.append(email)

        recipients_external = valid_external

        if invalid_external:
            response_message += (
                f"⚠️ The following external emails do not have correct format and will not be included: "
                f"{', '.join(invalid_external)}.<br>"
            )

        # ---- CHECK IF ANY RECIPIENTS ----
        if not (recipients_users or recipients_roles or recipients_external):
            session_context["item_index"] = index
            session_context["extracted"] = alert
            agent_response = (
                f"⚠️ No recipients were specified for email alert '{description}', so it cannot be saved."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{agent_response}<br>"
            continue

        # ---- OFFSET DAYS ----
        if offset_days is not None:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                session_context["item_index"] = index
                session_context["extracted"] = alert
                agent_response = (
                    f"⚠️ Cannot assign <b>offset days</b> to trigger '{trigger}'. "
                    f"Valid triggers for offset_days: quote_expiring, subscription_renewal."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += f"{agent_response}<br>"
                continue

        # ---- SCHEDULED CRON ----
        if scheduled_cron:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                session_context["item_index"] = index
                session_context["extracted"] = alert
                agent_response = (
                    f"⚠️ Cannot assign <b>scheduled cron</b> to trigger '{trigger}'. "
                    f"Valid triggers for scheduled_cron: quote_expiring, subscription_renewal."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += f"{agent_response}<br>"
                continue

            if not is_valid_cron(scheduled_cron):
                session_context["item_index"] = index
                session_context["extracted"] = alert
                agent_response = (
                    f"⚠️ The cron expression '{scheduled_cron}' is not valid. "
                    "Please provide a valid 5-field cron expression (minute hour day month weekday)."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += f"{agent_response}<br>"
                continue

        # Get the latest EmailAlert based on the object
        if native_object:
            last_email_alert = EmailAlert.objects.filter(native_object=native_object).order_by('-created_at').first()
        elif custom_object_name:
            try:
                custom_obj = CustomObject.objects.get(name=custom_object_name)
                last_email_alert = EmailAlert.objects.filter(custom_object=custom_obj).order_by('-created_at').first()
            except CustomObject.DoesNotExist:
                last_email_alert = None
        else:
            last_email_alert = None

        # Build the base name from the trigger
        base_name = (trigger.lower().replace(" ", "_") if trigger else "alert")

        # Generate the new incremental number
        new_number = 1
        if last_email_alert:
            # Extract the 5-digit number at the end of the name
            match = re.search(r'__(\d{5})$', last_email_alert.name)
            if match:
                new_number = int(match.group(1)) + 1

        # Format the final name with leading zeros
        name = f"{base_name}__{new_number:05d}"

        # ---- CREATE ALERT PAYLOAD ----
        alert_payload = {
            "description": description,
            "name": name,
            "trigger": trigger,
            "native_object": native_object,
            "custom_object": custom_object_name,
            "recipients_users": recipients_users,
            "recipients_roles": recipients_roles,
            "recipients_external": recipients_external,
            "offset_days": offset_days,
            "scheduled_cron": scheduled_cron,
        }

        # Call the save function
        response = save_email_alert(json.dumps(alert_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get("message")}<br><br>"
            alerts_created.append(alert_payload)
            agent_response = f"The custom field was or were created successfully, but the user wants to create a new one. You can see the custom object on previous extracted data."
            session_context["extracted"] = {"custom_object_name": custom_object_name}
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to create custom field. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, alerts_created


def is_valid_cron(cron_str):
    """Simple regex to check 5-field cron format (minute, hour, day, month, weekday)."""
    cron_regex = r'^(\S+\s){4}\S+$'
    return re.match(cron_regex, cron_str)