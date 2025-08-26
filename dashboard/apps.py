from django.apps import AppConfig

class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'

    def ready(self):
        # Inline receiver registration (no external import)
        from django.contrib.auth.signals import user_logged_in
        from django.dispatch import receiver
        from django.apps import apps as django_apps
        from django.utils import timezone

        @receiver(user_logged_in)
        def _greet_user_on_login(sender, user, request, **kwargs):
            ChatSession = django_apps.get_model('agents', 'ChatSession')
            ChatMessage = django_apps.get_model('agents', 'ChatMessage')

            session = (ChatSession.objects
                       .filter(user=user)
                       .order_by('-updated_at')
                       .first())
            if not session:
                session = ChatSession.objects.create(user=user, title='Welcome session')

            first = user.first_name or user.username
            ChatMessage.objects.create(
                session=session,
                role='system',
                content=f"Welcome back, {first}! 👋 How can I help with your quote today?",
                created_at=timezone.now(),
            )