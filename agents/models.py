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

class AgentPrompt(models.Model):
    AGENT_CHOICES = [
        ("admin_agent", "Admin Agent"),
        ("analytics_agent", "Analytics Agent"),
        ("bundles_agent", "Bundles Agent"),
        ("custom_object_agent", "Custom Object Agent"),
        ("product_agent", "Product Agent"),
        ("quote_agent", "Quote Agent"),
        ("action_trigger_agent", "Action Trigger Agent")
    ]

    METHOD_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("delete", "Delete"),
    ]

    agent_name = models.CharField(max_length=50, choices=AGENT_CHOICES)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    function = models.CharField(max_length=50, blank=True, null=True, help_text="The specific function of the LLM")
    system_instructions = models.TextField()
    system_rules = models.TextField()
    agent_message = models.TextField()
    agent_summary = models.TextField(blank=True, null=True)
    temperature = models.FloatField(default=0.8)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("agent_name", "method", "function")  # Evitar duplicados
        verbose_name = "Agent Prompt"
        verbose_name_plural = "Agent Prompts"

    def __str__(self):
        return f"{self.agent_name} - {self.method}"


class SingleRecordLayout(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="single_record_layouts")
    object_name = models.CharField(max_length=100)
    layout = models.JSONField(default=dict)  # { order: [], hidden: [] }
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "object_name")
        verbose_name = "Single Record Layout"
        verbose_name_plural = "Single Record Layouts"

    def __str__(self):
        return f"{self.user} - {self.object_name}"
