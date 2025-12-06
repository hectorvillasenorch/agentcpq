from django.urls import path
from .views import chat_with_gpt, upload_quote_attachment, single_record_layout

urlpatterns = [
    path("chat/", chat_with_gpt, name="chat_with_gpt"),
    path("upload-attachment/", upload_quote_attachment, name="upload_quote_attachment"),
    path("single-record-layout/", single_record_layout, name="single_record_layout"),
]
