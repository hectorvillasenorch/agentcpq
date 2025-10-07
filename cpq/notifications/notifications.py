from .email_utils import send_notification_email
from django.contrib.auth import get_user_model
from cpq.models import EmailAlert
from django.contrib.auth.models import User

User = get_user_model()

def notify_users(alerts, instance, template_name, subject, context_builder):
    """
    Envia notificaciones de email a usuarios internos y externos.

    alerts: queryset de EmailAlert
    instance: el objeto que disparó la alerta (Lead, Account, Opportunity, etc.)
    template_name: nombre de la plantilla de email
    subject: asunto del correo
    context_builder: función que recibe (instance, user) y devuelve un dict de contexto
    """
    for alert in alerts:
        recipients = get_users_for_alert(instance, alert)

        for user in recipients["users"]:
            if not user or not user.email:
                print(f"The user {getattr(user, 'username', 'Unknown')} has no email registered.")
                continue

            print(f"Sending email to {user.username}")
            context = context_builder(instance, user)
            send_notification_email(
                recipient=user.email,
                subject=subject,
                template_name=template_name,
                context=context
            )

        for email in recipients["external_emails"]:
            print(f"Sending email to external recipient {email}")
            context = context_builder(instance, None)
            send_notification_email(
                recipient=email,
                subject=subject,
                template_name=template_name,
                context=context
            )


# LEAD CREATED
def notify_lead_created(lead):
    email_alerts = EmailAlert.objects.filter(trigger="lead_created")

    notify_users(
        alerts=email_alerts,
        instance=lead,
        template_name="lead_created",
        subject=f'📋 New Lead Created: {lead.first_name} {lead.last_name}',
        context_builder=lambda instance, user: {
            "lead": instance,
            "user": user,
        },
    )

# ACCOUNT CREATED
def notify_account_created(account):
    email_alerts = EmailAlert.objects.filter(trigger="account_created")

    notify_users(
        alerts=email_alerts,
        instance=account,
        template_name="account_created",
        subject=f'👤 New Account Created: {account.name}',
        context_builder=lambda instance, user: {
            "account": instance,
            "user": user
        }
    )


# OPPORTUNITY CREATED
def notify_opportunity_created(opportunity):
    email_alerts = EmailAlert.objects.filter(trigger="opportunity_created")

    notify_users(
        alerts=email_alerts,
        instance=opportunity,
        template_name="opportunity_created",
        subject=f'📊 New Opportunity Created: {opportunity.name}',
        context_builder=lambda instance, user: {
            "opportunity": instance,
            "user": user,
        },
    )

# OPPORTUNITY CLOSED WON
def notify_opportunity_closed_won(opportunity):
    email_alerts = EmailAlert.objects.filter(trigger="opportunity_closed_won")

    notify_users(
        alerts=email_alerts,
        instance=opportunity,
        template_name="opportunity_closed_won",
        subject=f'✅ Opportunity Closed Won: {opportunity.name}',
        context_builder=lambda instance, user: {
            "opportunity": instance,
            "user": user,
        },
    )

# OPPORTUNITY CLOSED LOST
def notify_opportunity_closed_lost(opportunity):
    email_alerts = EmailAlert.objects.filter(trigger="opportunity_closed_lost")

    notify_users(
        alerts=email_alerts,
        instance=opportunity,
        template_name="opportunity_closed_lost",
        subject=f'❌ Opportunity Closed Lost: {opportunity.name}',
        context_builder=lambda instance, user: {
            "opportunity": instance,
            "user": user,
        },
    )

# QUOTE SENT FOR APPROVAL
def notify_quote_sent_for_approval(quote):
    email_alerts = EmailAlert.objects.filter(trigger="quote_sent_for_approval")

    notify_users(
        alerts=email_alerts,
        instance=quote,
        template_name="quote_sent_for_approval",
        subject=f'📑 Quote Sent for Approval: {quote.name}',
        context_builder=lambda instance, user: {
            "quote": instance,
            "user": user,
        },
    )

# QUOTE APPROVED
def notify_quote_approved(quote):
    email_alerts = EmailAlert.objects.filter(trigger="quote_approved")

    notify_users(
        alerts=email_alerts,
        instance=quote,
        template_name="quote_approved",
        subject=f'✅ Quote Approved: {quote.name}',
        context_builder=lambda instance, user: {
            "quote": instance,
            "user": user,
        },
    )

# QUOTE REJECTED
def notify_quote_rejected(quote):
    email_alerts = EmailAlert.objects.filter(trigger="quote_rejected")

    notify_users(
        alerts=email_alerts,
        instance=quote,
        template_name="quote_rejected",
        subject=f'❌ Quote Rejected: {quote.name}',
        context_builder=lambda instance, user: {
            "quote": instance,
            "user": user,
        },
    )





def get_users_for_alert(instance, alert):
    """
    Returns a list of users (User objects) and external emails for the given alert.
    Handles recipients_users, recipients_roles, and recipients_external.
    """
    # Start with users directly selected
    users_qs = alert.recipients_users.all()
    users_set = set(users_qs)  # avoid duplicates

    # Handle roles
    if alert.recipients_roles:
        roles = alert.recipients_roles.split(",") if isinstance(alert.recipients_roles, str) else [alert.recipients_roles]

        for role in roles:
            role_users = []
            if role == "all_superusers":
                role_users = User.objects.filter(is_superuser=True)
            elif role == "all_admins":
                role_users = User.objects.filter(is_staff=True, is_superuser=False)
            elif role == "all_staff":
                role_users = User.objects.filter(is_staff=True)
            elif role == "creator":
                if hasattr(instance, "created_by") and instance.created_by:
                    role_users = [instance.created_by]

            users_set.update(role_users)

    # Handle external recipients (list of emails)
    external_emails = []
    if alert.recipients_external:
        external_emails = [email.strip() for email in alert.recipients_external.split(",") if email.strip()]

    return {
        "users": list(users_set),
        "external_emails": external_emails,
    }
