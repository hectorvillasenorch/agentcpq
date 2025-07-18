from django.urls import path
from .views import receive_lead

urlpatterns = [
    path("leads/", receive_lead, name="receive_lead"),
]