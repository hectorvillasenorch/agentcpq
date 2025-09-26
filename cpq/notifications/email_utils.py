from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

def send_notification_email(recipient, subject, template_name, context):
    html_content = render_to_string(f'emails/{template_name}/{template_name}.html', context)
    text_content = render_to_string(f'emails/{template_name}/{template_name}.txt', context)

    email = EmailMultiAlternatives(subject, text_content, to=[recipient])
    email.attach_alternative(html_content, "text/html")
    email.send()
