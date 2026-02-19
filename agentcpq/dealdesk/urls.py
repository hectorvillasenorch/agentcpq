from django.urls import path

from . import views


urlpatterns = [
    path("review", views.review_deal_packet, name="dealdesk_review"),
    path("packets/<int:packet_id>", views.get_deal_packet, name="dealdesk_get_packet"),
    path("packets/<int:packet_id>/status", views.get_deal_packet_status, name="dealdesk_get_status"),
    path("packets/<int:packet_id>/audit", views.get_deal_packet_audit, name="dealdesk_get_audit"),
    path("packets/<int:packet_id>/evaluate", views.evaluate_packet, name="dealdesk_evaluate_packet"),
    path("packets/<int:packet_id>/route", views.route_packet, name="dealdesk_route_packet"),
    path("packets/<int:packet_id>/events", views.record_packet_event, name="dealdesk_record_event"),
]
