from django.urls import path
from .views import dashboard, get_tenant_usage
from agents.views import agents_chat, chat_with_gpt  # ✅ Fix: Import from `agents.views`
from django.urls import path

urlpatterns = [
    path('', dashboard, name='dashboard'),  # ✅ Loads the dashboard
    path('agents/', agents_chat, name='dashboard-agents'),  # ✅ Loads agents.html inside dashboard
    path('agents/chat/', chat_with_gpt, name='chat_with_gpt'),  # ✅ Fix: Ensure chat API exists 
]