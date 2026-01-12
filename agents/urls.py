from django.urls import path
from .views import chat_with_gpt, upload_quote_attachment, single_record_layout, list_record_layout, batch_schema, batch_map, log_agent_message

urlpatterns = [
    path("chat/", chat_with_gpt, name="chat_with_gpt"),
    path("upload-attachment/", upload_quote_attachment, name="upload_quote_attachment"),
    path("single-record-layout/", single_record_layout, name="single_record_layout"),
    path("list-record-layout/", list_record_layout, name="list_record_layout"),
    path("batch-schema/", batch_schema, name="batch_schema"),
    path("batch-map/", batch_map, name="batch_map"),
    path("log-message/", log_agent_message, name="log_agent_message"),
]
