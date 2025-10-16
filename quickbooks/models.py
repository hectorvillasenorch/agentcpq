from django.db import models
from django.utils import timezone


class QuickbooksToken(models.Model):
    """Stores OAuth credentials required to call the QuickBooks Online API."""

    user_id = models.CharField(
        max_length=100,
        default="default",
        unique=True,
        help_text="Identifier used to scope the stored credentials."
    )
    realm_id = models.CharField(
        max_length=100,
        help_text="QuickBooks company (realm) identifier."
    )
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_type = models.CharField(max_length=30, default="bearer")
    expires_at = models.DateTimeField(blank=True, null=True)
    refresh_token_expires_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "QuickBooks Token"
        verbose_name_plural = "QuickBooks Tokens"

    def __str__(self):
        return f"QuickBooks token for {self.user_id}"

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() >= self.expires_at)

