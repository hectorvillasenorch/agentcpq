from .email_utils import send_notification_email
from django.contrib.auth import get_user_model

User = get_user_model()

def notify_quote_approved(user_email, quote):
    context = {
        'quote': quote,
        'user': quote.user,
        'approval_date': quote.approved_at,
    }
    send_notification_email(
        recipient=user_email,
        subject='Your quote has been approved!',
        template_name='quote_approved',
        context=context
    )

def notify_account_created(account):
    superusers = User.objects.filter(is_superuser=True, email__isnull=False).exclude(email='') # Send email to all superusers

    for admin in superusers:
        context = {
            'account': account,
            'user': admin,
        }
        send_notification_email(
            recipient=admin.email,
            subject=f'👤 New Account Created: {account.name} 👤',
            template_name='account_created',
            context=context
        )

def notify_opportunity_created(opportunity):
    superusers = User.objects.filter(is_superuser=True, email__isnull=False).exclude(email='') # Send email to all superusers

    for admin in superusers:
        context = {
            'opportunity': opportunity,
            'user': admin,
        }
        send_notification_email(
            recipient=admin.email,
            subject=f'💼 New Opportunity Created: {opportunity.name} 💼',
            template_name='opportunity_created',
            context=context
        )