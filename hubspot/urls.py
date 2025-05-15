from django.urls import path
from . import views

urlpatterns = [
    path('oauth/callback/', views.hubspot_callback, name='hubspot_callback'),
    path('webhook/', views.hubspot_webhook, name='hubspot_webhook'),
    path('start/', views.start_hubspot_auth, name='start_hubspot_auth'),
]