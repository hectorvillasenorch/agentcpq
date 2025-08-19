from cpq.models import BusinessRule, CustomObject, EmailAlert
from django.contrib.auth.models import User
from django.db import transaction
import logging
import json

def update_rule_record(update_request):
    try:
        rule = update_request.get("rule", None)
        field = update_request.get("field", None)
        new_value = update_request.get("value", None)

        # ✅ Update based on the field dynamically
        string_fields = ["rule_type", "target_type", "error_message", "description"]

        if field in string_fields:
            setattr(rule, field, str(new_value))
        elif field == "priority":
            setattr(rule, field, int(new_value))
        elif field == "active":
            setattr(rule, field, bool(new_value))
        elif field == "conditions":
            setattr(rule, field, new_value)

        rule.save()

        response_message = "✅ Rule updated successfully."

        return {
            "message": response_message,
            "success": True
        }
    
    except ValueError as ve:
        return {
            "message": str(ve),
            "success": False
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating rule: {str(e)}")
        return {
            "message": f"Error updating rule: {str(e)}",
            "success": False
        }

    
def save_email_alert(payload_json, user=None):
    """
    Save an EmailAlert instance based on the payload.
    payload_json: JSON string con los campos normalizados de la alerta
    user: usuario que está creando la alerta
    """
    try:
        data = json.loads(payload_json)

        description = data.get("description")
        name = data.get("name")
        trigger = data.get("trigger")
        native_object = data.get("native_object")
        custom_object_name = data.get("custom_object")
        recipients_users_list = data.get("recipients_users", [])
        recipients_roles = data.get("recipients_roles", [])
        recipients_external = data.get("recipients_external", [])
        offset_days = data.get("offset_days")
        scheduled_cron = data.get("scheduled_cron")

        # Buscar el custom object si aplica
        custom_object = None
        if custom_object_name:
            try:
                custom_object = CustomObject.objects.get(name=custom_object_name)
            except CustomObject.DoesNotExist:
                logging.warning(f"⚠️ Custom object '{custom_object_name}' does not exist.")
                custom_object = None

        with transaction.atomic():
            email_alert = EmailAlert.objects.create(
                description=description,
                name=name,
                trigger=trigger,
                native_object=native_object,
                custom_object=custom_object,
                recipients_roles=",".join(recipients_roles) if recipients_roles else None,
                recipients_external=",".join(recipients_external) if recipients_external else None,
                offset_days=offset_days,
                scheduled_cron=scheduled_cron,
                created_by=user,
                updated_by=user
            )

            # Asociar usuarios ManyToMany
            if recipients_users_list:
                users_qs = User.objects.filter(username__in=recipients_users_list)
                email_alert.recipients_users.set(users_qs)

        return {
            "message": f"✅ Email alert '{description}' created successfully. Trigger: {trigger}, Object: {native_object or custom_object_name}",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error creating email alert (save_email_alert function): {str(e)}")
        return {
            "message": f"❌ Error creating email alert: {str(e)}",
            "success": False
        }