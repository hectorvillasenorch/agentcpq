from django.urls import path
from .views import chat_with_gpt

urlpatterns = [
    path("chat/", chat_with_gpt, name="chat_with_gpt"), 
]