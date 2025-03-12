from django.contrib import admin
from django.urls import path, include
from agents.views import agents_chat, chat_with_gpt
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('dashboard/', include('dashboard.urls')),
    path('agents/', include('agents.urls')),  
    path('cpq/', include('cpq.urls')), 
    path("salesforce/", include("salesforce.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
