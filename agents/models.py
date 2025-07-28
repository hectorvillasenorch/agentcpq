from django.db import models
from django.contrib.auth.models import User
import uuid

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
    hiddenMessage = models.BooleanField(default=False)


class SessionState(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    agent_name = models.CharField(max_length=100)
    intent = models.CharField(max_length=100)
    session_id = models.CharField(max_length=100)
    data = models.JSONField(default=list)  # [{user_message, agent_response, extracted_data}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session {self.session_id} for {self.user.username} with {self.agent_name}. Data: {self.data}"