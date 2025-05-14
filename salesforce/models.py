from django.db import models

class SalesforceToken(models.Model):
    """Stores Salesforce session tokens."""
    user_id = models.CharField(max_length=255, unique=True, default="default")
    access_token = models.TextField()
    refresh_token = models.TextField(null=True, blank=True)
    instance_url = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    issued_at_raw = models.CharField(max_length=30, blank=True, null=True)  # raw from SF
    issued_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Salesforce Token ({self.updated_at})"