import re, json, logging
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from cpq.models import CustomObject, EmailAlert, Product
from django.utils.html import escape
from cpq.models import BusinessRule
from django.db.models import Q

# Record Helpers
from agents.utils.admin_agent.record_helpers import save_email_alert, update_email_alert_record, delete_email_alert_record



def handle_email_alerts_creation(user, extracted_email_alerts, response_message):

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
        "user_created",
        "opportunity_greater_than_10k",
        "quote_discount_greater_than_50"
    ]

    NATIVE_OBJECT_CHOICES = [
        "Lead",
        "Account",
        "Opportunity",
        "Quote",
        "Subscription",
        "Product",
        "QuoteLine",
        "User",
        "Contract",
        "Subscription",
        "Contact",
        "Activity"
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
            agent_response = f"⚠️ No description specified for email alert #{index}. AgentCPQ could not infer a description."
            #alerts_created.append(f"{agent_response}<br>")
            logging.warning(agent_response)
            response_message += agent_response
            continue

        # ---- TRIGGER ----
        if not trigger or trigger not in TRIGGER_CHOICES:
            safe_trigger = escape(trigger or "")
            agent_response = (
                f"⚠️ The trigger '{safe_trigger}' is not valid for email alert #{index}. " # nosec B608
                f"Please select one from the following list: {', '.join(escape(t) for t in TRIGGER_CHOICES)}." # nosec B608
            )
            alerts_created.append(f"{agent_response}<br>")
            logging.warning(f"Invalid trigger received: {trigger}")  # Hard for logs
            response_message += agent_response
            continue

        # ---- OBJECT VALIDATION ----
        if not native_object and not custom_object_name:
            agent_response = (
                f"⚠️ No object specified for email alert '{description}'. "
                "Please specify either a native object (Lead, Account, Opportunity, Quote, Subscription) "
                "or a custom object for this alert."
            )
            alerts_created.append(f"{agent_response}<br>")
            logging.warning(agent_response)
            response_message += agent_response

            continue

        if native_object and custom_object_name:
            native_object = None

        # ---- NATIVE OBJECT ----
        if native_object and native_object not in NATIVE_OBJECT_CHOICES:
            safe_native_object = escape(native_object or "")
            agent_response = (
                f"⚠️ The native object '{safe_native_object}' is not valid. "
                f"Valid options are: {', '.join(escape(o) for o in NATIVE_OBJECT_CHOICES)}."
            )
            alerts_created.append(f"{agent_response}<br>")
            logging.warning(agent_response)
            response_message += agent_response

            continue

        # ---- CUSTOM OBJECT ----
        if custom_object_name:
            try:
                co_obj = CustomObject.objects.get(name=custom_object_name)
            except CustomObject.DoesNotExist:
                safe_custom_object = escape(custom_object_name or "")
                agent_response = (
                    f"⚠️ The custom object '{safe_custom_object}' does not exist. " # nosec B608
                    f"Please select one from the existing custom objects: " # nosec B608
                    f"{', '.join(escape(name) for name in CustomObject.objects.values_list('name', flat=True))}." # nosec B608
                )
                alerts_created.append(f"{agent_response}<br>")
                response_message += agent_response

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
            agent_response = (
                f"⚠️ The following users were not found in the system and will not be notified: "
                f"{', '.join(escape(u) for u in invalid_users)}.<br>"
            )
            alerts_created.append(agent_response)
            response_message += agent_response

        # ---- RECIPIENTS ROLES ----
        if not isinstance(recipients_roles, list):
            recipients_roles = []

        valid_roles = [r for r in recipients_roles if r in ROLE_CHOICES]
        invalid_roles = [r for r in recipients_roles if r not in ROLE_CHOICES]

        recipients_roles = valid_roles

        if invalid_roles:
            agent_response = (
                f"⚠️ The following roles are invalid and will not be notified: "
                f"{', '.join(escape(u) for u in invalid_roles)}.<br>"
            )
            alerts_created.append(agent_response)
            response_message += agent_response

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
            agent_response = (
                f"⚠️ The following external emails do not have correct format and will not be included: "
                f"{', '.join(escape(e) for e in invalid_external)}.<br>"
            )

            alerts_created.append(agent_response)
            response_message += agent_response

        # ---- CHECK IF ANY RECIPIENTS ----
        if not (recipients_users or recipients_roles or recipients_external):
            agent_response = (
                f"⚠️ No recipients were specified for email alert '{description}', so it cannot be saved."
            )
            alerts_created.append(f"{agent_response}<br>")
            response_message += agent_response

            continue

        # ---- OFFSET DAYS ----
        if offset_days is not None:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                agent_response = (
                    f"⚠️ Cannot assign <b>offset days</b> to trigger '{trigger}'. "
                    f"Valid triggers for offset_days: quote_expiring, subscription_renewal."
                )
                alerts_created.append(f"{agent_response}<br>")
                response_message += agent_response

                continue

        # ---- SCHEDULED CRON ----
        if scheduled_cron:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                agent_response = (
                    f"⚠️ Cannot assign <b>scheduled cron</b> to trigger '{trigger}'. "
                    f"Valid triggers for scheduled_cron: quote_expiring, subscription_renewal."
                )
                alerts_created.append(f"{agent_response}<br>")
                response_message += agent_response

                continue

            if not is_valid_cron(scheduled_cron):
                safe_cron = escape(scheduled_cron or "")
                agent_response = (
                    f"⚠️ The cron expression '{safe_cron}' is not valid. "
                    "Please provide a valid 5-field cron expression (minute hour day month weekday)."
                )
                alerts_created.append(f"{agent_response}<br>")
                response_message += agent_response

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
            # Extract the 3-digit number at the end of the name
            match = re.search(r'__(\d{3})$', last_email_alert.name)
            if match:
                new_number = int(match.group(1)) + 1

        # Format the final name with leading zeros (3 digits)
        name = f"{base_name}__{new_number:03d}"

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

            alerts_created.extend(get_email_details(response["email_details"]))

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            alerts_created.append(f"{error_msg}<br>")

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, alerts_created

def handle_email_alerts_updates(user, extracted_email_alerts_updates, response_message):

    alerts_updated = []

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

    for index, alert in enumerate(extracted_email_alerts_updates, start=1):
        alert_name = alert.get("alert_name", None)

        # ---- ALERT NAME ----
        if not alert_name:
            agent_response = f"⚠️ No alert_name specified for email alert #{index}. AgentCPQ could not determine which alert to update."
            response_message += f"{agent_response}<br>"

            continue

        try:
            email_alert_to_update = EmailAlert.objects.get(name=alert_name)
        except EmailAlert.DoesNotExist:
            agent_response = f"⚠️ The email alert with alert_name '{alert_name}' does not exist in the database. AgentCPQ cannot update it."
            response_message += f"{agent_response}<br>"

            continue


        description = alert.get("description", None)
        trigger = alert.get("trigger", None)
        native_object = alert.get("native_object", None)
        custom_object_name = alert.get("custom_object", None)

        offset_days = alert.get("offset_days", None)
        scheduled_cron = alert.get("scheduled_cron", None)


        # ---- TRIGGER ----
        if trigger and trigger not in TRIGGER_CHOICES:
            safe_trigger = escape(trigger)
            safe_choices = ", ".join(escape(t) for t in TRIGGER_CHOICES)
            agent_response = (
                f"⚠️ The trigger '{safe_trigger}' is not valid for email alert #{index}. " # nosec B608
                f"Please select one from the following list: {safe_choices}." # nosec B608
            )
            response_message += f"{agent_response}<br>"

            continue

        # ---- NATIVE OBJECT ----
        if native_object and native_object not in NATIVE_OBJECT_CHOICES:
            agent_response = (
                f"⚠️ The native object '{native_object}' is not valid. "
                f"Valid options are: {', '.join(NATIVE_OBJECT_CHOICES)}."
            )
            response_message += f"{agent_response}<br>"

            continue

        # ---- CUSTOM OBJECT ----
        if custom_object_name:
            try:
                co_obj = CustomObject.objects.get(name=custom_object_name)
            except CustomObject.DoesNotExist:
                # Get the custom object names as a list (force evaluation)
                names = list(CustomObject.objects.values_list("name", flat=True))

                # Escape to prevent XSS when displaying in HTML
                safe_names = ", ".join(escape(n) for n in names)
                safe_custom_object_name = escape(custom_object_name)

                # bandit: disable=B608 - false positive: this is message formatting, not SQL construction
                agent_response = (
                    f"⚠️ The custom object '{safe_custom_object_name}' does not exist. " # nosec B608
                    f"Please select one from the existing custom objects: {safe_names}." # nosec B608
                )

                response_message += f"{agent_response}<br>"

                continue

        # ---- RECIPIENTS ----
        recipients_list = alert.get("recipients", None)

        # Inicializamos todas las listas vacías
        remove_users, remove_roles, remove_externals = [], [], []
        add_users, add_roles, add_externals = [], [], []

        # Diccionario para normalizar los roles
        ROLE_NORMALIZATION_MAP = {
            "superadmins": "all_superusers",
            "superusers": "all_superusers",
            "admins": "all_admins",
            "staff": "all_staff",
            "creator": "creator",
        }

        if recipients_list:
            # Validar action
            action = recipients_list.get("action", None)
            if action not in ["add", "remove", "replace"]:
                agent_response = (
                    f"⚠️ Invalid recipients action '{action}' for email alert '{alert_name}'. "
                    f"Valid options are: add, remove, replace."
                )
                response_message += f"{agent_response}<br>"
                continue

            # ---- REMOVE ----
            remove_block = recipients_list.get("remove", {})
            remove_users_raw = remove_block.get("users", [])
            remove_roles_raw = remove_block.get("roles", [])
            remove_externals_raw = remove_block.get("externals", [])


            # Validación de usuarios
            for username in remove_users_raw:
                if User.objects.filter(username=username).exists():
                    remove_users.append(username)
                else:
                    response_message += f"⚠️ User '{username}' to remove does not exist.<br>"

            # Normalizar y validar roles
            normalized_remove_roles = [ROLE_NORMALIZATION_MAP.get(r.lower(), r) for r in remove_roles_raw]
            remove_roles = [r for r in normalized_remove_roles if r in ROLE_CHOICES]
            invalid_remove_roles = [r for r in normalized_remove_roles if r not in ROLE_CHOICES]
            if invalid_remove_roles:
                response_message += (
                    f"⚠️ The following roles to remove are invalid: {', '.join(invalid_remove_roles)}.<br>"
                )

            # Validación de emails externos
            for email in remove_externals_raw:
                try:
                    validate_email(email)
                    remove_externals.append(email)
                except ValidationError:
                    response_message += f"⚠️ External email '{email}' to remove is invalid.<br>"

            # ---- ADD ----
            add_block = recipients_list.get("add", {})
            add_users_raw = add_block.get("users", [])
            add_roles_raw = add_block.get("roles", [])
            add_externals_raw = add_block.get("externals", [])

            # Validación de usuarios
            for username in add_users_raw:
                if User.objects.filter(username=username).exists():
                    add_users.append(username)
                else:
                    response_message += f"⚠️ User '{username}' to add does not exist.<br>"

            # Normalizar y validar roles
            normalized_add_roles = [ROLE_NORMALIZATION_MAP.get(r.lower(), r) for r in add_roles_raw]
            add_roles = [r for r in normalized_add_roles if r in ROLE_CHOICES]
            invalid_add_roles = [r for r in normalized_add_roles if r not in ROLE_CHOICES]
            if invalid_add_roles:
                response_message += (
                    f"⚠️ The following roles to add are invalid: {', '.join(invalid_add_roles)}.<br>"
                )

            # Validación de emails externos
            for email in add_externals_raw:
                try:
                    validate_email(email)
                    add_externals.append(email)
                except ValidationError:
                    response_message += f"⚠️ External email '{email}' to add is invalid.<br>"


        # ---- OFFSET DAYS ----
        if offset_days is not None:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                agent_response = (
                    f"⚠️ Cannot assign <b>offset days</b> to trigger '{trigger}'. "
                    f"Valid triggers for offset_days: quote_expiring, subscription_renewal."
                )
                response_message += f"{agent_response}<br>"

                continue

        # ---- SCHEDULED CRON ----
        if scheduled_cron is not None:
            if trigger not in ["quote_expiring", "subscription_renewal"]:
                agent_response = (
                    f"⚠️ Cannot assign <b>scheduled cron</b> to trigger '{trigger}'. "
                    f"Valid triggers for scheduled_cron: quote_expiring, subscription_renewal."
                )
                response_message += f"{agent_response}<br>"

                continue

            if not is_valid_cron(scheduled_cron):
                agent_response = (
                    f"⚠️ The cron expression '{scheduled_cron}' is not valid. "
                    "Please provide a valid 5-field cron expression (minute hour day month weekday)."
                )
                response_message += f"{agent_response}<br>"

                continue


        # ---- CREATE ALERT PAYLOAD ----
        alert_payload = {
            "alert_name": alert_name,
            "description": description,
            "trigger": trigger,
            "native_object": native_object,
            "custom_object": custom_object_name,
            "offset_days": offset_days,
            "scheduled_cron": scheduled_cron,
            "active": alert.get("active", None),
            "remove_users": remove_users,
            "remove_roles": remove_roles,
            "remove_externals": remove_externals,
            "add_users": add_users,
            "add_roles": add_roles,
            "add_externals": add_externals
        }


        # Call the save function
        response = update_email_alert_record(json.dumps(alert_payload), user= user)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            alerts_updated.append(alert_payload)

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, alerts_updated

def handle_email_alerts_deletes(extracted_email_alerts_deletes, response_message):

    alerts_deleted = []


    for index, alert in enumerate(extracted_email_alerts_deletes, start=1):
        alert_name = alert.get("alert_name", None)

        # ---- ALERT NAME ----
        if not alert_name:
            agent_response = f"⚠️ No alert_name specified for email alert #{index}. AgentCPQ could not determine which alert to update."
            response_message += f"{agent_response}<br>"

            continue

        try:
            email_alert_to_delete = EmailAlert.objects.get(name=alert_name)
        except EmailAlert.DoesNotExist:
            agent_response = f"⚠️ The email alert with alert_name '{alert_name}' does not exist in the database. AgentCPQ cannot update it."
            response_message += f"{agent_response}<br>"

            continue


        # ---- CREATE ALERT PAYLOAD ----
        alert_payload = {
            "alert_name": alert_name
        }


        # Call the save function
        response = delete_email_alert_record(json.dumps(alert_payload))

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            alerts_deleted.append(alert_payload)

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"{error_msg}<br>"

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, alerts_deleted


def get_email_details(email):

    email_details_dict = []


    email_details_dict.append({
        "name": email.name if email.name else None,
        "description": email.description if email.description else None,
        "trigger": email.trigger if email.trigger else None,
        "native_object": email.native_object if email.native_object else None,
        "custom_object": email.custom_object.label if getattr(email, "custom_object", None) else None,
        "recipients_users": [user.username for user in email.recipients_users.all()] if hasattr(email, "recipients_users") else [],
        "recipients_roles": email.recipients_roles.split(",") if email.recipients_roles else [],
        "recipients_external": email.recipients_external.split(",") if email.recipients_external else [],
        "offset_days": email.offset_days if email.offset_days is not None else 0,
        "scheduled_cron": email.scheduled_cron if email.scheduled_cron else None,
        "active": email.active if email.active is not None else False,
        "created_at": email.created_at.strftime("%m/%d/%Y") if email.created_at else None,
        "created_by": email.created_by.username if getattr(email, "created_by", None) else None,
        "success": True
    })

    return email_details_dict


def is_valid_cron(cron_str):
    """Simple regex to check 5-field cron format (minute, hour, day, month, weekday)."""
    cron_regex = r'^(\S+\s){4}\S+$'
    return re.match(cron_regex, cron_str)


def handle_create_inclusion_rule(user, completed_rules, response_message):

    saved_rules = []

    for index, item in enumerate(completed_rules, start=1):
        try:
            description = item["description"]
            rule_type = item["rule_type"]
            target_type = item["target_type"]
            priority = item["priority"]
            message = item["message"]
            active = item["active"]
            conditions = item["conditions"]
        except Exception as e:
            return {
                "message": f"🚫 Error: {e}"
            }

        # DESCRIPTION: must be a string
        if not description:
            error = "⚠️ Missing rule description: No description was provided for this rule. Please include a descriptive description to identify it clearly."
            response_message += error
            logging.warning(error)

            continue

        # RULE_TYPE: must be a string and one of the allowed values
        if not rule_type:
            error = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            response_message += error
            logging.warning(error)

            continue

        if rule_type != "inclusion":
            error = "⚠️ Invalid rule type: the rule type must be 'inclusion'."
            response_message += error
            logging.warning(error)

            continue

        # TARGET_TYPE: must be a string and one of the allowed values
        valid_target_types = {"quote", "quote_line", "product", "multiple"}
        if not target_type:
            error = "⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            response_message += error
            logging.warning(error)

            continue

        target_type_lower = target_type.lower()

        if target_type_lower not in valid_target_types:
            error = f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            response_message += error
            logging.warning(error)

            continue

        target_type = target_type_lower

        # PRIORITY: must be an integer
        if priority is None:
            error = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
            response_message += error
            logging.warning(error)

            continue

        # ERROR_MESSAGE: must be a string
        if not message:
            error = "⚠️ Missing message: Please include a message that describes what should happen when the rule is triggered."
            response_message += error
            logging.warning(error)

            continue

        # CONDITIONS: must be a dict (object)
        if not conditions:
            error = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            response_message += error
            logging.warning(error)
            continue


        logging.info(f"\n✅ LLM returned a valid rule JSON. Ready to save the rule {description} to the database.")

        try:
            rule = BusinessRule.objects.create(
                description=description,
                rule_type=rule_type,
                target_type=target_type,
                priority=priority,
                error_message=message,
                active=active,
                conditions=conditions,  # conditions JSON
                created_by=user
            )

            # Set rule's name
            rule.name = f"IR-{rule.id:05d}"
            rule.save()
            saved_rules.append(rule)

            success = f"✅ Inclusion rule '{rule.name}' ('{rule.description}') saved successfully with ID {rule.id}.<br>"

            response_message += success
            logging.info(success)

        except Exception as e:
            error = f"❌ Error saving rule to database: {str(e)}"
            response_message += error
            logging.error(error)

            continue


    return response_message, saved_rules


def handle_create_exclusion_rule(user, completed_rules, response_message):

    saved_rules = []

    for index, item in enumerate(completed_rules, start=1):
        try:
            description = item["description"]
            rule_type = item["rule_type"]
            target_type = item["target_type"]
            priority = item["priority"]
            error_message = item["error_message"]
            active = item["active"]
            conditions = item["conditions"]
        except Exception as e:
            return {
                "message": f"🚫 Error: {e}"
            }

        # DESCRIPTION: must be a string
        if not description:
            error = "⚠️ Missing rule description: No description was provided for this rule. Please include a descriptive description to identify it clearly."
            response_message += error
            logging.warning(error)

            continue

        # RULE_TYPE: must be a string and one of the allowed values
        if not rule_type:
            error = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            response_message += error
            logging.warning(error)

            continue

        if rule_type != "exclusion":
            error = "⚠️ Invalid rule type: the rule type must be 'exclusion'."
            response_message += error
            logging.warning(error)

            continue

        # TARGET_TYPE: must be a string and one of the allowed values
        valid_target_types = {"quote", "quote_line", "product", "multiple"}
        if not target_type:
            error = "⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            response_message += error
            logging.warning(error)

            continue

        target_type_lower = target_type.lower()

        if target_type_lower not in valid_target_types:
            error = f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            response_message += error
            logging.warning(error)

            continue

        target_type = target_type_lower

        # PRIORITY: must be an integer
        if priority is None:
            error = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
            response_message += error
            logging.warning(error)

            continue

        # ERROR_MESSAGE: must be a string
        if not error_message:
            error = "⚠️ Missing error message: Please include an error message that describes what should happen when the rule is triggered."
            response_message += error
            logging.warning(error)

            continue

        # CONDITIONS: must be a dict (object)
        if not conditions:
            error = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            response_message += error
            logging.warning(error)
            continue


        logging.info(f"\n✅ LLM returned a valid rule JSON. Ready to save the rule {description} to the database.")

        excluded_products = conditions.get("excluded_products")

        valid_excluded_products = []

        for excluded_product in excluded_products:
            product_query = Product.objects.filter(
                Q(name=excluded_product) | Q(sku=excluded_product)
            ).first()

            if not product_query:
                error = f"⚠️ Excluded product '{excluded_product}' not found in the catalog. It was removed from the list.<br>"
                response_message = (response_message or "") + error
                logging.warning(error)
            else:
                valid_excluded_products.append(excluded_product)


        # Reasignar la lista limpia a conditions
        conditions["excluded_products"] = valid_excluded_products

        # Si la lista quedó vacía después de validar, cancelar toda la regla
        if not valid_excluded_products:
            error = "⚠️ Exclusion rule creation cancelled: No valid excluded products remain.<br>"
            response_message = (response_message or "") + error
            logging.warning(error)
            continue  # Saltar a la siguiente regla

        try:
            rule = BusinessRule.objects.create(
                description=description,
                rule_type=rule_type,
                target_type=target_type,
                priority=priority,
                error_message=error_message,
                active=active,
                conditions=conditions,  # conditions JSON
                created_by=user
            )

            # Set rule's name
            rule.name = f"ER-{rule.id:05d}"
            rule.save()
            saved_rules.append(rule)

            success = f"✅ Exclusion rule '{rule.name}' ('{rule.description}') saved successfully.<br>"

            response_message += success
            logging.info(success)

        except Exception as e:
            error = f"❌ Error saving rule to database: {str(e)}"
            response_message += error
            logging.error(error)

            continue


    return response_message, saved_rules
