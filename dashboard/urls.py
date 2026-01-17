from django.urls import path
from .views import (
    dashboard,
    get_tenant_usage,
    update_chat_session_title,
    delete_chat_session,
    custom_records_api,
)
from agents.views import agents_chat, chat_with_gpt  # ✅ Fix: Import from `agents.views`
from django.urls import path

urlpatterns = [
    path('', dashboard, name='dashboard'),  # ✅ Loads the dashboard
    path('agents/', agents_chat, name='dashboard-agents'),  # ✅ Loads agents.html inside dashboard
    path('agents/chat/', chat_with_gpt, name='chat_with_gpt'),  # ✅ Fix: Ensure chat API exists
    path('chat/session/<str:session_id>/title/', update_chat_session_title, name='update_chat_session_title'),
    path('chat/session/<str:session_id>/delete/', delete_chat_session, name='delete_chat_session'),
    path('custom-records/', custom_records_api, name='dashboard-custom-records'),
]
