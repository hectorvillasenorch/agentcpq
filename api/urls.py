from django.urls import path
from .views import receive_lead, orchestrate_v1, quote_action_v1

urlpatterns = [
    path("leads/", receive_lead, name="receive_lead"),
    path("orchestrator/", orchestrate_v1, name="orchestrate_v1"),
    path("quote/action/", quote_action_v1, name="quote_action_v1"),
]
