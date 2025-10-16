from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string, select_template
from django.template import TemplateDoesNotExist

def send_notification_email(recipient, subject, template_name, context):
    html_template_name = f'emails/{template_name}/{template_name}.html'
    html_content = render_to_string(html_template_name, context)

    text_template_candidates = [
        f'emails/{template_name}/{template_name}.txt',
        'emails/generic_notification.txt',
    ]

    try:
        text_template = select_template(text_template_candidates)
        text_content = text_template.render(context)
    except TemplateDoesNotExist:
        from django.utils.html import strip_tags
        text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(subject, text_content, to=[recipient])
    email.attach_alternative(html_content, "text/html")
    email.send()
