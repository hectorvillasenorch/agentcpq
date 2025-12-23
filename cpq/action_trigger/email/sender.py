from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist

from cpq.action_trigger.email.exceptions import EmailSendError

TEMPLATE_ALIASES = {
    "default": "generic_email_template"
}


def send_email(*, template, subject, recipients, context):
    try:
        html_body = render_template(template, context)

        reply_to = getattr(settings, "DEFAULT_REPLY_TO", None)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=list(recipients),
            reply_to=[reply_to] if reply_to else None,
        )

        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)

    except Exception as e:
        raise EmailSendError(f"SMTP error: {str(e)}")


def render_template(template, context):
    """
    Renderiza templates/emails/<template>.html
    Aplica aliases internos (default → generic_email_template)
    """
    resolved_template = TEMPLATE_ALIASES.get(template, template)
    template_path = f"emails/{resolved_template}.html"

    try:
        return render_to_string(template_path, context)
    except TemplateDoesNotExist:
        # Fallback seguro (no rompe engine)
        return (
            f"{context.get('title', 'Notification')}\n\n"
            f"{context.get('message', '')}\n\n"
            f"Record ID: {context.get('record', {}).get('pk')}"
        )