import uuid

from django.conf import settings
from django.db import models


def upload_path(instance, filename):
    # The user's filename is only a label; on disk the file gets a random name
    # inside a per-user folder, so names can never collide or traverse paths.
    return f"user_{instance.owner_id}/{uuid.uuid4().hex}.pdf"


class Document(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to=upload_path)
    content_hash = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)
    pages = models.PositiveIntegerField(null=True, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            # the same bytes twice, or the same filename twice, is a conflict for one user
            models.UniqueConstraint(fields=["owner", "content_hash"], name="uniq_owner_content"),
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"
