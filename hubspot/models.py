from django.db import models
class HubspotToken(models.Model):
    """Stores HubSpot OAuth tokens."""
    user_id = models.CharField(max_length=255, unique=True, default="default")

    access_token = models.TextField()
    refresh_token = models.TextField(null=True, blank=True)

    expires_in = models.IntegerField(blank=True, null=True)  # seconds until expiry
    expires_at = models.DateTimeField(blank=True, null=True)

    token_type = models.CharField(max_length=50, blank=True, null=True)
    scope = models.TextField(blank=True, null=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"HubSpot Token for {self.user_id} (updated {self.updated_at})"# Create your models here.
