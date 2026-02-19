from django.urls import include, path
from .views import receive_lead, orchestrate_v1

urlpatterns = [
    path("leads/", receive_lead, name="receive_lead"),
    path("orchestrator/", orchestrate_v1, name="orchestrate_v1"),
    path("dealdesk/", include("agentcpq.dealdesk.urls")),
]
