from .email_utils import send_notification_email
from django.contrib.auth import get_user_model
from cpq.models import EmailAlert
from django.contrib.auth.models import User

User = get_user_model()


def notify_lead_created(lead):
    email_alerts = EmailAlert.objects.filter(trigger="lead_created")

    for alert in email_alerts:
        all_users = get_users_for_alert(lead, alert)

        for user in all_users:
            if not user or not user.email:
                print(f"The user {user.username if user else 'None'} does not have an email registered, so their notification could not be sent.")
                continue

            print(f"Enviando email a {user.username}")
            context = {
                'lead': lead,
                'user': user
            }
            send_notification_email(
                recipient=user.email,
                subject=f'📋 New Lead Created: {lead.first_name} {lead.last_name} 📋',
                template_name='lead_created',
                context=context
            )


def notify_account_created(account):
    email_alerts = EmailAlert.objects.filter(trigger="account_created")

    for alert in email_alerts:
        all_users = get_users_for_alert(account, alert)

        for user in all_users:
            if not user or not user.email:
                print(f"The user {user.username if user else 'None'} does not have an email registered, so their notification could not be sent.")
                continue

            print(f"Enviando email a {user.username}")
            context = {
                'account': account,
                'user': user
            }
            send_notification_email(
                recipient=user.email,
                subject=f'👤 New Account Created: {account.name} 👤',
                template_name='account_created',
                context=context
            )
        

def notify_opportunity_created(opportunity):
    email_alerts = EmailAlert.objects.filter(trigger="account_created")

    for alert in email_alerts:
        all_users = get_users_for_alert(opportunity, alert)

        for user in all_users:
            if not user or not user.email:
                print(f"The user {user.username if user else 'None'} does not have an email registered, so their notification could not be sent.")
                continue

            print(f"Enviando email a {user.username}")
            context = {
                'opportunity': opportunity,
                'user': user,
            }
            send_notification_email(
                recipient=user.email,
                subject=f'💼 New Opportunity Created: {opportunity.name} 💼',
                template_name='opportunity_created',
                context=context
            )

    


def get_users_for_alert(instance, alert):
    """
    Returns a list of users for the given alert and instance (Lead, Account, etc.).
    Handles both recipients_users and recipients_roles without duplicates.
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

    return list(users_set)