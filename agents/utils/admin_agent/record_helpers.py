from cpq.models import BusinessRule, CustomObject, EmailAlert
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
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
    

def update_email_alert_record(payload_json, user=None):
    """
    Update an EmailAlert instance based on the payload.
    payload_json: JSON string con los campos normalizados de la alerta
    user: usuario que está creando la alerta
    """
    try:
        data = json.loads(payload_json)
    except json.JSONDecodeError as e:
        logging.warning(f"⚠️ Error updating email alert (update_email_alert function): {str(e)}")
        return {
            "message": f"❌ Error updating email alert: {str(e)}",
            "success": False
        }
    
    

    alert_name = data.get("alert_name")
    if not alert_name:
        return {"message": "⚠️ 'alert_name' is required", "success": False}

    try:
        alert = EmailAlert.objects.get(name=alert_name)
    except EmailAlert.DoesNotExist:
        logging.warning(f"⚠️ Email alert '{alert_name}' does not exist.")
        return {
            "message": f"⚠️ Email alert '{alert_name}' does not exist.",
            "success": False
        }

    # Campos generales
    description = data.get("description")
    trigger = data.get("trigger")
    native_object = data.get("native_object")
    custom_object_name = data.get("custom_object")
    offset_days = data.get("offset_days")
    scheduled_cron = data.get("scheduled_cron")
    active = data.get("active")

    # Recipients
    remove_users = data.get("remove_users") or []
    remove_roles = data.get("remove_roles") or []
    remove_externals = data.get("remove_externals") or []
    add_users = data.get("add_users") or []
    add_roles = data.get("add_roles") or []
    add_externals = data.get("add_externals") or []

    # Resolver custom object si viene
    custom_object = None
    if custom_object_name:
        try:
            custom_object = CustomObject.objects.get(name=custom_object_name)
        except CustomObject.DoesNotExist:
            logging.warning(f"⚠️ Custom object '{custom_object_name}' does not exist.")
            custom_object = None

    with transaction.atomic():
        # ---- Actualizar campos básicos ----
        if description is not None:
            alert.description = description
        if trigger is not None:
            alert.trigger = trigger
        if native_object is not None:
            alert.native_object = native_object
        if custom_object is not None:
            alert.custom_object = custom_object
        if active is not None:
            alert.active = active
        if offset_days is not None:
            alert.offset_days = offset_days
        if scheduled_cron is not None:
            alert.scheduled_cron = scheduled_cron

        # ---- Remove Users ----
        for username in remove_users:
            try:
                u = User.objects.get(username=username)
                alert.recipients_users.remove(u)
            except User.DoesNotExist:
                logging.warning(f"⚠️ User '{username}' not found, cannot remove.")

        # ---- Add Users ----
        for username in add_users:
            try:
                u = User.objects.get(username=username)
                alert.recipients_users.add(u)
            except User.DoesNotExist:
                logging.warning(f"⚠️ User '{username}' not found, cannot add.")

        # ---- Remove Roles ----
        if alert.recipients_roles:
            current_roles = set(alert.recipients_roles.split(",")) if alert.recipients_roles else set()
            current_roles -= set(remove_roles)
            alert.recipients_roles = ",".join(current_roles) if current_roles else None

        # ---- Add Roles ----
        if add_roles:
            current_roles = set(alert.recipients_roles.split(",")) if alert.recipients_roles else set()
            valid_roles = [r for r in add_roles if r in dict(EmailAlert.ROLE_CHOICES)]
            current_roles |= set(valid_roles)
            alert.recipients_roles = ",".join(current_roles)

        # ---- Remove Externals ----
        current_externals = set(alert.recipients_external.split(",")) if alert.recipients_external else set()
        current_externals -= set(remove_externals)
        alert.recipients_external = ",".join(current_externals) if current_externals else None

        # ---- Add Externals ----
        for email in add_externals:
            try:
                validate_email(email)
                current_externals.add(email)
            except ValidationError:
                logging.warning(f"⚠️ Invalid external email format '{email}', skipping.")
        alert.recipients_external = ",".join(current_externals) if current_externals else None

        # ---- updated_by ----
        if user:
            alert.updated_by = user

        alert.save()

        return {
            "message": f"✅ Email alert '{alert.name}' updated successfully.",
            "success": True
        }
