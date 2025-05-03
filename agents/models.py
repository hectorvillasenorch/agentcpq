from django.db import models
from django.contrib.auth.models import User
class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=255, default="Untitled Session")
    created_at = models.DateTimeField(auto_now_add=True)

class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, related_name="messages", on_delete=models.CASCADE)
    sender = models.CharField(max_length=10)  # 'user' or 'agent'
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)