from django.contrib import admin
from django.urls import path, include
from agents.views import agents_chat, chat_with_gpt

urlpatterns = [
    path('dashboard/', include('dashboard.urls')),
    path('agents/', include('agents.urls')),  
    path('cpq/', include('cpq.urls')), 
]
